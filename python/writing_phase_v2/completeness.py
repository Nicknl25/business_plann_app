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


def _product_year1_revenue(p) -> Optional[float]:
    """A product's Year-1 revenue, however the draft carries it: stored
    directly, via annual units, or derived from price x weekly capacity
    x utilization x operating periods - the same arithmetic the plan's
    own product table shows the client."""
    rev = p.get("revenue_total_year1")
    if rev:
        return float(rev)
    price = p.get("unit_price")
    if not price:
        return None
    units = p.get("annual_units_year1")
    if units:
        return float(price) * float(units)
    cap = p.get("units_per_week_capacity") or p.get("units_per_period_capacity")
    util = p.get("utilization_rate")
    periods = p.get("operating_periods_per_year") or p.get("operating_weeks_per_year")
    if cap and util and periods:
        return float(price) * float(cap) * float(util) * float(periods)
    return None


def revenue_streams(bundle) -> List[Tuple[str, Any]]:
    """Every priced revenue stream the record carries, with Year-1
    revenue. financials_year1 when present; the OPERATING MODEL's
    products otherwise - the source the writer's own product table
    reads. ONE definition, shared by the chart renderer and this gate:
    counting a different source than the page is how Sunny's false
    'single line of business' passed the first reason gate (two products
    in Table 1, zero lobs in financials_year1)."""
    rec = bundle.get("record") or {}
    out: List[Tuple[str, Any]] = []
    for lob in (rec.get("financials_year1") or {}).get("lobs") or []:
        prods = lob.get("products") or []
        if prods:
            for p in prods:
                out.append((str(p.get("product_name") or lob.get("lob_name")
                                or "line"), _product_year1_revenue(p)))
        else:
            out.append((str(lob.get("lob_name") or "line"),
                        lob.get("revenue_total_year1")))
    if out:
        return out
    for lob in (rec.get("operating_model") or {}).get("lob_models") or []:
        for p in lob.get("products") or []:
            out.append((str(p.get("product_name") or lob.get("lob_name")
                            or "line"), _product_year1_revenue(p)))
    return out


def capacity_lines(bundle) -> List[Tuple[str, float, float]]:
    """(name, weekly capacity, utilization) per product - same fallback
    order as revenue_streams, same reason."""
    rec = bundle.get("record") or {}
    for source in ((rec.get("financials_year1") or {}).get("lobs"),
                   (rec.get("operating_model") or {}).get("lob_models")):
        out = []
        for lob in source or []:
            for p in lob.get("products") or []:
                wk = p.get("units_per_week_capacity")
                u = p.get("utilization_rate")
                if wk and u:
                    out.append((str(p.get("product_name")
                                    or lob.get("lob_name") or "Line"),
                                float(wk), float(u)))
        if out:
            return out
    return []


def _single_line(bundle, render_data, draft) -> Optional[str]:
    streams = revenue_streams(bundle)
    priced = [(n, v) for n, v in streams if v]
    if len(priced) >= 2:
        return ("the business carries %d priced revenue streams: %s"
                % (len(priced),
                   "; ".join("%s at %.0f/yr" % (n, v) for n, v in priced)))
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
    lines = capacity_lines(bundle)
    if lines:
        n, wk, u = lines[0]
        return ("%r carries units_per_week_capacity=%s utilization_rate=%s"
                % (n, wk, u))
    return None


def _mkt_periods(render_data):
    return [p for p in ((render_data or {}).get("marketing_periods") or [])
            if not p.get("is_stub")]


def _no_marketing_periods(bundle, render_data, draft) -> Optional[str]:
    # a claim the audit had no data to test is not a claim that HOLDS
    # (2026-09-11, the same law _no_occupation_match states): render_data
    # comes back None when the run could not read render_data.json at all.
    if render_data is None:
        return "reason not testable - the audit was given no renderer data"
    periods = _mkt_periods(render_data)
    if periods:
        return "renderer data carries %d marketing periods" % len(periods)
    return None


def _fewer_than_four_quarters(bundle, render_data, draft) -> Optional[str]:
    if render_data is None:
        return "reason not testable - the audit was given no renderer data"
    periods = _mkt_periods(render_data)
    y1 = [p for p in periods if 0 < int(p.get("period_index") or 0) <= 4]
    if len(y1) >= 4:
        return "the first projection year holds %d quarters" % len(y1)
    return None


# THE BDS FIRM-SIZE BAND VOCABULARY. ONE definition, shared with
# render_charts.py the way revenue_streams is: the renderer carried its own
# map, stale since the BDS load moved to ten buckets, and every key it did
# not recognise was dropped SILENTLY - Oswin plotted 18,562 of 19,014 firms,
# Pelletier 142,990 of 151,242, both under a title claiming every U.S. firm
# in the trade (2026-09-11). These ten keys are the vocabulary the table
# actually supplies; the top four fold into one 1,000+ band.
FIRM_SIZE_LABELS: Dict[str, str] = {
    "a) 1 to 4": "1–4",
    "b) 5 to 9": "5–9",
    "c) 10 to 19": "10–19",
    "d) 20 to 99": "20–99",
    "e) 100 to 499": "100–499",
    "f) 500 to 999": "500–999",
    "g) 1000 to 2499": "1,000+",
    "h) 2500 to 4999": "1,000+",
    "i) 5000 to 9999": "1,000+",
    "j) 10000+": "1,000+",
}
FIRM_SIZE_ORDER: List[str] = ["1–4", "5–9", "10–19", "20–99", "100–499",
                              "500–999", "1,000+"]
