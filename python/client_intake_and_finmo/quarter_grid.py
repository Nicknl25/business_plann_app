from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from financial_model_engine.model_inputs import QUARTER_COUNT
from financial_model_engine.solver import LeverControl, OutputTarget

from client_intake_and_finmo import consistency_flow as consistency_runtime  # type: ignore
from client_intake_and_finmo.consistency_financials import build_consistency_financial_summary  # type: ignore
from client_intake_and_finmo.consistency_strategy_advisor import (  # type: ignore
  _openai_model,
  _openai_timeout_seconds,
  _parse_json_response,
  _post_openai,
  _require_openai_key,
  _sanitize_canonical_live_payload,
  _strategy_system_prompts,
)


_PLANNING_MODE_DEFAULTS: Dict[str, str] = {
  "turnaround": (
    "Assume you are allowed to use every listed variable as part of one coherent repair plan for this actual company. "
    "Realistically, what would make this business profitable as soon as it can become profitable without breaking business reality? "
    "Use the full company context and behave like an operator trying to make the company truly work, not just cosmetically improve."
  ),
  "normalize": (
    "This case may be over-optimistic or commercially overstated rather than distressed. "
    "Your job is to normalize the plan to something believable for the company's stage and business model. "
    "Dial back unrealistic pricing, utilization, capacity, margins, cash build, or timing when needed, but do not force a turnaround story if the business is not truly broken. "
    "Business stage matters. Preserve real upside where believable, but remove fantasy."
  ),
  "rebalance": (
    "This case appears directionally sound but misbalanced. "
    "Your job is to rebalance the model to a more believable operating path for the company's stage, tightening weak assumptions without forcing an unnecessary rescue or overcorrection."
  ),
}


def _prompt_library_dir() -> Path:
  return Path(__file__).resolve().parent / "prompts" / "quarter_grid"


def available_planning_modes() -> List[str]:
  names = set(_PLANNING_MODE_DEFAULTS.keys())
  prompt_dir = _prompt_library_dir()
  if prompt_dir.exists():
    for path in prompt_dir.glob("*.md"):
      if path.stem.strip():
        names.add(path.stem.strip().lower())
  preferred_order = ["turnaround", "normalize", "rebalance"]
  ordered = [name for name in preferred_order if name in names]
  ordered.extend(sorted(name for name in names if name not in preferred_order))
  return ordered


def resolve_planning_mode(planning_mode: str) -> str:
  mode = str(planning_mode or "").strip().lower()
  if mode in available_planning_modes():
    return mode
  return "turnaround"


def _load_planning_mode_prompt_file(planning_mode: str) -> str:
  mode = resolve_planning_mode(planning_mode)
  path = _prompt_library_dir() / f"{mode}.md"
  try:
    text = path.read_text(encoding="utf-8").strip()
  except Exception:
    text = ""
  return text


def planning_mode_text(planning_mode: str) -> str:
  mode = resolve_planning_mode(planning_mode)
  prompt_file_text = _load_planning_mode_prompt_file(mode)
  if prompt_file_text:
    return prompt_file_text
  return _PLANNING_MODE_DEFAULTS.get(mode) or _PLANNING_MODE_DEFAULTS["turnaround"]


def classify_planning_mode(
  *,
  baseline_summary: Dict[str, Any],
  diagnosis: Dict[str, Any],
) -> Dict[str, str]:
  severity = str((diagnosis or {}).get("severity_class") or "").strip().lower()
  primary = str((diagnosis or {}).get("primary_cause") or "").strip().lower()
  preferred = [str(item or "").strip().lower() for item in ((diagnosis or {}).get("preferred_strategy_ids") or [])]
  revenue = max(1.0, float_or_none((baseline_summary or {}).get("revenue")) or 0.0)
  ebitda = float_or_none((baseline_summary or {}).get("ebitda")) or 0.0
  ebitda_margin = ebitda / revenue if revenue > 0 else 0.0

  if "reality_normalization_strategy" in preferred or (ebitda > 0 and ebitda_margin > 0.30):
    return {
      "planning_mode": "normalize",
      "planning_mode_reason": "app_classified_overstated_or_overoptimistic_case",
    }
  if severity == "severe" or ebitda < 0:
    return {
      "planning_mode": "turnaround",
      "planning_mode_reason": (
        "app_classified_turnaround_case"
        if severity == "severe"
        else f"app_classified_loss_making_case:{primary or 'mixed'}"
      ),
    }
  return {
    "planning_mode": "rebalance",
    "planning_mode_reason": "app_classified_misaligned_but_salvageable_case",
  }


