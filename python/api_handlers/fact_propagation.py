from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Tuple


def _normalize_name(value: Any) -> str:
  return " ".join(str(value or "").strip().lower().split())


def _product_key(lob_name: str, product_name: str) -> str:
  return f"{_normalize_name(lob_name)}::{_normalize_name(product_name)}"


def _iter_lob_products(lobs: Iterable[Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip()
    if not lob_name:
      continue
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip()
      if not product_name:
        continue
      yield _product_key(lob_name, product_name), product


def _collect_products(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  for container_key in ("lobs", "lob_models"):
    lobs = payload.get(container_key)
    if isinstance(lobs, list):
      return {key: prod for key, prod in _iter_lob_products(lobs)}
  return {}


def _diff_top_level(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
  diff: Dict[str, Any] = {}
  for key, value in after.items():
    if key not in before or before.get(key) != value:
      diff[key] = value
  return diff


def _diff_products(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  diff: Dict[str, Dict[str, Any]] = {}
  before_products = _collect_products(before)
  after_products = _collect_products(after)
  for key, after_product in after_products.items():
    before_product = before_products.get(key, {})
    if not isinstance(before_product, dict):
      before_product = {}
    changed: Dict[str, Any] = {}
    for field, value in after_product.items():
      if field not in before_product or before_product.get(field) != value:
        changed[field] = value
    if changed:
      diff[key] = changed
  return diff


def _apply_top_level_updates(target: Dict[str, Any], updates: Dict[str, Any]) -> bool:
  changed = False
  for key, value in updates.items():
    if key in target and target.get(key) != value:
      target[key] = value
      changed = True
  return changed


def _apply_product_updates(target: Dict[str, Any], product_updates: Dict[str, Dict[str, Any]]) -> bool:
  changed = False
  for container_key in ("lob_models", "lobs"):
    lobs = target.get(container_key)
    if not isinstance(lobs, list):
      continue
    for key, product in _iter_lob_products(lobs):
      updates = product_updates.get(key)
      if not updates:
        continue
      for field, value in updates.items():
        if field in product and product.get(field) != value:
          product[field] = value
          changed = True
  return changed


def propagate_shared_facts(
  *,
  source_consult_type: str,
  before_json: Dict[str, Any],
  after_json: Dict[str, Any],
  consult_jsons: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
  if not isinstance(before_json, dict) or not isinstance(after_json, dict):
    return consult_jsons, False

  top_level_updates = _diff_top_level(before_json, after_json)
  product_updates = _diff_products(before_json, after_json)

  updated: Dict[str, Any] = {}
  propagated = False

  for consult_name, consult_payload in consult_jsons.items():
    if consult_name == source_consult_type:
      updated[consult_name] = after_json
      continue
    if not isinstance(consult_payload, dict):
      updated[consult_name] = consult_payload
      continue

    payload = json.loads(json.dumps(consult_payload, ensure_ascii=False))
    touched = False
    touched = _apply_top_level_updates(payload, top_level_updates) or touched
    touched = _apply_product_updates(payload, product_updates) or touched

    if touched:
      propagated = True
    updated[consult_name] = payload

  if source_consult_type not in updated:
    updated[source_consult_type] = after_json

  return updated, propagated
