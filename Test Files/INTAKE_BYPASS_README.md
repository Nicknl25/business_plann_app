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

## Excel format

- One **sheet per scenario**. Sheets whose name starts with `_` are ignored
  (the `_README` sheet documents the format in-workbook).
- **Column A** = field name, **Column B** = value.
- Rows whose field starts with `#` are comments and ignored.
- Required field: `baseline` (name of a snapshot in `intake_bypass_baselines/`).
- Any other field is an **override**; a blank cell means "inherit the baseline".
- An unknown field name fails loudly so typos are caught.

### Supported override fields

- **Financial scalars** (`financials_json`): `cash_on_hand`, `ar_balance`,
  `ap_balance`, `inventory_balance`, `current_capex`, `initial_assets`,
  `initial_lease`, `initial_equity`, `total_debt_outstanding`,
  `annual_interest_payment`, `annual_principal_payment`,
  `other_monthly_debt_payments`, `monthly_rent_expense`,
  `other_operating_expense`, `owner_compensation`, `current_payroll`,
  `payroll_total_year1`, `current_num_employees`, `current_cogs`,
  `current_revenue`, `cogs_percent_of_revenue` (accepts `29%` or `0.29`).
- **Shape-affecting** (`operating_model_json` top-level + every product, and
  `financials_year1_json` products): `unit_price`, `units_per_week_capacity`,
  `utilization_rate`. The post-intake solver re-derives revenue from these.
- **Descriptors** (`operating_model_json`): `naics`, `business_stage`.
- **Flat draft columns**: `business_name`, `business_start_date`,
  `business_address`, `address_street`, `address_city`, `address_state`,
  `address_zip`, `address_country`.

Numbers may be plain (`20000`), separated (`$20,000`), or percents (`29%`).

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
