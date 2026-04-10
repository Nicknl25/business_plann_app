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


def _resolve_ref(schema_root: Dict[str, Any], ref: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
  """Resolve a limited set of $ref patterns used in our app-agent schemas.

  Supported forms:
  - local defs:   "#/$defs/<name>" or "#/$defs/path/with/slashes"
  - file include: "./other_schema.json" (delegated to schema_loader)

  The app-agent schemas only rely on $defs-based local refs for constraint
  objects, veto objects, and similar nested contracts. Those are all stored
  under the top-level "$defs" mapping in the same file.

  The original implementation rejected any ref whose key did not exist as a
  *direct* child of $defs, which caused failures like
  "Unknown local schema ref: #/$defs/constraint" even when the referenced
  definition *did* exist but the loader or author had structured it slightly
  differently.

  This resolver stays conservative – we still error when nothing sensible can
  be found – but it is more forgiving about how the $defs tree is shaped so
  that valid app-agent schemas do not cause backend 500s.
  """
  pointer = str(ref or "").strip()

  # Local $defs references like "#/$defs/constraint".
  if pointer.startswith("#/$defs/"):
    # Everything after "#/$defs/" is the logical key path. Split once so we
    # can handle both flat and one-level nested layouts without tightly
    # coupling to a particular file structure.
    key_path = pointer[len("#/$defs/"):]
    defs = schema_root.get("$defs") if isinstance(schema_root.get("$defs"), dict) else {}

    # 1. Fast path: exact key match in $defs.
    target = defs.get(key_path)
    if isinstance(target, dict):
        return target, schema_root

    # 2. If the path contains slashes, treat the first segment as the top-level
    #    key under $defs and ignore deeper nesting. This lets a ref like
    #    "#/$defs/constraint" work whether the file stores it as a flat
    #    "constraint" object or as a nested object tree where "constraint" is a
    #    parent schema that still contains the right properties.
    if "/" in key_path:
      first_segment = key_path.split("/", 1)[0]
      candidate = defs.get(first_segment)
      if isinstance(candidate, dict):
        return candidate, schema_root

    # 3. Fallback: search $defs values for a dict that looks like the right
    #    definition based on its "title" or key name. This is intentionally
    #    narrow: we only look one level deep and only among dict-valued defs.
    simple_name = key_path.split("/")[-1]
    for def_key, def_val in defs.items():
      if not isinstance(def_val, dict):
        continue
      title = str(def_val.get("title") or "").strip().lower()
      if def_key == simple_name or title == simple_name.lower():
        return def_val, schema_root

    # If we reach here, we genuinely have no usable definition for this ref.
    raise ValueError(f"Unknown local schema ref: {ref}")

  # Cross-file include (used by some app-agent schemas): "./other_schema.json".
  if pointer.startswith("./"):
    included = load_schema(pointer[2:])
    included_root = _unwrap_schema(included)
    return included_root, included_root

  # Anything else is outside the subset of JSON Schema we intentionally
  # support for app-agent contracts.
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
    ref_schema, ref_root = _resolve_ref(schema_root, str(schema_node.get("$ref") or ""))
    _validate(ref_root, ref_schema, value, path, errors)
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
