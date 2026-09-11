"""Scripted personas for the intake persona gate (scripts/intake_persona_gate.py).

A persona is a business, a FIXED set of answers keyed on what the app asks,
and checks on what ends up stored. Rules are tried in order against the
question part of each app message (the paragraphs holding a "?"; scope="all"
reads the whole message). The first unused matching rule answers. A question
no rule answers stops the run as UNSCRIPTED - the script never improvises.

One business - Larkspur Dog Grooming, two lines, two named wages among seven
staff - so the three conversations share their opening and the response lock
replays the shared part:

  baseline      C1 rest-of-team fires + C3 a figure stays on its line
  stated_total  C2 a stated total that disagrees with the itemised wages:
                the app asks, and the intake does not complete while open
  monthly_wage  C4 a stated annual wage survives a monthly restatement to the cent

Every persona also checks U2: every stated payroll figure stored exactly.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# The business: every figure the persona states, in one place
# ---------------------------------------------------------------------------
OWNER, OWNER_WAGE = "Jess Harlow", 62000.0
DANA, DANA_WAGE = "Dana Okafor", 52000.0
POOL = 150000.0                              # rest-of-team: five groomers and bathers
ON_FILE = OWNER_WAGE + DANA_WAGE + POOL      # 264,000
STATED_TOTAL = 300000.0                      # stated_total persona only
HEADCOUNT = 7

LINE_PAT = {"full": r"full", "bath": r"bath"}
STATED_LINE = {                              # (line, field group) -> what the client said
    ("full", "cap"): 120.0, ("full", "util"): 0.80, ("full", "price"): 85.0,
    ("bath", "cap"): 150.0, ("bath", "util"): 0.70, ("bath", "price"): 40.0,
}
LINE_RULES = {                               # (line, field group) -> the rules that state it
    ("full", "cap"): {"cap_full", "cap_both", "cap_reask", "cap_reask_full"},
    ("full", "util"): {"util_full", "util_both", "util_any"},
    ("full", "price"): {"price_full", "price_both"},
    ("bath", "cap"): {"cap_bath", "cap_both", "cap_reask", "cap_reask_bath"},
    ("bath", "util"): {"util_bath", "util_both", "util_any"},
    ("bath", "price"): {"price_bath", "price_both"},
}
GROUP_FIELD = {"cap": "units_per_week_capacity", "util": "utilization_rate", "price": "unit_price"}

BOOTSTRAP = {
    "business_name": "Larkspur Dog Grooming",
    "business_start_date": "03/15/2019",
    "address": "4120 SE Division St, Portland, OR 97202",
    "address_street": "4120 SE Division St",
    "address_city": "Portland",
    "address_state": "OR",
    "address_zip": "97202",
    "address_country": "USA",
}

REST_OF_TEAM_MARKER = "payroll for the rest of your team"
HOLD_ASK = r"i've recorded \$[\d,.]+ across your named people"


def R(rid, stage, ask, say, times=1, scope="q"):
  return {"id": rid, "stage": stage, "ask": ask, "say": say, "times": times, "scope": scope}


_ANOTHER = (r"add another|another key|another individual|another person|anyone else"
            r"|any other (single |specific )?(key|individual|person)|other key (people|person)"
            r"|specific (key )?individual|only (people|ones) you want|named person|key, ongoing role"
            r"|any other named|all set with people")
_BOTH = (r"(?=.*(together|in total|combined|both (services|lines)|each (service|line|of (them|those|the two))"
         r"|full[- ]grooms? (and|or|plus) bath|bath[- ]and[- ]tid\w* (and|or|plus) full))")

BASE_RULES = [
  # --- operations -------------------------------------------------------
  R("describe", "ops", r"describe in plain language|what .{0,60} does or will do",
    "Larkspur Dog Grooming is a dog grooming salon in Portland, Oregon. Owners drop their "
    "dogs off with us and pick them up groomed. We sell two services: a full groom - bath, "
    "haircut, nails and ears - and a bath-and-tidy, which is a bath, brush-out, nails and a "
    "light trim. Customers pay per visit when they pick up."),
  # not "every week": a utilization question says "fully booked every week"
  # (monthly_wage 2026-09-11, turn 6 - the cadence answer went to it)
  R("cadence", "ops", r"year[- ]round|seasonal|open all year|weekly (cadence|basis)",
    "Yes - we're open year-round, so weekly works."),
  R("customers", "ops", r"individual|consumer|households|businesses|b2b|primarily serve|who (are|is) your|pet owners",
    "Individual dog owners - local households, almost entirely."),
  R("legal", "ops", r"legal (structure|entity|set ?up)|sole propriet|\bllc\b|s-?corp|partnership",
    "It's a single-member LLC - I'm the only owner."),
  R("picture", "ops", r"picturing|day[- ]to[- ]day|lay out how|matches how|how .{0,40} actually runs",
    "Yes, that matches. Dana and I lead the grooming, and the rest of the team does the "
    "baths and the prep."),
  R("split", "ops", r"separate|separately|break (it|them|that) (into|out|up)|different (things|services|lines)|one line|single line|two (lines|services|units)",
    "Yes, track the full groom and the bath-and-tidy separately - they're priced and booked "
    "differently.", times=2),
  # a question about BOTH lines gets both figures (the 2026-09-11 recording run
  # asked utilization for both at once; monthly_wage asked capacity "full
  # grooms plus bath-and-tidies together")
  R("util_both", "ops", _BOTH + r"(?=.*(how full|utiliz|percent|% of|on average|average load))",
    "About 80 percent on full grooms and about 70 percent on bath-and-tidies."),
  R("price_both", "ops", _BOTH + r"(?=.*(price|charge|how much do (you|customers)|pay for))",
    "A full groom averages $85 and a bath-and-tidy $40."),
  R("cap_both", "ops", _BOTH + r"(?=.*(capacity|fully booked|maximum|\bmax\b|how many))",
    "About 120 full grooms and 150 bath-and-tidies a week when we're fully booked - they're separate slots."),
  # a utilization question names the capacity, so utilization and price go first
  # "70%" and "booking level" are utilization too (baseline 2026-09-11 turn 10:
  # "about 70% earlier - does that still sound like the right average booking
  # level" went to the channel rule)
  R("util_full", "ops", r"(?=.*\bfull[- ]?groom)(?=.*(how full|utiliz|percent|% of|\d ?%|booking level|average booking))",
    "About 80 percent of the full-groom slots are booked on average."),
  R("util_bath", "ops", r"(?=.*\bbath)(?=.*(how full|utiliz|percent|% of|\d ?%|booking level|average booking))",
    "About 70 percent of the bath-and-tidy slots are booked on average."),
  # "what does a typical visit average per dog" is a price (baseline 2026-09-11 turn 13)
  R("price_full", "ops", r"(?=.*\bfull[- ]?groom)(?=.*(price|charge|how much do (you|customers)|average ticket|pay for|average per|per dog|visit average))",
    "A full groom averages $85."),
  R("price_bath", "ops", r"(?=.*\bbath)(?=.*(price|charge|how much do (you|customers)|average ticket|pay for|average per|per dog|visit average))",
    "A bath-and-tidy averages $40."),
  R("cap_full", "ops", r"(?=.*\bfull[- ]?groom)(?=.*(capacity|fully booked|maximum|\bmax\b|at most|realistically|how many))",
    "About 120 full grooms a week when we're fully booked."),
  R("cap_bath", "ops", r"(?=.*\bbath)(?=.*(capacity|fully booked|maximum|\bmax\b|at most|realistically|how many))",
    "About 150 bath-and-tidies a week when we're fully booked."),
  # the app asking AGAIN for a capacity it already stored (U4 flags it; the
  # persona restates so the run can go on)
  # Two figures in one answer are refused there - the fallback wants ONE
  # number (baseline 2026-09-11, turns 7-9). A real client escapes one line at
  # a time (Ferriday: "Wellness capacity stays 115 a week"); so does the persona.
  R("cap_reask_full", "ops", r"clear on your capacity|one number you have in mind|confirm your capacity",
    "Full grooms: about 120 a week when we're fully booked."),
  R("cap_reask_bath", "ops", r"clear on your capacity|one number you have in mind|confirm your capacity",
    "Bath-and-tidies: about 150 a week when we're fully booked."),
  R("cap_reask", "ops", r"clear on your capacity|one number you have in mind|confirm your capacity",
    "About 120 full grooms and 150 bath-and-tidies a week - two numbers, one per service."),
  # a utilization question that names neither line (the 2026-09-11 recording run)
  R("util_any", "ops", r"how full|utiliz|percent|% of|\d ?%|booking level|average booking|average load|feel more realistic",
    "About 80 percent on full grooms and about 70 percent on bath-and-tidies."),
  # who does the work (monthly_wage 2026-09-11 turn 13)
  R("fulfillment", "ops", r"done by you|grooming staff|who (does|handles|performs)|same day",
    "Yes - Dana and I and our groomers do every groom on-site, and dogs go home the same day.", times=2),
  R("delivery", "ops", r"in[- ]person|come to you|on[- ]?site|mobile|drop (off|their)|at (your|the) (salon|shop|location)",
    "Everything happens at our salon - owners drop their dogs off and pick them up.", times=2),
  R("stream", "*", r"before we wrap up operations", "No - no boarding, daycare or retail. Just grooms and baths.",
    times=2, scope="all"),
  R("goal", "ops", r"\bgoal\b|next 12 months|12 months",
    "Fill the weekday slots - I'd like full grooms closer to fully booked."),
  R("growth", "ops", r"grow|lever",
    "More customers - we have open weekday slots to fill."),
  R("geography", "ops", r"\barea\b|geograph|come from|service area|neighbo|radius|local",
    "Mostly Portland's east side, within about five miles of the salon."),
  R("channel", "ops", r"online|how do (customers|people|clients) (book|find)|walk[- ]in|storefront|physical|sales channel|find you",
    "Customers book online or by phone, and most come from word of mouth."),
  R("advantage", "ops", r"stand out|different from|advantage|why .{0,40} choose|competitor|sets you apart"
    r"|sets .{0,40}apart|do better|regulars appreciate|best customers say",
    "Fear-free handling - dogs are never crated for hours, and we text owners the moment "
    "their dog is ready."),
  # --- target market ----------------------------------------------------
  R("gender", "market", r"gender|female|male", "All genders, no particular focus."),
  R("age", "market", r"\bage\b|ages|years old", "Mostly adults 25 to 64."),
  R("income", "market", r"income", "Middle income and up - roughly $50,000 to $150,000 a household."),
  R("education", "market", r"education", "No preference - a broad mix."),
  R("dims_skip", "market", r"employment|household structure|housing", "Skip those, thanks - they don't matter for us."),
  R("employment", "market", r"employment", "Mostly working adults, plus some retirees."),
  # --- people -----------------------------------------------------------
  R("key_person_1", "people", r"key (person|people|individual)|pivotal|full name|name.{0,40}(title|role)",
    f"{OWNER}, owner and lead groomer. 14 years grooming. I pay myself $62,000 a year."),
  R("add_another_1", "people", _ANOTHER,
    f"Yes - {DANA}, head groomer, 9 years grooming. She earns $52,000 a year."),
  R("add_another_2", "people", _ANOTHER, "No, just the two of us by name."),
  R("narrative", "people", r"review this draft|narrative|any changes", "That reads well, no changes.", times=2),
  R("rest_of_team", "*", re.escape(REST_OF_TEAM_MARKER),
    "The rest of the team - five groomers and bathers - comes to about $150,000 a year.",
    times=2, scope="all"),
  # --- financials -------------------------------------------------------
  R("revenue", "financials", r"revenue|bringing in", "About $640,000 a year."),
  # inventory BEFORE cogs: "products or supplies kept in stock" matched the
  # cogs rule's "supplies" (stated_total 2026-09-11 turn 45)
  R("inventory", "financials", r"inventory|kept in stock", "About $4,000 of shampoo and supplies.", times=2),
  R("cogs", "financials", r"direct costs|materials|supplies|cost of (goods|sales)",
    "Shampoo, conditioner and supplies run about 5 percent of revenue.", times=2),
  # other bills BEFORE marketing: that question says "besides payroll,
  # marketing, and rent" (stated_total 2026-09-11 turn 36 sent the marketing answer)
  R("other_opex", "financials",
    r"other regular business bills|other (regular )?(monthly )?(operating|business) (expenses|bills)|ongoing bills",
    "About $1,500 a month - utilities, software, insurance and the accountant.", times=2),
  R("marketing", "financials", r"for marketing|marketing (budget|spend)|on marketing|spend on marketing",
    "About $12,000 a year on marketing.", times=2),
  R("rent_future", "financials", r"stay part of how|expect paid dedicated|keep (renting|the space)",
    "Yes, we'll keep the salon."),
  R("rent", "financials", r"pay each month for the space|\brent\b", "$4,500 a month for the salon."),
  R("headcount", "financials", r"how many people are on payroll|people on payroll|employee count|headcount",
    "Seven of us, including me.", times=2),
  R("lease", "financials", r"lease or finance|under a lease|finance agreement",
    "No, nothing on a lease or finance agreement - zero owed.", times=2),
  R("capex", "financials", r"one-time purchases|capital spending|larger .{0,30}purchases",
    "Nothing recent - zero.", times=2),
  R("assets", "financials", r"worth, all together|equipment, devices, furniture|currently in the business",
    "About $85,000 - tubs, tables, dryers and the build-out.", times=2),
  R("equity", "financials", r"money or value has gone into|invested|investors",
    "About $120,000, all from me.", times=2),
  R("debt", "financials", r"owe in total on loans|loans, lines of credit|total debt",
    "Nothing - we have no loans or credit lines.", times=2),
  R("debt_detail", "financials", r"debt payments|interest|principal", "None - we have no debt.", times=3),
  R("cash", "financials", r"cash .{0,30}on hand|in the bank|bank accounts", "About $60,000 in the bank.", times=2),
  R("ap", "financials", r"regular operating bills|supplier invoices|accounts payable",
    "About $3,000 in supplier invoices.", times=2),
  R("ar", "financials", r"customers currently owe|unpaid invoices|payment plans|accounts receivable",
    "Nothing - customers pay at pickup.", times=2),
  R("cash_posture", "financials", r"extra cash|cash posture", "Balanced - keep a cushion and pay myself a bit more."),
  R("funding", "financials", r"outside capital|prefer to fund|how would you prefer",
    "Equity - I'd rather put in my own money than borrow."),
  # --- confirmations: last, so a real question is never waved through ------
  R("confirm", "*",
    r"(does|do) (this|that|these|everything) (look|sound|read)s? (right|good|accurate)"
    r"|is (that|this) (an? )?(right|accurate|correct|fair)|(look|sound)s? right|any changes|tell me (if|any)"
    r"|did i (get|capture)|shall we (move|continue)|before we move on"
    r"|does (it|that|this) (feel|seem) (accurate|right)|accurate to say|sound accurate|fair to say"
    r"|does (that|this) match|match how you think",
    "Yes, that's right.", times=None),
]


def _with(rules, *, replace=None, before=None):
  """Copy of rules with {id: rule} replacements and {anchor_id: [rules]} insertions."""
  out = []
  for r in rules:
    for extra in (before or {}).get(r["id"], []):
      out.append(extra)
    out.append((replace or {}).get(r["id"], r))
  return out


# ---------------------------------------------------------------------------
# Record helpers the checks read
# ---------------------------------------------------------------------------
def num(v):
  try:
    return None if v is None or v == "" else float(v)
  except (TypeError, ValueError):
    return None


def exact(v, want):
  v = num(v)
  return v is not None and abs(v - want) < 0.005


def lines(snap):
  out = []
  for lob in ((snap or {}).get("ops") or {}).get("lob_models") or []:
    for p in (lob or {}).get("products") or []:
      out.append(p or {})
  return out


def find_line(snap, key):
  for p in lines(snap):
    if re.search(LINE_PAT[key], str(p.get("product_name") or ""), re.I):
      return p
  return None


def wage(snap, pat):
  for p in ((snap or {}).get("people") or {}).get("people") or []:
    if re.search(pat, str((p or {}).get("full_name") or ""), re.I):
      return num(p.get("annual_wage"))
  return None


def basis_amount(snap, pat):
  for p in ((snap or {}).get("fin") or {}).get("payroll_basis_people_roles") or []:
    if re.search(pat, str((p or {}).get("full_name") or ""), re.I):
      return num(p.get("year1_payroll_amount"))
  return None


def pool(snap):
  return num(((snap or {}).get("people") or {}).get("rest_of_team_payroll_year1"))


def payroll(snap):
  return num(((snap or {}).get("fin") or {}).get("current_payroll"))


# ---------------------------------------------------------------------------
# Checks: (ok True/False, or None = not reached, detail)
# ---------------------------------------------------------------------------
def u2_stated_figures_exact(rec):
  if not rec.completed:
    return None, "intake did not complete"
  f = rec.final
  got = {"owner": wage(f, "jess"), "Dana": wage(f, "dana"), "rest of team": pool(f), "payroll": payroll(f)}
  want = {"owner": OWNER_WAGE, "Dana": DANA_WAGE, "rest of team": POOL, "payroll": ON_FILE}
  bad = ["%s %r (said %s)" % (k, got[k], "{:,.2f}".format(want[k])) for k in want if not exact(got[k], want[k])]
  return not bad, ("; ".join(bad) if bad else
                   "owner 62,000.00, Dana 52,000.00, rest of team 150,000.00, payroll 264,000.00 - all exact")


def c1_rest_of_team_fires(rec):
  t = rec.turn_of("rest_of_team")
  if t is None:
    asked = [x["i"] for x in rec.turns if REST_OF_TEAM_MARKER in x["reply"].lower()]
    if rec.completed:
      return False, ("the intake completed and the rest-of-team question never fired - two named "
                     "wages, seven on staff" + (" (asked at %s but never answered)" % asked if asked else ""))
    return None, "not reached"
  got = pool(t["snap"])
  return exact(got, POOL), "asked at turn %d; stored pool %r (said $150,000)" % (t["i"] - 1, got)


def c3_figure_stays_on_its_line(rec):
  """Every turn: a line's capacity, utilization or price may change only on the
  turn the client stated that very figure for that very line - or to exactly
  the figure the client stated (a re-statement or a finalize tidy)."""
  stated = {k for k, rids in LINE_RULES.items() if any(rec.turn_of(r) is not None for r in rids)}
  if not stated:
    return None, "no line figure stated yet"
  problems = []
  for t in rec.turns[1:]:
    before, after = rec.turns[t["i"] - 1]["snap"], t["snap"]
    for (ln, grp), rids in LINE_RULES.items():
      a = find_line(after, ln)
      if a is None:
        continue
      b = find_line(before, ln)
      field = GROUP_FIELD[grp]
      vb, va = (num(b.get(field)) if b else None), num(a.get(field))
      if vb == va or (vb is not None and va is not None and abs(vb - va) < 1e-6):
        continue
      if t["rule"] in rids or exact(va, STATED_LINE[(ln, grp)]):
        continue
      problems.append("turn %d (%s: %r) moved %s %s %r -> %r" % (
        t["i"], t["rule"], t["sent"][:48], ln, field, vb, va))
  missing = ["%s %s" % k for k in LINE_RULES if k not in stated]
  detail = "; ".join(problems[:8]) if problems else (
    "%d of 6 line figures stated, none landed on another line or field" % len(stated))
  if missing and not problems:
    detail += " (not yet stated: %s)" % ", ".join(missing)
  return (False if problems else (True if not missing or rec.completed else None)), detail


def c3_final_line_values(rec):
  if not rec.completed:
    return None, "intake did not complete"
  bad = []
  for (ln, grp), want in STATED_LINE.items():
    row = find_line(rec.final, ln)
    got = num((row or {}).get(GROUP_FIELD[grp]))
    if got is None or abs(got - want) > max(0.005, abs(want) * 0.001):
      bad.append("%s %s %r (said %s)" % (ln, GROUP_FIELD[grp], got, want))
  return not bad, "; ".join(bad) if bad else "both lines stored as stated: 120/wk 80% $85, 150/wk 70% $40"


def _stated_total_window(rec):
  t0, tr = rec.turn_of("headcount_with_total"), rec.turn_of("hold_use_on_file")
  end = tr["i"] if tr else len(rec.turns)
  return t0, tr, [x for x in rec.turns if t0 and t0["i"] <= x["i"] < end]


def c2_app_asks(rec):
  t0, _tr, window = _stated_total_window(rec)
  if t0 is None:
    return None, "stated total not given yet"
  hit = next((x for x in rec.turns[t0["i"]:] if "$264,000" in x["reply"] and "$300,000" in x["reply"]
              and "?" in x["reply"]), None)
  if hit is None:
    return False, "the app never named both $300,000 and $264,000 and asked"
  return True, "asked at turn %d: %r" % (hit["i"], hit["reply"][:160])


def c2_numbers_unmoved(rec):
  t0 = rec.turn_of("headcount_with_total")
  if t0 is None:
    return None, "stated total not given yet"
  s = t0["snap"]
  got = (wage(s, "jess"), wage(s, "dana"), pool(s), payroll(s))
  ok = all(exact(g, w) for g, w in zip(got, (OWNER_WAGE, DANA_WAGE, POOL, ON_FILE)))
  return ok, "after the stated total: owner %r, Dana %r, pool %r, payroll %r (on file 62k/52k/150k/264k)" % got


def c2_holds_open(rec):
  t0, tr, window = _stated_total_window(rec)
  if t0 is None:
    return None, "stated total not given yet"
  closed = [x["i"] for x in window if x["done"] or x["snap"]["focus"] == "done" or x["snap"]["financials_confirmed"]]
  if closed:
    return False, "the intake completed at turn %s with the payroll question open" % closed[0]
  tf = rec.turn_of("funding")
  if tf is None or tf not in window:
    return (None if tr is None else False), (
      "the last financials question was not answered while the question was open - "
      "nothing proves the hold held the door")
  deflect = rec.turn_of("hold_deflect")
  return True, ("open from turn %d to %s: the last question answered at turn %d without completing%s" % (
    t0["i"], tr["i"] if tr else "the end", tf["i"],
    ", and still open after the client put it off (turn %d)" % deflect["i"] if deflect in window else ""))


def c2_resolves_on_file(rec):
  tr = rec.turn_of("hold_use_on_file")
  if tr is None:
    return (False if rec.completed else None), "the client never told it to use the figure on file"
  if not rec.completed:
    return False, "the client said use the $264,000 on file and the intake still did not complete"
  from client_intake_and_finmo.intake_coherence.section import open_hold_questions
  still = open_hold_questions(rec.final.get("fin") or {})
  ok = exact(payroll(rec.final), ON_FILE) and not still
  return ok, "completed on $%s; open holds after: %s" % ("{:,.2f}".format(payroll(rec.final) or 0), [k for k, _ in still] or "none")


def c4_wage_survives_monthly(rec):
  t = rec.turn_of("restate_monthly")
  if t is None:
    return None, "restatement not given yet"
  after = wage(t["snap"], "dana")
  final = wage(rec.final, "dana") if rec.completed else None
  basis = basis_amount(rec.final, "dana") if rec.completed else None
  ok = exact(after, DANA_WAGE) and (final is None or exact(final, DANA_WAGE)) and (basis is None or exact(basis, DANA_WAGE))
  return ok, "Dana after '$4,333.33 a month': %r; at the end: %r; year-one payroll row: %r (said $52,000.00 a year)" % (
    after, final, basis)


_FACT = re.compile(r"\{\{fact:([A-Za-z0-9_.-]+)\}\}")
_ANY_TOKEN = re.compile(r"\{\{[^{}]{0,80}\}\}")


def _fill_like_frontend(key, snap, business):
  """frontend/src/intake_form/flow/renderFactTemplate.ts, resolveFactValue:
  business.{name,address,start_date} from the form; ops/market/people/
  financials from the shared context; an ops product field falls back to the
  first product's value. Anything else fills with ''."""
  parts = str(key).split(".")
  if len(parts) != 2:
    return ""
  group, field = parts
  if group == "business":
    value = {"name": business.get("business_name"), "address": business.get("address"),
             "start_date": business.get("business_start_date")}.get(field)
  else:
    src = {"ops": snap.get("ops"), "market": snap.get("market"), "people": snap.get("people"),
           "financials": snap.get("fin")}.get(group)
    value = src.get(field) if isinstance(src, dict) else None
    if value in (None, "") and group == "ops":
      value = next((p.get(field) for p in lines(snap) if p.get(field) not in (None, "")), None)
  if isinstance(value, (dict, list)) and not value:
    return ""
  return "" if value is None else str(value).strip()


