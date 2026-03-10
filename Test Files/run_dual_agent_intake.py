import argparse
import json
import os
import sys
import textwrap
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import requests

try:
  from dotenv import load_dotenv
except Exception:
  load_dotenv = None


OPENAI_URL = "https://api.openai.com/v1/responses"


def _load_env() -> None:
  if load_dotenv:
    try:
      repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
      root_env = os.path.join(repo_root, ".env")
      if os.path.exists(root_env):
        load_dotenv(root_env, override=False)
      else:
        load_dotenv(override=False)
    except Exception:
      pass


def _post_json(url: str, payload: Dict[str, Any], *, timeout: int = 240) -> Dict[str, Any]:
  resp = requests.post(url, json=payload, timeout=timeout)
  try:
    data = resp.json()
  except Exception:
    data = {"raw": resp.text}
  if resp.status_code >= 400:
    raise RuntimeError(f"POST {url} -> {resp.status_code}: {data}")
  if not isinstance(data, dict):
    raise RuntimeError(f"POST {url} returned non-object payload: {data}")
  return data


def _get_json(url: str, params: Dict[str, Any], *, timeout: int = 240) -> Dict[str, Any]:
  resp = requests.get(url, params=params, timeout=timeout)
  try:
    data = resp.json()
  except Exception:
    data = {"raw": resp.text}
  if resp.status_code >= 400:
    raise RuntimeError(f"GET {url} -> {resp.status_code}: {data}")
  if not isinstance(data, dict):
    raise RuntimeError(f"GET {url} returned non-object payload: {data}")
  return data


def _normalize(text: str) -> str:
  return " ".join(str(text or "").strip().lower().split())


