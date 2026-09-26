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

# ONE SCRIPT, ANY BUSINESS (2026-09-26). Nick's step 4 is "one fresh business
# end to end", and Cowork's standing rule is a different business every run -
# with the identity and the brief inlined, a fresh business meant editing the
# harness, which is how two runs end up sharing a shape by accident. Pick one
# with --business; the keys are the dict below.
BUSINESSES = {}


def _business(key, **fields):
  BUSINESSES[str(key)] = fields


_business(
  "keir",
  business_name="Keir & Halloway Fabrication",
  address_street="1420 Indiana Avenue",
  address_city="Sheboygan",
  address_state="Wisconsin",
  address_zip="53081",
  address_country="United States",
  business_address="1420 Indiana Avenue, Sheboygan, Wisconsin 53081",
  business_start_date="2016-04-01",
  product_keywords="structural steel fabrication, sheet metal, ducting, repair",
  owner_email="rosalind@keirhalloway.example",
  owner_phone="920-555-0147",
  brief="""You are Rosalind Keir, sole owner of Keir & Halloway Fabrication, a
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
two years. No other plans.""",
  owner_first="Rosalind",
  owner_last="Keir",
)

_business(
  "pellingham",
  business_name="Pellingham Grounds Care",
  address_street="318 Sweeten Creek Road",
  address_city="Asheville",
  address_state="North Carolina",
  address_zip="28803",
  address_country="United States",
  business_address="318 Sweeten Creek Road, Asheville, North Carolina 28803",
  business_start_date="2014-03-01",
  product_keywords="commercial landscape maintenance, planting installation, "
                   "irrigation repair",
  owner_first="Delia",
  owner_last="Pellingham",
  owner_email="delia@pellinghamgrounds.example",
  owner_phone="828-555-0132",
  brief="""You are Delia Pellingham, sole owner of Pellingham Grounds Care, a
commercial grounds maintenance and landscape installation company in
Asheville, North Carolina, trading since March 2014, an S-corp. You are being
interviewed by a business consultant. Answer HIS QUESTION AND ONLY HIS
QUESTION, in one to three short sentences, the way a busy owner talks. Never
volunteer a figure he did not ask for. Never invent a dollar figure that is
not below - if he asks something outside these facts, answer plausibly in
words and give no new number.

SPEAK NUMBERS OUT LOUD, not as digits. Say "about two point four million",
"nine hundred and fifty a visit", "eighteen hundred a month". Only spell a
number in digits if he has already asked the same question twice.

THE WORK - three lines, quoted and invoiced separately:
  1. Grounds maintenance contracts, billed monthly per property. About
     nine hundred and fifty dollars a month per property. You can carry
     about a hundred and forty properties at once when the crews are full,
     and you run about eighty-five percent of that.
  2. Planting and hardscape installation, billed by the job. About eleven
     thousand dollars a job. You can have about six installs running at
     once flat out, and each of those slots turns over about nine times a
     year. You run about seventy percent.
  3. Irrigation repair callouts, billed by the visit. About four hundred
     and twenty dollars a visit. About thirty visits a week flat out,
     running about sixty percent.
Thirty-eight working weeks outdoors, though the maintenance contracts bill
all twelve months.

MONEY: revenue about two point four million a year. Materials, plants and
mulch run about twenty-six percent of revenue. Marketing about forty-five
thousand a year. The yard and office lease is eleven thousand a month. Other
regular bills about seven thousand a month.

PEOPLE - fourteen in total: you (general manager, about a hundred and twenty
thousand a year), Marcus Oyelaran (operations manager, about eighty-eight
thousand), and twelve field staff whose pay comes to about five hundred and
forty thousand a year between them. If he asks how you would GROUP the rest
of the team, say you think of them as two crews: eight on maintenance and
four on installation.

BALANCE SHEET: trucks, mowers and equipment worth about eight hundred and
sixty thousand; nothing on a lease; you have put in about two hundred and
twenty thousand of your own; about a hundred and forty thousand in the bank;
commercial clients pay on thirty day terms; about ninety thousand of supplier
invoices outstanding; about sixty thousand of plants and materials on hand.

DEBT: you owe about four hundred and ten thousand on equipment notes and you
pay about thirty-one thousand a year in interest on them. You would rather
borrow than take on a partner, and you keep a conservative cash cushion.

GROWTH: you want to add a third maintenance crew over the next two years. No
other plans."""
)


