"""CW-031 round 7 -- red-proof for mini's four defects plus the latent wildcard.

Every case below is a shape mini MEASURED as broken in
_mini_cw031_tier23_audit_20260813.txt. This asserts the fixed behaviour on the
PRODUCTION functions, so reverting any one hunk turns exactly its own block red.

  1  "1%" stored as 100%        -- the unit is declared, never inferred
  3  a collapse silently drops a stated rate  -- plain average, announced
  4  a uniform rate filed as a RECURRENCE     -- the client's recorded collapse
  6  an unnamed product row is a wildcard     -- latent, guarded

(Item 2, the window mis-award, has mini's own reproduction and is proven by
re-running Test Files/_mini_cw031_t23_window_break.py -- not duplicated here.)

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_round7_fixes.py"
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]

FAILURES: list = []


def check(tag: str, ok: bool, detail: str) -> None:
  print(f"  [{'PASS' if ok else 'FAIL'}] {tag}: {detail}")
  if not ok:
    FAILURES.append(tag)


def line(name, price=40.0, capacity=120, util=1.0, periods=52, pct=None):
  row = {
    "product_name": name,
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


def rate_of(ops, name):
  for lob in ops.get("lob_models") or []:
    for product in lob.get("products") or []:
      if str(product.get("product_name")) == name:
        return product.get("cogs_percent_of_line_revenue")
  return None


def group_of(ops, name):
  for lob in ops.get("lob_models") or []:
    for product in lob.get("products") or []:
      if str(product.get("product_name")) == name:
        return product.get("cogs_cost_structure_group")
  return None


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from api_handlers import intake_consult as ic  # type: ignore
  import issue_registry as ir  # type: ignore

  door = ic._apply_per_line_cogs_patch_keys
  say = ic._build_per_line_cogs_receipt_text

  print("=" * 78)
  print("ITEM 1 -- THE UNIT IS DECLARED, NEVER INFERRED")
  print("=" * 78)
  print("mini: _clamp divided by 100 only above 1.0, so a client whose design")
  print("line runs 1% got a line costing 100% of its own revenue, and it passed")
  print("every artifact assertion (non-null, distinct, internally consistent).")
  print()

  # THE DEFECT ITSELF, stated as the client states it.
  for raw, unit, want, label in [
    (1, "percent", 0.01, "'design is 1 percent'      "),
    (0.5, "percent", 0.005, "'half a point'             "),
    (71, "percent", 0.71, "'about 71 percent'         "),
    (4, "percent", 0.04, "'runs at 4'                "),
    (0.71, "ratio", 0.71, "'0.71 of that line'        "),
    (0.38, "ratio", 0.38, "'a ratio of 0.38'          "),
  ]:
    ops = ops_of(line("Plant sale", pct=None), line("Hard goods sale"))
    door({"financials.cogs_per_line_overrides": [
      {"line_name": "Plant sale", "cogs_percent": raw, "cogs_percent_unit": unit}]},
      ops_json=ops)
    got = rate_of(ops, "Plant sale")
    check(f"declared {label}", got == want,
          f"{raw!r} as {unit} -> {got!r} (want {want!r})")

  # NO UNIT: refuse, and ask the question that can be answered.
  ops = ops_of(line("Plant sale", pct=None), line("Hard goods sale"))
  receipt = door({"financials.cogs_per_line_overrides": [
    {"line_name": "Plant sale", "cogs_percent": 1}]}, ops_json=ops)
  text = say(receipt)
  check("no unit -> nothing written", rate_of(ops, "Plant sale") is None,
        f"row rate is {rate_of(ops, 'Plant sale')!r}")
  check("no unit -> receipt asks", bool(receipt.get("unit_unclear")) and "percent or a fraction" in text,
        repr(text[:120]))
  check("no unit -> not filed as unmatched line", not receipt.get("unmatched"),
        f"unmatched={receipt.get('unmatched')} (the LINE was known; the RATE was not)")
  # CW-022 #1 has to survive the refusal: the figure was stated about this
  # line's direct costs, so it is not a price or a lever target even though it
  # was not written. Otherwise "design is 1" comes back as a $1 unit price
  # while the app is still asking what the 1 meant.
  check("a refused figure is still claimed", 1.0 in (receipt.get("consumed_figures") or []),
        f"consumed_figures={receipt.get('consumed_figures')}")

  # CONTRADICTION: a unit that cannot describe its own figure is refused, not
  # silently rescaled into the clamp.
  for raw, unit in [(71, "ratio"), (150, "percent"), (-2, "percent")]:
    ops = ops_of(line("Plant sale", pct=None), line("Hard goods sale"))
    r = door({"financials.cogs_per_line_overrides": [
      {"line_name": "Plant sale", "cogs_percent": raw, "cogs_percent_unit": unit}]},
      ops_json=ops)
    check(f"contradiction {raw} as {unit}",
          rate_of(ops, "Plant sale") is None and bool(r.get("unit_unclear")),
          f"refused, rate={rate_of(ops, 'Plant sale')!r}")

  print()
  print("=" * 78)
  print("ITEM 3 -- A COLLAPSE MUST NOT SILENTLY DROP A STATED RATE")
  print("=" * 78)
  print("mini: Plant sale weighted 249,600 at 0.48, Hard goods sale with no")
  print("unit_price -> weight None -> contributes 0.0, total_weight still > 0,")
  print("so the shared rate was 0.48 EXACTLY and the client's stated 0.71 was")
  print("not averaged in, it was DISCARDED. The receipt called 0.48 computed.")
  print()

  ops = ops_of(
    line("Plant sale", 40.0, 120, pct=0.48),
    line("Hard goods sale", None, 30, pct=0.71),
  )
  receipt = door({"financials.cogs_shared_structure_groups":
                  [["Plant sale", "Hard goods sale"]]}, ops_json=ops)
  shared = rate_of(ops, "Plant sale")
  grouped = (receipt.get("grouped") or [{}])[0]
  text = say(receipt)
  check("stated rate not discarded", shared == 0.595,
        f"shared={shared!r} (0.48 would mean 0.71 was dropped; plain average is 0.595)")
  check("basis is named on the receipt", grouped.get("basis") == "plain average",
        f"basis={grouped.get('basis')!r}, unweighted={grouped.get('unweighted_lines')}")
  check("the client is TOLD", "plain average" in text and "Hard goods sale" in text,
        repr(text))

  # The all-weights-absent average must announce itself too.
  ops = ops_of(line("Plant sale", None, None, pct=0.48),
               line("Hard goods sale", None, None, pct=0.71))
  r = door({"financials.cogs_shared_structure_groups":
            [["Plant sale", "Hard goods sale"]]}, ops_json=ops)
  check("all-weights-absent average announces itself",
        (r["grouped"][0].get("basis") == "plain average"
         and rate_of(ops, "Plant sale") == 0.595
         and "plain average" in say(r)), repr(say(r)))

  # THE WEIGHTING ITSELF IS RIGHT AND MUST NOT MOVE (mini checked it hard: it
  # preserves the group's direct-cost dollars to $12 on $208,416).
  ops = ops_of(line("Plant sale", 40.0, 120, pct=0.48),
               line("Hard goods sale", 80.0, 30, pct=0.71))
  r = door({"financials.cogs_shared_structure_groups":
            [["Plant sale", "Hard goods sale"]]}, ops_json=ops)
  check("full weights still revenue-weighted",
        rate_of(ops, "Plant sale") == 0.5567
        and r["grouped"][0].get("basis") == "revenue weighted",
        f"shared={rate_of(ops, 'Plant sale')!r} basis={r['grouped'][0].get('basis')!r}")

  # One rated member propagating is not an average and must not claim to be.
  ops = ops_of(line("Plant sale", 40.0, 120, pct=0.48), line("Hard goods sale"))
  r = door({"financials.cogs_shared_structure_groups":
            [["Plant sale", "Hard goods sale"]]}, ops_json=ops)
  check("single stated rate propagates, not 'averaged'",
        rate_of(ops, "Hard goods sale") == 0.48
        and r["grouped"][0].get("basis") == "stated",
        f"basis={r['grouped'][0].get('basis')!r}")

  print()
  print("=" * 78)
  print("ITEM 4 -- ONE RATE FOR EVERY LINE IS A DECLARATION, NOT A RECURRENCE")
  print("=" * 78)
  print("mini: 4 rows at 0.55 FAIL even with the collapse stored on all four,")
  print("and spec['allow_shared_rates'] is a key nobody sets mid-run. A client")
  print("reaches this state with one ordinary sentence (live W3).")
  print()

  names = ["Plant sale", "Hard goods sale", "Install project", "Design consult"]
  ops = ops_of(*[line(n) for n in names])
  receipt = door({"financials.cogs_per_line_overrides": [
    {"line_name": n, "cogs_percent": 55, "cogs_percent_unit": "percent"} for n in names]},
    ops_json=ops)
  labels = {group_of(ops, n) for n in names}
  check("door records the client's own collapse",
        len(labels) == 1 and all(labels) and all(rate_of(ops, n) == 0.55 for n in names),
        f"group on all four = {labels}")
  check("the receipt says the collapse happened",
        any(g.get("all_lines") for g in receipt.get("grouped") or [])
        and "all 4 lines" in say(receipt), repr(say(receipt)))

  # And the assertion must now accept it -- read through the production
  # evaluator with a stubbed loader, so this is the real branch.
  real_loader = ir._load_ops_model
  try:
    ir._load_ops_model = lambda cur, draft_id: copy.deepcopy(ops)  # type: ignore
    verdict = ir._assert_ops_per_line_cogs(None, "x", {})
    check("uniform + recorded collapse PASSES", verdict.get("verdict") == "pass",
          f"{verdict.get('verdict')}: {verdict.get('detail')}")

    # Identical rates with NO group stored is still a blend wearing per-line
    # clothing and must still fail -- the opt-out is the client's authority,
    # not the check being absent.
    bare = copy.deepcopy(ops)
    for lob in bare["lob_models"]:
      for p in lob["products"]:
        p.pop("cogs_cost_structure_group", None)
    ir._load_ops_model = lambda cur, draft_id: copy.deepcopy(bare)  # type: ignore
    verdict = ir._assert_ops_per_line_cogs(None, "x", {})
    check("uniform with NO collapse still FAILS", verdict.get("verdict") == "fail",
          f"{verdict.get('verdict')}: {verdict.get('detail')}")

    # A partial collapse must not buy the opt-out either.
    partial = copy.deepcopy(ops)
    partial["lob_models"][0]["products"][0].pop("cogs_cost_structure_group", None)
    ir._load_ops_model = lambda cur, draft_id: copy.deepcopy(partial)  # type: ignore
    verdict = ir._assert_ops_per_line_cogs(None, "x", {})
    check("uniform with PARTIAL collapse still FAILS", verdict.get("verdict") == "fail",
          f"{verdict.get('verdict')}: {verdict.get('detail')}")
  finally:
    ir._load_ops_model = real_loader  # type: ignore

  # The narrow condition: three of four lines is NOT a declaration (mini's live
  # W3 -- "everything except design" -- must not mint an all-lines group).
  ops = ops_of(*[line(n) for n in names])
  door({"financials.cogs_per_line_overrides": [
    {"line_name": n, "cogs_percent": 55, "cogs_percent_unit": "percent"}
    for n in names[:3]]}, ops_json=ops)
  check("3 of 4 lines mints no group",
        all(group_of(ops, n) is None for n in names),
        f"groups={[group_of(ops, n) for n in names]}")

  print()
  print("=" * 78)
  print("ITEM 1b -- THE TRANSPORT KEY MUST NOT SPEAK FOR THE WRITE")
  print("=" * 78)
  print("Found live, and caused by fixing item 1: the acknowledgment renders")
  print("the RAW router figure. 'half a point' wrote 0.005 and the client was")
  print("told 'COGS to 50.0%'; '1 percent' wrote 0.01 and read out as '$1'")
  print("(a percent, dollared, because 'cogs' is a money hint). The write was")
  print("right both times -- the sentence over it was not.")
  print()

  import capture_receipt as cr  # type: ignore
  said = cr.receipt_summary({"written": [
    ("financials.cogs_per_line_overrides[0].cogs_percent", None, 0.5),
    ("financials.cogs_per_line_overrides[0].cogs_percent_unit", None, 1),
    ("operating_model.lob_models[0].products[3].cogs_percent_of_line_revenue",
     None, 0.005),
  ]})
  check("the raw router figure is not spoken", "50.0%" not in said and "$1" not in said,
        repr(said))
  check("the WRITTEN rate still is", "0.5%" in said, repr(said))
  # The stored percent fields are real client numbers and must survive the filter.
  kept = cr.receipt_summary({"written": [
    ("financials.cogs_percent_of_revenue", None, 0.42),
    ("financials.baseline_cogs_percent", None, 0.42)]})
  check("stored COGS percent fields still render", "42.0%" in kept, repr(kept))

  print()
  print("=" * 78)
  print("ITEM 6 -- AN UNNAMED PRODUCT ROW IS NOT A WILDCARD")
  print("=" * 78)
  print("mini: '' is a substring of every target, so a single unnamed row")
  print("matched ANY phrasing -- 'the pavers side' wrote 0.71 onto the blank")
  print("row and the receipt called it 'Garden'. Latent: 0 of 3,050 drafts.")
  print()

  directory = ic._cogs_line_directory(ops_of(line("")))
  for wording in ["the pavers side", "the two retail ones", "everything except design"]:
    check(f"unnamed row refuses {wording!r}",
          ic._resolve_cogs_line(wording, directory) is None,
          f"resolved to {ic._resolve_cogs_line(wording, directory)}")

  # ...and the wordings that SHOULD land still land (mini's live W1 shape).
  directory = ic._cogs_line_directory(
    ops_of(line("Plant sale"), line("Hard goods sale"), line("Design consult")))
  hit = ic._resolve_cogs_line("hard goods sale", directory)
  check("a real name still resolves", hit is not None and hit["product_name"] == "Hard goods sale",
        f"{hit and hit['product_name']!r}")

  print()
  print("=" * 78)
  if FAILURES:
    print(f"RED -- {len(FAILURES)} failing: {FAILURES}")
    return 1
  print("GREEN -- all round-7 fixes hold on the production functions")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
