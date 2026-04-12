import argparse
import importlib.util
import json
import os
import sys
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


THIS_DIR = Path(__file__).resolve().parent
DUAL_RUNNER_PATH = THIS_DIR / "run_dual_agent_intake.py"
ARGS_RUNNER_PATH = THIS_DIR / "run_args_intake.py"


def _load_module(path: Path, name: str):
  spec = importlib.util.spec_from_file_location(name, str(path))
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load module from {path}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


_DUAL = _load_module(DUAL_RUNNER_PATH, "run_dual_agent_intake_live_args")
_ARGS = _load_module(ARGS_RUNNER_PATH, "run_args_intake_live_args")


def _normalize(text: Any) -> str:
  return " ".join(str(text or "").strip().lower().split())


def _contains_any(text: Any, patterns: List[str]) -> bool:
  normalized = _normalize(text)
  return any(_normalize(item) in normalized for item in patterns if _normalize(item))


def _string(value: Any) -> str:
  return str(value or "").strip()


def _product_display_summary(product: Dict[str, Any]) -> str:
  name = _string(product.get("product_name")) or "Product"
  unit_definition = _string(product.get("unit_definition"))
  capacity = _string(product.get("capacity"))
  utilization = _string(product.get("utilization"))
  price = _string(product.get("price"))
  parts = [name]
  if unit_definition:
    parts.append(unit_definition)
  if capacity:
    parts.append(f"capacity {capacity}")
  if utilization:
    parts.append(f"utilization {utilization}")
  if price:
    parts.append(f"price {price}")
  return "; ".join(parts)


