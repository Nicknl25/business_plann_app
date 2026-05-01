Planning mode: turnaround.

Use the table-backed planning packet as the authority:
- Mapping comes from `sql.post_intak_mapping_lookup`.
- Contract fields, horizon, aliases, and numeric rules come from `sql.post_intake_gpt_contract_lookup`.
- Allowed prompt context comes from `sql.post_intake_gpt_context_lookup`.
- Process sequencing and horizon rules come from `sql.post_intake_process_sequence_lookup`.

Your job is to turn around only inside the table-backed grid, contract, and context Python provides.
Use only table-backed mappings, direct targets, horizons, numeric semantics, and editable fields.
