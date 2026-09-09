"""PAYROLL DIRECTIVE, Turn B (2026-09-09) - the stated-total door never
confirms a total that did not land.

Base (6af14a7): "people.total_team_payroll 300,000" on the Sunny canary
482b870f receipted "Recorded: total team payroll $300,000 a year"
(naturalized live to "Got it, your total team payroll is $300,000 a
year") while THE RECALC's fold landed 282,042.50 and HELD 17,957.50 in
_payroll_fold_hold - a key with one writer and no reader in the intake
handler. Deal breaker: the client reads $300,000 as recorded; the plan
carries $282,042.50.

  P1  stated total ABOVE the named+role floor, no rest pool -> the hold
      receipt (what landed, what did not, the HOW question); never
      "Recorded: total team payroll"; the spoken marker is stamped fresh
  P2  stated total that folds fully (a rest pool absorbs it) -> the
      Recorded ack exactly as before; no spoken marker
  P3  echo of the stored rollup -> silent (the door's own no-op rule)
  P4  the people DOOR end-to-end on the Sunny roster -> the hold
      receipt leads the ack; the real fold then holds the same remainder
  P5  the reader lifecycle: spoken this turn -> nothing more; the next
      unanswered edit turn -> the HOW question once; a third -> silent;
      a people write clears; a plain dismissal clears with the
      runs-on line
  P6  stated total BELOW the floor (a cut only named pay could absorb)
      -> the hold receipt says it will not assume the cut
  P7  a hold nobody ever spoke (stored before the reader existed) ->
      spoken on the very next reader pass
  P8  the roster moves AFTER the fold inside the same turn (the main
      flow's OEWS pass; live smoke aa3ee853) -> the reply-assembly
      re-compose speaks the FINAL landed figure and the true remainder,
      and resyncs the stored hold to that same fold
  P9  the roster move absorbs the whole remainder -> the Recorded ack,
      the stale hold cleared

Run from repo root with .venv python. PIN_PYTHON_ROOT=<path to a
baseline checkout's python dir> runs the same probes against that build
(red on 6af14a7: P1, P2, P4, P5, P6, P7, P8, P9).
"""
from __future__ import annotations