# headcount ranges for the same bands, in the same order - they must TILE:
# a business of 40 people had no band to stand in while the ranges still
# said 20-49/50-99 against buckets that no longer exist.
FIRM_SIZE_RANGES: List[Tuple[int, int]] = [(1, 4), (5, 9), (10, 19), (20, 99),
                                           (100, 499), (500, 999),
                                           (1000, 10 ** 9)]


def firm_size_bands(fs) -> Tuple[Dict[str, int], List[str]]:
    """(band label -> firms, unrecognised bucket keys). An unknown key is
    NEVER dropped - it comes back so the caller refuses to draw a chart
    that omits firms rather than quietly drawing a short one."""
    agg: Dict[str, int] = {}
    unknown: List[str] = []
    for k, v in (fs or {}).items():
        lb = FIRM_SIZE_LABELS.get(k)
        if lb is None:
            unknown.append(str(k))
            continue
        agg[lb] = agg.get(lb, 0) + (v or 0)
    return agg, sorted(unknown)


def _fs_slice(bundle):
    """The firm-size envelope AS CARRIED: None only when the key is truly
    absent from the warehouse. An envelope holding no buckets is PRESENT -
    that difference is the whole of the Halvorsen ruling below."""
    return (bundle.get("warehouse") or {}).get("bds_firm_size_2023")


def _fs(bundle):
    return (_fs_slice(bundle) or {}).get("firms_by_size") or {}


def _no_firm_size_slice(bundle, render_data, draft) -> Optional[str]:
    """THE CLAIM IS ABSENCE (Nick 2026-09-11: 'a reason must be tested
    against the claim, not against its own condition'). This validator used
    to re-run the renderer's emptiness guard, so Halvorsen Tide's bundle
    passed the gate carrying the slice it said was missing -
    {"naics4":"1125","year":2023,"source":"Census BDS","firms_by_size":{}} -
    while the Competitive Landscape beside it cited 125 Massachusetts
    establishments from the same warehouse. An envelope in the bundle makes
    this reason false whatever it holds; present-but-empty is a DIFFERENT
    claim, validated by _firm_size_empty."""
    sl = _fs_slice(bundle)
    if sl is None:
        return None
    fs = (sl or {}).get("firms_by_size") or {}
    return ("the bundle DOES carry bds_firm_size_2023 (naics4=%s, %d "
            "buckets)%s" % (sl.get("naics4"), len(fs),
                            "" if fs else " - present but empty is a "
                            "different claim, not a missing slice"))


def _firm_size_empty(bundle, render_data, draft) -> Optional[str]:
    """The claim: NO trade code available to the lookup has BDS firm-size
    coverage. Tested against the other codes, never against the one bucket
    dict the renderer happened to read - Census BDS excludes crop and animal
    production, so 1125 has no rows while 4244, the same business's second
    code, has ten (Halvorsen Tide 2026-09-11). bds_2023 carries
    share_firms_under_5/_10 only when bds_firm_size returned rows for that
    code, so a share on any code is direct proof the coverage exists."""
    filled = {k: v for k, v in _fs(bundle).items() if v}
    if filled:
        return "%d firm-size buckets carry counts (e.g. %s)" \
            % (len(filled), next(iter(filled.items())),)
    sl = _fs_slice(bundle) or {}
    tried = {str(c) for c in (sl.get("naics4_tried")
                              or ([sl["naics4"]] if sl.get("naics4") else []))}
    bds = (bundle.get("warehouse") or {}).get("bds_2023") or {}
    for code, grp in bds.items():
        if ((grp or {}).get("share_firms_under_5") is not None
                or (grp or {}).get("share_firms_under_10") is not None):
            return ("bds_2023[%s] carries firm-size shares, so bds_firm_size "
                    "HAS rows for that trade code - the lookup tried %s"
                    % (code, ", ".join(sorted(tried)) or "no code"))
    untried = sorted(str(c) for c in bds if str(c) not in tried)
    if untried:
        return ("the lookup only tried %s; the bundle's own BDS rows cover "
                "%s, never asked for"
                % (", ".join(sorted(tried)) or "no code", ", ".join(untried)))
    return None


def _firm_size_bucket_unknown(bundle, render_data, draft) -> Optional[str]:
    """The claim names bucket keys the shared vocabulary does not cover.
    False if every key the bundle carries maps - the absence would then be
    hiding a renderer bug, not a data/code contract break."""
    fs = _fs(bundle)
    agg, unknown = firm_size_bands(fs)
    if unknown:
        return None
    return ("every one of the %d firm-size buckets maps to a band (%s) - "
            "the figure had no unmapped key to refuse"
            % (len(fs), ", ".join(sorted(agg)) or "none"))


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
        ("BDS firm-size buckets empty", _firm_size_empty),
        ("BDS firm-size bucket not in the label map",
         _firm_size_bucket_unknown)],
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
