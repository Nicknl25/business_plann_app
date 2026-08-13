"""ABLATION BATCH B — B1..B6 in-memory monkeypatch ablations on real stored runs.

No file under python/ is modified. Constants are patched on the imported
modules and restored in finally blocks.
"""
import os, sys, json, copy, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from dotenv import load_dotenv
load_dotenv(os.path.join(HERE, "..", ".env"))
import mysql.connector

import client_intake_and_finmo.post_intake_acceptance.gate as G
import client_intake_and_finmo.post_intake_realism.formulas as F
import client_intake_and_finmo.post_intake_viability.policy as VP
from client_intake_and_finmo.post_intake_viability.adapter import evaluate_run_viability

DRAFTS = {
    "Peachtree": "f62e846077ef40ca96f37edafb97a6fe",
    "Sunny_A": "29c4a053b9f64ab3aad10fbcf5256674",
    "Sunny_B": "a7ae3c0bb8fd42fd9c1e1b1714012e09",
}

def j(raw):
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "ignore")
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
DATA = {}
for name, did in DRAFTS.items():
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (did,))
    d = cur.fetchone() or {}
    cur.execute(
        "SELECT * FROM planning_runs WHERE draft_id=%s AND current_stage=%s ORDER BY started_at DESC LIMIT 1",
        (did, "post_intake_finalize_validation_completed"),
    )
    pr = cur.fetchone() or {}
    DATA[name] = {
        "draft": d,
        "fin": j(d.get("finmo_json")),
        "mi": j(d.get("model_input_json")),
        "memo": j(d.get("realism_memo_json")),
        "prj": j(d.get("planning_run_json")),
        "pr": pr,
        "av": j(pr.get("acceptance_verdict_json")),
    }
cur.close(); conn.close()

def strip_judgment(mi):
    mi2 = copy.deepcopy(mi)
    si = mi2.get("solver_input")
    if isinstance(si, dict):
        si.pop("margin_band_judgment", None)
    return mi2

SEP = "=" * 78

# ---------------------------------------------------------------- B1
print(SEP); print("B1  revenue-not-flat  (CV>=0.02 OR Q10/Q1 delta>=0.05, series Q1..Q10)")
for name, D in DATA.items():
    ok, det = G._check_revenue_not_flat(D["fin"])
    cv, delta = det["stdev_over_mean"], det["q10_over_q1_delta"]
    print(f"  {name}: pass={ok} cv={cv:.4f} (thr 0.02, margin {cv-0.02:+.4f}) "
          f"delta={delta:.4f} (thr 0.05, margin {delta-0.05:+.4f})")
    # flip search: what thresholds would fail this run? (need BOTH to fail)
    print(f"    to fail this run: need cv_thr>{cv:.4f} AND delta_thr>{delta:.4f}")

# boundary: flat-taper growth g per quarter, series (1+g)^(q-1), q=1..10
def series_stats(g):
    s = [(1.0 + g) ** (q - 1) for q in range(1, 11)]
    m = sum(s) / len(s)
    cv = statistics.pstdev(s) / m
    delta = s[-1] / s[0] - 1.0
    return cv, delta

print("  boundary sweep (constant qoq growth g):")
lo, hi = 0.0, 0.02
for _ in range(60):
    mid = (lo + hi) / 2
    cv, delta = series_stats(mid)
    if cv >= 0.02 or delta >= 0.05:
        hi = mid
    else:
        lo = mid
gstar = (lo + hi) / 2
cv_s, del_s = series_stats(gstar)
print(f"    check fails for qoq growth < {gstar:.6f} ({gstar*100:.3f}%/q, "
      f"annual {( (1+gstar)**4-1)*100:.2f}%); at boundary cv={cv_s:.4f} delta={del_s:.4f}")
for g in (0.002, 0.004, 0.00567, 0.006, 0.0074, 0.01):
    cv, delta = series_stats(g)
    print(f"    g={g:.4f}/q (annual {((1+g)**4-1)*100:5.2f}%): cv={cv:.4f} delta={delta:.4f} "
          f"pass={cv>=0.02 or delta>=0.05}")
for name, D in DATA.items():
    jg = ((D["mi"].get("solver_input") or {}).get("judged_growth") or {})
    print(f"  {name} judged_growth qoq_start={jg.get('qoq_start')} qoq_end={jg.get('qoq_end')}")