def u1_every_token_fills(rec):
  """The app sends {{fact:...}} tokens by design - the frontend fills them
  (renderFactTemplate.ts). What reaches the client broken is a token that
  fills with nothing (a hole in the sentence) or a {{...}} the frontend does
  not treat as a fact at all. (2026-09-11: this check first flagged
  {{fact:business.name}} itself - wrong; that one fills with the name.)"""
  problems = []
  for t in rec.turns:
    for m in _ANY_TOKEN.finditer(t["reply"]):
      fm = _FACT.fullmatch(m.group(0))
      if fm is None:
        problems.append("turn %d: %s is not a fact token - the client sees it raw" % (t["i"], m.group(0)))
      elif not _fill_like_frontend(fm.group(1), t["snap"], rec.business):
        problems.append("turn %d: %s fills with nothing - a hole in the sentence" % (t["i"], m.group(0)))
  if problems:
    return False, "; ".join(problems[:6])
  n = sum(len(_ANY_TOKEN.findall(t["reply"])) for t in rec.turns)
  return True, "%d template token(s) in %d app messages, every one fills" % (n, len(rec.turns))


_BOUNCE = re.compile(
  r"- is that your [^?]{3,80}\?|which figure is that, so i record it|"
  r"is that your [^?]{3,60}, or your [^?]{3,60}\?", re.I)


