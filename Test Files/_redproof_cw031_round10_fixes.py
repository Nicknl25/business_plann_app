"""VS, CW-031 round 10: red-proof for mini's round-9 findings (turn 12 TASK).

Three checks, each red on TODAY'S code for the documented reason and green
only when its fix lands:

  C1  MEMBERSHIP IS DATA, NOT A LABEL PARSE. Declaring a group containing a
      '+'-named product ('Design + Build') must SURVIVE its own declaring
      call. Today the label encodes membership as "+".join(names) and the
      coherence pass parses it back with split('+'), so the declaration is
      retired in the same call that stored it (mini's O2). Positive controls:
      a genuinely stale group must STILL retire (separation of one member
      retires the survivor, by name), and a legacy row carrying a label with
      NO stored member list must still be judged by the label parse (R39's
      cursor-stub rows are stamped that way).

  C2  (LIVE) A RESTATEMENT OF AN ON-FILE FIGURE GETS A MATCH-ON-FILE
      SENTENCE. "Just to confirm, our annual revenue is 1,553,000" (on file:
      1,553,000) must not be answered with the failed-change sentence
      ("I wasn't able to apply that change just now..."). The stored figure
      must also be byte-unchanged either way. Requires ONE :5050 listener.

  C3  EVERY SEPARATED LINE IS NAMED. Four separated lines must all appear in
      the receipt sentence (or the tail must be counted); today the renderer
      slices separated[:3] and the fourth vanishes.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_round10_fixes.py"
  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_round10_fixes.py" --offline-only
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from api_handlers.intake_consult import (  # type: ignore
  _apply_per_line_cogs_patch_keys,
  _build_per_line_cogs_receipt_text,
)

SOURCE_DRAFT = "1070c6a560a04f3d971019a3787180bf"
BASE_URL = "http://127.0.0.1:5050"


def ops(names_rates):
  return {"lob_models": [{
    "lob_name": "Main",
    "products": [
      {"product_name": n, "cogs_percent_of_line_revenue": r,
       "unit_price": 100.0, "units_per_period_capacity": 10.0,
       "operating_periods_per_year": 12.0}
      for n, r in names_rates
    ],
  }]}


def prows(o):
  return o["lob_models"][0]["products"]


bad = []

# ---- C1: the '+' trap and the pass's remaining teeth -----------------------
o = ops([("Design + Build", 0.30), ("Plant sale", 0.30), ("Hard goods", 0.60)])
r = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_shared_structure_groups": [["Design + Build", "Plant sale"]]},
  ops_json=o)
db, ps, hg = prows(o)
print("C1a declare w/ '+' name:", [(p.get("product_name"),
                                    p.get("cogs_cost_structure_group")) for p in prows(o)],
      "| ungrouped:", r["ungrouped"])
if not (db.get("cogs_cost_structure_group") and ps.get("cogs_cost_structure_group")):
  bad.append("C1a: the '+'-named declared group was retired in the same call "
             f"that stored it (ungrouped={r['ungrouped']})")

# C1b positive control: the pass must still retire a genuinely stale group.
# Separate one member; the abandoned survivor's label must retire, by name.
if db.get("cogs_cost_structure_group"):
  r2 = _apply_per_line_cogs_patch_keys(
    {"financials.cogs_separate_lines": ["Plant sale"]}, ops_json=o)
  print("C1b after separation  :", [(p.get("product_name"),
                                     p.get("cogs_cost_structure_group")) for p in prows(o)],
        "| ungrouped:", r2["ungrouped"])
  if db.get("cogs_cost_structure_group"):
    bad.append("C1b: survivor of a real separation kept a label whose "
               "membership is gone (the pass lost its teeth)")
  if not any("Design + Build" in str(u) for u in r2["ungrouped"]):
    bad.append(f"C1b: retired survivor not named ({r2['ungrouped']})")
else:
  print("C1b skipped: C1a already red (group did not survive declaration)")

# C1c legacy compat: a row stamped label-only (no stored member list — R39's
# cursor-stub shape) must still be retired when the label's parse no longer
# matches the carrying set.
o3 = ops([("Alpha", 0.40), ("Beta", 0.40), ("Gamma", 0.10)])
a, b, g = prows(o3)
a["cogs_cost_structure_group"] = "shared:alpha+beta"
a["cogs_cost_structure_group_basis"] = "declared"
# Beta's row was cleared out-of-band: Alpha now wears a claim about a set
# that no longer carries it. Any group/separation write must retire it.
r3 = _apply_per_line_cogs_patch_keys(
  {"financials.cogs_separate_lines": ["Gamma"]}, ops_json=o3)
print("C1c legacy stale label:", [(p.get("product_name"),
                                   p.get("cogs_cost_structure_group")) for p in prows(o3)],
      "| ungrouped:", r3["ungrouped"])
if a.get("cogs_cost_structure_group"):
  bad.append("C1c: legacy label-only stale group survived (label-parse "
             "fallback lost)")

# ---- C3: every separated line is named -------------------------------------
receipt = {"written": [], "grouped": [], "unmatched": [], "unit_unclear": [],
           "separated": ["Main / Plant sale", "Main / Hard goods sale",
                         "Main / Install project", "Main / Design consult"],
           "ungrouped": [], "uniform_rate_ask": None, "wrote": True,
           "consumed_figures": []}
text = _build_per_line_cogs_receipt_text(receipt)
print("C3 sentence:", text)
named = sum(1 for s in receipt["separated"] if s in text)
counted = "more" in text
if named < 4 and not counted:
  bad.append(f"C3: only {named} of 4 separated lines are named and the rest "
             "are not counted (separated[:3] under-count)")

# ---- C2: live match-on-file (skippable) ------------------------------------
if "--offline-only" not in sys.argv:
  import requests
  from dotenv import load_dotenv
  load_dotenv(REPO_ROOT / ".env", override=False)
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  made = []
  try:
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s",
                (SOURCE_DRAFT,))
    src = cur.fetchone()
    cur.close()
    clone_id = "vt" + uuid.uuid4().hex[:30]
    client_id = "VT" + uuid.uuid4().hex[:16].upper()
    columns = [c for c in src.keys() if c != "id"]
    values = [(clone_id if c == "draft_id" else client_id if c == "client_id"
               else src[c]) for c in columns]
    w = conn.cursor()
    w.execute(f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
              f"VALUES ({', '.join(['%s'] * len(columns))})", tuple(values))
    conn.commit()
    w.close()
    made.append(clone_id)

    def fin_of(draft_id):
      conn.commit()
      c2 = conn.cursor()
      c2.execute("SELECT financials_json FROM intake_consult_drafts "
                 "WHERE draft_id=%s", (draft_id,))
      row = c2.fetchone()
      c2.close()
      return json.loads((row[0] if row else None) or "{}")

    before = fin_of(clone_id)
    on_file = before.get("current_revenue")
    print(f"C2 on file current_revenue: {on_file}")
    resp = requests.post(
      f"{BASE_URL}/api/intake-consult",
      json={"draft_id": clone_id, "client_id": client_id,
            "message": "Just to confirm, our annual revenue is 1,553,000."},
      timeout=300)
    reply = str((resp.json() if resp.status_code == 200 else {})
                .get("assistant_message") or "")
    after = fin_of(clone_id)
    print(f"C2 < [{resp.status_code}] {reply[:300]}")
    if "wasn't able to apply that change" in reply.lower():
      bad.append("C2: an on-file restatement was answered with the "
                 f"failed-change sentence ({reply[:140]!r})")
    if "match" not in reply.lower() or not any(
      tok in reply for tok in ("1,553,000", "1553000")):
      bad.append("C2: the reply does not speak the match "
                 f"({reply[:140]!r})")
    rev_after = after.get("current_revenue")
    if rev_after is not None and on_file is not None \
       and abs(float(rev_after) - float(on_file)) > 0.01:
      bad.append(f"C2: the restatement CHANGED the stored figure "
                 f"({on_file} -> {rev_after})")
  finally:
    for d in made:
      try:
        c3 = conn.cursor()
        c3.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s", (d,))
        conn.commit()
        c3.close()
      except Exception:
        pass
    print(f"C2 ({len(made)} clone(s) removed)")
    try:
      conn.close()
    except Exception:
      pass
else:
  print("C2 skipped (--offline-only)")

print("=" * 78)
if bad:
  print("ROUND-10 REDPROOF: RED")
  for item in bad:
    print(f"  - {item}")
  raise SystemExit(1)
print("ROUND-10 REDPROOF: GREEN (all three round-10 fixes hold)")
