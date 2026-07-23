"""COHERENCE CLOSED-FORM V2 BACKTEST — the Phase-0 gate for the
coherence section build.

The evaluator under test is the SHARED module the live coherence
section imports (client_intake_and_finmo.intake_coherence.evaluator) —
one implementation, proven here, consumed there.

Three proofs, in order of importance:

  1. VERDICTS (intake basis): closed form computed from STATED intake
     facts + the cached margin-band judgment must agree with the
     engine's real outcome on all 7 fleet businesses. Expected FAIL
     when restructure fired or the gate failed; expected PASS otherwise.

  2. CONSERVATISM (engine basis): the same arithmetic core computed on
     each draft's OWN model_input Q1 cost basis at the engine's landed
     Q11 revenue/payroll must never overstate the landed Q11 EBITDA
     margin by more than 1.5pp. The closed form is a floor, not a
     promise — this is the magnitude discipline that keeps "closes 40%
     of your gap" honest.

  3. CORNER (solver basis): for the restructured drafts, the
     NI-favorable corner of the persisted bounds box (prices at market
     ceilings, new lines at caps, costs at floors — the joint solver's
     own seed semantics, on the solver's loaded-cost scale) must agree
     with the restructure outcome: corner PASS where the solver found a
     viable config (final_passed=true), corner FAIL where it proved
     none exists (final_passed=false).

v1 history: flat-dollar costs + fence growth false-passed Understory
(flat costs don't scale with fence revenue) and the monthly*12 G&A
misread false-failed Ironthread (its pre-contract draft stores an
annual figure in the monthly field). v2 fixes both at the basis: costs
are percent-of-revenue (the engine's own treatment), G&A comes from
other_opex_absolute with an explicit legacy accommodation flagged in
the output.
"""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

from client_intake_and_finmo.intake_coherence.evaluator import (
    COVERAGE_FLOOR,
    GROWTH_FENCE_Q11,
    QUARTERLY_DEBT_SERVICE_FACTOR,
    basis_from_intake,
    basis_from_model_input,
    evaluate_structural,
    favorable_corner_basis,
    growth_multiple_from_judged,
    thresholds_from_margin_band,
)

BUSINESSES = [
    ("Sunny_V3", "Sunny Glaze Donuts", 280800),
    ("Glaze", "Sunny Glaze Donuts", 4500),
    ("Blueprint", "Blueprint%", None),
    ("Meridian", "Meridian Motorcars", None),
    ("Understory", "Understory Mushroom", None),
    ("Harvest Lane", "Harvest Lane", None),
    ("Ironthread", "Ironthread", None),
]

# Pre-contract drafts that store an ANNUAL figure in the monthly
# other_operating_expense field (verified against the engine's own
# g_and_a basis). The live app writes other_opex_absolute since the
# G&A root fix; this accommodation exists for legacy drafts only.
LEGACY_ANNUAL_OTHER_OPEX_DRAFTS = {"98a147fd8d0d"}

CONSERVATISM_TOLERANCE_PP = 1.5

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


def _f(d, key, default=0.0):
    try:
        v = d.get(key)
        return default if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return default


def _finmo_rows(fm):
    rows = {}
    for qr in (fm or {}).get("quarter_rows") or []:
        if isinstance(qr, dict):
            try:
                rows[int(float(qr.get("quarter_index")))] = qr
            except (TypeError, ValueError):
                continue
    return rows


def _ops_line_split(ops_json, financials_json):
    """Per-line Q1 quarterly revenue from the ops model's own drivers.
    Returns [] when the shape isn't recognizable (caller falls back to
    a no-price-move aggregate corner)."""
    lines = []
    candidates = []
    for key in ("lines_of_business", "lines", "lobs"):
        v = (ops_json or {}).get(key)
        if isinstance(v, list) and v:
            candidates = v
            break
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        products = entry.get("products") if isinstance(entry.get("products"), list) else [entry]
        for p in products:
            if not isinstance(p, dict):
                continue
            price = _f(p, "unit_price")
            cap = _f(p, "units_per_period_capacity") or _f(p, "units_per_week_capacity")
            util = _f(p, "utilization_rate", 1.0)
            periods = _f(p, "operating_periods_per_year", 12.0)
            if price > 0 and cap > 0:
                lines.append({
                    "lob": entry.get("lob") or entry.get("name") or "",
                    "product": p.get("product") or p.get("name") or "",
                    "annual_revenue": price * cap * util * periods,
                })
    total = sum(l["annual_revenue"] for l in lines)
    if total <= 0:
        return []
    ann_rev = _f(financials_json, "current_revenue") or total
    # scale driver-derived split to the stated anchor (the engine's own
    # rescale keeps these aligned; this guards drift)
    scale = ann_rev / total
    for l in lines:
        l["q1_revenue_quarterly"] = l["annual_revenue"] * scale / 4.0
    return lines