class LiveControlledAgent:
  def __init__(self, *, spec: Dict[str, Any], seed: str, model: str) -> None:
    self.spec = spec
    self.seed = _string(seed)
    self.model = _string(model)
    self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
    self.ops_state: Dict[str, int] = {}
    self.market_state: Dict[str, int] = {}
    self.people_state: Dict[str, int] = {}
    self.fin_state: Dict[str, int] = {}
    self.private_state = ""
    self.exact_facts = self._build_exact_facts()
    self.exact_facts_json = json.dumps(self.exact_facts, ensure_ascii=False)

  def bootstrap(self):
    bootstrap = self.spec["bootstrap"]
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
    missing = [key for key in required if not _string(bootstrap.get(key))]
    if missing:
      raise RuntimeError(f"bootstrap is missing required fields: {', '.join(missing)}")
    return _DUAL.Bootstrap(
      business_name=_string(bootstrap.get("business_name")),
      business_start_date=_string(bootstrap.get("business_start_date")),
      address=_string(bootstrap.get("address")),
      address_street=_string(bootstrap.get("address_street")),
      address_city=_string(bootstrap.get("address_city")),
      address_state=_string(bootstrap.get("address_state")),
      address_zip=_string(bootstrap.get("address_zip")),
      address_country=_string(bootstrap.get("address_country")),
      private_state=self.private_state,
    )

  def _build_exact_facts(self) -> Dict[str, Any]:
    operating_model = {}
    target_market = {}
    people_json = {}
    financials_json = {}
    try:
      operating_model = _ARGS._build_operating_model(self.spec)
    except Exception:
      operating_model = {}
    try:
      target_market = _ARGS._build_target_market(self.spec, operating_model or {})
    except Exception:
      target_market = {}
    try:
      people_json = _ARGS._build_people_json(self.spec)
    except Exception:
      people_json = {}
    try:
      financials_json = _ARGS._build_financials_json(self.spec)
    except Exception:
      financials_json = {}
    return {
      "bootstrap": self.spec.get("bootstrap") if isinstance(self.spec.get("bootstrap"), dict) else {},
      "ops": self.spec.get("ops") if isinstance(self.spec.get("ops"), dict) else {},
      "market": self.spec.get("market") if isinstance(self.spec.get("market"), dict) else {},
      "people": self.spec.get("people") if isinstance(self.spec.get("people"), dict) else {},
      "financials": self.spec.get("financials") if isinstance(self.spec.get("financials"), dict) else {},
      "operating_model_projection": operating_model,
      "target_market_projection": target_market,
      "people_projection": people_json,
      "financials_projection": financials_json,
    }

  def _ops(self) -> Dict[str, Any]:
    return self.spec.get("ops") if isinstance(self.spec.get("ops"), dict) else {}

  def _products(self) -> List[Dict[str, Any]]:
    ops = self._ops()
    products = ops.get("products")
    return [item for item in products if isinstance(item, dict)] if isinstance(products, list) else []

  def _market(self) -> Dict[str, Any]:
    return self.spec.get("market") if isinstance(self.spec.get("market"), dict) else {}

  def _people(self) -> Dict[str, Any]:
    return self.spec.get("people") if isinstance(self.spec.get("people"), dict) else {}

  def _financials(self) -> Dict[str, Any]:
    return self.spec.get("financials") if isinstance(self.spec.get("financials"), dict) else {}

  def _product_for_message(self, assistant_message: str) -> Optional[Dict[str, Any]]:
    message = _normalize(assistant_message)
    products = self._products()
    if not products:
      return None
    for product in products:
      names = [_string(product.get("product_name"))]
      aliases = product.get("aliases")
      if isinstance(aliases, list):
        names.extend(_string(item) for item in aliases)
      normalized_names = [_normalize(name) for name in names if _normalize(name)]
      if normalized_names and any(name in message for name in normalized_names):
        return product
    return None

  def _multi_product_correction(self, assistant_message: str) -> Optional[str]:
    products = self._products()
    if len(products) <= 1:
      return None
    message = _normalize(assistant_message)
    if not _contains_any(message, ["is this description", "does this description", "does this look right", "is that accurate"]):
      return None
    names = [_normalize(item.get("product_name")) for item in products if _normalize(item.get("product_name"))]
    matched_count = sum(1 for name in names if name in message)
    if matched_count >= len(names):
      return None
    product_lines = " | ".join(_product_display_summary(item) for item in products)
    return (
      "Not quite. Treat these as separate products for planning and do not collapse them: "
      f"{product_lines}."
    )

  def _answer_ops(self, assistant_message: str) -> str:
    ops = self._ops()
    message = _normalize(assistant_message)

    correction = self._multi_product_correction(assistant_message)
    if correction:
      return correction

    if _contains_any(message, ["describe in plain language", "what does", "to get us started", "how you expect to get paid"]):
      return _string(ops.get("business_description")) or _string(ops.get("confirmation")) or "Yes, that's correct."
    if _contains_any(message, ["is this description", "does this description", "does this look right", "is that accurate", "baseline works well for planning"]):
      return _string(ops.get("confirmation")) or "Yes, that's correct."
    if _contains_any(message, ["legal structure", "legal setup", "legal entity", "sole proprietor", "llc", "partnership", "s-corp", "c-corp", "llp"]):
      return _string(ops.get("legal_entity"))
    if _contains_any(message, ["who do you primarily sell to", "who are you mainly selling to", "individual consumers", "businesses", "mix of both", "customer base"]):
      return _string(ops.get("customer_type"))
    if _contains_any(message, ["separate products", "separate offerings", "track those as separate products", "modeled as separate products"]):
      return _string(ops.get("products_confirmed")) or _string(ops.get("confirmation")) or "Yes, track those as separate products."
    product = self._product_for_message(assistant_message)
    if product is not None:
      if _contains_any(message, ["one unit", "treat one unit", "unit as", "unit definition", "core unit", "what single unit"]):
        return _string(product.get("unit_definition"))
      if _contains_any(message, ["maximum", "max", "fully booked", "fully busy", "practical max", "practical ceiling", "could you realistically handle", "capacity"]):
        return _string(product.get("capacity"))
      if _contains_any(message, ["utilization", "year 1", "year-1", "on average", "roughly", "% utilization"]):
        return _string(product.get("utilization"))
      if _contains_any(message, ["average price", "single average price", "price per", "what price", "unit price", "typical sale price", "monthly price", "charge per"]):
        return _string(product.get("price"))
    if _contains_any(message, ["delivery method", "receive your services", "receive what they buy", "primary delivery", "travel to the client", "perform the treatment", "performed in person"]):
      return _string(ops.get("delivery_method"))
    if _contains_any(message, ["fulfillment model", "fulfillment typically works", "main operational constraint", "does this look right", "that is how fulfillment"]):
      return _string(ops.get("fulfillment_confirmation")) or _string(ops.get("confirmation")) or "Yes, that's accurate."
    if _contains_any(message, ["sales channel", "book online", "phone inquiries", "online booking", "how do customers find", "sales come from"]):
      return _string(ops.get("sales_channel")) or _string(ops.get("confirmation")) or "Yes, that's correct."
    if _contains_any(message, ["geographic side", "local service area", "service area", "main local service area", "area you serve", "geographic footprint"]):
      return _string(ops.get("geography"))
    if _contains_any(message, ["primary lever", "growth lever", "main growth lever", "primary lever to increase revenue"]):
      return _string(ops.get("growth_lever"))
    if _contains_any(message, ["competitive advantage", "sets the business apart", "what truly sets the business apart"]):
      return _string(ops.get("competitive_advantage"))
    if _contains_any(message, ["next 12 months", "concrete goal", "goal you want to hit", "looking ahead"]):
      return _string(ops.get("goal_12_months"))
    return _string(ops.get("confirmation")) or "Yes, that's correct."

  def _answer_market(self, assistant_message: str) -> str:
    market = self._market()
    message = _normalize(assistant_message)
    if _contains_any(message, ["gender", "all genders", "women, men", "target market open to all genders"]):
      return _string(market.get("gender")) or _string(market.get("confirmation")) or "Keep it open to all genders."
    if _contains_any(message, ["age range", "age", "focused on", "ideal clients"]):
      return _string(market.get("age_range")) or _string(market.get("confirmation")) or "Adults aged 25 to 55."
    if _contains_any(message, ["income range", "household income", "income"]):
      return _string(market.get("income_range")) or _string(market.get("confirmation")) or "Household income of 60000 and above."
    if _contains_any(message, ["education", "highest level of education"]):
      return _string(market.get("education")) or _string(market.get("confirmation")) or "No strict education preference."
    if _contains_any(message, ["household structure", "housing", "profile detail", "keep the target broad", "would you like to add"]):
      return _string(market.get("profile_detail_choice")) or _string(market.get("confirmation")) or "Keep household and housing broad for now."
    if _contains_any(message, ["employment", "office-based", "remote", "hybrid", "equally core targets"]):
      return _string(market.get("employment_mix")) or _string(market.get("confirmation")) or "A mix of professionals and business owners."
    return _string(market.get("confirmation")) or "Yes, that looks right."

  def _answer_people(self, assistant_message: str) -> str:
    people = self._people()
    message = _normalize(assistant_message)
    if _contains_any(message, ["full name", "current title", "years of relevant experience", "education credentials", "licenses"]):
      return _string(people.get("owner_background"))
    if _contains_any(message, ["another key person", "anyone else", "other key people", "meaningfully involved today", "medical director", "part-time clinician"]):
      return _string(people.get("other_key_people"))
    return _string(people.get("confirmation")) or "Yes, that looks right."

  def _answer_financials(self, assistant_message: str) -> str:
    fin = self._financials()
    message = _normalize(assistant_message)
    field_map = [
      (["year 1 revenue setup", "year-1 revenue setup", "revenue setup"], "revenue_setup"),
      (["cogs baseline", "direct costs", "projected year-1 direct costs"], "cogs"),
      (["year-1 payroll", "payroll baseline", "payroll expectation", "actual payroll setup"], "payroll"),
      (["current annual compensation", "recompute a more accurate year", "start paying yourself"], "payroll_detail"),
      (["monthly rent", "rent expense"], "monthly_rent_expense"),
      (["other operating expense", "other opex"], "other_operating_expense"),
      (["other monthly debt payments"], "other_monthly_debt_payments"),
      (["cash on hand"], "cash_on_hand"),
      (["accounts receivable", "ar balance"], "ar_balance"),
      (["accounts payable", "ap balance"], "ap_balance"),
      (["inventory balance", "inventory"], "inventory_balance"),
      (["capex", "capital expenditures"], "current_capex"),
      (["initial assets"], "initial_assets"),
      (["initial lease", "lease commitment", "lease payment", "leased equipment"], "initial_lease"),
      (["initial equity"], "initial_equity"),
      (["total debt outstanding", "outstanding debt"], "total_debt_outstanding"),
      (["annual interest payment", "interest payment"], "annual_interest_payment"),
      (["annual principal payment", "principal payment"], "annual_principal_payment"),
      (["owner compensation"], "owner_compensation"),
    ]
    for keywords, key in field_map:
      if _contains_any(message, keywords):
        return _string(fin.get(key)) or _string(fin.get("confirmation")) or "Yes, that's right."
    return _string(fin.get("confirmation")) or "Yes, that's right."

  def _preferred_answer(
    self,
    *,
    active_focus: str,
    assistant_message: str,
  ) -> str:
    focus = _normalize(active_focus)
    if focus == "ops":
      return self._answer_ops(assistant_message)
    if focus == "market":
      return self._answer_market(assistant_message)
    if focus == "people":
      return self._answer_people(assistant_message)
    if focus == "financials":
      return self._answer_financials(assistant_message)
    return "Yes, that's correct."

  def answer(
    self,
    *,
    active_focus: str,
    assistant_message: str,
    transcript_tail: List[Dict[str, str]],
    draft_snapshot: Dict[str, Any],
  ) -> str:
    preferred = self._preferred_answer(active_focus=active_focus, assistant_message=assistant_message)
    if not self.api_key:
      return preferred

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
      You are simulating a real business owner going through a live business-plan intake chat.

      Your job is to answer naturally and intelligently, like the original intake simulator, while obeying the
      exact configured facts supplied to you. Those configured facts are authoritative constraints.

      Rules:
      - Stay consistent with the configured facts and the hidden private state.
      - If the consultant asks about a configured fact, answer with that fact or briefly agree with an equivalent proposal.
      - Never substitute one field for another. Do not answer age when asked income, price when asked capacity, etc.
      - Keep separate products separate. If the consultant collapses distinct configured products, correct that briefly.
      - Be concise and human. Do not sound robotic or list-like unless the consultant clearly asks for a list.
      - If the consultant repeats a question you already answered, respond like a real user would.
      - If the consultant asks about something not explicitly configured, answer reasonably from the seed, transcript, and prior committed facts.
      - Do not mention hidden state, configured facts JSON, or that you are a simulation.

      Return ONLY JSON matching the schema.
      updated_private_state should stay compact and only capture clarified facts or choices made during the chat.
      """
    ).strip()
    transcript_blob = json.dumps(transcript_tail[-12:], ensure_ascii=False)
    draft_context = {
      "active_focus": draft_snapshot.get("active_focus"),
      "current_field_key": draft_snapshot.get("current_field_key"),
      "current_model_key": draft_snapshot.get("current_model_key"),
    }
    user = (
      f"Seed: {self.seed}\n"
      f"Current focus: {active_focus}\n"
      f"Hidden private state:\n{self.private_state}\n\n"
      "Authoritative configured facts JSON:\n"
      f"{self.exact_facts_json}\n\n"
      "Current draft context JSON:\n"
      f"{json.dumps(draft_context, ensure_ascii=False)}\n\n"
      "Recent transcript tail (JSON):\n"
      f"{transcript_blob}\n\n"
      "Latest consultant message:\n"
      f"{assistant_message}\n\n"
      "Preferred exact answer if directly applicable:\n"
      f"{preferred}\n"
    )
    try:
      obj = _DUAL._openai_call(
        api_key=self.api_key,
        model=self.model,
        schema_name="intake_live_args_turn",
        schema=schema,
        messages=[
          {"role": "system", "content": system},
          {"role": "user", "content": user},
        ],
      )
      self.private_state = str(obj.get("updated_private_state") or "").strip() or self.private_state
      answer = str(obj.get("answer") or "").strip()
      return answer or preferred
    except Exception:
      return preferred


def _run_live_spec(
  *,
  spec: Dict[str, Any],
  seed: str,
  base_url: str,
  model: str,
  max_turns: int,
  output_dir: str,
  persisted_output_dir: str,
) -> int:
  agent = LiveControlledAgent(spec=spec, seed=seed, model=model)
  transcript: List[Dict[str, str]] = []
  bootstrap = None
  draft_id: Optional[str] = None
  client_id: Optional[str] = None
  run_id = uuid.uuid4().hex
  run_started_at = _DUAL._eastern_now()
  trace_file_name: Optional[str] = None
  run_started_perf = time.perf_counter()
  metrics = _DUAL._SimulatorMetricsStore()
  metrics.create_run(
    run_id=run_id,
    seed=seed,
    model_name=model,
    base_url=base_url,
    output_dir=output_dir,
    started_at=run_started_at,
  )

  def _persist_report(*, status: str, stop_reason: str) -> None:
    written_at = _DUAL._eastern_now()
    artifact_seed = _DUAL._artifact_seed(seed=seed, draft_id=draft_id)
    path = _DUAL._save_run_report(
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
    persisted_path = _DUAL._save_persisted_state_report(
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
    new_runner_path = _DUAL._save_new_runner_report(
      base_url=base_url,
      output_dir=_DUAL.DEFAULT_NEW_RUNNER_DIR,
      seed=artifact_seed,
      bootstrap=bootstrap,
      draft_id=draft_id,
      written_at=written_at,
    )
    if new_runner_path:
      print(f"Saved New Runner report: {new_runner_path}")
    new_runner_grid_path = _DUAL._save_new_runner_grid_report(
      base_url=base_url,
      output_dir=_DUAL.DEFAULT_NEW_RUNNER_DIR,
      seed=artifact_seed,
      draft_id=draft_id,
      written_at=written_at,
    )
    if new_runner_grid_path:
      print(f"Saved New Runner grid report: {new_runner_grid_path}")
    if trace_file_name:
      print(f"Expected terminal log file: {os.path.join(_DUAL.DEFAULT_TERMINAL_LOGS_DIR, trace_file_name)}")

  def _finish_metrics(*, status: str, stop_reason: str, total_turns: int) -> None:
    metrics.finish_run(
      run_id=run_id,
      ended_at=_DUAL._eastern_now(),
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
    session = _DUAL._post_json(f"{base_url}/api/intake-consult/session", {})
    session_create_ms = int(round((time.perf_counter() - started) * 1000.0))
    draft_id = session.get("draft_id")
    client_id = session.get("client_id")
    if not draft_id:
      raise RuntimeError(f"Failed to create draft session: {session}")
    trace_file_name = _DUAL._build_run_artifact_filename(
      seed=_DUAL._artifact_seed(seed=seed, draft_id=draft_id),
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
      "X-Planning-Trace-Run-Name": trace_file_name,
      "X-Planning-Trace-Reset": "1",
    }
    started = time.perf_counter()
    response = _DUAL._post_json(f"{base_url}/api/intake-consult", seed_payload, headers=trace_headers)
    initial_app_response_ms = int(round((time.perf_counter() - started) * 1000.0))
    metrics.update_run_session(
      run_id=run_id,
      draft_id=draft_id,
      client_id=client_id,
      session_create_ms=session_create_ms,
      initial_app_response_ms=initial_app_response_ms,
    )

    for turn_index in range(max_turns):
      turn_started_at = _DUAL._eastern_now()
      draft_fetch_started = time.perf_counter()
      draft_snapshot = _DUAL._get_json(f"{base_url}/api/intake-consult/draft", {"draft_id": draft_id})
      draft_fetch_ms = int(round((time.perf_counter() - draft_fetch_started) * 1000.0))
      assistant_message = _DUAL._render_fact_placeholders(
        str(response.get("assistant_message") or "").strip(),
        draft_snapshot,
      ).strip()
      active_focus = str(response.get("active_focus") or "").strip().lower()
      transcript.append({"role": "assistant", "content": assistant_message, "focus": active_focus})
      print(f"\n[{active_focus or 'unknown'}][assistant] {assistant_message}")

      if response.get("done"):
        print("\nSimulation completed.")
        system_run_started = time.perf_counter()
        system_run_response = _DUAL._post_json(
          f"{base_url}/api/intake-consult/system-run",
          {"draft_id": draft_id, "client_id": client_id},
          timeout=None,
          headers=trace_headers,
        )
        system_run_ms = int(round((time.perf_counter() - system_run_started) * 1000.0))
        system_message = str(system_run_response.get("assistant_message") or "").strip() or "System run complete."
        transcript.append({"role": "assistant", "content": system_message, "focus": "system"})
        print(system_message)
        draft = _DUAL._get_json(f"{base_url}/api/intake-consult/draft", {"draft_id": draft_id})
        realism_flags = _DUAL._realism_final_flags_from_draft(draft)
        print(
          "Final flags:",
          json.dumps(
            {
              "ops_confirmed": draft.get("ops_confirmed"),
              "market_confirmed": draft.get("market_confirmed"),
              "people_confirmed": draft.get("people_confirmed"),
              "financials_confirmed": draft.get("financials_confirmed"),
              **realism_flags,
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

      failure = _DUAL._detect_failure(
        transcript=transcript,
        assistant_message=assistant_message,
        active_focus=active_focus,
        turn_index=turn_index,
        max_turns=max_turns,
      )
      if failure:
        print(f"\nSTOP: {failure}")
        print(f"Draft ID: {draft_id}")
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
        draft_snapshot=draft_snapshot,
      )
      client_answer_ms = int(round((time.perf_counter() - client_answer_started) * 1000.0))
      transcript.append({"role": "user", "content": reply, "focus": active_focus})
      print(f"[user] {reply}")

      app_response_started = time.perf_counter()
      response = _DUAL._post_json(
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

    stop_reason = f"max turns reached ({max_turns})"
    print(f"\nSTOP: {stop_reason}")
    if draft_id:
      print(f"Draft ID: {draft_id}")
    _finish_metrics(status="stopped", stop_reason=stop_reason, total_turns=max_turns)
    _persist_report(status="stopped", stop_reason=stop_reason)
    return 1
  finally:
    metrics.close()


def main(argv: Optional[List[str]] = None, *, forced_product_count: Optional[int] = None) -> int:
  _DUAL._load_env()
  parser = argparse.ArgumentParser(
    description="Run a live conversational intake simulation with deterministic field answers."
  )
  parser.add_argument("seed", nargs="?", default="", help="Plain-English business seed, same style as run_dual_agent_intake.py")
  parser.add_argument("--base-url", default=os.getenv("INTAKE_BASE_URL", "http://127.0.0.1:5050"))
  parser.add_argument("--model", default=os.getenv("INTAKE_SIM_MODEL", "gpt-4.1-mini"))
  parser.add_argument("--max-turns", type=int, default=80)
  parser.add_argument("--business-start-date", default="")
  parser.add_argument("--output-dir", default=_DUAL.DEFAULT_TEST_RUNS_DIR)
  parser.add_argument("--persisted-output-dir", default=_DUAL.DEFAULT_TEST_RUNS_DATA_DIR)
  parser.add_argument("--set", dest="sets", action="append", default=[], help="Override as key=value. Use --print-keys to see supported keys.")
  parser.add_argument("--answers", default="", help="Single quoted blob of key=value pairs separated by ';;'.")
  parser.add_argument("--print-keys", action="store_true", help="Print supported keys and exit.")
  args = parser.parse_args(argv)

  if args.print_keys:
    print(_ARGS.KEY_HELP)
    return 0
  if not _string(args.seed):
    parser.error("seed is required unless --print-keys is used")

  spec = _ARGS._blank_spec()
  for raw in args.sets:
    key, value = _ARGS._parse_set_arg(raw)
    _ARGS._apply_set(spec, key, value)
  for key, value in _ARGS._parse_answers_blob(args.answers):
    _ARGS._apply_set(spec, key, value)
  if _string(args.business_start_date):
    spec["bootstrap"]["business_start_date"] = _string(args.business_start_date)

  required_bootstrap = (
    "business_name",
    "business_start_date",
    "address",
    "address_street",
    "address_city",
    "address_state",
    "address_zip",
    "address_country",
  )
  missing_bootstrap = [key for key in required_bootstrap if not _string(spec["bootstrap"].get(key))]
  if missing_bootstrap:
    bootstrap_defaults = _ARGS._bootstrap_defaults(
      seed=_string(args.seed),
      model=_string(args.model),
      business_start_date_override=_string(args.business_start_date),
    )
    for key, value in bootstrap_defaults.items():
      if not _string(spec["bootstrap"].get(key)):
        spec["bootstrap"][key] = value

  spec = _ARGS._prune_spec(spec)
  _ARGS._validate_product_count(spec, forced_product_count=forced_product_count)
  return _run_live_spec(
    spec=spec,
    seed=_string(args.seed),
    base_url=_string(args.base_url).rstrip("/"),
    model=_string(args.model),
    max_turns=int(args.max_turns),
    output_dir=_string(args.output_dir),
    persisted_output_dir=_string(args.persisted_output_dir),
  )


if __name__ == "__main__":
  raise SystemExit(main())
