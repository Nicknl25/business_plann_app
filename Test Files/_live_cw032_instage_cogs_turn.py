"""CW-032 A-110, the IN-STAGE live proof - the surface the batch is named for.

THE PRODUCTION CALL CHAIN (named first, per the E2E law):
  POST /api/intake-consult (focus=financials, active stage=cogs)
    -> post_intake_consult_handler -> _run_financials_turn_and_sync
    -> route_intent(consult_type="financials")   <- the starved surface
    -> _apply_stage_cogs_door_keys -> _apply_per_line_cogs_patch_keys
    -> ops rows persist -> THE RECALC derives the blend -> stage advances

This drives a clone of the REAL Alderfen draft (158f6816), REWOUND to the
cogs stage exactly as the run stood at message [74] (the app's own per-line
proposal on the table), against the live :5050 backend and the live GPT
router, with the client's OWN transcript words. Nothing is stubbed. The
proof is the persisted ops rows and the persisted financials afterwards.

Three scenarios, each on a fresh rewound clone:
  S1  message [75]: all four rates in ONE message -> all four rows carry
      the client's numbers, the stage COMPLETES on the derived blend, the
      reply is the receipt + the roll-up + the next stage's question
      (never the Alderfen "I wasn't able to apply that change yet").
  S2  the collapse sentence -> a /shared/ group stored on exactly the
      named rows, basis declared, in-stage.
  S3  ONE line's rate (the [77] retry shape) -> that row written, and the
      recovery question keeps the per-line shape (names the missing
      lines), never the singular blend question.

  .venv\\Scripts\\python.exe "Test Files\\_live_cw032_instage_cogs_turn.py"
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
SOURCE_DRAFT = "158f6816e7a34926b81aba24bc412a51"
PROPOSAL_MESSAGE_INDEX = 74  # the app's per-line proposal, kept as last assistant

MSG_S1 = (
  "Close, but let me give you my actual numbers. Plants are 46%. Hardgoods "
  "are 73% — that's the pallet-of-pavers problem. Install is 17% in "
  "materials because the labour is all on my payroll. And design is 3%, "
  "just printing and the odd soil test."
)
MSG_S2 = (
  "Plants and hardgoods are both bought-in retail goods — treat those "
  "two as sharing one cost structure. Install and design each have their own."
)
MSG_S3 = "Hardgoods sale: 73 percent of that line's revenue."

# Every financials field the cogs stage and everything after it owns - the
# rewind strips these so the cogs stage is the ACTIVE stage again.
_STRIP_FIELDS = (
  "current_cogs", "cogs_total_year1", "cogs_percent_of_revenue",
  "baseline_cogs", "baseline_cogs_percent", "cogs_adjustment",
  "cogs_basis", "cogs_basis_naics", "cogs_basis_years_used",
  "cogs_basis_rationale", "cogs_fit_band", "_cogs_baseline_resolution",
  "current_payroll", "payroll_total_year1", "baseline_payroll_year1",
  "payroll_adjustment", "payroll_basis_people_roles",
  "marketing_total_year1", "marketing_percent_of_revenue",
  "baseline_marketing", "baseline_marketing_percent", "marketing_adjustment",
  "_financials_marketing_stage_done",
  "monthly_rent_expense", "future_rent_expected", "other_operating_expense",
  "current_num_employees", "current_capex", "initial_assets", "initial_lease",
  "initial_equity", "total_debt_outstanding", "other_monthly_debt_payments",
  "annual_interest_payment", "annual_principal_payment", "cash_on_hand",
  "ar_balance", "ap_balance", "inventory_balance", "cash_strategy",
  "funding_preference", "funding_split_debt_share",
)

FAILURES: list = []


def check(label: str, ok: bool, detail: str) -> None:
  print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")
  if not ok:
    FAILURES.append(label)


def _fresh_read(conn, draft_id, column):
  try:
    conn.commit()  # REPEATABLE READ trap - end the snapshot first
  except Exception:
    pass
  cur = conn.cursor()
  cur.execute(
    f"SELECT {column} FROM intake_consult_drafts WHERE draft_id=%s",
    (draft_id,),
  )
  row = cur.fetchone()
  cur.close()
  return json.loads((row[0] if row else None) or "{}")


def ops_rows(conn, draft_id):
  ops = _fresh_read(conn, draft_id, "operating_model_json")
  out = {}
  for lob in ops.get("lob_models") or []:
    for product in lob.get("products") or []:
      out[str(product.get("product_name"))] = {
        "pct": product.get("cogs_percent_of_line_revenue"),
        "group": product.get("cogs_cost_structure_group"),
        "basis": product.get("cogs_cost_structure_group_basis"),
      }
  return out


def make_rewound_clone(conn, tag: str) -> tuple:
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
  src = cur.fetchone()
  cur.close()
  if not src:
    raise RuntimeError("source draft missing")
  clone_id = tag + uuid.uuid4().hex[: 32 - len(tag)]
  client_id = tag.upper() + uuid.uuid4().hex[:10].upper()

  messages = json.loads(src["messages_json"] or "[]")[: PROPOSAL_MESSAGE_INDEX + 1]
  fin = json.loads(src["financials_json"] or "{}")
  for f in _STRIP_FIELDS:
    fin.pop(f, None)
  ops = json.loads(src["operating_model_json"] or "{}")
  for lob in ops.get("lob_models") or []:
    for product in lob.get("products") or []:
      for k in ("cogs_percent_of_line_revenue", "cogs_cost_structure_group",
                "cogs_cost_structure_group_basis",
                "cogs_cost_structure_group_members"):
        product.pop(k, None)

  overrides = {
    "draft_id": clone_id,
    "client_id": client_id,
    "active_focus": "financials",
    "financials_confirmed": 0,
    "financials_finalize_proposed": 0,
    "status": "in_progress",
    "completed_at": None,
    "submitted_at": None,
    "intake_submission_id": None,
    "messages_json": json.dumps(messages, ensure_ascii=False),
    "financials_json": json.dumps(fin, ensure_ascii=False),
    "operating_model_json": json.dumps(ops, ensure_ascii=False),
    "planning_run_id": None,
    "planning_run_status": None,
    "planning_stage": None,
    "planning_status": None,
  }
  columns = [c for c in src.keys() if c != "id"]
  values = [overrides.get(c, src[c]) if c in overrides else src[c] for c in columns]
  cur = conn.cursor()
  cur.execute(
    f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
    f"VALUES ({', '.join(['%s'] * len(columns))})",
    tuple(values),
  )
  conn.commit()
  cur.close()
  return clone_id, client_id


def post_turn(clone_id, client_id, message):
  resp = requests.post(
    f"{BASE_URL}/api/intake-consult",
    json={"draft_id": clone_id, "client_id": client_id, "message": message},
    timeout=300,
  )
  body = resp.json() if resp.status_code == 200 else {}
  return resp.status_code, str(body.get("assistant_message") or "")


def cleanup(conn, clone_id):
  try:
    cur = conn.cursor()
    cur.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s", (clone_id,))
    conn.commit()
    cur.close()
  except Exception:
    pass


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()

  # ---- S1: four rates, one message, IN-STAGE -----------------------------
  print("S1 - all four rates in ONE message at the cogs stage")
  c1, k1 = make_rewound_clone(conn, "cw32s1")
  try:
    before = ops_rows(conn, c1)
    check("clone rewound to the pre-correction state",
          len(before) == 4 and all(v["pct"] is None for v in before.values()),
          f"lines={list(before)}")
    status, reply = post_turn(c1, k1, MSG_S1)
    print(f"  < [{status}] {reply[:350]}")
    after = ops_rows(conn, c1)
    print(f"  ops now: { {k: v['pct'] for k, v in after.items()} }")
    fin = _fresh_read(conn, c1, "financials_json")
    check("S1 live turn 200", status == 200, str(status))
    check("all four rows carry the CLIENT's numbers",
          {k: v["pct"] for k, v in after.items()} == {
            "Plant sale": 0.46, "Hardgoods sale": 0.73,
            "Install job": 0.17, "Design project": 0.03},
          "46/73/17/3 through the live in-stage router")
    check("the cogs stage COMPLETED on the derived blend",
          fin.get("current_cogs") is not None
          and fin.get("cogs_percent_of_revenue") is not None,
          f"current_cogs={fin.get('current_cogs')} "
          f"pct={fin.get('cogs_percent_of_revenue')}")
    check("the reply is a receipt, not the Alderfen refusal",
          "wasn't able to apply" not in reply and "46" in reply,
          "speaks the write")
    check("the flow moved ON (a next question rides the same reply)",
          "?" in reply, "the stage did not re-ask the blend")
  finally:
    cleanup(conn, c1)

  # ---- S2: the collapse sentence, IN-STAGE -------------------------------
  print("\nS2 - the collapse sentence at the cogs stage")
  c2, k2 = make_rewound_clone(conn, "cw32s2")
  try:
    status2, reply2 = post_turn(c2, k2, MSG_S2)
    print(f"  < [{status2}] {reply2[:300]}")
    after2 = ops_rows(conn, c2)
    print(f"  ops now: {json.dumps(after2, ensure_ascii=False)[:400]}")
    grp_plant = after2.get("Plant sale", {})
    grp_hard = after2.get("Hardgoods sale", {})
    check("S2 live turn 200", status2 == 200, str(status2))
    check("a /shared/ group is STORED on exactly the two named rows",
          bool(grp_plant.get("group"))
          and grp_plant.get("group") == grp_hard.get("group")
          and not after2.get("Install job", {}).get("group")
          and not after2.get("Design project", {}).get("group"),
          str(grp_plant.get("group")))
    check("the group's basis is DECLARED",
          grp_plant.get("basis") == "declared", str(grp_plant.get("basis")))
  finally:
    cleanup(conn, c2)

  # ---- S3: one line only - the [77] retry shape --------------------------
  print("\nS3 - a single line's rate; the recovery keeps the per-line shape")
  c3, k3 = make_rewound_clone(conn, "cw32s3")
  try:
    status3, reply3 = post_turn(c3, k3, MSG_S3)
    print(f"  < [{status3}] {reply3[:350]}")
    after3 = ops_rows(conn, c3)
    check("S3 live turn 200", status3 == 200, str(status3))
    check("the named row is written",
          after3.get("Hardgoods sale", {}).get("pct") == 0.73,
          f"hardgoods={after3.get('Hardgoods sale', {}).get('pct')}")
    check("the other rows are untouched",
          all(after3.get(n, {}).get("pct") is None
              for n in ("Plant sale", "Install job", "Design project")),
          "plant/install/design still null")
    check("the recovery question keeps the per-line shape",
          "each line" in reply3.lower()
          or ("percent" in reply3.lower()
              and any(n in reply3 for n in ("Plant sale", "Install job", "Design project"))),
          "names the missing lines / per-line wording, never the singular blend ask")
    check("no false receipt for unstated lines",
          "Plant sale at" not in reply3 and "Design project at" not in reply3,
          "only the written line is receipted")
  finally:
    cleanup(conn, c3)
    try:
      conn.close()
    except Exception:
      pass

  print("\n" + "=" * 72)
  if FAILURES:
    print(f"RED - {len(FAILURES)} check(s) failed: {FAILURES}")
    return 1
  print("GREEN - the in-stage surface receives, writes, completes and "
        "recovers per-line.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
