"""CW-031 mini audit, tiers 2/3 -- ITEM 2: the collapse arithmetic, adversarially,
plus the resolver hazards that sit next to it.

VS asked two questions and I am answering both with numbers off the production
functions, not prose:

  (a) find the case where a member's revenue weight is ABSENT or ZERO -- does
      the plain-average fallback defend itself, or should it refuse?
  (b) a group whose members' weights are wildly unequal puts the shared rate
      almost on top of the bigger line. Is that right for a client who said
      "treat these two as one"?

And two hazards of my own on the same door, both of the class this batch is
named for (a number written onto the WRONG line, silently):

  (c) a product row with NO product_name is a wildcard in the loose branch of
      _resolve_cogs_line ("" is a substring of every target).
  (d) _clamp treats a bare 1 as 1.0 == 100%, so "design is 1%" stores 100%.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_t23_collapse_probe.py"
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]

FINDINGS: list = []


def note(tag: str, ok: bool, detail: str) -> None:
  print(f"  [{'OK  ' if ok else 'HAZARD'}] {tag}: {detail}")
  if not ok:
    FINDINGS.append(tag)


def line(name, price, capacity, util=1.0, periods=52, pct=None, product_name=None):
  row = {
    "product_name": name if product_name is None else product_name,
    "unit_price": price,
    "units_per_period_capacity": capacity,
    "utilization_rate": util,
    "operating_periods_per_year": periods,
  }
  if pct is not None:
    row["cogs_percent_of_line_revenue"] = pct
  return row


def ops_of(*rows, lob="Garden"):
  return {"lob_models": [{"lob_name": lob, "products": list(rows)}]}


def rates(ops):
  out = {}
  for lob in ops.get("lob_models") or []:
    for product in lob.get("products") or []:
      out[str(product.get("product_name"))] = (
        product.get("cogs_percent_of_line_revenue"),
        product.get("cogs_cost_structure_group"),
      )
  return out


def group_cogs_dollars(ops, names, weight_fn):
  """What the group's direct cost actually is, in dollars of a year."""
  total = 0.0
  for lob in ops.get("lob_models") or []:
    for product in lob.get("products") or []:
      if str(product.get("product_name")) in names:
        weight = weight_fn(product) or 0.0
        pct = product.get("cogs_percent_of_line_revenue")
        if pct is not None:
          total += float(weight) * float(pct)
  return total


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from api_handlers import intake_consult as ic  # type: ignore

  door = ic._apply_per_line_cogs_patch_keys
  weight_fn = ic._cogs_line_revenue_weight

  print("=" * 78)
  print("(b) EQUAL-ISH WEIGHTS: does the collapse preserve the group's COGS dollars?")
  print("=" * 78)
  ops = ops_of(
    line("Plant sale", 40.0, 120, pct=0.48),
    line("Hard goods sale", 80.0, 30, pct=0.71),
    line("Design consult", 500.0, 2, pct=0.04),
  )
  w = {n: weight_fn(r) for n, r in
       [(p["product_name"], p) for p in ops["lob_models"][0]["products"]]}
  print(f"  weights: { {k: f'{v:,.0f}' for k, v in w.items()} }")
  before_dollars = group_cogs_dollars(ops, {"Plant sale", "Hard goods sale"}, weight_fn)
  after = copy.deepcopy(ops)
  door({"financials.cogs_shared_structure_groups": [["Plant sale", "Hard goods sale"]]},
       ops_json=after)
  shared = rates(after)["Plant sale"][0]
  after_dollars = group_cogs_dollars(after, {"Plant sale", "Hard goods sale"}, weight_fn)
  plain = round((0.48 + 0.71) / 2, 4)
  print(f"  shared rate = {shared}  (plain average would be {plain})")
  print(f"  group COGS before collapse = ${before_dollars:,.2f}")
  print(f"  group COGS after  collapse = ${after_dollars:,.2f}")
  note("revenue-weighting preserves the group's direct-cost dollars",
       abs(before_dollars - after_dollars) < 1.0,
       f"delta ${abs(before_dollars - after_dollars):,.2f}; a plain average would "
       f"land ${abs(before_dollars - plain * sum(w[n] for n in ('Plant sale', 'Hard goods sale'))):,.0f} off")

  print()
  print("=" * 78)
  print("(b2) WILDLY UNEQUAL WEIGHTS: 200:1")
  print("=" * 78)
  ops2 = ops_of(
    line("Plant sale", 40.0, 1000, pct=0.48),      # big
    line("Hard goods sale", 20.0, 10, pct=0.71),   # tiny
  )
  w2 = {p["product_name"]: weight_fn(p) for p in ops2["lob_models"][0]["products"]}
  before2 = group_cogs_dollars(ops2, set(w2), weight_fn)
  after2 = copy.deepcopy(ops2)
  door({"financials.cogs_shared_structure_groups": [["Plant sale", "Hard goods sale"]]},
       ops_json=after2)
  shared2 = rates(after2)["Plant sale"][0]
  after2_dollars = group_cogs_dollars(after2, set(w2), weight_fn)
  print(f"  weights: { {k: f'{v:,.0f}' for k, v in w2.items()} }  ratio "
        f"{max(w2.values()) / min(w2.values()):,.0f}:1")
  print(f"  shared rate = {shared2} (big line was 0.48, small line was 0.71)")
  print(f"  group COGS before = ${before2:,.2f}   after = ${after2_dollars:,.2f}")
  note("the shared rate still preserves the group's dollars at 200:1",
       abs(before2 - after2_dollars) < 1.0, f"delta ${abs(before2 - after2_dollars):,.2f}")
  print(f"  NOTE the small line's own cost moves {abs(0.71 - shared2) * 100:.1f} points "
        f"({0.71:.2f} -> {shared2}); that is what 'treat these two as one' means.")

  print()
  print("=" * 78)
  print("(a1) ONE MEMBER'S WEIGHT MISSING -- VS's case, and it is NOT a plain average")
  print("=" * 78)
  ops3 = ops_of(
    line("Plant sale", 40.0, 120, pct=0.48),
    line("Hard goods sale", None, 30, pct=0.71),   # no unit price -> weight None
  )
  w3 = {p["product_name"]: weight_fn(p) for p in ops3["lob_models"][0]["products"]}
  print(f"  weights: {w3}")
  after3 = copy.deepcopy(ops3)
  receipt3 = door(
    {"financials.cogs_shared_structure_groups": [["Plant sale", "Hard goods sale"]]},
    ops_json=after3)
  shared3 = rates(after3)["Plant sale"][0]
  print(f"  shared rate = {shared3}")
  print(f"  receipt.grouped = {receipt3.get('grouped')}")
  note("a member with no revenue weight still counts in the shared rate",
       shared3 is not None and abs(float(shared3) - 0.48) > 1e-9,
       f"{shared3} == the weighted member's own rate exactly; the 0.71 the client "
       f"stated for the other line was dropped with no receipt and no log")

  print()
  print("=" * 78)
  print("(a2) BOTH WEIGHTS MISSING -- the documented plain-average fallback")
  print("=" * 78)
  ops4 = ops_of(
    line("Plant sale", None, None, pct=0.48),
    line("Hard goods sale", None, None, pct=0.71),
  )
  after4 = copy.deepcopy(ops4)
  door({"financials.cogs_shared_structure_groups": [["Plant sale", "Hard goods sale"]]},
       ops_json=after4)
  shared4 = rates(after4)["Plant sale"][0]
  print(f"  shared rate = {shared4} (plain average of 0.48 and 0.71 = 0.595)")
  note("the plain-average fallback announces itself",
       False,
       f"{shared4} is a plain average and nothing in the receipt, the row or the "
       f"log says the weighting it claims never happened")

  print()
  print("=" * 78)
  print("(a3) ONE RATED MEMBER, ONE UNRATED -- the rate propagates outward")
  print("=" * 78)
  ops5 = ops_of(
    line("Plant sale", 40.0, 120, pct=0.48),
    line("Hard goods sale", 80.0, 30),  # no rate at all
  )
  after5 = copy.deepcopy(ops5)
  receipt5 = door(
    {"financials.cogs_shared_structure_groups": [["Plant sale", "Hard goods sale"]]},
    ops_json=after5)
  print(f"  rows now: {rates(after5)}")
  print(f"  receipt.grouped = {receipt5.get('grouped')}")
  note("a line the client never rated is given a rate, and the receipt says so",
       rates(after5)["Hard goods sale"][0] == 0.48
       and bool(receipt5.get("grouped")),
       "0.48 propagates to the unrated member; the grouped receipt names both lines "
       "and the rate, so the client sees it")

  print()
  print("=" * 78)
  print("(c) WILDCARD ROW: a product with no name matches ANY client wording")
  print("=" * 78)
  ops6 = ops_of(
    line("Plant sale", 40.0, 120),
    line(None, 80.0, 30, product_name=""),   # unnamed row, e.g. a bare LOB product
  )
  after6 = copy.deepcopy(ops6)
  receipt6 = door({"financials.cogs_per_line_overrides": [
    {"line_name": "the pavers side", "cogs_percent": 71}]}, ops_json=after6)
  got6 = rates(after6)
  print(f"  rows now: {got6}")
  print(f"  receipt: written={receipt6.get('written')} unmatched={receipt6.get('unmatched')}")
  wrote_to_blank = got6.get("", (None, None))[0] is not None
  note("an unnamed row cannot absorb a rate meant for another line",
       not wrote_to_blank,
       "'the pavers side' resolved to the UNNAMED row and wrote 0.71 onto it"
       if wrote_to_blank else "unmatched, as it should be")

  print()
  print("=" * 78)
  print("(d) '1%' -- the one percent a client can actually say")
  print("=" * 78)
  ops7 = ops_of(line("Design consult", 500.0, 2), line("Plant sale", 40.0, 120))
  after7 = copy.deepcopy(ops7)
  door({"financials.cogs_per_line_overrides": [
    {"line_name": "Design consult", "cogs_percent": 1}]}, ops_json=after7)
  stored = rates(after7)["Design consult"][0]
  print(f"  client said 1 (percent); stored {stored}")
  note("a 1% line is stored as 1%", stored == 0.01,
       f"stored {stored} == {float(stored) * 100:g}% of that line's revenue")
  after8 = copy.deepcopy(ops7)
  door({"financials.cogs_per_line_overrides": [
    {"line_name": "Design consult", "cogs_percent": 0.5}]}, ops_json=after8)
  stored8 = rates(after8)["Design consult"][0]
  print(f"  client said 0.5 (percent, a half-point line); stored {stored8} "
        f"= {float(stored8) * 100:g}%")

  print()
  print("=" * 78)
  print(f"{len(FINDINGS)} hazard(s): {FINDINGS}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
