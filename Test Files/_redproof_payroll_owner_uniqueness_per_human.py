"""PAYROLL DIRECTIVE, Turn A (2026-09-09) - owner-row uniqueness is PER
HUMAN, never per title-regex.

Base (9c06f7a) deletes any second owner-titled named person at THE
RECALC's uniqueness pass: Marchetti's Rasheed Fennimore ("Design
Director and Co-Owner", $142,000) and Northwind's Rajan Mehta
("Co-Founder and CTO", $202,210) vanished from the roster and from the
delivered payroll while the app then asked the surviving owner about
"two figures for your pay" (the conflict hold). Deal breaker: a named
partner deleted from the plan and their wage dropped from payroll.

  P1  the ACTUAL Marchetti turn-79 finalize roster (evidence file) ->
      both partners survive, current_payroll 820,000 (297,000 named +
      523,000 rest), NO _owner_wage_conflict_hold
  P2  Northwind's two co-founders (650,000 + 202,210) -> both survive,
      no hold
  P3  the SAME human stated twice under two owner titles -> one row
      (the same-name group still dedupes)
  P4  Sumac's UNNAMED owner row against ONE named owner -> merges into
      the named row at the client's wage (the CW-026 #1 shape, intact)
  P5  an unnamed owner row against TWO named owners -> merges into the
      more complete named row, never deletes a named person
  P6  the gate question never fires for two different people: the
      hold is absent even though both wages are client_override and
      differ by more than 5%

Run from repo root with .venv python. Red on 9c06f7a (P1, P2, P5, P6),
green after the per-human pass.
"""
from __future__ import annotations

import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "python"),
          os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)

from api_handlers import intake_consult as ic  # noqa: E402

EVIDENCE = os.path.join(ROOT, "replay_gate", "_payroll_directive_audit",
                        "marchetti_turn79_finalize_people.json")

_results = []


def check(label, ok):
  _results.append((label, bool(ok)))
  print(("PASS " if ok else "FAIL ") + label)


def guarded(label, fn):
  try:
    check(label, fn())
  except Exception as exc:  # noqa: BLE001
    _results.append((label, False))
    print(f"FAIL {label}: {type(exc).__name__}: {exc}")


def _sync(people):
  fin, _ = ic._sync_financials_consult_persistence_state(
      financials_json={"current_revenue": 1650000.0,
                       "_financials_revenue_intro_done": True},
      financials_year1_json={},
      marketing_model_json={},
      people_json=people,
      ops_json={},
  )
  return fin, people


def _names(people):
  return [str(p.get("full_name") or "") for p in (people.get("people") or [])]


def _owners(people):
  return [p for p in (people.get("people") or [])
          if ic._OWNER_TITLE_RE.search(str(p.get("role_title") or ""))]


def p1():
  with open(EVIDENCE, encoding="utf-8") as fh:
    roster = json.load(fh)
  people = {"people": copy.deepcopy(roster["people"]),
            "rest_of_team_payroll_year1": 523000.0}
  fin, people = _sync(people)
  names = _names(people)
  rollup = float(fin.get("current_payroll") or 0.0)
  print(f"     P1 roster after: {names} current_payroll={rollup:,.2f} "
        f"hold={fin.get('_owner_wage_conflict_hold')!r}")
  return (names == ["Ottoline Marchetti", "Rasheed Fennimore"]
          and abs(rollup - 820000.0) < 1.5
          and fin.get("_owner_wage_conflict_hold") is None)


guarded("P1 Marchetti turn-79 roster: both partners survive, 820,000, no hold", p1)


def p2():
  people = {"people": [
      {"full_name": "Elena Vasquez", "role_title": "Co-Founder and CEO",
       "annual_wage": 650000.0, "wage_source": "client_override",
       "relevant_background": "16 years enterprise software"},
      {"full_name": "Rajan Mehta", "role_title": "Co-Founder and CTO",
       "annual_wage": 202210.0, "wage_source": "oews_pct75",
       "relevant_background": "15 years distributed systems"},
  ], "rest_of_team_payroll_year1": 0.0}
  fin, people = _sync(people)
  names = _names(people)
  rollup = float(fin.get("current_payroll") or 0.0)
  print(f"     P2 roster after: {names} current_payroll={rollup:,.2f}")
  return (names == ["Elena Vasquez", "Rajan Mehta"]
          and abs(rollup - 852210.0) < 1.5
          and fin.get("_owner_wage_conflict_hold") is None)


