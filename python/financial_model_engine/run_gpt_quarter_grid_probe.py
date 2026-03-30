from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "python"
CLIENT_INTAKE_DIR = PYTHON_DIR / "client_intake_and_finmo"
if str(PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(PYTHON_DIR))
if str(CLIENT_INTAKE_DIR) not in sys.path:
  sys.path.insert(0, str(CLIENT_INTAKE_DIR))

from client_intake_and_finmo.consistency_strategy_advisor import (  # type: ignore
  _openai_model,
  _openai_timeout_seconds,
  _parse_json_response,
  _post_openai,
  _require_openai_key,
  _sanitize_canonical_live_payload,
  _strategy_system_prompts,
)
from client_intake_and_finmo import consistency_flow as consistency_runtime  # type: ignore
from client_intake_and_finmo.consistency_financials import (  # type: ignore
  build_consistency_financial_summary,
)
from financial_model_engine.finmo_model import calculate_finmo_model
from financial_model_engine.model_inputs import FinancialModelInputs, QUARTER_COUNT
from financial_model_engine.run_engine_replay import (  # type: ignore
  DEFAULT_OUTPUT_DIR,
  _load_env,
  _load_workbook_views,
  _mysql_connect,
  _parse_json_object,
  _select_source_draft,
)


def _safe_filename_part(value: str) -> str:
  cleaned = "".join(ch for ch in str(value or "").strip() if ch not in '\\/:*?"<>|')
  return cleaned[:180] or "quarter_grid_probe"


def _build_report_path(*, output_dir: Path, seed: str, written_at: datetime) -> Path:
  timestamp_part = written_at.strftime("%m-%d-%Y %H-%M-%S")
  return output_dir / f"{timestamp_part} -- {_safe_filename_part(seed)}.txt"


def _write_report(*, output_dir: Path, seed: str, lines: Sequence[str]) -> Path:
  output_dir.mkdir(parents=True, exist_ok=True)
  path = _build_report_path(output_dir=output_dir, seed=seed, written_at=datetime.now())
  path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
  return path


def _quarter_label(quarter_index: int) -> str:
  return f"Q{int(quarter_index)}"


def _float_or_none(value: Any) -> Optional[float]:
  if value in {None, ""}:
    return None
  try:
    return float(value)
  except Exception:
    return None


def _has_material_values(values: Sequence[Any]) -> bool:
  for raw_value in values or []:
    number = _float_or_none(raw_value)
    if number is not None and abs(number) > 1e-12:
      return True
  return False


