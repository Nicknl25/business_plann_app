import json
import time
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify


def _parse_json_dict(raw: Any) -> Dict[str, Any]:
  if raw is None:
    return {}
  if isinstance(raw, dict):
    return raw
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _parse_json_list(raw: Any) -> List[Any]:
  if raw is None:
    return []
  if isinstance(raw, list):
    return list(raw)
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return []
  return list(parsed) if isinstance(parsed, list) else []


def _as_number(value: Any) -> Optional[float]:
  if value is None:
    return None
  if isinstance(value, (int, float)):
    return float(value)
  raw = str(value).strip().replace(",", "")
  if not raw:
    return None
  try:
    return float(raw)
  except Exception:
    return None


_BUSINESS_TYPE_TO_NAICS_6_CACHE: Dict[str, str] | None = None


def _ensure_business_type_to_naics_cache(*, conn) -> Dict[str, str]:
  global _BUSINESS_TYPE_TO_NAICS_6_CACHE
  if _BUSINESS_TYPE_TO_NAICS_6_CACHE is not None:
    return _BUSINESS_TYPE_TO_NAICS_6_CACHE

  mapping: Dict[str, str] = {}
  cur = conn.cursor()
  try:
    cur.execute(
      "SELECT business_types, naics_6 FROM naics_master WHERE business_types IS NOT NULL AND naics_6 IS NOT NULL"
    )
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass

  for row in rows:
    try:
      business_types_raw, naics_6 = row
    except Exception:
      continue
    if not business_types_raw or not naics_6:
      continue
    naics_6_str = str(naics_6).strip()
    if not naics_6_str:
      continue
    for part in str(business_types_raw).split(","):
      token = str(part).strip()
      if token and token not in mapping:
        mapping[token] = naics_6_str

  _BUSINESS_TYPE_TO_NAICS_6_CACHE = mapping
  return mapping


def _resolve_naics_6(*, conn, business_type: str) -> Optional[str]:
  bt = str(business_type or "").strip()
  if not bt:
    return None
  try:
    mapping = _ensure_business_type_to_naics_cache(conn=conn)
  except Exception:
    return None
  return mapping.get(bt)


def _model_column(model: str) -> Optional[str]:
  norm = str(model or "").strip().lower()
  mapping = {
    "ops_concept": "ops_concept_model_json",
    "fulfillment": "fulfillment_model_json",
    "marketing": "marketing_model_json",
    "pricing": "pricing_model_json",
    "headcount": "headcount_model_json",
    "milestones": "milestones_model_json",
  }
  return mapping.get(norm)


def _focus_for_model(model: str) -> Optional[str]:
  norm = str(model or "").strip().lower()
  if norm in ("marketing", "pricing"):
    return "market"
  if norm in ("headcount",):
    return "people"
  if norm in ("ops_concept", "fulfillment", "milestones"):
    return "ops"
  return None


def _has_nonempty_text(obj: Dict[str, Any], key: str) -> bool:
  try:
    return bool(str((obj or {}).get(key) or "").strip())
  except Exception:
    return False


def _normalize_model_card(card: Dict[str, Any]) -> Dict[str, Any]:
  """
  Backwards compatible:
  - old shape: {drivers: {...}, derived: {...}}
  - new shape: {lobs: [{lob_key, lob_name?, drivers: {...}, derived: {...}, rationale?}, ...]}
  """
  out = dict(card or {})
  lobs = out.get("lobs")
  if isinstance(lobs, list) and all(isinstance(x, dict) for x in lobs):
    # Ensure each lob has required containers.
    fixed = []
    for lob in lobs:
      lob_key = str(lob.get("lob_key") or "company_total").strip() or "company_total"
      fixed.append(
        {
          **lob,
          "lob_key": lob_key,
          "lob_name": str(lob.get("lob_name") or "").strip() or None,
          "drivers": lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {},
          "derived": lob.get("derived") if isinstance(lob.get("derived"), dict) else {},
        }
      )
    out["lobs"] = fixed
    out.pop("drivers", None)
    out.pop("derived", None)
    return _ensure_company_total_lob(out)

  # Promote old fields into a single default LOB.
  drivers = out.get("drivers") if isinstance(out.get("drivers"), dict) else {}
  derived = out.get("derived") if isinstance(out.get("derived"), dict) else {}
  out["lobs"] = [
    {
      "lob_key": "company_total",
      "lob_name": None,
      "drivers": dict(drivers),
      "derived": dict(derived),
    }
  ]
  out.pop("drivers", None)
  out.pop("derived", None)
  return _ensure_company_total_lob(out)


