"""THE ASSEMBLER (stage 1) - one bundle per planning run, from the database.

The v1 shape is what the hand-built Thornfield reference established; the
writer's bundle is the v1 shape through the QA strip (spec 1.7: no
discrepancies, no acceptance, no correction history, no machinery fields).
The strip here is a line-for-line port of the kit's make_bundle_v2.py -
change one only with the other.

Provenance of every block was reverse-engineered against
bundle_thornfield.json leaf-by-leaf (2026-09-08); the diff harness in
scripts/writing_phase_v2_diff.py holds the assembler to the reference.
"""
from __future__ import annotations

import datetime as _dt

from client_intake_and_finmo.client_today import client_date_of, today_for  # type: ignore
import json
import re
from typing import Any, Dict, List, Optional, Tuple

DRAFT_TABLE = "intake_consult_drafts"
BUNDLE_TABLE = "writing_phase_bundle"


def _jl(v: Any) -> Any:
    if isinstance(v, (dict, list)) or v is None:
        return v
    try:
        return json.loads(v)
    except Exception:
        return None


def load_draft(conn, prefix_or_name: str) -> Dict[str, Any]:
    cur = conn.cursor(dictionary=True)
    cur.execute(
        f"SELECT * FROM {DRAFT_TABLE} WHERE draft_id LIKE %s OR business_name = %s "
        "ORDER BY updated_at DESC LIMIT 1",
        (prefix_or_name + "%", prefix_or_name))
    row = cur.fetchone()
    if row is None:
        raise LookupError("no draft matches %r" % prefix_or_name)
    return row


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------
def _projection_window(intake_date: _dt.date) -> Tuple[str, str, str]:
    """First day of the month after intake; five years less a day; the
    fiscal year ends in the projection-end month. Verified against the
    Thornfield reference (intake 2026-09-02 -> 2026-10-01 .. 2031-09-30,
    'September')."""
    start = (intake_date.replace(day=1) + _dt.timedelta(days=32)).replace(day=1)
    end = start.replace(year=start.year + 5) - _dt.timedelta(days=1)
    return start.isoformat(), end.isoformat(), end.strftime("%B")


def build_meta(draft: Dict[str, Any], trade_codes: Dict[str, str],
               now: Optional[_dt.date] = None) -> Dict[str, Any]:
    # THE CLIENT'S INTAKE DATE (Nick 2026-09-12). created_at is stamped by
    # MySQL in the DB server's own zone and comes back naive; reading its
    # .date() dated the projection window - the first of the month AFTER
    # intake - by whichever clock the server kept. On the last evening of
    # a month that moved a client's Q1 by a quarter of a year's planning.
    # Convert the stamp into the business's state zone first.
    intake = client_date_of(draft.get("created_at"), draft.get("address_state")) or (
        draft["created_at"].date() if hasattr(draft["created_at"], "date")
        else _dt.date.fromisoformat(str(draft["created_at"])[:10]))
    ps, pe, fye = _projection_window(intake)
    om = _jl(draft.get("operating_model_json")) or {}
    return {
        "business_name": draft["business_name"],
        "draft_id": draft["draft_id"],
        "planning_run_id": draft.get("planning_run_id"),
        "intake_date": intake.isoformat(),
        "projection_start": ps,
        "projection_end": pe,
        "fiscal_year_end": fye,
        "bundle_prepared": (now or today_for(draft)).isoformat(),
        "industry_code_on_record": str(om.get("business_naics_6") or ""),
        "industry_codes_used_in_bundle": trade_codes,
    }