results = {"verdict": [], "conservatism": [], "corner": []}
seen = set()

for label, name, revenue_filter in BUSINESSES:
    cur.execute(
        "SELECT draft_id, business_name, model_input_json, financials_json, finmo_json, "
        "financials_year1_json, operating_model_json, planning_run_json, repair_guidance_json, "
        "updated_at FROM intake_consult_drafts WHERE business_name LIKE %s "
        "ORDER BY updated_at DESC LIMIT 8",
        (name if name.endswith("%") else name + "%",),
    )
    row = None
    for r in cur.fetchall():
        if r["draft_id"] in seen:
            continue
        fin = _j(r.get("financials_json"))
        if revenue_filter is not None and _f(fin, "current_revenue") != float(revenue_filter):
            continue
        if not str(_j(r.get("planning_run_json")).get("planning_run_id") or "").strip():
            continue
        row = r
        break
    if not row:
        print(f"=== {label}: NO DRAFT FOUND ===\n")
        continue
    seen.add(row["draft_id"])
    short_id = row["draft_id"][:12]
    fin = dict(_j(row.get("financials_json")))
    mi = _j(row.get("model_input_json"))
    fm = _j(row.get("finmo_json"))
    ops = _j(row.get("operating_model_json"))
    y1 = _j(row.get("financials_year1_json"))
    rg = _j(row.get("repair_guidance_json"))
    pr = _j(row.get("planning_run_json"))
    mb = (mi.get("solver_input") or {}).get("margin_band_judgment") or {}

    legacy_gna = short_id in LEGACY_ANNUAL_OTHER_OPEX_DRAFTS
    if legacy_gna and not _f(fin, "other_opex_absolute"):
        fin["other_opex_absolute"] = _f(fin, "other_operating_expense")

    # ---------------- 1. VERDICT (intake basis, FENCE) ----------------
    # The gate-entry verdict evaluates at the fence: exists-authorable,
    # including the engine's cost-restatement freedom the closed form
    # can't see (judged-basis entry flips Meridian, whose engine pass
    # came from fitted costs, not growth). The judged multiple governs
    # the WALK tier — its multiple is printed as information here.
    judged = (mi.get("solver_input") or {}).get("judged_growth")
    judged_mult = growth_multiple_from_judged(judged, ops_json=ops)
    basis = basis_from_intake(
        financials_json=fin, ops_json=ops, financials_year1_json=y1,
        growth_to_q11=GROWTH_FENCE_Q11,
    )
    thresholds = thresholds_from_margin_band(mb)
    verdict = evaluate_structural(basis, thresholds) if basis else {
        "passed": False, "failed": ["no_revenue"], "gap_quarterly": None, "q11": {}, "checks": {},
    }

    restructured = bool((rg.get("restructure") or {}))
    gate_passed = bool(pr.get("acceptance_passed")) if "acceptance_passed" in pr else None
    if gate_passed is None:
        from client_intake_and_finmo.post_intake_acceptance.gate import verify_run_acceptance
        v = verify_run_acceptance(
            conn, draft_id=row["draft_id"],
            planning_run_id=str(pr.get("planning_run_id") or "").strip() or None,
        )
        gate_passed = bool(v.get("passed"))
    expected_fail = restructured or not gate_passed
    match = (not verdict["passed"]) if expected_fail else verdict["passed"]
    results["verdict"].append((label, match))

    q11 = verdict.get("q11") or {}
    print(f"=== {label} (draft {short_id}){' [LEGACY G&A basis]' if legacy_gna else ''} ===")
    if basis:
        judged_note = f"  walk-tier judged x{judged_mult:.3f}" if judged_mult else ""
        print(f"  intake basis: q1 rev ${basis.q1_revenue_quarterly:,.0f}/q  cogs {basis.cogs_pct*100:.1f}%  "
              f"payroll ${basis.payroll_quarterly:,.0f}/q  rent ${basis.rent_quarterly:,.0f}/q  "
              f"gna {basis.gna_pct*100:.1f}%  mkt {basis.marketing_pct*100:.1f}%  [{basis.notes.get('revenue_source')}]  "
              f"verdict growth x{GROWTH_FENCE_Q11:.3f} [fence]{judged_note}")
        for cname, c in verdict["checks"].items():
            print(f"    {cname}: {'PASS' if c['passed'] else 'FAIL'} "
                  f"(value {c['value']:,.4f} vs {c['threshold']:,.4f})")
        print(f"  Q11@fence: rev ${q11.get('revenue', 0):,.0f}/q  ebitda ${q11.get('ebitda', 0):,.0f} "
              f"({q11.get('ebitda_margin', 0)*100:.1f}%)  gap ${verdict.get('gap_quarterly') or 0:,.0f}/q")
    print(f"  CLOSED-FORM: {'PASS' if verdict['passed'] else 'FAIL'}  "
          f"expected {'FAIL' if expected_fail else 'PASS'} "
          f"(gate_passed={gate_passed} restructured={restructured})  "
          f"VERDICT AGREEMENT: {'YES' if match else 'NO'}")

    # ---------------- 2. CONSERVATISM (engine basis) ----------------
    rows = _finmo_rows(fm)
    q11_row = rows.get(11)
    if q11_row and mi:
        landed_rev = _f(q11_row, "revenue")
        landed_payroll = _f(q11_row, "payroll")
        landed_ebitda = _f(q11_row, "ebitda")
        if landed_rev > 0:
            eng_basis = basis_from_model_input(
                model_input_json=mi,
                q11_revenue_quarterly=landed_rev,
                q11_payroll_quarterly=landed_payroll,
            )
            if eng_basis:
                eng = evaluate_structural(eng_basis, thresholds)
                closed_m = (eng.get("q11") or {}).get("ebitda_margin", 0.0)
                landed_m = landed_ebitda / landed_rev
                delta_pp = (closed_m - landed_m) * 100.0
                ok = delta_pp <= CONSERVATISM_TOLERANCE_PP
                results["conservatism"].append((label, ok))
                print(f"  engine-basis fidelity: closed {closed_m*100:.1f}% vs landed {landed_m*100:.1f}% "
                      f"(delta {delta_pp:+.1f}pp; conservative bound <= +{CONSERVATISM_TOLERANCE_PP}pp): "
                      f"{'OK' if ok else 'VIOLATED'}")

    # ---------------- 3. CORNER (solver basis) ----------------
    rest = rg.get("restructure") or {}
    bounds = None
    for h in rest.get("history") or []:
        if isinstance(h, dict) and h.get("stage") == "bounds" and isinstance(h.get("bounds"), dict):
            bounds = h["bounds"]
            break
    if bounds and basis:
        final_passed = bool(rest.get("final_passed"))
        split = _ops_line_split(ops, fin)
        if split:
            by_key = {}
            for bl in bounds.get("existing_lines") or []:
                by_key[(str(bl.get("lob") or "").lower(), str(bl.get("product") or "").lower())] = bl
            for l in split:
                bl = by_key.get((str(l["lob"]).lower(), str(l["product"]).lower()))
                if bl is None and len(bounds.get("existing_lines") or []) == 1:
                    bl = (bounds.get("existing_lines") or [{}])[0]
                l["price_multiplier_max"] = float((bl or {}).get("price_multiplier_max") or 1.0)
        # payroll burden factor: engine loaded basis over stated wages
        from client_intake_and_finmo.post_intake_restructure.searcher import _base_levels
        levels = _base_levels(mi) or {}
        stated_annual = _f(fin, "current_payroll") or _f(fin, "payroll_total_year1")
        stated_annual += _f(fin, "owner_compensation") * 12.0
        bf = 1.0
        if stated_annual > 0 and levels.get("annual_payroll"):
            bf = max(1.0, min(2.0, float(levels["annual_payroll"]) / stated_annual))
        corner = favorable_corner_basis(
            basis, bounds,
            existing_line_revenue_split=split or None,
            payroll_burden_factor=bf,
        )
        corner_result = evaluate_structural(corner, thresholds)
        corner_ok = corner_result["passed"] == final_passed
        results["corner"].append((label, corner_ok))
        cq = corner_result.get("q11") or {}
        print(f"  corner (bf {bf:.2f}, lines {'per-line' if split else 'aggregate'}): "
              f"rev ${cq.get('revenue', 0):,.0f}/q  ebitda ${cq.get('ebitda', 0):,.0f} "
              f"({cq.get('ebitda_margin', 0)*100:.1f}%)  corner {'PASS' if corner_result['passed'] else 'FAIL'} "
              f"vs solver final_passed={final_passed}: {'AGREE' if corner_ok else 'DISAGREE'}")
    print()

n_v = len(results["verdict"])
a_v = sum(1 for _, m in results["verdict"] if m)
n_c = len(results["conservatism"])
a_c = sum(1 for _, m in results["conservatism"] if m)
n_k = len(results["corner"])
a_k = sum(1 for _, m in results["corner"] if m)
print(f"VERDICT AGREEMENT: {a_v}/{n_v}")
print(f"CONSERVATISM (closed <= landed +{CONSERVATISM_TOLERANCE_PP}pp): {a_c}/{n_c}")
print(f"CORNER vs SOLVER OUTCOME: {a_k}/{n_k}")
print(f"PHASE-0 GATE: {'PASS' if (a_v == n_v and a_c == n_c and a_k == n_k and n_v == 7) else 'FAIL'}")

cur.close()
conn.close()
