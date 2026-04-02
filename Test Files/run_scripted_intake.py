import argparse
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


THIS_DIR = Path(__file__).resolve().parent
DUAL_RUNNER_PATH = THIS_DIR / "run_dual_agent_intake.py"


def _load_dual_runner_module():
  spec = importlib.util.spec_from_file_location("run_dual_agent_intake_shared", str(DUAL_RUNNER_PATH))
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load shared runner module from {DUAL_RUNNER_PATH}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


_SHARED = _load_dual_runner_module()


TEMPLATE_SPEC: Dict[str, Any] = {
  "bootstrap": {
    "business_name": "Example Wellness Business",
    "business_start_date": "08/05/2024",
    "address": "123 Example Street, Austin, TX 78701",
    "address_street": "123 Example Street",
    "address_city": "Austin",
    "address_state": "TX",
    "address_zip": "78701",
    "address_country": "USA",
  },
  "ops": {
    "business_description": "",
    "customer_type": "",
    "products_confirmed": "Yes, track those as separate products.",
    "legal_entity": "",
    "delivery_method": "",
    "fulfillment_confirmation": "Yes, that's accurate.",
    "sales_channel": "",
    "geography": "",
    "growth_lever": "",
    "competitive_advantage": "",
    "goal_12_months": "",
    "confirmation": "Yes, that's correct.",
    "products": [
      {
        "product_name": "Product 1",
        "aliases": [],
        "unit_definition": "",
        "capacity": "",
        "utilization": "",
        "price": "",
      }
    ],
  },
  "market": {
    "gender": "",
    "age_range": "",
    "income_range": "",
    "education": "",
    "profile_detail_choice": "",
    "employment_mix": "",
    "confirmation": "Yes, that looks right.",
  },
  "people": {
    "owner_background": "",
    "other_key_people": "I'm currently the only key person involved in the business.",
    "confirmation": "Yes, that looks right.",
  },
  "financials": {
    "revenue_setup": "",
    "cogs": "",
    "payroll": "",
    "payroll_detail": "",
    "monthly_rent_expense": "",
    "other_operating_expense": "",
    "other_monthly_debt_payments": "",
    "cash_on_hand": "",
    "ar_balance": "",
    "ap_balance": "",
    "inventory_balance": "",
    "current_capex": "",
    "initial_assets": "",
    "initial_lease": "",
    "initial_equity": "",
    "total_debt_outstanding": "",
    "annual_interest_payment": "",
    "annual_principal_payment": "",
    "owner_compensation": "",
    "confirmation": "Yes, that's right.",
  },
  "consistency": {
    "confirmation": "Yes, that works for me.",
  },
  "fallback": {
    "ops": [],
    "market": [],
    "people": [],
    "financials": [],
    "consistency": [],
  },
  "overrides": [
    {
      "focus": "consistency",
      "contains": "",
      "answer": "",
    }
  ],
}


def _normalize(text: str) -> str:
  return " ".join(str(text or "").strip().lower().split())


def _contains_any(text: str, patterns: Sequence[str]) -> bool:
  normalized = _normalize(text)
  return any(str(pattern or "").strip().lower() in normalized for pattern in patterns if str(pattern or "").strip())


def _load_spec(path: str) -> Dict[str, Any]:
  raw = Path(path).read_text(encoding="utf-8")
  data = json.loads(raw)
  if not isinstance(data, dict):
    raise RuntimeError("Spec file must contain a top-level JSON object.")
  return data