def _extract_grid_rows(
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
    if not _has_material_values(values):
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


def _build_real_governor_payload(
  *,
  source_row: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  finmo_path: str,
) -> Dict[str, Any]:
  ops_json = _parse_json_object(source_row.get("operating_model_json"))
  target_market_json = _parse_json_object(source_row.get("target_market_json"))
  people_json = _parse_json_object(source_row.get("people_json"))
  financials_json = _parse_json_object(source_row.get("financials_json"))
  financials_year1_json = _parse_json_object(source_row.get("financials_year1_json"))
  fulfillment_json = _parse_json_object(source_row.get("fulfillment_json"))
  marketing_model_json = _parse_json_object(source_row.get("marketing_model_json"))

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
  strategy_catalog = consistency_runtime._build_strategy_catalog(
    state_model=state_model,
    direct_inputs=direct_inputs,
  )
  catalog_payload: List[Dict[str, Any]] = []
  for item in strategy_catalog:
    if not isinstance(item, dict):
      continue
    catalog_payload.append(
      {
        "strategy_id": str(item.get("strategy_id") or "").strip(),
        "strategy_name": str(item.get("strategy_name") or "").strip(),
        "archetype": str(item.get("archetype") or "").strip(),
        "allowed_model_input_levers": list(item.get("allowed_model_input_levers") or []),
        "allowed_model_input_lever_details": _sanitize_canonical_live_payload(item.get("allowed_model_input_lever_details") or []),
        "dominant_tradeoff": str(item.get("dominant_tradeoff") or "").strip(),
      }
    )
  fixed_facts = (state_model.get("fixed_facts") or {}) if isinstance(state_model.get("fixed_facts"), dict) else {}
  return {
    "baseline_summary": _sanitize_canonical_live_payload(baseline_summary or {}),
    "fixed_facts": _sanitize_canonical_live_payload(fixed_facts or {}),
    "diagnosis": _sanitize_canonical_live_payload(diagnosis or {}),
    "model_input_view": _sanitize_canonical_live_payload((fixed_facts or {}).get("model_input_json") or {}),
    "finmo_view": _sanitize_canonical_live_payload((fixed_facts or {}).get("finmo_json") or {}),
    "viability_mode": True,
    "strategy_catalog": catalog_payload,
  }


def _grid_markdown(rows: List[Dict[str, Any]]) -> str:
  header = ["Variable", *[_quarter_label(index) for index in range(1, QUARTER_COUNT + 1)]]
  lines = [
    "| " + " | ".join(header) + " |",
    "| " + " | ".join(["---"] * len(header)) + " |",
  ]
  for item in rows:
    values = []
    for raw_value in item.get("baseline_values") or []:
      number = _float_or_none(raw_value)
      values.append("" if number is None else f"{number:.4f}")
    padded = values + [""] * (QUARTER_COUNT - len(values))
    lines.append("| " + " | ".join([str(item.get("row_id") or ""), *padded[:QUARTER_COUNT]]) + " |")
  return "\n".join(lines)


def _probe_schema(allowed_row_ids: Sequence[str]) -> Dict[str, Any]:
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


def _build_probe_prompt(
  *,
  source_row: Dict[str, Any],
  grid_rows: List[Dict[str, Any]],
  governor_payload: Dict[str, Any],
  batch_index: int,
  batch_count: int,
) -> str:
  business_name = str(source_row.get("business_name") or "").strip() or "Unknown business"
  row_descriptions = []
  for item in grid_rows:
    row_descriptions.append(f"- {item['row_id']} ({item['row_type']})")
  return (
    f"You are building a quarter-by-quarter financial planning grid for {business_name}.\n"
    "Assume you are allowed to use every listed variable as part of one coherent repair plan for this actual company.\n"
    "Realistically, what would make this business profitable as soon as it can become profitable without breaking business reality?\n"
    "Use the full company context and behave like an operator trying to make the company truly work, not just cosmetically improve.\n"
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
    "- the resulting grid should read like a real turnaround path for this specific home health business\n\n"
    f"This is batch {batch_index} of {batch_count}. Return only the rows listed in this batch.\n\n"
    "Real governor context payload:\n"
    + json.dumps(governor_payload, ensure_ascii=False)
    + "\n\n"
    "Rows you must fill:\n"
    + "\n".join(row_descriptions)
    + "\n\nBaseline quarter grid:\n"
    + _grid_markdown(grid_rows)
  )


def _probe_system_prompt(*, use_real_strategy_prompt: bool) -> str:
  if not use_real_strategy_prompt:
    return (
      "Fill the full quarter grid exactly. Return only the structured JSON schema response. "
      "Use real business judgment and aim for earliest believable profitability."
    )
  base_prompt = _strategy_system_prompts()[0]
  override = (
    "\n\nQuarter-Grid Probe Override:\n"
    "This is a sidecar experiment, not the live strategy-selection contract.\n"
    "For this probe, ignore any grouped-period guidance and do not return strategy ids, lever_adjustment_plan, "
    "controlled_output_targets, or target_posture.\n"
    "Instead, return only the requested quarter-by-quarter grid rows using the attached schema.\n"
    "Fill every listed row for every quarter Q1 through Q20.\n"
    "Preserve each row_id exactly as given.\n"
    "Use the real business context and realism standard from the rest of this prompt.\n"
    "Assume you may use every listed variable. Build the earliest believable path to profitability for this actual company and express it as min/max bands in the grid."
  )
  return base_prompt + override


def _call_probe(
  prompt: str,
  *,
  allowed_row_ids: Sequence[str],
  use_real_strategy_prompt: bool,
) -> Dict[str, Any]:
  api_key = _require_openai_key()
  url = "https://api.openai.com/v1/responses"
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
            "text": _probe_system_prompt(use_real_strategy_prompt=use_real_strategy_prompt),
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
        "schema": _probe_schema(allowed_row_ids)["schema"],
        "strict": True,
      }
    },
  }
  response = _post_openai(
    url=url,
    headers=headers,
    payload=payload,
    timeout_seconds=_openai_timeout_seconds("strategy"),
    max_attempts=2,
  )
  if response.status_code >= 400:
    raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:1200]}")
  return _parse_json_response(response.json())