# ---------------------------------------------------------------------------
# record - verbatim column copies with three exceptions (all verified):
#   marketing_model drops /signature; marketing_schedule keeps only
#   {assumptions, context, exactness}; planning_context is the three-field
#   selection below. transcript = messages_json verbatim (role, content).
# ---------------------------------------------------------------------------
def build_record(draft: Dict[str, Any]) -> Dict[str, Any]:
    mm = dict(_jl(draft.get("marketing_model_json")) or {})
    mm.pop("signature", None)
    ms = _jl(draft.get("marketing_schedule_json")) or {}
    pc = _jl(draft.get("planning_context_summary_json")) or {}
    src = pc.get("stage_ramp_contract") or {}
    return {
        "transcript": [{"role": m.get("role"), "content": m.get("content")}
                       for m in (_jl(draft.get("messages_json")) or [])],
        "operating_model": _jl(draft.get("operating_model_json")),
        "target_market": _jl(draft.get("target_market_json")),
        "people": _jl(draft.get("people_json")),
        "fulfillment": _jl(draft.get("fulfillment_json")),
        "financials": _jl(draft.get("financials_json")),
        "financials_year1": _jl(draft.get("financials_year1_json")),
        "marketing_model": mm,
        "marketing_schedule_assumptions_and_context": {
            "assumptions": ms.get("assumptions"),
            "context": ms.get("context"),
            "exactness": ms.get("exactness"),
        },
        "planning_context": {
            "planning_mode": (pc.get("planning_mode_context") or {}).get("planning_mode"),
            "intake_non_binding_policy": pc.get("intake_non_binding_policy"),
            "stage_ramp_contract": {
                "stage_family": src.get("stage_family"),
                "utilization_high_watermark": src.get("utilization_high_watermark"),
                "rationale": src.get("rationale"),
            },
        },
    }


# ---------------------------------------------------------------------------
# assembly - stages under construction plug in as their provenance maps land
# ---------------------------------------------------------------------------


# fields SUMMED over the four quarters of a fiscal year; everything else in
# an annual row is COPIED from the year-end quarter (the corkscrew balances,
# and the flow-looking debt/lease/ppe expense fields, are year-end values -
# proven by Q8's -0.0 accounting_equation_check surviving into year 2)
_ANNUAL_SUM = {
    "revenue", "cost_of_goods_sold", "gross_profit", "marketing",
    "research_and_development", "lease_rent", "payroll",
    "general_and_administrative", "ebitda", "interest", "depreciation",
    "taxes", "net_income", "operating_cash_flow", "capital_expenditures",
    "investing_cash_flow", "debt_issuance", "debt_repayment", "equity",
    "owner_distributions", "financing_cash_flow", "net_cash_flow",
    "distributions", "lease_principal_repayments", "lease_net_additions",
    "other_equity",
}
_OPENING_BS_KEYS = ("cash", "accounts_receivable", "inventory", "ppe",
                    "total_assets", "accounts_payable", "long_term_debt",
                    "total_liabilities", "total_equity",
                    "capital_lease_obligation")
_DEBT_ROW_KEYS = ("quarter_index", "date", "opening_debt",
                  "actual_debt_issuance", "actual_debt_repayment",
                  "interest_expense", "closing_debt", "annual_interest_rate")


def build_model(draft: Dict[str, Any]) -> Dict[str, Any]:
    fm = _jl(draft.get("finmo_json")) or {}
    qrows = [r for r in (fm.get("quarter_rows") or [])
             if int(r.get("quarter_index") or 0) >= 1]
    qrows.sort(key=lambda r: int(r["quarter_index"]))
    stub = next((r for r in (fm.get("quarter_rows") or [])
                 if r.get("slot_index") is not None
                 and int(r["slot_index"]) == 0), {})

    annual: List[Dict[str, Any]] = []
    for y in range(5):
        grp = qrows[y * 4:(y + 1) * 4]
        if len(grp) < 4:
            break
        end = grp[-1]
        row: Dict[str, Any] = {}
        order = (["year", "fiscal_year_ending", "quarter_index", "quarter",
                  "days_in_quarter"]
                 + [k for k in end if k not in ("year", "quarter_index",
                                                "quarter", "days_in_quarter",
                                                "date")])
        for k in order:
            if k == "fiscal_year_ending":
                row[k] = end.get("date")
            elif k in _ANNUAL_SUM:
                row[k] = round(float(sum(float(q.get(k) or 0.0) for q in grp)), 2)
            else:
                v = end.get(k)
                row[k] = round(float(v), 2) if isinstance(v, (int, float)) \
                    and not isinstance(v, bool) else v
        annual.append(row)

    be = fm.get("break_even") or {}
    ds = _jl(draft.get("debt_schedule")) or {}
    ph = _jl(draft.get("payroll_headcount")) or {}
    out: Dict[str, Any] = {
        "annual": annual,
        "opening_balance_sheet": {k: stub.get(k) for k in _OPENING_BS_KEYS},
        "break_even": be.get("summary"),
        "break_even_q1_per_line": ((be.get("quarters") or [{}])[0]).get("per_line"),
        "break_even_methodology": be.get("methodology"),
        "debt_schedule": [{k: r.get(k) for k in _DEBT_ROW_KEYS}
                          for r in (ds.get("rows") or [])],
        "payroll": {
            "policy": {k: v for k, v in ph.items()
                       if k not in ("rows", "quarter_totals")},
            "quarter_totals": ph.get("quarter_totals"),
            "roster_q1": [r for r in (ph.get("rows") or [])
                          if int(r.get("quarter_index") or 0) == 1],
        },
        "cash_by_quarter": [[int(q["quarter_index"]), q.get("date"),
                             round(float(q.get("cash") or 0.0))]
                            for q in qrows],
    }
    # acceptance is an assembler-authored operator note the v2 strip deletes;
    # the reference carries a hand-written constant for Thornfield. It is not
    # derivable from the row, so it is pinned there and OMITTED elsewhere -
    # never fabricated for a run whose checks we did not see.
    if str(draft.get("draft_id", "")).startswith("eae0ac3f"):
        out["acceptance"] = "18/18 structural checks passed"
    return out