import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_ROOT = os.environ.get("PIN_PYTHON_ROOT") or os.path.join(ROOT, "python")
for p in (ROOT, PY_ROOT, os.path.join(PY_ROOT, "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)

from api_handlers import intake_consult as ic  # noqa: E402

BASELINE = os.path.join(ROOT, "Test Files", "intake_bypass_baselines",
                        "sunny_glaze_donuts.json")

_results = []


def check(label, ok):
  _results.append((label, bool(ok)))
  print(("PASS " if ok else "FAIL ") + label)


def guarded(label, fn):
  try:
    check(label, fn())
  except Exception as exc:  # noqa: BLE001
    _results.append((label, False))
    print(f"FAIL {label} - {type(exc).__name__}: {exc}")


def _load():
  b = json.load(open(BASELINE, encoding="utf-8"))
  s = b.get("structured") or {}
  fin = copy.deepcopy(s.get("financials_json") or {})
  ppl = copy.deepcopy(s.get("people_json") or {})
  ops = copy.deepcopy(s.get("operating_model_json") or {})
  for k in ("_payroll_fold_hold", "_payroll_fold_hold_spoken",
            "payroll_stated_total_target"):
    fin.pop(k, None)
  fin["payroll_adjustment"] = 0.0
  ppl["rest_of_team_payroll_year1"] = None
  return fin, ppl, ops


def _recalc(fin, ppl, ops):
  fin2, _ = ic._sync_financials_consult_persistence_state(
    financials_json=copy.deepcopy(fin), financials_year1_json={},
    marketing_model_json={}, people_json=ppl, ops_json=ops,
  )
  return fin2


def _canon(fin, ppl, ops):
  return float(_recalc(fin, copy.deepcopy(ppl), copy.deepcopy(ops))["current_payroll"])


RECORDED = "Recorded: total team payroll"


def p1():
  fin, ppl, ops = _load()
  canon = _canon(fin, ppl, ops)
  ack, fin2 = ic._stated_total_receipt(
    canon + 20000.0, financials_json=fin, people_json=ppl, ops_json=ops)
  print("   P1 ack:", ack)
  sp = fin2.get("_payroll_fold_hold_spoken") or {}
  return (
    ack.startswith("I've recorded " + ic._fmt_money_exact(canon))
    and "remaining $20,000" in ack and "?" in ack
    and RECORDED not in ack
    and abs(float(sp.get("unapplied") or 0) - 20000.0) < 1.0
    and sp.get("fresh") is True and sp.get("turns") == 1
  )


def p2():
  fin, ppl, ops = _load()
  ppl["rest_of_team_payroll_year1"] = 50000.0
  canon = _canon(fin, ppl, ops)
  ack, fin2 = ic._stated_total_receipt(
    canon + 20000.0, financials_json=fin, people_json=ppl, ops_json=ops)
  print("   P2 ack:", ack)
  return (
    ack == f"{RECORDED} {ic._format_currency(canon + 20000.0)} a year."
    and "_payroll_fold_hold_spoken" not in fin2
  )


def p3():
  fin, ppl, ops = _load()
  canon = _canon(fin, ppl, ops)
  fin["current_payroll"] = canon
  _p, fin2, _sh, ack = ic._apply_stage_people_door_keys(
    patch={"people.total_team_payroll": canon},
    stage_shared_context={"people_capability": ppl, "operating_model": ops},
    next_financials=fin, conn=None, intake_context={"draft_id": ""},
  )
  print("   P3 ack:", repr(ack))
  return ack == ""


def p4():
  fin, ppl, ops = _load()
  canon = _canon(fin, ppl, ops)
  fin["current_payroll"] = canon
  _p, fin2, sh, ack = ic._apply_stage_people_door_keys(
    patch={"people.total_team_payroll": canon + 20000.0},
    stage_shared_context={"people_capability": ppl, "operating_model": ops},
    next_financials=fin, conn=None, intake_context={"draft_id": ""},
  )
  print("   P4 door ack:", ack)
  # the real fold, as the turn runs it moments later
  ppl2 = copy.deepcopy(sh.get("people_capability") or {})
  fin3 = _recalc(fin2, ppl2, copy.deepcopy(ops))
  hold = fin3.get("_payroll_fold_hold") or {}
  print("   P4 real fold: current_payroll", fin3.get("current_payroll"), "hold", hold)
  return (
    ack.startswith("I've recorded ") and RECORDED not in ack
    and abs(float(hold.get("unapplied") or 0) - 20000.0) < 1.0
    and abs(float(fin3.get("current_payroll") or 0) - canon) < 1.0
    and (fin3.get("_payroll_fold_hold_spoken") or {}).get("fresh") is True
  )


def p5():
  fin, ppl, ops = _load()
  canon = _canon(fin, ppl, ops)
  fin["current_payroll"] = canon
  _p, fin2, sh, _ack = ic._apply_stage_people_door_keys(
    patch={"people.total_team_payroll": canon + 20000.0},
    stage_shared_context={"people_capability": ppl, "operating_model": ops},
    next_financials=fin, conn=None, intake_context={"draft_id": ""},
  )
  fin3 = _recalc(fin2, copy.deepcopy(sh.get("people_capability") or {}), copy.deepcopy(ops))
  # same turn, after the pass: spoken by the receipt -> nothing more
  fin4, t1 = ic._payroll_hold_followup(
    fin3, user_message="Actually our total team payroll is higher.",
    patch={"people.total_team_payroll": canon + 20000.0})
  ok1 = t1 == "" and "_payroll_fold_hold" in fin4 \
    and (fin4.get("_payroll_fold_hold_spoken") or {}).get("fresh") is False
  # next edit turn, unanswered -> the HOW question, once
  fin5, t2 = ic._payroll_hold_followup(
    fin4, user_message="Also our rent is 3,600 a month.",
    patch={"financials.monthly_rent_expense": 3600})
  print("   P5 re-ask:", t2)
  ok2 = t2.startswith("On the team number:") and "?" in t2 \
    and (fin5.get("_payroll_fold_hold_spoken") or {}).get("turns") == 2 \
    and "_payroll_fold_hold" in fin5
  # a third unanswered edit turn -> silent (the gate's reader carries it)
  fin6, t3 = ic._payroll_hold_followup(
    fin5, user_message="And marketing is 12,000.",
    patch={"financials.marketing_total_year1": 12000})
  ok3 = t3 == "" and "_payroll_fold_hold" in fin6
  # a people write answers HOW -> cleared silently
  fin7, t4 = ic._payroll_hold_followup(
    fin5, user_message="Maria is actually 56,550.",
    patch={"people.people[1].annual_wage": 56550})
  ok4 = t4 == "" and "_payroll_fold_hold" not in fin7 \
    and "_payroll_fold_hold_spoken" not in fin7
  # a plain dismissal -> cleared, with the runs-on line
  fin8, t5 = ic._payroll_hold_followup(
    fin5, user_message="Never mind, run without it.",
    patch={"financials.monthly_rent_expense": 3600})
  print("   P5 dismissal:", t5)
  ok5 = t5.startswith("Okay - the plan runs on " + ic._fmt_money_exact(canon)) \
    and "_payroll_fold_hold" not in fin8
  print("   P5 legs:", ok1, ok2, ok3, ok4, ok5)
  return ok1 and ok2 and ok3 and ok4 and ok5


def p6():
  fin, ppl, ops = _load()
  canon = _canon(fin, ppl, ops)
  ack, fin2 = ic._stated_total_receipt(
    canon - 30000.0, financials_json=fin, people_json=ppl, ops_json=ops)
  print("   P6 ack:", ack)
  return (
    ack.startswith("I've recorded " + ic._fmt_money_exact(canon))
    and "won't assume" in ack and RECORDED not in ack
    and abs(float((fin2.get("_payroll_fold_hold_spoken") or {}).get("unapplied") or 0) + 30000.0) < 1.0
  )


def p7():
  fin, ppl, ops = _load()
  fin["current_payroll"] = 282042.5
  fin["_payroll_fold_hold"] = {"unapplied": 17957.5}
  fin2, t = ic._payroll_hold_followup(
    fin, user_message="Our rent is 3,600 a month.",
    patch={"financials.monthly_rent_expense": 3600})
  print("   P7 legacy hold spoken:", t)
  return (
    t.startswith("I've recorded $282,042.50") and "$17,957.50" in t
    and (fin2.get("_payroll_fold_hold_spoken") or {}).get("turns") == 1
  )


def p8():
  fin, ppl, ops = _load()
  canon = _canon(fin, ppl, ops)
  stated = canon + 60000.0
  fin["current_payroll"] = canon
  ack0, fin2 = ic._stated_total_receipt(
    stated, financials_json=fin, people_json=ppl, ops_json=ops)
  # the real fold on the OLD roster (hold = 60,000), as the turn runs it
  ppl_a = copy.deepcopy(ppl)
  fin2["payroll_stated_total_target"] = stated
  fin3 = _recalc(fin2, ppl_a, copy.deepcopy(ops))
  fin3, _ = ic._payroll_hold_followup(
    fin3, user_message="total is higher", patch={"people.total_team_payroll": stated})
  stale = float((fin3.get("_payroll_fold_hold") or {}).get("unapplied") or 0)
  # then the OEWS pass lifts the named wages by 20,000 in total
  ppl_b = copy.deepcopy(ppl_a)
  ppl_b["people"][0]["annual_wage"] = float(ppl_b["people"][0]["annual_wage"]) + 20000.0
  ack, fin4, is_hold = ic._recompose_stated_total_receipt(
    stated, financials_json=fin3, people_json=ppl_b, ops_json=ops)
  new_landed = _canon(fin4, ppl_b, ops)
  print("   P8 stale hold", stale, "-> resynced", fin4.get("_payroll_fold_hold"),
        "| landed", new_landed)
  print("   P8 ack:", ack)
  hold = float((fin4.get("_payroll_fold_hold") or {}).get("unapplied") or 0)
  return (
    is_hold and abs(stale - 60000.0) < 1.0
    and abs(new_landed - (canon + 20000.0)) < 1.0
    and abs(hold - 40000.0) < 1.0
    and ack.startswith("I've recorded " + ic._fmt_money_exact(new_landed))
    and ic._fmt_money_exact(40000.0) in ack and RECORDED not in ack
    and (fin4.get("_payroll_fold_hold_spoken") or {}).get("fresh") is False
  )


def p9():
  fin, ppl, ops = _load()
  canon = _canon(fin, ppl, ops)
  stated = canon + 20000.0
  fin["current_payroll"] = canon
  fin["_payroll_fold_hold"] = {"unapplied": 20000.0}
  fin["_payroll_fold_hold_spoken"] = {"unapplied": 20000.0, "turns": 1, "fresh": False}
  ppl_b = copy.deepcopy(ppl)
  ppl_b["people"][0]["annual_wage"] = float(ppl_b["people"][0]["annual_wage"]) + 20000.0
  ack, fin4, is_hold = ic._recompose_stated_total_receipt(
    stated, financials_json=fin, people_json=ppl_b, ops_json=ops)
  print("   P9 ack:", ack, "| hold after:", fin4.get("_payroll_fold_hold"))
  return (
    not is_hold and ack == f"{RECORDED} {ic._format_currency(stated)} a year."
    and "_payroll_fold_hold" not in fin4 and "_payroll_fold_hold_spoken" not in fin4
  )


if __name__ == "__main__":
  print("build:", PY_ROOT)
  for label, fn in (
    ("P1 stated above the floor, no rest pool -> hold receipt, never Recorded", p1),
    ("P2 stated total that folds fully -> the Recorded ack as before", p2),
    ("P3 echo -> silent", p3),
    ("P4 the people door end-to-end -> hold receipt leads, real fold holds the same", p4),
    ("P5 reader lifecycle: fresh silent, re-ask once, then silent; people write and dismissal clear", p5),
    ("P6 stated below the floor -> hold receipt refuses the silent cut", p6),
    ("P7 a never-spoken hold is spoken on the next reader pass", p7),
    ("P8 roster moves after the fold -> receipt re-derived from the final roster, hold resynced", p8),
    ("P9 roster move absorbs the remainder -> Recorded ack, stale hold cleared", p9),
  ):
    guarded(label, fn)
  n_ok = sum(1 for _l, ok in _results if ok)
  print(f"\n{n_ok}/{len(_results)} PASS")
  sys.exit(0 if n_ok == len(_results) else 1)
