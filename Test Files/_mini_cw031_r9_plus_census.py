"""mini, round 9 audit: census for the '+' label trap -- how many real drafts
carry a product or LOB name containing '+' (the character the group label uses
as its membership separator)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env", override=False)
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
from intake_submission import get_mysql_connection  # type: ignore

conn = get_mysql_connection()
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT draft_id, operating_model_json FROM intake_consult_drafts "
            "WHERE operating_model_json IS NOT NULL AND operating_model_json != ''")
total = with_ops = 0
hits = []
for draft_id, ops_raw in cur.fetchall():
  total += 1
  try:
    ops = json.loads(ops_raw or "{}")
  except Exception:
    continue
  lobs = ops.get("lob_models") or []
  if not lobs:
    continue
  with_ops += 1
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    names = [str(lob.get("lob_name") or lob.get("name") or "")]
    names += [str(p.get("product_name") or p.get("name") or "")
              for p in (lob.get("products") or []) if isinstance(p, dict)]
    plus = [n for n in names if "+" in n]
    if plus:
      hits.append((draft_id, plus))
cur.close()
conn.close()
print(f"drafts scanned: {total}; with lob_models: {with_ops}")
print(f"drafts with a '+' in a product/LOB name: {len(hits)}")
for draft_id, plus in hits[:20]:
  print(f"  {draft_id}: {plus}")