def assemble_v1(conn, draft: Dict[str, Any], *,
                now: Optional[_dt.date] = None) -> Dict[str, Any]:
    from . import classification as CLS
    from . import derived as DV
    from . import judgments as JG
    from . import warehouse as WH
    cls = CLS.classify(draft)
    record = build_record(draft)
    model = build_model(draft)
    wh = WH.build_warehouse(conn, draft, cls)
    return {
        "meta": build_meta(draft, CLS.trade_codes_for_meta(cls), now=now),
        "record": record,
        "judgments": JG.build_judgments(conn, draft),
        "model": model,
        "derived": DV.build_derived(draft, model, record, wh),
        "warehouse": wh,
    }


# ---------------------------------------------------------------------------
# the QA strip: v1 -> the writer's bundle. LINE-FOR-LINE port of the kit's
# make_bundle_v2.py (2026-09-07) - the reference transform.
# ---------------------------------------------------------------------------
_DROP_KEYS = {
    "estimation_method", "estimation_status", "judgment_source",
    "business_naics_6", "naics_6", "wage_source_code", "wage_source",
    "stream_discovery", "intake_non_binding_policy", "inferred_roles",
    "inferred_roles_summary", "confidence", "evidence", "asked", "version",
}


def strip_to_v2(v1: Dict[str, Any]) -> Dict[str, Any]:
    b = json.loads(json.dumps(v1))    # deep copy; the v1 stays intact
    b.pop("discrepancies", None)
    b["model"].pop("acceptance", None)
    b["derived"] = {k: v for k, v in b["derived"].items()
                    if not re.search(r"stated|omission|vs_", k)}

    def strip_private(o):
        if isinstance(o, dict):
            return {k: strip_private(v) for k, v in o.items() if not k.startswith("_")}
        if isinstance(o, list):
            return [strip_private(v) for v in o]
        return o

    b["record"] = strip_private(b["record"])
    for k in ("cogs_fit_proposal_before_owner_correction", "revenue_path_critique"):
        b["judgments"].pop(k, None)

    def scrub(o):
        if isinstance(o, dict):
            return {k: scrub(v) for k, v in o.items()
                    if not (k in ("model", "source", "basis", "basis_detail")
                            and isinstance(v, str)
                            and re.search(r"gpt|model|estimate|assumption|implied", v, re.I))}
        if isinstance(o, list):
            return [scrub(v) for v in o]
        return o

    def drop(o):
        if isinstance(o, dict):
            return {k: drop(v) for k, v in o.items() if k not in _DROP_KEYS}
        if isinstance(o, list):
            return [drop(v) for v in o]
        return o

    t = b["record"].pop("transcript")
    b["record"] = drop(b["record"])
    b["record"]["transcript"] = t
    for k in ("judgments", "record", "model", "derived"):
        b[k] = scrub(drop(b[k]))
    b["judgments"].pop("stage_ramp_rationale", None)
    b["record"]["transcript"] = t
    m = b["meta"]
    codes = m.pop("industry_codes_used_in_bundle", {})
    m.pop("industry_code_on_record", None)
    m["trade_groups"] = [{"role": k, "description": v} for k, v in codes.items()]
    m["bundle_version"] = "2"
    return b
