"""THE ASSIGNMENT — what each section may know, as the control (2026-09-03).

Nick's ruling, verbatim in spirit: "The fact catalogue becomes the control
mechanism. Every fact gets a row: the key, and which section or sections own
it. A fact assigned to no section reaches no brief. A section receives
exactly the facts assigned to it and nothing else. A fact assigned to nothing
is invisible - if something we want goes missing, the fix is to ASSIGN it,
not to widen the room."

Why this exists: tonight the mini-plan problem vanished when the material
left the room - with no rule and no instruction. It worked because it was
IMPOSSIBLE, not because it was forbidden. This module makes that systematic.

Same discipline as rules.py + rule_lookup.py: this file is the single door;
`writing_phase_assignment_lookup` is its serving copy, seeded from here and
verified field by field; the writing phase REFUSES to run on disagreement
(the payroll-contract lesson - a seeder that never ran left a row inert
through four live reruns).

Sharing is BY ASSIGNMENT: the five-year survival rate belongs to The
Business and to Market, deliberately, as two rows' worth of one key.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Tuple

ASSIGNMENT_VERSION = "assignments_v1"
TABLE_NAME = "writing_phase_assignment_lookup"

# Facts every section may know: the business must be nameable anywhere.
UNIVERSAL_FACTS: Tuple[str, ...] = ("entity.business_name", "entity.state_name")

# BUILT BUT DELIBERATELY INVISIBLE (each with its ruling):
#   entity.naics_title       - the classification is machinery (2026-09-03);
#                              the client's account names the trade.
#   industry.bds_scope_label - the statistical population lives in the NOTE
#                              basis, never the sentence (2026-09-03).
DELIBERATELY_UNASSIGNED: Tuple[str, ...] = (
  "entity.naics_title", "industry.bds_scope_label",
)

# ---------------------------------------------------------------------------
# THE ASSIGNMENT, by section - the readable, auditable form. A key may appear
# under several sections (sharing by assignment). Everything the builders
# produce is either here, in UNIVERSAL_FACTS, or in DELIBERATELY_UNASSIGNED -
# the audit script prints anything that is none of the three.
# ---------------------------------------------------------------------------
SECTION_FACTS: Dict[str, Tuple[str, ...]] = {
  # The Business explains the business: identity, offering count, tenure,
  # one scale anchor. Nothing else is in the room (Nick 2026-09-03).
  "the_business": (
    "entity.legal_entity", "entity.years_operating", "entity.founded_year",
    "entity.founded_month_year", "entity.city_state",
    "entity.stated_current_revenue", "entity.stated_employees",
    "entity.stated_certifications", "entity.coverage_zip",
    "annual.lob_count",
    "industry.first_year_exit_rate", "industry.five_year_survival_rate",
  ),
  "market_and_industry": (
    "market.competition_geo_label", "market.industry_scope_label",
    "market.establishments", "market.residents_per_establishment",
    "market.emp_per_establishment", "market.payroll_per_establishment",
    "market.households_per_establishment", "market.b2b_target_establishments_state",
    "market.trade_area_name", "market.trade_area_households",
    "market.trade_area_population", "market.trade_area_median_hh_income",
    "market.trade_area_income_vs_state", "market.trade_area_bachelors_or_higher_share",
    "market.trade_area_median_home_value",
    "market.share_households_in_target_income_band",
    "market.share_population_in_target_age_band",
    "market.composition", "market.composition_scope",
    "entity.target_income_floor", "entity.target_age_band",
    "industry.emp_per_establishment_national",
    "industry.payroll_per_establishment_national",
    "industry.establishment_entry_rate", "industry.establishment_exit_rate",
    "industry.net_job_creation_rate", "industry.bds_year",
    "industry.employment_direction", "industry.young_firm_employment_share",
    "industry.five_year_survival_rate",
    "industry.establishments_history", "industry.establishments_history_span",
    "industry.establishments_history_scope",
  ),
  "competitive_landscape": (
    "market.competition_geo_label", "market.industry_scope_label",
    "market.establishments", "market.client_share_of_establishments",
    "industry.share_firms_under_10_employees",
  ),
  "products_and_services": (
    "annual.revenue_by_lob", "annual.revenue_by_lob_basis",
    "annual.top_lob_name", "annual.top_lob_revenue_share_y1",
    "annual.top_lob_gross_profit_share_y1",
    "annual.top_lob_utilization_y1", "annual.top_lob_utilization_y5",
  ),
  "marketing_and_sales": (
    "annual.marketing_y1", "annual.marketing_pct_revenue_y1",
    "annual.new_customers_y1", "annual.cac_y1", "annual.retention_rate",
    "annual.repeat_share_y1", "annual.customers_y1", "annual.customers_y5",
    "industry.marketing_pct_benchmark",
  ),
  "operations_and_organisation": (
    "market.top_occupation_title", "market.top_occupation_loc_quotient",
  ),
  # Management Team is narrative-carried today; its facts (experience years
  # as citable numbers) are a flagged gap, not an accident - see the audit.
  "management_team": (),
  "staffing_and_human_capital": (
    "annual.headcount_y1", "annual.headcount_y5", "annual.payroll_y1",
    "annual.payroll_y5", "annual.payroll_pct_revenue_y1",
    "annual.revenue_per_fte_y1", "annual.headcount_by_role_group",
    "industry.payroll_pct_benchmark", "industry.revenue_per_fte_benchmark",
    "market.wage_check_title", "market.wage_check_client_wage",
    "market.wage_check_direction", "market.wage_check_area_label",
    "market.wage_check_area_median", "entity.wage_positioning",
    "economy.unemployment_rate", "economy.rates_period_label",
  ),
  "risks_and_mitigations": (
    "annual.price_retained_low", "annual.price_retained_high",
    "annual.debt_retired_year", "economy.ten_year_treasury",
    "economy.ppi_change_yoy",
  ),
  "funding_request": (
    "entity.funding_request", "industry.sba_loan_count",
    "industry.sba_scope_label", "industry.sba_window_start",
    "industry.sba_window_label", "industry.sba_median_amount",
    "industry.sba_median_rate", "industry.sba_median_term_months",
    "industry.sba_chargeoff_rate", "industry.sba_ask_percentile",
    "industry.sba_amount_distribution",
    "economy.ten_year_treasury", "economy.treasury_as_of",
  ),
  # The Financial Plan owns the five-year story: every year of every line,
  # the today-position, the valuation, the scenario bands, the two quarterly
  # exceptions, and the macro frame.
  "financial_plan": (
    "annual.revenue_y1", "annual.revenue_y2", "annual.revenue_y3",
    "annual.revenue_y4", "annual.revenue_y5", "annual.revenue_series",
    "annual.revenue_cagr_y1_y5", "annual.revenue_y1_vs_stated",
    "annual.net_income_y1", "annual.net_income_y2", "annual.net_income_y3",
    "annual.net_income_y4", "annual.net_income_y5", "annual.net_income_series",
    "annual.gross_margin_y1", "annual.gross_margin_y2", "annual.gross_margin_y3",
    "annual.gross_margin_y4", "annual.gross_margin_y5",
    "annual.gross_margin_gap_pts_y1", "annual.gross_margin_gap_direction_y1",
    "annual.operating_margin_y1", "annual.operating_margin_y2",
    "annual.operating_margin_y3", "annual.operating_margin_y4",
    "annual.operating_margin_y5", "annual.operating_margin_gap_pts_y1",
    "annual.operating_margin_gap_direction_y1",
    "annual.net_margin_y1", "annual.net_margin_y2", "annual.net_margin_y3",
    "annual.net_margin_y4", "annual.net_margin_y5",
    "annual.net_margin_gap_pts_y1", "annual.net_margin_gap_direction_y1",
    "annual.margin_structure_series",
    "annual.payroll_y2", "annual.payroll_y3", "annual.payroll_y4",
    "annual.payroll_pct_revenue_y2", "annual.payroll_pct_revenue_y3",
    "annual.payroll_pct_revenue_y4", "annual.payroll_pct_revenue_y5",
    "annual.rent_pct_revenue_y1", "annual.rent_pct_revenue_y2",
    "annual.rent_pct_revenue_y3", "annual.rent_pct_revenue_y4",
    "annual.rent_pct_revenue_y5",
    "annual.capex_y1", "annual.capex_y2", "annual.capex_y3", "annual.capex_y4",
    "annual.capex_y5", "annual.capex_total_y1_y5",
    "annual.dscr_y1", "annual.dscr_y2", "annual.dscr_y3", "annual.dscr_y4",
    "annual.dscr_y5", "annual.debt_retired_year",
    "annual.first_profitable_year", "annual.cash_y5",
    "annual.cash_months_of_costs_y5", "annual.cash_trough_months_of_costs",
    "annual.owners_capital_y1", "annual.owners_capital_pct_assets_y1",
    "annual.break_even_revenue_y1", "annual.cash_break_even_revenue_y1",
    "annual.margin_of_safety", "annual.cvp_fixed_costs_y1",
    "annual.cvp_cm_ratio_y1", "annual.cvp_planned_revenue_y1",
    "annual.marketing_demand_low", "annual.marketing_demand_high",
    "annual.volume_headroom_units",
    "quarterly.cash_trough", "quarterly.cash_trough_amount",
    "quarterly.break_even", "quarterly.cash_balance_series",
    "quarterly.revenue_series", "quarterly.total_cost_series",
    "industry.gross_margin_benchmark", "industry.operating_margin_benchmark",
    "industry.net_margin_benchmark", "industry.rent_pct_benchmark",
    "entity.stated_current_revenue", "entity.stated_employees",
    "entity.stated_revenue_per_employee", "entity.stated_cash_on_hand",
    "entity.stated_debt_outstanding",
    "entity.equity_value_dcf", "entity.exit_multiple_sde",
    "entity.value_at_exit_multiple",
    "economy.period_label", "economy.inflation_rate",
    "economy.ten_year_treasury", "economy.fed_funds_rate",
    "economy.two_year_treasury", "economy.yield_curve_shape",
    "economy.rates_period_label", "economy.gdp_growth_yoy",
    "economy.consumer_spending_growth_yoy",
  ),
  "disclosures": (),
  "executive_summary": (),   # built FROM the present sections, by design
}

# THE NARRATIVE GRANTS - moved here from the assembler (the single door).
SECTION_NARRATIVES: Dict[str, Tuple[str, ...]] = {
  "the_business": ("business_description_summary", "competitive_advantage",
                   "geographic_coverage"),
  "market_and_industry": ("target_market", "marketing_model"),
  "competitive_landscape": ("competitive_advantage", "substitute_pressure"),
  "products_and_services": ("lob_products", "financials_year1_lobs"),
  "marketing_and_sales": ("marketing_plan_summary", "marketing_model", "retention_rationale"),
  "operations_and_organisation": ("fulfillment", "operating_profile"),
  "management_team": ("people",),
  "staffing_and_human_capital": ("inferred_roles", "rest_of_team_payroll"),
  "risks_and_mitigations": ("risk_analysis",),
  "funding_request": ("debt_schedule", "funding_posture"),
  "financial_plan": ("coherence_analysis", "assumptions_ledger", "debt_schedule", "stage_ramp"),
  "disclosures": ("acceptance_verdict", "intake_policy", "estimation_flags"),
  "executive_summary": ("planning_context",),
}


def facts_for_section(section_key: str) -> Tuple[str, ...]:
  return tuple(UNIVERSAL_FACTS) + tuple(SECTION_FACTS.get(section_key, ()))


def narratives_for_section(section_key: str) -> Tuple[str, ...]:
  return tuple(SECTION_NARRATIVES.get(section_key, ()))


def assignment_rows() -> List[Dict[str, Any]]:
  """The control, materialized one row per (kind, key): key -> sections."""
  facts: Dict[str, List[str]] = {k: ["*"] for k in UNIVERSAL_FACTS}
  for sec, keys in SECTION_FACTS.items():
    for k in keys:
      facts.setdefault(k, []).append(sec)
  rows = [{"kind": "fact", "item_key": k, "sections": sorted(set(v))}
          for k, v in facts.items()]
  narr: Dict[str, List[str]] = {}
  for sec, keys in SECTION_NARRATIVES.items():
    for k in keys:
      narr.setdefault(k, []).append(sec)
  rows += [{"kind": "narrative", "item_key": k, "sections": sorted(set(v))}
           for k, v in narr.items()]
  return sorted(rows, key=lambda r: (r["kind"], r["item_key"]))


# ---------------------------------------------------------------------------
# THE TABLE - seeded from here, verified field by field, refused on
# disagreement. Mirrors rule_lookup.py exactly.
# ---------------------------------------------------------------------------
_READY = False
_LOCK = threading.Lock()


def ensure_assignment_table(conn) -> None:
  global _READY
  if _READY:
    return
  with _LOCK:
    if _READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          assignment_version VARCHAR(64) NOT NULL,
          kind VARCHAR(16) NOT NULL,
          item_key VARCHAR(128) NOT NULL,
          sections_json JSON NOT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uq_item (assignment_version, kind, item_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
      )
      conn.commit()
      _READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


def seed_assignment_lookup(conn) -> int:
  """Push this module into the table. Code is the source of truth; the table
  is its serving copy, never the other way round."""
  ensure_assignment_table(conn)
  cur = conn.cursor()
  written = 0
  try:
    for r in assignment_rows():
      cur.execute(
        f"""INSERT INTO {TABLE_NAME}
              (assignment_version, kind, item_key, sections_json, active)
            VALUES (%s,%s,%s,%s,1)
            ON DUPLICATE KEY UPDATE
              sections_json=VALUES(sections_json), active=1""",
        (ASSIGNMENT_VERSION, r["kind"], r["item_key"], json.dumps(r["sections"])),
      )
      written += 1
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return written


def verify_assignment_live(conn) -> Tuple[bool, List[str]]:
  """Read the table back and compare field by field. Disagreement is a
  REFUSAL, not a warning - the payroll-contract lesson."""
  ensure_assignment_table(conn)
  cur = conn.cursor(dictionary=True)
  problems: List[str] = []
  try:
    cur.execute(
      f"""SELECT kind, item_key, sections_json FROM {TABLE_NAME}
          WHERE assignment_version=%s AND active=1""",
      (ASSIGNMENT_VERSION,))
    db = {(r["kind"], r["item_key"]): sorted(json.loads(r["sections_json"]))
          for r in cur.fetchall()}
  finally:
    try:
      cur.close()
    except Exception:
      pass
  code = {(r["kind"], r["item_key"]): r["sections"] for r in assignment_rows()}
  for key in sorted(set(code) - set(db)):
    problems.append("missing from table: %s %s" % key)
  for key in sorted(set(db) - set(code)):
    problems.append("in table but not in code: %s %s" % key)
  for key in sorted(set(code) & set(db)):
    if code[key] != db[key]:
      problems.append("sections disagree for %s %s: code=%s table=%s"
                      % (key[0], key[1], code[key], db[key]))
  return (not problems), problems
