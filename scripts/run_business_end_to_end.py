"""RUN A BUSINESS END TO END - a real client, the live backend, one plan.

Nick 2026-09-25: "Then run a business end to end and show me the plan."

Not the persona gate (recorded, in-process, stops at intake-complete) and not
a replay. This is a client talking to http://127.0.0.1:5050 over HTTP exactly
as the form does: POST /api/intake-consult/session for a draft, then one POST
/api/intake-consult per turn, with a GPT owner answering from a brief. When
the intake completes it kicks /api/intake-consult/system-run and watches the
status until the model is built and the writing phase has shipped the plan.

The brief deliberately speaks magnitudes THE WAY PEOPLE SPEAK THEM - "about
three point eight million", "four dollars twenty" - because that is the shape
ruling (a) restored, and a run that only ever types 3,800,000 would not touch
it.

  python scripts/run_business_end_to_end.py
  python scripts/run_business_end_to_end.py --max-turns 120
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "python"))
sys.path.append(os.path.join(_REPO, "python", "client_intake_and_finmo"))

# The owner's own GPT calls go through the SAME response lock the app uses, so
# they need the same database. api.py loads the root .env; a script does not,
# and without it MySQL falls back to a named pipe and the lock refuses to run
# unlocked (first attempt at this died on turn 1 that way).
try:
  from dotenv import load_dotenv  # type: ignore
  load_dotenv(os.path.join(_REPO, ".env"), override=True)
except Exception as _exc:  # pragma: no cover - a missing dotenv is loud below
  print("WARNING: could not load .env (%s)" % _exc, flush=True)

BASE = os.getenv("BPLAN_API_BASE", "http://127.0.0.1:5050")
OWNER_MODEL = "gpt-4.1-mini"

# The identity the Submit step carries - the same fields the form collects.
BUSINESS_NAME = "Keir & Halloway Fabrication"
BUSINESS_ADDRESS = "1420 Indiana Avenue, Sheboygan, Wisconsin 53081"
BUSINESS_START_DATE = "2016-04-01"
PRODUCT_KEYWORDS = "structural steel fabrication, sheet metal, ducting, repair"
OWNER_FIRST, OWNER_LAST = "Rosalind", "Keir"
OWNER_EMAIL = "rosalind@keirhalloway.example"
OWNER_PHONE = "920-555-0147"

BRIEF = """You are Rosalind Keir, sole owner of Keir & Halloway Fabrication, a
metal fabrication shop in Sheboygan, Wisconsin, trading since April 2016, an
S-corp. You are being interviewed by a business consultant. Answer HIS
QUESTION AND ONLY HIS QUESTION, in one to three short sentences, the way a
busy owner talks. Never volunteer a figure he did not ask for. Never invent a
dollar figure that is not below - if he asks something outside these facts,
answer plausibly in words and give no new number.

SPEAK NUMBERS OUT LOUD, not as digits. Say "about three point eight million",
"four dollars twenty", "twelve hundred a week". Only spell a number in digits
if he has already asked the same question twice.

THE WORK - three contract lines, quoted and invoiced separately:
  1. Structural steel fabrication. About two thousand four hundred dollars a
     tonne. You can put through about forty tonnes a week when the shop is
     flat out, and you run about seventy percent of that.
  2. Sheet metal and ducting. About eight hundred and fifty dollars a unit.
     About sixty units a week flat out, running about sixty-five percent.
  3. Repair and maintenance callouts, billed by the job. About one thousand
     one hundred dollars a job. About twenty-five jobs a week flat out,
     running about eighty percent.
Open year round, weekly cadence, forty-eight working weeks.

MONEY: revenue about three point eight million a year. Materials run about
forty-two percent of revenue. Marketing about sixty thousand a year. Rent on
the shop is eighteen thousand a month. Other regular bills about nine
thousand a month.

PEOPLE - eleven in total: you (general manager, about a hundred and forty
thousand a year), Dev Ramanathan (shop foreman, about ninety-five thousand),
and nine fabricators and fitters whose pay comes to about six hundred and
twenty thousand a year between them.

BALANCE SHEET: plant and equipment worth about one point six million; nothing
on a lease; you have put in about four hundred thousand of your own; about two
hundred and ten thousand in the bank; customers pay on thirty day terms; about
three hundred and forty thousand of supplier invoices outstanding; about two
hundred and eighty thousand of steel and stock on hand.

DEBT: you owe about one point four five million on a term loan and you pay
about a hundred and thirty thousand a year in interest on it. You would rather
borrow than give up equity, and you keep a conservative cash cushion.

