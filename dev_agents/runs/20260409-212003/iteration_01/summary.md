Run failed in unknown quarter

Root cause:
- primary: system_run_failed
- secondary: backend_pipeline_failure
- affected rows: n/a
- band violation: Traceback (most recent call last):
  File "C:\dev\business_plann_app\Test Files\run_live_args_intake_1_product.py", line 21, in <module>
    raise SystemExit(mod.main(sys.argv[1:], forced_product_count=1))
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\dev\busines

Feasibility:
- cash too tight: False
- levers insufficient: False
- engine overpowered: False
- recommendation: Current run is solver-feasible under the current cash bands.

Fix applied:
- Extend local JSON-schema $ref resolver to support nested $defs paths so specialist output schemas validate correctly instead of throwing 'Unknown local schema ref' and causing system_run_failed.

Fix proposed:
- none

Fix status:
- applied count: 1
- applicable count: 1
- changed files: python/client_intake_and_finmo/app_agents/schema_validation.py

Replay result:
- moved failure: n/a
- shape change: unknown

Decision:
- continue
- Applied at least one fix; continue iteration.