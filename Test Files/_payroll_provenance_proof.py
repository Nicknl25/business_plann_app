"""FLEET PROOF for the payroll provenance stamp (#1).

Three assertions per fleet business:
  1. IDENTITY: landed Payroll row == Q1 roster wages x (1 + benefits_pct)
     within 0.1% — the deliberate load, reconstructed from the stored
     schedule payload (the before/after table: numbers UNCHANGED).
  2. NEUTRALITY: running the NEW apply function on the stored payload +
     model_input leaves every Payroll value byte-identical.
  3. STAMP: the new run writes solver_input.payroll_provenance whose
     arithmetic reconciles stated -> roster -> loaded -> landed.
Read-only against the DB; apply runs on deep copies in-process."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

from client_intake_and_finmo.post_intake_headcount.schedule import (
    apply_payroll_headcount_payload_to_model_input,
)
from client_intake_and_finmo.post_intake_sequence import post_intake_sequence_step_scope

DRAFTS = [
    ("Sunny_V3", "ee7cd6b20cc1"),
    ("Blueprint", "49181987acf2"),
    ("Meridian", "0f8e1e1c5d8d"),
    ("Harvest Lane", "9408bd78c98f"),
    ("Ironthread", "98a147fd8d0d"),
    ("Understory", "ea30f6dc2378"),
    ("Redux", "17d8793b08b5"),
]

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


def payroll_values(mi):
    for row in ((mi.get("sections") or {}).get("expenses") or []):
        if isinstance(row, dict) and str(row.get("label") or "").strip() == "Payroll":
            return list(row.get("values") or [])
    return []


ok_all = True
print(f"{'business':14} {'stated':>12} {'roster wages':>13} {'pct':>6} {'loaded calc':>12} "
      f"{'landed (before)':>15} {'landed (after)':>15} {'identity':>9} {'neutral':>8} {'stamp':>6}")
for label, prefix in DRAFTS:
    cur.execute(
        "SELECT financials_json, model_input_json, payroll_headcount FROM intake_consult_drafts "
        "WHERE draft_id LIKE %s ORDER BY updated_at DESC LIMIT 1", (prefix + "%",))
    r = cur.fetchone()
    if not r:
        print(f"{label:14} NOT FOUND")
        ok_all = False
        continue
    fin = _j(r.get("financials_json"))
    mi = _j(r.get("model_input_json"))
    payload = _j(r.get("payroll_headcount"))
    stated = float(fin.get("current_payroll") or 0.0)
    values_before = payroll_values(mi)
    landed_before = float(values_before[1]) * 4.0 if len(values_before) > 1 else 0.0

    # 1. identity from the stored payload rows
    q1_wages = 0.0
    pcts = set()
    for row in (payload.get("rows") or []):
        if not isinstance(row, dict):
            continue
        try:
            if int(float(row.get("quarter_index") or 0)) != 1:
                continue
            fte = float(row.get("ending_fte") if row.get("ending_fte") is not None
                        else (row.get("starting_fte") or 0.0))
            wage = float(row.get("annual_wage") or 0.0)
        except (TypeError, ValueError):
            continue
        q1_wages += max(0.0, fte) * max(0.0, wage)
        if row.get("payroll_taxes_benefits_percent") is not None:
            pcts.add(round(float(row.get("payroll_taxes_benefits_percent")), 4))
    pct = sorted(pcts)[0] if len(pcts) == 1 else (sorted(pcts)[-1] if pcts else 0.22)
    loaded_calc = q1_wages * (1.0 + pct)
    identity_ok = landed_before > 0 and abs(loaded_calc - landed_before) / landed_before < 0.001

    # 2+3. neutrality + stamp via the NEW apply on deep copies
    neutral_ok = stamp_ok = False
    landed_after = landed_before
    try:
        live_count = sum(1 for item in (payload.get("quarter_totals") or []) if isinstance(item, dict))
        with post_intake_sequence_step_scope(
            step_key="payroll_headcount_schedule",
            phase="post_intake_target_seeking",
            executor_function="payroll_provenance_proof",
        ):
            mi_after = apply_payroll_headcount_payload_to_model_input(
                json.loads(json.dumps(mi)),
                json.loads(json.dumps(payload)),
                live_count=max(1, live_count),
                stated_annual_wages=stated or None,
            )
        values_after = payroll_values(mi_after)
        landed_after = float(values_after[1]) * 4.0 if len(values_after) > 1 else 0.0
        neutral_ok = values_after == values_before
        prov = ((mi_after.get("solver_input") or {}).get("payroll_provenance")) or {}
        stamp_ok = (
            bool(prov)
            and abs(float(prov.get("q1_roster_annual_wages") or 0.0) - q1_wages) < 1.0
            and prov.get("q1_landed_annual_loaded") is not None
            and (stated <= 0 or prov.get("stated_annual_wages") == round(stated, 2))
        )
    except Exception as exc:  # noqa: BLE001
        print(f"{label:14} APPLY ERROR: {type(exc).__name__}: {str(exc)[:140]}")
        ok_all = False
        continue

    ok = identity_ok and neutral_ok and stamp_ok
    ok_all = ok_all and ok
    print(f"{label:14} {stated:>12,.0f} {q1_wages:>13,.0f} {pct:>6.2f} {loaded_calc:>12,.0f} "
          f"{landed_before:>15,.0f} {landed_after:>15,.0f} {'OK' if identity_ok else 'FAIL':>9} "
          f"{'OK' if neutral_ok else 'FAIL':>8} {'OK' if stamp_ok else 'FAIL':>6}")

print()
print("FLEET PROOF:", "PASS - numbers unchanged on every business; every landed line "
      "traceable as roster wages x (1+benefits_pct); provenance stamped" if ok_all else "FAIL")
cur.close()
conn.close()
