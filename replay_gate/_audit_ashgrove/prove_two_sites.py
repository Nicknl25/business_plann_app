"""Ashgrove Bindery bf731ee4 - the two unnamed write sites, named and proven.

mini, 2026-09-22. AUDIT ONLY: this script writes nothing to the app. It reads
the STORE (never a log) and replays the real doors offline.

Run:  .venv\Scripts\python.exe replay_gate\_audit_ashgrove\prove_two_sites.py

THE CODE THAT WAS LIVE. The store says so: every reconcile extract of this run
carries call_site 'intake_consult.py:22727 post_intake_consult_handler', and
22727 is that call's line in 592d2583 (09-18 18:51) - not 4f52588d (19:00),
which has it at 22750. The backend was started before 19:00 and never
restarted, so 592d2583 is what served turns 5..19. The two commits differ only
by the 3c provenance block; the doors below are byte-identical across them.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.join(ROOT, "python", "api_handlers"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(ROOT, ".env"))

DRAFT = "bf731ee486254923986eb049688aed29"
LIVE_COMMIT = "592d2583"


def _module_at(commit):
  """Import python/api_handlers/intake_consult.py AS IT WAS at `commit`."""
  blob = subprocess.check_output(
    ["git", "show", f"{commit}:python/api_handlers/intake_consult.py"], cwd=ROOT)
  d = tempfile.mkdtemp(prefix="ashgrove_")
  path = os.path.join(d, f"ic_{commit}.py")
  with open(path, "wb") as fh:
    fh.write(blob)
  sys.path.insert(0, d)
  return __import__(f"ic_{commit}")


def _store():
  from client_intake_and_finmo.intake_submission import get_mysql_connection
  conn = get_mysql_connection()
  cur = conn.cursor()

  def ops_at(turn):
    cur.execute(
      "select result_json from intake_turn_reader_extracts where draft_id=%s "
      "and reader='driver_correction_reconcile' and turn=%s", (DRAFT, turn))
    return json.loads(cur.fetchone()[0])[0]

  cur.execute("select messages_json from intake_consult_drafts where draft_id=%s", (DRAFT,))
  msgs = json.loads(cur.fetchone()[0])
  ops_at._conn = conn          # the cursor dies with the connection if nothing holds it
  return ops_at, msgs


def show(tag, ops):
  print(tag)
  for i, p in enumerate((ops.get("lob_models") or [{}])[0].get("products") or []):
    print("   row%d %-28s per=%s periods=%s week=%s annual_completed=%s price=%s" % (
      i + 1, p.get("product_name"), p.get("units_per_period_capacity"),
      p.get("operating_periods_per_year"), p.get("units_per_week_capacity"),
      p.get("annual_completed_units"), p.get("unit_price")))


def snapshot(rows):
  """A consultant turn's lob_models, shaped by the STRICT schema in
  intake_consultant.py (every product key required - and there is no
  annual_completed_units key in it at all)."""
  return {"lob_models": [{"lob_name": "Primary line of business", "products": [
    {"product_name": r["n"], "unit_name": "book", "unit_description": None,
     "unit_cadence": "contract", "units_per_week_capacity": r.get("wk"),
     "units_per_period_capacity": r.get("per"),
     "operating_periods_per_year": r.get("ppy"), "utilization_rate": None,
     "unit_price": r.get("price"), "cogs_percent_of_line_revenue": None,
     "origin": None} for r in rows]}]}


def main():
  M = _module_at(LIVE_COMMIT)
  ops_at, msgs = _store()
  copy = lambda o: json.loads(json.dumps(o))

  print("### SITE 1 - who wrote operating_periods_per_year=110")
  print("    the ops consultant's own snapshot (1,100 / 10), landing wholesale at")
  print("    _apply_model_ops_patch, intake_consult.py:1345 (592d2583)")
  o = copy(ops_at(11))
  show("  STORE, at the turn-11 reconcile:", o)
  o = M._apply_model_ops_patch(o, snapshot([
    {"n": "Book binding & repair job", "per": 10, "ppy": 110},
    {"n": "Short-run print job"}]), user_message="About eleven hundred.", draft_id=DRAFT)
  M._derive_ops_cells(o)
  show("  after the snapshot lands:", o)
  show("  STORE, at the turn-13 reconcile (+1,100 from that turn's patch door):", ops_at(13))

  print()
  print("### SITE 2 - who dropped annual_completed_units=1100")
  print("    the SAME assignment: _carry_forward_per_line_drivers restores the keys in")
  print("    _CARRIED_PER_LINE_KEYS (intake_consult.py:15628) and that tuple has never")
  print("    held annual_completed_units, so the snapshot erases it.")
  o2 = copy(ops_at(13))
  show("  STORE, at the turn-13 reconcile:", o2)
  o2 = M._apply_model_ops_patch(o2, snapshot([
    {"n": "Book binding & repair job", "per": 10, "ppy": 110, "wk": 21.1538},
    {"n": "Short-run print job"}]), user_message="Neither...", draft_id=DRAFT)
  M._derive_ops_cells(o2)
  show("  after the snapshot lands:", o2)
  show("  STORE, at the turn-15 reconcile (+$110 from that turn's patch door):", ops_at(15))
  print("  carried keys:", M._CARRIED_PER_LINE_KEYS)
  print("  annual_completed_units carried?",
        "annual_completed_units" in M._CARRIED_PER_LINE_KEYS)

  print()
  print("### AND IT IS STILL TRUE ON TODAY'S TREE")
  from api_handlers import intake_consult as H
  o3 = copy(ops_at(11))
  o3 = H._apply_scoped_patch(
    {"ops.product_overrides": {"Book binding & repair job": {"annual_completed_units": 1100},
                               "Short-run print job": {"annual_completed_units": 1100}}},
    business_facts={}, ops_json=o3, market_json={}, people_json={}, financials_json={},
    fulfillment_json={}, user_message="Neither. That's how many I actually finish in a year.",
    recent_assistant=msgs[12]["content"], consult_stage="ops")[1]
  show("  1) her 1,100 lands (the keeper shipped in fd1107f4):", o3)
  o3 = H._apply_model_ops_patch(o3, snapshot([
    {"n": "Book binding & repair job", "per": 10, "ppy": 110},
    {"n": "Short-run print job"}]), user_message="Neither...", draft_id=DRAFT)
  H._derive_ops_cells(o3)
  show("  2) the same turn's consultant snapshot:", o3)
  still = any(p.get("annual_completed_units")
              for lm in o3.get("lob_models") or [] for p in lm.get("products") or [])
  print("  her 1,100 still on a row after the snapshot?", still)
  print()
  print("  So the contradiction hold added in 1ba47652 (intake_consult.py:892+) reads")
  print("  annual_completed_units off the row and, from the next turn on, finds nothing")
  print("  there to contradict. THE KEEPER IS NOT KEPT.")
  return 0 if not still else 0


if __name__ == "__main__":
  sys.exit(main())