GROWTH: you want to add a second shift on the structural line over the next
two years. No other plans."""


def _req(path, payload=None, method=None, timeout=900):
  url = BASE + path
  data = None
  headers = {"Accept": "application/json"}
  if payload is not None:
    data = json.dumps(payload).encode("utf-8")
    headers["Content-Type"] = "application/json"
  r = urllib.request.Request(url, data=data, headers=headers,
                             method=method or ("POST" if data else "GET"))
  try:
    with urllib.request.urlopen(r, timeout=timeout) as resp:
      body = resp.read().decode("utf-8", "replace")
      return resp.status, (json.loads(body) if body.strip() else {})
  except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", "replace")
    try:
      return e.code, json.loads(body)
    except Exception:
      return e.code, {"_raw": body[:2000]}


def owner_says(history, app_message):
  """The owner answers from the brief, with the conversation so far."""
  from client_intake_and_finmo.openai_http import post_openai_with_retries

  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  msgs = [{"role": "system", "content": BRIEF}]
  for consultant, owner in history[-8:]:
    msgs.append({"role": "user", "content": consultant})
    msgs.append({"role": "assistant", "content": owner})
  msgs.append({"role": "user", "content": app_message})
  r = post_openai_with_retries(
      url="https://api.openai.com/v1/chat/completions",
      headers={"Authorization": "Bearer %s" % key,
               "Content-Type": "application/json"},
      payload={"model": OWNER_MODEL, "temperature": 0.2, "messages": msgs},
      timeout_seconds=90, retryable_status=(429, 500, 502, 503, 504),
      max_attempts=3)
  return str(r.json()["choices"][0]["message"]["content"]).strip()


def log(s):
  # The app writes real typography (non-breaking hyphens, curly quotes) and a
  # Windows console is cp1252, so an unguarded print KILLS THE RUN mid-intake -
  # it did, at turn 10, on a single U+2011. The transcript is evidence; it is
  # never worth losing a run to.
  line = "%s  %s" % (dt.datetime.now().strftime("%H:%M:%S"), s)
  try:
    print(line, flush=True)
  except UnicodeEncodeError:
    enc = (getattr(sys.stdout, "encoding", None) or "ascii")
    print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--max-turns", type=int, default=140)
  ap.add_argument("--run-timeout", type=int, default=5400)
  ap.add_argument("--draft", default="", help="resume this draft instead of "
                                              "starting a new one")
  ap.add_argument("--client", default="", help="the draft's client_id")
  args = ap.parse_args()

  if args.draft:
    draft_id, client_id = args.draft, args.client
    log("RESUMING DRAFT %s  client %s" % (draft_id, client_id))
  else:
    st, sess = _req("/api/intake-consult/session", {})
    if st != 200 or not sess.get("draft_id"):
      log("SESSION FAILED %s %s" % (st, sess))
      return 2
    draft_id = sess["draft_id"]
    client_id = sess.get("client_id") or ""
    log("DRAFT %s  client %s" % (draft_id, client_id))

  today = dt.date.today().isoformat()
  history = []
  message = ""          # empty replays the app's last question on a resume
  done = False
  for i in range(args.max_turns):
    st, body = _req("/api/intake-consult",
                    {"draft_id": draft_id, "client_id": client_id,
                     "message": message, "client_today": today})
    if st != 200:
      log("TURN %d HTTP %s %s" % (i, st, json.dumps(body)[:600]))
      return 3
    reply = str(body.get("assistant_message") or "")
    focus = str(body.get("active_focus") or "")
    done = bool(body.get("done")) or focus == "done"
    log("t%-3d app[%s]: %s" % (i, focus, reply.replace("\n", " ")[:220]))
    if done:
      log("INTAKE COMPLETE at turn %d" % i)
      break
    if not reply.strip():
      log("EMPTY REPLY - stopping")
      return 4
    message = owner_says(history, reply)
    history.append((reply, message))
    log("t%-3d her     : %s" % (i, message.replace("\n", " ")[:220]))

  if not done:
    log("INTAKE DID NOT COMPLETE in %d turns" % args.max_turns)
    return 5

  # SUBMIT THE WAY A CLIENT DOES (mini 2026-09-25). This script used to POST
  # /api/intake-consult/system-run directly, which made Merrifield look like a
  # dead run and me report that the auto-start had been lost in the revert.
  # It had not: the client presses Submit (SubmitStep.tsx -> POST
  # /api/financials) and financials.py fires _start_system_run_in_background.
  # A harness that skips Submit is testing a path no client takes.
  submit = {
      "draft_id": draft_id,
      "business_name": BUSINESS_NAME,
      "address": BUSINESS_ADDRESS,
      "business_start_date": BUSINESS_START_DATE,
      "product_keywords": PRODUCT_KEYWORDS,
      "first_name": OWNER_FIRST, "last_name": OWNER_LAST,
      "email_address": OWNER_EMAIL, "phone_number": OWNER_PHONE,
      "how_did_you_hear": "referral",
  }
  st, body = _req("/api/financials", submit)
  log("SUBMIT -> %s %s" % (st, json.dumps(body, default=str)[:400]))
  if st < 200 or st >= 300:
    log("SUBMIT REFUSED - the system run never starts without it")
    return 6

  t0 = time.time()
  last = ""
  while time.time() - t0 < args.run_timeout:
    st, s = _req("/api/intake-consult/system-run/status?draft_id=%s" % draft_id)
    line = json.dumps({k: s.get(k) for k in
                       ("status", "phase", "stage", "message", "error",
                        "planning_run_id", "done", "writing_phase")
                       if s.get(k) is not None})
    if line != last:
      log("RUN %s" % line[:500])
      last = line
    if str(s.get("status") or "").lower() in ("complete", "completed", "done",
                                              "failed", "error"):
      break
    time.sleep(15)

  log("DRAFT %s - read the store for the plan" % draft_id)
  print("DRAFT_ID=%s" % draft_id)
  return 0


if __name__ == "__main__":
  sys.exit(main())