def _ensure_company_total_lob(card: Dict[str, Any]) -> Dict[str, Any]:
  """
  Ensure the system-required, user-invisible "company_total" LOB exists as a stable home
  for shared drivers and optional aggregated derived values.
  """
  out = dict(card or {})
  lobs = out.get("lobs")
  if not isinstance(lobs, list):
    lobs = []
  has_company_total = any(
    isinstance(l, dict) and str(l.get("lob_key") or "").strip() == "company_total" for l in lobs
  )
  if not has_company_total:
    lobs = [
      {"lob_key": "company_total", "lob_name": None, "drivers": {}, "derived": {}},
      *[l for l in lobs if isinstance(l, dict)],
    ]
  out["lobs"] = lobs
  return out


def _get_lob_entry(
  card: Dict[str, Any], *, lob_key: str, lob_name: Optional[str]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  normalized = _ensure_company_total_lob(_normalize_model_card(card))
  lobs = normalized.get("lobs")
  if not isinstance(lobs, list):
    lobs = []
  norm_key = str(lob_key or "company_total").strip() or "company_total"
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    if str(lob.get("lob_key") or "").strip() == norm_key:
      if lob_name and not str(lob.get("lob_name") or "").strip():
        lob["lob_name"] = str(lob_name).strip()
      return normalized, lob

  new_lob = {"lob_key": norm_key, "lob_name": str(lob_name).strip() if lob_name else None, "drivers": {}, "derived": {}}
  lobs.append(new_lob)
  normalized["lobs"] = lobs
  return normalized, new_lob


def _compute_next_focus_from_draft(*, draft: Dict[str, Any]) -> str:
  operating_model = _parse_json_dict(draft.get("operating_model_json"))
  target_market = _parse_json_dict(draft.get("target_market_json"))
  people = _parse_json_dict(draft.get("people_json"))
  financials = _parse_json_dict(draft.get("financials_json"))
  marketing = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("marketing_model_json"))))
  milestones = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("milestones_model_json"))))
  headcount = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(draft.get("headcount_model_json"))))

  def _milestones_ready(card: Dict[str, Any]) -> bool:
    try:
      lobs = card.get("lobs")
      if not isinstance(lobs, list) or not lobs:
        return False
      non_company = [
        lob for lob in lobs if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"
      ]
      requires = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]
      for lob in requires:
        drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
        ms = drivers.get("milestones")
        if not isinstance(ms, dict):
          return False
        val = ms.get("value")
        if not isinstance(val, list) or not any(isinstance(x, dict) and str(x.get("title") or "").strip() for x in val):
          return False
      return True
    except Exception:
      return False

  ops_ready = _has_nonempty_text(operating_model, "business_description_summary") and _milestones_ready(milestones)
  market_summary_ready = _has_nonempty_text(target_market, "target_market_summary")
  marketing_ready = False
  try:
    lobs = marketing.get("lobs")
    if isinstance(lobs, list) and lobs:
      # If the only LOB is company_total, require it.
      non_company = [lob for lob in lobs if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"]
      requires = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]
      marketing_ready = True
      for lob in requires:
        derived = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
        y1 = derived.get("year1_marketing_spend")
        ok = isinstance(y1, dict) and bool(str(y1.get("value") or "").strip())
        if not ok:
          marketing_ready = False
          break
  except Exception:
    marketing_ready = False
  market_ready = market_summary_ready and marketing_ready
  people_ready = _has_nonempty_text(people, "key_people_summary")
  if people_ready:
    try:
      lobs = headcount.get("lobs")
      if not isinstance(lobs, list) or not lobs:
        people_ready = False
      else:
        non_company = [
          lob for lob in lobs if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() != "company_total"
        ]
        requires = non_company if non_company else [lob for lob in lobs if isinstance(lob, dict)]
        for lob in requires:
          dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
          y1 = dmap.get("year1_payroll")
          ok = isinstance(y1, dict) and bool(str(y1.get("value") or "").strip())
          if not ok:
            people_ready = False
            break
    except Exception:
      people_ready = False
  financials_ready = _has_nonempty_text(financials, "financials_summary")

  if not ops_ready:
    return "ops"
  if not market_ready:
    return "market"
  if not people_ready:
    return "people"
  if not financials_ready:
    return "financials"
  return "done"


