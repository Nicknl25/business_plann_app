"""CW-031 tier 3 red-proof: the receipt line says one thing per thing.

THE BUGS, all from the Ravenwood transcript, all in one renderer:

  item 6  "(Noted: operating periods per year -> 52; operating periods per
          year -> 52; operating periods per year -> 52; operating periods per
          year -> 52 (and 1 more)" - four DIFFERENT product rows rendered with
          identical words, so the note reads like one value repeated. The
          underlying broadcast was benign; the note was not.
  item 7  "weekly capacity -> 180; weekly capacity -> 180" - the same thing
          said twice in one acknowledgment.
  item 8  a weekly label over a monthly-cadence unit.

All three are rendering faults in receipt_summary/_fmt: it formatted each path
in isolation and never looked across the line it was building.

THE PRODUCTION CHAIN: numeric_receipt -> receipt_summary, the deterministic
receipt every financials acknowledgment is built from.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_receipt_copy.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FAILURES: list = []


def check(label: str, ok: bool, detail: str) -> None:
  print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")
  if not ok:
    FAILURES.append(label)


def ravenwood_ops(capacities, periods=52.0):
  """The real four-line shape: four products, each on its own row."""
  names = ["Plant sale", "Hard goods sale", "Install project", "Design consult"]
  lobs = ["Plant/nursery sales", "Hard goods & materials",
          "Landscaping & installation", "Garden design consultations"]
  return {
    "lob_models": [
      {"lob_name": lob,
       "products": [{
         "product_name": name,
         "units_per_week_capacity": cap,
         "operating_periods_per_year": periods,
       }]}
      for lob, name, cap in zip(lobs, names, capacities)
    ]
  }


def main() -> int:
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from client_intake_and_finmo.capture_receipt import (  # type: ignore
    numeric_receipt, receipt_summary,
  )

  print("STEP 1 - item 6: four lines, four rows, four DISTINCT phrases")
  before = {"ops": ravenwood_ops([None, None, None, None])}
  after = {"ops": ravenwood_ops([420.0, 180.0, 12.0, 6.0])}
  receipt = numeric_receipt(before=before, after=after)
  text = receipt_summary(receipt)
  print(f"  {text}")
  check("each line is named when the phrase would repeat",
        all(n in text for n in ("Plant sale", "Hard goods sale")),
        "the reader can tell which line is which")
  check("no phrase appears twice",
        len(text.split("; ")) == len(set(text.split("; "))),
        f"{len(text.split('; '))} parts, all distinct")

  print("\nSTEP 2 - item 6 red: the identical-value case is the one that broke")
  # The literal Ravenwood note: every line carrying the SAME transient value.
  same = {"ops": ravenwood_ops([420.0, 420.0, 420.0, 420.0])}
  receipt_same = numeric_receipt(before=before, after=same)
  text_same = receipt_summary(receipt_same)
  print(f"  {text_same}")
  check("four rows at one value do not read as one phrase repeated",
        text_same.count("weekly capacity → 420") <= 1
        or all(n in text_same for n in ("Plant sale", "Hard goods sale")),
        "each repeat is attributed to its line")
  check("the note never repeats a bare phrase verbatim",
        "→ 420; weekly capacity → 420" not in text_same,
        "the reported defect string is unrepresentable")

  print("\nSTEP 3 - item 7: the same thing is said once")
  # One row, one leaf, rendered from a receipt that carries it twice - the
  # doubled-line shape.
  doubled = {
    "written": [
      ("ops.lob_models[0].products[0].units_per_week_capacity", None, 180.0),
      ("ops.lob_models[0].products[0].units_per_week_capacity", None, 180.0),
    ],
    "dropped": [],
    "periods_by_prefix": {"ops.lob_models[0].products[0]": 52.0},
    "names_by_prefix": {"ops.lob_models[0].products[0]": "Plant sale"},
  }
  doubled_text = receipt_summary(doubled)
  print(f"  {doubled_text}")
  check("a doubled write acknowledges once",
        doubled_text.count("180") == 1, doubled_text)

  print("\nSTEP 4 - item 8: no weekly label over a non-weekly cadence")
  monthly_before = {"ops": {"lob_models": [{"lob_name": "L", "products": [
    {"product_name": "Contract", "units_per_period_capacity": None,
     "operating_periods_per_year": 12.0}]}]}}
  monthly_after = {"ops": {"lob_models": [{"lob_name": "L", "products": [
    {"product_name": "Contract", "units_per_period_capacity": 9.0,
     "operating_periods_per_year": 12.0}]}]}}
  monthly_text = receipt_summary(numeric_receipt(before=monthly_before, after=monthly_after))
  print(f"  {monthly_text}")
  check("a monthly-cadence capacity is labelled monthly",
        "monthly capacity" in monthly_text and "weekly" not in monthly_text,
        monthly_text)

  unknown = {
    "written": [("ops.lob_models[0].products[0].units_per_period_capacity", None, 9.0)],
    "dropped": [], "periods_by_prefix": {}, "names_by_prefix": {},
  }
  unknown_text = receipt_summary(unknown)
  print(f"  {unknown_text}")
  check("an unknown cadence claims no cadence at all",
        "weekly" not in unknown_text and "capacity" in unknown_text,
        unknown_text)

  print("\nSTEP 5 - the receipt still says what it always said when nothing repeats")
  plain = {"ops": {"lob_models": [{"lob_name": "L", "products": [
    {"product_name": "Only line", "unit_price": 38.0,
     "operating_periods_per_year": 52.0}]}]}}
  plain_before = {"ops": {"lob_models": [{"lob_name": "L", "products": [
    {"product_name": "Only line", "unit_price": None,
     "operating_periods_per_year": 52.0}]}]}}
  plain_text = receipt_summary(numeric_receipt(before=plain_before, after=plain))
  print(f"  {plain_text}")
  check("a single unambiguous change is not decorated with a line name",
        plain_text.startswith("unit price") and "Only line" not in plain_text,
        plain_text)
  check("nothing written still says nothing",
        receipt_summary({"written": [], "dropped": []}) == "",
        "empty receipt, empty claim")

  print("\n" + "=" * 72)
  if FAILURES:
    print(f"RED - {len(FAILURES)} check(s) failed: {FAILURES}")
    return 1
  print("GREEN - the receipt names its rows, says each thing once, and claims no cadence it does not know.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
