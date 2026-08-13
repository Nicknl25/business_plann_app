"""CW-031 round 8 -- red-proof for mini's three defects from the round-7 audit.

Every case below is a shape mini MEASURED as broken in
_mini_cw031_r7_audit_20260813.txt. This asserts the fixed behaviour on the
PRODUCTION functions, so reverting any one hunk turns exactly its own block red.

  1  the transport keys still PERSIST into financials_json (12/12 live turns;
     U5 stored 48 and 0.19 in one array under one field name)
  2  the all-lines group is minted from VALUE EQUALITY, so two coinciding
     lines mint a collapse the client never declared (and the assertion then
     passes it), while the same declaration split over two messages mints
     none and is filed as a RECURRENCE
  3  _normalize_ratio_like is round 7's deleted rule still alive, on the
     BLENDED rate the engine consumes when cogs_basis is "ratio"

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_round8_fixes.py"
"""

from __future__ import annotations

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


def row_of(ops, name):
  for lob in ops.get("lob_models") or []:
    for product in lob.get("products") or []:
      if str(product.get("product_name")) == name:
        return product
  return {}


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from api_handlers import intake_consult as ic  # type: ignore
  import issue_registry as ir  # type: ignore

  door = ic._apply_per_line_cogs_patch_keys
  say = ic._build_per_line_cogs_receipt_text

  def scoped(patch, ops, fin=None):
    """The correction path, as the app calls it."""
    _b, _ops, _m, _p, _fin, _f = ic._apply_scoped_patch(
      patch, business_facts={}, ops_json=ops, market_json={}, people_json={},
      financials_json=dict(fin or {}), fulfillment_json={},
    )
    return _ops, _fin

  print("=" * 78)
  print("ITEM 1 -- A TRANSPORT KEY IS CONSUMED, NEVER STORED")
  print("=" * 78)
  print("mini: _apply_scoped_patch persisted financials.cogs_per_line_overrides")
  print("verbatim on all twelve live turns. U5 stored [{cogs_percent: 48, unit")
  print("percent}, {cogs_percent: 0.19, unit ratio}] -- one array, one field")
  print("name, two units: the defect round 7 fixed, preserved in the artifact.")
  print()

  ops = ops_of(line("Plant sale"), line("Install project"))
  _ops, fin = scoped({
    "financials.cogs_per_line_overrides": [
      {"line_name": "Plant sale", "cogs_percent": 48, "cogs_percent_unit": "percent"},
      {"line_name": "Install project", "cogs_percent": 0.19, "cogs_percent_unit": "ratio"},
    ],
    "financials.cash_on_hand": 12500,
  }, ops)
  check("1a transport key not stored",
        "cogs_per_line_overrides" not in fin,
        f"financials keys after the write: {sorted(k for k in fin if not k.startswith('_'))}")
  check("1b the door still WROTE the rows",
        row_of(ops, "Plant sale").get("cogs_percent_of_line_revenue") == 0.48
        and row_of(ops, "Install project").get("cogs_percent_of_line_revenue") == 0.19,
        f"plant={row_of(ops, 'Plant sale').get('cogs_percent_of_line_revenue')!r} "
        f"install={row_of(ops, 'Install project').get('cogs_percent_of_line_revenue')!r}")
  check("1c POSITIVE CONTROL - an ordinary field still persists",
        fin.get("cash_on_hand") == 12500,
        f"cash_on_hand={fin.get('cash_on_hand')!r} - the filter is not a blanket drop")

  ops = ops_of(line("Plant sale", pct=0.48), line("Hard goods sale", pct=0.71))
  _ops, fin = scoped(
    {"financials.cogs_shared_structure_groups": [["Plant sale", "Hard goods sale"]]}, ops)
  check("1d the group transport key not stored",
        "cogs_shared_structure_groups" not in fin,
        f"financials keys: {sorted(k for k in fin if not k.startswith('_'))}")
  check("1e the group still LANDED on the rows",
        row_of(ops, "Plant sale").get("cogs_cost_structure_group")
        == row_of(ops, "Hard goods sale").get("cogs_cost_structure_group") is not None,
        f"group={row_of(ops, 'Plant sale').get('cogs_cost_structure_group')!r}")

  print()
  print("=" * 78)
  print("ITEM 2 -- THE COLLAPSE COMES FROM A DECLARATION, NOT FROM EQUAL NUMBERS")
  print("=" * 78)
  print("mini 4d: two lines both stated at 55% in one ordinary message minted")
  print("'shared:hard goods sale+plant sale', the receipt told the client all 2")
  print("lines were collapsed, and the production evaluator PASSED it citing a")
  print("collapse the client never declared. mini 4e: the same declaration split")
  print("over two messages minted nothing and was filed as a RECURRENCE.")
  print()

  def overrides(*pairs):
    return {"financials.cogs_per_line_overrides": [
      {"line_name": n, "cogs_percent": p, "cogs_percent_unit": "ratio"} for n, p in pairs]}

  # (a) N=2 COINCIDENCE -- no group, and the receipt claims none.
  ops = ops_of(line("Plant sale"), line("Hard goods sale"))
  receipt = door(overrides(("Plant sale", 0.55), ("Hard goods sale", 0.55)), ops_json=ops)
  text = say(receipt)
  check("2a N=2 coincidence mints NO group",
        row_of(ops, "Plant sale").get("cogs_cost_structure_group") is None
        and not receipt["grouped"],
        f"group={row_of(ops, 'Plant sale').get('cogs_cost_structure_group')!r}")
  check("2b the receipt does not claim a collapse",
        "sharing one direct-cost rate" not in text,
        repr(text))

  # (b) N=4 IN ONE PATCH -- minted, but as the app's reading, and it says so.
  ops = ops_of(line("A"), line("B"), line("C"), line("D"))
  receipt = door(overrides(("A", 0.55), ("B", 0.55), ("C", 0.55), ("D", 0.55)), ops_json=ops)
  text = say(receipt)
  check("2c N=4 uniform mints the group",
        len({row_of(ops, n).get("cogs_cost_structure_group") for n in "ABCD"}) == 1
        and row_of(ops, "A").get("cogs_cost_structure_group") is not None,
        f"group={row_of(ops, 'A').get('cogs_cost_structure_group')!r}")
  check("2d the stored group names its own authority",
        row_of(ops, "A").get("cogs_cost_structure_group_basis")
        == "inferred from identical stated rates",
        f"basis={row_of(ops, 'A').get('cogs_cost_structure_group_basis')!r}")
  check("2e the receipt names the inference as an inference",
        "so I've recorded them as sharing one cost structure" in text
        and "say so if any of them should be separate" in text,
        repr(text))
  verdict = ir._assert_ops_per_line_cogs(_FakeCur(ops), "draft", {})
  check("2f the assertion passes it WITHOUT calling it the client's own",
        verdict["verdict"] == "pass"
        and "the client's own recorded collapse" not in verdict["detail"]
        and "inferred from identical stated rates" in verdict["detail"],
        f"{verdict['verdict']}: {verdict['detail']}")

  # (c) mini 4e -- THE SAME DECLARATION SPLIT OVER TWO MESSAGES.
  ops = ops_of(line("A"), line("B"), line("C"), line("D"))
  door(overrides(("A", 0.55), ("B", 0.55)), ops_json=ops)
  check("2g half-written mints nothing yet",
        row_of(ops, "A").get("cogs_cost_structure_group") is None,
        "two of four rows carry a rate")
  receipt = door(overrides(("C", 0.55), ("D", 0.55)), ops_json=ops)
  verdict = ir._assert_ops_per_line_cogs(_FakeCur(ops), "draft", {})
  check("2h the second message completes the collapse (POST-WRITE state)",
        len({row_of(ops, n).get("cogs_cost_structure_group") for n in "ABCD"}) == 1
        and row_of(ops, "A").get("cogs_cost_structure_group") is not None
        and verdict["verdict"] == "pass",
        f"{verdict['verdict']}: {verdict['detail']}")

  # (d) THE DECLARED PATH -- the client says it, and the artifact says they did.
  ops = ops_of(line("A", pct=0.55), line("B", pct=0.55), line("C", pct=0.55),
               line("D", pct=0.55))
  receipt = door(
    {"financials.cogs_shared_structure_groups": [["A", "B", "C", "D"]]}, ops_json=ops)
  verdict = ir._assert_ops_per_line_cogs(_FakeCur(ops), "draft", {})
  check("2i a DECLARED all-lines collapse is recorded as declared",
        row_of(ops, "A").get("cogs_cost_structure_group_basis") == "declared"
        and verdict["verdict"] == "pass"
        and "the client's own recorded collapse" in verdict["detail"],
        f"basis={row_of(ops, 'A').get('cogs_cost_structure_group_basis')!r}; "
        f"{verdict['verdict']}: {verdict['detail']}")

  # (e) A PATCH THAT WRITES NOTHING mints nothing (the net fires on a
  #     statement, never on a passing read).
  ops = ops_of(line("A", pct=0.55), line("B", pct=0.55), line("C", pct=0.55))
  door({"financials.cogs_per_line_overrides": [
    {"line_name": "nothing like these", "cogs_percent": 55, "cogs_percent_unit": "percent"}]},
    ops_json=ops)
  check("2j an unmatched patch mints no group",
        row_of(ops, "A").get("cogs_cost_structure_group") is None,
        "three rows already share a rate; nothing this patch wrote")

  # (f) NOTHING LOOSENED: a partial collapse still fails.
  ops = ops_of(line("A", pct=0.55), line("B", pct=0.55), line("C", pct=0.55),
               line("D", pct=0.55))
  for n in ("A", "B"):
    row_of(ops, n)["cogs_cost_structure_group"] = "shared:a+b"
    row_of(ops, n)["cogs_cost_structure_group_basis"] = "declared"
  verdict = ir._assert_ops_per_line_cogs(_FakeCur(ops), "draft", {})
  check("2k a PARTIAL collapse over identical rates still fails",
        verdict["verdict"] == "fail",
        f"{verdict['verdict']}: {verdict['detail']}")

  print()
  print("=" * 78)
  print("ITEM 3 -- THE DELETED RULE IS DELETED, AND NOTHING RESCALES A BLEND")
  print("=" * 78)
  print("mini: _normalize_ratio_like divides by 100 only above 1.0, so 'COGS is")
  print("1% of revenue' stores 100% on the BLENDED rate the engine consumes when")
  print("cogs_basis is ratio -- and the correction path stored it with no")
  print("conversion at all, so 71 would have been 7,100%.")
  print()
  print("THE SHAPE THAT SHIPPED, and why it is not the per-line one: a unit KEY")
  print("for the blend was built and driven LIVE, and the router stopped patching")
  print("altogether on 3 of 4 wordings -- it asked the client 'what should we use")
  print("as the unit for COGS as a percent of revenue?', including on a per-line")
  print("collapse message. An always-allowed structural field is one the router")
  print("asks about (the documented ops.product_overrides trap). So field_basis's")
  print("own law stands instead: the ROUTER converts to the declared basis, and")
  print("the applier REFUSES anything that is not a fraction rather than picking")
  print("a rescaling for it. Rescaling was the bug; refusing is not a threshold.")
  print()

  check("3a the guessing helper is GONE, not routed around",
        not hasattr(ic, "_normalize_ratio_like"),
        "intake_consult._normalize_ratio_like: "
        + ("absent" if not hasattr(ic, "_normalize_ratio_like") else "STILL DEFINED"))

  def stage(value, message, field="cogs_percent_of_revenue", active="cogs"):
    rep: dict = {}
    out = ic._normalize_financials_router_patch(
      patch={f"financials.{field}": value}, active_stage=active,
      financials_json={"current_revenue": 1_000_000.0},
      financials_year1_json={"company_revenue_total_year1": 1_000_000.0},
      last_assistant="What are your direct costs?", user_message=message, report=rep,
    )
    return ((out or {}).get(field), rep)

  # A FRACTION IS STORED VERBATIM -- no ladder, no rescaling, either direction.
  for raw, want, label in [
    (0.01, 0.01, "'direct costs are about 1 percent of revenue' -> 0.01"),
    (0.005, 0.005, "'half a point of revenue' -> 0.005"),
    (0.71, 0.71, "'71 percent of revenue' -> 0.71"),
    (0.38, 0.38, "'a ratio of 0.38 of revenue' -> 0.38"),
  ]:
    got, _rep = stage(raw, f"the figure is {raw} of revenue")
    check(f"3b stage {label}", got == want, f"stored {got!r}, meant {want!r}")

  # THE DELETED RULE'S OWN CASE: 71 used to become 0.71 here. It is not a
  # fraction, so it is refused -- and the client hears that it did not land.
  got, rep = stage(71, "direct costs run 71 percent of revenue")
  check("3c stage - a non-fraction is REFUSED, never rescaled",
        got is None and "cogs_percent_of_revenue" in (rep.get("dropped") or []),
        f"stored {got!r}; report dropped={rep.get('dropped')!r}")
  got, rep = stage(1.5, "direct costs run 150 percent of revenue")
  check("3d stage - out of range in the other direction is refused too",
        got is None, f"1.5 stored {got!r} instead of being refused")
  got, rep = stage(0.06, "marketing is 6 percent of revenue",
                   field="marketing_percent_of_revenue", active="marketing")
  check("3e POSITIVE CONTROL - the marketing twin still lands a fraction",
        got == 0.06, f"stored {got!r}")

  # A TRANSPORT KEY IS NOT AN UNAPPLIED FIELD. It rides in the same patch as
  # the stage answer and is consumed by its own door; reporting it as dropped
  # tells the client the app failed to record something they never said.
  rep: dict = {}
  ic._normalize_financials_router_patch(
    patch={"financials.cogs_percent_of_revenue": 0.38,
           "financials.cogs_per_line_overrides": [
             {"line_name": "A", "cogs_percent": 38, "cogs_percent_unit": "percent"}]},
    active_stage="cogs", financials_json={"current_revenue": 1_000_000.0},
    financials_year1_json={"company_revenue_total_year1": 1_000_000.0},
    last_assistant="What are your direct costs?",
    user_message="direct costs are 0.38 of revenue and line A is 38 percent", report=rep)
  check("3k a transport key is never reported as an unapplied field",
        rep.get("applied") == ["cogs_percent_of_revenue"] and not (rep.get("dropped") or []),
        f"applied={rep.get('applied')!r} dropped={rep.get('dropped')!r}")

  # STATED, NOT A DEFECT OF THIS FIX: a wordless figure ("half a point", no
  # digit in the message) is dropped by the mid-intake DERIVABILITY guard on
  # the stage path, before and after this change - the guard needs a figure in
  # the turn's content. The per-line door has no such guard, which is why
  # mini's live "half a point" landed there. Pinned so the difference between
  # the two doors is a recorded fact rather than a surprise.
  got, rep = stage(0.005, "call it half a point of revenue")
  check("3i wordless figures are the derivability guard's business",
        got is None,
        f"stored {got!r} - dropped by _guard_underivable_stage_writes (no figure "
        "in the message), which is pre-existing and unchanged by round 8")

  # THE CORRECTION PATH, which had NO conversion at all: 71 stored 7,100%.
  ops = ops_of(line("Plant sale"), line("Hard goods sale"))
  _ops, fin = scoped({"financials.cogs_percent_of_revenue": 0.71}, ops)
  check("3f correction path stores a fraction and tags the basis",
        fin.get("cogs_percent_of_revenue") == 0.71 and fin.get("cogs_basis") == "ratio",
        f"stored {fin.get('cogs_percent_of_revenue')!r} basis={fin.get('cogs_basis')!r}")
  _ops, fin = scoped({"financials.cogs_percent_of_revenue": 71}, ops)
  _receipt = fin.get("_per_line_cogs_receipt") or {}
  check("3g correction path REFUSES a non-fraction and asks",
        "cogs_percent_of_revenue" not in fin
        and bool(_receipt.get("unit_unclear"))
        and "percent or a fraction" in say(_receipt),
        f"stored={fin.get('cogs_percent_of_revenue')!r}; asked={say(_receipt)!r}")
  check("3h the blend question does not borrow the per-line wording",
        "of revenue, and I won't guess" in say(_receipt),
        repr(say(_receipt)))

  print()
  print("=" * 78)
  print(f"RESULT: {'ALL CLEAN' if not FAILURES else 'RED -- ' + ', '.join(FAILURES)}")
  print("=" * 78)
  return 1 if FAILURES else 0


class _FakeCur:
  """The evaluator reads the ops model through a cursor; this hands it the
  in-memory rows so the assertion under test is the production one."""

  def __init__(self, ops):
    self._ops = ops

  def execute(self, *_a, **_k):
    return None

  def fetchone(self):
    import json
    return (json.dumps(self._ops),)

  def close(self):
    return None


if __name__ == "__main__":
  raise SystemExit(main())
