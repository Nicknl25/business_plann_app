"""CW-031 round-8 mini audit -- the LIVE half of items 2 and 3.

Phase A (current code, unit key ABSENT -- the shipped state):
  the refusal's live exposure. My own blend wordings, never VS's:
    A-B1  percent-shaped blend, big figure
    A-B2  fraction-shaped blend
    A-B3  field-name-shaped raw figure ("set cogs percent of revenue to 38")
    A-B4  percent-shaped blend, small figure (the latent 1%-stores-100% shape)
  Read: what landed, whether any transport/unit key stored, whether the reply
  refused where the client was clear, and the ratio the artifact expresses.

Phase B (unit key RE-ADDED to the two router lists -- the experiment):
  does the router stop patching and ask about the unit? My own wordings:
    B-U1  blend percent           B-U2  blend small percent
    B-U3  per-line rate (nothing to do with the blend)
    B-U4  collapse declaration (nothing to do with the blend)
  Measure the confirm_clarify rate; VS reports 3 of 4.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r8_live_probe.py" a|b
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

PHASE_A = [
  {"id": "A-B1", "message": ("Taking everything together, materials and product "
                             "costs eat up about 38 percent of what we bring in."),
   "means": 0.38},
  {"id": "A-B2", "message": "Our blended direct-cost ratio is 0.44.", "means": 0.44},
  {"id": "A-B3", "message": "Please set cogs percent of revenue to 38.", "means": 0.38},
  {"id": "A-B4", "message": ("Overall our direct costs are only about 2 percent "
                             "of revenue."), "means": 0.02},
]

PHASE_B = [
  {"id": "B-U1", "message": ("Our overall direct costs run around 40 percent of "
                             "revenue."), "means": 0.40},
  {"id": "B-U2", "message": "Direct costs are just 1 percent of revenue for us.",
   "means": 0.01},
  {"id": "B-U3", "message": ("For the install side, materials run 22 percent of "
                             "that line."), "means": None},
  {"id": "B-U4", "message": ("Plants and hard goods basically share one cost "
                             "structure - same rate for both."), "means": None},
]

_FIN_KEYS = ("cogs_percent_of_revenue", "cogs_percent_of_revenue_unit", "cogs_basis",
             "current_cogs", "cogs_total_year1", "cogs_per_line_overrides",
             "cogs_shared_structure_groups")

_ASK_PAT = re.compile(r"unit|percent or|0\.|ratio", re.IGNORECASE)


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
  clone_id = "m8" + uuid.uuid4().hex[:30]
  client_id = "M8" + uuid.uuid4().hex[:16].upper()
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


def router_line_for(draft_id: str) -> str:
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
  phase = (sys.argv[1] if len(sys.argv) > 1 else "a").lower()
  cases = PHASE_A if phase == "a" else PHASE_B
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  made, verdicts = [], []
  try:
    for case in cases:
      draft_id, client_id = clone(conn)
      made.append(draft_id)
      before_fin, before_rows = read_state(conn, draft_id)
      print("=" * 78)
      print(f"{case['id']}  clone {draft_id[:16]}")
      print(f"  > {case['message']}")
      resp = requests.post(
        f"{BASE_URL}/api/intake-consult",
        json={"draft_id": draft_id, "client_id": client_id, "message": case["message"]},
        timeout=300)
      body = resp.json() if resp.status_code == 200 else {}
      reply = str(body.get("assistant_message") or "")
      print(f"  < [{resp.status_code}] {reply[:400]}")
      print(f"  ROUTER: {router_line_for(draft_id)[:400]}")
      after_fin, after_rows = read_state(conn, draft_id)
      print(f"  rows : {[(r['name'], r['pct'], r['group_basis']) for r in after_rows]}")
      print(f"  fin  : {after_fin}")

      verdict = []
      leaked = [k for k in ("cogs_per_line_overrides", "cogs_shared_structure_groups",
                            "cogs_percent_of_revenue_unit") if after_fin.get(k) is not None]
      verdict.append(f"TRANSPORT KEY STORED: {leaked}" if leaked else "no key stored")
      asked_unit = ("unit" in reply.lower() and "?" in reply) or \
                   ("percent, or" in reply.lower()) or ("or 0." in reply.lower())
      verdict.append(f"asked-about-unit={asked_unit}")
      if case.get("means") is not None:
        stored = after_fin.get("cogs_percent_of_revenue")
        was = before_fin.get("cogs_percent_of_revenue")
        cogs_d = after_fin.get("current_cogs")
        was_d = before_fin.get("current_cogs")
        if stored is not None and abs(float(stored) - case["means"]) <= 0.002:
          verdict.append(f"blend CORRECT ratio {round(float(stored), 6)}")
        elif stored is not None and was is not None and \
             abs(float(stored) - float(was)) < 1e-9 and \
             cogs_d is not None and was_d is not None and \
             abs(float(cogs_d) - float(was_d)) < 1e-6:
          verdict.append("blend UNCHANGED (refused or landed nowhere)")
        elif stored is None:
          verdict.append("blend NULL")
        else:
          verdict.append(f"blend MOVED to {stored} (dollars {cogs_d}); "
                         f"ratio-vs-meant delta {abs(float(stored) - case['means']):.4f}")
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
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