DEFAULT_BUSINESS = "keir"

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
  ap.add_argument("--business", default=DEFAULT_BUSINESS,
                  choices=sorted(BUSINESSES),
                  help="which business to be (a different one every run)")
  args = ap.parse_args()
  _bz = BUSINESSES[args.business]
  global BUSINESS_NAME, ADDRESS_STREET, ADDRESS_CITY, ADDRESS_STATE
  global ADDRESS_ZIP, ADDRESS_COUNTRY, BUSINESS_ADDRESS, BUSINESS_START_DATE
  global PRODUCT_KEYWORDS, OWNER_FIRST, OWNER_LAST, OWNER_EMAIL, OWNER_PHONE
  global BRIEF
  BUSINESS_NAME = _bz["business_name"]
  ADDRESS_STREET = _bz["address_street"]
  ADDRESS_CITY = _bz["address_city"]
  ADDRESS_STATE = _bz["address_state"]
  ADDRESS_ZIP = _bz["address_zip"]
  ADDRESS_COUNTRY = _bz["address_country"]
  BUSINESS_ADDRESS = _bz["business_address"]
  BUSINESS_START_DATE = _bz["business_start_date"]
  PRODUCT_KEYWORDS = _bz["product_keywords"]
  OWNER_FIRST, OWNER_LAST = _bz["owner_first"], _bz["owner_last"]
  OWNER_EMAIL = _bz["owner_email"]
  OWNER_PHONE = _bz["owner_phone"]
  BRIEF = _bz["brief"]
  log("BUSINESS %s - %s" % (args.business, BUSINESS_NAME))

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
    turn_payload = {"draft_id": draft_id, "client_id": client_id,
                    "message": message, "client_today": today}
    if i == 0 and not args.draft:
      # THE FORM COLLECTS WHO SHE IS BEFORE THE CHAT and sends it on the
      # turn; this script went straight to /session and never did, so the
      # draft carried no business_name. The intake completed, Submit
      # returned 200, and the planning run then died in contract
      # validation on an empty name. A harness that skips the form's own
      # fields is not testing the client's path.
      turn_payload.update({
          "business_name": BUSINESS_NAME,
          "business_start_date": BUSINESS_START_DATE,
          "address_street": ADDRESS_STREET,
          "address_city": ADDRESS_CITY,
          "address_state": ADDRESS_STATE,
          "address_zip": ADDRESS_ZIP,
          "address_country": ADDRESS_COUNTRY,
          "address": BUSINESS_ADDRESS,
      })
    st, body = _req("/api/intake-consult", turn_payload)
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
    # THE RUN'S STATE IS IN planning_run, NOT IN "status" (2026-09-26). The
    # top-level "status" is the endpoint's own "ok" - it never changes, so the
    # watcher below could not see a completed run and polled until its
    # 5400-second timeout on a plan that had shipped nine minutes in.
    run = s.get("planning_run") if isinstance(s.get("planning_run"), dict) else {}
    state = str(run.get("run_status") or s.get("status") or "").lower()
    line = json.dumps({k: v for k, v in (
        ("run_status", run.get("run_status")),
        ("stage", run.get("current_stage")),
        ("stage_status", run.get("current_stage_status")),
        ("cycle", run.get("current_cycle")),
        ("planning_run_id", run.get("planning_run_id")),
        ("failure_reason", run.get("failure_reason")),
        ("endpoint", s.get("error")),
    ) if v is not None})
    if line != last:
      log("RUN %s" % line[:500])
      last = line
    if state in ("complete", "completed", "done", "failed", "error"):
      log("RUN %s after %ds" % (state.upper(), int(time.time() - t0)))
      break
    time.sleep(15)

  log("DRAFT %s - read the store for the plan" % draft_id)
  print("DRAFT_ID=%s" % draft_id)
  return 0


if __name__ == "__main__":
  sys.exit(main())
