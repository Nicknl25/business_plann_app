import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

import requests


def _post(base_url: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
  url = f"{base_url}{path}"
  last_exc: Optional[Exception] = None
  for _ in range(3):
    try:
      resp = requests.post(url, json=payload, timeout=180)
      try:
        data = resp.json()
      except Exception:
        data = {"raw": resp.text}
      if resp.status_code >= 400:
        raise RuntimeError(f"POST {url} -> {resp.status_code}: {data}")
      return data
    except requests.exceptions.ReadTimeout as exc:
      last_exc = exc
      continue
  raise RuntimeError(f"POST {url} timed out after retries: {last_exc}")


def _get(base_url: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
  url = f"{base_url}{path}"
  last_exc: Optional[Exception] = None
  for _ in range(3):
    try:
      resp = requests.get(url, params=params, timeout=180)
      try:
        data = resp.json()
      except Exception:
        data = {"raw": resp.text}
      if resp.status_code >= 400:
        raise RuntimeError(f"GET {url} -> {resp.status_code}: {data}")
      return data
    except requests.exceptions.ReadTimeout as exc:
      last_exc = exc
      continue
  raise RuntimeError(f"GET {url} timed out after retries: {last_exc}")


def _normalize(text: str) -> str:
  return " ".join(str(text or "").strip().lower().split())


def _reply_for(assistant_message: str, active_focus: str) -> str:
  msg = _normalize(assistant_message)

  if active_focus == "ops":
    if "plain language" in msg or "what does" in msg:
      return "We run a local bakery selling baked goods to walk-in consumers."
    if "mainly serve" in msg or "sell to" in msg or "mainly sell to" in msg:
      return "Mostly individual consumers."
    if "unit" in msg and "make the most sense" in msg:
      return "One customer order."
    if "typical order" in msg or "what's usually in it" in msg:
      return "A mix of baked goods, usually 2-3 items."
    if "average" in msg and ("price" in msg or "charge" in msg or "spend" in msg):
      return "12"
    if "how many" in msg and "week" in msg and ("order" in msg or "unit" in msg):
      return "200"
    if "receive" in msg or "deliver" in msg or "fulfillment" in msg:
      return "In-person pickup at the shop."
    if "local" in msg and ("regional" in msg or "nationwide" in msg):
      return "Local."
    if "legal setup" in msg or "legal" in msg:
      return "LLC"
    if "milestone" in msg or "goal" in msg:
      return "Reach 250 orders per week within 12 months."
    if "equipment" in msg or "fixtures" in msg:
      return "10000"
    if "paid for" in msg or "covered" in msg:
      return "Own money."
    if "lease" in msg or "rent equipment" in msg:
      return "No"
    if "total" in msg and "put into" in msg:
      return "20000"
    if "constraint" in msg or "limit" in msg:
      return "Demand"

  if active_focus == "market":
    if "approved" in msg or "approve" in msg:
      return "approved as-is"
    if "gender" in msg:
      return "All"
    if "age" in msg:
      return "25-60"
    if "income" in msg:
      return "40k-120k"
    if "education" in msg:
      return "No preference"
    if "optional" in msg or "skip" in msg:
      return "Skip"
    if "customers typically" in msg or "how customers are typically reached" in msg:
      return "Sounds right"

  if active_focus == "people":
    if "full name" in msg and "title" in msg:
      return "Alex Brown, Owner, 10 years experience, no formal degree"
    if "add another" in msg or "add anyone else" in msg:
      return "done with people"
    if "review" in msg or "accurate" in msg or "approve" in msg or "approved" in msg:
      return "approved as-is"
    if "roles" in msg and ("remove" in msg or "rename" in msg or "add" in msg):
      return "keep them"

  if active_focus == "financials":
    if "revenue" in msg:
      return "0"
    if "direct" in msg or "cogs" in msg:
      return "0"
    if "operating expenses" in msg or "regular" in msg:
      return "500"
    if "rent" in msg:
      return "0"
    if "payroll" in msg and "employees" in msg:
      return "0"
    if "how many employees" in msg:
      return "0"
    if "owner" in msg and ("pay" in msg or "draw" in msg):
      return "0"
    if "capex" in msg or "one-time" in msg or "equipment" in msg:
      return "0"
    if "debt" in msg and "owe" in msg:
      return "0"
    if "debt payments" in msg:
      return "0"
    if "interest" in msg and "principal" in msg:
      return "0"
    if "cash" in msg:
      return "0"
    if "receivable" in msg or "owed you" in msg:
      return "0"
    if "payable" in msg or "owe" in msg:
      return "0"
    if "inventory" in msg:
      return "0"

  if "does this look right" in msg or "confirm" in msg or "look right" in msg:
    return "yes"

  if active_focus == "consistency":
    return "yes"

  return "yes"


def main() -> int:
  parser = argparse.ArgumentParser(description="Run end-to-end intake consult via API.")
  parser.add_argument("--base-url", default=os.getenv("INTAKE_BASE_URL", "http://127.0.0.1:5050"))
  parser.add_argument("--max-turns", type=int, default=60)
  args = parser.parse_args()

  base_url = args.base_url.rstrip("/")

  session = _post(base_url, "/api/intake-consult/session", {})
  draft_id = session.get("draft_id")
  client_id = session.get("client_id")
  if not draft_id:
    raise RuntimeError(f"Failed to create draft: {session}")

  seed_payload = {
    "draft_id": draft_id,
    "client_id": client_id,
    "business_name": "Test Bakery",
    "business_start_date": "01/31/2026",
    "address": "888 Lane Ave S, Jacksonville, FL 32205, USA",
    "address_street": "888 Lane Ave S",
    "address_city": "Jacksonville",
    "address_state": "FL",
    "address_zip": "32205",
    "address_country": "USA",
    "message": "",
  }
  response = _post(base_url, "/api/intake-consult", seed_payload)
  transcript = []

  for _ in range(args.max_turns):
    assistant_msg = response.get("assistant_message") or ""
    active_focus = str(response.get("active_focus") or "").strip().lower()
    transcript.append({"role": "assistant", "content": assistant_msg})

    if response.get("done"):
      break

    reply = _reply_for(assistant_msg, active_focus)
    transcript.append({"role": "user", "content": reply})
    response = _post(
      base_url,
      "/api/intake-consult",
      {"draft_id": draft_id, "client_id": client_id, "message": reply},
    )

    if active_focus == "financials" and response.get("active_focus") == "consistency":
      break

  draft = _get(base_url, "/api/intake-consult/draft", {"draft_id": draft_id})

  print("Draft ID:", draft_id)
  print("Active focus:", draft.get("active_focus"))
  print("Confirmed:", {
    "ops": draft.get("ops_confirmed"),
    "market": draft.get("market_confirmed"),
    "people": draft.get("people_confirmed"),
    "financials": draft.get("financials_confirmed"),
    "consistency": draft.get("consistency_passed"),
  })

  print("\nFinal operating_model_json present:", bool(draft.get("operating_model_json")))
  print("Final target_market_json present:", bool(draft.get("target_market_json")))
  print("Final people_json present:", bool(draft.get("people_json")))
  print("Final financials_json present:", bool(draft.get("financials_json")))

  with open("intake_e2e_transcript.json", "w", encoding="utf-8") as handle:
    json.dump(transcript, handle, indent=2)
  print("Transcript saved to intake_e2e_transcript.json")

  if not draft.get("financials_confirmed"):
    print("WARNING: financials_confirmed is not true yet.")
    return 2

  return 0


if __name__ == "__main__":
  raise SystemExit(main())
