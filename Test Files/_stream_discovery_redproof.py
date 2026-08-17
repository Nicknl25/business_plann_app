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


# F4: the reader routes every reply through the app's existing intent door
# (intake_consult._classify_restatement_response). Offline that door is
# stubbed with a per-(label, reply) table - the plumbing is proven here, the
# real door is proven live in _stream_discovery_f4_redproof.py --live.
DOOR_TABLE = {}
DOOR_CALLS = []


def stub_door(*, restatement, user_reply):
  DOOR_CALLS.append((restatement, user_reply))
  m = re.search(r'RESTATEMENT TO CHECK: "([^"]+)" is part of', restatement)
  label = m.group(1) if m else None
  return (DOOR_TABLE.get(user_reply) or {}).get(label)


def door_answers(reply, mapping):
  """mapping: {label: yes|no|unclear|None|error}."""
  DOOR_TABLE[reply] = {}
  for lab, a in mapping.items():
    DOOR_TABLE[reply][lab] = {"yes": "ACCEPT", "no": "REJECT", "unclear": "CLARIFY"}.get(a, a)


def apply_answer(ops_json, message, last_assistant):
  return ic._apply_stream_discovery_answer(
    ops_json=ops_json, message=message, last_assistant=last_assistant, classify=stub_door,
  )


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
check("F4 ask tells the client why (revenue line clause) + uses the template verb", "revenue line" in ask and "also offer" in ask, ask)
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
# 4+. THE READER / APPLIER sections were DELETED 2026-08-17 (Nick's ruling,
#    Option A): discovery no longer owns a reader or an applier - the reply
#    is read by consultant_chat_turn (the shared reader) and the outcome is
#    recorded from the state. See _discovery_reader_convergence_redproof.py.
# --------------------------------------------------------------------------

print()
if FAILS:
  print(f"RED: {len(FAILS)} failing check(s): {FAILS}")
  sys.exit(1)
print("GREEN: every stream-discovery check passed")
