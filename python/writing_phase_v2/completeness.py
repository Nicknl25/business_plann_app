"""THE REASON GATE (Nick 2026-09-10).

The completeness gate used to check that an absence carried a reason -
not that the reason was TRUE. So a figure could omit itself, write a
note, and pass: Bright Smiles lost revenue_by_line to "single line of
business" on a practice with three priced service lines, and
wage_positioning to "no roster role could be matched to an occupation"
on a roster whose rows carried occupation stamps (the real failure was
the OEWS area join, 'IL' vs 'Illinois').

Every absence reason a renderer can emit is registered here with a
validator that re-tests the CLAIM against the same data the renderer
read. A reason that is false fails the gate with the evidence; a reason
this module has no validator for ALSO fails the gate - an excuse nobody
can test is not a reason. Adding an absent() call to render_charts.py
therefore requires adding its validator here, deliberately.

Validator contract: fn(bundle, render_data, draft) -> Optional[str].
None means the reason holds; a string is the evidence that it is false.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Tuple


def _jl(v):
    if isinstance(v, (dict, list)) or v is None:
        return v
    try:
        return json.loads(v)
    except Exception:
        return None


def _revenue_streams(bundle) -> List[Tuple[str, Any]]:
    """Every priced revenue stream the model carries: products within
    lobs are streams too - a 'single primary line' holding three priced
    services is three streams, not one."""
    fy = (bundle.get("record") or {}).get("financials_year1") or {}
    out = []
    for lob in fy.get("lobs") or []:
        prods = lob.get("products") or []
        if prods:
            for p in prods:
                out.append((str(p.get("product_name") or lob.get("lob_name")
                                or "line"), p.get("unit_price")))
        else:
            out.append((str(lob.get("lob_name") or "line"), None))
    return out


def _single_line(bundle, render_data, draft) -> Optional[str]:
    streams = _revenue_streams(bundle)
    if len(streams) >= 2:
        return ("the business carries %d priced revenue streams: %s"
                % (len(streams),
                   "; ".join("%s at %s" % (n, p) for n, p in streams)))
    return None


def _no_bds_history(bundle, render_data, draft) -> Optional[str]:
    bds = (bundle.get("warehouse") or {}).get("bds_2023") or {}
    for code, grp in bds.items():
        if (grp or {}).get("estabs_history"):
            return ("bds_2023[%s] carries %d establishment-history points"
                    % (code, len(grp["estabs_history"])))
    return None


def _payroll_qt(bundle):
    return ((bundle.get("model") or {}).get("payroll") or {}) \
        .get("quarter_totals") or []


def _no_quarter_totals(bundle, render_data, draft) -> Optional[str]:
    qt = _payroll_qt(bundle)
    if qt:
        return "model.payroll.quarter_totals holds %d rows" % len(qt)
    return None


def _no_fte_series(bundle, render_data, draft) -> Optional[str]:
    fte = [r.get("ending_fte") for r in _payroll_qt(bundle)]
    live = [v for v in fte if v is not None]
    if live:
        return ("%d of %d quarter totals carry ending_fte"
                % (len(live), len(fte)))
    return None


def _no_capacity_line(bundle, render_data, draft) -> Optional[str]:
    fy = (bundle.get("record") or {}).get("financials_year1") or {}
    for lob in fy.get("lobs") or []:
        for pr in lob.get("products") or []:
            if pr.get("units_per_week_capacity") and pr.get("utilization_rate"):
                return ("%r carries units_per_week_capacity=%s "
                        "utilization_rate=%s"
                        % (pr.get("product_name"),
                           pr.get("units_per_week_capacity"),
                           pr.get("utilization_rate")))
    return None


def _mkt_periods(render_data):
    return [p for p in ((render_data or {}).get("marketing_periods") or [])
            if not p.get("is_stub")]


def _no_marketing_periods(bundle, render_data, draft) -> Optional[str]:
    periods = _mkt_periods(render_data)
    if periods:
        return "renderer data carries %d marketing periods" % len(periods)
    return None


def _fewer_than_four_quarters(bundle, render_data, draft) -> Optional[str]:
    periods = _mkt_periods(render_data)
    y1 = [p for p in periods if 0 < int(p.get("period_index") or 0) <= 4]
    if len(y1) >= 4:
        return "the first projection year holds %d quarters" % len(y1)
    return None


def _fs(bundle):
    return ((bundle.get("warehouse") or {}).get("bds_firm_size_2023") or {}) \
        .get("firms_by_size") or {}


def _no_firm_size_slice(bundle, render_data, draft) -> Optional[str]:
    fs = _fs(bundle)
    if fs:
        return "bds_firm_size_2023.firms_by_size holds %d buckets" % len(fs)
    return None


def _firm_size_empty(bundle, render_data, draft) -> Optional[str]:
    filled = {k: v for k, v in _fs(bundle).items() if v}
    if filled:
        return "%d firm-size buckets carry counts (e.g. %s)" \
            % (len(filled), next(iter(filled.items())),)
    return None


def _no_occupation_match(bundle, render_data, draft) -> Optional[str]:
    """The claim is about the ROSTER; re-derive through the same helper
    the warehouse used. Rows coming back means roles DID match - the
    empty chart came from somewhere else (the wage-table join, percentile
    suppression) and must say so, not blame the roster."""
    if not isinstance(draft, dict):
        return "reason not testable - the audit was given no draft row"
    from writing_phase_v2.warehouse import _wage_rows_from_roster
    rows = _wage_rows_from_roster(draft)
    if rows:
        return ("%d roster roles matched occupations: %s"
                % (len(rows), "; ".join("%s -> %s" % (r["client_label"],
                                                      r["soc"])
                                        for r in rows)))
    return None


# figure id -> [(reason prefix, validator)]; prefixes because a figure
# can emit different reasons from different branches.
_VALIDATORS: Dict[str, List[Tuple[str, Callable]]] = {
    "revenue_by_line": [("single line of business", _single_line)],
    "industry_establishments_history": [
        ("no BDS establishment history", _no_bds_history)],
    "headcount_payroll": [
        ("no payroll quarter totals", _no_quarter_totals),
        ("payroll schedule carries no FTE series", _no_fte_series)],
    "capacity_vs_plan_y1": [
        ("no line carries weekly capacity", _no_capacity_line)],
    "marketing_customers": [
        ("no marketing-schedule periods", _no_marketing_periods),
        ("marketing schedule has fewer than four", _fewer_than_four_quarters)],
    "competitor_size_bands": [
        ("no bds_firm_size slice", _no_firm_size_slice),
        ("BDS firm-size buckets empty", _firm_size_empty)],
    "wage_positioning": [
        ("no roster role could be matched", _no_occupation_match)],
}


def audit_absences(report: Dict[str, Dict[str, Any]], *, bundle,
                   render_data=None, draft=None) -> List[str]:
    """Re-tests every absence reason in a render report. Returns gate
    failures: reasons proven FALSE (with the evidence) and reasons no
    validator can test. An empty list means every absence is honest."""
    problems: List[str] = []
    for fid, row in report.items():
        if row.get("placed") or row.get("kind") != "figure":
            continue
        reason = str(row.get("reason") or "")
        if reason.startswith("RENDERER ERROR"):
            continue  # the run-script gate already fails these
        fn = None
        for prefix, cand in _VALIDATORS.get(fid, []):
            if reason.startswith(prefix):
                fn = cand
                break
        if fn is None:
            problems.append(
                "%s: absence reason %r has NO validator - an excuse the "
                "gate cannot test is not a reason" % (fid, reason))
            continue
        evidence = fn(bundle, render_data, draft)
        if evidence:
            problems.append("%s: absence reason %r is FALSE - %s"
                            % (fid, reason, evidence))
    return problems
