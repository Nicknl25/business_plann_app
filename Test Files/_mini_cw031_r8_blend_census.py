"""CW-031 round-8 mini audit -- ITEM 3: the refusal's blast radius.

The blend doors now REFUSE cogs_percent_of_revenue / marketing_percent_of_revenue
values outside [0,1] instead of rescaling. Census the real drafts:

  C1  how many drafts CARRY an out-of-[0,1] value in either field today
      (stored damage the old rescale-or-store rules left behind);
  C2  of those, how recent, and what values (is 71-style percent-shaped input
      actually reaching these fields, or is the field always fraction-shaped);
  C3  distribution summary of in-range values (sanity: the field is used).

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r8_blend_census.py"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  try:
    conn.autocommit = True
  except Exception:
    pass
  cur = conn.cursor()
  cur.execute("SELECT draft_id, business_name, created_at, financials_json "
              "FROM intake_consult_drafts "
              "WHERE financials_json IS NOT NULL AND financials_json <> ''")
  rows = cur.fetchall()
  cur.close()
  conn.close()

  total = 0
  carrying = {"cogs_percent_of_revenue": [], "marketing_percent_of_revenue": []}
  out_of_range = []
  in_range_vals = {"cogs_percent_of_revenue": [], "marketing_percent_of_revenue": []}
  for draft_id, name, created, fin_raw in rows:
    try:
      fin = json.loads(fin_raw or "{}")
    except Exception:
      continue
    if not isinstance(fin, dict):
      continue
    total += 1
    for field in carrying:
      v = fin.get(field)
      if v is None:
        continue
      try:
        f = float(v)
      except Exception:
        out_of_range.append((str(draft_id), str(name), str(created), field, repr(v)))
        continue
      carrying[field].append(f)
      if f < 0.0 or f > 1.0:
        out_of_range.append((str(draft_id), str(name), str(created), field, f))
      else:
        in_range_vals[field].append(f)

  print(f"drafts with financials_json parsed: {total}")
  for field, vals in carrying.items():
    print(f"{field}: carried on {len(vals)} drafts")
  print(f"\nOUT OF [0,1]: {len(out_of_range)} field-instances")
  for rec in sorted(out_of_range, key=lambda r: r[2], reverse=True)[:25]:
    print("  ", rec)
  for field, vals in in_range_vals.items():
    if vals:
      vs = sorted(vals)
      print(f"\n{field} in-range: n={len(vs)} min={vs[0]:.4f} "
            f"p50={vs[len(vs)//2]:.4f} max={vs[-1]:.4f}; "
            f"suspicious 0-or-1 exact: {sum(1 for v in vs if v in (0.0, 1.0))}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
