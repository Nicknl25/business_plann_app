"""CW-031 mini audit, tiers 2/3 -- ITEM 3: the workbook_deliveries binding, on
artifacts, plus a census that grades the unnamed-row hazard from the collapse probe.

  1. the canary row (draft e7da60e6, run b0622f56) exists and
     resolve_workbook_for_draft returns basis="delivery record" for it;
  2. the Thistledown false-PASS mini found last round is really dead;
  3. how many REAL product rows carry no product_name (the wildcard the loose
     branch of _resolve_cogs_line turns into "matches any wording").

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_t23_binding_probe.py"
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
CANARY_DRAFT_PREFIX = "e7da60e6"
THISTLEDOWN_REAL = "be84629ada44"


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore
  from client_intake_and_finmo import workbook_delivery_record as wdr  # type: ignore
  from client_intake_and_finmo import issue_registry  # type: ignore

  delivery_dir = (os.getenv("FINMO_MODEL_DELIVERY_DIR") or "").strip()
  conn = get_mysql_connection()
  conn.commit()
  cur = conn.cursor()

  print("=" * 78)
  print("1. THE DELIVERY RECORDS THAT EXIST")
  print("=" * 78)
  try:
    cur.execute(
      "SELECT id, draft_id, planning_run_id, workbook_filename, delivered_at "
      "FROM workbook_deliveries ORDER BY id")
    rows = cur.fetchall() or []
  except Exception as exc:
    print(f"  table unreadable: {exc}")
    rows = []
  for r in rows:
    print(f"  #{r[0]} draft={r[1][:16]} run={str(r[2])[:16]} at={r[4]}")
    print(f"       file={r[3]}")
  canary = [r for r in rows if str(r[1]).startswith(CANARY_DRAFT_PREFIX)]
  print(f"  -> {len(rows)} delivery row(s); canary rows matching "
        f"{CANARY_DRAFT_PREFIX}*: {len(canary)}")

  print()
  print("=" * 78)
  print("2. RESOLUTION BASIS PER DRAFT")
  print("=" * 78)
  targets = [str(r[1]) for r in rows]
  cur.execute(
    "SELECT draft_id, business_name FROM intake_consult_drafts "
    "WHERE business_name LIKE 'Thistledown%%'")
  thistle = cur.fetchall() or []
  targets += [str(d[0]) for d in thistle]
  seen = set()
  for draft_id in targets:
    if draft_id in seen:
      continue
    seen.add(draft_id)
    res = wdr.resolve_workbook_for_draft(cur, draft_id, delivery_dir=delivery_dir)
    print(f"  {draft_id[:16]}  basis={res['basis']:<16} {res['detail'][:96]}")

  print()
  print("=" * 78)
  print("3. THE FALSE PASS mini FOUND LAST ROUND -- is it dead?")
  print("=" * 78)
  real = [str(d[0]) for d in thistle if str(d[0]).startswith(THISTLEDOWN_REAL)]
  if not real:
    print(f"  draft {THISTLEDOWN_REAL}* not found")
  for draft_id in real:
    ops = issue_registry._load_ops_model(cur, draft_id)
    rows_ops = issue_registry._ops_product_rows(ops or {})
    written = [r.get("cogs_percent_of_line_revenue") for r in rows_ops]
    print(f"  ops rows carrying a per-line COGS rate: "
          f"{sum(1 for w in written if w is not None)}/{len(rows_ops)} -> {written}")
    out = issue_registry._assert_workbook_cogs_rows(
      cur, draft_id, {"kind": "workbook_cogs_rows", "min_rows": 2})
    print(f"  workbook_cogs_rows: {out['verdict']} - {out['detail'][:150]}")

  print()
  print("=" * 78)
  print("4. CENSUS: real product rows with NO product_name (the wildcard row)")
  print("=" * 78)
  cur.execute(
    "SELECT draft_id, business_name, operating_model_json FROM intake_consult_drafts "
    "WHERE operating_model_json IS NOT NULL AND operating_model_json <> ''")
  total_drafts = blank_rows = drafts_with_blank = 0
  examples = []
  for draft_id, business_name, ops_raw in cur.fetchall() or []:
    try:
      ops = json.loads(ops_raw or "{}")
    except Exception:
      continue
    total_drafts += 1
    local = 0
    for lob in ops.get("lob_models") or []:
      if not isinstance(lob, dict):
        continue
      for product in lob.get("products") or []:
        if not isinstance(product, dict):
          continue
        name = str(product.get("product_name") or product.get("name") or "").strip()
        if not name:
          local += 1
    if local:
      drafts_with_blank += 1
      blank_rows += local
      if len(examples) < 8:
        examples.append((str(draft_id)[:16], str(business_name)[:34], local))
  print(f"  drafts with an ops model: {total_drafts}")
  print(f"  drafts carrying >=1 UNNAMED product row: {drafts_with_blank} "
        f"({blank_rows} rows)")
  for e in examples:
    print(f"    {e[0]}  {e[1]:<34} {e[2]} unnamed row(s)")

  cur.close()
  conn.close()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
