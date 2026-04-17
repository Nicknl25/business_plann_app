param(
  [string]$WorkbookPath = "C:\dev\Copy of Data Model using Planet Scale.xlsx",
  [string]$SourceSheetName = "Sheet3",
  [string]$SourceRangeName = "finmo_source_range",
  [string]$QueryName = "LatestFinmoExtract",
  [string]$OutputSheetName = "Latest Finmo Extract",
  [string]$OutputTableName = "tblLatestFinmoExtract",
  [switch]$QueryOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Remove-WorksheetIfExists {
  param(
    [Parameter(Mandatory = $true)] $Workbook,
    [Parameter(Mandatory = $true)] [string]$SheetName
  )

  foreach ($ws in $Workbook.Worksheets) {
    if ([string]$ws.Name -eq $SheetName) {
      $ws.Delete()
      break
    }
  }
}

if (-not (Test-Path -LiteralPath $WorkbookPath)) {
  throw "Workbook not found: $WorkbookPath"
}

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false

try {
  $workbook = $excel.Workbooks.Open($WorkbookPath)
  $sourceSheet = $workbook.Worksheets.Item($SourceSheetName)
  $sourceAddress = $sourceSheet.UsedRange.Address($true, $true)
  $sourceRefersTo = "='" + $SourceSheetName.Replace("'", "''") + "'!" + $sourceAddress

  foreach ($name in $workbook.Names) {
    if ([string]$name.Name -eq $SourceRangeName) {
      $name.Delete()
      break
    }
  }
  $null = $workbook.Names.Add($SourceRangeName, $sourceRefersTo)

  try {
    $existingQuery = $workbook.Queries.Item($QueryName)
    if ($existingQuery) {
      $existingQuery.Delete()
    }
  }
  catch {}

  $mCode = @"
let
    Source = Excel.CurrentWorkbook(){[Name="$SourceRangeName"]}[Content],
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    FilteredRows = Table.SelectRows(PromotedHeaders, each [draft_id] <> null and Text.Trim(Text.From([draft_id])) <> ""),
    LatestRow = Table.FirstN(FilteredRows, 1),
    BaseRecord = if Table.RowCount(LatestRow) = 0 then error "No draft rows found." else LatestRow{0},
    FinmoJson = Json.Document(Text.ToBinary(Text.From(BaseRecord[finmo_json]))),
    Periods = try FinmoJson[periods] otherwise {},
    PeriodTable = Table.FromRecords(
        List.Transform(
            List.Positions(Periods),
            each [
                quarter_index = _ + 1,
                period_year = try Number.From(Periods{_}[year]) otherwise null,
                period_quarter = try Number.From(Periods{_}[quarter]) otherwise null,
                period_date = try Text.From(Periods{_}[date]) otherwise null
            ]
        )
    ),
    ExpandStatement = (statementName as text, rows as list) as table =>
        let
            AsRecords =
                List.Combine(
                    List.Transform(
                        List.Positions(rows),
                        (rowPos) =>
                            let
                                rowRec = rows{rowPos},
                                label = try Text.From(rowRec[label]) otherwise null,
                                values = try rowRec[values] otherwise {},
                                valueRecords =
                                    List.Transform(
                                        List.Positions(values),
                                        (valuePos) => [
                                            created_at = try Text.From(BaseRecord[created_at]) otherwise null,
                                            draft_id = try Text.From(BaseRecord[draft_id]) otherwise null,
                                            business_name = try Text.From(BaseRecord[business_name]) otherwise null,
                                            statement = statementName,
                                            line_item = label,
                                            line_order = rowPos + 1,
                                            quarter_index = valuePos + 1,
                                            value = try Number.From(values{valuePos}) otherwise null
                                        ]
                                    )
                            in
                                valueRecords
                    )
                ),
            AsTable =
                if List.Count(AsRecords) = 0 then
                    #table(
                        type table [
                            created_at=nullable text,
                            draft_id=nullable text,
                            business_name=nullable text,
                            statement=nullable text,
                            line_item=nullable text,
                            line_order=nullable number,
                            quarter_index=nullable number,
                            value=nullable number
                        ],
                        {}
                    )
                else
                    Table.FromRecords(AsRecords)
        in
            AsTable,
    PLTable = ExpandStatement("P&L", try FinmoJson[pl] otherwise {}),
    BalanceTable = ExpandStatement("Balance Sheet", try FinmoJson[balance_sheet] otherwise {}),
    CashFlowTable = ExpandStatement("Cash Flow", try FinmoJson[cash_flow] otherwise {}),
    Combined = Table.Combine({PLTable, BalanceTable, CashFlowTable}),
    JoinedPeriods = Table.NestedJoin(Combined, {"quarter_index"}, PeriodTable, {"quarter_index"}, "period", JoinKind.LeftOuter),
    ExpandedPeriods = Table.ExpandTableColumn(JoinedPeriods, "period", {"period_year", "period_quarter", "period_date"}, {"period_year", "period_quarter", "period_date"}),
    Reordered = Table.ReorderColumns(ExpandedPeriods, {"created_at", "draft_id", "business_name", "statement", "line_item", "line_order", "quarter_index", "period_year", "period_quarter", "period_date", "value"})
in
    Reordered
"@

  $null = $workbook.Queries.Add($QueryName, $mCode)

  if (-not $QueryOnly) {
    Remove-WorksheetIfExists -Workbook $workbook -SheetName $OutputSheetName
    $outputSheet = $workbook.Worksheets.Add()
    $outputSheet.Name = $OutputSheetName

    $connection = "OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=`$Workbook$;Location=$QueryName;Extended Properties=`"`""
    $listObject = $outputSheet.ListObjects.Add(0, $connection, $null, 1, $outputSheet.Range("A1"))
    $listObject.Name = $OutputTableName
    $listObject.TableStyle = "TableStyleMedium2"
    $queryTable = $listObject.QueryTable
    $queryTable.CommandType = 2
    $queryTable.CommandText = "SELECT * FROM [$QueryName]"
    $queryTable.RowNumbers = $false
    $queryTable.FillAdjacentFormulas = $false
    $queryTable.PreserveFormatting = $true
    $queryTable.RefreshOnFileOpen = $false
    $queryTable.BackgroundQuery = $false
    $queryTable.RefreshStyle = 1
    $queryTable.AdjustColumnWidth = $true
    $queryTable.Refresh($false) | Out-Null

    $outputSheet.Cells.Item(1, 1).Select() | Out-Null
    $outputSheet.Columns("A:K").AutoFit() | Out-Null
  }

  $workbook.Save()
  Write-Output "Updated workbook: $WorkbookPath"
  Write-Output "Added Power Query: $QueryName"
  if ($QueryOnly) {
    Write-Output "Query only mode: no output sheet was created."
  } else {
    Write-Output "Added output sheet: $OutputSheetName"
  }
}
finally {
  if ($workbook) { $workbook.Close($true) }
  $excel.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null
}