def _similarity(a: str, b: str) -> float:
  return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _parse_responses_json(data: Dict[str, Any]) -> Dict[str, Any]:
  output = data.get("output") or []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        return part["json"]
  texts: List[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text":
        text = part.get("text")
        if isinstance(text, str) and text.strip():
          texts.append(text)
  raw = "\n".join(texts).strip()
  if not raw:
    raise RuntimeError(f"OpenAI response did not contain output_json/output_text: {data}")
  parsed = json.loads(raw)
  if not isinstance(parsed, dict):
    raise RuntimeError(f"OpenAI response was not a JSON object: {parsed}")
  return parsed


def _openai_call(
  *,
  api_key: str,
  model: str,
  schema_name: str,
  schema: Dict[str, Any],
  messages: List[Dict[str, str]],
) -> Dict[str, Any]:
  payload = {
    "model": model,
    "input": messages,
    "text": {
      "format": {
        "type": "json_schema",
        "name": schema_name,
        "schema": schema,
        "strict": True,
      }
    },
  }
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  resp = requests.post(OPENAI_URL, headers=headers, json=payload, timeout=240)
  try:
    data = resp.json()
  except Exception:
    data = {"raw": resp.text}
  if resp.status_code >= 400:
    raise RuntimeError(f"OpenAI -> {resp.status_code}: {data}")
  if not isinstance(data, dict):
    raise RuntimeError(f"OpenAI returned non-object payload: {data}")
  return _parse_responses_json(data)


@dataclass
class Bootstrap:
  business_name: str
  business_start_date: str
  address: str
  address_street: str
  address_city: str
  address_state: str
  address_zip: str
  address_country: str
  private_state: str


class ClientAgent:
  def __init__(self, *, api_key: str, model: str, seed: str) -> None:
    self.api_key = api_key
    self.model = model
    self.seed = seed.strip()
    self.private_state = ""

  def bootstrap(self) -> Bootstrap:
    schema = {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "business_name": {"type": "string"},
        "business_start_date": {"type": "string"},
        "address": {"type": "string"},
        "address_street": {"type": "string"},
        "address_city": {"type": "string"},
        "address_state": {"type": "string"},
        "address_zip": {"type": "string"},
        "address_country": {"type": "string"},
        "private_state": {"type": "string"},
      },
      "required": [
        "business_name",
        "business_start_date",
        "address",
        "address_street",
        "address_city",
        "address_state",
        "address_zip",
        "address_country",
        "private_state",
      ],
    }
    system = textwrap.dedent(
      """
      You are preparing a hidden business-owner persona for a black-box intake simulation.

      The seed sentence tells you what kind of business to simulate. Expand it into one coherent,
      plausible business in the United States. Keep it realistic. Do not invent something absurd.

      Return ONLY JSON that matches the schema.
      business_start_date must be formatted MM/DD/YYYY.
      address must be a plausible complete U.S. mailing address.
      private_state must be a compact hidden briefing that captures the business facts, owner style,
      and any important numbers so later answers stay consistent.
      """
    ).strip()
    user = f"Seed business to simulate: {self.seed}"
    obj = _openai_call(
      api_key=self.api_key,
      model=self.model,
      schema_name="intake_test_bootstrap",
      schema=schema,
      messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
      ],
    )
    self.private_state = str(obj["private_state"]).strip()
    return Bootstrap(
      business_name=str(obj["business_name"]).strip(),
      business_start_date=str(obj["business_start_date"]).strip(),
      address=str(obj["address"]).strip(),
      address_street=str(obj["address_street"]).strip(),
      address_city=str(obj["address_city"]).strip(),
      address_state=str(obj["address_state"]).strip(),
      address_zip=str(obj["address_zip"]).strip(),
      address_country=str(obj["address_country"]).strip(),
      private_state=self.private_state,
    )

  def answer(
    self,
    *,
    active_focus: str,
    assistant_message: str,
    transcript_tail: List[Dict[str, str]],
  ) -> str:
    schema = {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "answer": {"type": "string"},
        "updated_private_state": {"type": "string"},
      },
      "required": ["answer", "updated_private_state"],
    }
    system = textwrap.dedent(
      """
      You are simulating a real business owner going through a business-plan intake chat.

      Rules:
      - Stay consistent with the hidden private state.
      - Answer naturally, as a human would.
      - Be concise unless the consultant clearly needs detail.
      - If the consultant asks a confusing question, push back briefly and ask for clarification.
      - If the consultant repeats a question you already answered, say so like a real user would.
      - If the consultant proposes a reasonable assumption that fits your business, you may agree briefly.
      - Do not mention the hidden private state or that you are a simulation.

      Return ONLY JSON matching the schema.
      updated_private_state should stay compact and reflect any clarified facts you just committed to.
      """
    ).strip()
    transcript_blob = json.dumps(transcript_tail[-12:], ensure_ascii=False)
    user = (
      f"Seed: {self.seed}\n"
      f"Current focus: {active_focus}\n"
      f"Hidden private state:\n{self.private_state}\n\n"
      f"Recent transcript tail (JSON):\n{transcript_blob}\n\n"
      f"Latest consultant message:\n{assistant_message}\n"
    )
    obj = _openai_call(
      api_key=self.api_key,
      model=self.model,
      schema_name="intake_test_turn",
      schema=schema,
      messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
      ],
    )
    self.private_state = str(obj["updated_private_state"]).strip() or self.private_state
    return str(obj["answer"]).strip()


def _print_transcript_tail(transcript: List[Dict[str, str]], count: int = 10) -> None:
  print("\nLast transcript turns:")
  for item in transcript[-count:]:
    role = item.get("role", "?")
    content = str(item.get("content") or "").strip()
    print(f"[{role}] {content}")


def _detect_failure(
  *,
  transcript: List[Dict[str, str]],
  assistant_message: str,
  active_focus: str,
  turn_index: int,
  max_turns: int,
) -> Optional[str]:
  if not str(assistant_message or "").strip():
    return "assistant returned an empty message"
  if turn_index + 1 >= max_turns:
    return f"max turns reached ({max_turns})"

  assistant_msgs = [
    item for item in transcript if item.get("role") == "assistant" and str(item.get("focus") or "") == active_focus
  ]
  if len(assistant_msgs) >= 3:
    last_three = assistant_msgs[-3:]
    msg_a = str(last_three[-1].get("content") or "")
    msg_b = str(last_three[-2].get("content") or "")
    msg_c = str(last_three[-3].get("content") or "")
    if _similarity(msg_a, msg_b) >= 0.94 and _similarity(msg_a, msg_c) >= 0.90:
      return f"suspected loop in focus '{active_focus}' (assistant repeated substantially the same question)"

  user_msgs = [item for item in transcript if item.get("role") == "user"]
  if user_msgs and assistant_msgs:
    last_user = str(user_msgs[-1].get("content") or "")
    if _normalize(last_user) in {
      "i already answered this",
      "we already talked about this",
      "you already asked this",
      "i already answered this too",
    }:
      return f"user simulator flagged repetition in focus '{active_focus}'"
  return None