def quarter_label(quarter_index: int) -> str:
  return f"Q{int(quarter_index)}"


def float_or_none(value: Any) -> Optional[float]:
  if value in {None, ""}:
    return None
  try:
    return float(value)
  except Exception:
    return None


def has_material_values(values: Sequence[Any]) -> bool:
  for raw_value in values or []:
    number = float_or_none(raw_value)
    if number is not None and abs(number) > 1e-12:
      return True
  return False


def extract_quarter_grid_rows(
  *,
  model_input_json: Dict[str, Any],
  baseline_outputs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  sections = model_input_json.get("sections") if isinstance(model_input_json.get("sections"), dict) else {}
  rows: List[Dict[str, Any]] = []

  for item in sections.get("revenue") or []:
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    values = list(item.get("values") or [])
    if len(values) == QUARTER_COUNT + 1:
      values = values[1:]
    if not has_material_values(values):
      continue
    rows.append(
      {
        "row_id": lever_id,
        "row_type": "lever",
        "section": "revenue",
        "label": str(item.get("label") or lever_id),
        "baseline_values": values[:QUARTER_COUNT],
      }
    )

  for section_name in ("expenses", "balance_sheet"):
    for item in sections.get(section_name) or []:
      if not isinstance(item, dict):
        continue
      if not bool(item.get("controller_write")):
        continue
      lever_id = str(item.get("lever_id") or "").strip()
      if not lever_id:
        continue
      values = list(item.get("values") or [])
      if len(values) == QUARTER_COUNT + 1:
        values = values[1:]
      rows.append(
        {
          "row_id": lever_id,
          "row_type": "lever",
          "section": section_name,
          "label": str(item.get("label") or lever_id),
          "baseline_values": values[:QUARTER_COUNT],
        }
      )

  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for item in schedules.get("rows") or []:
    if not isinstance(item, dict):
      continue
    if not bool(item.get("controller_write")):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    values = list(item.get("values") or [])
    if len(values) == QUARTER_COUNT + 1:
      values = values[1:]
    rows.append(
      {
        "row_id": lever_id,
        "row_type": "lever",
        "section": "schedules",
        "label": str(item.get("label") or lever_id),
        "baseline_values": values[:QUARTER_COUNT],
      }
    )

  for metric in ("Revenue", "EBITDA", "Cash"):
    metric_key = {"Revenue": "revenue", "EBITDA": "ebitda", "Cash": "ending_cash"}[metric]
    rows.append(
      {
        "row_id": metric,
        "row_type": "output",
        "section": "output",
        "label": metric,
        "baseline_values": [row.get(metric_key) for row in baseline_outputs[:QUARTER_COUNT]],
      }
    )

  return rows


def build_real_governor_payload(
  *,
  source_row: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  finmo_path: str,
  parse_json_object,
) -> Dict[str, Any]:
  ops_json = parse_json_object(source_row.get("operating_model_json"))
  target_market_json = parse_json_object(source_row.get("target_market_json"))
  people_json = parse_json_object(source_row.get("people_json"))
  financials_json = parse_json_object(source_row.get("financials_json"))
  financials_year1_json = parse_json_object(source_row.get("financials_year1_json"))
  fulfillment_json = parse_json_object(source_row.get("fulfillment_json"))
  marketing_model_json = parse_json_object(source_row.get("marketing_model_json"))

  baseline_summary = consistency_runtime._baseline_summary_from_finmo(finmo_json) or build_consistency_financial_summary(
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  state_model = consistency_runtime._build_consistency_state_model(
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    baseline_summary=baseline_summary,
    diagnostic_state=None,
    finmo_path=finmo_path,
    business_facts={},
    model_input_json=model_input_json,
    finmo_json=finmo_json,
  )
  direct_inputs = consistency_runtime._build_controller_inputs(state_model=state_model)
  diagnosis = consistency_runtime._diagnose_case(
    baseline_summary=baseline_summary,
    diagnostic_state=None,
  )
  fixed_facts = (state_model.get("fixed_facts") or {}) if isinstance(state_model.get("fixed_facts"), dict) else {}
  return {
    "baseline_summary": _sanitize_canonical_live_payload(baseline_summary or {}),
    "fixed_facts": _sanitize_canonical_live_payload(fixed_facts or {}),
    "model_input_view": _sanitize_canonical_live_payload((fixed_facts or {}).get("model_input_json") or {}),
    "finmo_view": _sanitize_canonical_live_payload((fixed_facts or {}).get("finmo_json") or {}),
    "viability_mode": True,
  }


def grid_markdown(rows: List[Dict[str, Any]]) -> str:
  header = ["Variable", *[quarter_label(index) for index in range(1, QUARTER_COUNT + 1)]]
  lines = [
    "| " + " | ".join(header) + " |",
    "| " + " | ".join(["---"] * len(header)) + " |",
  ]
  for item in rows:
    values = []
    for raw_value in item.get("baseline_values") or []:
      number = float_or_none(raw_value)
      values.append("" if number is None else f"{number:.4f}")
    padded = values + [""] * (QUARTER_COUNT - len(values))
    lines.append("| " + " | ".join([str(item.get("row_id") or ""), *padded[:QUARTER_COUNT]]) + " |")
  return "\n".join(lines)


def quarter_grid_schema(allowed_row_ids: Sequence[str]) -> Dict[str, Any]:
  return {
    "name": "quarter_grid_probe",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "summary": {"type": "string"},
        "rows": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "row_id": {"type": "string", "enum": [str(item) for item in allowed_row_ids]},
              "row_type": {"type": "string", "enum": ["lever", "output"]},
              "quarter_bands": {
                "type": "array",
                "items": {
                  "type": "object",
                  "additionalProperties": False,
                  "properties": {
                    "quarter_index": {"type": "integer", "minimum": 1, "maximum": QUARTER_COUNT},
                    "min_value": {"type": "number"},
                    "max_value": {"type": "number"},
                  },
                  "required": ["quarter_index", "min_value", "max_value"],
                },
              },
            },
            "required": ["row_id", "row_type", "quarter_bands"],
          },
        },
      },
      "required": ["summary", "rows"],
    },
    "strict": True,
  }