# ---------------------------------------------------------------- B2
print(SEP); print("B2  balance-sheet growth plausible (cash/AR/inv <= 5.0x Q20 quarter opex)")
for name, D in DATA.items():
    ok, det = G._check_balance_sheet_growth_plausible(D["fin"])
    print(f"  {name}: pass={ok} cash_x={det.get('q20_cash_to_quarter_opex')} "
          f"ar_x={det.get('q20_ar_to_quarter_opex')} inv_x={det.get('q20_inventory_to_quarter_opex')}")
    orig = G._BALANCE_SHEET_GROWTH_RATIO_THRESHOLD
    for t in (2.0, 10.0):
        G._BALANCE_SHEET_GROWTH_RATIO_THRESHOLD = t
        try:
            ok2, _ = G._check_balance_sheet_growth_plausible(D["fin"])
        finally:
            G._BALANCE_SHEET_GROWTH_RATIO_THRESHOLD = orig
        print(f"    threshold={t}: pass={ok2}" + ("  <-- FLIP" if ok2 != ok else ""))

# ---------------------------------------------------------------- B3
print(SEP); print("B3  NI trajectory viable (ramping delta>=0.02 OR flat q11>=floor)")
for name, D in DATA.items():
    for label, mi in (("judged", D["mi"]), ("stripped", strip_judgment(D["mi"]))):
        ok, det = G._check_net_income_trajectory_viable(D["fin"], mi)
        print(f"  {name} [{label}]: pass={ok} q5m={det['q5_ni_margin']} q11m={det['q11_ni_margin']} "
              f"delta={det['q5_to_q11_delta']} ramp={det['ramping_viable']} flat={det['flat_healthy_viable']} "
              f"floor={det['min_required_q11_margin_flat']} src={det['flat_floor_source']}")
    # ablate delta constant
    base_ok, base_det = G._check_net_income_trajectory_viable(D["fin"], D["mi"])
    o1 = G._NI_TRAJECTORY_MIN_DELTA_Q5_TO_Q11
    for v in (0.001, 0.05, 0.10):
        G._NI_TRAJECTORY_MIN_DELTA_Q5_TO_Q11 = v
        try:
            ok2, det2 = G._check_net_income_trajectory_viable(D["fin"], D["mi"])
        finally:
            G._NI_TRAJECTORY_MIN_DELTA_Q5_TO_Q11 = o1
        print(f"    delta_min={v}: pass={ok2} (ramp={det2['ramping_viable']} flat={det2['flat_healthy_viable']})"
              + ("  <-- FLIP" if ok2 != base_ok else ""))
    # ablate flat-floor constant under judged AND stripped
    o2 = G._NI_Q11_HEALTHY_FLAT_MARGIN_FLOOR
    for v in (0.001, 0.05, 0.10):
        G._NI_Q11_HEALTHY_FLAT_MARGIN_FLOOR = v
        try:
            okj, _ = G._check_net_income_trajectory_viable(D["fin"], D["mi"])
            oks, dets = G._check_net_income_trajectory_viable(D["fin"], strip_judgment(D["mi"]))
        finally:
            G._NI_Q11_HEALTHY_FLAT_MARGIN_FLOOR = o2
        print(f"    flat_floor_const={v}: judged pass={okj} | stripped pass={oks} "
              f"(stripped flat={dets['flat_healthy_viable']})")

# ---------------------------------------------------------------- B4
print(SEP); print("B4  realism trajectory formulas: judged vs stripped, then ablations (pass = value>=0)")
FKEYS = {
    "recovery_trend": "trajectory_ebitda_recovery_trend",
    "q20_holds": "trajectory_ebitda_q20_holds_or_improves_vs_q11",
    "gm_supports": "trajectory_gross_margin_supports_recovery",
    "fixed_burden": "trajectory_fixed_cost_burden_at_industry_floor",
}
def run_formulas(mi, fin):
    out = {}
    for short, fk in FKEYS.items():
        v = F.evaluate_realism_formula(fk, model_input_json=mi, finmo_json=fin)
        out[short] = None if v is None else round(float(v), 5)
    return out