def main() -> int:
  _load_env()

  parser = argparse.ArgumentParser(
    description="Run a black-box dual-agent intake simulation against the real local app."
  )
  parser.add_argument(
    "seed",
    help='Plain-English seed, e.g. "Test a two-product local event services business"',
  )
  parser.add_argument("--base-url", default=os.getenv("INTAKE_BASE_URL", "http://127.0.0.1:5050"))
  parser.add_argument("--model", default=os.getenv("INTAKE_SIM_MODEL", "gpt-4.1-mini"))
  parser.add_argument("--max-turns", type=int, default=80)
  args = parser.parse_args()

  api_key = os.getenv("OPENAI_API_KEY", "").strip()
  if not api_key:
    print("OPENAI_API_KEY is not set.", file=sys.stderr)
    return 2

  base_url = args.base_url.rstrip("/")
  agent = ClientAgent(api_key=api_key, model=args.model, seed=args.seed)
  transcript: List[Dict[str, str]] = []

  try:
    bootstrap = agent.bootstrap()
    print(f"Bootstrapped business: {bootstrap.business_name}")

    session = _post_json(f"{base_url}/api/intake-consult/session", {})
    draft_id = session.get("draft_id")
    client_id = session.get("client_id")
    if not draft_id:
      raise RuntimeError(f"Failed to create draft session: {session}")

    seed_payload = {
      "draft_id": draft_id,
      "client_id": client_id,
      "business_name": bootstrap.business_name,
      "business_start_date": bootstrap.business_start_date,
      "address": bootstrap.address,
      "address_street": bootstrap.address_street,
      "address_city": bootstrap.address_city,
      "address_state": bootstrap.address_state,
      "address_zip": bootstrap.address_zip,
      "address_country": bootstrap.address_country,
      "message": "",
    }
    response = _post_json(f"{base_url}/api/intake-consult", seed_payload)

    for turn_index in range(args.max_turns):
      assistant_message = str(response.get("assistant_message") or "").strip()
      active_focus = str(response.get("active_focus") or "").strip().lower()
      transcript.append({"role": "assistant", "content": assistant_message, "focus": active_focus})
      print(f"\n[{active_focus or 'unknown'}][assistant] {assistant_message}")

      if response.get("done"):
        print("\nSimulation completed.")
        draft = _get_json(f"{base_url}/api/intake-consult/draft", {"draft_id": draft_id})
        print(
          "Final flags:",
          json.dumps(
            {
              "ops_confirmed": draft.get("ops_confirmed"),
              "market_confirmed": draft.get("market_confirmed"),
              "people_confirmed": draft.get("people_confirmed"),
              "financials_confirmed": draft.get("financials_confirmed"),
              "consistency_passed": draft.get("consistency_passed"),
            },
            ensure_ascii=False,
          ),
        )
        print(f"Draft ID: {draft_id}")
        return 0

      failure = _detect_failure(
        transcript=transcript,
        assistant_message=assistant_message,
        active_focus=active_focus,
        turn_index=turn_index,
        max_turns=args.max_turns,
      )
      if failure:
        print(f"\nSTOP: {failure}")
        print(f"Draft ID: {draft_id}")
        _print_transcript_tail(transcript)
        return 1

      reply = agent.answer(
        active_focus=active_focus,
        assistant_message=assistant_message,
        transcript_tail=transcript,
      )
      transcript.append({"role": "user", "content": reply, "focus": active_focus})
      print(f"[user] {reply}")

      response = _post_json(
        f"{base_url}/api/intake-consult",
        {
          "draft_id": draft_id,
          "client_id": client_id,
          "message": reply,
        },
      )

    print(f"\nSTOP: max turns reached ({args.max_turns})")
    print(f"Draft ID: {draft_id}")
    _print_transcript_tail(transcript)
    return 1

  except KeyboardInterrupt:
    print("\nStopped by user.")
    return 130
  except Exception as exc:
    print(f"\nSTOP: runner error: {type(exc).__name__}: {exc}")
    _print_transcript_tail(transcript)
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
