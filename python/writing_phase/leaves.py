"""THE LEAVES — field-level control over what each section can see (2026-09-03).

Nick: "The unit has to be the individual fact. business_description_summary
to The Business. lob_models[].products[].unit_price to Products. The NAICS
to nothing at all." The census said the job is ~520 rows, 81% of raw
patterns dissolving into source-level dispositions by existing rulings.

Row semantics, per (source, pattern):
  unit     leaf | group (row covers the whole subtree) | source (whole payload)
  status   assigned  - projects into the named sections' briefs
           via_facts - owned by the named sections but SERVED through the
                       catalog's formatted facts (rule 16's one formatter),
                       never as a raw narrative leaf - no double door
           invisible - ruled out (each row says why); projects nowhere
           pending   - a judgment call brought to Nick, NOT decided here;
                       projects nowhere, but is KNOWN - never an orphan
An actual draft path that matches NO row is an ORPHAN: recorded to
`writing_phase_leaf_orphans` and surfaced on the receipt as new-leaves=N,
so a new intake field appears on the next receipt instead of vanishing.

Same discipline as rule_lookup/assignment: this module is the single door,
`writing_phase_leaf_lookup` its serving copy, seeded from here, verified
field by field, the runner refusing on disagreement.

INCREMENTAL BY SECTION: only PROJECTED_SECTIONS assemble their narratives
from leaves; every other section keeps its current grant until touched.
The orphan walk is global from day one regardless.

The transcript is prose, not leaves, and stays whole in the common core.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

LEAF_VERSION = "leaves_v1"
TABLE_NAME = "writing_phase_leaf_lookup"
ORPHANS_TABLE = "writing_phase_leaf_orphans"

# Sections whose narratives are assembled FROM LEAVES today. Others keep
# their extract_narratives grants until each is converted deliberately.
PROJECTED_SECTIONS: Tuple[str, ...] = ("the_business",)

# Sources the projector walks. Grids and excluded payloads are governed by
# source-level rows below and are never projected.
PROJECTABLE_SOURCES: Tuple[str, ...] = (
  "operating_model_json", "target_market_json", "financials_json",
  "financials_year1_json", "people_json", "fulfillment_json",
  "marketing_schedule_json", "marketing_model_json",
  "planning_context_summary_json",
)

# (source, pattern, unit, status, sections, why)
Row = Tuple[str, str, str, str, Tuple[str, ...], str]

_TB = "the_business"
_MKT = "market_and_industry"
_CL = "competitive_landscape"
_PRD = "products_and_services"
_MS = "marketing_and_sales"
_OPS = "operations_and_organisation"
_MGT = "management_team"
_STF = "staffing_and_human_capital"
_RSK = "risks_and_mitigations"
_FND = "funding_request"
_FP = "financial_plan"
_DSC = "disclosures"
_EXC = "executive_summary"


def _rows() -> List[Row]:
  R: List[Row] = []

  def leaf(src, pat, secs, why=""):
    R.append((src, pat, "leaf", "assigned", tuple(secs), why))

  def group(src, pat, secs, why=""):
    R.append((src, pat, "group", "assigned", tuple(secs), why))

  def invisible(src, pat, why, unit="leaf"):
    R.append((src, pat, unit, "invisible", (), why))

  def pending(src, pat, why, unit="leaf"):
    R.append((src, pat, unit, "pending", (), why))

  def via_facts(src, pat, secs, why=""):
    R.append((src, pat, "leaf", "via_facts", tuple(secs),
              why or "served through the catalog's formatted facts"))

  # ---- source-level dispositions (81% of raw patterns dissolve here) ------
  R.append(("finmo_json", "", "source", "assigned", ("*",),
            "served as finmo_annual_body in the common core; quarterly "
            "detail is appendix-only (rule 18)"))
  R.append(("payroll_headcount", "", "source", "assigned", (_STF,),
            "the role-by-quarter grid; reaches prose via derived facts only"))
  R.append(("model_input_json", "", "source", "invisible", (),
            "rule 4 - machinery never reaches the writer"))
  R.append(("realism_memo_json", "", "source", "invisible", (),
            "rule 4 - machinery never reaches the writer"))

  # ---- operating_model_json ----------------------------------------------
  s = "operating_model_json"
  leaf(s, "/business_description_summary", (_TB,), "prose; carries Products/Ops detail inside text - flagged for intake repack")
  leaf(s, "/competitive_advantage", (_TB, _CL), "shared by assignment: TB says what, CL says versus-whom")
  leaf(s, "/geographic_coverage", (_TB,))
  group(s, "/lob_models[]", (_PRD,), "the lines with their unit economics - Products owns every field inside")
  leaf(s, "/split_rationale", (_PRD,))
  leaf(s, "/unit_description", (_PRD,))
  for p in ("/capacity_driver", "/shipping_method", "/sales_modality",
            "/geographic_scope", "/countries[]", "/business_type",
            "/consumer_type", "/business_stage"):
    leaf(s, p, (_OPS,), "the operating profile (business_stage also rides the common-core identity)")
  via_facts(s, "/legal_entity", (_TB,))
  invisible(s, "/business_naics_6", "the classification is machinery (2026-09-03)")
  invisible(s, "/stream_discovery", "intake machinery - the discovery record", unit="group")
  invisible(s, "/milestones[]", "an unmodelled intake aspiration (2026-09-01)", unit="group")
  invisible(s, "/confidence", "intake diagnostic")
  invisible(s, "/line_split_confidence", "intake diagnostic")
  pending(s, "/primary_growth_lever",
          "ruled OUT of The Business (strategy is not identity); no home "
          "ruled yet - Marketing? Executive Summary? Nick decides")

  # ---- target_market_json ------------------------------------------------
  s = "target_market_json"
  leaf(s, "/marketing_plan_summary", (_MS,))
  for p in ("/consumer_type", "/gender_age_intent", "/gender_age_intent[]/age_min",
            "/gender_age_intent[]/age_max", "/gender_age_intent[]/gender_focus",
            "/income_intent", "/income_intent[]/income_min", "/income_intent[]/income_max",
            "/selections", "/selections[]/segment", "/selections[]/acs_codes[]",
            "/b2b_industry_terms", "/b2b_industry_terms[]",
            "/b2b_age_bands", "/b2b_age_bands[]", "/b2b_size_bands", "/b2b_size_bands[]"):
    leaf(s, p, (_MKT,))
  invisible(s, "/b2b_naics_6", "codes are machinery")
  invisible(s, "/b2b_naics_6[]", "codes are machinery")
  invisible(s, "/confidence", "intake diagnostic")

  # ---- financials_json ---------------------------------------------------
  s = "financials_json"
  group(s, "/_coherence/demand_response", (_FP, _RSK), "the judged sensitivity - shared by assignment")
  group(s, "/_coherence/walls", (_FP, _RSK))
  for p in ("/_coherence/margin_band_judgment", "/_coherence/judged_growth",
            "/_coherence/essentials_response"):
    group(s, p, (_FP,))
  leaf(s, "/_coherence/converged_suffix", (_FP,))
  leaf(s, "/_coherence/status", (_FP,))
  for p in ("/_coherence/eval", "/_coherence/eval_flat", "/_coherence/early_eval"):
    invisible(s, p, "engine diagnostics, never granted", unit="group")
  invisible(s, "/_coherence/digest_hash", "machinery")
  invisible(s, "/_coherence/gap_open", "machinery")
  group(s, "/_cogs_baseline_resolution", (_FP,), "the assumptions record behind COGS")
  group(s, "/payroll_basis_people_roles[]", (_STF,), "payroll basis - wages live with Staffing")
  for p in ("/funding_preference", "/funding_split_debt_share", "/cash_strategy"):
    leaf(s, p, (_FND,))
  for p in ("/current_revenue", "/current_num_employees"):
    via_facts(s, p, (_TB, _FP), "the scale anchor (TB) and today-position (FP) - the catalog formats it")
  for p in ("/cash_on_hand", "/total_debt_outstanding"):
    via_facts(s, p, (_FP,), "the today balance, ruled to the Financial Plan (2026-09-03)")
  for p in ("/_financials_marketing_stage_done", "/_financials_revenue_intro_done"):
    invisible(s, p, "flow flags - machinery")
  # THE JUDGMENT CLUSTER - the stated today-scalars. Brought to Nick as a
  # list before anyone decides them; pending projects nothing meanwhile.
  for p in ("/current_payroll", "/payroll_total_year1", "/baseline_payroll_year1",
            "/owner_compensation", "/monthly_rent_expense", "/future_rent_expected",
            "/other_operating_expense", "/other_opex_absolute",
            "/other_monthly_debt_payments", "/annual_interest_payment",
            "/annual_principal_payment", "/current_cogs", "/cogs_total_year1",
            "/cogs_percent_of_revenue", "/cogs_basis", "/current_capex",
            "/initial_assets", "/initial_equity", "/capital_lease_balance",
            "/ar_balance", "/ap_balance", "/inventory_balance",
            "/marketing_total_year1", "/marketing_percent_of_revenue",
            "/marketing_adjustment", "/baseline_marketing",
            "/baseline_marketing_percent"):
    pending(s, p, "stated today-scalar - cross-cutting by nature; on Nick's judgment list")

  # ---- financials_year1_json ---------------------------------------------
  s = "financials_year1_json"
  leaf(s, "/company_revenue_total_year1", (_FP,))
  group(s, "/lobs[]", (_PRD,), "per-line Year-1 drivers - Products owns every field inside")

  # ---- people_json -------------------------------------------------------
  s = "people_json"
  group(s, "/people[]", (_MGT,), "who people are - Management Team's material")
  for p in ("/people[]/annual_wage", "/people[]/wage_source"):
    pending(s, p, "the wage split - wages were kept OUT of the people "
                  "narrative on 08-30; their positive home is Nick's call")
  leaf(s, "/inferred_roles[]", (_STF,))
  leaf(s, "/inferred_roles_summary", (_STF,))
  leaf(s, "/rest_of_team_payroll_year1", (_STF,))
  invisible(s, "/business_naics_6", "codes are machinery")
  invisible(s, "/confidence", "intake diagnostic")

  # ---- fulfillment_json --------------------------------------------------
  leaf("fulfillment_json", "/personnel", (_OPS,))
  leaf("fulfillment_json", "/time", (_OPS,))

  # ---- marketing_schedule_json -------------------------------------------
  s = "marketing_schedule_json"
  group(s, "/assumptions", (_MS,), "retention and repeat-purchase judgments")
  group(s, "/context", (_MS,), "the customer/units frame behind the schedule")
  for p in ("/periods[]", "/exactness", "/tie_back"):
    invisible(s, p, "the quarterly schedule grid - rule 18 territory", unit="group")
  for p in ("/schedule_class", "/status", "/contract_version"):
    invisible(s, p, "machinery")

  # ---- marketing_model_json ----------------------------------------------
  s = "marketing_model_json"
  for p in ("/b2b_basis_counts", "/b2c_basis_counts[]", "/geography_basis"):
    group(s, p, (_MKT, _MS), "the market-universe evidence - shared by assignment")
  leaf(s, "/b2c_basis_counts", (_MKT, _MS))
  for p in ("/reachable_market", "/reachable_market_b2b", "/reachable_market_b2c",
            "/expected_customers_or_clients_year1", "/expected_units_year1",
            "/capture_rate_year1", "/marketing_basis_summary",
            "/marketing_intensity", "/market_basis_type",
            "/baseline_marketing", "/baseline_marketing_percent"):
    leaf(s, p, (_MKT, _MS))
  for p in ("/estimation_method", "/estimation_status"):
    leaf(s, p, (_DSC,), "the estimation flags the honesty page discloses")
  for p in ("/estimation_warning", "/signature", "/version", "/ready",
            "/missing_dependencies[]", "/required_revenue_year1",
            "/required_units_year1", "/demand_supports_required_units"):
    invisible(s, p, "machinery/diagnostics")

  # ---- planning_context_summary_json -------------------------------------
  s = "planning_context_summary_json"
  group(s, "/stage_ramp_contract", (_FP,))
  group(s, "/intake_non_binding_policy", (_DSC,))
  group(s, "", (_EXC,), "the executive summary's whole-picture digest "
                        "(catch-all group; more specific rows above win)")
  return R


LEAF_ROWS: Tuple[Row, ...] = tuple(_rows())


# ---------------------------------------------------------------------------
# matching - exact leaf first, then longest group/source prefix
# ---------------------------------------------------------------------------
def _index():
  exact: Dict[Tuple[str, str], Row] = {}
  prefixes: Dict[str, List[Row]] = {}
  for r in LEAF_ROWS:
    src, pat, unit = r[0], r[1], r[2]
    if unit == "leaf":
      exact[(src, pat)] = r
    else:
      prefixes.setdefault(src, []).append(r)
  for src in prefixes:
    prefixes[src].sort(key=lambda r: -len(r[1]))
  return exact, prefixes


_EXACT, _PREFIXES = _index()


def match(source: str, pattern: str) -> Optional[Row]:
  r = _EXACT.get((source, pattern))
  if r is not None:
    return r
  for row in _PREFIXES.get(source, []):
    if pattern.startswith(row[1]):
      return row
  return None


# ---------------------------------------------------------------------------
# the walker (orphan surfacing - GLOBAL from day one)
# ---------------------------------------------------------------------------
def _jload(v):
  if isinstance(v, (dict, list)):
    return v
  try:
    return json.loads(v) if v else {}
  except Exception:
    return {}


def _walk_patterns(o, pat, out):
  if isinstance(o, dict):
    for k, v in o.items():
      _walk_patterns(v, pat + "/" + str(k), out)
  elif isinstance(o, list):
    for v in o:
      _walk_patterns(v, pat + "[]", out)
    if not o:
      out.add(pat + "[]")
  else:
    out.add(pat)


def draft_patterns(draft: Dict[str, Any]) -> Dict[str, set]:
  out: Dict[str, set] = {}
  for src in PROJECTABLE_SOURCES:
    pats: set = set()
    _walk_patterns(_jload(draft.get(src)), "", pats)
    out[src] = pats
  return out


def orphans_for_draft(draft: Dict[str, Any]) -> List[Tuple[str, str]]:
  """Every actual path matching NO row. A new intake field lands here."""
  found: List[Tuple[str, str]] = []
  for src, pats in draft_patterns(draft).items():
    for p in sorted(pats):
      if match(src, p) is None:
        found.append((src, p))
  return found


# ---------------------------------------------------------------------------
# the projector - a section's narrative view, rebuilt from assigned leaves
# ---------------------------------------------------------------------------
def _prune(o, src, pat, section):
  row = match(src, pat) if pat else None
  if row is not None and row[3] == "assigned" and row[2] in ("group", "source"):
    return o if (section in row[4] or "*" in row[4]) else None
  if isinstance(o, dict):
    out = {}
    for k, v in o.items():
      kept = _prune(v, src, pat + "/" + str(k), section)
      if kept is not None and kept != {} and kept != []:
        out[k] = kept
    return out or None
  if isinstance(o, list):
    out = [x for x in (_prune(v, src, pat + "[]", section) for v in o)
           if x is not None and x != {} and x != []]
    return out or None
  r = match(src, pat)
  if r is not None and r[3] == "assigned" and (section in r[4] or "*" in r[4]):
    return o
  return None


def project(section_key: str, draft: Dict[str, Any]) -> Dict[str, Any]:
  """The section's narrative material from its assigned leaves. Top-level
  scalars keep their own key names (so The Business's slice is
  byte-compatible with the narrative keys the payload always used);
  collisions across sources refuse loudly rather than silently merge."""
  out: Dict[str, Any] = {}
  for src in PROJECTABLE_SOURCES:
    pruned = _prune(_jload(draft.get(src)), src, "", section_key)
    if not pruned:
      continue
    for k, v in (pruned.items() if isinstance(pruned, dict) else [(src, pruned)]):
      if k in out:
        raise ValueError("leaf projection collision on %r from %s" % (k, src))
      out[k] = v
  return out


# ---------------------------------------------------------------------------
# seed / verify / refuse + the orphans table - the rule-lookup discipline
# ---------------------------------------------------------------------------
_READY = False
_LOCK = threading.Lock()


def ensure_tables(conn) -> None:
  global _READY
  if _READY:
    return
  with _LOCK:
    if _READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          leaf_version VARCHAR(64) NOT NULL,
          source VARCHAR(64) NOT NULL,
          path_pattern VARCHAR(255) NOT NULL,
          unit VARCHAR(16) NOT NULL,
          status VARCHAR(16) NOT NULL,
          sections_json JSON NOT NULL,
          why TEXT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uq_leaf (leaf_version, source, path_pattern)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
      cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {ORPHANS_TABLE} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          draft_id VARCHAR(64) NOT NULL,
          source VARCHAR(64) NOT NULL,
          path_pattern VARCHAR(255) NOT NULL,
          seen_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          UNIQUE KEY uq_orphan (draft_id, source, path_pattern)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
      conn.commit()
      _READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


def seed_leaf_lookup(conn) -> int:
  ensure_tables(conn)
  cur = conn.cursor()
  written = 0
  try:
    for src, pat, unit, status, secs, why in LEAF_ROWS:
      cur.execute(
        f"""INSERT INTO {TABLE_NAME}
              (leaf_version, source, path_pattern, unit, status, sections_json, why, active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,1)
            ON DUPLICATE KEY UPDATE
              unit=VALUES(unit), status=VALUES(status),
              sections_json=VALUES(sections_json), why=VALUES(why), active=1""",
        (LEAF_VERSION, src, pat, unit, status, json.dumps(sorted(secs)), why))
      written += 1
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return written


def verify_leaf_lookup_live(conn) -> Tuple[bool, List[str]]:
  ensure_tables(conn)
  cur = conn.cursor(dictionary=True)
  problems: List[str] = []
  try:
    cur.execute(f"""SELECT source, path_pattern, unit, status, sections_json
                    FROM {TABLE_NAME} WHERE leaf_version=%s AND active=1""",
                (LEAF_VERSION,))
    db = {(r["source"], r["path_pattern"]):
          (r["unit"], r["status"], sorted(json.loads(r["sections_json"])))
          for r in cur.fetchall()}
  finally:
    try:
      cur.close()
    except Exception:
      pass
  code = {(src, pat): (unit, status, sorted(secs))
          for src, pat, unit, status, secs, _ in LEAF_ROWS}
  for k in sorted(set(code) - set(db)):
    problems.append("missing from table: %s %s" % k)
  for k in sorted(set(db) - set(code)):
    problems.append("in table but not in code: %s %s" % k)
  for k in sorted(set(code) & set(db)):
    if code[k] != db[k]:
      problems.append("disagrees for %s %s: code=%s table=%s"
                      % (k[0], k[1], code[k], db[k]))
  return (not problems), problems


def record_orphans(conn, draft: Dict[str, Any], draft_id: str) -> int:
  """Write every unmatched actual path; returns the count for the receipt."""
  ensure_tables(conn)
  found = orphans_for_draft(draft)
  if found:
    cur = conn.cursor()
    try:
      for src, pat in found:
        cur.execute(
          f"""INSERT IGNORE INTO {ORPHANS_TABLE} (draft_id, source, path_pattern)
              VALUES (%s,%s,%s)""", (draft_id, src, pat))
      conn.commit()
    finally:
      try:
        cur.close()
      except Exception:
        pass
  return len(found)
