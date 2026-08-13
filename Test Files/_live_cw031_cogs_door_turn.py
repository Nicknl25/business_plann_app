"""CW-031 tier 2, the LIVE half of A-110: does the ROUTER reach the door?

The offline proof (_redproof_cw031_cogs_write_door.py) shows the write works
once the patch exists. That was never the failing half. The failing half was
that NOTHING the client could say produced such a patch -- the field had no
intent, so six corrections across three phrasings died at the router.

So this drives the real thing: a clone of the REAL Ravenwood draft (four lines,
all four cogs_percent_of_line_revenue null, exactly as delivered), the live
:5050 backend, the live GPT router, and the client's OWN words from the
transcript. Nothing is stubbed. The proof is the persisted ops rows afterwards.

  turn 79  "Close but not quite - let me give you my real ones. Plants are 48%..."
  turn 113 "Plant sale and Hard goods sale should share one direct-cost rate..."

  .venv\\Scripts\\python.exe "Test Files\\_live_cw031_cogs_door_turn.py"
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:5050"
SOURCE_DRAFT = "1070c6a560a04f3d971019a3787180bf"

RATES_MESSAGE = (
  "Close but not quite - let me give you my real ones. Plants are 48%, we mark "
  "those up properly. Hard goods are 71%, that's the pallet-of-pavers problem I "
  "mentioned. Install is only 19% in materials because the labour is all on my "
  "payroll. And design is 4%, basically just printing and the odd site survey."
)
COLLAPSE_MESSAGE = (
  "Plant sale and Hard goods sale should share one direct-cost rate. Install "
  "project keeps its own. Design consult keeps its own."
)

FAILURES: list = []


def check(label: str, ok: bool, detail: str) -> None:
  print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")
  if not ok:
    FAILURES.append(label)


def ops_rates(conn, draft_id):
  # REPEATABLE READ: this connection's snapshot was taken at its first read,
  # so without ending the transaction it keeps showing the pre-POST state and
  # a working write reads back as null. (The app itself was never wrong here -
  # the second live turn read the first turn's rates straight out of MySQL.)
  try:
    conn.commit()
  except Exception:
    pass
  cur = conn.cursor()
  cur.execute(
    "SELECT operating_model_json FROM intake_consult_drafts WHERE draft_id=%s",
    (draft_id,),
  )
  row = cur.fetchone()
  cur.close()
  ops = json.loads((row[0] if row else None) or "{}")
  out = {}
  for lob in ops.get("lob_models") or []:
    for product in lob.get("products") or []:
      out[str(product.get("product_name"))] = {
        "pct": product.get("cogs_percent_of_line_revenue"),
        "group": product.get("cogs_cost_structure_group"),
      }
  return out


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  clone_id = "a110" + uuid.uuid4().hex[:28]
  try:
    print("STEP 0 - clone the REAL Ravenwood draft (same rows, new id)")
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
    src = cur.fetchone()
    cur.close()
    if not src:
      print("  source draft missing")
      return 1
    columns = [c for c in src.keys() if c not in ("id",)]
    values = []
    for c in columns:
      v = src[c]
      if c == "draft_id":
        v = clone_id
      elif c == "client_id":
        v = "A110" + uuid.uuid4().hex[:14].upper()
      values.append(v)
    cur = conn.cursor()
    cur.execute(
      f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
      f"VALUES ({', '.join(['%s'] * len(columns))})",
      tuple(values),
    )
    conn.commit()
    cur.close()
    client_id = values[columns.index("client_id")]
    before = ops_rates(conn, clone_id)
    print(f"  clone {clone_id[:16]} lines={list(before)}")
    check("the clone starts in the delivered (broken) state",
          len(before) == 4 and all(v["pct"] is None for v in before.values()),
          "4 lines, all per-line COGS null")

    print("\nSTEP 1 - the client's own correction, POSTed to the live backend")
    print(f"  > {RATES_MESSAGE[:90]}...")
    resp = requests.post(
      f"{BASE_URL}/api/intake-consult",
      json={"draft_id": clone_id, "client_id": client_id, "message": RATES_MESSAGE},
      timeout=300,
    )
    body = resp.json() if resp.status_code == 200 else {}
    print(f"  < [{resp.status_code}] {str(body.get('assistant_message') or '')[:400]}")
    after = ops_rates(conn, clone_id)
    print(f"  ops now: { {k: v['pct'] for k, v in after.items()} }")
    check("the live turn returned 200", resp.status_code == 200, str(resp.status_code))
    check("the four client rates are PERSISTED on the ops rows",
          {k: v["pct"] for k, v in after.items()} == {
            "Plant sale": 0.48, "Hard goods sale": 0.71,
            "Install project": 0.19, "Design consult": 0.04},
          "48/71/19/4 through the live router")
    check("the reply speaks the write, not a promise",
          "48" in str(body.get("assistant_message") or ""),
          "the receipt names a rate that is now stored")

    print("\nSTEP 2 - the collapse instruction, same live path")
    print(f"  > {COLLAPSE_MESSAGE}")
    resp2 = requests.post(
      f"{BASE_URL}/api/intake-consult",
      json={"draft_id": clone_id, "client_id": client_id, "message": COLLAPSE_MESSAGE},
      timeout=300,
    )
    body2 = resp2.json() if resp2.status_code == 200 else {}
    print(f"  < [{resp2.status_code}] {str(body2.get('assistant_message') or '')[:400]}")
    final = ops_rates(conn, clone_id)
    print(f"  ops now: {json.dumps(final, ensure_ascii=False)}")
    check("the live turn returned 200", resp2.status_code == 200, str(resp2.status_code))
    check("the two named lines share ONE rate",
          final["Plant sale"]["pct"] == final["Hard goods sale"]["pct"] is not None,
          f"{final['Plant sale']['pct']} on both")
    check("the lines kept separate are untouched",
          final["Install project"]["pct"] == 0.19
          and final["Design consult"]["pct"] == 0.04,
          "install 19%, design 4%")
    check("the client's grouping is stored on the rows",
          final["Plant sale"]["group"] == final["Hard goods sale"]["group"] is not None
          and not final["Install project"]["group"],
          str(final["Plant sale"]["group"]))
    check("three distinct rates for four lines, as the client asked",
          len({v["pct"] for v in final.values()}) == 3,
          f"{len({v['pct'] for v in final.values()})} distinct")
  finally:
    try:
      cur = conn.cursor()
      cur.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s", (clone_id,))
      conn.commit()
      cur.close()
      print(f"\n  (clone {clone_id[:16]} removed)")
    except Exception:
      pass
    try:
      conn.close()
    except Exception:
      pass

  print("\n" + "=" * 72)
  if FAILURES:
    print(f"RED - {len(FAILURES)} check(s) failed: {FAILURES}")
    return 1
  print("GREEN - the client's words reach the model through the live router.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
