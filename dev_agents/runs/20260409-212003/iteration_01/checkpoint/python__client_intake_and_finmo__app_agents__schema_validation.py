from __future__ import annotations

from typing import Any, Dict, List

from .schema_loader import load_schema


def _unwrap_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
  if isinstance(schema.get("schema"), dict):
    return schema.get("schema")  # type: ignore[return-value]
  return schema


def _resolve_ref(schema: Dict[str, Any], ref: str) -> Dict[str, Any]:
  pointer = str(ref or "").strip()
  if pointer.startswith("#/$defs/"):
    key = pointer.split("/", 3)[-1]
    defs = schema.get("$defs") if isinstance(schema.get("$defs"), dict) else {}
    target = defs.get(key)
    if not isinstance(target, dict):
      raise ValueError(f"Unknown local schema ref: {ref}")
    return target
  if pointer.startswith("./"):
    return _unwrap_schema(load_schema(pointer[2:]))
  raise ValueError(f"Unsupported schema ref: {ref}")


def _check_type(value: Any, expected: str) -> bool:
  if expected == "object":
    return isinstance(value, dict)
  if expected == "array":
    return isinstance(value, list)
  if expected == "string":
    return isinstance(value, str)
  if expected == "boolean":
    return isinstance(value, bool)
  if expected == "integer":
    return isinstance(value, int) and not isinstance(value, bool)
  if expected == "number":
    return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
  if expected == "null":
    return value is None
  return True


def _validate(schema_root: Dict[str, Any], schema_node: Dict[str, Any], value: Any, path: str, errors: List[str]) -> None:
  if "$ref" in schema_node:
    ref_schema = _resolve_ref(schema_root, str(schema_node.get("$ref") or ""))
    _validate(schema_root, ref_schema, value, path, errors)
    return

  expected_type = schema_node.get("type")
  if isinstance(expected_type, list):
    if not any(_check_type(value, item) for item in expected_type if isinstance(item, str)):
      errors.append(f"{path}: expected one of {expected_type}")
      return
  elif isinstance(expected_type, str):
    if not _check_type(value, expected_type):
      errors.append(f"{path}: expected {expected_type}")
      return

  if "const" in schema_node and value != schema_node.get("const"):
    errors.append(f"{path}: expected const {schema_node.get('const')!r}")

  enum_values = schema_node.get("enum")
  if isinstance(enum_values, list) and value not in enum_values:
    errors.append(f"{path}: expected one of {enum_values!r}")

  if isinstance(value, (int, float)) and not isinstance(value, bool):
    minimum = schema_node.get("minimum")
    maximum = schema_node.get("maximum")
    if isinstance(minimum, (int, float)) and value < minimum:
      errors.append(f"{path}: value {value} < minimum {minimum}")
    if isinstance(maximum, (int, float)) and value > maximum:
      errors.append(f"{path}: value {value} > maximum {maximum}")

  if isinstance(value, dict):
    properties = schema_node.get("properties") if isinstance(schema_node.get("properties"), dict) else {}
    required = schema_node.get("required") if isinstance(schema_node.get("required"), list) else []
    additional = schema_node.get("additionalProperties", True)
    for key in required:
      if key not in value:
        errors.append(f"{path}: missing required property {key!r}")
    if additional is False:
      for key in value:
        if key not in properties:
          errors.append(f"{path}: unexpected property {key!r}")
    for key, child_schema in properties.items():
      if key in value and isinstance(child_schema, dict):
        child_path = f"{path}.{key}" if path else key
        _validate(schema_root, child_schema, value.get(key), child_path, errors)
    return

  if isinstance(value, list):
    items_schema = schema_node.get("items")
    if isinstance(items_schema, dict):
      for index, item in enumerate(value):
        _validate(schema_root, items_schema, item, f"{path}[{index}]", errors)


def validate_data_against_schema(*, data: Any, schema: Dict[str, Any]) -> List[str]:
  schema_root = _unwrap_schema(schema)
  errors: List[str] = []
  _validate(schema_root, schema_root, data, "$", errors)
  return errors