def _apply_updates(
  *,
  model: str,
  current_card: Dict[str, Any],
  updates: List[Dict[str, Any]],
  derived: List[Dict[str, Any]],
  now_ms: int,
  lob_key: str,
  lob_name: Optional[str],
  apply_to_all_lobs: bool,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
  normalized = _ensure_company_total_lob(_normalize_model_card(current_card))
  targets: List[Tuple[str, Optional[str]]] = [(lob_key, lob_name)]
  if apply_to_all_lobs and str(lob_key or "").strip() == "company_total":
    try:
      lobs = normalized.get("lobs")
      if isinstance(lobs, list):
        for lob in lobs:
          if not isinstance(lob, dict):
            continue
          k = str(lob.get("lob_key") or "").strip()
          if not k or k == "company_total":
            continue
          targets.append((k, str(lob.get("lob_name") or "").strip() or None))
    except Exception:
      pass

  changes: List[Dict[str, Any]] = []
  for target_key, target_name in targets:
    normalized, lob = _get_lob_entry(normalized, lob_key=target_key, lob_name=target_name)
    drivers: Dict[str, Any] = dict(lob.get("drivers") or {})
    derived_map: Dict[str, Any] = dict(lob.get("derived") or {})

    for u in updates:
      key = str(u.get("key") or "").strip()
      if not key:
        continue
      old = drivers.get(key)
      next_val = {
        "value": u.get("value"),
        "unit": u.get("unit"),
        "time_basis": u.get("time_basis"),
        "rationale": u.get("rationale"),
        "updated_at_ms": now_ms,
      }
      drivers[key] = next_val
      changes.append(
        {"model": model, "lob_key": target_key, "path": f"drivers.{key}", "old": old, "new": next_val}
      )

    # Derived values are LOB-specific; do not fan-out derived updates across LOBs.
    if (not apply_to_all_lobs) or (target_key == lob_key):
      for d in derived:
        key = str(d.get("key") or "").strip()
        if not key:
          continue
        # Headcount: ignore client-provided year1_payroll derived; it is computed from roles.
        if str(model or "").strip().lower() == "headcount" and key == "year1_payroll":
          continue
        old = derived_map.get(key)
        next_val = {
          "value": d.get("value"),
          "unit": d.get("unit"),
          "time_basis": d.get("time_basis"),
          "derivation": d.get("derivation"),
          "updated_at_ms": now_ms,
        }
        derived_map[key] = next_val
        changes.append(
          {"model": model, "lob_key": target_key, "path": f"derived.{key}", "old": old, "new": next_val}
        )

    lob["drivers"] = drivers
    lob["derived"] = derived_map

  normalized["version"] = int(normalized.get("version") or 1)
  normalized["updated_at_ms"] = now_ms
  normalized = _recompute_company_total_derived(normalized, model=model, now_ms=now_ms)
  return normalized, changes


def _recompute_company_total_derived(card: Dict[str, Any], *, model: str, now_ms: int) -> Dict[str, Any]:
  """
  For multi-LOB cards, keep company-level derived values as simple sums of LOB-level derived values.
  No allocation logic: we only sum already-entered per-LOB derived numbers.
  """
  normalized = _ensure_company_total_lob(_normalize_model_card(card))
  lobs = normalized.get("lobs")
  if not isinstance(lobs, list) or not lobs:
    return normalized

  non_company = [l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"]
  if not non_company:
    return normalized

  # Only keys we currently use for query rollups.
  sum_keys_by_model = {
    "marketing": ["year1_marketing_spend"],
    "headcount": ["year1_payroll"],
  }
  keys = sum_keys_by_model.get(str(model or "").strip().lower(), [])
  if not keys:
    return normalized

  # Find company_total entry
  company_total = None
  for lob in lobs:
    if isinstance(lob, dict) and str(lob.get("lob_key") or "").strip() == "company_total":
      company_total = lob
      break
  if not isinstance(company_total, dict):
    return normalized

  derived_out = company_total.get("derived") if isinstance(company_total.get("derived"), dict) else {}
  derived_out = dict(derived_out)

  for key in keys:
    total = 0.0
    found_any = False
    unit = None
    time_basis = None
    for lob in non_company:
      dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
      val = dmap.get(key)
      if not isinstance(val, dict):
        continue
      num = _as_number(val.get("value"))
      if num is None:
        continue
      total += float(num)
      found_any = True
      unit = unit or val.get("unit")
      time_basis = time_basis or val.get("time_basis")
    if not found_any:
      continue
    derived_out[key] = {
      "value": total,
      "unit": unit,
      "time_basis": time_basis,
      "derivation": "sum(per_lob)",
      "updated_at_ms": now_ms,
    }

  company_total["derived"] = derived_out
  return normalized


def _recompute_headcount_from_roles(
  *,
  conn,
  draft: Dict[str, Any],
  card: Dict[str, Any],
  now_ms: int,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
  """
  Deterministically enrich headcount roles using the IN wages dataset (when available),
  falling back to GPT-proposed fallback rates when no dataset match exists, then compute year1_payroll.
  """
  changes: List[Dict[str, Any]] = []
  normalized = _ensure_company_total_lob(_normalize_model_card(card))
  lobs = normalized.get("lobs")
  if not isinstance(lobs, list) or not lobs:
    return normalized, changes

  try:
    from wage_lookup import enrich_headcount_roles, normalize_state_code  # type: ignore
  except Exception:
    return normalized, changes

  state_code = normalize_state_code(draft.get("address_state"))
  naics_6: Optional[str] = None
  try:
    ops_json = _parse_json_dict(draft.get("operating_model_json"))
    naics_6 = _resolve_naics_6(conn=conn, business_type=str((ops_json or {}).get("business_type") or ""))
  except Exception:
    naics_6 = None

  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
    roles_val = drivers.get("roles")
    if not isinstance(roles_val, dict):
      continue
    roles_list = roles_val.get("value")
    if not isinstance(roles_list, list):
      continue

    enriched, total = enrich_headcount_roles(
      conn=conn,
      roles=roles_list,
      state_code=state_code,
      state_name=None,
      naics_6=naics_6,
    )
    incomplete = any(
      (isinstance(r, dict) and int(r.get("employee_count") or 0) > 0 and r.get("hourly_rate") is None)
      for r in enriched
    )

    old_roles = roles_val.get("value")
    roles_val["value"] = enriched
    roles_val["updated_at_ms"] = now_ms
    drivers["roles"] = roles_val
    lob["drivers"] = drivers
    changes.append(
      {
        "model": "headcount",
        "lob_key": str(lob.get("lob_key") or "").strip() or "company_total",
        "path": "drivers.roles.value",
        "old": old_roles,
        "new": enriched,
      }
    )

    derived = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
    old_y1 = derived.get("year1_payroll")
    derived["year1_payroll"] = {
      "value": (float(total) if (not incomplete) else None),
      "unit": "USD",
      "time_basis": "year",
      "derivation": "sum(employee_count × hourly_rate × hours_per_week × weeks_per_year)",
      "updated_at_ms": now_ms,
    }
    lob["derived"] = derived
    changes.append(
      {
        "model": "headcount",
        "lob_key": str(lob.get("lob_key") or "").strip() or "company_total",
        "path": "derived.year1_payroll",
        "old": old_y1,
        "new": derived.get("year1_payroll"),
      }
    )

  normalized["updated_at_ms"] = now_ms
  normalized = _recompute_company_total_derived(normalized, model="headcount", now_ms=now_ms)
  return normalized, changes


def post_intake_model_cards_handler(*, app, request):
  """
  Persist model-card driver updates (Accept/Edit) to the consult draft immediately.

  Request:
  {
    "draft_id": "...",
    "action": "accept" | "edit",
    "model": "marketing" | "headcount" | "pricing" | "fulfillment" | "ops_concept",
    "updates": [{ "key": "...", "value": ..., "unit": "...", "time_basis": "...", "rationale": "..." }],
    "derived": [{ "key": "...", "value": ..., "unit": "...", "time_basis": "...", "derivation": "..." }],
    "proposal_id": "...?",
    "note": "...?"
  }
  """
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = str(payload.get("draft_id") or "").strip()
  if not draft_id:
    return (jsonify({"error": "invalid_request", "detail": "draft_id is required"}), 400)

  model = str(payload.get("model") or "").strip().lower()
  column = _model_column(model)
  if not column:
    return (
      jsonify(
        {
          "error": "invalid_request",
          "detail": "model must be one of: ops_concept, fulfillment, marketing, pricing, headcount, milestones",
        }
      ),
      400,
    )

  updates = payload.get("updates")
  derived = payload.get("derived")
  if updates is None:
    updates = []
  if derived is None:
    derived = []
  if not isinstance(updates, list) or not all(isinstance(u, dict) for u in updates):
    return (jsonify({"error": "invalid_request", "detail": "updates must be a list of objects"}), 400)
  if not isinstance(derived, list) or not all(isinstance(d, dict) for d in derived):
    return (jsonify({"error": "invalid_request", "detail": "derived must be a list of objects"}), 400)

  action = str(payload.get("action") or "").strip().lower()
  if action not in ("accept", "edit"):
    action = "edit"
  proposal_id = str(payload.get("proposal_id") or "").strip() or None
  note = str(payload.get("note") or "").strip() or None
  lob_key = str(payload.get("lob_key") or "company_total").strip() or "company_total"
  lob_name = str(payload.get("lob_name") or "").strip() or None
  apply_to_all_lobs = bool(payload.get("apply_to_all_lobs"))

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from intake_consult_draft import append_messages, get_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    draft = get_draft(conn, draft_id=draft_id)
    current_card = _parse_json_dict(draft.get(column))
    now_ms = int(time.time() * 1000)
    pricing_unit_price_updated = False
    pricing_unit_price_value: Any = None
    if model == "pricing":
      try:
        for u in (updates or []):
          if str(u.get("key") or "").strip() == "unit_price":
            pricing_unit_price_updated = True
            pricing_unit_price_value = u.get("value")
            break
      except Exception:
        pricing_unit_price_updated = False
        pricing_unit_price_value = None
    next_card, changes = _apply_updates(
      model=model,
      current_card=current_card,
      updates=updates,
      derived=derived,
      now_ms=now_ms,
      lob_key=lob_key,
      lob_name=lob_name,
      apply_to_all_lobs=apply_to_all_lobs,
    )

    # Deterministic headcount math: enrich roles (dataset/fallback) + compute year1_payroll.
    if model == "headcount":
      touched_roles = any(str(u.get("key") or "").strip() == "roles" for u in updates)
      if touched_roles:
        next_card, extra_changes = _recompute_headcount_from_roles(
          conn=conn, draft=draft, card=next_card, now_ms=now_ms
        )
        changes.extend(extra_changes)

    try:
      current_nonce = int(draft.get("driver_revision_nonce") or 0)
    except Exception:
      current_nonce = 0
    next_nonce = current_nonce + 1

    existing_events = draft.get("driver_events_json")
    if isinstance(existing_events, list):
      events = list(existing_events)
    else:
      try:
        parsed = json.loads(str(existing_events)) if existing_events else []
      except Exception:
        parsed = []
      events = parsed if isinstance(parsed, list) else []

    events.append(
      {
        "nonce": next_nonce,
        "at_ms": now_ms,
        "action": action,
        "proposal_id": proposal_id,
        "note": note,
        "changes": changes,
      }
    )
    if len(events) > 500:
      events = events[-500:]

    proposals = _parse_json_list(draft.get("model_card_proposals_json"))
    if proposal_id:
      proposals = [
        p for p in proposals if not (isinstance(p, dict) and str(p.get("id") or "").strip() == str(proposal_id))
      ]

    # Update rollup columns opportunistically (query-friendly), without requiring a fixed driver taxonomy.
    year1_marketing_spend: Any = None
    year1_payroll: Any = None
    year1_revenue: Any = None
    if model == "marketing":
      # Only set company_total rollup if it exists.
      try:
        for lob in (next_card.get("lobs") or []):
          if not isinstance(lob, dict):
            continue
          if str(lob.get("lob_key") or "").strip() != "company_total":
            continue
          dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
          y1 = dmap.get("year1_marketing_spend")
          if isinstance(y1, dict):
            year1_marketing_spend = _as_number(y1.get("value"))
      except Exception:
        year1_marketing_spend = None
    if model == "headcount":
      try:
        for lob in (next_card.get("lobs") or []):
          if not isinstance(lob, dict):
            continue
          if str(lob.get("lob_key") or "").strip() != "company_total":
            continue
          dmap = lob.get("derived") if isinstance(lob.get("derived"), dict) else {}
          y1 = dmap.get("year1_payroll")
          if isinstance(y1, dict):
            year1_payroll = _as_number(y1.get("value"))
      except Exception:
        year1_payroll = None
    if model in ("ops_concept", "fulfillment", "pricing"):
      pass
    if model == "pricing":
      # Nothing automatic here yet; pricing rollups are typically used via revenue logic.
      pass

    # Persist the new card + event log; do not append a synthetic user message.
    kwargs: Dict[str, Any] = {
      "draft_id": draft_id,
      "new_messages": [],
      "driver_events": events,
      "driver_revision_nonce": next_nonce,
      "model_card_proposals": proposals,
    }

    # Map column -> append_messages argument name.
    card_param_by_column = {
      "ops_concept_model_json": "ops_concept_model_json",
      "fulfillment_model_json": "fulfillment_model_json",
      "marketing_model_json": "marketing_model_json",
      "pricing_model_json": "pricing_model_json",
      "headcount_model_json": "headcount_model_json",
      "milestones_model_json": "milestones_model_json",
    }
    card_param = card_param_by_column.get(column)
    if card_param:
      kwargs[card_param] = next_card

    # Additive sync: Pricing model is sourced from Ops `unit_price`. If the user edits the pricing
    # driver, keep Ops canonical `unit_price` in lockstep so revenue math updates immediately.
    if model == "pricing" and pricing_unit_price_updated:
      ops_json = _parse_json_dict(draft.get("operating_model_json"))
      # Preserve "not applicable" semantics for multi-stream businesses.
      if pricing_unit_price_value in (None, "", "null"):
        ops_json["unit_price"] = None
      else:
        ops_json["unit_price"] = pricing_unit_price_value
      kwargs["operating_model_json"] = ops_json

    if year1_marketing_spend is not None:
      kwargs["year1_marketing_spend"] = year1_marketing_spend
    if year1_payroll is not None:
      kwargs["year1_payroll"] = year1_payroll
    if year1_revenue is not None:
      kwargs["year1_revenue"] = year1_revenue

    append_messages(conn, **kwargs)

    # Ask the next question by delegating to the existing consult flow (no UI "wait" state).
    fresh = get_draft(conn, draft_id=draft_id)
    next_focus = _compute_next_focus_from_draft(draft=fresh)

    assistant_message: str = ""
    try:
      # Pull the freshest draft state after the write.
      messages_raw = fresh.get("messages_json")
      messages = []
      try:
        parsed_msgs = json.loads(str(messages_raw)) if messages_raw else []
        if isinstance(parsed_msgs, list):
          messages = [m for m in parsed_msgs if isinstance(m, dict)]
      except Exception:
        messages = []

      from api_handlers.shared_context import build_shared_context  # type: ignore
      from fact_templates import sanitize_fact_template  # type: ignore
      from intake_consultant import consultant_chat_turn  # type: ignore
      from target_market_consultant import target_market_chat_turn  # type: ignore
      from marketing_consultant import marketing_chat_turn  # type: ignore
      from milestones_consultant import milestones_chat_turn  # type: ignore
      from headcount_consultant import headcount_chat_turn  # type: ignore
      from people_capability_consultant import people_capability_chat_turn  # type: ignore
      from financials_consultant import financials_chat_turn  # type: ignore

      shared_context = build_shared_context(conn, draft_id=draft_id)
      ops_json = _parse_json_dict(fresh.get("operating_model_json"))
      naics_6 = _resolve_naics_6(conn=conn, business_type=str((ops_json or {}).get("business_type") or ""))
      ops_consumer_type = str((ops_json or {}).get("consumer_type") or "").strip().lower()
      if ops_consumer_type not in ("consumer", "b2b", "mixed"):
        ops_consumer_type = "consumer"
      intake_context = {
        "client_id": str(fresh.get("client_id") or "").strip(),
        "draft_id": draft_id,
        "business_name": fresh.get("business_name"),
        "business_start_date": fresh.get("business_start_date"),
        "address": fresh.get("business_address"),
        "consumer_type": ops_consumer_type,
        "naics_6": naics_6,
        "shared_context": shared_context,
      }
      continue_instruction = "Continue. Ask exactly ONE next question for the client to answer (do not bundle)."
      start_by_focus = {
        "ops": "Start the operational intake. Ask your first question.",
        "market": "Start the target market intake. Ask exactly ONE question for the client to answer (do not bundle multiple questions).",
        "people": "Start the People & Capability intake. Ask your first question.",
        "financials": "Start the financials intake. Ask your first question.",
      }
      # When editing model cards mid-stream, never restart a section: continue from current state.
      instruction = continue_instruction if messages else start_by_focus.get(next_focus, continue_instruction)
      if pricing_unit_price_updated and next_focus == "ops":
        instruction = (
          "A pricing driver was edited (unit price). Recalculate the revenue estimate using the updated unit price "
          "while keeping the previously agreed capacity/utilization assumptions the same, show the arithmetic, "
          "and then ask the client the next single data-bearing question (do not bundle)."
        )
      conversation_messages = [*messages, {"role": "user", "content": instruction}]

      turn: Dict[str, Any] = {"assistant_message": ""}
      if next_focus == "ops":
        operating_model = _parse_json_dict(fresh.get("operating_model_json"))
        milestones_card = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(fresh.get("milestones_model_json"))))
        milestones_pending = True
        try:
          lobs = milestones_card.get("lobs")
          if isinstance(lobs, list) and lobs:
            non_company = [
              l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
            ]
            requires = non_company if non_company else [l for l in lobs if isinstance(l, dict)]
            milestones_pending = any(
              not (
                isinstance((lob.get("drivers") if isinstance(lob, dict) else None), dict)
                and isinstance(((lob.get("drivers") or {}).get("milestones")), dict)
                and isinstance((((lob.get("drivers") or {}).get("milestones") or {}).get("value")), list)
                and any(
                  isinstance(x, dict) and bool(str(x.get("title") or "").strip())
                  for x in (((lob.get("drivers") or {}).get("milestones") or {}).get("value") or [])
                )
              )
              for lob in requires
            )
        except Exception:
          milestones_pending = True

        if _has_nonempty_text(operating_model, "business_description_summary") and milestones_pending:
          turn = milestones_chat_turn(
            intake_context={**intake_context, "milestones_suggestions": []},
            conversation_messages=conversation_messages,
          )
        else:
          turn = consultant_chat_turn(intake_context=intake_context, conversation_messages=conversation_messages)
      elif next_focus == "market":
        target_market = _parse_json_dict(fresh.get("target_market_json"))
        marketing = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(fresh.get("marketing_model_json"))))
        marketing_pending = True
        try:
          lobs = marketing.get("lobs")
          if isinstance(lobs, list) and lobs:
            non_company = [
              l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
            ]
            requires = non_company if non_company else [l for l in lobs if isinstance(l, dict)]
            marketing_pending = any(
              not (
                isinstance((lob.get("derived") if isinstance(lob, dict) else None), dict)
                and isinstance(((lob.get("derived") or {}).get("year1_marketing_spend")), dict)
                and bool(str((((lob.get("derived") or {}).get("year1_marketing_spend") or {}).get("value")) or "").strip())
              )
              for lob in requires
            )
        except Exception:
          marketing_pending = True

        if _has_nonempty_text(target_market, "target_market_summary") and marketing_pending:
          # Marketing pending: do not push target market questions; return a short Accept/Edit prompt.
          suggestion = {
            "monthly_marketing_budget": None,
            "year1_marketing_spend": fresh.get("year1_marketing_spend"),
            "basis": "Lock the budget driver so we can ground demand assumptions.",
            "primary_channels": None,
          }
          turn = marketing_chat_turn(intake_context={**intake_context, "marketing_suggestion": suggestion}, conversation_messages=conversation_messages)
        else:
          turn = target_market_chat_turn(intake_context=intake_context, conversation_messages=conversation_messages)
      elif next_focus == "people":
        people = _parse_json_dict(fresh.get("people_json"))
        headcount = _ensure_company_total_lob(_normalize_model_card(_parse_json_dict(fresh.get("headcount_model_json"))))
        headcount_pending = True
        try:
          lobs = headcount.get("lobs")
          if isinstance(lobs, list) and lobs:
            non_company = [
              l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "").strip() != "company_total"
            ]
            requires = non_company if non_company else [l for l in lobs if isinstance(l, dict)]
            headcount_pending = any(
              not (
                isinstance((lob.get("derived") if isinstance(lob, dict) else None), dict)
                and isinstance(((lob.get("derived") or {}).get("year1_payroll")), dict)
                and bool(str((((lob.get("derived") or {}).get("year1_payroll") or {}).get("value")) or "").strip())
              )
              for lob in requires
            )
        except Exception:
          headcount_pending = True

        if _has_nonempty_text(people, "key_people_summary") and headcount_pending:
          # Ensure at least one headcount proposal exists; propose if missing.
          proposals_now = _parse_json_list(fresh.get("model_card_proposals_json"))
          if not any(isinstance(p, dict) and p.get("model") == "headcount" for p in proposals_now):
            try:
              from model_card_proposer import propose_headcount_suggestions  # type: ignore
              from wage_lookup import enrich_headcount_roles, normalize_state_code  # type: ignore

              ops_json = _parse_json_dict(fresh.get("operating_model_json"))
              naics_6_live = _resolve_naics_6(
                conn=conn, business_type=str((ops_json or {}).get("business_type") or "")
              )
              state_code = normalize_state_code(fresh.get("address_state"))
              lobs_in = []
              try:
                raw_lobs = headcount.get("lobs")
                if isinstance(raw_lobs, list):
                  for l in raw_lobs:
                    if isinstance(l, dict):
                      lobs_in.append(
                        {
                          "lob_key": str(l.get("lob_key") or "").strip() or "company_total",
                          "lob_name": str(l.get("lob_name") or "").strip(),
                        }
                      )
              except Exception:
                lobs_in = []
              suggested = propose_headcount_suggestions(
                business_name=str(fresh.get("business_name") or "").strip(),
                business_type=str((ops_json or {}).get("business_type") or "").strip(),
                naics_6=naics_6_live,
                today_iso=time.strftime("%Y-%m-%d"),
                business_start_date=str(fresh.get("business_start_date") or "").strip() or None,
                ops_json=ops_json,
                people_json=people,
                shared_context=shared_context,
                lobs=lobs_in,
              )
              now_ms = int(time.time() * 1000)
              for s in suggested:
                if not isinstance(s, dict):
                  continue
                roles = s.get("roles")
                if not isinstance(roles, list) or not roles:
                  continue
                roles_enriched, total = enrich_headcount_roles(
                  conn=conn, roles=roles, state_code=state_code, state_name=None, naics_6=naics_6_live
                )
                proposal_id = f"hc_{now_ms}_{len(proposals_now)+1}"
                proposals_now = [
                  *proposals_now,
                  {
                    "id": proposal_id,
                    "model": "headcount",
                    "title": "Headcount (Year 1 payroll)",
                    "lob_key": str(s.get("lob_key") or "").strip() or None,
                    "lob_name": s.get("lob_name"),
                    "updates": [
                      {
                        "key": "roles",
                        "value": roles_enriched,
                        "unit": None,
                        "time_basis": None,
                        "rationale": str(s.get("basis") or "").strip()
                        or "Proposed Year‑1 staffing plan; edit roles/counts as needed.",
                      }
                    ],
                    "derived": [
                      {
                        "key": "year1_payroll",
                        "value": float(total),
                        "unit": "USD",
                        "time_basis": "year",
                        "derivation": "sum(employee_count × hourly_rate × hours_per_week × weeks_per_year)",
                      }
                    ],
                    "created_at_ms": now_ms,
                  },
                ]
              append_messages(conn, draft_id=draft_id, new_messages=[], model_card_proposals=proposals_now)
            except Exception:
              pass

          turn = headcount_chat_turn(
            intake_context={**intake_context, "headcount_suggestions": []},
            conversation_messages=conversation_messages,
          )
        else:
          turn = people_capability_chat_turn(intake_context=intake_context, conversation_messages=conversation_messages)
      elif next_focus == "financials":
        turn = financials_chat_turn(intake_context=intake_context, conversation_messages=conversation_messages)

      assistant_message = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
    except Exception:
      assistant_message = ""

    if assistant_message:
      append_messages(
        conn,
        draft_id=draft_id,
        new_messages=[{"role": "assistant", "content": assistant_message}],
        active_focus=next_focus,
        status="in_progress",
      )
    else:
      if next_focus == "done":
        assistant_message = 'All sections are complete.\n\nClick "Submit intake" to finish.'
        append_messages(
          conn,
          draft_id=draft_id,
          new_messages=[{"role": "assistant", "content": assistant_message}],
          active_focus="done",
          status="completed",
          completed=True,
          consistency_passed=True,
        )

    return jsonify(
      {
        "status": "ok",
        "draft_id": draft_id,
        "client_id": str(draft.get("client_id") or "").strip(),
        "model": model,
        "driver_revision_nonce": next_nonce,
        "active_focus": next_focus,
        "assistant_message": assistant_message,
        "model_card": next_card,
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass
