param(
  [string]$WorkbookPath = "C:\dev\Copy of Data Model using Planet Scale.xlsx",
  [string]$SourceSheetName = "Sheet3",
  [int]$LatestDataRow = 2,
  [string]$FlatSheetName = "Latest Finmo Flat",
  [string]$ViewSheetName = "Latest Finmo Statements"
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

function Format-CurrencyRange {
  param(
    [Parameter(Mandatory = $true)] $Range
  )

  $Range.NumberFormat = '_(* #,##0_);_(* (#,##0);_(* "-"_);_(@_)'
}

function Format-AmountText {
  param(
    [Parameter(Mandatory = $true)] [double]$Amount
  )

  if ([Math]::Abs($Amount) -lt 0.0000001) {
    return "-"
  }
  if ($Amount -lt 0) {
    return "(" + ([Math]::Abs($Amount)).ToString("#,##0") + ")"
  }
  return $Amount.ToString("#,##0")
}

function Build-YearTotals {
  param(
    [Parameter(Mandatory = $true)] [double[]]$QuarterValues,
    [Parameter(Mandatory = $true)] [bool]$UseYearEndValues
  )

  $totals = New-Object System.Collections.Generic.List[double]
  for ($yearIndex = 0; $yearIndex -lt 5; $yearIndex++) {
    $start = $yearIndex * 4
    if ($UseYearEndValues) {
      $endIndex = $start + 3
      if ($endIndex -lt $QuarterValues.Count) {
        [void]$totals.Add([double]$QuarterValues[$endIndex])
      } else {
        [void]$totals.Add(0.0)
      }
      continue
    }

    $sum = 0.0
    for ($i = $start; $i -lt [Math]::Min($start + 4, $QuarterValues.Count); $i++) {
      $sum += [double]$QuarterValues[$i]
    }
    [void]$totals.Add($sum)
  }
  return ,$totals.ToArray()
}

function Write-StatementBlock {
  param(
    [Parameter(Mandatory = $true)] $Worksheet,
    [Parameter(Mandatory = $true)] [int]$StartRow,
    [Parameter(Mandatory = $true)] [string]$Title,
    [Parameter(Mandatory = $true)] $Rows,
    [Parameter(Mandatory = $true)] [bool]$UseYearEndValues
  )

  $Worksheet.Cells.Item($StartRow, 1).Value2 = $Title
  $Worksheet.Cells.Item($StartRow, 1).Font.Bold = $true
  $Worksheet.Cells.Item($StartRow, 1).Font.Size = 14

  $headers = @("Line Item")
  for ($q = 1; $q -le 20; $q++) {
    $headers += "Q$q"
  }
  for ($y = 1; $y -le 5; $y++) {
    $headers += "Y$y"
  }
  for ($i = 0; $i -lt $headers.Count; $i++) {
    $Worksheet.Cells.Item($StartRow + 1, $i + 1).Value2 = $headers[$i]
  }
  $headerRange = $Worksheet.Range($Worksheet.Cells.Item($StartRow + 1, 1), $Worksheet.Cells.Item($StartRow + 1, $headers.Count))
  $headerRange.Font.Bold = $true
  $headerRange.Interior.Color = 15132390

  $currentRow = $StartRow + 2
  foreach ($entry in $Rows) {
    $label = [string]$entry.label
    $quarterValues = @()
    foreach ($value in @($entry.values)) {
      $quarterValues += [double]$value
    }
    $yearValues = Build-YearTotals -QuarterValues $quarterValues -UseYearEndValues:$UseYearEndValues
    $quarterValueTexts = @()
    foreach ($amount in $quarterValues) {
      $quarterValueTexts += (Format-AmountText -Amount ([double]$amount))
    }
    $yearValueTexts = @()
    foreach ($amount in $yearValues) {
      $yearValueTexts += (Format-AmountText -Amount ([double]$amount))
    }
    $rowValues = @($label) + $quarterValueTexts + $yearValueTexts
    for ($i = 0; $i -lt $rowValues.Count; $i++) {
      $Worksheet.Cells.Item($currentRow, $i + 1).Value2 = [string]$rowValues[$i]
    }
    $currentRow++
  }

  $Worksheet.Range($Worksheet.Cells.Item($StartRow + 2, 1), $Worksheet.Cells.Item($currentRow - 1, 1)).Font.Bold = $false

  return $currentRow + 1
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

  $createdAt = [string]$sourceSheet.Cells.Item($LatestDataRow, 1).Text
  $draftId = [string]$sourceSheet.Cells.Item($LatestDataRow, 2).Text
  $businessName = [string]$sourceSheet.Cells.Item($LatestDataRow, 3).Text
  $rawFinmo = [string]$sourceSheet.Cells.Item($LatestDataRow, 10).Value2

  if ([string]::IsNullOrWhiteSpace($rawFinmo)) {
    throw "finmo_json is blank at row $LatestDataRow on $SourceSheetName."
  }

  $finmo = $rawFinmo | ConvertFrom-Json
  $periods = @($finmo.periods)
  $plRows = @($finmo.pl)
  $balanceRows = @($finmo.balance_sheet)
  $cashRows = @($finmo.cash_flow)

  Remove-WorksheetIfExists -Workbook $workbook -SheetName $FlatSheetName
  Remove-WorksheetIfExists -Workbook $workbook -SheetName $ViewSheetName

  $flatSheet = $workbook.Worksheets.Add()
  $flatSheet.Name = $FlatSheetName
  $viewSheet = $workbook.Worksheets.Add()
  $viewSheet.Name = $ViewSheetName

  $flatHeaders = @(
    "DraftId",
    "BusinessName",
    "CreatedAt",
    "Statement",
    "Label",
    "PeriodKey",
    "ForecastYear",
    "CalendarYear",
    "Date",
    "Value",
    "StatementOrder",
    "LabelOrder",
    "PeriodOrder"
  )
  for ($i = 0; $i -lt $flatHeaders.Count; $i++) {
    $flatSheet.Cells.Item(1, $i + 1).Value2 = $flatHeaders[$i]
  }
  $flatSheet.Range("A1:M1").Font.Bold = $true
  $flatSheet.Range("A1:M1").Interior.Color = 15132390

  $statementSpecs = @(
    @{ Name = "P&L"; Rows = $plRows; Order = 1 },
    @{ Name = "Balance Sheet"; Rows = $balanceRows; Order = 2 },
    @{ Name = "Cash Flow"; Rows = $cashRows; Order = 3 }
  )

  $flatRow = 2
  foreach ($statementSpec in $statementSpecs) {
    $labelOrder = 1
    foreach ($statementRow in @($statementSpec['Rows'])) {
      $values = @($statementRow.values)
      for ($i = 0; $i -lt $values.Count; $i++) {
        $periodOrder = $i + 1
        $period = $null
        if ($periods.Count -gt $periodOrder) {
          $period = $periods[$periodOrder]
        }
        $calendarYear = $null
        $periodDate = ""
        if ($null -ne $period) {
          $calendarYear = [int][double]$period.year
          $periodDate = [string]$period.date
        }
        $rowValues = @(
          $draftId,
          $businessName,
          $createdAt,
          [string]$statementSpec['Name'],
          [string]$statementRow.label,
          "Q$periodOrder",
          [string]([int][Math]::Ceiling($periodOrder / 4.0)),
          $(if ($null -eq $calendarYear) { "" } else { [string]$calendarYear }),
          $periodDate,
          [double]$values[$i],
          [string]([int]$statementSpec['Order']),
          [string]([int]$labelOrder),
          [string]([int]$periodOrder)
        )
        for ($col = 0; $col -lt $rowValues.Count; $col++) {
          $flatSheet.Cells.Item($flatRow, $col + 1).Value2 = [string]$rowValues[$col]
        }
        $flatRow++
      }
      $labelOrder++
    }
  }

  $flatLastRow = $flatRow - 1
  $flatSheet.Columns("A:M").EntireColumn.AutoFit() | Out-Null

  $viewSheet.Cells.Item(1, 1).Value2 = "Latest Finmo Statement View"
  $viewSheet.Cells.Item(1, 1).Font.Bold = $true
  $viewSheet.Cells.Item(1, 1).Font.Size = 18
  $viewSheet.Cells.Item(2, 1).Value2 = "Business"
  $viewSheet.Cells.Item(2, 2).Value2 = $businessName
  $viewSheet.Cells.Item(3, 1).Value2 = "Draft ID"
  $viewSheet.Cells.Item(3, 2).Value2 = $draftId
  $viewSheet.Cells.Item(4, 1).Value2 = "Created At"
  $viewSheet.Cells.Item(4, 2).Value2 = $createdAt
  $viewSheet.Range("A2:A4").Font.Bold = $true

  $nextRow = 6
  $nextRow = Write-StatementBlock -Worksheet $viewSheet -StartRow $nextRow -Title "P&L" -Rows $plRows -UseYearEndValues:$false
  $nextRow = Write-StatementBlock -Worksheet $viewSheet -StartRow $nextRow -Title "Balance Sheet" -Rows $balanceRows -UseYearEndValues:$true
  $nextRow = Write-StatementBlock -Worksheet $viewSheet -StartRow $nextRow -Title "Cash Flow Statement" -Rows $cashRows -UseYearEndValues:$false

  $viewSheet.Cells.Item(5, 1).Value2 = "Source"
  $viewSheet.Cells.Item(5, 2).Value2 = "Latest row on Sheet3 (currently row $LatestDataRow)"
  $viewSheet.Range("A5").Font.Bold = $true
  $viewSheet.Columns("A:Z").EntireColumn.AutoFit() | Out-Null
  $viewSheet.Range("B8:Z8").Select() | Out-Null
  $excel.ActiveWindow.FreezePanes = $true

  $workbook.Save()
  Write-Output "Updated workbook: $WorkbookPath"
  Write-Output "Business: $businessName"
  Write-Output "Draft ID: $draftId"
  Write-Output "Added sheets: $FlatSheetName, $ViewSheetName"
}
finally {
  if ($workbook) { $workbook.Close($true) }
  $excel.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null
}