def u3_no_figure_bounced(rec):
  """The price/capacity ping-pong (Ferriday 2026-09-10/11, reproduced by the
  first scripted run): the client states a figure plainly, for the field just
  asked, and the app bounces it back - 'The About 80 percent ... - is that
  your financials summary, or your weekly capacity?'. Every scripted answer
  names its field, so any such clarifier after one is the app not hearing it."""
  hits = []
  for t in rec.turns[1:]:
    if t["rule"] in ("seed", "IMPROVISED"):
      continue
    m = _BOUNCE.search(t["reply"])
    if m:
      hits.append("turn %d after %s (%r): %r" % (t["i"], t["rule"], t["sent"][:50], t["reply"][:140]))
  if hits:
    return False, "%d bounced figure(s): %s" % (len(hits), " || ".join(hits[:4]))
  return True, "no stated figure bounced back in %d client turns" % (len(rec.turns) - 1)


U3 = ("U3", "a plainly stated figure is never bounced back as 'is that your X or your Y?'", u3_no_figure_bounced)

_CAP_REASK = re.compile(r"clear on your capacity|one number you have in mind|just to confirm your capacity", re.I)


def u4_stored_capacity_never_reasked(rec):
  """The ping-pong's other half (Ferriday 2026-09-11 turns 24 and 32; the
  baseline recording 2026-09-11 turn 7): the client answers utilization and
  the app asks for the capacity it has already stored."""
  hits = []
  for t in rec.turns[1:]:
    if not _CAP_REASK.search(t["reply"]):
      continue
    before = rec.turns[t["i"] - 1]["snap"]
    held = [ln for ln in ("full", "bath")
            if num((find_line(before, ln) or {}).get("units_per_week_capacity")) is not None]
    if held:
      hits.append("turn %d after %s (%r): capacity already stored for %s, asked again: %r" % (
        t["i"], t["rule"], t["sent"][:50], "/".join(held), t["reply"][:110]))
  if hits:
    return False, "%d re-ask(s): %s" % (len(hits), " || ".join(hits[:3]))
  return True, "no stored capacity asked for again"


