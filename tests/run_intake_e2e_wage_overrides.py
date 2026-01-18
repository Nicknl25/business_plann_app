import argparse
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests


MAX_TURNS = 120


def _post(base_url: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base_url}{path}"
    for attempt in range(3):
        resp = requests.post(url, json=payload, timeout=240)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        if resp.status_code < 400:
            return data
        detail = json.dumps(data) if not isinstance(data, str) else data
        if resp.status_code >= 500 and "OpenAI API error 500" in detail and attempt < 2:
            time.sleep(2 + attempt)
            continue
        raise RuntimeError(f"POST {url} -> {resp.status_code}: {data}")
    raise RuntimeError(f"POST {url} failed after retries.")


def _get(base_url: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base_url}{path}"
    resp = requests.get(url, params=params, timeout=240)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"GET {url} -> {resp.status_code}: {data}")
    return data


def _parse_json(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return None


def _first_person_and_role(people_json: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    people_list = people_json.get("people") if isinstance(people_json, dict) else None
    roles_list = people_json.get("inferred_roles") if isinstance(people_json, dict) else None
    person = people_list[0] if isinstance(people_list, list) and people_list else None
    role = roles_list[0] if isinstance(roles_list, list) and roles_list else None
    return person if isinstance(person, dict) else None, role if isinstance(role, dict) else None


def _next_answer(focus: str, state: Dict[str, Any]) -> str:
    queue = state.get("queues", {}).get(focus, [])
    if isinstance(queue, list) and queue:
        return str(queue.pop(0))
    return "yes"


def _looks_like_confirmation(message: str) -> bool:
    text = str(message or "").strip().lower()
    cues = (
        "does that sound",
        "does this sound",
        "does this look right",
        "does this capture",
        "is that accurate",
        "is that correct",
        "is that right",
        "is this correct",
        "is this accurate",
        "does this match",
        "does that match",
        "is this ok",
        "is this okay",
    )
    return any(cue in text for cue in cues)


def _override_message(
    person: Optional[Dict[str, Any]],
    role: Optional[Dict[str, Any]],
    override_people_wage: Optional[float],
    override_role_wage: Optional[float],
    state: Dict[str, Any],
) -> Optional[str]:
    parts: List[str] = []
    if person and override_people_wage is not None:
        full_name = str(person.get("full_name") or "").strip()
        role_title = str(person.get("role_title") or "").strip()
        if full_name:
            state["override_person_key"] = {"full_name": full_name, "role_title": role_title}
            if role_title:
                parts.append(f"Set {full_name} ({role_title}) wage to {override_people_wage}")
            else:
                parts.append(f"Set {full_name}'s wage to {override_people_wage}")
    if role and override_role_wage is not None:
        role_title = str(role.get("role_title") or "").strip()
        if role_title:
            state["override_role_key"] = {"role_title": role_title}
            parts.append(f"Set {role_title} wage to {override_role_wage}")
    return " and ".join(parts) if parts else None


def _find_person(people: List[Dict[str, Any]], key: Dict[str, str]) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    target_name = str(key.get("full_name") or "").strip().lower()
    target_role = str(key.get("role_title") or "").strip().lower()
    for person in people:
        if not isinstance(person, dict):
            continue
        full_name = str(person.get("full_name") or "").strip().lower()
        role_title = str(person.get("role_title") or "").strip().lower()
        if target_name and full_name != target_name:
            continue
        if target_role and target_role not in role_title:
            continue
        return person
    return None


def _find_role(roles: List[Dict[str, Any]], key: Dict[str, str]) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    target_role = str(key.get("role_title") or "").strip().lower()
    for role in roles:
        if not isinstance(role, dict):
            continue
        role_title = str(role.get("role_title") or "").strip().lower()
        if target_role and role_title == target_role:
            return role
    return None


def _check_invariants(
    draft: Dict[str, Any],
    state: Dict[str, Any],
    override_people_wage: Optional[float],
    override_role_wage: Optional[float],
) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    ops = _parse_json(draft.get("operating_model_json")) or {}
    people_json = _parse_json(draft.get("people_json")) or {}

    if not str(ops.get("business_naics_6") or "").strip():
        errors.append("ops.business_naics_6 is missing")

    people = people_json.get("people") if isinstance(people_json, dict) else []
    roles = people_json.get("inferred_roles") if isinstance(people_json, dict) else []
    if not isinstance(people, list) or not people:
        errors.append("people list missing")
    else:
        for person in people:
            if not isinstance(person, dict):
                continue
            if person.get("annual_wage") is None:
                errors.append("people annual_wage missing")
                break
            wage_source = str(person.get("wage_source") or "")
            if "oews" not in wage_source and "override" not in wage_source:
                errors.append("people wage_source not OEWS/override")
                break

    if not isinstance(roles, list) or not roles:
        errors.append("inferred_roles list missing")
    else:
        for role in roles:
            if not isinstance(role, dict):
                continue
            if role.get("annual_wage") is None:
                errors.append("role annual_wage missing")
                break
            wage_source = str(role.get("wage_source") or "")
            if "oews" not in wage_source and "override" not in wage_source:
                errors.append("role wage_source not OEWS/override")
                break

    person_key = state.get("override_person_key") or {}
    role_key = state.get("override_role_key") or {}
    if person_key and override_people_wage is not None:
        person = _find_person(people or [], person_key)
        if not person:
            errors.append("override person not found")
        else:
            if float(person.get("annual_wage") or 0) != float(override_people_wage):
                errors.append("override person wage not persisted")
    if role_key and override_role_wage is not None:
        role = _find_role(roles or [], role_key)
        if not role:
            errors.append("override role not found")
        else:
            if float(role.get("annual_wage") or 0) != float(override_role_wage):
                errors.append("override role wage not persisted")

    if state.get("duplicate_summary_detected"):
        errors.append("duplicate summary detected")

    if state.get("auto_advance_detected"):
        errors.append("auto-advance detected without confirmation")

    return (len(errors) == 0, errors)


def run_scenario(base_url: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    session = _post(base_url, "/api/intake-consult/session", {})
    draft_id = session.get("draft_id")
    client_id = session.get("client_id")
    if not draft_id:
        raise RuntimeError(f"Failed to create draft: {session}")

    state: Dict[str, Any] = {
        "override_sent": False,
        "override_person_key": None,
        "override_role_key": None,
        "duplicate_summary_detected": False,
        "auto_advance_detected": False,
        "last_summary_by_focus": {},
        "queues": {
            "ops": list(scenario.get("ops_answers", [])),
            "market": list(scenario.get("market_answers", [])),
            "people": list(scenario.get("people_answers", [])),
            "financials": list(scenario.get("financials_answers", [])),
            "consistency": list(scenario.get("consistency_answers", [])),
        },
    }

    seed_payload = {
        "draft_id": draft_id,
        "client_id": client_id,
        "business_name": scenario["business_name"],
        "business_start_date": scenario["business_start_date"],
        "address": scenario["address"],
        "address_street": scenario["address_street"],
        "address_city": scenario["address_city"],
        "address_state": scenario["address_state"],
        "address_zip": scenario["address_zip"],
        "address_country": scenario["address_country"],
        "message": "",
    }
    response = _post(base_url, "/api/intake-consult", seed_payload)

    transcript: List[Dict[str, str]] = []
    last_focus: Optional[str] = None
    last_reply_was_confirmation = False
    last_assistant_msg = ""
    last_reply = ""

    for _ in range(MAX_TURNS):
        assistant_msg = response.get("assistant_message") or ""
        active_focus = str(response.get("active_focus") or "").strip().lower()
        awaiting_confirmation = bool(response.get("awaiting_confirmation"))
        done = bool(response.get("done"))

        transcript.append({"role": "assistant", "content": assistant_msg})
        last_assistant_msg = assistant_msg

        if done:
            break

        reply: str
        if awaiting_confirmation:
            last_summary = state["last_summary_by_focus"].get(active_focus)
            if last_summary and last_summary.strip() == assistant_msg.strip():
                state["duplicate_summary_detected"] = True
            state["last_summary_by_focus"][active_focus] = assistant_msg
            if active_focus == "people" and not state["override_sent"]:
                draft = _get(base_url, "/api/intake-consult/draft", {"draft_id": draft_id})
                people_json = _parse_json(draft.get("people_json")) or {}
                person, role = _first_person_and_role(people_json)
                reply = _override_message(
                    person,
                    role,
                    scenario.get("override_people_wage"),
                    scenario.get("override_role_wage"),
                    state,
                ) or "yes"
                state["override_sent"] = True
            else:
                reply = "yes"
            last_reply_was_confirmation = True
        else:
            if _looks_like_confirmation(assistant_msg):
                reply = "yes"
            else:
                reply = _next_answer(active_focus, state)
            last_reply_was_confirmation = False

        transcript.append({"role": "user", "content": reply})
        last_reply = reply
        try:
            response = _post(
                base_url,
                "/api/intake-consult",
                {"draft_id": draft_id, "client_id": client_id, "message": reply},
            )
        except Exception as exc:
            raise RuntimeError(
                f"{exc} | focus={active_focus} | reply={last_reply!r} | assistant={last_assistant_msg!r}"
            ) from exc
        next_focus = str(response.get("active_focus") or "").strip().lower()
        action = str(response.get("action") or "").strip().lower()
        if last_focus and next_focus and next_focus != last_focus:
            if action not in ("confirm_proceed", "consistency_passed"):
                state["auto_advance_detected"] = True
        last_focus = next_focus

        if active_focus == "financials" and response.get("active_focus") == "consistency":
            last_focus = "consistency"

    draft = _get(base_url, "/api/intake-consult/draft", {"draft_id": draft_id})
    ok, errors = _check_invariants(
        draft,
        state,
        scenario.get("override_people_wage"),
        scenario.get("override_role_wage"),
    )

    out = {
        "name": scenario["name"],
        "draft_id": draft_id,
        "active_focus": draft.get("active_focus"),
        "ok": ok,
        "errors": errors,
        "override_person_key": state.get("override_person_key"),
        "override_role_key": state.get("override_role_key"),
        "operating_model_json": draft.get("operating_model_json"),
        "people_json": draft.get("people_json"),
    }

    with open(f"intake_e2e_{scenario['name']}.json", "w", encoding="utf-8") as handle:
        json.dump(transcript, handle, indent=2)

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run intake E2E wage override scenarios.")
    parser.add_argument("--base-url", default=os.getenv("INTAKE_BASE_URL", "http://127.0.0.1:5050"))
    parser.add_argument(
        "--scenario",
        action="append",
        help="Scenario name to run (can be provided multiple times).",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    scenarios = [
        {
            "name": "home_health_override",
            "business_name": "Shonna's Home Health Agency",
            "business_start_date": "04/15/2026",
            "address": "5500 Care Blvd, Jacksonville, FL 32224, USA",
            "address_street": "5500 Care Blvd",
            "address_city": "Jacksonville",
            "address_state": "FL",
            "address_zip": "32224",
            "address_country": "USA",
            "ops_answers": [
                "We operate a home health agency providing in-home care services.",
                "Mostly consumers.",
                "One billable hour of in-home care.",
                "One hour of in-home care delivered by a caregiver.",
                "45",
                "120",
                "Care delivered in the client home by caregivers.",
                "Local.",
                "LLC",
                "Reach 400 billable hours per week in year one.",
                "100000",
                "50000",
                "No",
                "50000",
                "Labor",
            ],
            "market_answers": ["all", "25-60", "40k-120k", "no preference", "skip", "sounds right"],
            "people_answers": [
                "Shonna H., CEO & Founder, 13 years in home health, MBA in Health Care Management, RN",
                "no",
                "approved",
                "keep them",
            ],
            "financials_answers": ["0", "0", "500", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"]
            + ["0"] * 8,
            "consistency_answers": ["yes"],
            "override_people_wage": 145000,
            "override_role_wage": 40000,
        },
        {
            "name": "bakery_override",
            "business_name": "Riverbend Bakery",
            "business_start_date": "05/20/2026",
            "address": "120 Market St, Jacksonville, FL 32202, USA",
            "address_street": "120 Market St",
            "address_city": "Jacksonville",
            "address_state": "FL",
            "address_zip": "32202",
            "address_country": "USA",
            "ops_answers": [
                "We run a walk-in retail bakery selling pastries and bread.",
                "Consumers only.",
                "One customer transaction.",
                "One in-store purchase of baked goods.",
                "28",
                "200",
                "On-site pickup at the bakery.",
                "Local.",
                "LLC",
                "Reach 250 transactions per week in six months.",
                "80000",
                "20000",
                "No",
                "60000",
                "Demand",
            ],
            "market_answers": ["mix", "18-80", "40k-120k", "no preference", "no additional detail", "yes"],
            "people_answers": [
                "Alex Rivera, Owner, 10 years in baking, culinary certificate",
                "no",
                "approved",
                "keep them",
            ],
            "financials_answers": ["0", "0", "500", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"]
            + ["0"] * 8,
            "consistency_answers": ["yes"],
            "override_people_wage": 90000,
            "override_role_wage": 42000,
        },
        {
            "name": "freight_override",
            "business_name": "Atlantic Freight Co.",
            "business_start_date": "06/01/2026",
            "address": "77771 Lumber Creek Blvd, Yulee, FL 32097, USA",
            "address_street": "77771 Lumber Creek Blvd",
            "address_city": "Yulee",
            "address_state": "FL",
            "address_zip": "32097",
            "address_country": "USA",
            "ops_answers": [
                "We run an Over-the-Road Trucking company hauling freight across the US.",
                "Businesses only.",
                "One paid load.",
                "One completed paid freight haul.",
                "2500",
                "5",
                "Owner-operator hauling freight from shipper to receiver.",
                "National.",
                "LLC",
                "Complete 5 paid loads per week within the first month.",
                "150000",
                "80000",
                "No",
                "70000",
                "Labor",
            ],
            "market_answers": ["all genders", "25-60", "50k-150k", "no preference", "no additional detail", "yes"],
            "people_answers": [
                "Nick Henry, Owner-Operator, 12 years in trucking, CDL and MBA",
                "no",
                "approved",
                "keep them",
            ],
            "financials_answers": ["0", "0", "500", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"]
            + ["0"] * 8,
            "consistency_answers": ["yes"],
            "override_people_wage": 120000,
            "override_role_wage": 55000,
        },
    ]

    selected: List[str] = []
    if args.scenario:
        for entry in args.scenario:
            for item in str(entry or "").split(","):
                item = item.strip()
                if item:
                    selected.append(item)
    if selected:
        scenarios = [s for s in scenarios if s["name"] in set(selected)]

    results = []
    failures = 0
    for scenario in scenarios:
        res = run_scenario(base_url, scenario)
        results.append(res)
        if not res["ok"]:
            failures += 1
        with open("intake_e2e_results.json", "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2)
        print(f"[done] {scenario['name']} ok={res['ok']} errors={res['errors']}")

    print(json.dumps(results, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
