"""OFFLINE red-proof for the discovery reader CONVERGENCE (Nick's ruling
2026-08-17, Option A) - the deterministic bookkeeping around the SHARED
reader, on the Corvid Press shapes (e3af1f24). No GPT, no DB.

PRODUCTION CALL CHAIN (the pieces exercised here are the exact functions the
handler calls, with production data shapes):
  intake_consult._open_stream_discovery_window (window only, no read)
  -> consultant_chat_turn [live GPT; simulated here by the snapshot it returns]
  -> _apply_model_ops_patch
  -> gpt_stream_discovery.record_stream_discovery_outcomes (origin stamp,
     latch answer, receipt from STATE)
  -> carry_stream_discovery (no resurrection) + note_stream_discovery_removals
  -> align_gate_rows_with_persisted (wrap gate == persisted row set)
  -> finalize: carry_stream_discovery(restore_dropped=True)

  .venv\\Scripts\\python.exe "Test Files\\_discovery_reader_convergence_redproof.py"
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "client_intake_and_finmo"))
try:
  sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
  pass

from client_intake_and_finmo.intake_coherence import gpt_stream_discovery as sd  # type: ignore

FAILS: list = []


def check(label, ok, detail=""):
  print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
  if not ok:
    FAILS.append(label)


PHANTOM = "Digital printing services"
LABELS = [PHANTOM, "Copying and duplicating services", "Graphic design and prepress services", "Bindery and finishing services"]


def row(name, price, cap, util, origin=None):
  return {
    "product_name": name, "unit_name": name, "unit_description": None, "unit_cadence": "contract",
    "units_per_week_capacity": cap, "units_per_period_capacity": cap, "operating_periods_per_year": 52,
    "utilization_rate": util, "unit_price": price, "cogs_percent_of_line_revenue": None, "origin": origin,
  }


def corvid_ops(*, with_phantom: bool, answers=None):
  ops = {
    "business_type": "Commercial Print House",
    "lob_models": [
      {"lob_name": "Commercial print (brochures/forms/catalogs/labels)", "products": [row("Standard commercial print job", 862.5, 30, 0.528)]},
      {"lob_name": "Wide-format banners and signage", "products": [row("Wide-format job", 567.0, 9, 0.44)]},
    ],
    "stream_discovery": {
      "asked": True, "asked_turn_index": 21,
      "ask_text": sd.compose_stream_discovery_ask("Commercial Print House", LABELS),
      "candidates": [{"label": L, "commonality": "most", "answer": (answers or {}).get(L)} for L in LABELS],
      "proposed": list(LABELS),
    },
  }
  if with_phantom:
    ops["lob_models"].append({"lob_name": PHANTOM, "products": [
      {"product_name": PHANTOM, "unit_name": None, "unit_description": None, "unit_cadence": None,
       "units_per_week_capacity": None, "units_per_period_capacity": None, "operating_periods_per_year": None,
       "utilization_rate": None, "unit_price": None, "cogs_percent_of_line_revenue": None, "origin": "discovery_confirmed"}]})
  return ops


def rows_of(ops):
  return [(l["lob_name"], p["product_name"], p.get("origin"), p.get("unit_price")) for l in ops["lob_models"] for p in l["products"]]


def answers(ops):
  return {c["label"]: c.get("answer") for c in ops["stream_discovery"]["candidates"]}


print("=== 1. THE PARALLEL READER IS GONE (source-level) ===")
src_sd = (ROOT / "python/client_intake_and_finmo/intake_coherence/gpt_stream_discovery.py").read_text(encoding="utf-8")
src_ic = (ROOT / "python/api_handlers/intake_consult.py").read_text(encoding="utf-8-sig")
src_cons = (ROOT / "python/client_intake_and_finmo/intake_consultant.py").read_text(encoding="utf-8-sig")
for name in ("read_stream_discovery_answer", "stream_discovery_intent_frame", "_DOOR_TO_ANSWER", "append_confirmed_stream_rows", "new_discovered_row", "_mention_hits"):
  check(f"deleted from the module: {name}", name not in src_sd, name)
check("intake_consult: no _apply_stream_discovery_answer", "_apply_stream_discovery_answer" not in src_ic)
seam = src_ic[src_ic.index("def _open_stream_discovery_window"):src_ic.index("def _is_guardrail_acknowledgement")]
check("the discovery window never calls _classify_restatement_response (no per-candidate door)", "_classify_restatement_response" not in seam)
check("_classify_restatement_response still exists for its restatement callers", src_ic.count("_classify_restatement_response(") >= 2, str(src_ic.count("_classify_restatement_response(")))
check("no discovery loop over labels calling classify anywhere in intake_consult", not re.search(r"for\s+\w+\s+in\s+\w*lab\w*:\s*\n\s*.*classify\(", src_ic))
check("shared reader schema carries stream_discovery_outcomes", '"stream_discovery_outcomes"' in src_cons and '"enum": ["added", "merged_into", "declined", "unclear"]' in src_cons)
check("shared reader prompt: explicit client removal => omit the row (the :426 do-not-drop clause reconciled)", "the ONE exception is a line the client explicitly retracted" in src_cons and "OMIT that product row" in src_cons)
check("shared reader prompt: discovery section (already inside => add nothing; yes => new row; never restate)", "Stream discovery (the app's proposal" in src_cons and "it stays inside X" in src_cons)
check("wrap gate aligned to persisted discovery rows", "align_gate_rows_with_persisted(ops_json, gate_obj)" in src_ic)
check("finalize sites carry with restore_dropped=True (from the shared model's own filled row only)", src_ic.count("carry_stream_discovery(ops_json, final_obj, restore_dropped=True)") == 2)
check("ordinary ops turn carry has NO restore (model snapshot authoritative)", "carry_stream_discovery(_ops_before, ops_json)" in src_ic and "restore_dropped=True" not in src_ic[src_ic.index("carry_stream_discovery(_ops_before, ops_json)")-2000:src_ic.index("carry_stream_discovery(_ops_before, ops_json)")+200])
check("email/delivery path untouched (workbook_email / notify lines not in diff scope)", "workbook_email" not in seam)

print("\n=== 2. CASE A (merged): the shared reader keeps digital printing inside commercial print ===")
before = corvid_ops(with_phantom=False)
after = copy.deepcopy(before)  # the shared reader's snapshot: 2 lines, nothing added
model_outcomes = [
  {"label": PHANTOM, "outcome": "merged_into", "line": "Standard commercial print job"},
  {"label": "Copying and duplicating services", "outcome": "declined", "line": None},
  {"label": "Graphic design and prepress services", "outcome": "declined", "line": None},
  {"label": "Bindery and finishing services", "outcome": "declined", "line": None},
]
after, receipts, clar = sd.record_stream_discovery_outcomes(before, after, message="Digital printing is already part of our commercial print line...", pending_labels=LABELS, model_outcomes=model_outcomes, clarify_round=False)
print("  receipts:", receipts)
print("  latch:", json.dumps(answers(after)))
check("A: no clarify", clar == [])
check("A: model still has 2 lines (no phantom)", len(rows_of(after)) == 2 and not any(r[2] == "discovery_confirmed" for r in rows_of(after)))
check("A: latch merged_into:<the client's line>", answers(after)[PHANTOM] == "merged_into:Standard commercial print job", answers(after)[PHANTOM])
check("A: three declined", all(answers(after)[L] == "declined" for L in LABELS[1:]))
check("A: receipt says stays inside, never 'is its own line'", any("stays inside Standard commercial print job" in r for r in receipts) and not any("is its own line" in r for r in receipts), str(receipts))
check("A: not pending afterwards", not sd.stream_discovery_pending(after))
after2 = sd.carry_stream_discovery(before, copy.deepcopy(after))
check("A: carry does not mint the phantom (no confirmed label => nothing to carry)", rows_of(after2) == rows_of(after))
gate = {"lob_models": copy.deepcopy(before["lob_models"]) + [{"lob_name": PHANTOM, "products": [row(PHANTOM, None, None, None, "discovery_confirmed")]}]}
gate = sd.align_gate_rows_with_persisted(after2, gate)
check("A: a phantom the gate re-derivation invented is REMOVED from the gate (gate == persisted)", not any(r[1] == PHANTOM for r in rows_of(gate)), json.dumps(rows_of(gate)))

print("\n=== 3. CASE C (genuine yes, Nine Fathom shape): the shared reader adds a real row; Python stamps + records ===")
nf_before = {"lob_models": [{"lob_name": "Roasted coffee", "products": [row("5 lb bag roasted coffee", 58, 380, 0.75)]}],
             "stream_discovery": {"asked": True, "ask_text": "x", "candidates": [
               {"label": "retail coffee bags", "answer": None}, {"label": "wholesale coffee sales to grocery stores", "answer": None}, {"label": "brew gear and merchandise sales", "answer": None}]}}
nf_after = copy.deepcopy(nf_before)
nf_after["lob_models"].append({"lob_name": "retail coffee bags", "products": [row("retail coffee bags", None, None, None)]})
nf_after["lob_models"].append({"lob_name": "Wholesale coffee to grocery stores", "products": [row("Wholesale coffee to grocery stores", None, None, None)]})
oc = [{"label": "retail coffee bags", "outcome": "added", "line": None},
      {"label": "wholesale coffee sales to grocery stores", "outcome": "added", "line": None},
      {"label": "brew gear and merchandise sales", "outcome": "declined", "line": None}]
nf_after, rec, clar = sd.record_stream_discovery_outcomes(nf_before, nf_after, message="Yeah, we do sell retail coffee bags... And yes, we do wholesale... But no, we don't do brew gear", pending_labels=[c["label"] for c in nf_before["stream_discovery"]["candidates"]], model_outcomes=oc, clarify_round=False)
print("  receipts:", rec)
print("  latch:", json.dumps(answers(nf_after)))
r = rows_of(nf_after)
check("C: two genuine yeses -> two rows stamped discovery_confirmed", sum(1 for x in r if x[2] == "discovery_confirmed") == 2, json.dumps(r))
check("C: exact-name row stamped", any(x[1] == "retail coffee bags" and x[2] == "discovery_confirmed" for x in r))
check("C: renamed row paired to its label by overlap and stamped", any(x[1] == "Wholesale coffee to grocery stores" and x[2] == "discovery_confirmed" for x in r))
check("C: latch added / added / declined", answers(nf_after) == {"retail coffee bags": "added", "wholesale coffee sales to grocery stores": "added", "brew gear and merchandise sales": "declined"}, json.dumps(answers(nf_after)))
check("C: latch records the actual row name for the renamed one", nf_after["stream_discovery"]["candidates"][1].get("row_product_name") == "Wholesale coffee to grocery stores")
check("C: receipts name each added line + numbers next; no is not mentioned", sum(1 for x in rec if "is its own line; a few quick numbers" in x) == 2 and not any("brew gear" in x for x in rec), str(rec))
check("C: primary row untouched", r[0] == ("Roasted coffee", "5 lb bag roasted coffee", None, 58))
# carry on a later ordinary turn keeps both (model still has them) and scrubs invented origin
later = copy.deepcopy(nf_after)
later["lob_models"][0]["products"][0]["origin"] = "invented_by_model"
later = sd.carry_stream_discovery(nf_after, later)
check("C: carry keeps both discovery rows and scrubs an invented origin on the primary", later["lob_models"][0]["products"][0]["origin"] is None and sum(1 for x in rows_of(later) if x[2] == "discovery_confirmed") == 2)
# gate alignment: a persisted null-driver discovery row is FORCED into the gate snapshot
gate = {"lob_models": [{"lob_name": "Roasted coffee", "products": [row("5 lb bag roasted coffee", 58, 380, 0.75)]}]}
gate = sd.align_gate_rows_with_persisted(later, gate)
gr = rows_of(gate)
check("C: gate snapshot now carries the two persisted discovery rows (null drivers) -> wrap cannot fire past them", sum(1 for x in gr if x[2] == "discovery_confirmed") == 2 and any(x[3] is None for x in gr), json.dumps(gr))
# model claims added but wrote no row -> not believed
nb_after = copy.deepcopy(nf_before)
nb_after, rec2, _ = sd.record_stream_discovery_outcomes(nf_before, nb_after, message="m", pending_labels=["retail coffee bags"], model_outcomes=[{"label": "retail coffee bags", "outcome": "added", "line": None}], clarify_round=False)
check("C: model says added but wrote no row -> declined + reason (state is the truth), no false receipt", answers(nb_after)["retail coffee bags"] == "declined" and nb_after["stream_discovery"]["candidates"][0].get("answer_reason") == "model_reported_added_but_wrote_no_row" and not any("its own line" in x for x in rec2), json.dumps(nb_after["stream_discovery"]["candidates"][0]))
# unclear -> ONE clarify then unclear-after-clarify
uc = copy.deepcopy(nf_before)
uc, rec3, clar3 = sd.record_stream_discovery_outcomes(nf_before, uc, message="hmm maybe", pending_labels=["retail coffee bags"], model_outcomes=[{"label": "retail coffee bags", "outcome": "unclear", "line": None}], clarify_round=False)
check("C: unclear first round -> held for ONE clarify, no answer yet", clar3 == ["retail coffee bags"] and uc["stream_discovery"]["candidates"][0]["answer"] is None and uc["stream_discovery"].get("clarify_asked") is True)
uc, rec4, clar4 = sd.record_stream_discovery_outcomes(nf_before, uc, message="still dunno", pending_labels=["retail coffee bags"], model_outcomes=[{"label": "retail coffee bags", "outcome": "unclear", "line": None}], clarify_round=True)
check("C: unclear after clarify -> unclear, not confirmed, honest move-on receipt", clar4 == [] and answers(uc)["retail coffee bags"] == "unclear" and any("none of them for now" in x for x in rec4))

print("\n=== 4. CASE B (removed): 'drop that line' - the shared reader omits the row; NEVER resurrected ===")
b_before = corvid_ops(with_phantom=True, answers={PHANTOM: "yes", LABELS[1]: "no", LABELS[2]: "no", LABELS[3]: "no"})  # legacy latch vocab as persisted live
b_after = corvid_ops(with_phantom=False, answers={PHANTOM: "yes", LABELS[1]: "no", LABELS[2]: "no", LABELS[3]: "no"})  # the shared reader's snapshot: row omitted
b_after = sd.carry_stream_discovery(b_before, b_after)
rec = sd.note_stream_discovery_removals(b_before, b_after, message="No, don't make digital printing a separate line ... Please drop that line.")
print("  receipts:", rec, "latch:", json.dumps(answers(b_after)))
check("B: ordinary-turn carry does NOT resurrect the omitted row", not any(r[1] == PHANTOM for r in rows_of(b_after)), json.dumps(rows_of(b_after)))
check("B: latch records removed (from legacy 'yes')", answers(b_after)[PHANTOM] == "removed")
check("B: removal receipt", rec == [f"Noted - {PHANTOM} is dropped as a separate line."], str(rec))
check("B: removed_from stamped", "drop that line" in b_after["stream_discovery"]["candidates"][0].get("removed_from", ""))
# next turn: model returns the 2-line snapshot again -> still gone, latch stays removed, no receipt again
n_after = sd.carry_stream_discovery(b_after, copy.deepcopy(b_after))
rec_n = sd.note_stream_discovery_removals(b_after, n_after, message="That's about right.")
check("B: next turn: still gone, no second removal receipt", not any(r[1] == PHANTOM for r in rows_of(n_after)) and rec_n == [] and answers(n_after)[PHANTOM] == "removed")
# gate: a fresh re-derivation that still carries the phantom -> gate drops it (persisted lacks it)
gate = {"lob_models": copy.deepcopy(b_before["lob_models"])}
gate = sd.align_gate_rows_with_persisted(n_after, gate)
check("B: wrap gate == persisted: the phantom is removed from the gate snapshot", not any(r[1] == PHANTOM for r in rows_of(gate)), json.dumps(rows_of(gate)))
# finalize: consultant_finalize returns 2 lines; carry(restore_dropped=True) must NOT mint from the latch
fin = {"lob_models": copy.deepcopy(b_after["lob_models"])}
fin = sd.carry_stream_discovery(n_after, fin, restore_dropped=True)
check("B: finalize carry does NOT resurrect (removed label is not confirmed; nothing minted)", not any(r[1] == PHANTOM for r in rows_of(fin)) and isinstance(fin.get("stream_discovery"), dict), json.dumps(rows_of(fin)))
check("B: latch re-attached across the wholesale finalize replace (auditable record survives)", answers(fin)[PHANTOM] == "removed")
# even a legacy 'yes' latch with NO before-row is never minted at finalize
ghost_before = corvid_ops(with_phantom=False, answers={PHANTOM: "yes"})
ghost_fin = sd.carry_stream_discovery(ghost_before, {"lob_models": copy.deepcopy(ghost_before["lob_models"])}, restore_dropped=True)
check("B: a yes-latch with no row in the shared model mints NOTHING at finalize (never from the latch)", not any(r[1] == PHANTOM for r in rows_of(ghost_fin)))
# a null-driver before-row is not restored at finalize either (never a null-driver row from carry)
nulled_before = corvid_ops(with_phantom=True, answers={PHANTOM: "yes"})
nulled_fin = sd.carry_stream_discovery(nulled_before, {"lob_models": copy.deepcopy(corvid_ops(with_phantom=False)["lob_models"])}, restore_dropped=True)
check("B: finalize never restores a NULL-driver row (nothing to carry)", not any(r[1] == PHANTOM for r in rows_of(nulled_fin)))
# a FILLED discovery row the finalize re-derivation lost IS carried from the shared model's own row
filled_before = corvid_ops(with_phantom=False, answers={PHANTOM: "added"})
filled_before["lob_models"].append({"lob_name": PHANTOM, "products": [row(PHANTOM, 300, 12, 0.7, "discovery_confirmed")]})
filled_fin = sd.carry_stream_discovery(filled_before, {"lob_models": copy.deepcopy(corvid_ops(with_phantom=False)["lob_models"])}, restore_dropped=True)
kept = [r for r in rows_of(filled_fin) if r[1] == PHANTOM]
check("B: finalize carries a FILLED discovery row the re-derivation lost, from the shared model's own row (price 300)", kept == [(PHANTOM, PHANTOM, "discovery_confirmed", 300)], json.dumps(kept))
# on an ORDINARY turn the same filled row omitted by the shared reader is a removal, not restored
ord_after = sd.carry_stream_discovery(filled_before, {"lob_models": copy.deepcopy(corvid_ops(with_phantom=False)["lob_models"]), "stream_discovery": copy.deepcopy(filled_before["stream_discovery"])})
rec_o = sd.note_stream_discovery_removals(filled_before, ord_after, message="take digital printing out")
check("B: ordinary turn: the shared reader's omission of a filled discovery row is honored as a removal (never restored)", not any(r[1] == PHANTOM for r in rows_of(ord_after)) and answers(ord_after)[PHANTOM] == "removed" and len(rec_o) == 1)

print("\n=== 5. Window opener: window detection only, no reader ===")
sys.path.insert(0, str(ROOT / "python" / "api_handlers"))
import importlib
ic = importlib.import_module("api_handlers.intake_consult")
o = corvid_ops(with_phantom=False)
o2, note, labels, cr = ic._open_stream_discovery_window(ops_json=copy.deepcopy(o), last_assistant=o["stream_discovery"]["ask_text"])
check("window: ask was last -> note + all 4 pending labels + not clarify round", bool(note) and labels == LABELS and cr is False)
check("window: note tells the shared reader yes=add / already-inside=merged_into / decline / unclear and that its snapshot is authoritative", all(k in note for k in ("'added'", "'merged_into'", "'declined'", "'unclear'", "snapshot is authoritative")), note[:200])
o3, note3, labels3, _ = ic._open_stream_discovery_window(ops_json=copy.deepcopy(o), last_assistant="Some other question?")
check("window: ask NOT last -> closed honestly (unclear, ask_not_last_assistant), no note", note3 == "" and labels3 == [] and all(c["answer"] == "unclear" and c["answer_reason"] == "ask_not_last_assistant" for c in o3["stream_discovery"]["candidates"]))
oc_ = copy.deepcopy(o); oc_["stream_discovery"]["clarify_asked"] = True
o4, note4, labels4, cr4 = ic._open_stream_discovery_window(ops_json=oc_, last_assistant=sd.compose_stream_discovery_clarify([PHANTOM]))
check("window: the clarify was last -> clarify round", cr4 is True and bool(note4) and "clarifying question" in note4)

print()
if FAILS:
  print(f"RED: {len(FAILS)} failing: {FAILS}")
  sys.exit(1)
print("GREEN: discovery reader convergence red-proof passed")