U4 = ("U4", "a capacity already stored is never asked for again", u4_stored_capacity_never_reasked)


# What the --author GPT client knows. Rules stay the spec; this only drafts
# answers to the questions the rules do not cover yet, and an author run is
# never a pass.
BRIEF = (
  "You are Jess Harlow, sole owner of Larkspur Dog Grooming, a dog grooming salon in Portland, "
  "Oregon, operating since March 2019, a single-member LLC. Owners drop their dogs off and pick "
  "them up. Two services, tracked separately: full groom ($85 average; about 120 a week when "
  "fully booked; about 80 percent booked) and bath-and-tidy ($40; about 150 a week; about 70 "
  "percent booked). Open year-round, weekly cadence. Customers are local households on "
  "Portland's east side; they book online or by phone. Staff: you (lead groomer, $62,000 a "
  "year), Dana Okafor (head groomer, $52,000 a year) and five groomers and bathers whose pay "
  "totals $150,000 a year - seven people. Revenue about $640,000 a year; supplies about 5 percent "
  "of revenue; marketing $12,000 a year; rent $4,500 a month; other regular bills $1,500 a month; "
  "equipment and build-out worth about $85,000; nothing on a lease; you have put in $120,000; "
  "$60,000 in the bank; customers pay at pickup; about $3,000 of supplier invoices; about $4,000 "
  "of inventory; no debt; you prefer equity to borrowing and a balanced cash posture. Answer the "
  "consultant's question in one to three short sentences - only what is asked, like a busy "
  "owner. If a question is outside these facts, answer plausibly and briefly and do not invent "
  "new dollar figures."
)


