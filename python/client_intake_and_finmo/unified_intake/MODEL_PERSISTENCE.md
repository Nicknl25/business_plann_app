# Unified Intake Model Persistence (Verification + Mapping)

This document describes what the code guarantees today for **chat-driven model capture**, **immediate SQL persistence**, **derived recompute**, and **audit logging** for the unified intake models.

## Where persistence happens

**Single write path (chat turn):**

- Intent router emits a patch of scoped keys like `pricing.unit_price` or `cogs.cost_per_unit`.
- `unified_intake.controller.post_intake_consult_handler` routes the patch to `unified_intake.draft_service.apply_chat_patch_and_persist`.
- `apply_chat_patch_and_persist`:
  - applies fact patches (business/ops/market/people/financials),
  - applies model driver patches via `unified_intake.model_engine.apply_company_driver_patch`,
  - recomputes derived values deterministically via `unified_intake.model_engine.recompute_*`,
  - writes everything immediately to SQL using `client_intake_and_finmo.intake_consult_draft.append_messages`.

## SQL tables & authoritative storage

### Primary table (during chat): `intake_consult_drafts`

Defined in `python/client_intake_and_finmo/intake_consult_draft.py:49`.

**Authoritative inputs**

- Model drivers and derived values live in JSON columns:
  - `pricing_model_json`
  - `marketing_model_json`
  - `revenue_model_json`
  - `headcount_model_json`
  - `fulfillment_model_json`
  - `ops_concept_model_json`
  - `milestones_model_json`
  - `cogs_model_json`
  - `gna_model_json`
- Ops facts (non-model-card) live in:
  - `operating_model_json` (LONGTEXT JSON)

**Derived numeric rollups (duplicated for query convenience)**

- `year1_revenue`
- `year1_marketing_spend`
- `year1_payroll`
- `year1_cogs`
- `year1_gna_total`

**Audit logs**

- `driver_events_json` + `driver_revision_nonce` (immutable-ish append-only event stream)
- `fact_revisions_json` + `fact_revision_nonce` (immutable-ish fact revision history)

### Submission table (post-submit mirror): `intake_submissions` (partial)

`python/client_intake_and_finmo/intake_submission.py` inserts a subset of known columns into `intake_submissions`.

Important gaps noted below: **COGS/G&A are not mirrored yet** (no `cogs_model_json`, `gna_model_json`, `year1_cogs`, `year1_gna_total` in the candidate insert list).

## Model card JSON shape

All model cards are normalized to the same structure:

- `{"lobs":[{"lob_key":"company_total","drivers":{...},"derived":{...}}, ...], "updated_at_ms": ..., "version": ...}`

All chat-driven writes currently target **`lob_key="company_total"`** (multi-LOB is scaffolding today).

For a driver named `X`, the canonical storage is:

- `...lobs[company_total].drivers.X.value`
- plus metadata: `unit`, `time_basis`, `rationale`, `updated_at_ms`

For a derived value named `Y`, the canonical storage is:

- `...lobs[company_total].derived.Y.value`
- plus metadata: `unit`, `time_basis`, `derivation`, `updated_at_ms`

## Model-by-model mapping

Notation:

- **model_card_key** is the logical path within the model JSON (company_total).
- **SQL column** is on `intake_consult_drafts` unless stated otherwise.
- **Event log** means an entry is appended to `driver_events_json` with `path="drivers.<field>"` (and `driver_revision_nonce` increments) whenever the driver value actually changes.

### Pricing

| model | driver | model_card_key | SQL column | notes |
|---|---|---|---|---|
| pricing | `unit_price` | `pricing_model_json.lobs[company_total].drivers.unit_price.value` | `intake_consult_drafts.pricing_model_json` | Captured via patch `pricing.unit_price`. Also mirrored to `pricing_model_json.unit_price` (root convenience key). |

**Cross-model sync**

- Ops → Pricing: `ensure_pricing_from_ops` runs inside `apply_chat_patch_and_persist` recompute block so `operating_model_json.unit_price` is projected into pricing the same turn.
- Pricing → Ops: `apply_company_driver_patch` mirrors `pricing.unit_price` into `operating_model_json.unit_price` the same turn.

