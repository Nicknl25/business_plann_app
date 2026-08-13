"""CW-031 round 9 -- the GREEN half: every fix asserted on the real modules.

Covers the round-9 batch (mini's round-8 audit, Nick's rulings applied):
  1  THE NET ASKS, NEVER STORES -- uniform post-write rates at N>=3 earn a
     question in the receipt; nothing is stamped on any row; a client-declared
     partial group SURVIVES a coinciding write (the A2 clobber is dead); the
     ask fires once, when the write CREATES the uniformity.
  2  ONLY A DECLARATION IS AUTHORITY at the gate -- a declared all-lines
     collapse passes; an inferred-basis group fails; uniform-with-no-group
     fails with the ask vocabulary.
  3  THE SEPARATION DOOR -- "keep X separate" clears the row's group+basis;
     the coherence pass retires stale labels from rows whose declared group no
     longer exists as declared; the receipt names everything it touched.
  4  F1 -- prose that acknowledges a figure no receipt carries is detected
     (_prose_acks_unwritten_figure), in both units, while honest asks and
     question-turn answers survive.
  6  THE PROBE -- a zero-message draft no longer blocks the backend restart;
     one client message restores the protection (real DB, temp row).

Run the RED half after this: Test Files/_redproof_cw031_round9_ablate.py

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_round9_fixes.py"
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FINDINGS: list = []


def note(tag: str, ok: bool, detail: str) -> None:
  verdict = "PASS" if ok else "FAIL"
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
  import intent_router as irt  # type: ignore

  P = lambda name, **kw: dict({"product_name": name, "unit_price": 40.0,
                               "units_per_period_capacity": 100.0}, **kw)

  def door(patch, ops):
    return ic._apply_per_line_cogs_patch_keys(patch, ops_json=ops)

  def assert_on(ops):
    orig = ir._load_ops_model
    ir._load_ops_model = lambda cur, d: ops
    try:
      return ir._assert_ops_per_line_cogs(None, "synthetic", {})
    finally:
      ir._load_ops_model = orig

  # ---- 1 THE NET ASKS, NEVER STORES --------------------------------------
  ops = ops_of(P("plant sale", cogs_percent_of_line_revenue=0.55),
               P("hard goods sale", cogs_percent_of_line_revenue=0.55),
               P("install project"))
  r = door({"financials.cogs_per_line_overrides": [
    {"line_name": "install project", "cogs_percent": 55,
     "cogs_percent_unit": "percent"}]}, ops)
  grouped_rows = [x for x in rows_of(ops) if x.get("cogs_cost_structure_group")]
  ask = r.get("uniform_rate_ask")
  note("1a uniform write stores NO group", not grouped_rows,
       f"rows carrying a group={len(grouped_rows)}")
  note("1b receipt carries the ask",
       isinstance(ask, dict) and ask.get("count") == 3
       and abs(float(ask.get("rate") or 0) - 0.55) < 1e-9,
       f"uniform_rate_ask={ask}")
  text = ic._build_per_line_cogs_receipt_text(r)
  note("1c the receipt SPEAKS the ask",
       "same rate on all 3 lines" in text and "keep them separate?" in text,
       f"text={text!r}")

  # 1d fires once: echo of an already-uniform state neither stores nor re-asks
  ops = ops_of(P("a", cogs_percent_of_line_revenue=0.55),
               P("b", cogs_percent_of_line_revenue=0.55),
               P("c", cogs_percent_of_line_revenue=0.55))
  r = door({"financials.cogs_per_line_overrides": [
    {"line_name": "a", "cogs_percent": 55, "cogs_percent_unit": "percent"}]}, ops)
  note("1d echo of uniform state: no store, no re-ask",
       not r.get("uniform_rate_ask")
       and not any(x.get("cogs_cost_structure_group") for x in rows_of(ops)),
       f"ask={r.get('uniform_rate_ask')}")

  # 1e THE A2 CLOBBER IS DEAD: a declared partial group survives a coinciding
  # write byte-for-byte (AN INFERENCE NEVER OVERWRITES A DECLARED STAMP).
  shared = "shared:hard goods sale+plant sale"
  ops = ops_of(
    P("plant sale", cogs_percent_of_line_revenue=0.55,
      cogs_cost_structure_group=shared, cogs_cost_structure_group_basis="declared"),
    P("hard goods sale", cogs_percent_of_line_revenue=0.55,
      cogs_cost_structure_group=shared, cogs_cost_structure_group_basis="declared"),
    P("install project", cogs_percent_of_line_revenue=0.55),
    P("design consult"))
  r = door({"financials.cogs_per_line_overrides": [
    {"line_name": "design consult", "cogs_percent": 55,
     "cogs_percent_unit": "percent"}]}, ops)
  plant = next(x for x in rows_of(ops) if x["product_name"] == "plant sale")
  note("1e declared partial group SURVIVES a coinciding write",
       plant.get("cogs_cost_structure_group") == shared
       and plant.get("cogs_cost_structure_group_basis") == "declared"
       and isinstance(r.get("uniform_rate_ask"), dict),
       f"group={plant.get('cogs_cost_structure_group')!r} "
       f"basis={plant.get('cogs_cost_structure_group_basis')!r} "
       f"ask fired={bool(r.get('uniform_rate_ask'))}")

  # 1f N=2: a coincidence is all it would take, so no ask and no store.
  ops = ops_of(P("a", cogs_percent_of_line_revenue=0.4), P("b"))
  r = door({"financials.cogs_per_line_overrides": [
    {"line_name": "b", "cogs_percent": 40, "cogs_percent_unit": "percent"}]}, ops)
  note("1f N=2 uniform: no ask, no store",
       not r.get("uniform_rate_ask")
       and not any(x.get("cogs_cost_structure_group") for x in rows_of(ops)),
       f"ask={r.get('uniform_rate_ask')}")

  # 1g an all-lines DECLARED collapse suppresses the ask (already answered).
  ops = ops_of(P("a", cogs_percent_of_line_revenue=0.5),
               P("b", cogs_percent_of_line_revenue=0.5),
               P("c"))
  r = door({
    "financials.cogs_shared_structure_groups": [["a", "b", "c"]],
  }, ops)
  labels = {x.get("cogs_cost_structure_group") for x in rows_of(ops)}
  note("1g declared all-lines group: stored, basis declared, no ask",
       len(labels) == 1 and next(iter(labels))
       and all(x.get("cogs_cost_structure_group_basis") == "declared"
               for x in rows_of(ops))
       and not r.get("uniform_rate_ask"),
       f"labels={labels}, ask={r.get('uniform_rate_ask')}")

  # ---- 2 ONLY A DECLARATION IS AUTHORITY AT THE GATE ---------------------
  G = "shared:a+b+c"
  ops = ops_of(*[P(n, cogs_percent_of_line_revenue=0.55,
                   cogs_cost_structure_group=G,
                   cogs_cost_structure_group_basis="declared")
                 for n in ("a", "b", "c")])
  v = assert_on(ops)
  note("2a declared all-lines collapse PASSES",
       v["verdict"] == "pass" and "client's own recorded collapse" in v["detail"],
       f"{v['verdict']}: {v['detail']}")

  ops = ops_of(*[P(n, cogs_percent_of_line_revenue=0.55,
                   cogs_cost_structure_group=G,
                   cogs_cost_structure_group_basis="inferred from identical stated rates")
                 for n in ("a", "b", "c")])
  v = assert_on(ops)
  note("2b inferred-basis group FAILS the gate",
       v["verdict"] == "fail" and "not authority" in v["detail"],
       f"{v['verdict']}: {v['detail']}")

  ops = ops_of(*[P(n, cogs_percent_of_line_revenue=0.55) for n in ("a", "b", "c")])
  v = assert_on(ops)
  note("2c uniform with no group FAILS with the ask vocabulary",
       v["verdict"] == "fail" and "the app asks" in v["detail"],
       f"{v['verdict']}: {v['detail']}")

  ops = ops_of(P("a", cogs_percent_of_line_revenue=0.5),
               P("b", cogs_percent_of_line_revenue=0.3),
               P("c", cogs_percent_of_line_revenue=0.1))
  v = assert_on(ops)
  note("2d distinct rates still PASS", v["verdict"] == "pass",
       f"{v['verdict']}: {v['detail']}")

  # ---- 3 THE SEPARATION DOOR ---------------------------------------------
  ALL = "shared:design consult+hard goods sale+install project+plant sale"
  def _all_grouped():
    return ops_of(*[P(n, cogs_percent_of_line_revenue=0.55,
                      cogs_cost_structure_group=ALL,
                      cogs_cost_structure_group_basis="declared")
                    for n in ("plant sale", "hard goods sale",
                              "install project", "design consult")])

  ops = _all_grouped()
  r = door({"financials.cogs_separate_lines": ["design consult"]}, ops)
  design = next(x for x in rows_of(ops) if x["product_name"] == "design consult")
  others = [x for x in rows_of(ops) if x["product_name"] != "design consult"]
  note("3a separation clears the named row's group AND basis",
       "cogs_cost_structure_group" not in design
       and "cogs_cost_structure_group_basis" not in design,
       f"design row keys={sorted(k for k in design if 'group' in k)}")
  note("3b the stale label is retired from the rows left behind",
       all("cogs_cost_structure_group" not in x for x in others)
       and len(r.get("ungrouped") or []) == 3,
       f"ungrouped={r.get('ungrouped')}")
  text = ic._build_per_line_cogs_receipt_text(r)
  note("3c the receipt names the separation and the retirement",
       "own separate cost structure" in text
       and "no longer covers" in text,
       f"text={text!r}")

  ops = _all_grouped()
  r = door({"financials.cogs_separate_lines": ["the gizmo department"]}, ops)
  note("3d an unresolvable name refuses: nothing cleared, unmatched says so",
       "the gizmo department" in (r.get("unmatched") or [])
       and all(x.get("cogs_cost_structure_group") == ALL for x in rows_of(ops)),
       f"unmatched={r.get('unmatched')}")

  # 3e a REGROUP write retires the departing row's stale label via the same
  # coherence pass (the group-write half of the remover).
  ops = _all_grouped()
  r = door({"financials.cogs_shared_structure_groups": [
    ["plant sale", "hard goods sale", "install project"]]}, ops)
  design = next(x for x in rows_of(ops) if x["product_name"] == "design consult")
  note("3e a regroup clears the stale label from the row it leaves out",
       "cogs_cost_structure_group" not in design
       and design["product_name"] in " ".join(r.get("ungrouped") or []).lower()
       or "design consult" in [u.lower().split(" / ")[-1] for u in (r.get("ungrouped") or [])],
       f"design group={design.get('cogs_cost_structure_group')!r} "
       f"ungrouped={r.get('ungrouped')}")

  ops = ops_of(P("a", cogs_percent_of_line_revenue=0.5), P("b"))
  r = door({"financials.cogs_separate_lines": ["a"]}, ops)
  note("3f separating an ungrouped line is a no-op that still speaks",
       not r.get("wrote") and r.get("separated") == ["Garden / a"],
       f"wrote={r.get('wrote')} separated={r.get('separated')}")

  # ---- 4 F1: A FIGURE NO RECEIPT CARRIES MAY NOT BE ACKNOWLEDGED ---------
  pred = lambda prose, msg: ic._prose_acks_unwritten_figure(
    prose=prose, user_message=msg)
  note("4a mini's A-B2 reply is caught",
       pred("Got it, thank you for sharing that your blended direct-cost "
            "ratio is 0.44.",
            "Our blended direct-cost ratio is 0.44."),
       "ack of a stated 0.44 with no write")
  note("4b mini's A-B3 reply is caught",
       pred("Got it, you'd like the COGS percent of revenue field updated "
            "to 38%.",
            "Please set cogs percent of revenue to 38."),
       "ack of a stated 38 with no write")
  note("4c an honest ask about the figure SURVIVES",
       not pred("Just to be sure - was that 0.44 a percent of revenue, or "
                "a ratio?",
                "Our blended direct-cost ratio is 0.44."),
       "a question about the figure is an ask, not a claim")
  note("4d a question turn may quote figures back",
       not pred("Your direct costs are recorded at 0.44 of revenue.",
                "Is my blended ratio 0.44?"),
       "the client asked; the answer may say the number")
  note("4e a unit-scaled echo is caught (38 <-> 0.38)",
       pred("Got it - we'll use 0.38 for that.",
            "Please set cogs percent of revenue to 38."),
       "the converted restatement is the same claim")
  note("4f figure-free prose survives",
       not pred("Got it - what does a typical month of rent look like?",
                "Our blended direct-cost ratio is 0.44."),
       "no figure, no claim")

  # ---- 5 ROUTER SURFACE ---------------------------------------------------
  schema = irt._value_schema_by_consult_field(consult_type="financials")
  note("5a cogs_separate_lines is a router field",
       schema.get("cogs_separate_lines", {}).get("type") == "array"
       and "cogs_separate_lines" in irt._PER_LINE_COGS_FIELDS,
       "schema entry + gated with the other per-line fields")
  rated = {"operating_model": ops_of(
    P("a", cogs_percent_of_line_revenue=0.5),
    P("b", cogs_percent_of_line_revenue=0.3))}
  unrated = {"operating_model": ops_of(
    P("a", cogs_percent_of_line_revenue=0.5), P("b"))}
  single = {"operating_model": ops_of(P("a", cogs_percent_of_line_revenue=0.5))}
  note("5b the fully-rated detector is right on all three shapes",
       irt._draft_all_lines_carry_cogs_rates(rated)
       and not irt._draft_all_lines_carry_cogs_rates(unrated)
       and not irt._draft_all_lines_carry_cogs_rates(single),
       "rated=True unrated=False single-line=False")

  # ---- 6 THE PROBE ON THE REAL DB ----------------------------------------
  try:
    sys.path.insert(0, str(REPO_ROOT / "python"))
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
    from intake_submission import get_mysql_connection  # type: ignore
    import subprocess
    conn = get_mysql_connection()
    conn.autocommit = True
    cur = conn.cursor()
    probe_draft = "r9probe" + uuid.uuid4().hex[:8]
    cur.execute(
      "INSERT INTO intake_consult_drafts (draft_id, client_id, status, "
      "messages_json, created_at, updated_at) "
      "VALUES (%s, %s, 'in_progress', '[]', NOW(), NOW())",
      (probe_draft, "r9probe-client"),
    )
    def run_probe() -> str:
      out = subprocess.run(
        [str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
         str(REPO_ROOT / "scripts" / "_active_intake_probe.py")],
        capture_output=True, text=True, timeout=60)
      return (out.stdout or "").strip()
    got = run_probe()
    note("6a a zero-message draft does NOT block the restart",
         probe_draft not in got, f"probe printed {got!r}")
    cur.execute(
      "UPDATE intake_consult_drafts SET messages_json = %s, updated_at = NOW() "
      "WHERE draft_id = %s",
      ('[{"role": "user", "content": "hello"}]', probe_draft),
    )
    got = run_probe()
    note("6b one client message restores the protection",
         probe_draft in got.splitlines() or got == probe_draft,
         f"probe printed {got!r}")
    cur.execute("DELETE FROM intake_consult_drafts WHERE draft_id = %s",
                (probe_draft,))
    conn.close()
  except Exception as exc:  # noqa: BLE001
    note("6a/6b probe on real DB", False, f"exception: {exc!r}")

  fails = [f for f in FINDINGS if f[1] == "FAIL"]
  print(f"\n{len(FINDINGS)} checks, {len(fails)} FAIL")
  return 1 if fails else 0


if __name__ == "__main__":
  raise SystemExit(main())
