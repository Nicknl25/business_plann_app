# Dev Agents

This folder is intentionally **not part of the production app**.

It is a dev-only helper system for iterating on planning failures, especially the cash-path problem. It watches a run, gathers artifacts, diagnoses the failure, audits prompt risk, checks feasibility, proposes or applies controlled fixes, reruns, compares results, and stops after a bounded number of iterations.

## Agents

- `OrchestratorAgent`
- `DiagnoserAgent`
- `PromptAuditorAgent`
- `FeasibilityAgent`
- `FixerAgent`
- `RegressionAgent`

## How To Start It

From repo root:

```powershell
$env:PYTHONPATH = "python"
.\.venv\Scripts\python.exe -m dev_agents.cli `
  --command "& '.\.venv\Scripts\python.exe' 'Test Files\run_live_args_intake_1_product.py'" `
  --max-iterations 3
```

If you want it to auto-apply supported prompt fixes between iterations:

```powershell
$env:PYTHONPATH = "python"
.\.venv\Scripts\python.exe -m dev_agents.cli `
  --command "& '.\.venv\Scripts\python.exe' 'Test Files\run_live_args_intake_1_product.py'" `
  --max-iterations 3 `
  --apply-fixes
```

If you want it to apply the broader high-risk fixes too:

```powershell
$env:PYTHONPATH = "python"
.\.venv\Scripts\python.exe -m dev_agents.cli `
  --command "& '.\.venv\Scripts\python.exe' 'Test Files\run_live_args_intake_1_product.py'" `
  --max-iterations 3 `
  --apply-fixes `
  --allow-high-risk-fixes
```

## Auto-Apply Scope

When `--apply-fixes` is used, the fixer is allowed to patch only this bounded allowlist:

- `python/client_intake_and_finmo/quarter_grid.py`
- `python/client_intake_and_finmo/cash_contract_baby_ai.py`
- `python/client_intake_and_finmo/capital_allocation_baby_ai.py`
- `python/financial_model_engine/solver.py`

Current supported auto-fix categories:

- prompt modifications
- AI-facing payload sanitization
- cash-feasibility guidance strengthening
- capital-allocation deployment strengthening
- limited solver tuning

Every proposed and applied change is logged in the session output.

## Safety / Autonomy Behavior

- auto-fixes are limited to the allowlist above
- every applied iteration creates a checkpoint before changing files
- if a later iteration regresses after an applied fix, the helper restores the previous checkpoint and escalates
- if diagnosis confidence falls below the configured threshold, the helper escalates
- if there is no improvement for two consecutive iterations, the helper escalates
- high-risk changes are surfaced but not auto-applied
- unless you explicitly pass `--allow-high-risk-fixes`

## Outputs

Each session writes a separate folder under:

- `dev_agents/runs/<timestamp>/`

Per iteration it writes:

- `command_result.json`
- `artifact_bundle.json`
- `diagnosis.json`
- `prompt_audit.json`
- `feasibility.json`
- `fixer.json`
- `regression.json`
- `decision.json`
- `summary.md`

And at the session root:

- `final_report.json`
- `final_report.md`