def _write_template(path: str) -> None:
  target = Path(path)
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text(json.dumps(TEMPLATE_SPEC, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _spec_section(spec: Dict[str, Any], key: str) -> Dict[str, Any]:
  value = spec.get(key)
  return value if isinstance(value, dict) else {}


def _string_value(value: Any) -> str:
  if value is None:
    return ""
  if isinstance(value, str):
    return value.strip()
  if isinstance(value, (int, float)) and not isinstance(value, bool):
    if abs(float(value) - round(float(value))) < 1e-9:
      return str(int(round(float(value))))
    return str(value)
  return str(value).strip()


@dataclass
class ScriptedBootstrap:
  business_name: str
  business_start_date: str
  address: str
  address_street: str
  address_city: str
  address_state: str
  address_zip: str
  address_country: str


class ScriptedClientAgent:
  def __init__(self, spec: Dict[str, Any]) -> None:
    self.spec = spec
    self.fallback_positions: Dict[str, int] = {}

  def bootstrap(self):
    bootstrap = _spec_section(self.spec, "bootstrap")
    required = [
      "business_name",
      "business_start_date",
      "address",
      "address_street",
      "address_city",
      "address_state",
      "address_zip",
      "address_country",
    ]
    missing = [key for key in required if not _string_value(bootstrap.get(key))]
    if missing:
      raise RuntimeError(f"Spec bootstrap is missing required fields: {', '.join(missing)}")
    try:
      datetime.strptime(_string_value(bootstrap.get("business_start_date")), "%m/%d/%Y")
    except ValueError as exc:
      raise RuntimeError("bootstrap.business_start_date must be MM/DD/YYYY") from exc
    return _SHARED.Bootstrap(
      business_name=_string_value(bootstrap.get("business_name")),
      business_start_date=_string_value(bootstrap.get("business_start_date")),
      address=_string_value(bootstrap.get("address")),
      address_street=_string_value(bootstrap.get("address_street")),
      address_city=_string_value(bootstrap.get("address_city")),
      address_state=_string_value(bootstrap.get("address_state")),
      address_zip=_string_value(bootstrap.get("address_zip")),
      address_country=_string_value(bootstrap.get("address_country")),
      private_state="",
    )

  def _override_answer(self, *, focus: str, assistant_message: str) -> Optional[str]:
    overrides = self.spec.get("overrides")
    if not isinstance(overrides, list):
      return None
    normalized = _normalize(assistant_message)
    for item in overrides:
      if not isinstance(item, dict):
        continue
      item_focus = _normalize(str(item.get("focus") or ""))
      if item_focus and item_focus != _normalize(focus):
        continue
      contains = _normalize(str(item.get("contains") or ""))
      regex = str(item.get("regex") or "").strip()
      if contains and contains not in normalized:
        continue
      if regex:
        try:
          if re.search(regex, assistant_message, flags=re.IGNORECASE) is None:
            continue
        except re.error:
          continue
      answer = _string_value(item.get("answer"))
      if answer:
        return answer
    return None

  def _fallback_answer(self, focus: str) -> Optional[str]:
    fallback = _spec_section(self.spec, "fallback")
    items = fallback.get(focus)
    if not isinstance(items, list):
      return None
    index = self.fallback_positions.get(focus, 0)
    if index >= len(items):
      return None
    self.fallback_positions[focus] = index + 1
    answer = _string_value(items[index])
    return answer or None

  def _ops_product_answer(self, assistant_message: str) -> Optional[str]:
    ops = _spec_section(self.spec, "ops")
    products = ops.get("products")
    if not isinstance(products, list):
      return None
    message = _normalize(assistant_message)
    for product in products:
      if not isinstance(product, dict):
        continue
      names = [_string_value(product.get("product_name"))]
      aliases = product.get("aliases")
      if isinstance(aliases, list):
        names.extend(_string_value(item) for item in aliases)
      names = [name for name in names if name]
      if names and not any(_normalize(name) in message for name in names):
        continue
      if _contains_any(message, ["one unit", "treat one unit", "unit as", "unit definition", "what should we treat one unit"]):
        return _string_value(product.get("unit_definition"))
      if _contains_any(message, ["maximum", "max", "fully booked", "fully busy", "practical max", "practical ceiling", "handle in a week", "handle in a month", "capacity"]):
        return _string_value(product.get("capacity"))
      if _contains_any(message, ["utilization", "year 1", "year-1", "% utilization", "using about", "on average"]):
        answer = _string_value(product.get("utilization"))
        if answer:
          return answer
      if _contains_any(message, ["average price", "single average price", "price per", "what price", "unit price", "typical sale price", "average price per"]):
        return _string_value(product.get("price"))
    return None

  def _answer_ops(self, assistant_message: str) -> Optional[str]:
    ops = _spec_section(self.spec, "ops")
    message = _normalize(assistant_message)
    if _contains_any(message, ["describe in plain language", "what does", "how you expect to get paid", "how it operates", "restatement accurate"]):
      return _string_value(ops.get("business_description")) or _string_value(ops.get("confirmation"))
    if _contains_any(message, ["primarily sell", "individual consumers", "businesses", "mix of both", "customer base"]):
      return _string_value(ops.get("customer_type"))
    if _contains_any(message, ["separate products for planning", "track them as", "three separate offerings", "separate offerings", "separate products"]):
      return _string_value(ops.get("products_confirmed")) or _string_value(ops.get("confirmation"))
    if _contains_any(message, ["legal structure", "legal setup", "sole proprietor", "llc", "s-corp", "c-corp", "partnership", "llp"]):
      return _string_value(ops.get("legal_entity"))
    product_answer = self._ops_product_answer(assistant_message)
    if product_answer:
      return product_answer
    if _contains_any(message, ["delivery method", "receive your services", "receive what they buy", "primary delivery", "travel to the client", "perform the treatment"]):
      return _string_value(ops.get("delivery_method"))
    if _contains_any(message, ["fulfillment model", "does this look right", "that is how fulfillment", "main operational constraint", "main constraint"]):
      return _string_value(ops.get("fulfillment_confirmation")) or _string_value(ops.get("confirmation"))
    if _contains_any(message, ["sales channel", "book online", "phone inquiries", "online booking", "mixed model"]):
      return _string_value(ops.get("sales_channel"))
    if _contains_any(message, ["geographic footprint", "area you serve", "service area", "local service area", "main area you serve", "geographic side"]):
      return _string_value(ops.get("geography"))
    if _contains_any(message, ["growth lever", "primary growth lever", "main operational growth lever", "what is one primary lever"]):
      return _string_value(ops.get("growth_lever"))
    if _contains_any(message, ["competitive advantage", "what truly sets the business apart", "sets the business apart"]):
      return _string_value(ops.get("competitive_advantage"))
    if _contains_any(message, ["next 12 months", "concrete goal", "looking ahead", "goal you want to hit"]):
      return _string_value(ops.get("goal_12_months"))
    if _contains_any(message, ["is this accurate", "does this description", "does this look right", "are we aligned", "works for planning purposes"]):
      return _string_value(ops.get("confirmation")) or "Yes, that's correct."
    return None

  def _answer_market(self, assistant_message: str) -> Optional[str]:
    market = _spec_section(self.spec, "market")
    message = _normalize(assistant_message)
    if _contains_any(message, ["women, men, or keep it open", "all genders", "target market open to all genders", "focus on women", "focus on men"]):
      return _string_value(market.get("gender"))
    if _contains_any(message, ["age range", "focused on", "ideal clients", "mid-20s", "25 to 50"]):
      return _string_value(market.get("age_range"))
    if _contains_any(message, ["household income", "income range", "$60k", "$75k", "income preference"]):
      return _string_value(market.get("income_range"))
    if _contains_any(message, ["education", "highest level of education", "college-educated", "education focus"]):
      return _string_value(market.get("education"))
    if _contains_any(message, ["household structure", "employment", "housing economics", "would you like to add", "keep the target broad"]):
      return _string_value(market.get("profile_detail_choice")) or _string_value(market.get("confirmation"))
    if _contains_any(message, ["office-based", "remote/hybrid", "equally core targets", "employment"]):
      return _string_value(market.get("employment_mix"))
    if _contains_any(message, ["does this look right", "before we move on", "ready to move on to human resources"]):
      return _string_value(market.get("confirmation")) or "Yes, that looks right."
    return None

  def _answer_people(self, assistant_message: str) -> Optional[str]:
    people = _spec_section(self.spec, "people")
    message = _normalize(assistant_message)
    if _contains_any(message, ["full name", "current title", "years of relevant experience", "education credentials", "licenses"]):
      return _string_value(people.get("owner_background"))
    if _contains_any(message, ["another key person", "only key person", "meaningfully involved today", "medical director", "part-time clinician"]):
      return _string_value(people.get("other_key_people"))
    if _contains_any(message, ["review this draft", "does this look right before we move on", "suggested year-1 roles"]):
      return _string_value(people.get("confirmation")) or "Yes, that looks right."
    return None

  def _answer_financials(self, assistant_message: str) -> Optional[str]:
    financials = _spec_section(self.spec, "financials")
    message = _normalize(assistant_message)
    if _contains_any(message, ["year 1 revenue setup", "year-1 revenue setup", "do you want to keep this year", "adjust any of these levers"]):
      return _string_value(financials.get("revenue_setup")) or _string_value(financials.get("confirmation"))
    if _contains_any(message, ["cogs baseline", "direct costs", "projected year-1 direct costs", "does that broadly match how your business works"]):
      return _string_value(financials.get("cogs")) or _string_value(financials.get("confirmation"))
    if _contains_any(message, ["year-1 payroll", "payroll baseline", "payroll expectation", "actual payroll setup"]):
      return _string_value(financials.get("payroll")) or _string_value(financials.get("confirmation"))
    if _contains_any(message, ["current annual compensation", "start paying yourself", "start paying each of the three planned roles", "recompute a more accurate year", "month or quarter"]):
      return _string_value(financials.get("payroll_detail"))
    field_map = [
      (["monthly rent", "rent expense"], "monthly_rent_expense"),
      (["other operating expense", "other opex"], "other_operating_expense"),
      (["other monthly debt payments"], "other_monthly_debt_payments"),
      (["cash on hand"], "cash_on_hand"),
      (["accounts receivable", "ar balance"], "ar_balance"),
      (["accounts payable", "ap balance"], "ap_balance"),
      (["inventory balance", "inventory"], "inventory_balance"),
      (["capex", "capital expenditures"], "current_capex"),
      (["initial assets"], "initial_assets"),
      (["initial lease", "lease payment", "leased equipment"], "initial_lease"),
      (["initial equity"], "initial_equity"),
      (["total debt outstanding", "outstanding debt"], "total_debt_outstanding"),
      (["annual interest payment", "interest payment"], "annual_interest_payment"),
      (["annual principal payment", "principal payment"], "annual_principal_payment"),
      (["owner compensation"], "owner_compensation"),
    ]
    for keywords, key in field_map:
      if _contains_any(message, keywords):
        return _string_value(financials.get(key))
    if _contains_any(message, ["does that broadly match", "is that accurate", "does this work", "keep these numbers as is"]):
      return _string_value(financials.get("confirmation")) or "Yes, that's right."
    return None

  def _answer_consistency(self, assistant_message: str) -> Optional[str]:
    consistency = _spec_section(self.spec, "consistency")
    if _string_value(consistency.get("confirmation")):
      return _string_value(consistency.get("confirmation"))
    return None

  def answer(
    self,
    *,
    active_focus: str,
    assistant_message: str,
    transcript_tail: List[Dict[str, str]],
  ) -> str:
    del transcript_tail
    override = self._override_answer(focus=active_focus, assistant_message=assistant_message)
    if override:
      return override
    dispatch = {
      "ops": self._answer_ops,
      "market": self._answer_market,
      "people": self._answer_people,
      "financials": self._answer_financials,
      "consistency": self._answer_consistency,
    }
    answer = None
    fn = dispatch.get(_normalize(active_focus))
    if fn:
      answer = fn(assistant_message)
    if answer:
      return answer
    fallback = self._fallback_answer(_normalize(active_focus))
    if fallback:
      return fallback
    return "Yes, that's correct."


def _print_transcript_tail(transcript: List[Dict[str, str]], count: int = 10) -> None:
  print("\nLast transcript turns:")
  for item in transcript[-count:]:
    role = item.get("role", "?")
    content = str(item.get("content") or "").strip()
    print(f"[{role}] {content}")


def _run_spec(
  *,
  spec_path: str,
  spec: Optional[Dict[str, Any]],
  base_url: str,
  max_turns: int,
  output_dir: str,
  persisted_output_dir: str,
) -> int:
  loaded_spec = spec if isinstance(spec, dict) else _load_spec(spec_path)
  agent = ScriptedClientAgent(loaded_spec)
  transcript: List[Dict[str, str]] = []
  bootstrap = None
  draft_id: Optional[str] = None
  client_id: Optional[str] = None
  run_id = uuid.uuid4().hex
  run_started_at = _SHARED._eastern_now()
  trace_file_name: Optional[str] = None
  run_started_perf = time.perf_counter()
  metrics = _SHARED._SimulatorMetricsStore()
  metrics.create_run(
    run_id=run_id,
    seed=str(Path(spec_path).stem if spec_path and spec_path != "<inline_scenario>" else "controlled_intake"),
    model_name="scripted",
    base_url=base_url,
    output_dir=output_dir,
    started_at=run_started_at,
  )

  def _persist_report(*, status: str, stop_reason: str) -> None:
    written_at = _SHARED._eastern_now()
    artifact_seed = _SHARED._artifact_seed(
      seed=str(Path(spec_path).stem if spec_path and spec_path != "<inline_scenario>" else "controlled_intake"),
      draft_id=draft_id,
    )
    path = _SHARED._save_run_report(
      output_dir=output_dir,
      seed=artifact_seed,
      bootstrap=bootstrap,
      transcript=transcript,
      draft_id=draft_id,
      status=status,
      stop_reason=stop_reason,
      written_at=written_at,
    )
    if path:
      print(f"Saved run report: {path}")
    persisted_path = _SHARED._save_persisted_state_report(
      base_url=base_url,
      output_dir=persisted_output_dir,
      seed=artifact_seed,
      bootstrap=bootstrap,
      draft_id=draft_id,
      client_id=client_id,
      status=status,
      stop_reason=stop_reason,
      written_at=written_at,
    )
    if persisted_path:
      print(f"Saved persisted state report: {persisted_path}")
    new_runner_path = _SHARED._save_new_runner_report(
      base_url=base_url,
      output_dir=_SHARED.DEFAULT_NEW_RUNNER_DIR,
      seed=artifact_seed,
      bootstrap=bootstrap,
      draft_id=draft_id,
      written_at=written_at,
    )
    if new_runner_path:
      print(f"Saved New Runner report: {new_runner_path}")
    new_runner_grid_path = _SHARED._save_new_runner_grid_report(
      base_url=base_url,
      output_dir=_SHARED.DEFAULT_NEW_RUNNER_DIR,
      seed=artifact_seed,
      draft_id=draft_id,
      written_at=written_at,
    )
    if new_runner_grid_path:
      print(f"Saved New Runner grid report: {new_runner_grid_path}")
    new_runner_solver_path = _SHARED._save_new_runner_solver_report(
      base_url=base_url,
      output_dir=_SHARED.DEFAULT_NEW_RUNNER_DIR,
      seed=artifact_seed,
      draft_id=draft_id,
      written_at=written_at,
    )
    if new_runner_solver_path:
      print(f"Saved New Runner solver report: {new_runner_solver_path}")
    if trace_file_name:
      print(f"Expected terminal log file: {os.path.join(_SHARED.DEFAULT_TERMINAL_LOGS_DIR, trace_file_name)}")

  def _finish_metrics(*, status: str, stop_reason: str, total_turns: int) -> None:
    metrics.finish_run(
      run_id=run_id,
      ended_at=_SHARED._eastern_now(),
      total_duration_ms=int(round((time.perf_counter() - run_started_perf) * 1000.0)),
      total_turns=total_turns,
      status=status,
      stop_reason=stop_reason,
    )
    metrics.close()

  try:
    bootstrap = agent.bootstrap()
    metrics.update_run_bootstrap(
      run_id=run_id,
      business_name=bootstrap.business_name,
      business_start_date=bootstrap.business_start_date,
      business_address=bootstrap.address,
    )
    print(f"Bootstrapped business: {bootstrap.business_name}")

    started = time.perf_counter()
    session = _SHARED._post_json(f"{base_url}/api/intake-consult/session", {})
    session_create_ms = int(round((time.perf_counter() - started) * 1000.0))
    draft_id = session.get("draft_id")
    client_id = session.get("client_id")
    if not draft_id:
      raise RuntimeError(f"Failed to create draft session: {session}")
    trace_file_name = _SHARED._build_run_artifact_filename(
      seed=_SHARED._artifact_seed(
        seed=str(Path(spec_path).stem if spec_path and spec_path != "<inline_scenario>" else "controlled_intake"),
        draft_id=draft_id,
      ),
      written_at=run_started_at,
    )

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
    trace_headers = {
      "X-Solver-Trace-Run-Name": trace_file_name,
      "X-Solver-Trace-Reset": "1",
    }
    started = time.perf_counter()
    response = _SHARED._post_json(f"{base_url}/api/intake-consult", seed_payload, headers=trace_headers)
    initial_app_response_ms = int(round((time.perf_counter() - started) * 1000.0))
    metrics.update_run_session(
      run_id=run_id,
      draft_id=draft_id,
      client_id=client_id,
      session_create_ms=session_create_ms,
      initial_app_response_ms=initial_app_response_ms,
    )

    for turn_index in range(max_turns):
      turn_started_at = _SHARED._eastern_now()
      draft_fetch_started = time.perf_counter()
      draft_snapshot = _SHARED._get_json(f"{base_url}/api/intake-consult/draft", {"draft_id": draft_id})
      draft_fetch_ms = int(round((time.perf_counter() - draft_fetch_started) * 1000.0))
      assistant_message = _SHARED._render_fact_placeholders(
        str(response.get("assistant_message") or "").strip(),
        draft_snapshot,
      ).strip()
      active_focus = str(response.get("active_focus") or "").strip().lower()
      transcript.append({"role": "assistant", "content": assistant_message, "focus": active_focus})
      print(f"\n[{active_focus or 'unknown'}][assistant] {assistant_message}")

      if response.get("done"):
        print("\nSimulation completed.")
        system_run_started = time.perf_counter()
        system_run_response = _SHARED._post_json(
          f"{base_url}/api/intake-consult/system-run",
          {"draft_id": draft_id, "client_id": client_id},
          timeout=None,
          headers=trace_headers,
        )
        system_run_ms = int(round((time.perf_counter() - system_run_started) * 1000.0))
        system_message = str(system_run_response.get("assistant_message") or "").strip() or "System run complete."
        transcript.append({"role": "assistant", "content": system_message, "focus": "system"})
        print(system_message)
        draft = _SHARED._get_json(f"{base_url}/api/intake-consult/draft", {"draft_id": draft_id})
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
        metrics.insert_turn(
          run_id=run_id,
          turn_index=turn_index,
          focus=active_focus,
          turn_started_at=turn_started_at,
          draft_fetch_ms=draft_fetch_ms,
          client_answer_ms=None,
          app_response_ms=system_run_ms,
          assistant_chars=len(assistant_message),
          user_chars=0,
          stop_flag=True,
          stop_reason="system run complete",
        )
        _finish_metrics(status="completed", stop_reason="system run complete", total_turns=turn_index + 1)
        _persist_report(status="completed", stop_reason="system run complete")
        return 0

      failure = _SHARED._detect_failure(
        transcript=transcript,
        assistant_message=assistant_message,
        active_focus=active_focus,
        turn_index=turn_index,
        max_turns=max_turns,
      )
      if failure:
        print(f"\nSTOP: {failure}")
        print(f"Draft ID: {draft_id}")
        _print_transcript_tail(transcript)
        metrics.insert_turn(
          run_id=run_id,
          turn_index=turn_index,
          focus=active_focus,
          turn_started_at=turn_started_at,
          draft_fetch_ms=draft_fetch_ms,
          client_answer_ms=None,
          app_response_ms=None,
          assistant_chars=len(assistant_message),
          user_chars=0,
          stop_flag=True,
          stop_reason=failure,
        )
        _finish_metrics(status="stopped", stop_reason=failure, total_turns=turn_index + 1)
        _persist_report(status="stopped", stop_reason=failure)
        return 1

      client_answer_started = time.perf_counter()
      reply = agent.answer(
        active_focus=active_focus,
        assistant_message=assistant_message,
        transcript_tail=transcript,
      )
      client_answer_ms = int(round((time.perf_counter() - client_answer_started) * 1000.0))
      transcript.append({"role": "user", "content": reply, "focus": active_focus})
      print(f"[user] {reply}")

      app_response_started = time.perf_counter()
      response = _SHARED._post_json(
        f"{base_url}/api/intake-consult",
        {"draft_id": draft_id, "client_id": client_id, "message": reply},
        headers=trace_headers,
      )
      app_response_ms = int(round((time.perf_counter() - app_response_started) * 1000.0))
      metrics.insert_turn(
        run_id=run_id,
        turn_index=turn_index,
        focus=active_focus,
        turn_started_at=turn_started_at,
        draft_fetch_ms=draft_fetch_ms,
        client_answer_ms=client_answer_ms,
        app_response_ms=app_response_ms,
        assistant_chars=len(assistant_message),
        user_chars=len(reply),
        stop_flag=False,
        stop_reason="",
      )

    print(f"\nSTOP: max turns reached ({max_turns})")
    print(f"Draft ID: {draft_id}")
    _print_transcript_tail(transcript)
    _finish_metrics(status="stopped", stop_reason=f"max turns reached ({max_turns})", total_turns=max_turns)
    _persist_report(status="stopped", stop_reason=f"max turns reached ({max_turns})")
    return 1

  except KeyboardInterrupt:
    print("\nStopped by user.")
    _finish_metrics(status="stopped", stop_reason="stopped by user", total_turns=len([t for t in transcript if t.get("role") == "assistant"]))
    _persist_report(status="stopped", stop_reason="stopped by user")
    return 130
  except Exception as exc:
    print(f"\nSTOP: runner error: {type(exc).__name__}: {exc}")
    _print_transcript_tail(transcript)
    _finish_metrics(
      status="error",
      stop_reason=f"{type(exc).__name__}: {exc}",
      total_turns=len([t for t in transcript if t.get('role') == 'assistant']),
    )
    _persist_report(status="error", stop_reason=f"{type(exc).__name__}: {exc}")
    return 1


def main() -> int:
  _SHARED._load_env()
  parser = argparse.ArgumentParser(description="Run a scripted intake simulation with exact user-controlled answers.")
  parser.add_argument("--spec", default="", help="Path to a JSON spec file with exact scripted answers.")
  parser.add_argument("--write-template", default="", help="Write a blank/example spec JSON to this path and exit.")
  parser.add_argument("--base-url", default=os.getenv("INTAKE_BASE_URL", "http://127.0.0.1:5050"))
  parser.add_argument("--max-turns", type=int, default=80)
  parser.add_argument("--output-dir", default=_SHARED.DEFAULT_TEST_RUNS_DIR)
  parser.add_argument("--persisted-output-dir", default=_SHARED.DEFAULT_TEST_RUNS_DATA_DIR)
  args = parser.parse_args()

  if args.write_template:
    _write_template(args.write_template)
    print(f"Wrote template: {args.write_template}")
    return 0
  if not str(args.spec or "").strip():
    print("Provide --spec <path> or --write-template <path>.", file=sys.stderr)
    return 2
  return _run_spec(
    spec_path=str(args.spec),
    spec=None,
    base_url=str(args.base_url or "").rstrip("/"),
    max_turns=int(args.max_turns),
    output_dir=str(args.output_dir),
    persisted_output_dir=str(args.persisted_output_dir),
  )


if __name__ == "__main__":
  raise SystemExit(main())
