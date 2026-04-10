from __future__ import annotations

from typing import Any, Dict, List

from .schema_loader import load_schema


def _unwrap_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
  """If the loaded schema is wrapped, return the inner schema object.

  Some loaders wrap the actual JSON-schema under a top-level "schema" key.
  The validator wants the bare JSON-schema object.
  """
  if isinstance(schema.get("schema"), dict):
    return schema.get("schema")  # type: ignore[return-value]
  return schema


def _resolve_ref(schema: Dict[str, Any], ref: str) -> Dict[str, Any]:
  """Resolve a limited set of $ref patterns used in our app-agent schemas.

  Supported forms:
  - local defs:   "#/$defs/<name>" or "#/$defs/path/with/slashes" (full path after $defs)
  - file include: "./other_schema.json" (delegated to schema_loader)

  Anything else is treated as unsupported to avoid silently accepting
  references we don't actually know how to resolve.
  """
  pointer = str(ref or "").strip()

  # Local $defs references
  if pointer.startswith("#/$defs/"):
    # Everything after "#/$defs/" is treated as the key path inside $defs.
    # This allows future nested-defs like "#/$defs/nested/constraint" to work
    # as long as the schema stores them under that exact key string.
    key_path = pointer[len("#/$defs/"):]
    defs = schema.get("$defs") if isinstance(schema.get("$defs"), dict) else {}
    target = defs.get(key_path)
    if not isinstance(target, dict):
      # Fall back to simple single-segment lookup if someone wrote
      # "#/$defs/constraint" but stored it under a nested object structure.
      # This keeps behavior compatible with older flat-defs contracts while
      # remaining explicit when a ref truly cannot be resolved.
      if "/" not in key_path:
        raise ValueError(f"Unknown local schema ref: {ref}")
      first, *_rest = key_path.split("/", 1)
      nested = defs.get(first)
      if not isinstance(nested, dict):
        raise ValueError(f"Unknown local schema ref: {ref}")
      # If nested is an object that itself looks like a full schema, use it
      # as the resolution target. This is sufficient for the app-agent
      # schemas, which only use one level of indirection today.
      target = nested
      if not isinstance(target, dict):
        raise ValueError(f"Unknown local schema ref: {ref}")
    return target

  # Cross-file include (used by some app-agent schemas)
  if pointer.startswith("./"):
    included = load_schema(pointer[2:])
    return _unwrap_schema(included)

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
  # Handle $ref indirection first so downstream logic always sees a concrete node.
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
  """Validate data against a JSON-schema object.

  The validator intentionally implements only the subset of JSON Schema we
  need for the app-agent contracts (types, enums, const, min/max, required,
  additionalProperties, nested objects/arrays, and a limited $ref form).

  It returns a list of human-readable error strings; an empty list means the
  payload conformed to the schema.
  """
  schema_root = _unwrap_schema(schema)
  errors: List[str] = []
  _validate(schema_root, schema_root, data, "$", errors)
  return errors
