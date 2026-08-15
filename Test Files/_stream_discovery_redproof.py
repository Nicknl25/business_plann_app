"""STREAM DISCOVERY - spot-check red-proofs + named neighbor checks
(docs/STREAM_DISCOVERY_SPEC.md, VS turn 1, 2026-08-15).

Runs OFFLINE against the module + the controller helpers with a fake
judge (no OpenAI, no DB): every fence is exercised on the exact production
functions the seam calls (`_stream_discovery_ask_if_due`,
`_apply_stream_discovery_answer`, `carry_stream_discovery`), with
production data shapes (ops_json as the ops consultant stores it).

  python "Test Files/_stream_discovery_redproof.py"

Exit 0 = every check green; nonzero = the failing check name.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from api_handlers import intake_consult as ic  # noqa: E402
from client_intake_and_finmo.intake_coherence import gpt_stream_discovery as sd  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
  status = "PASS" if cond else "FAIL"
  print(f"[{status}] {name}" + (f"  -- {detail}" if detail and not cond else ""))
  if not cond:
    FAILS.append(name)


def garden_centre_ops():
  return {
    "business_type": "Garden centre",
    "business_naics_6": "444240",
    "business_stage": "operating",
    "consumer_type": "consumer",
    "geographic_scope": "local",
    "shipping_method": "in-store",
    "sales_modality": "physical",
    "legal_entity": "LLC",
    "capacity_driver": "labor",
    "primary_growth_lever": "volume",
    "business_description_summary": "A garden centre selling plants and hard goods with landscaping installs.",
    "lob_models": [
      {"lob_name": "Retail", "products": [
        {"product_name": "Plant sales", "unit_name": "transaction", "unit_description": "one till sale",
         "unit_cadence": "weekly", "units_per_week_capacity": 400, "units_per_period_capacity": 400,
         "operating_periods_per_year": 52, "utilization_rate": 0.7, "unit_price": 45,
         "cogs_percent_of_line_revenue": None},
      ]},
      {"lob_name": "Landscaping", "products": [
        {"product_name": "Landscaping installation job", "unit_name": "job", "unit_description": "one install",
         "unit_cadence": "weekly", "units_per_week_capacity": 4, "units_per_period_capacity": 4,
         "operating_periods_per_year": 40, "utilization_rate": 0.8, "unit_price": 2500,
         "cogs_percent_of_line_revenue": None},
      ]},
    ],
  }


def fake_http_factory(candidates):
  class _Resp:
    status_code = 200
    def json(self):
      return {"choices": [{"message": {"tool_calls": [{"function": {
        "arguments": json.dumps({"candidates": candidates, "basis": "test"})}}]}}]}
  calls = {"n": 0}
  def _http(**kw):
    calls["n"] += 1
    return _Resp()
  return _http, calls


# Patch the judge to a fake HTTP so the controller helper runs the real
# validator/template on a controlled judgment.
_JUDGE_CANDS = {"value": []}
_JUDGE_CALLS = {"n": 0}
_orig_author = sd.gpt_author_stream_candidates_once
def _patched_author(**kw):
  _JUDGE_CALLS["n"] += 1
  http, _ = fake_http_factory(_JUDGE_CANDS["value"])
  return _orig_author(_http=http, **kw)
sd.gpt_author_stream_candidates_once = _patched_author

# --------------------------------------------------------------------------
# 1. THIN => no GPT call, no ask, latched with reason.
# --------------------------------------------------------------------------
for label, mut in (
  ("no_business_type", lambda o: o.update(business_type="")),
  ("naics_unresolved", lambda o: o.update(business_naics_6=None)),
  ("pre_revenue", lambda o: o.update(business_stage="pre-revenue")),
  ("no_client_lines", lambda o: o.update(lob_models=[])),
):
  o = garden_centre_ops(); mut(o)
  _JUDGE_CALLS["n"] = 0
  _JUDGE_CANDS["value"] = [{"label": "delivery service", "commonality": "most"}]
  ask = ic._stream_discovery_ask_if_due(conn=None, ops_json=o, turn_index=5, stage_hint=None)
  latch = o.get("stream_discovery") or {}
  check(f"thin:{label} => no ask", ask is None, repr(ask))
  check(f"thin:{label} => ZERO judge calls", _JUDGE_CALLS["n"] == 0, str(_JUDGE_CALLS))
  check(f"thin:{label} => latched asked:false reason:thin", latch.get("asked") is False and latch.get("reason") == "thin", json.dumps(latch))

# stage falls back to the controller hint when the model has not stamped it
o = garden_centre_ops(); o.pop("business_stage")
lvl = sd.stream_discovery_evidence_level(o, stage_hint="operating")
check("stage_hint fallback => rich", lvl["level"] == "rich", json.dumps(lvl))
lvl = sd.stream_discovery_evidence_level(o, stage_hint=None)
check("no stage anywhere => thin", lvl["level"] == "thin", json.dumps(lvl))

# --------------------------------------------------------------------------
# 2. VALIDATOR: band gate, stem dedup, addition-verb lint, NO count cap.
# --------------------------------------------------------------------------
o = garden_centre_ops()
judgment = {"candidates": [
  {"label": "delivery service", "commonality": "most"},
  {"label": "garden design", "commonality": "many"},
  {"label": "gift shop sales", "commonality": "some"},                # band-dropped
  {"label": "landscape installation", "commonality": "most"},        # paraphrase of an existing line
  {"label": "consider adding a cafe", "commonality": "most"},         # addition verb
  {"label": "new plant hire", "commonality": "many"},                 # addition verb (new)
  {"label": "seasonal workshops", "commonality": "many"},
  {"label": "bulk mulch and soil", "commonality": "many"},
  {"label": "Delivery Service", "commonality": "most"},               # duplicate
  {"label": "3 extra services", "commonality": "most"},              # number
]}
railed = sd.validate_stream_candidates(judgment=judgment, ops_json=o, naics_title="Nursery, Garden Center, and Farm Supply Stores")
labels = [c["label"] for c in railed["candidates"]]
reasons = {d["label"]: d["reason"] for d in railed["dropped"]}
check("band gate drops 'some'", reasons.get("gift shop sales") == "commonality_some", json.dumps(reasons))
check("stem dedup drops the paraphrase of an existing line", reasons.get("landscape installation", "").startswith("matches_existing_line"), json.dumps(reasons))
check("addition-verb lint drops 'consider adding'", reasons.get("consider adding a cafe") == "addition_verb", json.dumps(reasons))
check("addition-verb lint drops 'new'", reasons.get("new plant hire") == "addition_verb", json.dumps(reasons))
check("duplicate label dropped", reasons.get("Delivery Service") == "duplicate_label", json.dumps(reasons))
check("numeric label dropped", reasons.get("3 extra services") == "label_carries_number", json.dumps(reasons))
check("NO COUNT CAP ON THE BAND: all 4 band-gated survivors kept and proposed (<= cap)", labels == ["delivery service", "garden design", "seasonal workshops", "bulk mulch and soil"], json.dumps(labels))
check("survivors == candidates when <= the proposal cap", [c["label"] for c in railed["survivors"]] == labels)
# F3 (Nick, 2026-08-15): the ONLY cap is the proposal cap of 4 on the ASK
# (most-first slice of the survivors); the band itself is uncapped. See
# _stream_discovery_f123_redproof.py for the slice red-proof.
src = (ROOT / "python/client_intake_and_finmo/intake_coherence/gpt_stream_discovery.py").read_text(encoding="utf-8")
check("no band-side count cap in the module (only STREAM_DISCOVERY_PROPOSAL_CAP on the ask)", not re.search(r"MAX_CANDIDATES|\[:\s*[23]\]", src) and sd.STREAM_DISCOVERY_PROPOSAL_CAP == 4)

# --------------------------------------------------------------------------
# 3. THE ASK: template constant, forbidden phrases absent, fires ONCE.
# --------------------------------------------------------------------------
o = garden_centre_ops()
_JUDGE_CANDS["value"] = [
  {"label": "delivery service", "commonality": "most"},
  {"label": "garden design", "commonality": "many"},
  {"label": "seasonal workshops", "commonality": "some"},
]
_JUDGE_CALLS["n"] = 0
ask = ic._stream_discovery_ask_if_due(conn=None, ops_json=o, turn_index=41, stage_hint=None)
print("   ASK:", ask)
check("rich => ask fires", bool(ask))
check("exactly ONE judge call", _JUDGE_CALLS["n"] == 1)
check("ask == template with band-gated survivors", ask == sd.compose_stream_discovery_ask("Garden centre", ["delivery service", "garden design"]))
check("ask is existence-framed", "part of your business today" in ask)
low = ask.lower()
check("forbidden-phrase grep finds nothing", not any(p in low for p in sd.FORBIDDEN_ASK_PHRASES), low)
check("ask has exactly one question mark", ask.count("?") == 1)
latch = o["stream_discovery"]
check("latch asked:true w/ turn index", latch["asked"] is True and latch["asked_turn_index"] == 41)
check("latch candidates carry commonality + answer:null", all(c["answer"] is None and c["commonality"] in ("most", "many") for c in latch["candidates"]))
check("latch dropped carries reason", latch["dropped"] == [{"label": "seasonal workshops", "reason": "commonality_some"}], json.dumps(latch["dropped"]))
check("stream_discovery_pending", sd.stream_discovery_pending(o))
# ONCE: a second call on the same draft is silent and does not call the judge
_JUDGE_CALLS["n"] = 0
ask2 = ic._stream_discovery_ask_if_due(conn=None, ops_json=o, turn_index=42, stage_hint=None)
check("second call => no ask (latched)", ask2 is None)
check("second call => no judge call", _JUDGE_CALLS["n"] == 0)

# no survivors => asked:false, reason no_common_candidates
o2 = garden_centre_ops()
_JUDGE_CANDS["value"] = [{"label": "gift shop sales", "commonality": "some"}]
ask3 = ic._stream_discovery_ask_if_due(conn=None, ops_json=o2, turn_index=7, stage_hint=None)
check("no survivors => no ask + reason no_common_candidates", ask3 is None and o2["stream_discovery"]["reason"] == "no_common_candidates", json.dumps(o2["stream_discovery"]))

# judge unavailable => no ask, latched
o3 = garden_centre_ops()
sd.gpt_author_stream_candidates_once = lambda **kw: {"ok": False, "judgment": None, "error": "http_status_500"}
ask4 = ic._stream_discovery_ask_if_due(conn=None, ops_json=o3, turn_index=7, stage_hint=None)
check("judge unavailable => no ask, latched with reason", ask4 is None and o3["stream_discovery"]["reason"].startswith("judge_unavailable"), json.dumps(o3["stream_discovery"]))
sd.gpt_author_stream_candidates_once = _patched_author

# pluralizer sanity (client-plain)
check("pluralize garden centre", sd.pluralize_business_type("Garden centre") == "garden centres")
check("pluralize bakery", sd.pluralize_business_type("Bakery") == "bakeries")
check("pluralize bicycle shop", sd.pluralize_business_type("Bicycle shop") == "bicycle shops")
check("pluralize law practice", sd.pluralize_business_type("Law practice") == "law practices")

# --------------------------------------------------------------------------
# 4. THE READER: yes/no/unclear per candidate, deterministic.
# --------------------------------------------------------------------------
L = ["delivery service", "garden design"]
cases = [
  ("yes to design, no to delivery", {"delivery service": "no", "garden design": "yes"}),
  ("we do design but not deliveries", {"delivery service": "no", "garden design": "yes"}),
  ("no, neither of those", {"delivery service": "no", "garden design": "no"}),
  ("nope", {"delivery service": "no", "garden design": "no"}),
  ("no", {"delivery service": "no", "garden design": "no"}),
  ("yes both", {"delivery service": "yes", "garden design": "yes"}),
  ("yes we do all of that", {"delivery service": "yes", "garden design": "yes"}),
  ("just the design work", {"delivery service": "no", "garden design": "yes"}),
  ("we do garden design", {"delivery service": "unclear", "garden design": "yes"}),
  ("yes", {"delivery service": "unclear", "garden design": "unclear"}),   # several candidates, no name: never guess WHICH
  ("what do you mean by that", {"delivery service": "unclear", "garden design": "unclear"}),
  ("we don't do delivery", {"delivery service": "no", "garden design": "unclear"}),
  ("Yes, garden design is part of it. The others no.", {"delivery service": "no", "garden design": "yes"}),
  ("garden design yes, and the rest too", {"delivery service": "yes", "garden design": "yes"}),
]
for msg, want in cases:
  got = sd.read_stream_discovery_answer(msg, L)
  check(f"reader: {msg!r}", got == want, json.dumps(got))
check("reader single candidate bare yes => yes", sd.read_stream_discovery_answer("yes", ["delivery service"]) == {"delivery service": "yes"})
check("reader single candidate bare no => no", sd.read_stream_discovery_answer("no we don't", ["delivery service"]) == {"delivery service": "no"})

# --------------------------------------------------------------------------
# 5. LANDING: yes appends a null-driver row with origin; receipt == write;
#    no/unclear stored, never re-asked; the note tells the consultant.
# --------------------------------------------------------------------------
o = garden_centre_ops()
_JUDGE_CANDS["value"] = [
  {"label": "delivery service", "commonality": "most"},
  {"label": "garden design", "commonality": "many"},
]
ask = ic._stream_discovery_ask_if_due(conn=None, ops_json=o, turn_index=41, stage_hint=None)
o_after, ack, note = ic._apply_stream_discovery_answer(ops_json=o, message="yes to design, no to delivery", last_assistant=ask)
print("   RECEIPT:", ack)
rows = [(lob["lob_name"], p) for lob in o_after["lob_models"] for p in lob["products"]]
disc_rows = [(ln, p) for ln, p in rows if p.get("origin") == "discovery_confirmed"]
check("yes => exactly one appended row", len(disc_rows) == 1, json.dumps(disc_rows))
check("appended row named for the label, all drivers null", disc_rows and disc_rows[0][1]["product_name"] == "garden design" and all(disc_rows[0][1][k] is None for k in ("unit_name", "unit_cadence", "units_per_week_capacity", "units_per_period_capacity", "utilization_rate", "unit_price")))
check("appended under stem-matched LOB or new LOB named for label", disc_rows and disc_rows[0][0] in ("garden design", "Landscaping", "Retail"))
check("receipt names the line + says numbers next", "garden design" in ack and "quick numbers" in ack, ack)
check("receipt has no jargon", not any(t in ack.lower() for t in ("origin", "lob", "json", "null", "discovery_confirmed")), ack)
latch = o_after["stream_discovery"]
answers = {c["label"]: c["answer"] for c in latch["candidates"]}
check("latch answers stored", answers == {"delivery service": "no", "garden design": "yes"}, json.dumps(answers))
check("no longer pending (never re-asked)", not sd.stream_discovery_pending(o_after))
check("second ask_if_due after answers is silent", ic._stream_discovery_ask_if_due(conn=None, ops_json=o_after, turn_index=50, stage_hint=None) is None)
check("note names confirmed + declined for the consultant", "garden design" in note and "DECLINED" in note and "delivery service" in note, note)
# a second reply never re-lands / re-asks
o_again, ack2, note2 = ic._apply_stream_discovery_answer(ops_json=o_after, message="yes delivery too", last_assistant=ask)
check("post-answer reply => no second landing, no ack", ack2 == "" and note2 == "" and {c["label"]: c["answer"] for c in o_again["stream_discovery"]["candidates"]} == answers)

# no => stored, nothing appended
o = garden_centre_ops()
ask = ic._stream_discovery_ask_if_due(conn=None, ops_json=o, turn_index=41, stage_hint=None)
n_before = sum(len(l["products"]) for l in o["lob_models"])
o_after, ack, note = ic._apply_stream_discovery_answer(ops_json=o, message="no, neither", last_assistant=ask)
check("no => nothing appended", sum(len(l["products"]) for l in o_after["lob_models"]) == n_before)
check("no => stored no for all", all(c["answer"] == "no" for c in o_after["stream_discovery"]["candidates"]))
check("no => honest move-on receipt", "move on" in ack, ack)

# unclear => NOT confirmed, stored unclear, nothing appended, honest receipt
o = garden_centre_ops()
ask = ic._stream_discovery_ask_if_due(conn=None, ops_json=o, turn_index=41, stage_hint=None)
o_after, ack, note = ic._apply_stream_discovery_answer(ops_json=o, message="hmm maybe, depends", last_assistant=ask)
check("unclear => nothing appended", sum(len(l["products"]) for l in o_after["lob_models"]) == n_before)
check("unclear => stored unclear", all(c["answer"] == "unclear" for c in o_after["stream_discovery"]["candidates"]))
check("unclear => honest receipt offers the door, no re-ask", "tell me its name" in ack and "?" not in ack, ack)
check("unclear => not pending", not sd.stream_discovery_pending(o_after))

# --------------------------------------------------------------------------
# 6. FINALIZE CARRY (neighbor): a wholesale replacement (finalize / model
#    patch) that drops the latch and the origin gets both back; a
#    duplicate mint is collapsed; a dropped confirmed row is restored.
# --------------------------------------------------------------------------
o = garden_centre_ops()
ask = ic._stream_discovery_ask_if_due(conn=None, ops_json=o, turn_index=41, stage_hint=None)
o, _, _ = ic._apply_stream_discovery_answer(ops_json=o, message="yes to design, no to delivery", last_assistant=ask)
# the client then gave its numbers (as the cascade captures them)
for lob in o["lob_models"]:
  for p in lob["products"]:
    if p["product_name"] == "garden design":
      p.update(unit_name="design", unit_cadence="weekly", units_per_week_capacity=3, units_per_period_capacity=3,
               operating_periods_per_year=48, utilization_rate=0.6, unit_price=400)
# (a) finalize returns the strict object: no latch, origin null on every row
final_obj = copy.deepcopy(o); final_obj.pop("stream_discovery")
for lob in final_obj["lob_models"]:
  for p in lob["products"]:
    p["origin"] = None
final_obj = ic._sdisc.carry_stream_discovery(o, final_obj)
check("carry: latch re-attached after finalize replace", final_obj.get("stream_discovery") == o["stream_discovery"])
gd = [p for lob in final_obj["lob_models"] for p in lob["products"] if p["product_name"] == "garden design"]
check("carry: origin re-stamped on the confirmed row, drivers kept", len(gd) == 1 and gd[0]["origin"] == "discovery_confirmed" and gd[0]["unit_price"] == 400)
others = [p for lob in final_obj["lob_models"] for p in lob["products"] if p["product_name"] != "garden design"]
check("carry: other rows untouched (origin stays null)", all(p.get("origin") is None for p in others))
# (b) the model minted a duplicate
dup = copy.deepcopy(o); dup["lob_models"][0]["products"].append(sd.new_discovered_row("Garden Design"))
dup = ic._sdisc.carry_stream_discovery(o, dup)
gd = [p for lob in dup["lob_models"] for p in lob["products"] if p["product_name"].lower() == "garden design"]
check("carry: duplicate mint collapsed to ONE row (the one with drivers)", len(gd) == 1 and gd[0]["unit_price"] == 400)
# (c) the model dropped the row entirely
dropped = copy.deepcopy(o)
for lob in dropped["lob_models"]:
  lob["products"] = [p for p in lob["products"] if p["product_name"] != "garden design"]
dropped["lob_models"] = [l for l in dropped["lob_models"] if l["products"]]
dropped = ic._sdisc.carry_stream_discovery(o, dropped)
gd = [p for lob in dropped["lob_models"] for p in lob["products"] if p["product_name"] == "garden design"]
check("carry: dropped confirmed row restored WITH its client-given drivers", len(gd) == 1 and gd[0]["unit_price"] == 400 and gd[0]["origin"] == "discovery_confirmed")
# (d) idempotent
twice = ic._sdisc.carry_stream_discovery(o, copy.deepcopy(final_obj))
check("carry: idempotent", twice == final_obj)
# (e) a draft with NO discovery latch is untouched (the single-line floor)
plain = {"lob_models": [{"lob_name": "X", "products": [{"product_name": "a", "unit_price": 1}]}]}
check("carry: no latch => byte-identical passthrough", ic._sdisc.carry_stream_discovery({}, copy.deepcopy(plain)) == plain)
# (f0) the model invented an origin on an ordinary row (seen live) => scrubbed to null
inv = copy.deepcopy(final_obj)
inv["lob_models"][0]["products"][0]["origin"] = "client_stated"
inv["lob_models"][1]["products"][0]["origin"] = "discovery_confirmed"   # not a latched yes
inv = ic._sdisc.carry_stream_discovery(o, inv)
check("carry: model-invented origin values scrubbed to null", inv["lob_models"][0]["products"][0]["origin"] is None and inv["lob_models"][1]["products"][0]["origin"] is None)
gd = [p for lob in inv["lob_models"] for p in lob["products"] if p["product_name"] == "garden design"]
check("carry: the real stamp survives the scrub", len(gd) == 1 and gd[0]["origin"] == "discovery_confirmed")
inv2 = {"lob_models": [{"lob_name": "X", "products": [{"product_name": "a", "origin": "discovery_confirmed"}]}]}
inv2 = ic._sdisc.carry_stream_discovery({}, inv2)
check("carry: no latch + model-stamped discovery_confirmed => scrubbed", inv2["lob_models"][0]["products"][0]["origin"] is None)
# (f) a THIN latch (asked:false) => passthrough of lob_models
thin_before = {"stream_discovery": {"asked": False, "reason": "thin"}}
after = ic._sdisc.carry_stream_discovery(thin_before, copy.deepcopy(plain))
check("carry: thin latch carried, rows untouched", after["stream_discovery"] == thin_before["stream_discovery"] and after["lob_models"] == plain["lob_models"])

# --------------------------------------------------------------------------
# 7. NEIGHBORS by source: both hooks present, both schemas carry origin,
#    both finalize sites carry, competitive-advantage + milestone ordering.
# --------------------------------------------------------------------------
consult_src = (ROOT / "python/api_handlers/intake_consult.py").read_text(encoding="utf-8-sig")
consultant_src = (ROOT / "python/client_intake_and_finmo/intake_consultant.py").read_text(encoding="utf-8")
check("hook: main gate cascade seam", "STREAM DISCOVERY (spec Q4)" in consult_src and consult_src.count("_stream_discovery_ask_if_due(") >= 3)
check("hook: follow-up mirror seam", "STREAM DISCOVERY mirror" in consult_src)
check("carry at BOTH ops_json = final_obj sites", consult_src.count("_sdisc.carry_stream_discovery(ops_json, final_obj)") == 2)
check("carry after BOTH model-patch applications", "carry_stream_discovery(_ops_before, ops_json)" in consult_src and "carry_stream_discovery(_ops_before_fu, ops_json)" in consult_src)
check("origin in BOTH strict schemas", consultant_src.count('"origin": {"type": ["string", "null"]}') == 2 and consultant_src.count('"origin",') == 2)
# ordering: the discovery seam precedes the competitive-advantage proposal in the main cascade
i_seam = consult_src.index("STREAM DISCOVERY (spec Q4)")
i_adv = consult_src.index("and not str((ops_json or {}).get(\"competitive_advantage\") or \"\").strip()\n    ):\n      confirmed_restatement", i_seam)
i_ms = consult_src.index("assistant_text = OPS_MILESTONE_QUESTION\n      finalize_ready = False\n      pending_ops_milestone = True", i_adv)
check("ordering: discovery -> competitive advantage -> milestone (unchanged)", i_seam < i_adv < i_ms)
check("competitive-advantage proposal untouched", "proposed_advantage = _propose_ops_competitive_advantage(" in consult_src)
check("milestone question constant unchanged", 'OPS_MILESTONE_QUESTION = (' in consult_src)
# the ask holds the turn: finalize_ready False + ops_ready_for_wrap False on ask
check("ask holds the turn (finalize_ready False)", "if _disc_ask:\n                assistant_text = _disc_ask\n                ops_ready_for_wrap = False\n                finalize_ready = False" in consult_src)
# forbidden phrases: the template constant itself
tmpl = sd.STREAM_DISCOVERY_ASK_TEMPLATE.lower()
check("template constant carries no forbidden phrase", not any(p in tmpl for p in sd.FORBIDDEN_ASK_PHRASES))
check("template is the ONE constant (single definition)", src.count("STREAM_DISCOVERY_ASK_TEMPLATE = (") == 1)

print()
if FAILS:
  print(f"RED: {len(FAILS)} failing check(s): {FAILS}")
  sys.exit(1)
print("GREEN: every stream-discovery check passed")