def build_quarter_grid_prompt(
  *,
  source_row: Dict[str, Any],
  grid_rows: List[Dict[str, Any]],
  governor_payload: Dict[str, Any],
  batch_index: int,
  batch_count: int,
  planning_mode: str,
) -> str:
  business_name = str(source_row.get("business_name") or "").strip() or "Unknown business"
  row_descriptions = [f"- {item['row_id']} ({item['row_type']})" for item in grid_rows]
  return (
    f"You are building a quarter-by-quarter financial planning grid for {business_name}.\n"
    + planning_mode_text(planning_mode)
    + "\n"
    "Return a min/max band for every listed row and every quarter Q1 through Q20.\n"
    "Fill every box. Every listed row must have a min/max band in every quarter.\n"
    "Do not group periods. Do not omit rows. Do not invent rows.\n"
    "You must preserve every row_id exactly as given. Do not add suffixes, prefixes, labels, or parentheses.\n"
    "Every returned row must contain exactly 20 quarter_bands, one for each quarter_index from 1 to 20.\n"
    "For each quarter, min_value must be less than or equal to max_value.\n"
    "Rows may stay similar quarter to quarter when genuinely appropriate, but do not flatten the whole horizon into one repeated answer unless the business logic truly requires it.\n"
    "For output rows, use dollar values from Financial Model QTR semantics.\n"
    "For lever rows, use realistic workbook-driver values.\n\n"
    "Profitability standard for this probe:\n"
    "- push toward profitability as early as realism allows\n"
    "- do not normalize persistent multi-year losses if a believable operating repair exists\n"
    "- use the full set of listed variables if needed to create a credible path\n"
    "- the resulting grid should read like a real company plan for this specific business and stage\n\n"
    f"This is batch {batch_index} of {batch_count}. Return only the rows listed in this batch.\n\n"
    "Real governor context payload:\n"
    + json.dumps(governor_payload, ensure_ascii=False)
    + "\n\n"
    "Rows you must fill:\n"
    + "\n".join(row_descriptions)
    + "\n\nBaseline quarter grid:\n"
    + grid_markdown(grid_rows)
  )