guarded("P2 Northwind two co-founders: both survive, 852,210, no hold", p2)


def p3():
  people = {"people": [
      {"full_name": "Delia Rennick", "role_title": "Owner and Crew Lead",
       "annual_wage": 63960.0, "wage_source": "oews_pct75",
       "relevant_background": "ten years"},
      {"full_name": "delia  rennick", "role_title": "Owner",
       "annual_wage": 34000.0, "wage_source": "client_override"},
  ], "rest_of_team_payroll_year1": 0.0}
  fin, people = _sync(people)
  rows = people.get("people") or []
  return (len(rows) == 1 and str(rows[0].get("full_name")) == "Delia Rennick"
          and abs(float(rows[0].get("annual_wage") or 0) - 34000.0) < 0.5)


guarded("P3 same human under two owner titles (name normalized) -> one row at the override", p3)


def p4():
  people = {"people": [
      {"full_name": "Delia Rennick", "role_title": "Owner and Crew Lead",
       "annual_wage": 63960.0, "wage_source": "oews_pct75",
       "relevant_background": "ten years"},
      {"full_name": "", "role_title": "Owner",
       "annual_wage": 34000.0, "wage_source": "client_override"},
  ], "rest_of_team_payroll_year1": 0.0}
  fin, people = _sync(people)
  rows = people.get("people") or []
  return (len(rows) == 1 and str(rows[0].get("full_name")) == "Delia Rennick"
          and abs(float(rows[0].get("annual_wage") or 0) - 34000.0) < 0.5
          and str(rows[0].get("wage_source")) == "client_override")


guarded("P4 Sumac unnamed owner row vs one named owner -> merges (CW-026 #1 intact)", p4)


def p5():
  people = {"people": [
      {"full_name": "Ottoline Marchetti",
       "role_title": "Principal Architect and Co-Owner",
       "annual_wage": 155000.0, "wage_source": "client_override",
       "relevant_background": "24 years", "primary_responsibilities": "leads"},
      {"full_name": "Rasheed Fennimore",
       "role_title": "Design Director and Co-Owner",
       "annual_wage": 142000.0, "wage_source": "client_override",
       "relevant_background": "19 years"},
      {"full_name": "", "role_title": "Owner",
       "annual_wage": 155000.0, "wage_source": "client_override"},
  ], "rest_of_team_payroll_year1": 0.0}
  fin, people = _sync(people)
  names = _names(people)
  rollup = float(fin.get("current_payroll") or 0.0)
  print(f"     P5 roster after: {names} current_payroll={rollup:,.2f} "
        f"hold={fin.get('_owner_wage_conflict_hold')!r}")
  return (names == ["Ottoline Marchetti", "Rasheed Fennimore"]
          and abs(rollup - 297000.0) < 1.5
          and fin.get("_owner_wage_conflict_hold") is None)


guarded("P5 unnamed owner row vs TWO named owners -> merges into one, neither named person deleted", p5)


def p6():
  people = {"people": [
      {"full_name": "Ava Stone", "role_title": "Managing Partner",
       "annual_wage": 120000.0, "wage_source": "client_override"},
      {"full_name": "Ben Ruiz", "role_title": "Partner",
       "annual_wage": 80000.0, "wage_source": "client_override"},
  ], "rest_of_team_payroll_year1": 0.0}
  fin, people = _sync(people)
  return (_names(people) == ["Ava Stone", "Ben Ruiz"]
          and len(_owners(people)) == 2
          and fin.get("_owner_wage_conflict_hold") is None)


guarded("P6 two different partners with different override wages -> no conflict hold", p6)

_n_ok = sum(1 for _l, ok in _results if ok)
print(f"\n{_n_ok}/{len(_results)} passed")
sys.exit(0 if _n_ok == len(_results) else 1)