### Marketing

| model | driver | model_card_key | SQL column | notes |
|---|---|---|---|---|
| marketing | `monthly_marketing_budget` | `marketing_model_json.lobs[company_total].drivers.monthly_marketing_budget.value` | `intake_consult_drafts.marketing_model_json` | Triggers derived `year1_marketing_spend`. |
| marketing | `primary_channels` | `marketing_model_json.lobs[company_total].drivers.primary_channels.value` | `intake_consult_drafts.marketing_model_json` | Stored, no deterministic math today. |
| marketing | *(any other driver)* | `marketing_model_json.lobs[company_total].drivers.<field>.value` | `intake_consult_drafts.marketing_model_json` | Stored as-is; unit/time_basis may be null unless explicitly set by model engine. |

**Derived**

| derived | model_card_key | SQL column | notes |
|---|---|---|---|
| `year1_marketing_spend` | `marketing_model_json.lobs[company_total].derived.year1_marketing_spend.value` | `intake_consult_drafts.year1_marketing_spend` | Computed as `monthly_marketing_budget × 12`. |

### Revenue

| model | driver | model_card_key | SQL column | notes |
|---|---|---|---|---|
| revenue | `units_per_week_capacity` | `revenue_model_json.lobs[company_total].drivers.units_per_week_capacity.value` | `intake_consult_drafts.revenue_model_json` | Unit derived from `operating_model_json.unit_name`. |
| revenue | `avg_units_per_week_year1` | `revenue_model_json.lobs[company_total].drivers.avg_units_per_week_year1.value` | `intake_consult_drafts.revenue_model_json` | Used directly or inferred from `starting_revenue`. |
| revenue | `utilization_rate` | `revenue_model_json.lobs[company_total].drivers.utilization_rate.value` | `intake_consult_drafts.revenue_model_json` | If set and capacity present, drives `avg_units_per_week_year1 = utilization_rate × capacity`. |
| revenue | `operating_weeks_per_year` | `revenue_model_json.lobs[company_total].drivers.operating_weeks_per_year.value` | `intake_consult_drafts.revenue_model_json` | Default 52 if missing. |
| revenue | `unit_price` | `revenue_model_json.lobs[company_total].drivers.unit_price.value` | `intake_consult_drafts.revenue_model_json` | If missing, falls back to `operating_model_json.unit_price`. |

**Derived**

| derived | model_card_key | SQL column | notes |
|---|---|---|---|
| `year1_revenue` | `revenue_model_json.lobs[company_total].derived.year1_revenue.value` | `intake_consult_drafts.year1_revenue` | `avg_units_per_week_year1 × unit_price × operating_weeks_per_year`. |
| `weekly_revenue` | `revenue_model_json.lobs[company_total].derived.weekly_revenue.value` | *(JSON only)* | `avg_units_per_week_year1 × unit_price`. |

**Ops coupling**

`recompute_revenue_company_total` keeps these Ops facts in sync when it can:

- `operating_model_json.units_per_week_capacity`
- `operating_model_json.unit_price`
- `operating_model_json.starting_revenue`

Revenue recompute is triggered when:

- any revenue driver changes, OR
- any of these Ops inputs change: `units_per_week_capacity`, `unit_price`, `unit_name`, `starting_revenue`.

### Headcount

| model | driver | model_card_key | SQL column | notes |
|---|---|---|---|---|
| headcount | `roles` | `headcount_model_json.lobs[company_total].drivers.roles.value` | `intake_consult_drafts.headcount_model_json` | List of role dicts; recompute reads `employee_count`/`count`, `hourly_rate`/`hourly_rate_override`, `hours_per_week`, `weeks_per_year`. |
| headcount | *(any other driver)* | `headcount_model_json.lobs[company_total].drivers.<field>.value` | `intake_consult_drafts.headcount_model_json` | Stored as-is; not used in deterministic payroll math unless `roles`. |

**Derived**

