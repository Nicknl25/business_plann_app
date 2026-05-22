# Intake Bypass Runner (P3.33 Phase 1)

Exercise the **post-intake** pipeline without re-running the GPT intake
conversation. Built so the post-intake architecture can be tested quickly and
repeatably, including deliberately challenging scenarios (under-capitalized
restaurant, airline with $0 capex, service business with no payroll, ...).

This is a **test harness only**. Intake remains unchanged for real users.

## Why "baseline + overrides" (the key design decision)

The literal Phase 1 directive described an Excel of raw intake answers
(column A = question, column B = answer) inserted directly into SQL, skipping
GPT. Investigation showed that **cannot work**: post-intake does not consume
raw answers. It consumes the *structured JSON* the intake GPT consultants
synthesize during the conversation — `operating_model_json`,
`target_market_json`, `people_json`, `financials_json`,
`financials_year1_json`, etc. There is no deterministic "raw answers →
structured JSON" builder; that synthesis is the GPT conversation.

So a raw-Q&A Excel has no faithful path into the tables post-intake reads.
The chosen model instead is:

- **Baseline** — the structured intake output captured once from a real,
  intake-complete draft. Reusing it guarantees the JSON is shaped exactly as
  post-intake expects.
- **Overrides** — scalar values (cash, capex, payroll, price, NAICS, ...) the
  user edits per scenario. The runner overlays them onto a copy of the
  baseline. Stress scenarios are authored by changing numbers only.

This is fully GPT-free and fast. Its one limit: a genuinely new *business
shape* needs its own captured baseline first (cheap — see below). The repo's
existing drafts already cover bakery (Sunny Glaze), airline (Skyward),
logistics (SwiftCargo/Pinnacle/Freedom), home health (CareFirst), etc.

## Files

| File | Purpose |
|------|---------|
| `run_intake_bypass.py` | Main runner: Excel → overrides → SQL → trigger `system-run`. |
| `capture_intake_baseline.py` | Capture a baseline snapshot from a real draft in MySQL. |
| `intake_bypass_common.py` | Shared DB access + the override → JSON-path mapping. |
| `make_intake_bypass_scenarios_xlsx.py` | Regenerates the sample workbook. |
| `intake_bypass_scenarios.xlsx` | Sample workbook (one sheet per scenario). |
| `intake_bypass_baselines/*.json` | Captured baseline snapshots (editable by hand). |

## Quick start

```bash
# 1. (once per business shape) capture a baseline from a finished draft
python "Test Files/capture_intake_baseline.py" --list                       # see candidates
python "Test Files/capture_intake_baseline.py" --draft-id <id> --name my_biz

# 2. edit Test Files/intake_bypass_scenarios.xlsx (see the _README sheet)

# 3a. offline check: build the draft + write the intake tables, no API/GPT
python "Test Files/run_intake_bypass.py" --dry-run

# 3b. full run: also trigger the post-intake pipeline (API must be running)
python context/run_api_5050_single.py        # in another terminal
python "Test Files/run_intake_bypass.py" --scenario Sunny_Glaze_Donuts
```

## Excel format — EXHAUSTIVE, pre-filled

Each non-underscore sheet is one scenario. **Every leaf of the baseline appears
as a pre-filled row** addressed by a dotted path. To author a scenario you just
edit the cells you want to change.

- **Column A** = field path; **Column B** = value.
- A row takes effect only when its value **differs from the baseline** at that
  path, so an unedited sheet reproduces the baseline exactly. Blank = inherit.
  The literal `(null)` sets a field to null. Rows starting with `#` (the
  per-section headers) are ignored.
- Required field: `baseline` (snapshot in `intake_bypass_baselines/`).
- Path syntax:
  - `draft.<col>` — a flat draft column (e.g. `draft.business_name`,
    `draft.address_city`).
  - `<payload>.<dotted.path>` — a leaf inside one of the structured payloads:
    `operating_model_json`, `target_market_json`, `people_json`,
    `financials_json`, `financials_year1_json`, `marketing_model_json`,
    `fulfillment_json`.
  - List elements use `[i]`, e.g.
    `operating_model_json.lob_models[0].products[0].unit_price`.
- Numbers may be plain (`20000`), separated (`$20,000`), or percent (`29%`).
- A target whose root isn't a known payload or `draft.` fails loudly so typos
  surface immediately.

### Denormalization — edit consistently

`unit_price`, `units_per_week_capacity`, and `utilization_rate` appear in BOTH
`operating_model_json` (top-level **and** each product) **and**
`financials_year1_json` products. To change these coherently, edit every
occurrence. Each appears on its own row; nothing is hidden.

### Limitation — adding new array elements

Editing existing leaves is fully supported. To add a **new** array element
(e.g. a third product or an eighth person), either edit the baseline JSON in
`intake_bypass_baselines/` directly or capture a baseline that already has the
shape. For headcount scale, the right knobs are typically
`financials_json.current_num_employees` / `payroll_total_year1` — post-intake
authors the actual quarterly headcount grid.

### Regenerating the sheet

If you capture a new baseline, regenerate the workbook with:

```bash
python "Test Files/make_intake_bypass_scenarios_xlsx.py" \
       --baseline <name> --sheet <Scenario_Name>
```

## What the runner writes

It populates **`intake_consult_drafts`** (status `completed`, `active_focus`
`done`, all confirmation flags set, structured JSON columns filled). It then
calls `POST /api/intake-consult/system-run`, which is the exact path real
intake uses on completion; that trigger creates `planning_runs`,
`planning_run_checkpoints`, `planning_stage_events`, and
`post_intake_run_diagnostics`.

It deliberately does **not** write `intake_submissions`. Post-intake reads its
inputs from the draft, not from `intake_submissions`; the proven clone runner
(`run_persisted_system_run.py`) omits it too. Writing a hand-built submission
row would add NOT-NULL-column risk for no downstream benefit.

`--dry-run` mints the draft with a direct insert (no API needed) and stops
after writing/verifying the intake tables — useful for confirming a scenario
populates correctly before spending a full pipeline run.