# ---------------------------------------------------------------------------
# The personas
# ---------------------------------------------------------------------------
U1 = ("U1", "every template token the app sends fills with a value", u1_every_token_fills)

PERSONAS = {
  "baseline": {
    "about": "two lines, two named wages among seven staff; nothing unusual said",
    "bootstrap": BOOTSTRAP,
    "rules": BASE_RULES,
    "checks": [
      U1,
      U3,
      U4,
      ("C1", "rest-of-team question fires (more people than named wages)", c1_rest_of_team_fires),
      ("C3", "a figure given for one line never lands on another line or field", c3_figure_stays_on_its_line),
      ("C3", "both lines stored exactly as stated", c3_final_line_values),
      ("U2", "every stated payroll figure stored exactly", u2_stated_figures_exact),
    ],
  },
  "stated_total": {
    "about": "states total payroll $300,000 against $264,000 on file, puts the question off, then says use the figure on file",
    "bootstrap": BOOTSTRAP,
    "rules": _with(
      BASE_RULES,
      replace={"headcount": R("headcount_with_total", "financials",
                              r"how many people are on payroll|people on payroll|employee count|headcount",
                              "Seven of us, including me, and total payroll comes to about $300,000 a year.")},
      before={"confirm": [
        R("hold_deflect", "*", HOLD_ASK, "Let me check that with my bookkeeper and come back to it.", scope="all"),
        R("hold_use_on_file", "*", HOLD_ASK, "Use the $264,000 on file - that's the right figure.", scope="all"),
      ]}),
    "checks": [
      U1,
      U3,
      U4,
      ("C2", "the app names both figures and asks", c2_app_asks),
      ("C2", "the stored wages, pool and payroll do not move", c2_numbers_unmoved),
      ("C2", "the intake does not complete while the question is open", c2_holds_open),
      ("C2", "'use the figure on file' closes it and the intake completes", c2_resolves_on_file),
      ("U2", "every stated payroll figure stored exactly", u2_stated_figures_exact),
    ],
  },
  "monthly_wage": {
    "about": "restates Dana's $52,000 a year as about $4,333.33 a month",
    "bootstrap": BOOTSTRAP,
    "rules": _with(BASE_RULES, before={"add_another_2": [
      R("restate_monthly", "people", _ANOTHER,
        "Just so it's clear, Dana's $52,000 a year works out to about $4,333.33 a month."),
    ]}),
    "checks": [
      U1,
      U3,
      U4,
      ("C4", "a stated annual wage survives a monthly restatement to the cent", c4_wage_survives_monthly),
      ("U2", "every stated payroll figure stored exactly", u2_stated_figures_exact),
    ],
  },
}
