"""CW-031 round 8 -- the LIVE half: drive the round-8 rules through the real
router and read the ARTIFACT, not the reply.

Three things offline cannot prove:

  V1/V2  THE BLEND UNIT CONTRACT depends on the LIVE router emitting
         cogs_percent_of_revenue_unit. If it does not, the write now REFUSES
         where it used to land, and a client who was clear gets asked. mini's
         honest limit last round was that they could not reach this field live
         (the router converted both wordings into dollars), so this measures
         what actually happens rather than assuming either way.
  V3     THE TRANSPORT KEYS. mini measured financials.cogs_per_line_overrides
         PERSISTED into financials_json on 12 of 12 live turns. This is the
         same shape live: the rows must be written and the key must be gone.
  V4     THE DECLARED COLLAPSE. "everything runs at about 55" should reach the
         door as a GROUP (the client's own authority), not only as N identical
         overrides the app then has to guess about.

Every case is a FRESH clone of the real Ravenwood draft, one live POST, and the
artifact is read back with commit() FIRST (a long-lived connection under
REPEATABLE READ shows null while the app is writing correctly).

  .venv\\Scripts\\python.exe "Test Files\\_live_cw031_round8_turns.py"
"""

from __future__ import annotations

import json
import re
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
    "id": "V1",
    "kind": "blend",
    "message": ("Across the whole business, our direct costs come to about "
                "1 percent of revenue."),
    "means": 0.01,
    "why": "the small-percent reading the deleted rule stored as 100%",
  },
  {
    "id": "V2",
    "kind": "blend",
    "message": "Company-wide, direct costs are about 71 percent of revenue.",
    "means": 0.71,
    "why": "a large percent -- the reading the deleted rule got right",
  },
  {
    "id": "V3",
    "kind": "perline",
    "message": ("For the plant sales the materials are 48 percent of that line, "
                "and installation is 0.19."),
    "why": "two units in one message -- the array mini found stored verbatim",
  },
  {
    "id": "V4",
    "kind": "collapse",
    "message": ("Honestly every one of our lines runs at about 55 percent for "
                "direct costs - treat them all as one cost structure."),
    "why": "a DECLARED all-lines collapse: does it arrive as a group?",
  },
]

_FIN_KEYS = ("cogs_percent_of_revenue", "cogs_percent_of_revenue_unit", "cogs_basis",
             "current_cogs", "cogs_per_line_overrides", "cogs_shared_structure_groups")


