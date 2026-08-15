"""STREAM DISCOVERY F1+F2+F3 - spot-check red-proof on the EXACT Cormorant
latch input (Nick's ruling 2026-08-15, record
_confirm_discovery_cormorant_20260815.txt).

PRODUCTION CALL CHAIN (named first): the end-of-ops seam ->
_stream_discovery_ask_if_due -> gpt_author_stream_candidates_once (patched
here to return the 8 labels the live judge returned for draft ec1e22ef)
-> validate_stream_candidates (F1 dedup / F2 size-strip / F3 slice)
-> compose_stream_discovery_ask -> latch. The ops_json is the REAL
persisted operating_model_json of ec1e22ef (single line, Coffee Roaster,
NAICS 311920, the client-confirmed description).

PRE-FIX (HEAD before this turn): all 8 dropped, asked:false -> this file
is RED. POST-FIX: retail coffee bags (size stripped) + private label coffee
roasting + office coffee supply accounts SURVIVE and are asked; wholesale
coffee beans + online coffee bean sales STAY deduped; the three `some`
stay dropped. F3: 6 synthetic survivors (2 most, 4 many) -> proposed = the
2 most + first 2 many, the ask names exactly 4; 3 survivors -> all 3.

  .venv\\Scripts\\python.exe "Test Files\\_stream_discovery_f123_redproof.py"
Exit 0 = green.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
try:
  sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
  pass

from api_handlers import intake_consult as ic  # noqa: E402
from client_intake_and_finmo.intake_coherence import gpt_stream_discovery as sd  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
  print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not cond else ""))
  if not cond:
    FAILS.append(name)


# The REAL Cormorant ops_json (draft ec1e22ef, persisted operating_model_json,
# fact templates as stored). Only the latch is removed so discovery is due.
CORMORANT_DESC = (
  "{{fact:business.name}} is a wholesale-focused coffee roastery that buys green coffee, roasts it "
  "in-house, and sells roasted whole-bean coffee primarily in {{fact:ops.unit_name}} units to cafes, "
  "restaurants, and a smaller segment of direct online buyers. Production and delivery are organized on a "
  "{{fact:ops.unit_cadence}} cadence, with roasting and packing scheduled to fill twice-weekly local "
  "delivery routes and ongoing standing orders, and with online orders batched into roast days and shipped "
  "promptly. Day-to-day fulfillment is handled by the owner and an in-house team who manage roasting, "
  "bagging, and local deliveries, while UPS handles parcel shipments for online customers; typical lead "
  "time is a few days from roasting to local delivery and next-business-day handoff to the carrier for "
  "online orders, and practical capacity is primarily constrained by labor on the roaster and packing line "
  "rather than by equipment or demand.\n\nFor planning, each {{fact:ops.unit_name}} is treated as the core "
  "revenue unit, billed on a {{fact:ops.unit_cadence}} cycle at an average price of {{fact:ops.unit_price}}, "
  "with a practical weekly throughput capacity of about {{fact:ops.units_per_week_capacity}} "
  "{{fact:ops.unit_name}} ({{fact:ops.units_per_period_capacity}} per operating period) under the current "
  "team and equipment. The business is organized as a {{fact:ops.legal_entity}}, and standard food/coffee "
  "production requirements (such as food-handling regulations, any required health department or facility "
  "permits, green coffee and packaging supply compliance, and appropriate business/general liability "
  "coverage) are assumed to be built into ongoing operations, recognizing that exact permitting, licensing, "
  "and insurance needs vary by state and local jurisdiction and must be confirmed with local authorities and "
  "advisors."
)


def cormorant_ops():
  return {
    "business_type": "Coffee Roaster",
    "business_naics_6": "311920",
    "business_stage": "operating",
    "consumer_type": "business",
    "geographic_scope": "regional",
    "legal_entity": "LLC",
    "capacity_driver": "labor",
    "primary_growth_lever": "volume",
    "business_description_summary": CORMORANT_DESC,
    "lob_models": [
      {"lob_name": "Roasted coffee", "products": [
        {"product_name": "5 lb bag of roasted coffee", "unit_name": "5 lb bag of roasted coffee",
         "unit_description": "One 5-pound bag of roasted whole-bean coffee, roasted in-house and packed for wholesale or online customers.",
         "unit_cadence": "weekly", "units_per_week_capacity": 420, "units_per_period_capacity": 420,
         "operating_periods_per_year": 52, "utilization_rate": 0.72, "unit_price": 62,
         "cogs_percent_of_line_revenue": None, "origin": None},
      ]},
    ],
  }


# The 8 labels the LIVE judge returned for ec1e22ef, band as returned.
CORMORANT_JUDGE = [
  {"label": "12 oz retail coffee bags", "commonality": "most"},
  {"label": "wholesale coffee beans", "commonality": "most"},
  {"label": "office coffee supply accounts", "commonality": "many"},
  {"label": "private label coffee roasting", "commonality": "many"},
  {"label": "online coffee bean sales", "commonality": "most"},
  {"label": "cold brew coffee", "commonality": "some"},
  {"label": "single serve coffee pods", "commonality": "some"},
  {"label": "merchandise and branded apparel", "commonality": "some"},
]
NAICS_311920_TITLE = "Coffee and Tea Manufacturing"


def fake_http_factory(candidates):
  class _Resp:
    status_code = 200
    def json(self):
      return {"choices": [{"message": {"tool_calls": [{"function": {
        "arguments": json.dumps({"candidates": candidates, "basis": "test"})}}]}}]}
  def _http(**kw):
    return _Resp()
  return _http


_JUDGE_CANDS = {"value": []}
_orig_author = sd.gpt_author_stream_candidates_once
def _patched_author(**kw):
  return _orig_author(_http=fake_http_factory(_JUDGE_CANDS["value"]), **kw)
sd.gpt_author_stream_candidates_once = _patched_author
# The naics title normally comes from the DB (conn); conn=None => "" - feed
# the real title through the same helper the seam uses.
ic._stream_discovery_naics_title = lambda conn, n: NAICS_311920_TITLE if str(n) == "311920" else ""

# ---------------------------------------------------------------------------
# 1. THE CORMORANT LATCH - through the seam helper (production chain).
# ---------------------------------------------------------------------------
print("=== 1. Cormorant (draft ec1e22ef) exact judge output through _stream_discovery_ask_if_due ===")
o = cormorant_ops()
_JUDGE_CANDS["value"] = CORMORANT_JUDGE
ask = ic._stream_discovery_ask_if_due(conn=None, ops_json=o, turn_index=20, stage_hint="operating")
latch = o.get("stream_discovery") or {}
print("   ASK:", ask)
print("   LATCH:", json.dumps(latch, indent=1))
reasons = {d["label"]: d["reason"] for d in latch.get("dropped") or []}
asked = [c["label"] for c in latch.get("candidates") or []]
check("Cormorant: discovery ASKS (asked:true)", latch.get("asked") is True and bool(ask), json.dumps(latch)[:300])
check("F2: '12 oz retail coffee bags' -> 'retail coffee bags' SURVIVES (size stripped, not dropped)",
      "retail coffee bags" in asked and "12 oz retail coffee bags" not in reasons, json.dumps(asked) + json.dumps(reasons))
check("F2: the survivor records the judge's original label", any(c.get("judge_label") == "12 oz retail coffee bags" for c in latch.get("candidates") or []))
check("F1: 'private label coffee roasting' SURVIVES (shared only the category noun 'coffee')", "private label coffee roasting" in asked, json.dumps(asked) + json.dumps(reasons))
check("F1: 'office coffee supply accounts' SURVIVES (shared only the category noun 'coffee')", "office coffee supply accounts" in asked, json.dumps(asked) + json.dumps(reasons))
check("F1: 'wholesale coffee beans' STAYS deduped (the primary - client described it)",
      reasons.get("wholesale coffee beans") in ("matches_existing_line", "mentioned_by_client"), json.dumps(reasons))
check("F1: 'online coffee bean sales' STAYS deduped (mentioned in the client's description)",
      reasons.get("online coffee bean sales") in ("matches_existing_line", "mentioned_by_client"), json.dumps(reasons))
for lab in ("cold brew coffee", "single serve coffee pods", "merchandise and branded apparel"):
  check(f"band gate: '{lab}' stays dropped commonality_some", reasons.get(lab) == "commonality_some", json.dumps(reasons))
check("exactly the three survive, in judge order (most first: retail is most; the two many follow)",
      asked == ["retail coffee bags", "office coffee supply accounts", "private label coffee roasting"], json.dumps(asked))
check("latch stores survivors AND proposed (F3 auditability)",
      [s["label"] for s in latch.get("survivors") or []] == asked and latch.get("proposed") == asked and latch.get("proposal_cap") == 4,
      json.dumps(latch)[:400])
if ask:
  low = ask.lower()
  check("ask is the template, existence-framed", ask.startswith(sd.STREAM_DISCOVERY_ASK_PREFIX) and "part of your business today" in ask)
  check("ask forbidden-phrase grep clean", not any(p in low for p in sd.FORBIDDEN_ASK_PHRASES), low)
  check("ask names no digit (size stripped)", not re.search(r"\d", ask), ask)
  check("ask == compose(business_type, proposed)", ask == sd.compose_stream_discovery_ask("Coffee Roaster", asked))

# ---------------------------------------------------------------------------
# 2. F1 generalizes: category-noun-heavy types; non-category matches still dedup.
# ---------------------------------------------------------------------------
print("=== 2. F1 generalization ===")
cat = sd.discovery_category_tokens(cormorant_ops(), NAICS_311920_TITLE)
check("category tokens = business_type + NAICS title stems (+ the LOB name's category word)",
      {"coffee", "roaster", "manufacturing"} <= cat and "roasted" not in cat, json.dumps(sorted(cat)))
o = cormorant_ops()
check("F1: 'roasted coffee delivery' shares 'roasted' (non-category) with the line -> matches_existing_line",
      sd.discovery_dedup_reason("roasted coffee delivery", o, category_tokens=cat) == "matches_existing_line")
check("F1: 'coffee catering' shares only 'coffee' -> survives",
      sd.discovery_dedup_reason("coffee catering", o, category_tokens=cat) is None)
check("F1: 'coffee' alone (bare category noun) -> survives the dedup (no distinguishing tokens; the judge would not send it)",
      sd.discovery_dedup_reason("coffee", o, category_tokens=cat) is None)
# dental: 'dental cleanings' captured; 'dental implants' shares only 'dental'.
dental = {"business_type": "Dental practice", "business_naics_6": "621210", "business_stage": "operating",
          "business_description_summary": "A family dental practice doing routine cleanings and exams.",
          "lob_models": [{"lob_name": "Dental services", "products": [
            {"product_name": "Dental cleaning", "unit_name": "visit", "unit_description": "one hygiene visit"}]}]}
dcat = sd.discovery_category_tokens(dental, "Offices of Dentists")
check("dental: 'dental implants' survives (only the category noun shared)",
      sd.discovery_dedup_reason("dental implants", dental, category_tokens=dcat) is None, json.dumps(sorted(dcat)))
check("dental: 'hygiene cleaning visits' deduped (non-category token 'cleaning'/'visit' shared with the row)",
      sd.discovery_dedup_reason("hygiene cleaning visits", dental, category_tokens=dcat) == "matches_existing_line")
check("dental: 'routine exams' deduped as mentioned_by_client (the client described exams)",
      sd.discovery_dedup_reason("routine exams", dental, category_tokens=dcat) == "mentioned_by_client")
# The garden-centre neighbor from the original red-proof still dedups.
gc = {"business_type": "Garden centre", "business_naics_6": "444240", "business_stage": "operating",
      "business_description_summary": "A garden centre selling plants and hard goods with landscaping installs.",
      "lob_models": [{"lob_name": "Retail", "products": [{"product_name": "Plant sales", "unit_name": "transaction"}]},
                     {"lob_name": "Landscaping", "products": [{"product_name": "Landscaping installation job", "unit_name": "job"}]}]}
gcat = sd.discovery_category_tokens(gc, "Nursery, Garden Center, and Farm Supply Stores")
check("garden centre: 'landscape installation' still deduped (>=2 shared, non-category)",
      sd.discovery_dedup_reason("landscape installation", gc, category_tokens=gcat) == "matches_existing_line")
check("garden centre: 'garden design' survives ('garden' is the category noun)",
      sd.discovery_dedup_reason("garden design", gc, category_tokens=gcat) is None)

# ---------------------------------------------------------------------------
# 3. F2: sizes stripped; money / volume / count figures still dropped.
# ---------------------------------------------------------------------------
print("=== 3. F2 size-strip vs number lint ===")
for raw, want in (
  ("12 oz retail coffee bags", "retail coffee bags"),
  ("5 lb wholesale bags", "wholesale bags"),
  ("500ml cold brew bottles", "cold brew bottles"),
  ("2-pack gift boxes", "gift boxes"),
  ("1.5 kg bulk bags", "bulk bags"),
  ("delivery service", "delivery service"),
):
  check(f"strip_size_qualifiers({raw!r}) == {want!r}", sd.strip_size_qualifiers(raw) == want, repr(sd.strip_size_qualifiers(raw)))
o = cormorant_ops()
r = sd.validate_stream_candidates(judgment={"candidates": [
  {"label": "$40 wholesale accounts", "commonality": "most"},
  {"label": "40 units per week subscriptions", "commonality": "most"},
  {"label": "3 extra services", "commonality": "most"},
  {"label": "coffee subscriptions 200 per month", "commonality": "most"},
  {"label": "12 oz", "commonality": "most"},
]}, ops_json=o, naics_title=NAICS_311920_TITLE)
rs = {d["label"]: d["reason"] for d in r["dropped"]}
check("F2: money figure still dropped", rs.get("$40 wholesale accounts") == "label_carries_number", json.dumps(rs))
check("F2: volume figure still dropped", rs.get("40 units per week subscriptions") == "label_carries_number", json.dumps(rs))
check("F2: count figure still dropped", rs.get("3 extra services") == "label_carries_number", json.dumps(rs))
check("F2: rate figure still dropped", rs.get("coffee subscriptions 200 per month") == "label_carries_number", json.dumps(rs))
check("F2: a bare size with nothing left is dropped, not asked", rs.get("12 oz") == "label_not_a_short_phrase" and not r["candidates"], json.dumps(rs))

# ---------------------------------------------------------------------------
# 4. F3: proposal cap - most first, then many, at most 4; <=4 => all.
# ---------------------------------------------------------------------------
print("=== 4. F3 proposal cap ===")
o = cormorant_ops()
six = [
  {"label": "espresso catering", "commonality": "many"},
  {"label": "barista training", "commonality": "most"},
  {"label": "brewing equipment resale", "commonality": "many"},
  {"label": "gift subscriptions", "commonality": "many"},
  {"label": "farmers market stall", "commonality": "most"},
  {"label": "tasting events", "commonality": "many"},
]
r = sd.validate_stream_candidates(judgment={"candidates": six}, ops_json=o, naics_title=NAICS_311920_TITLE)
surv = [c["label"] for c in r["survivors"]]
prop = [c["label"] for c in r["candidates"]]
check("F3: all 6 survive the band-gate (no cap on survivors)", surv == [c["label"] for c in six], json.dumps(surv) + json.dumps(r["dropped"]))
check("F3: proposed = the 2 most + the first 2 many, exactly 4",
      prop == ["barista training", "farmers market stall", "espresso catering", "brewing equipment resale"], json.dumps(prop))
_JUDGE_CANDS["value"] = six
o = cormorant_ops()
ask6 = ic._stream_discovery_ask_if_due(conn=None, ops_json=o, turn_index=20, stage_hint="operating")
print("   ASK(6):", ask6)
l6 = o["stream_discovery"]
check("F3 latch: survivors=6, proposed=4, candidates (asked) = proposed",
      len(l6["survivors"]) == 6 and l6["proposed"] == prop and [c["label"] for c in l6["candidates"]] == prop, json.dumps(l6)[:400])
check("F3 ask names exactly the 4 proposed labels and none of the other 2",
      all(l in ask6 for l in prop) and not any(l in ask6 for l in ("gift subscriptions", "tasting events")), ask6)
check("F3 ask has one question mark", ask6.count("?") == 1)
three = six[:3]
r3 = sd.validate_stream_candidates(judgment={"candidates": three}, ops_json=cormorant_ops(), naics_title=NAICS_311920_TITLE)
check("F3: 3 survivors -> all 3 proposed, no padding, most first",
      [c["label"] for c in r3["candidates"]] == ["barista training", "espresso catering", "brewing equipment resale"] and len(r3["survivors"]) == 3,
      json.dumps([c["label"] for c in r3["candidates"]]))
check("F3: cap constant is 4", sd.STREAM_DISCOVERY_PROPOSAL_CAP == 4)

# The answer path reads against the PROPOSED labels only (unchanged reader).
o = cormorant_ops()
_JUDGE_CANDS["value"] = six
ask6 = ic._stream_discovery_ask_if_due(conn=None, ops_json=o, turn_index=20, stage_hint="operating")
o, receipt, note = ic._apply_stream_discovery_answer(ops_json=o, message="Barista training yes, the rest no.", last_assistant=ask6)
ans = {c["label"]: c["answer"] for c in o["stream_discovery"]["candidates"]}
check("answer path: yes lands on the proposed label, the other 3 proposed are no",
      ans == {"barista training": "yes", "farmers market stall": "no", "espresso catering": "no", "brewing equipment resale": "no"}, json.dumps(ans))
check("answer path: the confirmed row appended with origin", any(p.get("origin") == "discovery_confirmed" and p.get("product_name") == "barista training" for l in o["lob_models"] for p in l["products"]))
check("answer path: pending False afterwards", not sd.stream_discovery_pending(o))

# ---------------------------------------------------------------------------
# 5. Boundary: the corrections resolver is untouched (its callers unchanged).
# ---------------------------------------------------------------------------
print("=== 5. resolver untouched ===")
src = (ROOT / "python/api_handlers/intake_consult.py").read_text(encoding="utf-8")
seam = src[src.index("def _stream_discovery_ask_if_due"):src.index("def _apply_stream_discovery_answer")]
check("discovery seam no longer calls _resolve_ops_product_line", "_resolve_ops_product_line(" not in seam and "resolve_line=" not in seam)
check("resolver still has its correction callers", src.count("_resolve_ops_product_line(") >= 3, str(src.count("_resolve_ops_product_line(")))
res, why = ic._resolve_ops_product_line(cormorant_ops(), "the coffee price is now 65")
check("resolver behaviour unchanged: 'coffee' still resolves the single line for a correction", res is not None and why == "")

print()
if FAILS:
  print(f"RED: {len(FAILS)} failing: {FAILS}")
  sys.exit(1)
print("GREEN: F1+F2+F3 red-proof passed")
sys.exit(0)
