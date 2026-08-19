"""ABLATION BATCH A common loader. Read-only DB access; all ablations
are in-memory monkeypatches in the calling scripts. Never writes."""
import json
import sys

import mysql.connector

sys.path.insert(0, "C:/dev/business_plann_app/python")

DRAFTS = {
    "Peachtree": "f62e846077ef40ca96f37edafb97a6fe",
    "Meridian": "adf1090bf87d446c80ee3b81d10ce273",
    "Glaze": "cc8b7081adec47b4b79f33a6231beb26",
}


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


def load_drafts():
    conn = mysql.connector.connect(
        host="localhost", user="root", password="Lovers251979!",
        database="biz_plan_revert", autocommit=True,
    )
    cur = conn.cursor(dictionary=True)
    out = {}
    for label, did in DRAFTS.items():
        cur.execute(
            "SELECT draft_id, business_name, operating_model_json, financials_json, "
            "financials_year1_json, model_input_json, repair_guidance_json, "
            "planning_convergence_json "
            "FROM intake_consult_drafts WHERE draft_id=%s",
            (did,),
        )
        r = cur.fetchone()
        if not r:
            out[label] = None
            continue
        fin = _j(r.get("financials_json"))
        mi = _j(r.get("model_input_json"))
        si = mi.get("solver_input") or {}
        out[label] = {
            "draft_id": did,
            "business_name": r.get("business_name"),
            "ops": _j(r.get("operating_model_json")),
            "fin": fin,
            "fy1": _j(r.get("financials_year1_json")),
            "mi": mi,
            "band": si.get("margin_band_judgment") or None,
            "judged_growth": si.get("judged_growth") or None,
            "coherence_state": fin.get("_coherence") or {},
            "repair_guidance": _j(r.get("repair_guidance_json")),
            "planning_convergence": _j(r.get("planning_convergence_json")),
        }
    cur.close()
    conn.close()
    return out


def growth_mult_for(d):
    from client_intake_and_finmo.intake_coherence.evaluator import (
        growth_multiple_from_judged,
    )
    return growth_multiple_from_judged(d["judged_growth"], ops_json=d["ops"])
