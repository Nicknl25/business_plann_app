"""JUDGMENTS (spec 1.3) - the reasoning about this business, at full length.

Eleven of the fifteen live ONLY in post_intake_gpt_response_store: the draft
row's persisted copies are truncated (500/600/800 chars) and python-reshaped,
so the bundle takes the verbatim GPT payloads - exactly how the reference
was built ("the only recovery is a text search on distinctive phrases",
spec 1.3). The store is keyed by input_hash with no draft_id, so recovery
filters by the draft's run window and each call's discriminator (the CC
tool-call name, or the RA payload's key set), then REFUSES on ambiguity -
two candidate rows for one judgment is a hard error, never a guess.

The other four are verbatim copies out of the draft row.
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Dict, List, Optional, Tuple

STORE = "post_intake_gpt_response_store"

# judgment -> ("cc", tool_call_name) or ("ra", frozenset(required top keys))
_DISCRIMINATORS: Dict[str, Tuple[str, Any]] = {
    "margin_band": ("cc", "submit_margin_band_judgment"),
    "demand_response": ("cc", "submit_demand_response_judgment"),
    "essentials": ("cc", "submit_essentials_judgment"),
    "growth": ("cc", "submit_growth_judgment"),
    "headcount_coherence": ("cc", "submit_headcount_coherence"),
    "working_capital": ("cc", "submit_wc_judgment"),
    "cash_and_capital_structure": ("cc", "submit_cash_judgment"),
    "cost_structure_forecast": ("cc", "submit_cost_structure_forecast"),
    "cogs_fit_proposal_before_owner_correction":
        ("ra", frozenset({"basis_reconciliation", "materials_cogs_percent_band",
                          "per_line_proposals", "proposed_cogs_percent"})),
    "marketing_basis_estimate":
        ("ra", frozenset({"baseline_marketing_percent", "brief_rationale",
                          "expected_units_year1", "reachable_market"})),
    "revenue_path_critique": ("ra", frozenset({"issues", "status"})),
}


def _jl(v):
    if isinstance(v, (dict, list)) or v is None:
        return v
    try:
        return json.loads(v)
    except Exception:
        return None


def _parse_row(text: str):
    """Returns ('cc', tool_name, payload) or ('ra', payload) or None."""
    try:
        j = json.loads(text)
    except Exception:
        return None
    try:
        if "choices" in j:
            tc = j["choices"][0]["message"]["tool_calls"][0]["function"]
            return ("cc", tc["name"], json.loads(tc["arguments"]))
        out = j["output"][0]["content"][0]["text"]
        return ("ra", json.loads(out))
    except Exception:
        return None


def _run_window(draft: Dict[str, Any]) -> Tuple[_dt.datetime, _dt.datetime]:
    start = draft["created_at"] - _dt.timedelta(minutes=5)
    end = draft["updated_at"] + _dt.timedelta(hours=2)
    return start, end


def recover_from_store(conn, draft: Dict[str, Any]) -> Dict[str, Any]:
    lo, hi = _run_window(draft)
    cur = conn.cursor(dictionary=True)
    cur.execute(f"SELECT response_text, created_at FROM {STORE} "
                "WHERE created_at BETWEEN %s AND %s ORDER BY created_at", (lo, hi))
    rows = cur.fetchall()
    found: Dict[str, List[Any]] = {k: [] for k in _DISCRIMINATORS}
    for r in rows:
        p = _parse_row(r["response_text"])
        if p is None:
            continue
        for key, (kind, disc) in _DISCRIMINATORS.items():
            if kind == "cc" and p[0] == "cc" and p[1] == disc:
                found[key].append(p[2])
            elif kind == "ra" and p[0] == "ra" and isinstance(p[1], dict) \
                    and disc <= set(p[1]):
                found[key].append(p[1])
    anchors = _corroboration_anchors(draft)
    out: Dict[str, Any] = {}
    problems: List[str] = []
    for key, hits in found.items():
        uniq = []
        for h in hits:
            if h not in uniq:
                uniq.append(h)
        if len(uniq) > 1:
            # The intake iterates some calls; the ACCEPTED iteration is the
            # one whose content the draft persisted (truncated rationales are
            # PREFIXES of the true text; accepted scalars were copied over).
            scored = [(c, _corroborate(c, anchors)) for c in uniq]
            best = max(s for _, s in scored)
            uniq = [c for c, s in scored if s == best and best > 0]
        if len(uniq) == 1:
            out[key] = uniq[0]
        elif len(uniq) > 1:
            problems.append("%s: %d corroboration-tied candidate store rows "
                            "in the run window - refusing to guess"
                            % (key, len(uniq)))
        # zero hits = the run never made that judgment; absent, not fabricated
    if problems:
        raise LookupError("; ".join(problems))
    return out


def _corroboration_anchors(draft: Dict[str, Any]):
    """Long strings and scalars the intake PERSISTED from the accepted
    iterations - truncated rationales, copied figures."""
    areas = []
    fj = _jl(draft.get("financials_json")) or {}
    areas.append(fj.get("_coherence") or {})
    areas.append(fj.get("_cogs_baseline_resolution") or {})
    areas.append((_jl(draft.get("model_input_json")) or {}).get("solver_input") or {})
    areas.append(_jl(draft.get("marketing_model_json")) or {})
    strings: List[str] = []
    scalars: List[float] = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and len(o) >= 120:
            strings.append(o[:180])
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            scalars.append(float(o))

    for a in areas:
        walk(a)
    return strings, set(scalars)


def _corroborate(candidate: Any, anchors) -> int:
    strings, scalars = anchors
    score = 0

    def walk(o):
        nonlocal score
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and len(o) >= 120:
            if any(o.startswith(a) for a in strings):
                score += 3
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            if float(o) in scalars:
                score += 1

    walk(candidate)
    return score


def build_judgments(conn, draft: Dict[str, Any]) -> Dict[str, Any]:
    mi = _jl(draft.get("model_input_json")) or {}
    pr = _jl(draft.get("planning_run_json")) or {}
    pc = _jl(draft.get("planning_context_summary_json")) or {}
    ms = _jl(draft.get("marketing_schedule_json")) or {}

    store = recover_from_store(conn, draft)
    ordered = ["margin_band", "demand_response", "essentials", "growth",
               "headcount_coherence", "working_capital",
               "cash_and_capital_structure", "cost_structure_forecast",
               "cogs_fit_proposal_before_owner_correction",
               "marketing_basis_estimate", "revenue_path_critique"]
    out: Dict[str, Any] = {k: store[k] for k in ordered if k in store}

    fsp = ((pr.get("post_cascade_completion") or {}).get("cash_pass") or {}) \
        .get("funding_source_policy")
    if fsp is not None:
        out["funding_source_policy"] = fsp
    lsd = (mi.get("solver_input") or {}).get("labor_scaling_directive")
    if lsd is not None:
        out["labor_scaling_directive"] = lsd
    srr = (pc.get("stage_ramp_contract") or {}).get("rationale")
    if srr is not None:
        out["stage_ramp_rationale"] = srr
    if ms.get("assumptions") is not None:
        out["retention_assumption"] = ms["assumptions"]
    return out
