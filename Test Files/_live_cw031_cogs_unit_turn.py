"""CW-031 round 7 -- THE UNIT, ON THE LIVE PATH.

mini measured that "1%" stored as 100%: _clamp divided by 100 only above 1.0,
so a client whose design line runs 1% got a line costing 100% of its own
revenue, and every artifact assertion passed it. The fix moves the unit to the
ROUTER, where the client's own words are still visible, and refuses at the door
when it is absent -- which means the fix is only real if the LIVE router
actually emits it. Offline probes cannot answer that.

Three fresh clones of the REAL Ravenwood draft (four lines, all rates null),
the live :5050 backend, the live router, one turn each. The ARTIFACT is read
back, never the reply.

  L1  "only about 1 percent"  -- THE DEFECT. Must store 0.01, not 1.0.
  L2  "half a point"          -- a sub-1 percent said in words.
  L3  "0.71 of that line"     -- a ratio, which must NOT become 0.0071.

READ-BACK COMMITS FIRST: a long-lived connection under REPEATABLE READ shows
null while the app is writing correctly.

  .venv\\Scripts\\python.exe "Test Files\\_live_cw031_cogs_unit_turn.py"
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:5050"
SOURCE_DRAFT = "1070c6a560a04f3d971019a3787180bf"

CASES = [
  {
    "id": "L1",
    "message": ("On direct costs - the design consult line only runs about 1 percent "
                "in materials, it's basically all my own time."),
    "expect": {"Design consult": 0.01},
    "why": "THE DEFECT: 1 percent must be 0.01, not a line costing 100% of itself",
  },
  {
    "id": "L2",
    "message": ("Design consult materials are half a point of that line, call it "
                "half a percent."),
    "expect": {"Design consult": 0.005},
    "why": "'half a point' must be 0.005, not 50%",
  },
  {
    "id": "L3",
    "message": ("For hard goods sale the direct-cost ratio is 0.71 of that line's "
                "revenue."),
    "expect": {"Hard goods sale": 0.71},
    "why": "a ratio stays a ratio - 0.71 must not become 0.0071",
  },
]

VERDICTS: list = []


def ops_rates(conn, draft_id):
  try:
    conn.commit()
  except Exception:
    pass
  cur = conn.cursor()
  cur.execute(
    "SELECT operating_model_json FROM intake_consult_drafts WHERE draft_id=%s",
    (draft_id,))
  row = cur.fetchone()
  cur.close()
  ops = json.loads((row[0] if row else None) or "{}")
  return {str(p.get("product_name")): p.get("cogs_percent_of_line_revenue")
          for lob in ops.get("lob_models") or []
          for p in lob.get("products") or []}


def clone(conn, cur):
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
  src = cur.fetchone()
  if not src:
    raise SystemExit("source Ravenwood draft missing")
  clone_id = "unit" + uuid.uuid4().hex[:28]
  client_id = "UNIT" + uuid.uuid4().hex[:14].upper()
  columns = [c for c in src.keys() if c != "id"]
  values = []
  for c in columns:
    v = src[c]
    if c == "draft_id":
      v = clone_id
    elif c == "client_id":
      v = client_id
    values.append(v)
  write = conn.cursor()
  write.execute(
    f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
    f"VALUES ({', '.join(['%s'] * len(columns))})", tuple(values))
  conn.commit()
  write.close()
  return clone_id, client_id


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  made: list = []
  try:
    for case in CASES:
      dict_cur = conn.cursor(dictionary=True)
      draft_id, client_id = clone(conn, dict_cur)
      dict_cur.close()
      made.append(draft_id)
      before = ops_rates(conn, draft_id)
      print("=" * 78)
      print(f"{case['id']}  {case['why']}")
      print("=" * 78)
      print(f"  clone {draft_id[:16]}")
      print(f"  before: {before}")
      print(f"  > {case['message']}")
      resp = requests.post(
        f"{BASE_URL}/api/intake-consult",
        json={"draft_id": draft_id, "client_id": client_id, "message": case["message"]},
        timeout=300,
      )
      body = resp.json() if resp.status_code == 200 else {}
      reply = str(body.get("assistant_message") or "")
      print(f"  < [{resp.status_code}] {reply[:400]}")
      after = ops_rates(conn, draft_id)
      print(f"  after : {after}")

      asks = ("percent or a fraction" in reply.lower()
              or "couldn't tell which line" in reply.lower())
      wrong = {n: after.get(n) for n, want in case["expect"].items()
               if after.get(n) is not None and abs(float(after[n]) - want) > 1e-9}
      landed = all(after.get(n) is not None and abs(float(after[n]) - want) <= 1e-9
                   for n, want in case["expect"].items())
      untouched = {n: v for n, v in after.items()
                   if n not in case["expect"] and v != before.get(n)}
      if wrong or untouched:
        verdict = "WRONG-NUMBER" if wrong else "WRONG-LINE"
      elif landed:
        verdict = "LANDED"
      elif asks:
        verdict = "HONEST-REFUSAL"
      else:
        verdict = "NO-WRITE-NO-QUESTION"
      print(f"  expected={case['expect']}  wrong={wrong or '(none)'}  "
            f"other lines touched={untouched or '(none)'}")
      print(f"  VERDICT: {verdict}")
      VERDICTS.append((case["id"], verdict, case["expect"], wrong, reply[:160]))
      print()
  finally:
    for draft_id in made:
      try:
        cur = conn.cursor()
        cur.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))
        conn.commit()
        cur.close()
      except Exception:
        pass
    print(f"  ({len(made)} clone(s) removed)")
    try:
      conn.close()
    except Exception:
      pass

  print("=" * 78)
  for case_id, verdict, expect, wrong, _reply in VERDICTS:
    print(f"  {case_id}: {verdict:<20} expected={expect} wrong={wrong or '{}'}")
  bad = [v for v in VERDICTS if v[1] in ("WRONG-NUMBER", "WRONG-LINE")]
  if bad:
    print(f"UNACCEPTABLE - {len(bad)} case(s) wrote a wrong number or a wrong line.")
    return 1
  quiet = [v for v in VERDICTS if v[1] == "NO-WRITE-NO-QUESTION"]
  if quiet:
    print(f"NOTE - {len(quiet)} case(s) wrote nothing and asked nothing.")
    return 1
  print("Every case either landed the client's own number or asked which unit it was.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