| derived | model_card_key | SQL column | notes |
|---|---|---|---|
| `year1_payroll` | `headcount_model_json.lobs[company_total].derived.year1_payroll.value` | `intake_consult_drafts.year1_payroll` | `sum(employee_count × hourly_rate × hours_per_week × weeks_per_year)` with defaults `40×52` if missing. |

### Fulfillment

| model | driver | model_card_key | SQL column | notes |
|---|---|---|---|---|
| fulfillment | `fulfillment_model` | `fulfillment_model_json.lobs[company_total].drivers.fulfillment_model.value` | `intake_consult_drafts.fulfillment_model_json` | Required by Ops completeness gating. |
| fulfillment | `who_fulfills` | `fulfillment_model_json.lobs[company_total].drivers.who_fulfills.value` | `intake_consult_drafts.fulfillment_model_json` | Required by Ops completeness gating. |
| fulfillment | `lead_time` | `fulfillment_model_json.lobs[company_total].drivers.lead_time.value` | `intake_consult_drafts.fulfillment_model_json` | Required by Ops completeness gating. |
| fulfillment | *(any other driver)* | `fulfillment_model_json.lobs[company_total].drivers.<field>.value` | `intake_consult_drafts.fulfillment_model_json` | Stored as-is. |

### Ops concept

| model | driver | model_card_key | SQL column | notes |
|---|---|---|---|---|
| ops_concept | `operating_unit` | `ops_concept_model_json.lobs[company_total].drivers.operating_unit.value` | `intake_consult_drafts.ops_concept_model_json` | Required by Ops completeness gating. |
| ops_concept | `primary_constraint` | `ops_concept_model_json.lobs[company_total].drivers.primary_constraint.value` | `intake_consult_drafts.ops_concept_model_json` | Required by Ops completeness gating. |
| ops_concept | `process_overview` | `ops_concept_model_json.lobs[company_total].drivers.process_overview.value` | `intake_consult_drafts.ops_concept_model_json` | Required by Ops completeness gating. |
| ops_concept | *(any other driver)* | `ops_concept_model_json.lobs[company_total].drivers.<field>.value` | `intake_consult_drafts.ops_concept_model_json` | Stored as-is. |

### Milestones

| model | driver | model_card_key | SQL column | notes |
|---|---|---|---|---|
| milestones | `milestones` | `milestones_model_json.lobs[company_total].drivers.milestones.value` | `intake_consult_drafts.milestones_model_json` | Expected to be a list of milestone dicts (e.g., `{title, description, target_period}`). Required by Ops completeness gating. |
| milestones | *(any other driver)* | `milestones_model_json.lobs[company_total].drivers.<field>.value` | `intake_consult_drafts.milestones_model_json` | Stored as-is. |

### COGS

| model | driver | model_card_key | SQL column | notes |
|---|---|---|---|---|
| cogs | `cost_per_unit` | `cogs_model_json.lobs[company_total].drivers.cost_per_unit.value` | `intake_consult_drafts.cogs_model_json` | USD/per_unit; used directly for year1_cogs if present. |
| cogs | `materials_cost_per_unit` | `cogs_model_json.lobs[company_total].drivers.materials_cost_per_unit.value` | `intake_consult_drafts.cogs_model_json` | Optional; summed into cost_per_unit if `cost_per_unit` missing. |
| cogs | `direct_fulfillment_cost_per_unit` | `cogs_model_json.lobs[company_total].drivers.direct_fulfillment_cost_per_unit.value` | `intake_consult_drafts.cogs_model_json` | Optional; summed into cost_per_unit if `cost_per_unit` missing. |
| cogs | `other_variable_cost_per_unit` | `cogs_model_json.lobs[company_total].drivers.other_variable_cost_per_unit.value` | `intake_consult_drafts.cogs_model_json` | Optional; summed into cost_per_unit if `cost_per_unit` missing. |
| cogs | `cogs_percent_of_revenue` | `cogs_model_json.lobs[company_total].drivers.cogs_percent_of_revenue.value` | `intake_consult_drafts.cogs_model_json` | If provided and `year1_revenue` known, used for year1_cogs. Accepts 0–1 or 0–100 input. |

