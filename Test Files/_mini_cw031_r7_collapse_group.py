"""CW-031 round-7 mini audit -- ITEMS 3 AND 4, ADVERSARIALLY.

Item 3, THE COLLAPSE BASIS ON REAL DRIVER ROWS. VS's plain-average fallback is
proven on synthetic rows. This runs it on the REAL product rows of real drafts
whose weight the function cannot compute, and asks three things:
  (a) does the receipt sentence name the RIGHT lines as unweighted;
  (b) is the average actually over the members it claims;
  (c) does the fallback ever fire on a line that HAS a weight the weight
      function simply cannot SEE (a different field name)? That would be a
      plain average announced where a weighted one was owed.

Item 4, THE ALL-LINES GROUP. It fires only when ONE patch sets EVERY line to
the SAME rate. Two attacks:
  (d) make it fire when the client declared NO collapse -- N=2 makes a genuine
      coincidence cheap;
  (e) make it MISS a real declaration -- four lines set to one rate across TWO
      messages, which is how a client actually talks;
and then run the ARTIFACT ASSERTION on each outcome, because the assertion is
what turns a miss into a filed RECURRENCE.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r7_collapse_group.py"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]

FINDINGS: list = []


def note(tag: str, verdict: str, detail: str) -> None:
  print(f"  [{verdict}] {tag}: {detail}")
  FINDINGS.append((tag, verdict, detail))


def ops_of(*rows, lob="Garden"):
  return {"lob_models": [{"lob_name": lob, "products": [dict(r) for r in rows]}]}


def row_of(ops, name):
  for lob in ops.get("lob_models") or []:
    for product in lob.get("products") or []:
      if str(product.get("product_name")) == name:
        return product
  return {}


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from api_handlers import intake_consult as ic  # type: ignore
  from intake_submission import get_mysql_connection  # type: ignore

  door = ic._apply_per_line_cogs_patch_keys
  say = ic._build_per_line_cogs_receipt_text
  weight = ic._cogs_line_revenue_weight

  # ================================================================= item 3
  print("=" * 78)
  print("ITEM 3 -- THE COLLAPSE BASIS ON REAL DRIVER ROWS")
  print("=" * 78)
  conn = get_mysql_connection()
  cur = conn.cursor()
  cur.execute("SELECT draft_id, business_name, operating_model_json "
              "FROM intake_consult_drafts "
              "WHERE operating_model_json IS NOT NULL AND operating_model_json <> ''")
  drafts = cur.fetchall()
  cur.close()
  conn.close()

  # (c) FIRST, because it decides whether (a)/(b) are even reachable: real rows
  # whose weight the function cannot see, split into "no revenue driver at all"
  # and "a driver under a name the function does not read".
  ALT_DRIVER_KEYS = ("units_per_month_capacity", "avg_units_per_week_year1",
                     "avg_units_per_period_year1", "units_per_year_capacity",
                     "monthly_revenue", "annual_revenue", "revenue_year1",
                     "price", "unit_revenue", "capacity_allocation_share")
  weightless = []
  for draft_id, business_name, ops_raw in drafts:
    try:
      ops = json.loads(ops_raw or "{}")
    except Exception:
      continue
    for lob in ops.get("lob_models") or []:
      if not isinstance(lob, dict):
        continue
      for product in lob.get("products") or []:
        if not isinstance(product, dict):
          continue
        if weight(product) is None:
          alt = {k: product.get(k) for k in ALT_DRIVER_KEYS
                 if isinstance(product.get(k), (int, float))
                 and not isinstance(product.get(k), bool) and float(product.get(k)) > 0}
          weightless.append({
            "draft_id": draft_id, "business": business_name,
            "lob": lob.get("lob_name"), "row": product, "alt": alt,
          })
  print(f"  real product rows whose weight the function returns None for: {len(weightless)}")
  invisible = [w for w in weightless if w["alt"]]
  note("3c invisible-weight rows",
       "CLEAN" if not invisible else "FINDING",
       f"{len(invisible)} of {len(weightless)} weightless rows carry a revenue "
       f"driver under a name _cogs_line_revenue_weight does not read")
  for w in weightless[:8]:
    r = w["row"]
    print(f"    {w['draft_id'][:12]} {str(w['business'])[:22]:<22} "
          f"{str(r.get('product_name'))[:22]:<22} price={r.get('unit_price')!r} "
          f"cap={r.get('units_per_period_capacity')!r}/{r.get('units_per_week_capacity')!r} "
          f"alt={w['alt']}")

  # (a)/(b) on REAL rows: pair a real weightless row with a real weighted row
  # from the SAME draft when possible, otherwise with the real Ravenwood rows.
  if weightless:
    subject = weightless[0]
    sib = None
    for lob in json.loads(
      next(d[2] for d in drafts if d[0] == subject["draft_id"]) or "{}"
    ).get("lob_models") or []:
      for product in lob.get("products") or []:
        if isinstance(product, dict) and product is not subject["row"] \
           and weight(product) is not None:
          sib = product
          break
      if sib:
        break
    if sib is None:
      sib = {"product_name": "Plant sale", "unit_price": 38,
             "units_per_period_capacity": 420, "utilization_rate": 0.62,
             "operating_periods_per_year": 52}
    a_name = str(subject["row"].get("product_name") or "(unnamed)")
    b_name = str(sib.get("product_name") or "(unnamed)")
    ops = ops_of(subject["row"], sib)
    door({"financials.cogs_per_line_overrides": [
      {"line_name": a_name, "cogs_percent": 71, "cogs_percent_unit": "percent"},
      {"line_name": b_name, "cogs_percent": 48, "cogs_percent_unit": "percent"}]},
      ops_json=ops)
    receipt = door({"financials.cogs_shared_structure_groups": [[a_name, b_name]]},
                   ops_json=ops)
    text = say(receipt)
    grouped = (receipt.get("grouped") or [{}])[0]
    landed_a = row_of(ops, a_name).get("cogs_percent_of_line_revenue")
    landed_b = row_of(ops, b_name).get("cogs_percent_of_line_revenue")
    print(f"\n  real weightless row: {subject['draft_id'][:12]} / {a_name!r} "
          f"(weight={weight(subject['row'])!r})")
    print(f"  paired with        : {b_name!r} (weight={weight(sib)!r})")
    print(f"  basis={grouped.get('basis')!r} shared={grouped.get('cogs_percent')!r} "
          f"unweighted={grouped.get('unweighted_lines')!r}")
    print(f"  receipt: {text}")
    plain = round((0.71 + 0.48) / 2, 4)
    note("3a names the right unweighted line",
         "CLEAN" if a_name in " ".join(grouped.get("unweighted_lines") or []) or
                    a_name in text else "FINDING",
         f"unweighted_lines={grouped.get('unweighted_lines')!r}")
    note("3b average is over the members it claims",
         "CLEAN" if grouped.get("cogs_percent") == plain and landed_a == landed_b == plain
         else "FINDING",
         f"shared={grouped.get('cogs_percent')!r} plain-average={plain} "
         f"landed=({landed_a!r}, {landed_b!r})")
  else:
    note("3a/3b", "N/A", "no real weightless product row exists to drive")

  # ================================================================= item 4
  print()
  print("=" * 78)
  print("ITEM 4 -- THE ALL-LINES GROUP, ADVERSARIALLY")
  print("=" * 78)

  def line(name, price=40.0, capacity=120, util=1.0, periods=52):
    return {"product_name": name, "unit_price": price,
            "units_per_period_capacity": capacity, "utilization_rate": util,
            "operating_periods_per_year": periods}

  # (d) N=2 COINCIDENCE, no collapse declared: two lines that genuinely run the
  # same rate, stated in one ordinary message.
  ops2 = ops_of(line("Plant sale"), line("Hard goods sale"))
  r = door({"financials.cogs_per_line_overrides": [
    {"line_name": "Plant sale", "cogs_percent": 55, "cogs_percent_unit": "percent"},
    {"line_name": "Hard goods sale", "cogs_percent": 55, "cogs_percent_unit": "percent"}]},
    ops_json=ops2)
  g2 = row_of(ops2, "Plant sale").get("cogs_cost_structure_group")
  print(f"  (d) N=2 both stated at 55%, no collapse said: group={g2!r}")
  print(f"      receipt: {say(r)}")
  note("4d N=2 coincidence mints a collapse the client never declared",
       "FINDING" if g2 else "CLEAN",
       f"stored group={g2!r} from two independent rates that happen to match")

  # (d2) the same shape at N=4, for contrast -- how cheap is the coincidence?
  ops4 = ops_of(line("A"), line("B"), line("C"), line("D"))
  door({"financials.cogs_per_line_overrides": [
    {"line_name": n, "cogs_percent": 55, "cogs_percent_unit": "percent"}
    for n in ("A", "B", "C", "D")]}, ops_json=ops4)
  note("4d2 same at N=4", "CONTEXT",
       f"group={row_of(ops4, 'A').get('cogs_cost_structure_group')!r} "
       "(four independent rates coinciding is a far less likely accident)")

  # (e) A REAL DECLARATION SPLIT ACROSS TWO MESSAGES.
  ops4b = ops_of(line("A"), line("B"), line("C"), line("D"))
  door({"financials.cogs_per_line_overrides": [
    {"line_name": n, "cogs_percent": 55, "cogs_percent_unit": "percent"}
    for n in ("A", "B")]}, ops_json=ops4b)
  door({"financials.cogs_per_line_overrides": [
    {"line_name": n, "cogs_percent": 55, "cogs_percent_unit": "percent"}
    for n in ("C", "D")]}, ops_json=ops4b)
  groups = {n: row_of(ops4b, n).get("cogs_cost_structure_group") for n in "ABCD"}
  rates = {n: row_of(ops4b, n).get("cogs_percent_of_line_revenue") for n in "ABCD"}
  print(f"\n  (e) 'everything runs at 55' said over TWO messages: rates={rates}")
  print(f"      groups={groups}")
  note("4e a real declaration split over two messages mints no group",
       "FINDING" if not any(groups.values()) else "CLEAN",
       f"groups={groups} -- the artifact assertion reads four identical rates "
       "with no recorded collapse")

  # (f) and what the ASSERTION then does with each artifact.
  import issue_registry as ir  # type: ignore

  class _FakeCur:
    def __init__(self, ops):
      self._ops = ops
    def execute(self, *_a, **_k):
      return None
    def fetchone(self):
      return (json.dumps(self._ops),)
    def close(self):
      return None

  for label, ops_obj in (("(d) N=2 coincidence", ops2),
                         ("(e) two-message declaration", ops4b),
                         ("(d2) N=4 one message", ops4)):
    verdict = ir._assert_ops_per_line_cogs(_FakeCur(ops_obj), "draft", {})
    print(f"  assertion on {label:<28}: {verdict['verdict']:<14} {verdict['detail'][:90]}")
    FINDINGS.append((f"4f assertion {label}", verdict["verdict"], verdict["detail"]))

  print()
  print("=" * 78)
  findings = [f for f in FINDINGS if f[1] == "FINDING"]
  for tag, verdict, detail in FINDINGS:
    print(f"  {verdict:<14} {tag}")
  print(f"  {len(findings)} finding(s)")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
