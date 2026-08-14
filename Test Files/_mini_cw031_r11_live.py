"""mini, CW-031 round 11 audit -- live turns, my own wordings, rows not replies.

L1  AMBIGUOUS COLLISION, live (D1): restate the annual interest payment
    (9,800; rent is also 9,800). The sentence must speak the bare value and
    name NO field. Round 10's W4 heard "monthly rent expense is $9,800".
L2  DERIVED TWIN, live (item 3's honest-cost measurement): restate a figure
    stored under 2+ derived-twin names (picked from the draft's own
    collision map, printed first). Expect bare value -- record the client-
    speak so the acceptability judgment is made on a real sentence.
L3  UNIQUE NAME, live: restate a figure with exactly one distinct leaf name
    on this draft. The common case must keep its field name.
L4  NEAR-MISS CORRECTION, live (D2): "our annual revenue is 1,548,000"
    (stored 1,553,000). Must NOT claim a match. Read the stored figure:
    either the correction LANDS as a write or the honest ask fires.
L5  DISJOINT GROUPS + SEPARATION, live (D3 retire through the router):
    declare plants+hard goods at one rate and install+design at another,
    then separate design. Install's orphaned claim must retire spoken, and
    the plants+hard goods group must survive byte-identical.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r11_live.py"
"""
from __future__ import annotations

import json
import sys
import uuid
from collections import defaultdict
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


def collision_map(state):
  """value -> sorted distinct leaf names, for leaves >= 1000."""
  by_val = defaultdict(set)

  def walk(node):
    if isinstance(node, dict):
      for k, v in node.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) \
           and abs(v) >= 1000:
          by_val[float(v)].add(k)
        elif isinstance(v, (dict, list)):
          walk(v)
    elif isinstance(node, list):
      for it in node:
        walk(it)

  walk(state)
  return by_val


