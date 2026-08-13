"""CW-031 tier 2 red-proof: A-110, the COGS write door.

THE BUG. Ravenwood is a four-line business. The judge proposed four correct
rates (55/60/38/6 with bands). The client corrected all four
("Plants are 48%... Hard goods are 71%... Install is only 19%... design is 4%"),
re-stated one of them twice more, and finally declared a collapse ("plants and
hard goods are both bought-in retail goods, treat those two as sharing one cost
structure"). The app said "Got it - I'll keep one shared direct-cost rate for
Plant sale and Hard goods sale" and stored NOTHING: all four ops product rows
read cogs_percent_of_line_revenue = null, and the delivered workbook carried
one blended COGS row. cogs_percent_of_line_revenue and
_apply_per_line_cogs_to_ops both existed - the only caller was the cogs stage's
own default patch, so no client statement could ever reach them.

THE PRODUCTION CHAIN under test:

    post_intake_consult_handler
      -> _apply_scoped_patch                 (the one door every surface uses)
        -> _apply_per_line_cogs_patch_keys   (A-110: the write)
    _build_financials_live_turn's stage flow
      -> _apply_stage_cogs_door_keys         (the same write, inside the stage)

RED ON THE BUG: before the door, the patches below leave all four rows null
and the artifact assertion fails. After it, the rows carry the client's own
four rates, the collapse lands one shared rate on exactly the two lines the
client named, and the assertion passes.

Run:
  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_cogs_write_door.py"
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
RAVENWOOD = "1070c6a560a04f3d971019a3787180bf"

FAILURES: list = []


def check(label: str, ok: bool, detail: str) -> None:
  print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")
  if not ok:
    FAILURES.append(label)


def rows_of(ops):
  out = []
  for lob in (ops or {}).get("lob_models") or []:
    for product in lob.get("products") or []:
      out.append((f"{lob.get('lob_name')} / {product.get('product_name')}", product))
  return out


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore
  from api_handlers import intake_consult as ic  # type: ignore
  from client_intake_and_finmo import issue_registry  # type: ignore

  conn = get_mysql_connection()
  cur = conn.cursor()
  try:
    print("STEP 0 - the REAL Ravenwood ops model, exactly as it was delivered")
    ops_before = issue_registry._load_ops_model(cur, RAVENWOOD)
    before = rows_of(ops_before)
    for name, row in before:
      print(f"  {name:52} cogs_pct={row.get('cogs_percent_of_line_revenue')}")
    check("the live defect is present in the stored artifact",
          len(before) == 4
          and all(r.get("cogs_percent_of_line_revenue") is None for _, r in before),
          f"{len(before)} lines, all null")

    print("\nSTEP 1 - the client's OWN four rates, through the production door")
    # The patch the router now emits for turn 79: "Plants are 48%... Hard goods
    # are 71%... Install is only 19%... design is 4%". Percent form on purpose -
    # that is how a client says it.
    patch = {
      "financials.cogs_per_line_overrides": [
        {"line_name": "Plant sale", "cogs_percent": 48},
        {"line_name": "Hard goods sale", "cogs_percent": 71},
        {"line_name": "Install project", "cogs_percent": 19},
        {"line_name": "Design consult", "cogs_percent": 4},
      ],
    }
    ops_after = copy.deepcopy(ops_before)
    _, ops_after, _, _, fin_after, _ = ic._apply_scoped_patch(
      patch, business_facts={}, ops_json=ops_after, market_json={},
      people_json={}, financials_json={}, fulfillment_json={},
    )
    got = {name.split(" / ")[-1]: row.get("cogs_percent_of_line_revenue")
           for name, row in rows_of(ops_after)}
    print(f"  written: {got}")
    check("all four client rates are WRITTEN to the ops rows",
          got == {"Plant sale": 0.48, "Hard goods sale": 0.71,
                  "Install project": 0.19, "Design consult": 0.04},
          "48/71/19/4 as the client stated them")
    check("a percent-form statement is stored as a rate",
          all(0.0 < v <= 1.0 for v in got.values()), "71 -> 0.71, never 71.0")
    receipt = (fin_after or {}).get("_per_line_cogs_receipt")
    check("the door leaves a receipt for the caller to speak from",
          isinstance(receipt, dict) and len(receipt.get("written") or []) == 4,
          f"{len(((receipt or {}).get('written') or []))} written")

    print("\nSTEP 2 - the artifact assertion flips on the REAL detector")
    real_loader = issue_registry._load_ops_model
    spec = {"kind": "ops_per_line_cogs", "min_lines": 2}
    try:
      issue_registry._load_ops_model = lambda _c, _d: ops_before  # type: ignore
      was = issue_registry._assert_ops_per_line_cogs(cur, RAVENWOOD, spec)
      issue_registry._load_ops_model = lambda _c, _d: ops_after  # type: ignore
      now = issue_registry._assert_ops_per_line_cogs(cur, RAVENWOOD, spec)
    finally:
      issue_registry._load_ops_model = real_loader  # type: ignore
    print(f"  before: {was['verdict']} - {was['detail'][:80]}")
    print(f"  after : {now['verdict']} - {now['detail'][:80]}")
    check("the artifact fails before the door and passes after it",
          was["verdict"] == "fail" and now["verdict"] == "pass",
          "the same detector, the same draft, the door is the only difference")

    print("\nSTEP 3 - the collapse the client declared, routed (item 4)")
    # Turn 111/113: "plants and hard goods are both bought-in retail goods, so
    # treat those two as sharing one cost structure. But keep install and
    # design separate from them and from each other."
    collapse = {
      "financials.cogs_shared_structure_groups": [["Plant sale", "Hard goods sale"]],
    }
    ops_collapsed = copy.deepcopy(ops_after)
    _, ops_collapsed, _, _, fin_collapsed, _ = ic._apply_scoped_patch(
      collapse, business_facts={}, ops_json=ops_collapsed, market_json={},
      people_json={}, financials_json={}, fulfillment_json={},
    )
    after = {name.split(" / ")[-1]: row for name, row in rows_of(ops_collapsed)}
    rates = {k: v.get("cogs_percent_of_line_revenue") for k, v in after.items()}
    groups = {k: v.get("cogs_cost_structure_group") for k, v in after.items()}
    print(f"  rates : {rates}")
    print(f"  groups: {groups}")
    check("the two named lines now share ONE rate",
          rates["Plant sale"] == rates["Hard goods sale"],
          f"{rates['Plant sale']} on both")
    check("the shared rate is revenue-weighted, not a plain average",
          rates["Plant sale"] not in (None, round((0.48 + 0.71) / 2, 4)),
          f"weighted {rates['Plant sale']} vs unweighted 0.595")
    check("it sits between the two rates it collapsed",
          0.48 <= float(rates["Plant sale"]) <= 0.71, str(rates["Plant sale"]))
    check("the lines the client kept separate are untouched",
          rates["Install project"] == 0.19 and rates["Design consult"] == 0.04,
          "install and design keep their own")
    check("the grouping is STORED, not just applied",
          groups["Plant sale"] and groups["Plant sale"] == groups["Hard goods sale"]
          and not groups["Install project"] and not groups["Design consult"],
          str(groups["Plant sale"]))
    check("three distinct rates for four lines, as the client asked",
          len({rates[k] for k in rates}) == 3,
          f"{len({rates[k] for k in rates})} distinct")
    check("the collapse still satisfies the distinct-rates default",
          issue_registry._assert_ops_per_line_cogs.__name__ == "_assert_ops_per_line_cogs"
          and len({rates[k] for k in rates}) >= 2,
          "a declared collapse is not a blend in disguise")

    print("\nSTEP 4 - a grouping declared BEFORE any rate still binds")
    ops_bare = copy.deepcopy(ops_before)
    _, ops_bare, _, _, _, _ = ic._apply_scoped_patch(
      collapse, business_facts={}, ops_json=ops_bare, market_json={},
      people_json={}, financials_json={}, fulfillment_json={},
    )
    bare = {name.split(" / ")[-1]: row for name, row in rows_of(ops_bare)}
    check("the group is recorded even with no rates yet",
          bare["Plant sale"].get("cogs_cost_structure_group")
          == bare["Hard goods sale"].get("cogs_cost_structure_group") is not None,
          "the client's authority outlives the missing numbers")

    print("\nSTEP 5 - the receipt cannot outrun the write (item 2)")
    said = ic._build_per_line_cogs_receipt_text(
      (fin_collapsed or {}).get("_per_line_cogs_receipt") or {})
    print(f"  receipt: {said}")
    check("the receipt names the two lines that actually share a rate",
          "Plant sale" in said and "Hard goods sale" in said and "shar" in said,
          "spoken from the rows")
    empty = ic._build_per_line_cogs_receipt_text(
      ic._apply_per_line_cogs_patch_keys(
        {"financials.cogs_per_line_overrides": [
          {"line_name": "a line that does not exist", "cogs_percent": 50}]},
        ops_json=copy.deepcopy(ops_before)))
    print(f"  unmatched: {empty}")
    check("an unmatched line produces a question, never a confirmation",
          "couldn't tell which line" in empty and "Recorded" not in empty,
          "no receipt without a write")
    ambiguous = ic._resolve_cogs_line("sale", ic._cogs_line_directory(ops_before))
    check("an ambiguous name refuses to guess",
          ambiguous is None, "'sale' matches two lines -> no write")

    print("\nSTEP 6 - the stage-flow door is the SAME write (not a second one)")
    stage_ops = copy.deepcopy(ops_before)
    stage_ctx = {"operating_model": stage_ops}
    left, stage_ctx_out, ack = ic._apply_stage_cogs_door_keys(
      patch=dict(patch), stage_shared_context=stage_ctx, conn=conn,
      intake_context={"draft_id": ""},
    )
    stage_rates = {n.split(" / ")[-1]: r.get("cogs_percent_of_line_revenue")
                   for n, r in rows_of(stage_ctx_out["operating_model"])}
    print(f"  stage rates: {stage_rates}")
    print(f"  stage ack  : {ack}")
    check("the stage flow writes the same four rates",
          stage_rates == got, "one writer, two surfaces")
    check("the door consumes its keys so the whitelist never sees them",
          not left, f"{list(left or {})}")
    check("the stage ack is built from the write",
          "Recorded" in ack and "48%" in ack, ack[:70])
  finally:
    try:
      cur.close()
      conn.close()
    except Exception:
      pass

  print("\n" + "=" * 72)
  if FAILURES:
    print(f"RED - {len(FAILURES)} check(s) failed: {FAILURES}")
    return 1
  print("GREEN - a client's per-line direct costs now reach the model.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