def quarter_grid_system_prompt(*, use_real_strategy_prompt: bool, planning_mode: str) -> str:
  if not use_real_strategy_prompt:
    return (
      "Fill the full quarter grid exactly. Return only the structured JSON schema response. "
      "Use real business judgment and match the company stage. "
      + planning_mode_text(planning_mode)
    )
  base_prompt = _strategy_system_prompts()[0]
  override = (
    "\n\nQuarter-Grid Override:\n"
    "This is the quarter-native planning contract, not the grouped-period contract.\n"
    "Ignore any grouped-period guidance and do not return strategy ids, lever_adjustment_plan, "
    "controlled_output_targets, or target_posture.\n"
    "Instead, return only the requested quarter-by-quarter grid rows using the attached schema.\n"
    "Fill every listed row for every quarter Q1 through Q20.\n"
    "Preserve each row_id exactly as given.\n"
    "Use the real business context and realism standard from the rest of this prompt.\n"
    + planning_mode_text(planning_mode)
    + "\n"
    "Express the result as min/max bands in the quarter grid."
  )
  return base_prompt + override


def call_quarter_grid_openai(
  prompt: str,
  *,
  allowed_row_ids: Sequence[str],
  use_real_strategy_prompt: bool,
  planning_mode: str,
) -> Dict[str, Any]:
  api_key = _require_openai_key()
  headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
  }
  payload = {
    "model": _openai_model(),
    "input": [
      {
        "role": "system",
        "content": [
          {
            "type": "input_text",
            "text": quarter_grid_system_prompt(
              use_real_strategy_prompt=use_real_strategy_prompt,
              planning_mode=planning_mode,
            ),
          }
        ],
      },
      {
        "role": "user",
        "content": [{"type": "input_text", "text": prompt}],
      },
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "quarter_grid_probe",
        "schema": quarter_grid_schema(allowed_row_ids)["schema"],
        "strict": True,
      }
    },
  }
  response = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers=headers,
    payload=payload,
    timeout_seconds=_openai_timeout_seconds("strategy"),
    max_attempts=2,
  )
  if response.status_code >= 400:
    raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:1200]}")
  return _parse_json_response(response.json())


