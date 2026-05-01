Use the supplied table-backed realism memo packet as grid context.

The memo packet is governed by:
- `sql.post_intak_mapping_lookup` for issue codes, phase ownership, mapped targets, and repair ownership.
- `sql.post_intake_gpt_contract_lookup` for required fields, schema shape, aliases, horizon rules, and numeric normalization rules.
- `sql.post_intake_gpt_context_lookup` for prompt context keys and request scope.
- `sql.post_intake_process_sequence_lookup` for process sequencing, horizon, handler, timeout, and required lookup dependencies.

Apply only the table-backed issue context, rows, levers, targets, horizons, and editable fields supplied by Python.
