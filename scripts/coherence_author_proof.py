"""THE PROOF (Nick 2026-09-12): what each of last night's drafts would have
been offered by the coherence author, next to what they were offered.

  python scripts/coherence_author_proof.py [--drafts 3d57edc6,955d2b46,...] [--out file]

Read-only against the drafts (Halloran & Voss 955d2b46 is evidence - this
script never writes a draft row). The author call is the live one, through
the response lock, so a rerun replays.

How the moment is rebuilt, honestly: a finished draft holds its FINAL
financials, after the walk moved figures. The gate's own first evaluation
(`_coherence.early_eval`, the quarter it judged before any lever) gives the
cost ratios and the flat payroll and rent; the gate's own first message
gives the revenue and the gap it stated. The basis is rebuilt from those
and CHECKED against the gap in that message - the check is printed. The
revenue lines (prices, units) come from the ops model as it stands at the
end, which for a draft whose walk moved prices or volumes is the post-walk
line; that limit is printed too.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from client_intake_and_finmo.intake_submission import get_mysql_connection  # noqa: E402
from client_intake_and_finmo.intake_consult_draft import get_draft  # noqa: E402
from client_intake_and_finmo.intake_coherence import author as A  # noqa: E402
from client_intake_and_finmo.intake_coherence import controller as C  # noqa: E402
from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from client_intake_and_finmo.intake_coherence.evaluator import StructuralBasis, thresholds_from_margin_band  # noqa: E402
from client_intake_and_finmo.openai_http import post_openai_with_retries  # noqa: E402

DEFAULT_DRAFTS = "3d57edc6,955d2b46,578d2006,ef02160d,625de320"
_GAP_RE = re.compile(r"gap[^$\n]{0,24}\$([\d,]+)", re.I)
_REV_RE = re.compile(r"About\s+\$([\d,]+)\s+comes in", re.I)
_OPT_RE = re.compile(r"(?:^|\n|\s)(\d\)\s[^\n]{0,220})")


def _money(s: str) -> float:
  return float(s.replace(",", ""))


def _jd(raw: Any) -> Dict[str, Any]:
  if isinstance(raw, dict):
    return raw
  try:
    v = json.loads(raw or "{}")
    return v if isinstance(v, dict) else {}
  except Exception:
    return {}


def _first_gate_index(msgs: List[Dict[str, Any]]) -> Optional[int]:
  for i, m in enumerate(msgs):
    c = str(m.get("content") or "")
    if m.get("role") == "assistant" and _GAP_RE.search(c) and "work on paper" in c:
      return i
  return None


def _offer_indexes(msgs: List[Dict[str, Any]]) -> List[int]:
  out = []
  for i, m in enumerate(msgs):
    c = str(m.get("content") or "")
    if m.get("role") == "assistant" and ("Which fits" in c or "closes about" in c or "closing about" in c):
      out.append(i)
  return out


def _options_in(text: str) -> List[str]:
  return [o.strip() for o in _OPT_RE.findall(text)]


def _pre_walk_basis(state: Dict[str, Any], first_msg: str):
  early = ((state.get("early_eval") or {}).get("q11")) or {}
  rev = _money(_REV_RE.search(first_msg).group(1)) if _REV_RE.search(first_msg) else 0.0
  e_rev = float(early.get("revenue") or 0.0)
  if rev <= 0 or e_rev <= 0:
    return None
  return StructuralBasis(
    q1_revenue_quarterly=rev,
    cogs_pct=float(early.get("cogs") or 0.0) / e_rev,
    payroll_quarterly=float(early.get("payroll") or 0.0),
    rent_quarterly=float(early.get("rent") or 0.0),
    gna_pct=float(early.get("gna") or 0.0) / e_rev,
    marketing_pct=float(early.get("marketing") or 0.0) / e_rev,
    growth_to_q11=1.0,
  )


def _reset_state(state: Dict[str, Any]) -> Dict[str, Any]:
  keep = ("margin_band_judgment", "judged_growth", "bounds", "demand_response", "essentials_response",
          "price_market_facts", "digest_hash", "walls")
  st = {k: state[k] for k in keep if k in state}
  st["status"] = C.STATUS_WALKING
  return st


class Meter:
  def __init__(self):
    self.calls: List[Dict[str, Any]] = []

  def post(self, **kw):
    t0 = time.time()
    resp = post_openai_with_retries(**kw)
    rec = {"seconds": round(time.time() - t0, 1), "status": resp.status_code}
    try:
      u = resp.json().get("usage") or {}
      rec["input_tokens"] = u.get("input_tokens")
      rec["output_tokens"] = u.get("output_tokens")
    except Exception:
      pass
    self.calls.append(rec)
    return resp


def _fmt_option(o: Dict[str, Any]) -> str:
  rec = "  <- recommended" if o.get("recommended") else ""
  deep = "  (deep cut)" if o.get("deep_cut") else ""
  return f"    - [{o.get('id')}] {o.get('label')}\n        why: {o.get('why')}\n        closes: {o.get('closes_display')}{deep}{rec}"


def run_draft(conn, prefix: str, out: List[str], meter: Meter, report: Dict[str, Any]) -> None:
  cur = conn.cursor()
  cur.execute("SELECT draft_id FROM intake_consult_drafts WHERE draft_id LIKE %s", (prefix + "%",))
  rows = cur.fetchall()
  cur.close()
  if len(rows) != 1:
    out.append(f"##### {prefix}: {len(rows)} rows match - skipped")
    return
  draft = get_draft(conn, draft_id=rows[0][0]) or {}
  name = str(draft.get("business_name") or "")
  msgs = draft.get("messages_json") or []
  if isinstance(msgs, str):
    msgs = json.loads(msgs or "[]")
  msgs = [m for m in msgs if isinstance(m, dict)]
  ops_json = _jd(draft.get("operating_model_json"))
  people_json = _jd(draft.get("people_json"))
  market_json = _jd(draft.get("target_market_json"))
  marketing_model_json = _jd(draft.get("marketing_model_json"))
  financials_json = _jd(draft.get("financials_json"))
  state = S.get_state(financials_json)
  rep: Dict[str, Any] = {"draft": prefix, "business": name, "messages": len(msgs)}
  report[prefix] = rep
  out.append("=" * 100)
  out.append(f"{name}  ({prefix})  {len(msgs)} messages  stored status={state.get('status')}")

  g = _first_gate_index(msgs)
  if g is None:
    out.append("  The gate never stated a gap in this transcript: the numbers passed at the first evaluation.")
    out.append("  Nothing was offered, and nothing would be authored - there is no gap to close.")
    rep["gate_fired"] = False
    return
  rep["gate_fired"] = True
  first_msg = str(msgs[g].get("content") or "")
  stated_gap = _money(_GAP_RE.search(first_msg).group(1))
  basis = _pre_walk_basis(state, first_msg)
  band = state.get("margin_band_judgment")
  th = thresholds_from_margin_band(band)
  if basis is None:
    out.append("  could not rebuild the pre-walk basis (no early_eval or no revenue in the gate message)")
    return
  gap = C._gap(basis, th)
  out.append(f"  gate fired at message {g}. Gap stated then: ${stated_gap:,.0f} a quarter; "
             f"rebuilt pre-walk basis gives ${gap:,.0f} ({(gap / stated_gap - 1) * 100:+.1f}%)")
  rep["gap_stated"] = stated_gap
  rep["gap_rebuilt"] = round(gap)

  # bounds: stored, else the same judgment the gate would author (through the lock)
  st = _reset_state(state)
  if not st.get("bounds"):
    out.append("  bounds: not stored on this draft - authoring the bounds judgment now (GPT, through the lock)")
    st = S._ensure_bounds(st, ops_json=ops_json, people_json=people_json, market_json=market_json,
                          marketing_model_json=marketing_model_json, financials_json=financials_json)
  else:
    out.append("  bounds: stored on the draft")
  bounds = st.get("bounds") or {}
  fin_reset = S.put_state(financials_json, st)
  split = C.ops_line_split(ops_json, financials_json)
  out.append(f"  revenue lines from the ops model as it stands now (post-walk where the walk moved them): "
             + "; ".join(f"{l['product']} ${l['unit_price']:,.2f} x {l['annual_units']:,.0f}/yr" for l in split))

  # ---- WHAT THEY WERE OFFERED
  offers = _offer_indexes(msgs)
  out.append("")
  out.append("  WHAT THEY WERE OFFERED (from the transcript):")
  out.append(f"    first gate message [{g}]: " + first_msg[:500].replace("\n", " ") + " ...")
  for i in offers[:1] + offers[-1:]:
    if i == g:
      continue
    opts = _options_in(str(msgs[i].get("content") or ""))
    out.append(f"    [{i}] after client said: {str(msgs[i-1].get('content') or '')[:140]!r}")
    for o in opts[:4]:
      out.append(f"        {o}")
  rep["actual_offers"] = [{"index": i, "after": str(msgs[i - 1].get("content") or "")[:200],
                           "options": _options_in(str(msgs[i].get("content") or ""))[:4]} for i in offers]
  rep["first_gate_message"] = first_msg[:1200]

  legacy = C.plan_rounds(basis=basis, thresholds=th, bounds=bounds, ops_json=ops_json,
                         financials_json=fin_reset, rounds_done=None)
  out.append("")
  out.append("  THE LEGACY ENGINE, rerun on the rebuilt basis (what the code would offer first, without the agent):")
  if legacy:
    out.append(f"    round={legacy.get('key')}")
    for o in legacy.get("options") or []:
      out.append(_fmt_option(o))
    rep["legacy_round"] = {"key": legacy.get("key"), "options": [
      {k: o.get(k) for k in ("id", "label", "closes_display", "recommended")} for o in legacy.get("options") or []]}
  else:
    out.append("    (no round)")

  # ---- WHAT THEY WOULD HAVE BEEN OFFERED
  points = [("A - at the first offer", g)]
  last_user_before_last_offer = None
  if offers:
    k = offers[-1] - 1
    while k > g and msgs[k].get("role") != "user":
      k -= 1
    if k > g:
      last_user_before_last_offer = k
  if last_user_before_last_offer is not None:
    points.append(("B - after everything the client said during the walk", last_user_before_last_offer + 1))
  rep["authored"] = []
  for label, cut in points:
    transcript = msgs[:cut]
    st_pt = dict(st)
    n0 = len(meter.calls)
    t0 = time.time()
    rnd, st2, _fin2 = S._authored_round(
      state=st_pt, basis=basis, thresholds=th, bounds=bounds, ops_json=ops_json, financials_json=fin_reset,
      transcript=transcript, gap=gap,
      author=lambda payload: A.author(payload=payload, post=meter.post),
    )
    calls = meter.calls[n0:]
    out.append("")
    out.append(f"  WHAT THEY WOULD HAVE BEEN OFFERED - point {label} (transcript through message {cut - 1}, "
               f"{sum(1 for m in transcript if m.get('role') == 'user')} client turns):")
    out.append(f"    author call: {calls[0] if calls else 'replayed/none'}  wall {time.time() - t0:.1f}s")
    entry: Dict[str, Any] = {"point": label, "through": cut - 1, "call": calls[0] if calls else None}
    if rnd is None:
      out.append(f"    nothing authored: {st2.get('authored_fallback')}; rejections={st2.get('authored_rejections')}")
      entry["fallback"] = st2.get("authored_fallback")
      entry["rejections"] = st2.get("authored_rejections")
      rep["authored"].append(entry)
      continue
    fr = rnd.get("floors_read") or []
    out.append("    floors the agent read in the client's words: " + (
      "; ".join(f"{f.get('cost')} ({f.get('kind')}) - \"{str(f.get('because'))[:110]}\"" for f in fr) if fr else "none"))
    fm = st2.get("floors_mentioned") or []
    if fm:
      out.append("    costs the client mentioned without refusing (hold nothing): " + "; ".join(
        f"{f.get('cost')} - \"{str(f.get('because'))[:90]}\"" for f in fm))
    out.append(f"    options ({len(rnd['options'])}):")
    for o in rnd["options"]:
      out.append(_fmt_option(o))
    rej = st2.get("authored_rejections") or []
    if rej:
      out.append("    refused by the engine: " + "; ".join(
        f"{r['candidate'].get('kind')}:{r['candidate'].get('levers') or [lm.get('line', '')[:30] for lm in (r['candidate'].get('line_moves') or [])]} -> {r['reason']}" for r in rej))
    q = S._round_question(rnd, S._fmt(gap))
    out.append("    the message the client would have seen:")
    for line in q.split(". "):
      out.append("      " + line.strip())
    entry.update({
      "floors_read": fr,
      "floors_mentioned": fm,
      "options": [{k: o.get(k) for k in ("id", "label", "why", "closes_display", "recommended", "deep_cut")} for o in rnd["options"]],
      "rejections": rej,
      "question": q,
    })
    rep["authored"].append(entry)


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--drafts", default=DEFAULT_DRAFTS)
  ap.add_argument("--out", default=os.path.join(ROOT, "_coherence_proof_20260912.txt"))
  args = ap.parse_args()
  conn = get_mysql_connection()
  out: List[str] = []
  report: Dict[str, Any] = {}
  meter = Meter()
  for prefix in [p.strip() for p in args.drafts.split(",") if p.strip()]:
    try:
      run_draft(conn, prefix, out, meter, report)
    except Exception as exc:  # the proof reports, it does not hide
      import traceback
      out.append(f"##### {prefix}: FAILED {type(exc).__name__}: {exc}")
      out.append(traceback.format_exc())
  conn.close()
  out.append("=" * 100)
  tot_in = sum(int(c.get("input_tokens") or 0) for c in meter.calls)
  tot_out = sum(int(c.get("output_tokens") or 0) for c in meter.calls)
  out.append(f"author calls: {len(meter.calls)}  input tokens {tot_in:,}  output tokens {tot_out:,}  "
             f"seconds {sum(c['seconds'] for c in meter.calls):.0f}")
  report["_meter"] = meter.calls
  text = "\n".join(out)
  with open(args.out, "w", encoding="utf-8") as fh:
    fh.write(text)
  with open(os.path.splitext(args.out)[0] + ".json", "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
  print(text)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
