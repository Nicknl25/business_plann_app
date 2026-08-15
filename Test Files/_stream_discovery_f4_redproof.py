"""F4 red-proof - the discovery reader reads INTENT, not keywords
(docs/STREAM_DISCOVERY_SPEC.md Q5, Nick's ruling 2026-08-15: DEAL BREAKER =
a phantom discovery_confirmed row + a false 'is its own line' receipt on an
explicit no).

PRODUCTION CALL CHAIN: POST /api/intake-consult (focus=ops, the turn after
the discovery ask) -> consultant_chat_turn -> _apply_stream_discovery_answer
-> gpt_stream_discovery.read_stream_discovery_answer -> per proposed stream:
intake_consult._classify_restatement_response (the app's existing
ACCEPT/REJECT/CLARIFY intent door) -> yes: append_confirmed_stream_rows +
receipt; no: stored; unclear: ONE clarify (compose_stream_discovery_clarify),
read the same way; still unclear -> not confirmed.

Two modes:
  python "Test Files/_stream_discovery_f4_redproof.py"          # OFFLINE: door stubbed, plumbing + PRE/POST on the six replies
  python "Test Files/_stream_discovery_f4_redproof.py" --live   # LIVE: the REAL door (OpenAI) reads the six replies per stream

PRE (old keyword reader, no `classify` kwarg): the six-reply table is run
through the old signature and reds for the RIGHT reason (phantom yes on
'No, none of those. We just do the five pound wholesale bags.').
Exit 0 = green; nonzero = failing check names.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
LIVE = "--live" in sys.argv
if LIVE:
  from dotenv import load_dotenv  # type: ignore
  load_dotenv(str(ROOT / ".env"))
else:
  os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
try:
  sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
  pass

from api_handlers import intake_consult as ic  # noqa: E402
from client_intake_and_finmo.intake_coherence import gpt_stream_discovery as sd  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
  status = "PASS" if cond else "FAIL"
  print(f"[{status}] {name}" + (f"  -- {detail}" if detail and not cond else ""))
  if not cond:
    FAILS.append(name)


# The real Cormorant proposal (ec1e22ef): four labels, one of them carrying
# the word 'wholesale' that also appears inside the client's decline.
LABELS = [
  "wholesale subscription contracts",
  "retail coffee bags",
  "single-origin limited release coffees",
  "direct-to-consumer coffee subscriptions",
]
BT = "Coffee Roaster"
ASK = sd.compose_stream_discovery_ask(BT, LABELS)
Y, N, U = "yes", "no", "unclear"
# reply -> expected per-label reading (the six from the task + the live bug)
SIX = [
  ("No, none of those. We just do the five pound wholesale bags.", {l: N for l in LABELS}),
  ("No. Retail bags no, subscriptions no. Just wholesale to cafes.", {l: N for l in LABELS}),
  ("yeah we do the retail bags", {LABELS[0]: N, LABELS[1]: Y, LABELS[2]: N, LABELS[3]: N}),
  ("no retail bags, but yes direct to consumer subscriptions", {LABELS[0]: N, LABELS[1]: N, LABELS[2]: N, LABELS[3]: Y}),
  ("sort of, sometimes", {l: U for l in LABELS}),
  ("yes", {l: U for l in LABELS}),   # several streams named, no WHICH -> clarify, never guess
]
# The task's own phrasing with a candidate that IS proposed ('a cafe'):
CAFE_LABELS = ["retail coffee bags", "a cafe", "coffee subscriptions"]
CAFE_ASK = sd.compose_stream_discovery_ask(BT, CAFE_LABELS)
CAFE = [
  ("yeah we have a small cafe", {"retail coffee bags": N, "a cafe": Y, "coffee subscriptions": N}),
  ("no, we don't do a cafe", {"retail coffee bags": N, "a cafe": N, "coffee subscriptions": N}),
  ("no retail bags, but yes subscriptions", {"retail coffee bags": N, "a cafe": N, "coffee subscriptions": Y}),
]


def _stub_door_factory(table):
  def door(*, restatement, user_reply):
    m = re.search(r'RESTATEMENT TO CHECK: "([^"]+)" is part of', restatement)
    lab = m.group(1) if m else None
    want = (table.get(user_reply) or {}).get(lab)
    return {Y: "ACCEPT", N: "REJECT", U: "CLARIFY"}.get(want)
  return door


def read(msg, labels, ask, door):
  sig = inspect.signature(sd.read_stream_discovery_answer)
  if "classify" not in sig.parameters:
    print("   (PRE build: old keyword reader, no intent door)")
    return sd.read_stream_discovery_answer(msg, labels)
  return sd.read_stream_discovery_answer(msg, labels, classify=door, ask_text=ask)


print("=== 1. the template (F4 part 2): why they are asked, template verb ===")
print("   ASK:", ASK)
check("ask carries the revenue-line clause", "revenue line" in ASK, ASK)
check("ask uses the template verb 'also offer' (labels read naturally)", "also offer " in ASK, ASK)
check("ask is one question", ASK.count("?") == 1, ASK)
check("forbidden-phrase grep clean", not any(p in ASK.lower() for p in sd.FORBIDDEN_ASK_PHRASES), ASK)
check("ask == the ONE template constant", ASK == sd.STREAM_DISCOVERY_ASK_TEMPLATE.format(business_type_plural=sd.pluralize_business_type(BT), labels=sd.join_labels(LABELS)))
clar = sd.compose_stream_discovery_clarify(["retail coffee bags"]) if hasattr(sd, "compose_stream_discovery_clarify") else ""
print("   CLARIFY:", clar)
check("clarify exists, one question, says revenue line, forbidden grep clean", bool(clar) and clar.count("?") == 1 and "revenue line" in clar and not any(p in clar.lower() for p in sd.FORBIDDEN_ASK_PHRASES), clar)

print("=== 2. the reader has NO keyword logic ===")
src = (ROOT / "python/client_intake_and_finmo/intake_coherence/gpt_stream_discovery.py").read_text(encoding="utf-8")
check("no _NEG_RE/_AFFIRM_RE/_ALL_RE/_ONLY_RE/_OTHERS_RE/_clauses in the module", not re.search(r"_NEG_RE|_AFFIRM_RE|_ALL_RE|_ONLY_RE|_OTHERS_RE|def _clauses", src))
if "def stream_discovery_intent_frame" in src:
  reader_src = src[src.index("def stream_discovery_intent_frame"):src.index("def _mention_hits")]
  check("reader section has no re./regex/word-list scoring", "re." not in reader_src and "startswith" not in reader_src, reader_src[:120])
else:
  check("reader routes through an intent frame (stream_discovery_intent_frame present)", False)
consult_src = (ROOT / "python/api_handlers/intake_consult.py").read_text(encoding="utf-8-sig")
check("production caller hands the app's existing door (_classify_restatement_response) to the reader",
      "door = classify if classify is not None else _classify_restatement_response" in consult_src)

print("=== 3. the six replies (%s) ===" % ("LIVE door" if LIVE else "stubbed door"))
door = ic._classify_restatement_response if LIVE else _stub_door_factory({r: w for r, w in SIX} | {r: w for r, w in CAFE})
for msg, want in SIX:
  got = read(msg, LABELS, ASK, door)
  print(f"   {msg!r} -> {json.dumps(got)}")
  check(f"reader: {msg!r}", got == want, json.dumps(got))
for msg, want in CAFE:
  got = read(msg, CAFE_LABELS, CAFE_ASK, door)
  print(f"   {msg!r} -> {json.dumps(got)}")
  check(f"reader (cafe set): {msg!r}", got == want, json.dumps(got))

print("=== 4. the answer path end-to-end (Cormorant shape, %s) ===" % ("LIVE door" if LIVE else "stubbed door"))
def cormorant_ops():
  return {
    "business_type": BT, "business_naics_6": "311920", "business_stage": "operating",
    "consumer_type": "b2b", "geographic_scope": "regional", "shipping_method": "delivery",
    "sales_modality": "hybrid", "legal_entity": "LLC", "capacity_driver": "labor",
    "primary_growth_lever": "volume",
    "business_description_summary": "A coffee roaster selling five pound wholesale bags to cafes.",
    "lob_models": [{"lob_name": "Wholesale", "products": [
      {"product_name": "Wholesale coffee beans (5 lb bags)", "unit_name": "bag", "unit_description": "one 5 lb bag",
       "unit_cadence": "weekly", "units_per_week_capacity": 300, "units_per_period_capacity": 300,
       "operating_periods_per_year": 52, "utilization_rate": 0.7, "unit_price": 55,
       "cogs_percent_of_line_revenue": None}]}],
    "stream_discovery": {
      "version": 1, "business_type": BT, "naics_6": "311920", "asked": True, "asked_turn_index": 19,
      "ask_text": ASK,
      "candidates": [{"label": l, "commonality": "most", "answer": None} for l in LABELS],
      "proposed": list(LABELS),
    },
  }

def apply(o, msg, last):
  kw = {"ops_json": o, "message": msg, "last_assistant": last}
  if "classify" in inspect.signature(ic._apply_stream_discovery_answer).parameters:
    kw["classify"] = door
  out = ic._apply_stream_discovery_answer(**kw)
  return out if len(out) == 4 else (*out, "")

n0 = 1
# (a) THE BUG: explicit no with 'wholesale' inside -> nothing appended, no receipt claiming a line
o = cormorant_ops()
o, ack, note, clar = apply(o, "No, none of those. We just do the five pound wholesale bags.", ASK)
ans = {c["label"]: c["answer"] for c in o["stream_discovery"]["candidates"]}
print("   answers:", json.dumps(ans)); print("   receipt:", ack)
check("BUG PATH: every proposed label answered no", all(v == "no" for v in ans.values()), json.dumps(ans))
check("BUG PATH: no origin rows written on a no", not any(p.get("origin") == "discovery_confirmed" for l in o["lob_models"] for p in l["products"]))
check("BUG PATH: receipt does not claim any line is its own line", "its own line" not in ack and "move on" in ack, ack)
check("BUG PATH: no clarify", not clar)
# (b) affirmative -> appended + receipt
o = cormorant_ops()
o, ack, note, clar = apply(o, "yeah we do the retail bags", ASK)
disc = [p for l in o["lob_models"] for p in l["products"] if p.get("origin") == "discovery_confirmed"]
check("affirmative: exactly one row appended, named for the label", len(disc) == 1 and disc[0]["product_name"] == "retail coffee bags", json.dumps([p.get("product_name") for p in disc]))
check("affirmative: receipt names the line (words == state)", "retail coffee bags" in ack and "its own line" in ack, ack)
check("affirmative: no clarify", not clar)
# (c) mixed
o = cormorant_ops()
o, ack, note, clar = apply(o, "no retail bags, but yes direct to consumer subscriptions", ASK)
disc = [p["product_name"] for l in o["lob_models"] for p in l["products"] if p.get("origin") == "discovery_confirmed"]
check("mixed: only the confirmed stream appended", disc == ["direct-to-consumer coffee subscriptions"], json.dumps(disc))
# (d) hedge -> ONE clarify, nothing appended; second unclear -> not confirmed, no further ask
o = cormorant_ops()
o, ack, note, clar = apply(o, "sort of, sometimes", ASK)
print("   clarify:", clar)
check("hedge: ONE clarify rendered", bool(clar) and clar.count("?") == 1, clar)
check("hedge: nothing appended, no receipt", ack == "" and not any(p.get("origin") == "discovery_confirmed" for l in o["lob_models"] for p in l["products"]))
check("hedge: still pending for the clarify reply", sd.stream_discovery_pending(o))
if LIVE:
  second = "honestly not sure what you mean"
else:
  second = "sort of, sometimes"
o, ack2, note2, clar2 = apply(o, second, clar)
check("second unclear: NO further clarify", clar2 == "", clar2)
check("second unclear: not confirmed, nothing appended, not pending", not any(p.get("origin") == "discovery_confirmed" for l in o["lob_models"] for p in l["products"]) and not sd.stream_discovery_pending(o) and all(c["answer"] == "unclear" for c in o["stream_discovery"]["candidates"]))
check("second unclear: honest receipt, no question", "tell me its name" in ack2 and "?" not in ack2, ack2)

print()
if FAILS:
  print(f"RED: {len(FAILS)} failing: {FAILS}")
  sys.exit(1)
print("GREEN: F4 red-proof passed (%s)" % ("LIVE door" if LIVE else "stubbed door"))
sys.exit(0)
