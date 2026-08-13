"""CW-031 round-8 mini audit -- ITEM 4: the post-write minting net, adversarially.

The net (intake_consult._apply_per_line_cogs_patch_keys, tail block) fires when
THIS patch wrote a per-line rate, N >= 3, no all-lines group in THIS patch's
receipt, and all N rows now coincide. Attacks:

  A1  baseline: multi-message uniform. ROUND 9 RE-POINT (VS): the ruling
      landed -- THE NET STORES NOTHING and the receipt ASKS instead. A1 now
      asserts the new law (no group stored, no basis stamped, uniform_rate_ask
      present in the receipt). The original assertion (an inferred mint) pinned
      the superseded round-8 design and could never go green after the fix.
  A2  A DECLARED partial group is CLOBBERED by the inferred all-lines mint:
      client declared plants+hard goods share; install coincides; patch writes
      design at the same rate. Does the client's declaration survive?
  A3  unset attempt: a null/empty figure through the door -- refused? and is
      there ANY path that removes a stored group? (static answer: no remover
      exists; here we prove the door refuses the null write.)
  A4  a patch with NO transport keys (lob restatement / coherence lever /
      passing read) while all rows already coincide -- must NOT mint.
  A5  re-ask echo: one line's EXISTING rate re-stated verbatim while all rows
      already coincide -- fires the net on an echo?
  A6  the artifact assertion on each outcome (item 1 evidence): does an
      inferred group PASS, and what does the verdict cite?

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r8_net_attack.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FINDINGS: list = []


def note(tag: str, verdict: str, detail: str) -> None:
  print(f"  [{verdict}] {tag}: {detail}")
  FINDINGS.append((tag, verdict, detail))


def ops_of(*rows, lob="Garden"):
  return {"lob_models": [{"lob_name": lob, "products": [dict(r) for r in rows]}]}


def rows_of(ops):
  out = []
  for lob in ops.get("lob_models") or []:
    out.extend(lob.get("products") or [])
  return out


def main() -> int:
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from api_handlers import intake_consult as ic  # type: ignore
  import issue_registry as ir  # type: ignore

  P = lambda name, **kw: dict({"product_name": name, "unit_price": 40.0,
                               "units_per_period_capacity": 100.0}, **kw)

  # ---- A1 baseline: multi-message uniform fires the net -------------------
  ops = ops_of(P("plant sale", cogs_percent_of_line_revenue=0.55),
               P("hard goods sale", cogs_percent_of_line_revenue=0.55),
               P("install project"))
  receipt = ic._apply_per_line_cogs_patch_keys(
    {"financials.cogs_per_line_overrides": [
      {"line_name": "install project", "cogs_percent": 55, "cogs_percent_unit": "percent"}]},
    ops_json=ops)
  minted = [g for g in receipt["grouped"] if g.get("all_lines")]
  grouped_rows = [r for r in rows_of(ops) if r.get("cogs_cost_structure_group")]
  ask = receipt.get("uniform_rate_ask")
  a1_ok = (not minted and not grouped_rows
           and isinstance(ask, dict) and ask.get("count") == 3)
  note("A1-uniform-asks-never-stores", "PASS" if a1_ok else "FAIL",
       f"stored groups={len(grouped_rows)}, minted={bool(minted)}, "
       f"uniform_rate_ask={ask} (the net must ask, not store)")

  # ---- A2 declared partial group clobbered --------------------------------
  shared = "shared:hard goods sale+plant sale"
  ops = ops_of(
    P("plant sale", cogs_percent_of_line_revenue=0.55,
      cogs_cost_structure_group=shared, cogs_cost_structure_group_basis="declared"),
    P("hard goods sale", cogs_percent_of_line_revenue=0.55,
      cogs_cost_structure_group=shared, cogs_cost_structure_group_basis="declared"),
    P("install project", cogs_percent_of_line_revenue=0.55),  # coincidence
    P("design consult"))
  receipt = ic._apply_per_line_cogs_patch_keys(
    {"financials.cogs_per_line_overrides": [
      {"line_name": "design consult", "cogs_percent": 55, "cogs_percent_unit": "percent"}]},
    ops_json=ops)
  after = rows_of(ops)
  plant = next(r for r in after if r["product_name"] == "plant sale")
  survived = plant.get("cogs_cost_structure_group") == shared and \
             plant.get("cogs_cost_structure_group_basis") == "declared"
  note("A2-declared-group-survives", "PASS" if survived else "FAIL",
       f"plant sale row after patch: group={plant.get('cogs_cost_structure_group')!r} "
       f"basis={plant.get('cogs_cost_structure_group_basis')!r} "
       f"(declared partial group {'survived' if survived else 'was CLOBBERED by the inferred net'})")
  a2_ops = ops  # kept for A6

  # ---- A3 unset attempt ---------------------------------------------------
  ops = ops_of(P("plant sale", cogs_percent_of_line_revenue=0.55),
               P("hard goods sale", cogs_percent_of_line_revenue=0.55),
               P("install project", cogs_percent_of_line_revenue=0.55))
  for val in (None, "", "unset"):
    receipt = ic._apply_per_line_cogs_patch_keys(
      {"financials.cogs_per_line_overrides": [
        {"line_name": "install project", "cogs_percent": val, "cogs_percent_unit": "percent"}]},
      ops_json=ops)
    row = next(r for r in rows_of(ops) if r["product_name"] == "install project")
    still = row.get("cogs_percent_of_line_revenue") == 0.55
    wrote = bool(receipt["written"])
    note(f"A3-unset-{val!r}", "PASS" if (still and not wrote) else "FAIL",
         f"rate still 0.55={still}, wrote={wrote}, minted={any(g.get('all_lines') for g in receipt['grouped'])}")

  # ---- A4 no transport keys => no mint ------------------------------------
  ops = ops_of(P("plant sale", cogs_percent_of_line_revenue=0.55),
               P("hard goods sale", cogs_percent_of_line_revenue=0.55),
               P("install project", cogs_percent_of_line_revenue=0.55))
  receipt = ic._apply_per_line_cogs_patch_keys(
    {"financials.marketing_total_year1": 12000, "ops.hours_per_week": 40},
    ops_json=ops)
  minted = any(g.get("all_lines") for g in receipt["grouped"])
  grouped_rows = [r for r in rows_of(ops) if r.get("cogs_cost_structure_group")]
  note("A4-passing-read-no-mint", "PASS" if not minted and not grouped_rows else "FAIL",
       f"minted={minted}, rows carrying a group after non-COGS patch={len(grouped_rows)}")

  # ---- A5 re-ask echo of an existing rate ---------------------------------
  ops = ops_of(P("plant sale", cogs_percent_of_line_revenue=0.55),
               P("hard goods sale", cogs_percent_of_line_revenue=0.55),
               P("install project", cogs_percent_of_line_revenue=0.55))
  receipt = ic._apply_per_line_cogs_patch_keys(
    {"financials.cogs_per_line_overrides": [
      {"line_name": "plant sale", "cogs_percent": 55, "cogs_percent_unit": "percent"}]},
    ops_json=ops)
  minted = any(g.get("all_lines") for g in receipt["grouped"])
  note("A5-echo-mints", "INFO",
       f"re-stating one line's existing rate minted an inferred all-lines group: {minted}")

  # ---- A6 the assertion on each outcome (item 1 evidence) -----------------
  def assert_on(ops):
    orig = ir._load_ops_model
    ir._load_ops_model = lambda cur, d: ops
    try:
      return ir._assert_ops_per_line_cogs(None, "synthetic", {})
    finally:
      ir._load_ops_model = orig

  # A6a: the A2 outcome (whatever it is) through the gate
  v = assert_on(a2_ops)
  note("A6a-assertion-on-A2-outcome", "INFO", f"verdict={v['verdict']}; {v['detail']}")

  # A6b: pure inferred all-lines group (A1 shape completed)
  ops = ops_of(P("a", cogs_percent_of_line_revenue=0.55,
                 cogs_cost_structure_group="shared:a+b+c",
                 cogs_cost_structure_group_basis="inferred from identical stated rates"),
               P("b", cogs_percent_of_line_revenue=0.55,
                 cogs_cost_structure_group="shared:a+b+c",
                 cogs_cost_structure_group_basis="inferred from identical stated rates"),
               P("c", cogs_percent_of_line_revenue=0.55,
                 cogs_cost_structure_group="shared:a+b+c",
                 cogs_cost_structure_group_basis="inferred from identical stated rates"))
  v = assert_on(ops)
  note("A6b-inferred-group-verdict", "INFO", f"verdict={v['verdict']}; {v['detail']}")

  fails = [f for f in FINDINGS if f[1] == "FAIL"]
  print(f"\n{len(FINDINGS)} checks, {len(fails)} FAIL")
  return 1 if fails else 0


if __name__ == "__main__":
  raise SystemExit(main())