for name, D in DATA.items():
    rj = run_formulas(D["mi"], D["fin"])
    rs = run_formulas(strip_judgment(D["mi"]), D["fin"])
    print(f"  {name} judged : {rj}")
    print(f"  {name} stripped: {rs}")
    # raw margins for context
    q5 = F._quarter_ebitda_margin(D["fin"], 5); q11 = F._quarter_ebitda_margin(D["fin"], 11)
    q20 = F._quarter_ebitda_margin(D["fin"], 20); gm11 = F._quarter_gross_margin(D["fin"], 11)
    print(f"    ebitda m: q5={q5:.4f} q11={q11:.4f} q20={q20:.4f}; gm q11={gm11:.4f}")
    # ablations (both modes)
    ABL = [
        ("_EBITDA_HEALTHY_FLAT_FLOOR", [0.001, 0.10, 0.30]),
        ("_EBITDA_HEALTHY_RETENTION_FRACTION", [0.1, 0.9, 1.2]),
        ("_EBITDA_Q20_HOLDS_OR_IMPROVES_TOLERANCE", [0.0, 0.05, -0.01]),
        ("_GROSS_MARGIN_RECOVERY_FLOOR", [0.05, 0.5, 0.9]),
        ("_FIXED_COST_BURDEN_INDUSTRY_MAX", [0.3, 0.9]),
    ]
    for const, vals in ABL:
        orig = getattr(F, const)
        for v in vals:
            setattr(F, const, v)
            try:
                aj = run_formulas(D["mi"], D["fin"])
                a_s = run_formulas(strip_judgment(D["mi"]), D["fin"])
            finally:
                setattr(F, const, orig)
            flips_j = [k for k in aj if aj[k] is not None and rj[k] is not None and (aj[k] >= 0) != (rj[k] >= 0)]
            flips_s = [k for k in a_s if a_s[k] is not None and rs[k] is not None and (a_s[k] >= 0) != (rs[k] >= 0)]
            moved_j = [k for k in aj if aj[k] != rj[k]]
            moved_s = [k for k in a_s if a_s[k] != rs[k]]
            print(f"    {const}={v}: judged moved={moved_j} FLIPS={flips_j} | "
                  f"stripped moved={moved_s} FLIPS={flips_s}")

# ---------------------------------------------------------------- B5
print(SEP); print("B5  viability standard offline rerun + PASS_REFINE_THRESHOLD ablation")
for name, D in DATA.items():
    stored = (D["av"] or {}).get("viability_standard") or {}
    print(f"  {name} STORED: verdict={stored.get('verdict')} tier1={stored.get('tier1_score')} "
          f"thr={stored.get('pass_refine_threshold')} notes={stored.get('notes')}")
    for thr in (0.45, 0.55, 0.65):
        orig = VP.PASS_REFINE_THRESHOLD
        VP.PASS_REFINE_THRESHOLD = thr
        try:
            res = evaluate_run_viability(
                finmo_json=D["fin"], draft=D["draft"], model_input_json=D["mi"],
                planning_run_json=D["prj"],
            )
        finally:
            VP.PASS_REFINE_THRESHOLD = orig
        print(f"    rerun thr={thr}: verdict={res.get('verdict')} tier1={res.get('tier1_score')} "
              f"gates_all_pass={(res.get('gates') or {}).get('all_pass')} notes={res.get('notes')}")

# ---------------------------------------------------------------- B6
print(SEP); print("B6  ebitda_margin band rows in realism memo: which floor bound?")
for name, D in DATA.items():
    results = (D["memo"] or {}).get("results") or []
    mbj = ((D["mi"].get("solver_input") or {}).get("margin_band_judgment") or {})
    print(f"  {name}: judged q11_low={((mbj.get('q11') or {}).get('low'))} q20_low={((mbj.get('q20') or {}).get('low'))}")
    n = 0
    for r in results:
        if not isinstance(r, dict):
            continue
        if str(r.get("metric_key")) not in ("ebitda_margin", "net_income_margin"):
            continue
        n += 1
        if n > 40: break
        print(f"    q={r.get('quarter_index')} {r.get('metric_key')}: actual={r.get('actual')} "
              f"min={r.get('effective_min')} max={r.get('effective_max')} "
              f"floor={r.get('planning_mode_floor')} src={r.get('band_source')} status={r.get('status')}")
    if n == 0:
        print("    sample result keys:", list(results[0].keys()) if results else "EMPTY",
              "metric_keys:", sorted({str(r.get('metric_key')) for r in results if isinstance(r, dict)})[:30])
print("done")
