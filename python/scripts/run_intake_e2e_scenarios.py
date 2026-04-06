
import argparse
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

OPS_CONFIRM = "Does this look right before we move on to Target Market?"
MARKET_CONFIRM = "Does this look right before we move on to Human Resources?"
PEOPLE_CONFIRM = "Does this look right before we move on to Financials?"
FIN_CONFIRM = "Does this look right before we move on to Submit intake?"
CONFIRM_QUESTIONS = [OPS_CONFIRM, MARKET_CONFIRM, PEOPLE_CONFIRM, FIN_CONFIRM]


def _post(base_url: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base_url}{path}"
    resp = requests.post(url, json=payload, timeout=180)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"POST {url} -> {resp.status_code}: {data}")
    return data


def _get(base_url: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base_url}{path}"
    resp = requests.get(url, params=params, timeout=180)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(f"GET {url} -> {resp.status_code}: {data}")
    return data


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _reply_for(msg: str, focus: str, scenario: Dict[str, Any]) -> str:
    m = _normalize(msg)

    if "does this look right" in m or "confirm" in m:
        return "yes"

    if focus == "ops":
        if "plain language" in m or "what does" in m or "to get us started" in m:
            return scenario["ops_intro"]
        if "mainly serve" in m or "sell to" in m or "mainly sell" in m:
            return scenario["consumer_type"]
        if "unit" in m and ("make the most sense" in m or "treat" in m):
            return scenario["unit_reply"]
        if "typical" in m or "usually" in m:
            return scenario["unit_desc"]
        if "average" in m and ("price" in m or "charge" in m or "spend" in m):
            return scenario["unit_price"]
        if "how many" in m and "week" in m:
            return scenario["capacity"]
        if "receive" in m or "deliver" in m or "fulfillment" in m:
            return scenario["fulfillment"]
        if "local" in m and ("regional" in m or "nationwide" in m):
            return scenario["geographic_scope"]
        if "legal" in m:
            return scenario["legal_entity"]
        if "milestone" in m or "goal" in m:
            return scenario["milestone"]
        if "equipment" in m or "fixtures" in m or "assets" in m:
            return scenario["initial_assets"]
        if "owe" in m or "loan" in m:
            return scenario["debt"]
        if "lease" in m:
            return scenario["lease"]
        if "total" in m and "put into" in m:
            return scenario["initial_equity"]
        if "constraint" in m or "limit" in m:
            return scenario["capacity_driver"]

    if focus == "market":
        if "approved" in m or "approve" in m:
            return "approved as-is"
        if "gender" in m:
            return scenario.get("gender", "all")
        if "age" in m:
            return scenario.get("age", "25-60")
        if "income" in m:
            return scenario.get("income", "40k-120k")
        if "education" in m:
            return "no preference"
        if "industry" in m or "b2b" in m or "firms" in m:
            return scenario.get("b2b_industry", "freight brokers")
        if "promotion" in m or "reach" in m or "customers typically" in m:
            return "sounds right"
        if "skip" in m or "optional" in m:
            return "skip"

    if focus == "people":
        if "full name" in m and "title" in m:
            return scenario["people_first"]
        if "add another" in m or "anyone else" in m or "add anyone" in m:
            return "done with people"
        if "review" in m or "accurate" in m or "approve" in m or "approved" in m or "confirm" in m:
            return "approved as-is"
        if "roles" in m and ("remove" in m or "rename" in m or "add" in m or "keep" in m):
            return "keep them"

    if focus == "financials":
        if "revenue" in m:
            return "0"
        if "direct" in m or "cogs" in m:
            return "0"
        if "operating expenses" in m or "regular" in m:
            return "500"
        if "rent" in m:
            return "0"
        if "payroll" in m and "employees" in m:
            return "0"
        if "how many employees" in m:
            return "0"
        if "owner" in m and ("pay" in m or "draw" in m):
            return "0"
        if "capex" in m or "one-time" in m:
            return "0"
        if "debt" in m and "owe" in m:
            return "0"
        if "debt payments" in m:
            return "0"
        if "interest" in m and "principal" in m:
            return "0"
        if "cash" in m:
            return "0"
        if "receivable" in m or "owed you" in m:
            return "0"
        if "payable" in m or "owe" in m:
            return "0"
        if "inventory" in m:
            return "0"

    return "yes"


