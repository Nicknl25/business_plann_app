"""mini, CW-031 round 11 audit -- part B: DECLARATIVE restatements aimed at
the deterministic no-write match branch (round 10's B1 shape; questions
route to the answer path and never reach it -- part A proved that).

B1  "Just to confirm, our annual interest payment is 9,800."  (ambiguous:
    rent==interest)  -> expect the bare-value sentence, NO field name.
B2  "Just to confirm, our direct costs for the year came to 729,910."
    (derived twin cogs_total_year1==current_cogs) -> expect bare value.
B3  "Just to confirm, our other monthly debt payments are 3,100."
    (unique leaf) -> expect the named sentence.
Rows are read after every turn: a restatement must never CHANGE the state.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r11_live_b.py"
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

conn = get_mysql_connection()
made = []


def clone():
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s",
              (SOURCE_DRAFT,))
  src = cur.fetchone()
  cur.close()
  clone_id = "mn" + uuid.uuid4().hex[:30]
  client_id = "MN" + uuid.uuid4().hex[:16].upper()
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


def fin_of(draft_id):
  conn.commit()
  cur = conn.cursor()
  cur.execute("SELECT financials_json FROM intake_consult_drafts "
              "WHERE draft_id=%s", (draft_id,))
  (fin_j,) = cur.fetchone()
  cur.close()
  return json.loads(fin_j or "{}")


findings = []
try:
  d, c = clone()
  fin0 = fin_of(d)
  print(f"clone {d}")
  print(f"before: interest={fin0.get('annual_interest_payment')} "
        f"rent={fin0.get('monthly_rent_expense')} "
        f"cogs_total_year1={fin0.get('cogs_total_year1')} "
        f"current_cogs={fin0.get('current_cogs')} "
        f"other_debt={fin0.get('other_monthly_debt_payments')}")

  cases = [
    ("B1 ambiguous", "Just to confirm, our annual interest payment is 9,800.",
     ("annual_interest_payment", 9800.0)),
    ("B2 twin", "Just to confirm, our direct costs for the year came to "
     "729,910.", ("current_cogs", 729910.0)),
    ("B3 unique", "Just to confirm, our other monthly debt payments are "
     "3,100.", ("other_monthly_debt_payments", 3100.0)),
  ]
  for tag, msg, (field, want) in cases:
    st, r = turn(d, c, msg)
    print(f"\n{tag} < [{st}] {r[:400]}")
    fin = fin_of(d)
    got = fin.get(field)
    changed = got is None or abs(float(got) - want) > 1.0
    print(f"{tag} stored {field}={got} (changed={changed})")
    if changed:
      findings.append(f"{tag}: a RESTATEMENT changed stored {field}: {got!r}")
    low = r.lower()
    if tag.startswith("B1"):
      if "rent" in low:
        findings.append(f"B1: named RENT on an interest restatement: {r[:200]!r}")
      print(f"B1 deterministic-match register: "
            f"{'matches what i have' in low}; names interest field: "
            f"{'interest' in low}")
    if tag.startswith("B2"):
      named = [n for n in ("cogs total year1", "current cogs") if n in low]
      if named:
        findings.append(f"B2: twin confirmation named {named!r}")
      print(f"B2 deterministic-match register: {'matches what i have' in low}")
    if tag.startswith("B3"):
      print(f"B3 deterministic-match register: {'matches what i have' in low}; "
            f"names field: {'debt' in low}")

finally:
  for dd in made:
    try:
      w = conn.cursor()
      w.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s", (dd,))
      conn.commit()
      w.close()
    except Exception:
      pass
  print(f"\n({len(made)} clone(s) removed)")
  try:
    conn.close()
  except Exception:
    pass

print("=" * 78)
if findings:
  print("LIVE-B FINDINGS:")
  for f in findings:
    print("  -", f)
else:
  print("LIVE-B: all clean")