**Derived**

| derived | model_card_key | SQL column | notes |
|---|---|---|---|
| `year1_cogs` | `cogs_model_json.lobs[company_total].derived.year1_cogs.value` | `intake_consult_drafts.year1_cogs` | Based on either cost/unit × units × weeks, or % × year1_revenue. |

**Recompute trigger**

COGS recompute is triggered when either:

- any COGS driver changes, OR
- revenue inputs change (including Ops `unit_price` / `starting_revenue` fallback path).

### G&A (Operating overhead)

| model | driver | model_card_key | SQL column | notes |
|---|---|---|---|---|
| gna | `monthly_rent_expense` | `gna_model_json.lobs[company_total].drivers.monthly_rent_expense.value` | `intake_consult_drafts.gna_model_json` | USD/month |
| gna | `other_operating_expense` | `gna_model_json.lobs[company_total].drivers.other_operating_expense.value` | `intake_consult_drafts.gna_model_json` | USD/month |
| gna | `other_monthly_debt_payments` | `gna_model_json.lobs[company_total].drivers.other_monthly_debt_payments.value` | `intake_consult_drafts.gna_model_json` | USD/month |
| gna | `monthly_software_expense` | `gna_model_json.lobs[company_total].drivers.monthly_software_expense.value` | `intake_consult_drafts.gna_model_json` | USD/month |
| gna | `monthly_insurance_expense` | `gna_model_json.lobs[company_total].drivers.monthly_insurance_expense.value` | `intake_consult_drafts.gna_model_json` | USD/month |
| gna | `monthly_utilities_expense` | `gna_model_json.lobs[company_total].drivers.monthly_utilities_expense.value` | `intake_consult_drafts.gna_model_json` | USD/month |
| gna | `monthly_admin_expense` | `gna_model_json.lobs[company_total].drivers.monthly_admin_expense.value` | `intake_consult_drafts.gna_model_json` | USD/month |
| gna | *(any other monthly driver)* | `gna_model_json.lobs[company_total].drivers.<field>.value` | `intake_consult_drafts.gna_model_json` | If its stored `time_basis` is `"month"`, it is included in year1_gna_total (extensible without code/schema churn). |

**Derived**

| derived | model_card_key | SQL column | notes |
|---|---|---|---|
| `year1_gna_total` | `gna_model_json.lobs[company_total].derived.year1_gna_total.value` | `intake_consult_drafts.year1_gna_total` | Sum(monthly drivers) × 12; derivation lists included components. |

## Update semantics (guarantees)

### Mid-chat updates

- Any driver can be changed mid-chat by emitting another patch with the same `model.field` key.
- Storage is “last write wins” in the model JSON (`drivers.<field>.value` overwrites).

### Deterministic recompute

- Marketing, Headcount, Revenue, COGS, and G&A derived values are recomputed deterministically in `apply_chat_patch_and_persist` every time their inputs change.
- Derived values are persisted both:
  - in the model JSON (`derived.*.value`), and
  - in the corresponding `year1_*` numeric columns when applicable.

### Versioning / audit

- Model driver updates that actually change a value append an event to:
  - `intake_consult_drafts.driver_events_json` (bounded to last 500), and bump `driver_revision_nonce`.
- Fact edits append revisions to:
  - `intake_consult_drafts.fact_revisions_json` (bounded to last 200), and bump `fact_revision_nonce`.

## Gaps / TODOs (current)

- **`intake_submissions` does not mirror COGS/G&A yet**:
  - missing insert of `cogs_model_json`, `gna_model_json`, `year1_cogs`, `year1_gna_total` in `python/client_intake_and_finmo/intake_submission.py`.
- **Multi-LOB is scaffolding only**:
  - Chat patch application targets `company_total` only; per-LOB drivers aren’t supported yet.
- **Legacy summary keys still exist elsewhere**:
  - Unified intake flow drops them, but other modules still reference `*_summary` (e.g., legacy consultants and `intake_consult_draft.append_messages` strips them defensively).
