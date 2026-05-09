# Phase 9 — Excel Workbook Delivery Diagnosis

**Run timestamp:** 2026-05-09
**Subject draft:** ExpressLogix `398986f44cec43589a0db2ac001d4a03` (most recent E2E)
**Symptom:** No Excel file produced after the run completed.

---

## Pipeline trace

[Test Files/run_persisted_system_run.py:436-449](Test%20Files/run_persisted_system_run.py#L436-L449)
POSTs to `/api/intake-consult/system-run`, then reads
`client_workbook_path` from the JSON response. If the field is empty,
nothing is printed. If the POST raises (HTTP error), the test runner's
`except Exception` block at line 478 prints `ERROR: ...` and exits 1
without ever attempting workbook resolution.

The server-side handler is
[python/api_handlers/intake_consult.py:7188-7273](python/api_handlers/intake_consult.py#L7188-L7273):

1. `_run_unified_post_grid_system_run(...)` returns `result`
   (planning_run, finmo, model_input, etc. — no workbook yet).
2. `verify_run_acceptance(...)` runs the 16-check acceptance gate.
3. **If `acceptance_verdict["passed"]` is False, the handler returns
   HTTP 500 with `{"error": "acceptance_gate_failed",
   "acceptance_verdict": ...}`.** Workbook export never runs.
4. Only on `passed = True` does the handler call
   `export_workbook_for_draft_id(draft_id, conn)` and return the
   resulting path in `client_workbook_path`.

```python
if not bool(acceptance_verdict.get("passed")):
    app.logger.error(...)
    return jsonify({"error": "acceptance_gate_failed", ...}), 500

client_workbook_path = ""
try:
    from client_statements_output_excel.export_client_workbook import (
        export_workbook_for_draft_id,
    )
    client_workbook_path = str(
        export_workbook_for_draft_id(draft_id=result_draft_id, conn=conn)
    )
except Exception as exc:
    ...
    return jsonify({"error": "client_workbook_export_failed", ...}), 500
```

The previous ExpressLogix run finished with the acceptance verdict
**13/16 (passed=False)** per
[docs/phase_9_realism_audit_test_run.md](docs/phase_9_realism_audit_test_run.md).
That triggered the short-circuit at step 3. The HTTP 500 with
`acceptance_gate_failed` is exactly what the test runner caught, which
is why no `client_workbook_path` made it back to the runner output.

---

## Conclusion

Workbook delivery is **gated on acceptance.passed=True**. There is no
silent workbook failure — `export_workbook_for_draft_id` was never
invoked. This is intentional doctrine (Phase 8: "the gate is the
authority on whether this run actually succeeded — a failed verdict
short-circuits the workbook export") but it has the side effect that
**every acceptance failure produces zero visibility into the model
that was actually generated.** A user iterating to fix acceptance
issues can't open the Excel to see the underlying numbers.

---

## Triage options (no code change in this PR)

1. **Allow workbook export on acceptance failure**, with the verdict
   embedded as a sheet so the user can inspect what failed and the
   numbers behind it. This is the user-experience win.
2. **Keep the short-circuit**, but persist the workbook to a separate
   path (`<draft>_failed_acceptance.xlsx`) so QA can inspect when
   needed.
3. **Status quo** — accept that no acceptance fail = no workbook.

The Task 1+2 cleanup (cash-strategy metrics out of realism gate;
current_ratio cash-excluded) plus the Task 3 cascade fixes
(trajectory_check routing, direction-aware lift) should unblock the
acceptance gate on ExpressLogix without the workbook flow needing
to change. If the upcoming E2E still fails acceptance, option 1 or
2 becomes urgent. Until then this is a documentation note, not a
code change.
