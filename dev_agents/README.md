# Dev Agents

This folder is intentionally **not part of the production app**.

It is a dev-only helper system for iterating on planning failures, especially the cash-path problem. It watches a run, gathers artifacts, diagnoses the failure, audits prompt risk, checks feasibility, proposes or applies fixes, reruns, compares results, and stops after a bounded number of iterations.

The agents now also read permanent guidance files before they reason about fixes:

- `dev_agents/PLAYBOOK.md`
- `dev_agents/CRITICAL_CONTEXT.md`
- `dev_agents/APP_MAP.md`
- `dev_agents/EVAL_RULES.md`
- `dev_agents/LEARNINGS.md`

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
  --command-file "dev_agents/commands/med_spa_one_product.ps1" `
  --max-iterations 5
```

For your current med-spa scenario, the repo already includes:

- `dev_agents/commands/med_spa_one_product.ps1`

By default the helper now:

- auto-applies fixes
- applies high-risk fixes too
- keeps iterating until it solves or reaches the iteration cap
- prioritizes root-cause fixes over bandaids
- reads persistent learnings from `dev_agents/LEARNINGS.md`
- logs every change and decision path under `dev_agents/runs/<timestamp>/`

Important:

- `dev_agents/LEARNINGS.md` is helper-maintained
- the helper appends structured learnings after each run
- learnings are written conservatively with verdict, confidence, and scope so single-case conclusions do not become overconfident doctrine

The optional flags `--apply-fixes` and `--allow-high-risk-fixes` are now effectively compatibility flags. The helper behaves as if both are on.

Root-cause invariant:

- when diagnosis points to upstream causes like prompt leakage, cash bands, capital allocation, or an overpowered operating engine, the fixer targets those first
- it does not reach for solver tuning as a default bandaid while those upstream causes are still present
- it uses the playbook/app-map/evaluation rules as persistent product context when proposing broader code changes

## Auto-Apply Scope

The fixer is no longer limited to the old four-file allowlist. It can patch any file inside the repo root, as long as the proposed target path stays inside the repository.

Current built-in fix categories still include:

- prompt modifications
- AI-facing payload sanitization
- cash-feasibility guidance strengthening
- capital-allocation deployment strengthening
- limited solver tuning

Every proposed and applied change is logged in the session output.

## Safety / Autonomy Behavior

- every applied iteration creates a checkpoint before changing files
- the main loop no longer stops early for low confidence, no-improvement streaks, or high-risk review
- the practical stop conditions are:
  - solver success
  - max iterations reached
- you can still manually reset to git if you dislike the outcome, which is why this folder is kept separate from the production runtime

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
