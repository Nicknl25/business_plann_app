# Client Statements Output Excel

Production workbook exporter for completed post-intake financial models.

The exporter reads a completed `intake_consult_drafts` row and writes one client-ready `.xlsx` workbook per run/client. The default local save location is:

`C:\dev\Cilient Plans`

The save name is intentionally client-clean:

`Business Name -- MM-DD-YYYY HH-MM-SS.xlsx`

## Workbook Contract

The workbook is formula-driven in the direction required for client delivery:

1. Schedule tabs hold source operating schedule logic.
2. `Model Inputs` links to those schedule tabs.
3. `FINMO` links to `Model Inputs` and in-sheet statement rows.
4. `Checks` ties workbook formulas back to persisted FINMO output.

## Sheets

- `Revenue Drivers`
- `Payroll Schedule`
- `Debt Schedule`
- `CapEx Depreciation`
- `Working Capital`
- `Cash Equity Schedule`
- `Model Inputs`
- `FINMO`
- `Checks`
- hidden `Audit Source`

## CLI

```powershell
.\.venv\Scripts\python.exe -B -m client_statements_output_excel.export_client_workbook --draft-id <draft_id>
```

The system-run handler also exports a workbook after successful completion and returns `client_workbook_path` in the JSON response.
