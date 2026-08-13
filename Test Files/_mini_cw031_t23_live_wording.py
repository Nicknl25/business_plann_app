"""CW-031 mini audit, tiers 2/3 -- ITEM 1, THE ONE THAT MATTERS.

VS's live proof used the client's own sentences from the Ravenwood transcript,
and those sentences name the lines the way the app names them ("Plant sale",
"Hard goods sale"). The door's weakest point is exactly there: line-name
resolution. So this drives wording that does NOT name the app's lines, on a
fresh clone of the REAL Ravenwood draft each time, through the live :5050
backend and the live router, and reads the ARTIFACT afterwards -- never the reply.

  W1  "the pavers side"        -- a name only a human would use
  W2  "the two retail ones"    -- a category, not a name
  W3  "everything except..."   -- an exclusion, so the door must enumerate

THE ONLY UNACCEPTABLE OUTCOME is a rate written onto a line the wording does not
denote. _resolve_cogs_line is meant to refuse rather than guess, so a
"I couldn't tell which line you meant" question is a PASS here.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_t23_live_wording.py"
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

# What each wording DENOTES, judged against the app's own line names.
CASES = [
  {
    "id": "W1",
    "message": ("On the direct costs - the pavers side runs about 71 percent in "
                "materials, that's the pallet stuff we buy in."),
    "denotes": {"Hard goods sale"},
    "why": "'the pavers side' is the hard goods line and nothing else",
  },
  {
    "id": "W2",
    "message": ("Let's treat the two retail ones as sharing a single direct-cost "
                "rate - they're both just bought-in goods we resell."),
    "denotes": {"Plant sale", "Hard goods sale"},
    "why": "'the two retail ones' are the plant and hard-goods lines",
    "group": True,
  },
  {
    "id": "W3",
    "message": ("Everything except design runs at about 55 percent for materials. "
                "Design stays where it is."),
    "denotes": {"Plant sale", "Hard goods sale", "Install project"},
    "why": "'everything except design' is the other three lines",
  },
]

VERDICTS: list = []


def ops_rates(conn, draft_id):
  # commit() FIRST: this connection is under REPEATABLE READ, so without ending
  # the transaction it keeps serving the snapshot taken at its first read and a
  # correct write reads back as null. (VS lost two live runs to this.)
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
  out = {}
  for lob in ops.get("lob_models") or []:
    for product in lob.get("products") or []:
      out[str(product.get("product_name"))] = {
        "pct": product.get("cogs_percent_of_line_revenue"),
        "group": product.get("cogs_cost_structure_group"),
      }
  return out


def clone(conn, cur):
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
  src = cur.fetchone()
  if not src:
    raise SystemExit("source Ravenwood draft missing")
  clone_id = "mini" + uuid.uuid4().hex[:28]
  client_id = "MINI" + uuid.uuid4().hex[:14].upper()
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
      print(f"  clone {draft_id[:16]}  lines={list(before)}")
      print(f"  before: { {k: v['pct'] for k, v in before.items()} }")
      print(f"  > {case['message']}")
      resp = requests.post(
        f"{BASE_URL}/api/intake-consult",
        json={"draft_id": draft_id, "client_id": client_id,
              "message": case["message"]},
        timeout=300,
      )
      body = resp.json() if resp.status_code == 200 else {}
      reply = str(body.get("assistant_message") or "")
      print(f"  < [{resp.status_code}] {reply}")
      after = ops_rates(conn, draft_id)
      print(f"  after : { {k: v['pct'] for k, v in after.items()} }")
      print(f"  groups: { {k: v['group'] for k, v in after.items() if v['group']} }")

      changed = {name for name, value in after.items()
                 if value["pct"] != before.get(name, {}).get("pct")
                 or value["group"] != before.get(name, {}).get("group")}
      denotes = set(case["denotes"])
      wrong = changed - denotes
      missed = denotes - changed
      asks = ("couldn't tell which line" in reply.lower()
              or "which one should i change" in reply.lower()
              or "which line" in reply.lower())
      if wrong:
        verdict = "WRONG-LINE"
      elif changed == denotes:
        verdict = "LANDED"
      elif not changed and asks:
        verdict = "HONEST-REFUSAL"
      elif not changed:
        verdict = "NO-WRITE-NO-QUESTION"
      else:
        verdict = "PARTIAL"
      print(f"  changed={sorted(changed) or '(nothing)'}  "
            f"wrong={sorted(wrong) or '(none)'}  missed={sorted(missed) or '(none)'}")
      print(f"  VERDICT: {verdict}")
      VERDICTS.append((case["id"], verdict, sorted(changed), sorted(wrong), reply[:200]))
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
  for case_id, verdict, changed, wrong, _reply in VERDICTS:
    print(f"  {case_id}: {verdict:<20} wrote={changed} wrong={wrong}")
  bad = [v for v in VERDICTS if v[1] == "WRONG-LINE"]
  quiet = [v for v in VERDICTS if v[1] == "NO-WRITE-NO-QUESTION"]
  if bad:
    print(f"UNACCEPTABLE - {len(bad)} wording(s) wrote a rate onto a line the "
          f"client did not name.")
    return 1
  if quiet:
    print(f"NOTE - {len(quiet)} wording(s) wrote nothing and asked nothing.")
  print("No wording wrote the wrong line.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
