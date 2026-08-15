"""Red-proof for HANDOFF turn 1 (Nick's ruling after Nine Fathom run #2):
 1a  a confirmed discovered stream ALWAYS gets its OWN LOB named for its
     label - never nested under another line's LOB by a shared category
     noun (Nine Fathom: 'wholesale coffee sales to grocery stores' landed
     under LOB 'retail coffee bags' via the stem match on 'coffee').
 1b  the ask template renders a serial comma for 3+ labels ('A, B, or C');
     2 labels 'A or B'; 1 label 'A'.

PRE (before the fix): FAILs on nesting + comma. POST: all PASS.
Pure-python, no server, no GPT. Exact Nine Fathom shape (draft 6d2823db).

  .venv\Scripts\python.exe "Test Files\_discovery_lob_nesting_redproof.py"
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
try:
  sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
  pass

from client_intake_and_finmo.intake_coherence import gpt_stream_discovery as sd  # type: ignore

FAILURES: list = []


def check(label, ok, detail=""):
  print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
  if not ok:
    FAILURES.append(label)


PRIMARY = {"lob_name": "Primary line of business", "products": [{
  "product_name": "5 lb bag roasted coffee", "unit_name": "5 lb bag", "unit_cadence": "weekly",
  "units_per_week_capacity": 380, "utilization_rate": 0.75, "unit_price": 58, "origin": None,
}]}
LABELS = ["retail coffee bags", "wholesale coffee sales to grocery stores", "brew gear and merchandise sales"]
CONFIRMED = LABELS[:2]


def ninefathom_ops():
  return {"business_type": "Coffee Roaster", "business_naics_6": "311920",
          "lob_models": [copy.deepcopy(PRIMARY)]}


def rows_of(ops):
  return [(lob["lob_name"], p["product_name"], p.get("origin")) for lob in ops["lob_models"] for p in lob["products"]]


print("== 1a LOB NESTING: append_confirmed_stream_rows on the Nine Fathom shape ==")
ops, receipts = sd.append_confirmed_stream_rows(ninefathom_ops(), CONFIRMED)
rows = rows_of(ops)
print("   rows:", json.dumps(rows))
print("   receipts:", json.dumps(receipts))
lob_of = {pn: ln for ln, pn, _ in rows}
check("primary row untouched under its own LOB", lob_of["5 lb bag roasted coffee"] == "Primary line of business")
check("retail coffee bags -> its OWN LOB named for the label", lob_of.get("retail coffee bags") == "retail coffee bags")
check("wholesale grocery -> its OWN LOB named for the label (NOT nested under retail coffee bags)",
      lob_of.get("wholesale coffee sales to grocery stores") == "wholesale coffee sales to grocery stores", lob_of.get("wholesale coffee sales to grocery stores"))
check("three LOBs total, one row each", len(ops["lob_models"]) == 3 and all(len(l["products"]) == 1 for l in ops["lob_models"]))
check("both discovered rows stamped origin=discovery_confirmed", all(o == sd.STREAM_DISCOVERY_ORIGIN for ln, pn, o in rows if pn in CONFIRMED))
check("receipt says 'its own line' and never 'under <other line>' (receipt == state)",
      all("is its own line;" in r and " under " not in r for r in receipts), json.dumps(receipts))
check("idempotent: second append does not duplicate", rows_of(sd.append_confirmed_stream_rows(copy.deepcopy(ops), CONFIRMED)[0]) == rows)

print("== 1a same shape through carry_stream_discovery (a model patch dropped both rows) ==")
before = copy.deepcopy(ops)
before["stream_discovery"] = {"asked": True, "candidates": [
  {"label": LABELS[0], "answer": "yes"}, {"label": LABELS[1], "answer": "yes"}, {"label": LABELS[2], "answer": "no"}]}
# the client's numbers land on the rows before the replacement
for lob in before["lob_models"]:
  for p in lob["products"]:
    if p["product_name"] == "retail coffee bags":
      p.update({"unit_price": 19, "units_per_week_capacity": 260, "utilization_rate": 0.6})
    if p["product_name"] == "wholesale coffee sales to grocery stores":
      p.update({"unit_price": 13, "units_per_week_capacity": 140, "utilization_rate": 0.55})
after = {"business_type": "Coffee Roaster", "lob_models": [copy.deepcopy(PRIMARY)]}
after = sd.carry_stream_discovery(before, after)
crows = rows_of(after)
print("   rows:", json.dumps(crows))
clob = {pn: ln for ln, pn, _ in crows}
check("carry: wholesale grocery restored to its OWN LOB (not nested)", clob.get("wholesale coffee sales to grocery stores") == "wholesale coffee sales to grocery stores", clob.get("wholesale coffee sales to grocery stores"))
check("carry: retail bags restored to its OWN LOB", clob.get("retail coffee bags") == "retail coffee bags")
drivers = {p["product_name"]: (p.get("unit_price"), p.get("units_per_week_capacity"), p.get("utilization_rate"))
           for lob in after["lob_models"] for p in lob["products"]}
check("carry: drivers untouched (19/260/.6 and 13/140/.55)", drivers["retail coffee bags"] == (19, 260, 0.6) and drivers["wholesale coffee sales to grocery stores"] == (13, 140, 0.55), json.dumps(drivers))
check("carry: primary drivers untouched (58/380/.75)", drivers["5 lb bag roasted coffee"] == (58, 380, 0.75))
# a pre-fix nested layout in `before` is re-homed by carry only if the row is dropped; an existing nested row is left where the model kept it (no re-shuffle of client-seen state)
check("carry idempotent", rows_of(sd.carry_stream_discovery(copy.deepcopy(after), copy.deepcopy(after))) == crows)

print("== 1a stem-match LOB placement is GONE (a discovered stream is a peer by definition) ==")
src = (REPO_ROOT / "python/client_intake_and_finmo/intake_coherence/gpt_stream_discovery.py").read_text(encoding="utf-8")
check("no stem_match_lob_index in the module", "stem_match_lob_index" not in src)
check("no 'own line under' receipt variant", "own line under" not in src)

print("== 1b SERIAL COMMA in the ask template ==")
ask3 = sd.compose_stream_discovery_ask("Coffee Roaster", LABELS)
print("   ask3:", ask3)
check("3 labels: 'A, B, or C'", "retail coffee bags, wholesale coffee sales to grocery stores, or brew gear and merchandise sales" in ask3, ask3)
check("2 labels: 'A or B'", sd.join_labels(LABELS[:2]) == "retail coffee bags or wholesale coffee sales to grocery stores", sd.join_labels(LABELS[:2]))
check("1 label: 'A'", sd.join_labels(LABELS[:1]) == "retail coffee bags")
check("4 labels: 'A, B, C, or D'", sd.join_labels(["a", "b", "c", "d"]) == "a, b, c, or d", sd.join_labels(["a", "b", "c", "d"]))
check("ask == the ONE template constant", ask3 == sd.STREAM_DISCOVERY_ASK_TEMPLATE.format(business_type_plural=sd.pluralize_business_type("Coffee Roaster"), labels=sd.join_labels(LABELS)))
check("revenue-line clause stays", "include it as a revenue line" in ask3)
check("forbidden-phrase grep clean", not any(p in ask3.lower() for p in sd.FORBIDDEN_ASK_PHRASES), ask3)
clar = sd.STREAM_DISCOVERY_CLARIFY_TEMPLATE.format(labels=sd.join_labels(LABELS))
check("clarify template renders the same comma", ", or brew gear" in clar and not any(p in clar.lower() for p in sd.FORBIDDEN_ASK_PHRASES), clar)

print()
print("RESULT:", "GREEN" if not FAILURES else f"RED ({len(FAILURES)} failing): " + "; ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
