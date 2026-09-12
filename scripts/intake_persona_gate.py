"""INTAKE PERSONA GATE - a scripted client driven through the REAL
conversational handler headless, with assertions on what ends up stored
(Nick 2026-09-11: "Every intake defect this week was found by a person
talking to the app - the plug, the invented headcount, the price/capacity
ping-pong, the user_message door. The replay gate would have caught none of
them.").

Each persona (scripts/intake_personas.py) is a business, a fixed set of
answers keyed on what the app asks, and checks on the stored draft. Per
persona the driver:
  1. builds the Flask app IN-PROCESS (api.create_app) - the code on disk, no
     :5050, no stale server - and posts to /api/intake-consult exactly as the
     form does;
  2. creates a scratch draft (client_id "rpgate...": the replay's sweep owns
     it, and the watcher and live monitor ignore it);
  3. answers every app message with the persona's first matching rule. A
     question no rule answers stops the run UNSCRIPTED - it never improvises;
  4. snapshots the stored draft after every turn, runs the persona's checks
     over the whole record, saves the full transcript, and sweeps the draft.
It stops at intake-complete: the system run (and so the writing phase) is
never started - the post-intake replay covers that half.

GPT: every intake call goes through the response lock (content-addressed;
draft ids and datetimes stripped). The first run of a conversation calls GPT
live and records it; a later run of the same conversation replays it.
  default   lock on - replay what is recorded, call live (and record) what is new
  --strict  replay only - a call the store never saw is GPT_MISS, never live
  --fresh   lock off - every call live, nothing recorded; re-samples GPT for the
            probabilistic defects (issue 578's one figure written to two fields)

A change to a persona's rules changes its conversation from that turn on, so
its recording no longer covers it: after editing intake_personas.py, run
once in default mode (re-records the new part), then --strict proves it.

Verdicts: PASS | FAIL (a check is red - the app) | LOOP (the app repeated
itself - the app) | UNSCRIPTED (the script has no answer - the harness) |
GPT_MISS | ERROR. Exit 0 only when every persona PASSES.

  python scripts/intake_persona_gate.py                  # every persona, in parallel
  python scripts/intake_persona_gate.py --persona baseline
  python scripts/intake_persona_gate.py --strict
  python scripts/intake_persona_gate.py --keep           # leave the scratch drafts
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "python")
for _p in (os.path.join(ROOT, "scripts"), os.path.join(PY, "client_intake_and_finmo"), PY, ROOT):
  if _p not in sys.path:
    sys.path.insert(0, _p)

OUT_DIR = os.path.join(ROOT, "_runtime", "intake_gate")
REPORT_PATH = os.path.join(ROOT, "_runtime", "intake_gate_last.json")
SCRATCH_PREFIX = "rpgate"          # the replay's scratch prefix: its sweep owns these drafts
MAX_TURNS = 140
LOOP_REPEATS = 3
MODES = ("default", "strict", "fresh")


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------
def question_part(reply: str) -> str:
  """The paragraphs of an app message that ask something. A receipt ("Got it
  - I'll use $4,500 for monthly rent.") must not answer for the question."""
  paras = [p.strip() for p in re.split(r"\n\s*\n", reply or "") if p.strip()]
  asks = [p for p in paras if "?" in p]
  return "\n".join(asks) if asks else (reply or "")


def pick_rule(rules, reply: str, focus: str):
  q, full = question_part(reply).lower(), (reply or "").lower()
  for r in rules:
    if r["stage"] not in ("*", focus):
      continue
    if r["times"] is not None and r["used"] >= r["times"]:
      continue
    if re.search(r["ask"], full if r["scope"] == "all" else q, re.I | re.S):
      return r
  return None


# ---------------------------------------------------------------------------
# GPT meter: counts every call the app makes, live or replayed
# ---------------------------------------------------------------------------
class GptMeter:
  """Wraps openai_http._record_call_vitals, which the app calls once per GPT
  request on BOTH paths (a lock replay and a live call), with the response
  body. The module is imported under two names; both are wrapped."""

  MODULES = ("openai_http", "client_intake_and_finmo.openai_http")

  def __init__(self, dump_dir=None):
    self.calls = []
    self.mods = []
    self.dump_dir = dump_dir

  def install(self):
    for name in self.MODULES:
      try:
        m = importlib.import_module(name)
      except Exception:
        continue
      if getattr(m, "_intake_gate_meter", None) is not None:
        continue
      orig = m._record_call_vitals

      def wrapped(*a, _orig=orig, **k):
        try:
          self._add(k)
        except Exception:
          pass
        return _orig(*a, **k)

      m._record_call_vitals = wrapped
      m._intake_gate_meter = self
      self.mods.append(m)

  def _add(self, k):
    if str((k.get("payload") or {}).get("model") or "") == PERSONA_MODEL:
      return  # the --author client's own calls are not the app's
    body = k.get("body") if isinstance(k.get("body"), dict) else {}
    usage = body.get("usage") or {}
    # The request as the lock sees it (ids and datetimes normalized): two runs
    # of one conversation must produce the same keys, or nothing replays.
    payload = k.get("payload") or {}
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    try:
      canon = self.mods[0]._VOLATILE_TOKEN_RE.sub("<VOLATILE>", canon)
    except Exception:
      pass
    import hashlib
    req_key = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
    if self.dump_dir:
      os.makedirs(self.dump_dir, exist_ok=True)
      with open(os.path.join(self.dump_dir, "%03d_%s_%s.json" % (
          len(self.calls), "replay" if k.get("lock_replay") else "live", req_key)), "w", encoding="utf-8") as fh:
        fh.write(canon)
    self.calls.append({
      "req": req_key,
      "replay": bool(k.get("lock_replay")),
      "seconds": round(time.monotonic() - float(k.get("started_monotonic") or time.monotonic()), 3),
      "tokens_in": int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
      "tokens_out": int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
      "model": str(body.get("model") or (k.get("payload") or {}).get("model") or ""),
      "error": k.get("error"),
    })

  def strict_misses(self):
    out = []
    for m in self.mods:
      out.extend(getattr(m, "_STRICT_MISSES", []) or [])
    return out

  def summary(self):
    live = [c for c in self.calls if not c["replay"]]
    rep = [c for c in self.calls if c["replay"]]
    return {
      "calls": len(self.calls), "live": len(live), "replayed": len(rep),
      "live_seconds": round(sum(c["seconds"] for c in live), 1),
      "tokens_in": sum(c["tokens_in"] for c in live), "tokens_out": sum(c["tokens_out"] for c in live),
      "models": dict(Counter(c["model"] for c in live)),
      "errors": [c["error"] for c in self.calls if c["error"]],
      "keys": ["%s:%s" % ("R" if c["replay"] else "L", c["req"]) for c in self.calls],
    }


# ---------------------------------------------------------------------------
# --author: draft answers for the questions no rule covers yet
# ---------------------------------------------------------------------------
PERSONA_MODEL = "gpt-4.1-mini"


def improvise(brief: str, app_message: str) -> str:
  """A GPT client answers from the persona's brief. Through the same response
  lock as the app, so an author rerun asks and answers identically. Every
  improvised answer is listed; an author run is never a pass - the answers
  become rules, and the rules are the spec."""
  from client_intake_and_finmo.openai_http import post_openai_with_retries  # type: ignore
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  payload = {"model": PERSONA_MODEL, "temperature": 0, "messages": [
    {"role": "system", "content": brief},
    {"role": "user", "content": app_message}]}
  r = post_openai_with_retries(
    url="https://api.openai.com/v1/chat/completions",
    headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"},
    payload=payload, timeout_seconds=60, retryable_status=(429, 500, 502, 503, 504), max_attempts=3)
  return str(r.json()["choices"][0]["message"]["content"]).strip()


# ---------------------------------------------------------------------------
# The stored draft
# ---------------------------------------------------------------------------
def _j(v):
  try:
    return json.loads(v) if v else {}
  except Exception:
    return {}


def snapshot(conn, draft_id: str) -> dict:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      "SELECT status, active_focus, financials_confirmed, operating_model_json, target_market_json, "
      "people_json, financials_json FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))
    r = cur.fetchone() or {}
  finally:
    cur.close()
  return {"status": r.get("status"), "focus": r.get("active_focus"),
          "financials_confirmed": bool(r.get("financials_confirmed")),
          "ops": _j(r.get("operating_model_json")), "market": _j(r.get("target_market_json")),
          "people": _j(r.get("people_json")), "fin": _j(r.get("financials_json"))}


class Record:
  def __init__(self, business=None, facts=None):
    self.turns = []
    self.business = dict(business or {})   # the form's bootstrap facts, for U1's fill
    self.facts = facts                     # the persona's stated figures, for the checks
    self.submit = None                     # {"status", "body", "payload"} once the persona pressed Submit

  def turn_of(self, rule_id):
    return next((t for t in self.turns if t["rule"] == rule_id), None)

  @property
  def final(self):
    return self.turns[-1]["snap"] if self.turns else {}

  @property
  def completed(self):
    return bool(self.turns) and bool(self.turns[-1]["done"])


def load_transcript(path):
  """(persona, client_id, [(rule, message), ...]) from a gate transcript -
  the exact client messages of a past run, in order. Replayed under the
  same client_id, every GPT call it made answers from the store, so a
  conversation the gate once saw is reproduced turn for turn (2026-09-11:
  the monthly_wage run that hit issue 577's fallthrough)."""
  with open(path, encoding="utf-8") as fh:
    lines = fh.read().splitlines()
  m = re.match(r"INTAKE PERSONA (\S+) .* client=(\S+)", lines[0] if lines else "")
  if not m:
    raise SystemExit("not a gate transcript: %s" % path)
  msgs = []
  for line in lines[1:]:
    mm = re.match(r"^\s+USER \[([^\]]+)\]: (.*)$", line)
    if mm:
      msgs.append((mm.group(1), mm.group(2)))
  return m.group(1), m.group(2), msgs


def _sweep(conn, draft_id):
  spec = importlib.util.spec_from_file_location(
    "replay_post_intake_for_sweep", os.path.join(ROOT, "scripts", "replay_post_intake.py"))
  rp = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(rp)
  return rp.sweep(conn, [draft_id])


# ---------------------------------------------------------------------------
# One persona, in this process
# ---------------------------------------------------------------------------
def run_persona(name: str, mode: str, keep: bool, author: bool = False, transcript: str = "") -> dict:
  import intake_personas as PS
  persona = PS.PERSONAS[name]
  os.makedirs(OUT_DIR, exist_ok=True)
  stamp = time.strftime("%Y%m%d_%H%M%S")
  tx_path = os.path.join(OUT_DIR, "%s__%s.txt" % (name, stamp))
  result = {"persona": name, "about": persona.get("about"), "mode": mode, "verdict": None,
            "detail": "", "turns": 0, "wall_seconds": 0.0, "transcript": tx_path, "checks": []}
  rec = Record(persona.get("bootstrap"), persona.get("facts"))
  improvised = []
  conn = draft_id = None
  tx = open(tx_path, "w", encoding="utf-8")

  def log(s=""):
    tx.write(s + "\n")
    tx.flush()

  t_start = time.monotonic()
  run_status = None
  try:
    import api  # noqa: E402
    app = api.create_app()
    # AFTER create_app: it reloads .env with override=True
    if mode == "strict":
      os.environ["GPT_RESPONSE_LOCK_STRICT"] = "1"
      os.environ["GPT_RESPONSE_LOCK_MISS_DIR"] = os.path.join(OUT_DIR, "%s__%s_misses" % (name, stamp))
    elif mode == "fresh":
      os.environ["GPT_RESPONSE_LOCK"] = "0"
    # PIN "TODAY" TO THE RECORDING DATE (2026-09-11): the handler computes
    # current_date in UTC and puts it in every consult context, and bare dates
    # stay in the lock key on purpose. After 20:00 local this machine is
    # already tomorrow in UTC, so an evening run missed every stored turn,
    # spent ~$8 live and stopped UNSCRIPTED on a question the fresh model
    # improvised. Set AFTER create_app for the same reason as the lock env.
    os.environ["INTAKE_CURRENT_DATE"] = str(getattr(PS, "RECORDED_ON", "") or "")
    # THE INTAKE WATCHER runs on every persisted turn; inside the gate it
    # runs INLINE so its GPT read is recorded and replayed within the turn
    # (a background thread would race the persona and leak live calls).
    os.environ["INTAKE_WATCHER_SYNC"] = "1"
    # THE PERSONA SUBMITS (Nick 2026-09-12: Sablecreek and the field-name 500
    # both passed everything upstream and died AT submit). The submit is the
    # real endpoint; only the system-run trigger is suppressed (it would fire
    # the live :5050 for a scratch draft).
    os.environ["INTAKE_SUBMIT_NO_RUN"] = "1"
    # and as a CLIENT does it: the browser sends client_today with every
    # message, so the gate sends RECORDED_ON the same way (resolve order:
    # request first, then the env seam above, then the state's zone).
    meter = GptMeter(dump_dir=(os.path.join(OUT_DIR, "%s__%s_requests" % (name, stamp))
                               if os.getenv("INTAKE_GATE_DUMP_REQUESTS") == "1" else None))
    meter.install()
    client = app.test_client()

    from intake_submission import get_mysql_connection  # type: ignore
    from client_intake_and_finmo.intake_consult_draft import create_draft  # type: ignore
    conn = get_mysql_connection()
    conn.autocommit = True
    # ONE client_id per persona, never per run: the consultant's request
    # carries the client_id in its intake context, and the lock normalizes
    # only 32-hex ids - a fresh id per run made every request new and
    # nothing ever replayed (measured 2026-09-11: two runs' first requests
    # differed in the client_id alone).
    client_id = (SCRATCH_PREFIX + "in" + hashlib.sha256(name.encode("utf-8")).hexdigest())[:20]
    script = None
    if transcript:
      _t_persona, client_id, script = load_transcript(transcript)
      log("TRANSCRIPT %s: %d client messages, client_id %s" % (transcript, len(script), client_id))
    script_i = 0
    # client_id is UNIQUE on intake_consult_drafts: one draft per persona at a
    # time. A recent one is a run in progress - refuse. An old one is a
    # leftover (--keep, or a killed run) - it carries our prefix, sweep it.
    cur = conn.cursor()
    cur.execute("SELECT draft_id, updated_at > NOW() - INTERVAL 15 MINUTE FROM intake_consult_drafts "
                "WHERE client_id=%s", (client_id,))
    prior = cur.fetchone()
    cur.close()
    if prior and prior[1]:
      raise RuntimeError("persona %s is already running (draft %s touched in the last 15 minutes) - "
                         "one run per persona at a time" % (name, prior[0]))
    if prior:
      log("swept a leftover scratch draft %s (%d rows)" % (prior[0], _sweep(conn, prior[0])))
    draft_id = create_draft(conn, client_id=client_id)["draft_id"]
    result["draft_id"] = draft_id
    log("INTAKE PERSONA %s (%s) mode=%s draft=%s client=%s" % (name, persona.get("about"), mode, draft_id, client_id))

    rules = [dict(r, used=0) for r in persona["rules"]]
    seen = Counter()

    def post(message, rule_id, extra=None):
      # client_today as the browser sends it: the recording date, so every
      # prompt hashes as it did the day the persona was recorded
      payload = {"draft_id": draft_id, "client_id": client_id, "message": message,
                 "client_today": str(getattr(PS, "RECORDED_ON", "") or "")}
      payload.update(extra or {})
      t0 = time.monotonic()
      misses_before = len(meter.strict_misses())
      r = client.post("/api/intake-consult", json=payload)
      ms = int((time.monotonic() - t0) * 1000)
      body = r.get_json(silent=True) or {}
      snap = snapshot(conn, draft_id)
      turn = {"i": len(rec.turns), "rule": rule_id, "sent": message, "status": r.status_code,
              "reply": str(body.get("assistant_message") or ""), "focus": str(body.get("active_focus") or ""),
              "done": bool(body.get("done")) or str(body.get("active_focus") or "") == "done",
              "ms": ms, "snap": snap}
      rec.turns.append(turn)
      if message or rule_id != "seed":
        log("      USER [%s]: %s" % (rule_id, message))
      log("[%3d] APP (%s, %dms): %s" % (turn["i"], turn["focus"], ms, turn["reply"].replace("\n", " | ")))
      log("      stored: " + PS.describe_state(snap, persona.get("facts")))
      # a strict miss first: the handler turns it into an HTTP 500, and that
      # must read GPT_MISS, not ERROR (2026-09-11 strict run, baseline turn 50)
      new_misses = meter.strict_misses()[misses_before:]
      if new_misses or (r.status_code >= 400 and "gpt_lock_miss_strict_replay" in r.get_data(as_text=True)):
        raise LookupError((new_misses or [r.get_data(as_text=True)[:600]])[0])
      if r.status_code >= 400:
        raise RuntimeError("HTTP %d on turn %d: %s" % (r.status_code, turn["i"], r.get_data(as_text=True)[:600]))
      return turn

    seed = dict(persona["bootstrap"])
    turn = post("", "seed", extra=seed)
    while True:
      if turn["done"]:
        break
      seen[turn["reply"]] += 1
      if seen[turn["reply"]] >= LOOP_REPEATS:
        run_status, result["detail"] = "LOOP", "the app sent the same message %d times: %r" % (
          LOOP_REPEATS, turn["reply"][:300])
        break
      if len(rec.turns) >= MAX_TURNS:
        run_status, result["detail"] = "LOOP", "no completion after %d turns" % MAX_TURNS
        break
      if script is not None:
        if script_i >= len(script):
          run_status, result["detail"] = "TRANSCRIPT_END", "every recorded client message sent (%d)" % len(script)
          break
        _rid, _msg = script[script_i]
        script_i += 1
        turn = post(_msg, _rid)
        continue
      rule = pick_rule(rules, turn["reply"], turn["focus"])
      if rule is None and author:
        said = improvise(persona.get("brief") or PS.BRIEF, turn["reply"])
        improvised.append({"turn": turn["i"], "focus": turn["focus"],
                           "asked": question_part(turn["reply"]), "said": said})
        turn = post(said, "IMPROVISED")
        continue
      if rule is None:
        run_status, result["detail"] = "UNSCRIPTED", "no rule answers (%s): %r" % (turn["focus"], turn["reply"][:600])
        break
      rule["used"] += 1
      turn = post(rule["say"], rule["id"])
    # SUBMIT: the turn the old gate stopped short of
    if rec.completed and persona.get("submit") and script is None:
      _sp = dict(persona["submit"])
      _bs = persona.get("bootstrap") or {}
      _payload = {
        "draft_id": draft_id,
        "business_name": _bs.get("business_name"),
        "address": _bs.get("address"),
        "business_start_date": _bs.get("business_start_date"),
        "product_keywords": _sp.get("product_keywords"),
        "first_name": _sp.get("first_name"), "last_name": _sp.get("last_name"),
        "email_address": _sp.get("email_address"), "phone_number": _sp.get("phone_number"),
        "how_did_you_hear": _sp.get("how_did_you_hear"),
      }
      _t0 = time.monotonic()
      _r = client.post("/api/financials", json=_payload)
      _body = _r.get_json(silent=True) or {}
      rec.submit = {"status": _r.status_code, "body": _body, "payload": _payload,
                    "ms": int((time.monotonic() - _t0) * 1000)}
      log("      SUBMIT -> HTTP %d in %dms: %s" % (_r.status_code, rec.submit["ms"], json.dumps(_body, default=str)[:600]))
  except LookupError as exc:
    run_status, result["detail"] = "GPT_MISS", str(exc)[:600]
  except Exception as exc:  # noqa: BLE001
    import traceback
    run_status, result["detail"] = "ERROR", "%s: %s" % (type(exc).__name__, str(exc)[:600])
    log(traceback.format_exc())
  finally:
    result["wall_seconds"] = round(time.monotonic() - t_start, 1)
    result["turns"] = max(0, len(rec.turns) - 1)
    try:
      result["gpt"] = meter.summary()  # type: ignore[name-defined]
    except Exception:
      result["gpt"] = {}

  # checks - over whatever was reached
  checks = []
  # THE GUARD'S RECORD, EVERY TURN (Nick 2026-09-12: "A table from a fresh
  # persona run: every turn, which stage, whether the guard ran, and what it
  # saw. If financials has forty turns, I want forty rows.")
  result["guard"] = []
  rec.guard_rows = []
  if conn is not None and draft_id:
    try:
      cur = conn.cursor()
      cur.execute("SELECT turn, door, action, field, from_value, to_value, why, elapsed_ms FROM intake_guard_actions "
                  "WHERE draft_id=%s ORDER BY turn, id", (draft_id,))
      for turn_i, door, action, field, fv, tv, why, ms in cur.fetchall():
        result["guard"].append({"turn": turn_i, "door": door, "action": action, "field": field,
                                "from": str(fv or "")[:4000], "to": str(tv or "")[:600], "why": str(why or ""), "ms": ms})
      cur.close()
    except Exception as exc:  # noqa: BLE001
      result["guard_error"] = "%s: %s" % (type(exc).__name__, exc)
    rec.guard_rows = list(result["guard"])
    log("GUARD %d row(s)%s" % (len(result["guard"]), (" - " + result["guard_error"]) if result.get("guard_error") else ""))
    log("  turn  stage        door action        model            what it saw")
    for gr in result["guard"]:
      if gr["action"] == "turn_review":
        try:
          seen = json.loads(gr["from"] or "[]")
          if isinstance(seen, str):
            seen = json.loads(seen)
          if not isinstance(seen, list):
            seen = []
        except Exception:
          seen = []
        what = "; ".join("%s %s->%s [%s/%s]" % (c.get("path"), c.get("from"), c.get("to"), c.get("origin") or "none", c.get("verdict")) for c in seen[:6])
        if len(seen) > 6:
          what += "; ... %d more" % (len(seen) - 6)
        log("  %4s  %-12s %-4s %-13s %-16s %s" % (gr["turn"], str(gr["field"] or "").replace("stage:", ""), gr["door"],
                                                  gr["action"], gr["why"][:16], what[:240] or "no change"))
      else:
        log("  %4s  %-12s %-4s %-13s %-16s %s" % (gr["turn"], "", gr["door"], gr["action"], "", ("%s %s" % (gr["field"] or "", gr["why"]))[:240]))

  for cid, desc, fn in persona["checks"]:
    try:
      ok, detail = fn(rec) if rec.turns else (None, "no turns")
    except Exception as exc:  # noqa: BLE001
      ok, detail = False, "check crashed: %s: %s" % (type(exc).__name__, exc)
    if ok is None and rec.completed:
      ok, detail = False, "never reached on a completed intake: " + detail
    checks.append({"case": cid, "check": desc, "ok": ok, "detail": detail})
  result["checks"] = checks
  red = any(c["ok"] is False for c in checks)
  result["improvised"] = improvised
  if run_status in ("ERROR", "GPT_MISS"):
    result["verdict"] = run_status
  elif improvised:
    result["verdict"] = "AUTHOR"  # never a pass: the script does not cover the conversation yet
  elif red:
    result["verdict"] = "FAIL"
  elif run_status:
    result["verdict"] = run_status
  else:
    result["verdict"] = "PASS" if all(c["ok"] is True for c in checks) else "FAIL"
  result["completed"] = rec.completed

  log()
  log("VERDICT %s %s" % (result["verdict"], result["detail"]))
  for c in checks:
    log("  [%s] %s %s: %s" % ({True: " ok ", False: "FAIL", None: " -- "}[c["ok"]], c["case"], c["check"], c["detail"]))
  log("GPT %s" % json.dumps(result.get("gpt")))

  # THE WATCHER'S FILINGS, BEFORE THE SWEEP TAKES THEM (Nick 2026-09-12: "I
  # built that thing so I'd stop finding these one at a time" - it caught
  # the van lease landing on rent in run 1 and nobody read it, because the
  # sweep deletes the table). Every filing goes into the transcript and the
  # summary; a run is never silent about what the watcher saw.
  result["watch"] = []
  if conn is not None and draft_id:
    try:
      cur = conn.cursor()
      cur.execute("SELECT turn, kind, severity, detector, field, why FROM intake_watch_observations "
                  "WHERE draft_id=%s ORDER BY turn, id", (draft_id,))
      for turn_i, kind, sev, det, field, why in cur.fetchall():
        result["watch"].append({"turn": turn_i, "kind": kind, "severity": sev, "detector": det,
                                "field": field, "why": str(why or "")})
      cur.close()
    except Exception as exc:  # noqa: BLE001
      result["watch_error"] = "%s: %s" % (type(exc).__name__, exc)
    log("WATCHER %d filing(s)%s" % (len(result["watch"]), (" - " + result["watch_error"]) if result.get("watch_error") else ""))
    for w in result["watch"]:
      log("  turn %3s [%s/%s] %-28s %s - %s" % (w["turn"], w["severity"], w["detector"], w["kind"], w["field"] or "", w["why"][:220]))

  if conn is not None and draft_id and not keep:
    try:
      # the submissions row the persona's submit created is keyed by its own id
      _sid = ((rec.submit or {}).get("body") or {}).get("intake_submission_id") if rec.submit else None
      if _sid is not None:
        try:
          _c = conn.cursor(); _c.execute("DELETE FROM intake_submissions WHERE id=%s", (int(_sid),)); _c.close()
        except Exception as _exc:  # noqa: BLE001
          result["sweep_error"] = "intake_submissions %s: %s" % (_sid, _exc)
      result["swept_rows"] = _sweep(conn, draft_id)
    except Exception as exc:  # noqa: BLE001
      result["sweep_error"] = "%s: %s" % (type(exc).__name__, exc)
  tx.close()
  return result


# ---------------------------------------------------------------------------
# Orchestration: one worker process per persona, in parallel
# ---------------------------------------------------------------------------
def _fmt_s(s):
  s = float(s or 0)
  return "%dm%02ds" % (int(s // 60), int(s % 60)) if s >= 60 else "%.1fs" % s


def print_result(r):
  g = r.get("gpt") or {}
  print("  %-10s %-13s %3d turns  %7s   GPT %d calls (%d live %s, %d replayed)  tokens in %s out %s" % (
    r["verdict"], r["persona"], r.get("turns", 0), _fmt_s(r.get("wall_seconds")),
    g.get("calls", 0), g.get("live", 0), _fmt_s(g.get("live_seconds")), g.get("replayed", 0),
    "{:,}".format(g.get("tokens_in", 0)), "{:,}".format(g.get("tokens_out", 0))))
  if r.get("detail"):
    print("             %s" % r["detail"])
  _guard_rows = [g for g in (r.get("guard") or []) if g.get("action") == "turn_review"]
  if _guard_rows:
    print("     GUARD %d turn(s) reviewed: %d model, %d no-model, %d unguarded; %d refused, %d rewrote, %d asked" % (
      len(_guard_rows), sum(1 for g in _guard_rows if str(g.get("why") or "").startswith("ran_model")),
      sum(1 for g in _guard_rows if str(g.get("why") or "").startswith("no_model")),
      sum(1 for g in _guard_rows if str(g.get("why") or "").startswith("unguarded")),
      sum(1 for g in (r.get("guard") or []) if g.get("action") == "refused_write"),
      sum(1 for g in (r.get("guard") or []) if g.get("action") == "rewrote_write"),
      sum(1 for g in (r.get("guard") or []) if g.get("action") == "asked")))
    print("     per-turn table: " + str(r.get("transcript") or ""))
  for c in r.get("checks") or []:
    print("     [%s] %s %s: %s" % ({True: " ok ", False: "FAIL", None: " -- "}[c["ok"]], c["case"], c["check"], c["detail"]))
  for x in r.get("improvised") or []:
    print("     IMPROVISED turn %s (%s)\n        Q: %s\n        A: %s" % (
      x["turn"], x["focus"], x["asked"].replace("\n", " | ")[:400], x["said"]))
  w = r.get("watch") or []
  from collections import Counter as _C
  print("     WATCHER %d filing(s)%s" % (len(w), (": " + ", ".join("%s x%d" % kv for kv in _C(x["kind"] for x in w).most_common())) if w else ""))
  for x in w:
    if str(x.get("severity") or "") in ("high", "critical", "error"):
      print("        turn %s %s %s - %s" % (x["turn"], x["kind"], x.get("field") or "", x["why"][:160]))
  print("     transcript: %s" % r.get("transcript"))


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  ap.add_argument("--persona", action="append", help="run only these (repeatable)")
  ap.add_argument("--strict", action="store_true", help="replay only - a store miss is GPT_MISS")
  ap.add_argument("--fresh", action="store_true", help="lock off - every call live, nothing recorded")
  ap.add_argument("--keep", action="store_true", help="leave the scratch drafts")
  ap.add_argument("--transcript",
                  help="replay a past gate transcript's client messages verbatim, under its client_id")
  ap.add_argument("--dump-requests", action="store_true",
                  help="write every GPT request, as the lock keys it, next to the transcript")
  ap.add_argument("--author", action="store_true",
                  help="answer unscripted questions from the persona brief and list them - never a pass")
  ap.add_argument("--worker", help=argparse.SUPPRESS)
  ap.add_argument("--mode", default="default", choices=MODES, help=argparse.SUPPRESS)
  ap.add_argument("--out", help=argparse.SUPPRESS)
  args = ap.parse_args(argv)

  if args.worker:
    res = run_persona(args.worker, args.mode, args.keep, args.author, args.transcript or "")
    with open(args.out, "w", encoding="utf-8") as fh:
      json.dump(res, fh, indent=1, default=str)
    return 0

  if args.strict and args.fresh:
    print("--strict and --fresh contradict each other", file=sys.stderr)
    return 2
  mode = "strict" if args.strict else ("fresh" if args.fresh else "default")
  if args.dump_requests:
    os.environ["INTAKE_GATE_DUMP_REQUESTS"] = "1"  # inherited by the workers
  import intake_personas as PS
  names = args.persona or list(PS.PERSONAS)
  if args.transcript:
    names = [load_transcript(args.transcript)[0]]
  unknown = [n for n in names if n not in PS.PERSONAS]
  if unknown:
    print("unknown persona(s): %s - have %s" % (unknown, list(PS.PERSONAS)), file=sys.stderr)
    return 2
  build = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short=8", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
  dirty = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--", "python/"],
                         capture_output=True, text=True).stdout.strip()
  print("INTAKE PERSONA GATE  build %s%s  mode %s  personas %d" % (
    build, " (+uncommitted python/ changes)" if dirty else "", mode, len(names)))
  os.makedirs(OUT_DIR, exist_ok=True)
  t0 = time.monotonic()

  def launch(name):
    out = os.path.join(OUT_DIR, "_%s_%s.json" % (name, uuid.uuid4().hex[:8]))
    cmd = [sys.executable, "-X", "utf8", os.path.abspath(__file__), "--worker", name, "--mode", mode, "--out", out]
    if args.keep:
      cmd.append("--keep")
    if args.author:
      cmd.append("--author")
    if args.transcript:
      cmd += ["--transcript", os.path.abspath(args.transcript)]
    log = os.path.join(OUT_DIR, "_%s_worker.log" % name)
    with open(log, "w", encoding="utf-8") as fh:
      p = subprocess.run(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
    try:
      with open(out, encoding="utf-8") as fh:
        res = json.load(fh)
      os.remove(out)
      return res
    except Exception:
      return {"persona": name, "verdict": "ERROR", "detail": "worker exited %d without a result - see %s" % (p.returncode, log),
              "checks": [], "transcript": log}

  with ThreadPoolExecutor(max_workers=len(names)) as ex:
    results = list(ex.map(launch, names))
  for r in results:
    print_result(r)
  bad = [r["persona"] for r in results if r["verdict"] != "PASS"]
  verdict = "SAFE TO RUN A LIVE INTAKE" if not bad else "NOT SAFE - %s" % ", ".join(
    "%s %s" % (r["persona"], r["verdict"]) for r in results if r["verdict"] != "PASS")
  print("INTAKE GATE: %s in %s" % (verdict, _fmt_s(time.monotonic() - t0)))
  with open(REPORT_PATH, "w", encoding="utf-8") as fh:
    json.dump({"build": build, "dirty": bool(dirty), "mode": mode, "verdict": verdict,
               "at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}, fh, indent=1, default=str)
  return 0 if not bad else 1


if __name__ == "__main__":
  raise SystemExit(main())