def _chunked_rows(rows: List[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
  normalized_size = max(1, int(batch_size or 1))
  return [rows[index:index + normalized_size] for index in range(0, len(rows), normalized_size)]


def _validate_probe_response(
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
      q = int(band.get("quarter_index") or 0)
      minimum = _float_or_none(band.get("min_value"))
      maximum = _float_or_none(band.get("max_value"))
      if q < 1 or q > QUARTER_COUNT:
        malformed_rows.append(f"{row_id}::quarter={q}")
        break
      if minimum is None or maximum is None or minimum > maximum:
        malformed_rows.append(f"{row_id}::invalid_band::Q{q}")
        break
      seen_quarters.append(q)
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


def _report_lines(
  *,
  source_row: Dict[str, Any],
  finmo_path: str,
  grid_rows: List[Dict[str, Any]],
  response_json: Dict[str, Any],
  validation: Dict[str, Any],
  batch_summaries: List[str],
) -> List[str]:
  lines: List[str] = []
  draft_id = str(source_row.get("draft_id") or "").strip()
  client_id = str(source_row.get("client_id") or "").strip()
  lines.append(f"Quarter Grid Probe: {draft_id or client_id}")
  lines.append(f"Source Draft ID: {draft_id}")
  lines.append(f"Source Client ID: {client_id}")
  lines.append(f"Business Name: {str(source_row.get('business_name') or '').strip()}")
  lines.append(f"Finmo Path: {finmo_path}")
  lines.append("")
  lines.append("Probe Summary")
  lines.append("-------------")
  lines.append(str(response_json.get("summary") or ""))
  if batch_summaries:
    lines.append("")
    lines.append("Batch Summaries")
    lines.append("---------------")
    for item in batch_summaries:
      lines.append(f"- {item}")
  lines.append("")
  lines.append("Validation")
  lines.append("----------")
  lines.append(f"Requested Rows: {validation['requested_row_count']}")
  lines.append(f"Returned Rows: {validation['returned_row_count']}")
  lines.append(f"Missing Rows: {len(validation['missing_rows'])}")
  lines.append(f"Extra Rows: {len(validation['extra_rows'])}")
  lines.append(f"Duplicate Rows: {len(validation['duplicate_rows'])}")
  lines.append(f"Malformed Rows: {len(validation['malformed_rows'])}")
  lines.append(f"Flat Rows: {len(validation['flat_rows'])}")
  if validation["missing_rows"]:
    lines.append("Missing Row IDs:")
    for row_id in validation["missing_rows"]:
      lines.append(f"- {row_id}")
  if validation["malformed_rows"]:
    lines.append("Malformed Rows:")
    for item in validation["malformed_rows"]:
      lines.append(f"- {item}")
  if validation["flat_rows"]:
    lines.append("Flat Rows:")
    for row_id in validation["flat_rows"][:100]:
      lines.append(f"- {row_id}")
  lines.append("")
  lines.append("Requested Grid Rows")
  lines.append("-------------------")
  for item in grid_rows:
    lines.append(f"- {item['row_type']} | {item['row_id']}")
  lines.append("")
  lines.append("Response JSON")
  lines.append("-------------")
  lines.append(json.dumps(response_json, indent=2))
  return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
  parser = argparse.ArgumentParser(description="Probe whether GPT can fill a full quarter-by-quarter band grid.")
  parser.add_argument("--draft-id", dest="draft_id")
  parser.add_argument("--client-id", dest="client_id")
  parser.add_argument("--output-dir", dest="output_dir", default=str(DEFAULT_OUTPUT_DIR))
  parser.add_argument("--batch-size", dest="batch_size", type=int, default=12)
  parser.add_argument("--use-real-strategy-prompt", dest="use_real_strategy_prompt", action="store_true")
  args = parser.parse_args(list(argv) if argv is not None else None)

  _load_env()
  conn = _mysql_connect()
  try:
    source_row = _select_source_draft(conn, source_draft_id=args.draft_id, source_client_id=args.client_id)
    model_input_json, _finmo_json, finmo_path = _load_workbook_views(source_row)
  finally:
    conn.close()

  baseline_inputs = FinancialModelInputs.from_model_input_json(model_input_json)
  baseline_outputs = calculate_finmo_model(baseline_inputs).quarter_rows()
  grid_rows = _extract_grid_rows(model_input_json=model_input_json, baseline_outputs=baseline_outputs)
  governor_payload = _build_real_governor_payload(
    source_row=source_row,
    model_input_json=model_input_json,
    finmo_json=_finmo_json,
    finmo_path=finmo_path,
  )
  response_rows: List[Dict[str, Any]] = []
  batch_summaries: List[str] = []
  batches = _chunked_rows(grid_rows, args.batch_size)
  for batch_offset, batch_rows in enumerate(batches, start=1):
    prompt = _build_probe_prompt(
      source_row=source_row,
      grid_rows=batch_rows,
      governor_payload=governor_payload,
      batch_index=batch_offset,
      batch_count=len(batches),
    )
    batch_response = _call_probe(
      prompt,
      allowed_row_ids=[str(item.get("row_id") or "") for item in batch_rows],
      use_real_strategy_prompt=bool(args.use_real_strategy_prompt),
    )
    response_rows.extend(batch_response.get("rows") if isinstance(batch_response.get("rows"), list) else [])
    batch_summaries.append(str(batch_response.get("summary") or f"Batch {batch_offset} completed."))
  response_json = {
    "summary": f"Completed {len(batches)} quarter-grid probe batches.",
    "rows": response_rows,
  }
  validation = _validate_probe_response(requested_rows=grid_rows, response_json=response_json)
  report_path = _write_report(
    output_dir=Path(args.output_dir),
    seed=str(source_row.get("draft_id") or source_row.get("client_id") or "quarter-grid-probe"),
    lines=_report_lines(
      source_row=source_row,
      finmo_path=finmo_path,
      grid_rows=grid_rows,
      response_json=response_json,
      validation=validation,
      batch_summaries=batch_summaries,
    ),
  )
  print(f"Quarter grid probe saved to: {report_path}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