findings = []
try:
  d1, c1 = clone()
  rows0, fin0 = rows_of(d1)
  cmap = collision_map({"financials": fin0})
  print(f"clone {d1} -- collision map (financials, >=1000):")
  twins = {v: sorted(n) for v, n in cmap.items() if len(n) >= 2}
  uniques = {v: sorted(n) for v, n in cmap.items() if len(n) == 1}
  for v, names in sorted(twins.items()):
    print(f"  {v:>14,.0f} under {names}")
  n_all = len(cmap)
  print(f"  {len(twins)} of {n_all} distinct stored values >=1000 are "
        f"collided -- each of those confirmations now speaks bare")

  # ---- L1: ambiguous collision (rent == interest) ---------------------------
  st, r = turn(d1, c1, "Quick sanity check before we move on - I make our "
               "annual interest payment 9,800, is that what you have?")
  print(f"\nL1 < [{st}] {r[:350]}")
  low = r.lower()
  if "rent" in low or "interest payment is" in low:
    findings.append(f"L1: the sentence still names a field: {r[:160]!r}")
  if "9,800" not in r:
    findings.append(f"L1: the value is not spoken back: {r[:160]!r}")

  # ---- L2: derived twin (from the map) --------------------------------------
  twin_val = None
  for v, names in twins.items():
    if any("cogs" in n for n in names) and v != 9800.0:
      twin_val, twin_names = v, names
      break
  if twin_val is None:
    for v, names in twins.items():
      if v != 9800.0:
        twin_val, twin_names = v, names
        break
  print(f"\nL2 twin picked: {twin_val:,.0f} under {twin_names}")
  st2, r2 = turn(d1, c1, f"And just confirming our direct costs - "
                 f"{twin_val:,.0f} for the year, right?")
  print(f"L2 < [{st2}] {r2[:350]}")
  low2 = r2.lower()
  named2 = [n for n in twin_names
            if n.replace('_', ' ') in low2]
  print(f"L2 names spoken: {named2!r}")
  if named2:
    findings.append(f"L2: a twin-collided confirmation named {named2!r}")

  # ---- L3: unique name keeps its field --------------------------------------
  uniq_val = None
  for v, names in sorted(uniques.items()):
    if "monthly" in names[0] or "annual" in names[0] or "current" in names[0]:
      uniq_val, uniq_name = v, names[0]
      break
  if uniq_val is None:
    uniq_val, uniq_name = next(iter(sorted(uniques.items())))
    uniq_name = uniq_name[0]
  print(f"\nL3 unique picked: {uniq_val:,.0f} under {uniq_name!r}")
  st3, r3 = turn(d1, c1, f"Also double-checking: {uniq_val:,.0f} is the "
                 f"figure I gave you for {uniq_name.replace('_', ' ')}?")
  print(f"L3 < [{st3}] {r3[:350]}")
  if "matches what i have" in r3.lower() \
     and uniq_name.replace("_", " ") not in r3.lower():
    findings.append(f"L3: unique-name match lost its field name: {r3[:160]!r}")

  # ---- L4: near-miss correction ---------------------------------------------
  d2, c2 = clone()
  print(f"\nL4 clone {d2}")
  st4, r4 = turn(d2, c2, "Just to confirm, our annual revenue is 1,548,000.")
  print(f"L4 < [{st4}] {r4[:350]}")
  _, fin4 = rows_of(d2)
  rev4 = fin4.get("current_revenue")
  print(f"L4 stored current_revenue after: {rev4}")
  claims = "matches what i have" in r4.lower()
  kept_old = rev4 is not None and abs(float(rev4) - 1553000.0) < 1.0
  landed = rev4 is not None and abs(float(rev4) - 1548000.0) < 1.0
  print(f"L4 claims_match={claims} kept_old={kept_old} landed={landed}")
  if claims and kept_old:
    findings.append("L4: a 0.32% correction is STILL spoken as a match with "
                    "the old figure kept (D2 not live)")

  # ---- L5: disjoint groups + separation through the router ------------------
  d3, c3 = clone()
  print(f"\nL5 clone {d3}")
  st5a, r5a = turn(
    d3, c3,
    "Two housekeeping notes on direct costs. The plant sale and hard goods "
    "lines are both resale stock, so run them as one shared cost structure "
    "at 52 percent. Install projects and design consults are labour, so "
    "treat those two as one shared structure at 30 percent.")
  print(f"L5a < [{st5a}] {r5a[:350]}")
  rows5, _ = rows_of(d3)
  for row in rows5:
    print("L5a row:", row)
  by_name = {row["product_name"]: row for row in rows5}
  g_retail = {by_name.get("Plant sale", {}).get("cogs_cost_structure_group"),
              by_name.get("Hard goods sale", {}).get("cogs_cost_structure_group")}
  g_labour = {by_name.get("Install project", {}).get("cogs_cost_structure_group"),
              by_name.get("Design consult", {}).get("cogs_cost_structure_group")}
  if None in g_retail or len(g_retail) != 1 or None in g_labour \
     or len(g_labour) != 1 or g_retail == g_labour:
    findings.append(f"L5a: the two disjoint declarations did not both land: "
                    f"retail={g_retail!r} labour={g_labour!r}")
  retail_before = {n: by_name.get(n, {}) for n in ("Plant sale",
                                                   "Hard goods sale")}
  retail_snapshot = json.dumps(retail_before, sort_keys=True)

  st5b, r5b = turn(d3, c3, "On second thought the design consults should "
                   "stand on their own - pull them back out.")
  print(f"L5b < [{st5b}] {r5b[:350]}")
  rows5b, _ = rows_of(d3)
  for row in rows5b:
    print("L5b row:", row)
  by_name_b = {row["product_name"]: row for row in rows5b}
  design_b = by_name_b.get("Design consult", {})
  install_b = by_name_b.get("Install project", {})
  if design_b.get("cogs_cost_structure_group"):
    findings.append("L5b: separated line still carries a group")
  if install_b.get("cogs_cost_structure_group"):
    findings.append("L5b: install's orphaned two-member claim did not retire: "
                    f"{install_b!r}")
  retail_after = {n: {k: by_name_b.get(n, {}).get(k) for k in
                      retail_before[n]} for n in retail_before}
  if json.dumps(retail_after, sort_keys=True) != retail_snapshot:
    findings.append(f"L5b: the OTHER group did not survive byte-identical: "
                    f"before={retail_snapshot} after={retail_after!r}")
  low5b = r5b.lower()
  if "install" not in low5b:
    print("L5b NOTE: install's retire was not spoken in the reply "
          "(check receipt honesty above)")

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
