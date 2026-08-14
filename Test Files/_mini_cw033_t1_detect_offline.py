"""mini CW-033: WHY did D1's wording land mid-interview with no redirect?

Runs the redirect's own detector (_apply_cross_section_driver_correction,
detect-only, exactly as the wrapper calls it) on: my D1 wording, VS's
verbatim [99]/[107]/[111], my A4 price wording. If mine returns no
triggered_leaf while the live forward move landed the same message, the
redirect detector is NARROWER than the lander - the off-path back door.

Also reads the real Sumac row cadence for the D3 cadence finding.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env", override=False)
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from api_handlers import intake_consult as ic  # noqa: E402
from intake_submission import get_mysql_connection  # noqa: E402

THORN = "d9b17850350545e9911fa09b3e333429"
SUMAC = "2ecc759c5d934706ad95123831f9e0c2"

conn = get_mysql_connection()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT operating_model_json, messages_json FROM intake_consult_drafts "
            "WHERE draft_id=%s", (THORN,))
row = cur.fetchone()
ops = json.loads(row["operating_model_json"] or "{}")
msgs = json.loads(row["messages_json"] or "[]")
M99 = str(msgs[99].get("content"))
M107 = str(msgs[107].get("content"))
M111 = str(msgs[111].get("content"))

WORDINGS = [
    ("MY-D1", "Hang on, one fix on operations - the install crew can "
              "actually do 7 jobs a week, not 5. Please update that."),
    ("MY-A4", "One more thing - bump the hard goods ticket price to 99 "
              "instead of 95."),
    ("VS-99", M99),
    ("VS-107", M107),
    ("VS-111", M111),
]
for tag, wording in WORDINGS:
    rep: dict = {}
    try:
        res = ic._apply_cross_section_driver_correction(
            ops_json=copy.deepcopy(ops), user_message=wording, report=rep)
    except Exception as exc:  # noqa: BLE001
        res = f"RAISED {exc!r}"
    print(f"{tag}: triggered_leaf={rep.get('triggered_leaf')!r} "
          f"report_keys={sorted(rep.keys())}")
    print(f"   report={ {k: (str(v)[:120]) for k, v in rep.items()} }")

print()
cur.execute("SELECT operating_model_json FROM intake_consult_drafts "
            "WHERE draft_id=%s", (SUMAC,))
o2 = json.loads((cur.fetchone() or {}).get("operating_model_json") or "{}")
for lob in o2.get("lob_models") or []:
    for p in lob.get("products") or []:
        print("SUMAC row:", {k: p.get(k) for k in (
            "product_name", "unit_cadence", "operating_periods_per_year",
            "units_per_week_capacity", "units_per_period_capacity",
            "unit_price", "utilization_rate")})
cur.close()
conn.close()