def chunk_quarter_grid_rows(rows: List[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
  normalized_size = max(1, int(batch_size or 1))
  return [rows[index:index + normalized_size] for index in range(0, len(rows), normalized_size)]


def validate_quarter_grid_response(
  *,
  requested_rows: List[Dict[str, Any]],
  response_json: Dict[str, Any],
) -> Dict[str, Any]:
  requested_ids = [str(item.get("row_id") or "") for item in requested_rows]
  requested_id_set = set(requested_ids)
  returned_rows = response_json.get("rows") if isinstance(response_json.get("rows"), list) else []
  returned_by_id: Dict[str, Dict[str, Any]] = {}
  duplicates: List[str] = []
  for item in returned_rows:
    if not isinstance(item, dict):
      continue
    row_id = str(item.get("row_id") or "").strip()
    if not row_id:
      continue
    if row_id in returned_by_id:
      duplicates.append(row_id)
    returned_by_id[row_id] = item

  missing_rows = [row_id for row_id in requested_ids if row_id not in returned_by_id]
  extra_rows = sorted(row_id for row_id in returned_by_id if row_id not in requested_id_set)

  malformed_rows: List[str] = []
  flat_rows: List[str] = []
  for row_id, item in returned_by_id.items():
    quarter_bands = item.get("quarter_bands") if isinstance(item.get("quarter_bands"), list) else []
    if len(quarter_bands) != QUARTER_COUNT:
      malformed_rows.append(f"{row_id}::quarter_count={len(quarter_bands)}")
      continue
    seen_quarters = []
    identical_pairs = []
    for band in quarter_bands:
      if not isinstance(band, dict):
        malformed_rows.append(f"{row_id}::non_object_band")
        break
      quarter_index = int(band.get("quarter_index") or 0)
      minimum = float_or_none(band.get("min_value"))
      maximum = float_or_none(band.get("max_value"))
      if quarter_index < 1 or quarter_index > QUARTER_COUNT:
        malformed_rows.append(f"{row_id}::quarter={quarter_index}")
        break
      if minimum is None or maximum is None or minimum > maximum:
        malformed_rows.append(f"{row_id}::invalid_band::Q{quarter_index}")
        break
      seen_quarters.append(quarter_index)
      identical_pairs.append((round(minimum, 6), round(maximum, 6)))
    if sorted(seen_quarters) != list(range(1, QUARTER_COUNT + 1)):
      malformed_rows.append(f"{row_id}::quarter_indexes_invalid")
      continue
    if len(set(identical_pairs)) == 1:
      flat_rows.append(row_id)

  return {
    "requested_row_count": len(requested_rows),
    "returned_row_count": len(returned_by_id),
    "missing_rows": missing_rows,
    "extra_rows": extra_rows,
    "duplicate_rows": duplicates,
    "malformed_rows": malformed_rows,
    "flat_rows": flat_rows,
  }


def controls_from_quarter_grid(grid_json: Dict[str, Any]) -> List[LeverControl]:
  controls: List[LeverControl] = []
  for row in grid_json.get("rows") or []:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_type") or "").strip().lower() != "lever":
      continue
    lever_id = str(row.get("row_id") or "").strip()
    if not lever_id:
      continue
    for band in row.get("quarter_bands") or []:
      if not isinstance(band, dict):
        continue
      quarter_index = int(band.get("quarter_index") or 0)
      if quarter_index < 1:
        continue
      controls.append(
        LeverControl(
          lever_id=lever_id,
          quarter_start=quarter_index,
          quarter_end=quarter_index,
          min_value=float_or_none(band.get("min_value")),
          max_value=float_or_none(band.get("max_value")),
        )
      )
  return controls


def targets_from_quarter_grid(grid_json: Dict[str, Any]) -> List[OutputTarget]:
  targets: List[OutputTarget] = []
  for row in grid_json.get("rows") or []:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_type") or "").strip().lower() != "output":
      continue
    metric = str(row.get("row_id") or "").strip()
    if not metric:
      continue
    for band in row.get("quarter_bands") or []:
      if not isinstance(band, dict):
        continue
      quarter_index = int(band.get("quarter_index") or 0)
      if quarter_index < 1:
        continue
      targets.append(
        OutputTarget(
          metric=metric,
          quarter_start=quarter_index,
          quarter_end=quarter_index,
          min_value=float_or_none(band.get("min_value")),
          max_value=float_or_none(band.get("max_value")),
        )
      )
  return targets