def read_state(conn, draft_id):
  try:
    conn.commit()
  except Exception:
    pass
  cur = conn.cursor()
  cur.execute("SELECT financials_json, operating_model_json "
              "FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))
  row = cur.fetchone()
  cur.close()
  fin = json.loads((row[0] if row else None) or "{}")
  ops = json.loads((row[1] if row else None) or "{}")
  rows = []
  for lob in ops.get("lob_models") or []:
    for product in (lob.get("products") or []):
      if isinstance(product, dict):
        rows.append({
          "name": product.get("product_name") or product.get("name"),
          "pct": product.get("cogs_percent_of_line_revenue"),
          "group": product.get("cogs_cost_structure_group"),
          "group_basis": product.get("cogs_cost_structure_group_basis"),
        })
  return {k: fin.get(k) for k in _FIN_KEYS}, rows


def clone(conn):
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
  src = cur.fetchone()
  cur.close()
  clone_id = "r8" + uuid.uuid4().hex[:30]
  client_id = "R8" + uuid.uuid4().hex[:16].upper()
  columns = [c for c in src.keys() if c != "id"]
  values = [(clone_id if c == "draft_id" else client_id if c == "client_id" else src[c])
            for c in columns]
  write = conn.cursor()
  write.execute(
    f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
    f"VALUES ({', '.join(['%s'] * len(columns))})", tuple(values))
  conn.commit()
  write.close()
  return clone_id, client_id


def router_patch_for(draft_id: str) -> str:
  """The router's own emitted patch, from the live server's log -- the only
  place the DECLARED unit is visible before the applier consumes it."""
  logs = sorted(REPO_ROOT.glob("_logs_persona_*.txt"),
                key=lambda p: p.stat().st_mtime, reverse=True)
  for log in logs[:2]:
    try:
      text = log.read_text(encoding="utf-8", errors="replace")
    except Exception:
      continue
    hits = re.findall(rf"TURN_INTENT draft={re.escape(draft_id)} (.+)", text)
    if hits:
      return hits[-1].strip()
  return "(no TURN_INTENT line found)"


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  made, verdicts = [], []
  try:
    for case in CASES:
      draft_id, client_id = clone(conn)
      made.append(draft_id)
      before_fin, before_rows = read_state(conn, draft_id)
      print("=" * 78)
      print(f"{case['id']}  {case['why']}")
      print(f"  clone {draft_id[:16]}")
      print(f"  before rows: {[(r['name'], r['pct']) for r in before_rows]}")
      print(f"  > {case['message']}")
      resp = requests.post(
        f"{BASE_URL}/api/intake-consult",
        json={"draft_id": draft_id, "client_id": client_id, "message": case["message"]},
        timeout=300)
      body = resp.json() if resp.status_code == 200 else {}
      print(f"  < [{resp.status_code}] {str(body.get('assistant_message') or '')[:400]}")
      print(f"  ROUTER: {router_patch_for(draft_id)[:400]}")
      after_fin, after_rows = read_state(conn, draft_id)
      print(f"  after rows : {[(r['name'], r['pct'], r['group_basis']) for r in after_rows]}")
      print(f"  financials : {after_fin}")

      # THE RULE THAT APPLIES TO EVERY CASE: a transport key never lands.
      leaked = [k for k in ("cogs_per_line_overrides", "cogs_shared_structure_groups",
                            "cogs_percent_of_revenue_unit")
                if after_fin.get(k) is not None]
      verdict = []
      if leaked:
        verdict.append(f"TRANSPORT KEY STORED: {leaked}")
      else:
        verdict.append("no transport key stored")

      if case["kind"] == "blend":
        stored = after_fin.get("cogs_percent_of_revenue")
        was = before_fin.get("cogs_percent_of_revenue")
        # THE BLEND IS DOLLAR-DERIVABLE, so strict equality cries wolf: the
        # router converts "71 percent of revenue" into $1,102,620 and the
        # deriver lands 0.70999356, which is the client's number, not a defect.
        # (mini's round-7 file carries the same false alarm, labelled.) Judge
        # the RATIO the artifact ends up expressing, to a tenth of a point.
        if stored is None or (was is not None and abs(float(stored) - float(was)) < 1e-9):
          verdict.append("blend UNCHANGED (router landed it elsewhere or refused)")
        elif abs(float(stored) - case["means"]) <= 0.001:
          basis = after_fin.get("cogs_basis")
          verdict.append(f"blend CORRECT ({round(float(stored), 6)}, basis {basis})")
        else:
          verdict.append(f"BLEND WRONG-NUMBER: meant {case['means']}, stored {stored}")
      if case["kind"] == "perline":
        got = {r["name"]: r["pct"] for r in after_rows}
        verdict.append("rows: " + ", ".join(f"{k}={v}" for k, v in got.items()))
      if case["kind"] == "collapse":
        groups = {r["group"] for r in after_rows}
        bases = {r["group_basis"] for r in after_rows}
        rates = {r["pct"] for r in after_rows}
        verdict.append(f"groups={groups} bases={bases} rates={rates}")

      print(f"  VERDICT: {'; '.join(verdict)}\n")
      verdicts.append((case["id"], "; ".join(verdict)))
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
  for case_id, verdict in verdicts:
    print(f"  {case_id}: {verdict}")
  bad = [v for v in verdicts if "WRONG-NUMBER" in v[1] or "TRANSPORT KEY STORED" in v[1]]
  print("=" * 78)
  print("LIVE RESULT: " + ("CLEAN" if not bad else "RED -- " + ", ".join(v[0] for v in bad)))
  return 1 if bad else 0


if __name__ == "__main__":
  raise SystemExit(main())
