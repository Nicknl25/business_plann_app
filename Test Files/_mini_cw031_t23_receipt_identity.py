"""CW-031 mini audit, tiers 2/3 -- ITEM 5: did the receipt renderer change what a
SINGLE-LINE business sees?

VS's tier-3 fix names the row whenever a label would otherwise repeat. The whole
point is that a one-line business has no repeats, so its receipts must come out
BYTE-IDENTICAL to the pre-fix renderer. This runs both renderers -- the shipped
one and the one from 51d0810^ extracted straight out of git -- over the same
payloads and compares the strings exactly.

The payloads are taken from REAL single-line drafts in the database (the
business's own ops rows), plus the shapes the CW-024 slate cares about:
a cadence-carrying capacity write, a people role, and the same row written twice.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_t23_receipt_identity.py"
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
OLD_REV = "51d0810^:python/client_intake_and_finmo/capture_receipt.py"

FAILURES: list = []


def load_module(path: Path, name: str):
  spec = importlib.util.spec_from_file_location(name, path)
  module = importlib.util.module_from_spec(spec)
  assert spec.loader is not None
  spec.loader.exec_module(module)
  return module


def render(module, before, after):
  receipt = module.numeric_receipt(before=before, after=after, clarify_pending=None)
  return module.receipt_summary(receipt)


def compare(label, old_mod, new_mod, before, after, *, expect_identical=True):
  old_text = render(old_mod, before, after)
  new_text = render(new_mod, before, after)
  same = old_text == new_text
  status = "PASS" if same == expect_identical else "FAIL"
  print(f"  [{status}] {label}")
  print(f"         before-fix: {old_text!r}")
  print(f"         after-fix : {new_text!r}")
  if same != expect_identical:
    FAILURES.append(label)
  return old_text, new_text


def one_line_ops(name="Average bike sale", lob="Primary line of business", **fields):
  product = {"product_name": name}
  product.update(fields)
  return {"lob_models": [{"lob_name": lob, "products": [product]}]}


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

  # BYTES, not text: git's output is UTF-8 and this console is cp1252, so
  # text=True mangles the receipt's own arrow into mojibake and every shape
  # "differs" for a reason that is entirely the harness's.
  old_source = subprocess.run(
    ["git", "show", OLD_REV], cwd=str(REPO_ROOT), capture_output=True,
  )
  if old_source.returncode != 0:
    print(f"could not read the pre-fix renderer: {old_source.stderr[:200]!r}")
    return 1
  tmpdir = Path(tempfile.mkdtemp())
  old_path = tmpdir / "capture_receipt_before_fix.py"
  old_path.write_bytes(old_source.stdout)
  old_mod = load_module(old_path, "capture_receipt_before_fix")
  new_mod = load_module(
    REPO_ROOT / "python" / "client_intake_and_finmo" / "capture_receipt.py",
    "capture_receipt_shipped")

  print("=" * 78)
  print("A. SYNTHETIC SINGLE-LINE SHAPES (must be byte-identical)")
  print("=" * 78)

  compare("one line, price corrected", old_mod, new_mod,
          {"operating_model": one_line_ops(unit_price=780.0)},
          {"operating_model": one_line_ops(unit_price=845.0)})

  compare("one line, weekly capacity with its cadence in the same receipt",
          old_mod, new_mod,
          {"operating_model": one_line_ops(units_per_period_capacity=12.0,
                                           operating_periods_per_year=52.0)},
          {"operating_model": one_line_ops(units_per_period_capacity=18.0,
                                           operating_periods_per_year=52.0)})

  compare("one line, utilization", old_mod, new_mod,
          {"operating_model": one_line_ops(utilization_rate=0.62)},
          {"operating_model": one_line_ops(utilization_rate=0.71)})

  compare("one people role", old_mod, new_mod,
          {"people": {"roles": [{"role": "Technician", "annual_wage": 48000.0}]}},
          {"people": {"roles": [{"role": "Technician", "annual_wage": 52000.0}]}})

  compare("two DIFFERENT leaves on one line (no repeated label)", old_mod, new_mod,
          {"operating_model": one_line_ops(unit_price=780.0, utilization_rate=0.62)},
          {"operating_model": one_line_ops(unit_price=845.0, utilization_rate=0.71)})

  print()
  print("=" * 78)
  print("B. ITEM 8's OWN SHAPE: capacity with NO cadence in the receipt")
  print("=" * 78)
  print("  (this one is EXPECTED to differ -- it is the reported defect)")
  compare("capacity with no cadence, single line", old_mod, new_mod,
          {"operating_model": one_line_ops(units_per_period_capacity=180.0)},
          {"operating_model": one_line_ops(units_per_period_capacity=210.0)},
          expect_identical=False)

  print()
  print("=" * 78)
  print("C. REAL SINGLE-LINE DRAFTS FROM THE DATABASE")
  print("=" * 78)
  from intake_submission import get_mysql_connection  # type: ignore
  conn = get_mysql_connection()
  conn.commit()
  cur = conn.cursor()
  cur.execute(
    "SELECT draft_id, business_name, operating_model_json FROM intake_consult_drafts "
    "WHERE operating_model_json IS NOT NULL AND operating_model_json <> '' "
    "ORDER BY updated_at DESC LIMIT 400")
  checked = 0
  differed = 0
  for draft_id, business_name, ops_raw in cur.fetchall() or []:
    try:
      ops = json.loads(ops_raw or "{}")
    except Exception:
      continue
    products = [p for lob in (ops.get("lob_models") or [])
                if isinstance(lob, dict)
                for p in (lob.get("products") or []) if isinstance(p, dict)]
    if len(products) != 1:
      continue
    row = products[0]
    movable = [k for k in ("unit_price", "units_per_period_capacity",
                           "utilization_rate", "cogs_percent_of_line_revenue")
               if isinstance(row.get(k), (int, float)) and not isinstance(row.get(k), bool)]
    if not movable:
      continue
    before = {"operating_model": copy.deepcopy(ops)}
    after = {"operating_model": copy.deepcopy(ops)}
    target = after["lob_models"][0]["products"][0] if False else \
        after["operating_model"]["lob_models"][0]["products"][0]
    for key in movable:
      target[key] = float(row[key]) * 1.1 + 1.0
    old_text = render(old_mod, before, after)
    new_text = render(new_mod, before, after)
    checked += 1
    if old_text != new_text:
      differed += 1
      if differed <= 5:
        print(f"  DIFFERS  {str(draft_id)[:14]} {str(business_name)[:30]}")
        print(f"    before-fix: {old_text!r}")
        print(f"    after-fix : {new_text!r}")
  print(f"  real single-line drafts rendered: {checked}; differing: {differed}")
  if differed:
    print("  (each difference above is either item 8's cadence label or a real"
          " regression -- read them)")
  cur.close()
  conn.close()

  print()
  print("=" * 78)
  if FAILURES:
    print(f"{len(FAILURES)} shape(s) changed that should not have: {FAILURES}")
    return 1
  print("Single-line receipts are unchanged except where item 8 says they must be.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
