"""mini, CW-031 round 10 audit — live turns, my own wordings, rows not replies.

W1  '+'-NAMED GROUP THROUGH THE LIVE ROUTER (item 1's honest gap). Rename a
    Ravenwood clone's product to 'Hard goods + Sundries', then declare a
    group containing it in ordinary client words. Read the rows: label,
    stored member list, basis — and confirm the declaration SURVIVES its own
    call (the round-9 trap).
W2  Same clone, then separate it — the group must clear on both rows and
    the retire must be spoken.
W3  NEAR-MISS RESTATEMENT, live: "Just to confirm, our annual revenue is
    1,548,000" (stored: 1,553,000 — 0.32% off, inside the 0.5% match
    tolerance). If the no-write branch fires, the reply claims a match with
    a figure the client did not state. Read reply AND stored figure.
W4  COINCIDENCE, live, this draft's own numbers: monthly_rent_expense and
    annual_interest_payment are BOTH 9,800. Restate the interest payment;
    walk order hits rent first. Which field does the sentence name?
W5  PEOPLE SCOPE: restate an on-file people_json wage (96,000). The scan
    covers financials+ops only — record the register the client meets.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r10_live.py"
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

import requests
from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env", override=False)
from intake_submission import get_mysql_connection  # type: ignore

SOURCE_DRAFT = "1070c6a560a04f3d971019a3787180bf"
BASE_URL = "http://127.0.0.1:5050"
PLUS_NAME = "Hard goods + Sundries"

conn = get_mysql_connection()
made = []


def clone(rename_hard_goods=False):
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s",
              (SOURCE_DRAFT,))
  src = cur.fetchone()
  cur.close()
  clone_id = "mn" + uuid.uuid4().hex[:30]
  client_id = "MN" + uuid.uuid4().hex[:16].upper()
  if rename_hard_goods:
    o = json.loads(src["operating_model_json"] or "{}")
    for lob in o.get("lob_models", []):
      for p in lob.get("products", []):
        if p.get("product_name") == "Hard goods sale":
          p["product_name"] = PLUS_NAME
    src["operating_model_json"] = json.dumps(o)
  columns = [c for c in src.keys() if c != "id"]
  values = [(clone_id if c == "draft_id" else client_id if c == "client_id"
             else src[c]) for c in columns]
  w = conn.cursor()
  w.execute(f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))})", tuple(values))
  conn.commit()
  w.close()
  made.append(clone_id)
  return clone_id, client_id


def turn(draft_id, client_id, message):
  resp = requests.post(
    f"{BASE_URL}/api/intake-consult",
    json={"draft_id": draft_id, "client_id": client_id, "message": message},
    timeout=300)
  body = resp.json() if resp.status_code == 200 else {}
  return resp.status_code, str(body.get("assistant_message") or "")


def rows_of(draft_id):
  conn.commit()  # REPEATABLE READ: commit first or read a stale snapshot
  cur = conn.cursor()
  cur.execute("SELECT operating_model_json, financials_json "
              "FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))
  ops_j, fin_j = cur.fetchone()
  cur.close()
  o = json.loads(ops_j or "{}")
  out = []
  for lob in o.get("lob_models", []):
    for p in lob.get("products", []):
      out.append({k: p.get(k) for k in (
        "product_name", "cogs_percent_of_line_revenue",
        "cogs_cost_structure_group", "cogs_cost_structure_group_members",
        "cogs_cost_structure_group_basis")})
  return out, json.loads(fin_j or "{}")


findings = []
try:
  # ---- W1 + W2: the '+'-named group, live -----------------------------------
  d1, c1 = clone(rename_hard_goods=True)
  print(f"W1 clone {d1} (product renamed to {PLUS_NAME!r})")
  st, reply = turn(
    d1, c1,
    "Plants and the hard goods and sundries side are both bought-in retail "
    "goods, so treat Plant sale and Hard goods + Sundries as one shared "
    "cost structure at 55 percent. Install project and Design consult keep "
    "their own separate rates.")
  print(f"W1 < [{st}] {reply[:400]}")
  rows, _ = rows_of(d1)
  for r in rows:
    print("W1 row:", r)
  grouped = [r for r in rows
             if r["cogs_cost_structure_group"]
             and PLUS_NAME.lower() in [str(m).strip().lower() for m in
                                       (r["cogs_cost_structure_group_members"]
                                        or [])]]
  plus_row = next((r for r in rows if r["product_name"] == PLUS_NAME), None)
  plant_row = next((r for r in rows if r["product_name"] == "Plant sale"), None)
  if not (plus_row and plus_row["cogs_cost_structure_group"]
          and plant_row and plant_row["cogs_cost_structure_group"]
          == plus_row["cogs_cost_structure_group"]):
    findings.append("W1: the '+'-named declared group did NOT land/survive "
                    "on the live path")
  else:
    ms = plus_row["cogs_cost_structure_group_members"]
    if not (isinstance(ms, list)
            and sorted(str(m).strip().lower() for m in ms)
            == sorted([PLUS_NAME.lower(), "plant sale"])):
      findings.append(f"W1: stored member list wrong: {ms!r}")
    if plus_row["cogs_cost_structure_group_basis"] != "declared":
      findings.append(f"W1: basis {plus_row['cogs_cost_structure_group_basis']!r}"
                      " != 'declared'")
    others = [r for r in rows if r["product_name"] not in
              (PLUS_NAME, "Plant sale")]
    if any(r["cogs_cost_structure_group"] for r in others):
      findings.append("W1: a line OUTSIDE the declaration was grouped")

  st2, reply2 = turn(
    d1, c1,
    "Actually, split those back up - keep Hard goods + Sundries separate "
    "from Plant sale after all.")
  print(f"W2 < [{st2}] {reply2[:400]}")
  rows2, _ = rows_of(d1)
  for r in rows2:
    print("W2 row:", r)
  if any(r["cogs_cost_structure_group"] for r in rows2):
    findings.append("W2: separation left a group standing: "
                    f"{[(r['product_name'], r['cogs_cost_structure_group']) for r in rows2]!r}")
  if any(r["cogs_cost_structure_group_members"] for r in rows2):
    findings.append("W2: a cleared row still carries a stored member list")

  # ---- W3: near-miss restatement --------------------------------------------
  d2, c2 = clone()
  print(f"\nW3 clone {d2}")
  st3, reply3 = turn(
    d2, c2, "Just to confirm, our annual revenue is 1,548,000.")
  print(f"W3 < [{st3}] {reply3[:400]}")
  _, fin3 = rows_of(d2)
  rev3 = fin3.get("current_revenue")
  print(f"W3 stored current_revenue after: {rev3}")
  claims_match = "matches what i have" in reply3.lower()
  landed = rev3 is not None and abs(float(rev3) - 1548000.0) < 1.0
  kept = rev3 is not None and abs(float(rev3) - 1553000.0) < 1.0
  print(f"W3 claims_match={claims_match} landed_correction={landed} "
        f"kept_old={kept}")
  if claims_match and kept:
    findings.append("W3 LIVE: a 1,548,000 correction (stored 1,553,000) was "
                    "answered 'that matches what I have' and the old figure "
                    "kept - a correction swallowed as a confirmation")

  # ---- W4: coincidence, this draft's own 9,800 ------------------------------
  d3, c3 = clone()
  print(f"\nW4 clone {d3}")
  st4, reply4 = turn(
    d3, c3,
    "Just to confirm, our annual interest payment is 9,800.")
  print(f"W4 < [{st4}] {reply4[:400]}")
  _, fin4 = rows_of(d3)
  print(f"W4 stored annual_interest_payment={fin4.get('annual_interest_payment')} "
        f"monthly_rent_expense={fin4.get('monthly_rent_expense')}")
  low4 = reply4.lower()
  if "matches what i have" in low4 and "rent" in low4:
    findings.append("W4 LIVE: restated the interest payment, the match "
                    "sentence named RENT - the coincidence names the "
                    "first-walked leaf, a claim the client never made")

  # ---- W5: people scope -----------------------------------------------------
  st5, reply5 = turn(
    d3, c3,
    "Just to confirm, our operations manager's salary is 96,000 a year.")
  print(f"\nW5 < [{st5}] {reply5[:400]}")
  low5 = reply5.lower()
  print(f"W5 register: match={'matches what i have' in low5} "
        f"failed_change={'wasn''t able to apply' in low5}")

finally:
  for d in made:
    try:
      c = conn.cursor()
      c.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s", (d,))
      conn.commit()
      c.close()
    except Exception:
      pass
  print(f"\n({len(made)} clone(s) removed)")
  try:
    conn.close()
  except Exception:
    pass

print("=" * 78)
if findings:
  print("LIVE FINDINGS:")
  for f in findings:
    print("  -", f)
else:
  print("LIVE: all clean")