def _parse_json(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return None


def _check_invariants(draft: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    ops = _parse_json(draft.get("operating_model_json")) or {}
    people = _parse_json(draft.get("people_json")) or {}
    msgs = _parse_json(draft.get("messages_json")) or []

    # NAICS in ops
    if not str(ops.get("business_naics_6") or "").strip():
        errors.append("ops.business_naics_6 is missing")

    # wages in people + roles
    ppl = people.get("people") if isinstance(people, dict) else []
    roles = people.get("inferred_roles") if isinstance(people, dict) else []
    if not isinstance(ppl, list) or not ppl:
        errors.append("people list missing")
    else:
        for p in ppl:
            if not isinstance(p, dict):
                continue
            if p.get("annual_wage") is None:
                errors.append("people annual_wage missing")
                break
            if "oews" not in str(p.get("wage_source") or ""):
                errors.append("people wage_source not OEWS")
                break
    if not isinstance(roles, list) or not roles:
        errors.append("inferred_roles list missing")
    else:
        for r in roles:
            if not isinstance(r, dict):
                continue
            if r.get("annual_wage") is None:
                errors.append("role annual_wage missing")
                break
            if "oews" not in str(r.get("wage_source") or ""):
                errors.append("role wage_source not OEWS")
                break

    # duplicate summaries or auto-advance
    if isinstance(msgs, list):
        for q in CONFIRM_QUESTIONS:
            count = sum(1 for m in msgs if isinstance(m, dict) and q in str(m.get("content") or ""))
            if count > 1:
                errors.append(f"duplicate confirm question: {q}")
        # auto-advance check: confirm question followed by assistant message without user
        for i, m in enumerate(msgs[:-1]):
            if not isinstance(m, dict):
                continue
            if str(m.get("role") or "") != "assistant":
                continue
            content = str(m.get("content") or "")
            if any(q in content for q in CONFIRM_QUESTIONS):
                # find next non-empty message
                j = i + 1
                while j < len(msgs) and not str(msgs[j].get("content") or "").strip():
                    j += 1
                if j < len(msgs) and str(msgs[j].get("role") or "") == "assistant":
                    errors.append("auto-advance after confirmation")
                    break

    return (len(errors) == 0, errors)


def run_scenario(base_url: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    session = _post(base_url, "/api/intake-consult/session", {})
    draft_id = session.get("draft_id")
    client_id = session.get("client_id")
    if not draft_id:
        raise RuntimeError(f"Failed to create draft: {session}")

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
    focus_sequence: List[str] = []

    for _ in range(80):
        assistant_msg = response.get("assistant_message") or ""
        active_focus = str(response.get("active_focus") or "").strip().lower()
        transcript.append({"role": "assistant", "content": assistant_msg})
        if active_focus and (not focus_sequence or focus_sequence[-1] != active_focus):
            focus_sequence.append(active_focus)

        if response.get("done"):
            break

        reply = _reply_for(assistant_msg, active_focus, scenario)
        transcript.append({"role": "user", "content": reply})
        response = _post(
            base_url,
            "/api/intake-consult",
            {"draft_id": draft_id, "client_id": client_id, "message": reply},
        )

    draft = _get(base_url, "/api/intake-consult/draft", {"draft_id": draft_id})
    ok, errors = _check_invariants(draft)

    out = {
        "name": scenario["name"],
        "draft_id": draft_id,
        "active_focus": draft.get("active_focus"),
        "focus_sequence": focus_sequence,
        "ok": ok,
        "errors": errors,
        "operating_model_json": draft.get("operating_model_json"),
        "people_json": draft.get("people_json"),
    }

    with open(f"intake_e2e_{scenario['name']}.json", "w", encoding="utf-8") as handle:
        json.dump(transcript, handle, indent=2)

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multiple intake e2e scenarios via API.")
    parser.add_argument("--base-url", default=os.getenv("INTAKE_BASE_URL", "http://127.0.0.1:5050"))
    parser.add_argument("--scenario", default="", help="Run only a named scenario")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    scenarios = [
        {
            "name": "landscaping_multi_lob",
            "business_name": "Evergreen Grounds Co.",
            "business_start_date": "04/10/2026",
            "address": "2200 Greenway Dr, Jacksonville, FL 32216, USA",
            "address_street": "2200 Greenway Dr",
            "address_city": "Jacksonville",
            "address_state": "FL",
            "address_zip": "32216",
            "address_country": "USA",
            "ops_intro": (
                "We run a Landscaping Company with two lines of business: "
                "recurring lawn maintenance for homeowners and tree/shrub service jobs for local businesses."
            ),
            "consumer_type": "A mix of consumers and businesses.",
            "unit_reply": (
                "Two units: (1) one lawn maintenance visit, and (2) one tree/shrub service job."
            ),
            "unit_desc": (
                "A lawn visit covers mowing, edging, and cleanup; a tree/shrub job covers trimming and hauling."
            ),
            "unit_price": "120 per lawn visit and 500 per tree/shrub job.",
            "capacity": "25 lawn visits and 6 tree/shrub jobs per week.",
            "fulfillment": "On-site service at the customer property with our crew and equipment.",
            "geographic_scope": "Local.",
            "legal_entity": "LLC",
            "milestone": "Reach 40 lawn visits and 10 tree/shrub jobs per week within 12 months.",
            "initial_assets": "75000",
            "debt": "25000",
            "lease": "No",
            "initial_equity": "50000",
            "capacity_driver": "Labor",
            "people_first": "Casey Jordan, Owner, 14 years in landscaping, no formal degree",
        },
        {
            "name": "dental_equipment_multi_products",
            "business_name": "BrightSmile Devices",
            "business_start_date": "05/05/2026",
            "address": "4100 Innovation Way, Jacksonville, FL 32224, USA",
            "address_street": "4100 Innovation Way",
            "address_city": "Jacksonville",
            "address_state": "FL",
            "address_zip": "32224",
            "address_country": "USA",
            "ops_intro": (
                "We are a Dental Equipment Manufacturer producing two products: "
                "dental chairs and dental X-ray machines."
            ),
            "consumer_type": "Businesses only (dental clinics and distributors).",
            "unit_reply": "One piece of dental equipment (chair or X-ray machine).",
            "unit_desc": "A single manufactured dental chair or dental X-ray unit delivered to a clinic.",
            "unit_price": "22000 per chair and 90000 per X-ray machine.",
            "capacity": "10 chairs and 2 X-ray machines per week.",
            "fulfillment": "Factory production and on-site delivery/installation at customer facilities.",
            "geographic_scope": "National.",
            "legal_entity": "LLC",
            "milestone": "Deliver 250 chairs and 40 X-ray machines in year one.",
            "initial_assets": "1200000",
            "debt": "400000",
            "lease": "No",
            "initial_equity": "800000",
            "capacity_driver": "Labor",
            "people_first": "Taylor Nguyen, GM, 16 years in medical device manufacturing, BS Engineering",
            "b2b_industry": "dental clinics and distributors",
        },
        {
            "name": "ready_to_eat_multi_lob_products",
            "business_name": "Harvest Ready Meals",
            "business_start_date": "06/15/2026",
            "address": "800 Food Park Blvd, Jacksonville, FL 32218, USA",
            "address_street": "800 Food Park Blvd",
            "address_city": "Jacksonville",
            "address_state": "FL",
            "address_zip": "32218",
            "address_country": "USA",
            "ops_intro": (
                "We are a Ready-to-Eat Food Producer with two lines of business: "
                "retail packaged meals for grocery chains and bulk meal kits for institutional cafeterias. "
                "Retail has two product lines (vegan and keto trays), and bulk has two products "
                "(50-serving trays and 200-serving trays)."
            ),
            "consumer_type": "Businesses only (grocery chains and cafeterias).",
            "unit_reply": (
                "Two lines: retail meal trays (vegan and keto) and bulk meal kits "
                "(50-serving and 200-serving trays)."
            ),
            "unit_desc": (
                "Retail is one packaged meal tray; bulk is one prepared tray of 50 or 200 servings."
            ),
            "unit_price": "8 per retail tray, 350 per 50-serving tray, 1200 per 200-serving tray.",
            "capacity": "1500 retail trays and 40 bulk trays per week.",
            "fulfillment": "On-site production with refrigerated distribution to customer loading docks.",
            "geographic_scope": "Regional.",
            "legal_entity": "LLC",
            "milestone": "Reach 1.5 million retail trays and 2,000 bulk trays in year one.",
            "initial_assets": "2500000",
            "debt": "1500000",
            "lease": "No",
            "initial_equity": "1000000",
            "capacity_driver": "System",
            "people_first": "Jordan Ellis, Plant Manager, 18 years in food manufacturing, BS Food Science",
            "b2b_industry": "grocery chains and institutional cafeterias",
        },
        {
            "name": "xray_producer",
            "business_name": "Radiant Imaging Systems",
            "business_start_date": "04/01/2026",
            "address": "1200 Tech Park Dr, Jacksonville, FL 32224, USA",
            "address_street": "1200 Tech Park Dr",
            "address_city": "Jacksonville",
            "address_state": "FL",
            "address_zip": "32224",
            "address_country": "USA",
            "ops_intro": "We are an X-ray Machine Producer manufacturing imaging equipment for hospitals and clinics.",
            "consumer_type": "Businesses only (hospitals, clinics, distributors).",
            "unit_reply": "One X-ray machine.",
            "unit_desc": "A single manufactured X-ray system delivered to a medical facility.",
            "unit_price": "250000",
            "capacity": "4",
            "fulfillment": "On-site delivery and installation at customer facilities.",
            "geographic_scope": "National.",
            "legal_entity": "LLC",
            "milestone": "Deliver 10 systems within the first year.",
            "initial_assets": "500000",
            "debt": "200000",
            "lease": "No",
            "initial_equity": "300000",
            "capacity_driver": "Labor",
            "people_first": "Jordan Lee, Founder & CEO, 15 years in medical device manufacturing, MS in Engineering",
            "b2b_industry": "hospitals and clinics",
        },
        {
            "name": "preowned_auto_dealer",
            "business_name": "Value Motors",
            "business_start_date": "03/15/2026",
            "address": "900 Auto Row Blvd, Jacksonville, FL 32210, USA",
            "address_street": "900 Auto Row Blvd",
            "address_city": "Jacksonville",
            "address_state": "FL",
            "address_zip": "32210",
            "address_country": "USA",
            "ops_intro": "We run a Pre-Owned Auto Dealer selling used vehicles to local consumers.",
            "consumer_type": "Mostly individual consumers.",
            "unit_reply": "One used car sale.",
            "unit_desc": "A single used vehicle sold to a customer.",
            "unit_price": "14000",
            "capacity": "12",
            "fulfillment": "In-person pickup at the dealership.",
            "geographic_scope": "Local.",
            "legal_entity": "LLC",
            "milestone": "Sell 50 vehicles in the first 6 months.",
            "initial_assets": "250000",
            "debt": "100000",
            "lease": "No",
            "initial_equity": "150000",
            "capacity_driver": "Demand",
            "people_first": "Avery Smith, Owner, 12 years in auto sales, no formal degree",
        },
        {
            "name": "mutual_fund",
            "business_name": "Sunrise Growth Fund",
            "business_start_date": "05/01/2026",
            "address": "500 Finance Ave, Jacksonville, FL 32202, USA",
            "address_street": "500 Finance Ave",
            "address_city": "Jacksonville",
            "address_state": "FL",
            "address_zip": "32202",
            "address_country": "USA",
            "ops_intro": "We operate a Mutual Fund offering investment shares to individual investors.",
            "consumer_type": "Mostly individual consumers.",
            "unit_reply": "One investor account.",
            "unit_desc": "A single investor account holding mutual fund shares.",
            "unit_price": "10000",
            "capacity": "50",
            "fulfillment": "Digital onboarding and account setup.",
            "geographic_scope": "National.",
            "legal_entity": "LLC",
            "milestone": "Reach 500 investor accounts in year one.",
            "initial_assets": "1000000",
            "debt": "0",
            "lease": "No",
            "initial_equity": "1000000",
            "capacity_driver": "Demand",
            "people_first": "Morgan Patel, Managing Director, 18 years in asset management, MBA",
        },
        {
            "name": "energy_from_waste",
            "business_name": "GreenCycle Energy",
            "business_start_date": "06/01/2026",
            "address": "1000 Industrial Way, Jacksonville, FL 32219, USA",
            "address_street": "1000 Industrial Way",
            "address_city": "Jacksonville",
            "address_state": "FL",
            "address_zip": "32219",
            "address_country": "USA",
            "ops_intro": "We operate an Energy-from-Waste Facility that converts municipal waste into electricity for utilities and local governments.",
            "consumer_type": "Businesses and municipalities.",
            "unit_reply": "One ton of waste processed.",
            "unit_desc": "Processing one ton of municipal solid waste into energy.",
            "unit_price": "65",
            "capacity": "500",
            "fulfillment": "On-site waste intake and energy generation.",
            "geographic_scope": "Regional.",
            "legal_entity": "LLC",
            "milestone": "Process 25,000 tons in the first year.",
            "initial_assets": "25000000",
            "debt": "15000000",
            "lease": "No",
            "initial_equity": "10000000",
            "capacity_driver": "System",
            "people_first": "Riley Chen, Plant Director, 20 years in waste-to-energy operations, BS Engineering",
            "b2b_industry": "municipalities and utilities",
        },
    ]
    results = []
    failures = 0
    for scenario in scenarios:
        if args.scenario and scenario["name"] != args.scenario:
            continue
        res = run_scenario(base_url, scenario)
        results.append(res)
        if not res["ok"]:
            failures += 1

    print(json.dumps(results, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
