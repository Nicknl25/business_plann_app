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
# THE DATE THE PERSONAS WERE RECORDED ON (2026-09-11). current_date rides in
# every consult context and the GPT lock keeps bare dates in its key, so a
# run on any other UTC day misses the whole store and goes live - the gate
# pins the handler's "today" to this through INTAKE_CURRENT_DATE. Bump it
# only on a deliberate full re-record.
RECORDED_ON = "2026-09-11"
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

# A persona's FACTS - every figure its client states, read by the checks.
# Larkspur's are the default, so a persona without facts is Larkspur.
LARKSPUR = {
  "owner": {"pat": "jess", "wage": OWNER_WAGE},
  "key": {"pat": "dana", "wage": DANA_WAGE},
  "pool": POOL,
  "lines": {
    ln: {"pat": LINE_PAT[ln], "cap_field": GROUP_FIELD["cap"], "cap": STATED_LINE[(ln, "cap")],
         "util": STATED_LINE[(ln, "util")], "price": STATED_LINE[(ln, "price")],
         "rules": {g: LINE_RULES[(ln, g)] for g in ("cap", "util", "price")}}
    for ln in ("full", "bath")
  },
}


def _facts(rec):
  return getattr(rec, "facts", None) or LARKSPUR


def _field_of(facts, ln, grp):
  return facts["lines"][ln]["cap_field"] if grp == "cap" else GROUP_FIELD[grp]

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
  # "what does that typically run" is a price too (baseline 2026-09-11 17:00 turn 10)
  R("price_full", "ops", r"(?=.*\bfull[- ]?groom)(?=.*(price|charge|how much do (you|customers)|average ticket|pay for|average per|per dog|visit average|typically (run|cost|go)|\bcost\b))",
    "A full groom averages $85."),
  R("price_bath", "ops", r"(?=.*\bbath)(?=.*(price|charge|how much do (you|customers)|average ticket|pay for|average per|per dog|visit average|typically (run|cost|go)|\bcost\b))",
    "A bath-and-tidy averages $40."),
  # a PLAUSIBILITY CHALLENGE on a capacity figure (live run 2026-09-11 23:30:
  # "120 full grooms per week is a pretty high volume - does that number
  # already assume multiple groomers working at once?") - the persona confirms
  # its own figure and the assumption behind it; never a new number.
  R("cap_plausibility", "ops",
    r"(sanity|already assume|assumes? multiple|multiple groomers|something else in mind"
    r"|pretty high|high volume|does that (number|figure)|is that (number|figure) (right|realistic))",
    "Yes - that assumes the whole team grooming at once. 120 full grooms a week is our "
    "fully booked figure for full grooms only; bath-and-tidies are separate at about 150."),
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
  # the follow-up: which lever fills them (baseline 2026-09-11 16:49 turn 16)
  R("growth_lever", "ops", r"lever|lean on|primary push|biggest",
    "Word of mouth and repeat visits - a referral discount for regulars."),
  R("geography", "ops", r"\barea\b|geograph|come from|service area|neighbo|radius|local",
    "Mostly Portland's east side, within about five miles of the salon."),
  R("channel", "ops", r"online|how do (customers|people|clients) (book|find)|walk[- ]in|storefront|physical|sales channel|find you",
    "Customers book online or by phone, and most come from word of mouth."),
  R("advantage", "ops", r"stand out|different from|advantage|why .{0,40} choose|competitor|sets you apart"
    r"|sets .{0,40}apart|do better|regulars appreciate|best customers say",
    "Fear-free handling - dogs are never crated for hours, and we text owners the moment "
    "their dog is ready."),
  # the consultant sometimes confirms the stored edge with a follow-up ("is
  # that your main edge, or anything else?") - guarded pass 2026-09-12
  R("advantage_confirm", "ops", r"main edge|anything else you.d highlight|truly sets|is that (your|the) main",
    "That's it - the fear-free handling and the texting. Nothing else to add.", times=2),
  # --- target market ----------------------------------------------------
  R("gender", "market", r"gender|female|male", "All genders, no particular focus."),
  R("age", "market", r"\bage\b|ages|years old", "Mostly adults 25 to 64."),
  R("income", "market", r"income", "Middle income and up - roughly $50,000 to $150,000 a household."),
  R("education", "market", r"education", "No preference - a broad mix."),
  # the options can sit in a bullet paragraph with no "?" (baseline 2026-09-11
  # 17:07 turn 22: "Do you want to add any of those (you can choose any combination")
  R("dims_skip", "market", r"employment|household structure|housing|add any of those|any combination|optional extra",
    "Skip those, thanks - they don't matter for us."),
  R("employment", "market", r"employment", "Mostly working adults, plus some retirees."),
  # --- people -----------------------------------------------------------
  R("key_person_1", "people", r"key (person|people|individual)|pivotal|full name|name.{0,40}(title|role)",
    f"{OWNER}, owner and lead groomer. 14 years grooming. I pay myself $62,000 a year."),
  # the app may ask for Dana BY NAME (baseline 2026-09-11 17:09 turn 25:
  # "Next, let's capture Dana ... For Dana, what are her: - Full name")
  R("add_another_1", "people", _ANOTHER + r"|\bfor dana\b|capture dana|dana'?s (full name|title|details)",
    f"Yes - {DANA}, head groomer, 9 years grooming. She earns $52,000 a year."),
  # once a people clarify goes to the CONSULTANT (issue 577's people half,
  # 2026-09-11 23:52), it asks the schema's remaining field for Dana -
  # "what relevant education or credentials does she have?" - and the
  # persona must answer it, never a new figure.
  R("dana_credentials", "people",
    r"(credential|education|certif|grooming school|training).{0,140}\b(dana|she|her)\b"
    r"|\b(dana|she|her)\b.{0,140}(credential|education|certif|grooming school)",
    "None formal - Dana trained on the job. Nothing else to note for her."),
  R("add_another_2", "people", _ANOTHER, "No, just the two of us by name."),
  R("narrative", "people", r"review this draft|narrative|any changes", "That reads well, no changes.", times=2),
  R("rest_of_team", "*", re.escape(REST_OF_TEAM_MARKER),
    "The rest of the team - five groomers and bathers - comes to about $150,000 a year.",
    times=2, scope="all"),
  # the app's double-count check (the cleaning persona drew it, 2026-09-11)
  R("double_count", "*", r"counted twice|inside that \$|only the people we haven'?t listed",
    "No - Dana is separate. The $150,000 is only the five groomers and bathers.", times=3, scope="all"),
  R("pool_total", "*", r"per (groomer|bather|person|employee)|for all .{0,30}together|total for all",
    "That's the total for all five together, per year.", times=2),
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
    r"|does (that|this) match|match how you think"
    r"|sound like the right|right way to describe|tighten or expand",
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


def find_line(snap, key, facts=None):
  f = facts or LARKSPUR
  rows = lines(snap)
  for p in rows:
    if re.search(f["lines"][key]["pat"], str(p.get("product_name") or ""), re.I):
      return p
  if len(f["lines"]) == 1 and len(rows) == 1:
    return rows[0]  # a one-line business: its only row is the line
  return None


def describe_state(snap, facts=None):
  """One transcript line of what the draft holds after a turn."""
  f = facts or LARKSPUR
  parts = []
  for key, spec in f["lines"].items():
    row = find_line(snap, key, f)
    if row:
      parts.append("%s cap=%s util=%s price=%s" % (
        key, row.get(spec["cap_field"]), row.get("utilization_rate"), row.get("unit_price")))
  parts.append("%s=%s %s=%s pool=%s payroll=%s" % (
    f["owner"]["pat"], wage(snap, f["owner"]["pat"]), f["key"]["pat"], wage(snap, f["key"]["pat"]),
    pool(snap), payroll(snap)))
  hold = ((snap or {}).get("fin") or {}).get("_payroll_fold_hold")
  if hold:
    parts.append("payroll hold unapplied=%s" % (hold or {}).get("unapplied"))
  parts.append("focus=%s confirmed=%s" % ((snap or {}).get("focus"), (snap or {}).get("financials_confirmed")))
  return " | ".join(parts)


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
  fx, s = _facts(rec), rec.final
  o, k = fx["owner"], fx["key"]
  got = {"owner": wage(s, o["pat"]), k["pat"]: wage(s, k["pat"]), "rest of team": pool(s), "payroll": payroll(s)}
  want = {"owner": o["wage"], k["pat"]: k["wage"], "rest of team": fx["pool"],
          "payroll": o["wage"] + k["wage"] + fx["pool"]}
  bad = ["%s %r (said %s)" % (n, got[n], "{:,.2f}".format(want[n])) for n in want if not exact(got[n], want[n])]
  return not bad, ("; ".join(bad) if bad else
                   "all exact: " + ", ".join("%s %s" % (n, "{:,.2f}".format(v)) for n, v in want.items()))


def c1_rest_of_team_fires(rec):
  t = rec.turn_of("rest_of_team")
  if t is None:
    asked = [x["i"] for x in rec.turns if REST_OF_TEAM_MARKER in x["reply"].lower()]
    if rec.completed:
      return False, ("the intake completed and the rest-of-team question never fired - two named "
                     "wages, seven on staff" + (" (asked at %s but never answered)" % asked if asked else ""))
    return None, "not reached"
  want = _facts(rec)["pool"]
  got = pool(t["snap"])
  return exact(got, want), "asked at turn %d; stored pool %r (said %s)" % (
    t["i"] - 1, got, "${:,.0f}".format(want))


def c3_figure_stays_on_its_line(rec):
  """Every turn: a line's capacity, utilization or price may change only on the
  turn the client stated that very figure for that very line - or to exactly
  the figure the client stated (a re-statement or a finalize tidy)."""
  fx = _facts(rec)
  line_rules = {(ln, g): set(spec["rules"][g]) for ln, spec in fx["lines"].items() for g in ("cap", "util", "price")}
  stated = {k for k, rids in line_rules.items() if any(rec.turn_of(r) is not None for r in rids)}
  if not stated:
    return None, "no line figure stated yet"
  problems = []
  for t in rec.turns[1:]:
    before, after = rec.turns[t["i"] - 1]["snap"], t["snap"]
    for (ln, grp), rids in line_rules.items():
      a = find_line(after, ln, fx)
      if a is None:
        continue
      b = find_line(before, ln, fx)
      field = _field_of(fx, ln, grp)
      vb, va = (num(b.get(field)) if b else None), num(a.get(field))
      if vb == va or (vb is not None and va is not None and abs(vb - va) < 1e-6):
        continue
      if t["rule"] in rids or exact(va, fx["lines"][ln][grp]):
        continue
      problems.append("turn %d (%s: %r) moved %s %s %r -> %r" % (
        t["i"], t["rule"], t["sent"][:48], ln, field, vb, va))
  missing = ["%s %s" % k for k in line_rules if k not in stated]
  detail = "; ".join(problems[:8]) if problems else (
    "%d of %d line figures stated, none landed on another line or field" % (len(stated), len(line_rules)))
  if missing and not problems:
    detail += " (not yet stated: %s)" % ", ".join(missing)
  return (False if problems else (True if not missing or rec.completed else None)), detail


def c3_final_line_values(rec):
  if not rec.completed:
    return None, "intake did not complete"
  fx = _facts(rec)
  bad, said = [], []
  for ln, spec in fx["lines"].items():
    row = find_line(rec.final, ln, fx)
    for grp in ("cap", "util", "price"):
      want, field = spec[grp], _field_of(fx, ln, grp)
      got = num((row or {}).get(field))
      said.append("%s %s %s" % (ln, field, want))
      if got is None or abs(got - want) > max(0.005, abs(want) * 0.001):
        bad.append("%s %s %r (said %s)" % (ln, field, got, want))
  return not bad, "; ".join(bad) if bad else "every line stored as stated: " + ", ".join(said)


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
    fx = _facts(rec)
    held = [ln for ln, spec in fx["lines"].items()
            if num((find_line(before, ln, fx) or {}).get(spec["cap_field"])) is not None]
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


# ---------------------------------------------------------------------------
# A SECOND SHAPE (Nick 2026-09-11: "Add a second persona with a different
# shape - different industry, different line count. One dog-grooming
# business proves one path."): Northgate Commercial Cleaning. ONE line,
# recurring office cleaning billed MONTHLY per client site; business
# clients (the B2B market questions); a van loan (the debt questions);
# receivables from monthly invoicing; the owner states pay MONTHLY ("$6,500
# a month" must land as 78,000.00 exactly).
# ---------------------------------------------------------------------------
CLEANING_BOOTSTRAP = {
  "business_name": "Northgate Commercial Cleaning",
  "business_start_date": "06/01/2017",
  "address": "2215 Nicollet Ave, Minneapolis, MN 55404",
  "address_street": "2215 Nicollet Ave",
  "address_city": "Minneapolis",
  "address_state": "MN",
  "address_zip": "55404",
  "address_country": "USA",
}

CLEANING_FACTS = {
  "owner": {"pat": "marcus", "wage": 78000.0},     # "$6,500 a month"
  "key": {"pat": "priya", "wage": 54000.0},
  "pool": 176000.0,                                # eight part-time cleaners
  "lines": {
    "sites": {"pat": r"clean|contract|site|office|janitor|commercial", "cap_field": "units_per_period_capacity",
              "cap": 40.0, "util": 0.85, "price": 1200.0,
              "rules": {"cap": {"cap_sites", "cap_reask_sites"}, "util": {"util_sites"},
                        "price": {"price_sites"}}},
  },
}

_UTIL_ASK = r"how full|utiliz|percent|% of|\d ?%|booking level|average (load|booking)|filled|under contract right now"
_CONFIRM_RULE = next(r for r in BASE_RULES if r["id"] == "confirm")

CLEANING_RULES = [
  # --- operations -------------------------------------------------------
  R("describe", "ops", r"describe in plain language|what .{0,60} does or will do",
    "Northgate Commercial Cleaning cleans offices and small commercial buildings in Minneapolis. "
    "It's one service: recurring evening cleaning under monthly contracts - each client site pays a "
    "flat monthly fee."),
  R("cadence", "ops", r"monthly (works|cadence|basis|rhythm)|month by month|year[- ]round|seasonal",
    "Yes - we bill monthly, so monthly works."),
  R("customers", "ops", r"individual|consumer|households|businesses|b2b|primarily serve|who (are|is) your",
    "Businesses - offices, clinics and small commercial buildings. No homes."),
  R("legal", "ops", r"legal (structure|entity|set ?up)|sole propriet|\bllc\b|s-?corp|partnership",
    "It's a single-member LLC - I'm the only owner."),
  R("picture", "ops", r"picturing|day[- ]to[- ]day|lay out how|matches how|how .{0,40} actually runs",
    "Yes. Priya runs the crews, and our part-time cleaners do the work in the evenings at the "
    "client's building."),
  R("split", "ops", r"separate|separately|break (it|them|that)|different (things|services|lines)|one line|single line|one service",
    "No - it's all one service, recurring office cleaning on monthly contracts.", times=2),
  R("unit", "ops", r"count as (one|a) unit|one unit|unit of|what .{0,30}(counts|count) as",
    "One client site cleaned for a month under contract.", times=2),
  R("util_sites", "ops", _UTIL_ASK, "About 85 percent - we have 34 sites under contract right now."),
  R("price_sites", "ops",
    r"price|charge|how much do (you|clients|customers)|average (fee|contract|ticket)|per site|typically (run|cost|go)|\bcost\b|monthly fee",
    "About $1,200 per site per month on average.", times=2),  # the app re-checks the price (turn 15)
  R("cap_reask_sites", "ops", r"clear on your capacity|one number you have in mind|confirm your capacity",
    "40 client sites a month.", times=3),
  R("cap_sites", "ops", r"capacity|fully booked|maximum|\bmax\b|at most|realistically|how many",
    "About 40 client sites a month with the crew we have now."),
  R("fulfillment", "ops", r"done by you|who (does|handles|performs)|crews?|cleaners do",
    "Priya supervises; our part-time cleaners do the cleaning in the evenings after the offices close.",
    times=2),
  R("delivery", "ops", r"in[- ]person|come to you|on[- ]?site|mobile|travel|at (their|the client|your client)|go to",
    "We go to the client's building - all the work is on their site, in the evenings.", times=2),
  R("stream", "*", r"before we wrap up operations",
    "No - no carpet shampooing or window washing, just recurring office cleaning.", times=2, scope="all"),
  R("goal", "ops", r"\bgoal\b|next 12 months|12 months", "Get to 38 sites under contract."),
  R("growth", "ops", r"grow|lever", "More contracts - we could take six more sites without hiring."),
  R("growth_lever", "ops", r"lever|lean on|primary push|biggest",
    "Referrals from the property managers we already work with."),
  R("geography", "ops", r"\barea\b|geograph|come from|service area|neighbo|radius|local|where .{0,30}(clients|customers)",
    "Minneapolis and the inner-ring suburbs - within about 20 minutes' drive.", times=2),  # re-framed (turn 11)
  R("channel", "ops", r"online|how do (customers|people|clients) (book|find)|walk[- ]in|storefront|physical|sales channel|find you|win (work|contracts)|\bbid",
    "Referrals and property managers send most of our work; we bid on a few contracts a year."),
  R("advantage", "ops", r"stand out|different from|advantage|why .{0,40} choose|competitor|sets .{0,40}apart|do better|best (customers|clients) say",
    "Reliability - the same crew every visit, and we fix a complaint the same night."),
  # --- target market: business clients ----------------------------------
  R("b2b_industry", "market", r"industr|kinds of (businesses|companies|organizations|clients)|types of (businesses|companies|organizations|clients)|sectors?",
    "Professional offices - law firms, accountants, clinics - and small property managers."),
  R("b2b_size", "market", r"\bsize\b|how (big|large)|employees|small, mid|mid-sized",
    "Small to mid-sized - about 10 to 150 people per site."),
  # the app follows "a few years" up ("3-5+ years ... rather than startups
  # under 2 years?" - cleaning 2026-09-11 17:20 turn 20): one answer, both asks
  R("b2b_established", "market", r"established|years in business|how long .{0,40}(operating|in business|around)|newer|mature|track record|a few years|startups",
    "Mostly established firms - three years or more in business, not new startups.", times=2),
  R("b2b_decider", "market", r"decision|who (signs|decides|buys|chooses)|buyer",
    "Office managers and property managers sign our contracts."),
  R("consumer_dims", "market", r"gender|\bage\b|income|education|employment|household|housing|add any of those|any combination|optional extra",
    "Not relevant for us - our clients are businesses, not households.", times=6),
  # --- people -----------------------------------------------------------
  R("key_person_1", "people", r"key (person|people|individual)|pivotal|full name|name.{0,40}(title|role)",
    "Marcus Lindqvist, owner and operations lead. 12 years in commercial cleaning. I pay myself $6,500 a month."),
  R("add_another_1", "people", _ANOTHER + r"|\bfor priya\b|capture priya|priya'?s (full name|title|details)",
    "Yes - Priya Raman, crew supervisor, 7 years in cleaning. She earns $54,000 a year."),
  R("add_another_2", "people", _ANOTHER, "No, just the two of us by name."),
  R("narrative", "people", r"review this draft|narrative|any changes", "That reads well, no changes.", times=2),
  # unambiguous: "all together" read as the whole team and drew the
  # double-count check (cleaning 2026-09-11 17:05, turn 26)
  R("rest_of_team", "*", re.escape(REST_OF_TEAM_MARKER),
    "Eight part-time cleaners, not counting Priya or me - about $176,000 a year for the eight of them.",
    times=2, scope="all"),
  R("double_count", "*", r"counted twice|inside that \$|only the people we haven'?t listed",
    "No - Priya is separate. The $176,000 is only the eight part-time cleaners.", times=3, scope="all"),
  R("pool_total", "*", r"per (cleaner|person|employee)|for all .{0,30}together|total for all",
    "That's the total for all eight together, per year.", times=2),
  # --- financials -------------------------------------------------------
  R("revenue", "financials", r"revenue|bringing in", "About $490,000 a year."),
  R("inventory", "financials", r"inventory|kept in stock", "About $3,000 of cleaning supplies.", times=2),
  R("cogs", "financials", r"direct costs|materials|supplies|cost of (goods|sales)",
    "Cleaning supplies run about 6 percent of revenue.", times=2),
  R("other_opex", "financials",
    r"other regular business bills|other (regular )?(monthly )?(operating|business) (expenses|bills)|ongoing bills",
    "About $2,500 a month - van fuel, insurance, software and phones.", times=2),
  R("marketing", "financials", r"for marketing|marketing (budget|spend)|on marketing|spend on marketing",
    "About $6,000 a year on marketing.", times=2),
  R("rent_future", "financials", r"stay part of how|expect paid dedicated|keep (renting|the space)",
    "Yes, we'll keep the office."),
  R("rent", "financials", r"pay each month for the space|\brent\b", "$1,400 a month for a small office and storage unit."),
  R("headcount", "financials", r"how many people are on payroll|people on payroll|employee count|headcount",
    "Ten of us, including me.", times=2),
  # the app's lease question covers finance agreements too; the van is a
  # plain bank loan, given at the debt question - "No leases - the vans are
  # on a loan" mixed the two and was re-asked (cleaning 2026-09-11 turn 38)
  R("lease", "financials", r"lease or finance|under a lease|finance agreement|lease or finance payments",
    "Zero - nothing on a lease or an equipment-finance agreement.", times=2),
  R("capex", "financials", r"one-time purchases|capital spending|larger .{0,30}purchases",
    "Nothing recent - zero.", times=2),
  R("assets", "financials", r"worth, all together|equipment, devices, furniture|currently in the business",
    "About $45,000 - two vans and our equipment.", times=2),
  R("equity", "financials", r"money or value has gone into|invested|investors", "About $60,000, all mine.", times=2),
  R("debt", "financials", r"owe in total on loans|loans, lines of credit|total debt",
    "About $18,000 left on a van loan.", times=2),
  # interest and principal BEFORE the payments rule: "Of your debt payments,
  # what is the annual interest cost" names debt payments too
  R("interest", "financials", r"interest", "About $1,100 a year.", times=2),
  R("principal", "financials", r"principal", "About $6,700 a year.", times=2),
  R("debt_payments", "financials", r"debt payments|loan payments?|other .{0,20}payments",
    "$650 a month on the van loan.", times=2),
  R("cash", "financials", r"cash .{0,30}on hand|in the bank|bank accounts", "About $35,000 in the bank.", times=2),
  R("ap", "financials", r"regular operating bills|supplier invoices|accounts payable", "About $4,000.", times=2),
  R("ar", "financials", r"(customers|clients) currently owe|unpaid invoices|payment plans|accounts receivable",
    "About $41,000 - we invoice monthly and clients pay in 30 days.", times=2),
  R("cash_posture", "financials", r"extra cash|cash posture", "Balanced."),
  R("funding", "financials", r"outside capital|prefer to fund|how would you prefer", "Debt - a bank line if we need one."),
  _CONFIRM_RULE,
]

PERSONAS["cleaning"] = {
  "about": "one line, monthly contracts, business clients, a van loan; the owner states pay monthly",
  "bootstrap": CLEANING_BOOTSTRAP,
  "facts": CLEANING_FACTS,
  "brief": (
    "You are Marcus Lindqvist, sole owner of Northgate Commercial Cleaning in Minneapolis, operating "
    "since June 2017, a single-member LLC. One service: recurring evening office cleaning under monthly "
    "contracts, about $1,200 per client site per month; capacity about 40 sites a month, 34 under "
    "contract (85 percent). Clients are offices, clinics and small property managers in Minneapolis "
    "and the inner-ring suburbs. You pay yourself $6,500 a month; Priya Raman, crew supervisor, earns "
    "$54,000 a year; eight part-time cleaners cost about $176,000 a year - ten people. Revenue about "
    "$490,000 a year; supplies about 6 percent of revenue; marketing $6,000 a year; rent $1,400 a "
    "month; other bills $2,500 a month; vans and equipment worth $45,000; $18,000 left on a van loan "
    "at $650 a month (about $1,100 interest and $6,700 principal a year); $60,000 invested; $35,000 in "
    "the bank; clients owe about $41,000; $4,000 of supplier bills; $3,000 of supplies. Answer the "
    "consultant's question in one to three short sentences - only what is asked. If a question is "
    "outside these facts, answer plausibly and briefly and do not invent new dollar figures."
  ),
  "rules": CLEANING_RULES,
  "checks": [
    U1,
    U3,
    U4,
    ("C1", "rest-of-team question fires (more people than named wages)", c1_rest_of_team_fires),
    ("C3", "a figure given for the line never lands on another field", c3_figure_stays_on_its_line),
    ("C3", "the line stored exactly as stated", c3_final_line_values),
    ("U2", "every stated payroll figure stored exactly - the owner's monthly pay to the cent",
     u2_stated_figures_exact),
  ],
}


# ---------------------------------------------------------------------------
# A THIRD SHAPE - THE WALK (Nick 2026-09-12: "add a persona that reaches the
# walk. Every gate is green and none of them has seen the author... A
# persona whose numbers don't clear, that walks a round or two, refuses
# something in plain words, and picks an option."). Brightwater Office
# Services: Northgate's shape (one line, monthly contracts, business
# clients) losing a little - $14,500 a month of overhead on $490,000 of
# revenue, so even the capacity-capped growth path lands under the band
# (the fence must FAIL: a judged-path shortfall alone is disclosed, not
# walked) and the completion attempt opens the coherence walk. The client refuses rent (a
# signed three-year lease) and the crews in plain words, then picks the
# first option until the numbers clear.
# ---------------------------------------------------------------------------
WALK_BOOTSTRAP = {
  "business_name": "Brightwater Office Services",
  "business_start_date": "04/01/2018",
  "address": "1740 Grand Ave, St. Paul, MN 55105",
  "address_street": "1740 Grand Ave",
  "address_city": "St. Paul",
  "address_state": "MN",
  "address_zip": "55105",
  "address_country": "USA",
}

WALK_FACTS = {
  "owner": {"pat": "tamsin", "wage": 78000.0},     # "$6,500 a month"
  "key": {"pat": "luis", "wage": 54000.0},
  "pool": 176000.0,                                # eight part-time cleaners
  "lines": {
    "sites": {"pat": r"clean|contract|site|office|janitor|commercial", "cap_field": "units_per_period_capacity",
              "cap": 40.0, "util": 0.85, "price": 1200.0,
              "rules": {"cap": {"cap_sites", "cap_reask_sites"}, "util": {"util_sites"},
                        "price": {"price_sites"}}},
  },
}

# the walk's own wording only - an ops question can say "which fits" too
# (the naturalizer rewords the offer and uses a curly apostrophe: anchor on
# the phrases that survive it)
# and only the walk says "work on paper" in the same message
_WALK_OFFER = r"(?s)(?=.*work on paper)(?=.*(put in front of you|recompute on the spot|which of these feels|which fits))"

WALK_RULES = _with(
  CLEANING_RULES,
  replace={
    "describe": R("describe", "ops", r"describe in plain language|what .{0,60} does or will do",
                  "Brightwater Office Services cleans offices and small commercial buildings in St. Paul. "
                  "It's one service: recurring evening cleaning under monthly contracts - each client site pays a "
                  "flat monthly fee."),
    "picture": R("picture", "ops", r"picturing|day[- ]to[- ]day|lay out how|matches how|how .{0,40} actually runs",
                 "Yes. Luis runs the crews, and our part-time cleaners do the work in the evenings at the "
                 "client's building."),
    "fulfillment": R("fulfillment", "ops", r"done by you|who (does|handles|performs)|crews?|cleaners do",
                     "Luis supervises; our part-time cleaners do the cleaning in the evenings after the offices close.",
                     times=2),
    "geography": R("geography", "ops", r"\barea\b|geograph|come from|service area|neighbo|radius|local|where .{0,30}(clients|customers)",
                   "St. Paul and the east-metro suburbs - within about 20 minutes' drive.", times=2),
    "key_person_1": R("key_person_1", "people", r"key (person|people|individual)|pivotal|full name|name.{0,40}(title|role)",
                      "Tamsin Ferrier, owner and operations lead. 11 years in commercial cleaning. I pay myself $6,500 a month."),
    "add_another_1": R("add_another_1", "people", _ANOTHER + r"|\bfor luis\b|capture luis|luis'?s? (full name|title|details)",
                       "Yes - Luis Ortega, crew supervisor, 6 years in cleaning. He earns $54,000 a year."),
    "rest_of_team": R("rest_of_team", "*", re.escape(REST_OF_TEAM_MARKER),
                      "Eight part-time cleaners, not counting Luis or me - about $176,000 a year for the eight of them.",
                      times=2, scope="all"),
    "double_count": R("double_count", "*", r"counted twice|inside that \$|only the people we haven'?t listed",
                      "No - Luis is separate. The $176,000 is only the eight part-time cleaners.", times=3, scope="all"),
    "other_opex": R("other_opex", "financials",
                    r"other regular business bills|other (regular )?(monthly )?(operating|business) (expenses|bills)|ongoing bills",
                    "About $14,500 a month - insurance, a subcontracted floor-care crew, vehicle running costs, "
                    "equipment service contracts, software and phones.", times=2),
    "rent": R("rent", "financials", r"pay each month for the space|\brent\b",
              "$2,600 a month for the office and the storage bay."),
    "assets": R("assets", "financials", r"worth, all together|equipment, devices, furniture|currently in the business",
                "About $20,000 - the equipment; the vans are leased.", times=2),
    # THE VAN LEASE TRAP (run 1 wrote this $2,400 onto rent): the intake guard
    # must keep rent at $2,600 and say why in the client's words
    "lease": R("lease", "financials", r"lease or finance|under a lease|finance agreement|lease or finance payments",
               "The three vans are leased - about $2,400 a month for the three, and that's inside the $14,500 "
               "of other bills I gave you.", times=1),
    "goal": R("goal", "ops", r"\bgoal\b|next 12 months|12 months", "Get the business to actually make money - it's break-even now."),
    "growth": R("growth", "ops", r"grow|lever", "More contracts - we could take six more sites without hiring."),
  },
  before={"stream": [
    # after the stream question the app asks once more whether the line is
    # the only paid service (run 3, turn 16)
    R("only_service", "ops", r"only revenue.generating|any other distinct paid service|truly the only",
      "No - that's the only service."),
  ], "geography": [
    # the app restates the reach and asks whether it fits (run 1, turn 11)
    R("coverage", "ops", r"coverage description|how you think about your service area", "Yes, that coverage fits."),
  ], "add_another_2": [
    # a follow-up on the supervisor's credentials (run 1, turn 26)
    R("credentials", "people", r"education or credentials|credentials|certificates|formal schooling",
      "None specific - six years of on-the-job experience."),
  ], "capex": [
    # the balance question that follows the lease answer
    R("lease_balance", "financials", r"still owed|remaining (lease )?balance|owed in total on equipment|how much is still owed",
      "Nothing is owed on them - they're month-to-month with no balance to pay off. Zero.", times=2),
  ], "describe": [
    # THE WALK (first in the list: a half-used financials rule must never
    # answer the offer). The first offer is refused in plain words - a signed lease and
    # the crews - and nothing is picked; the second offer is taken at option 1,
    # and again if a further round comes, until the numbers clear.
    R("walk_refuse", "*", _WALK_OFFER,
      "Before I pick anything: the office lease is signed for three years, so the rent cannot move. "
      "And I am not cutting the crews - the people are the service.", scope="all"),
    R("walk_pick", "*", _WALK_OFFER, "Option 1.", times=12, scope="all"),
    R("walk_retention", "*", r"expect your current (customers|clients) to stay|how many you'?d realistically keep",
      "They would all stay - the contracts run a year.", times=2, scope="all"),
    R("walk_widened", "*", r"something is off|tell me which figure looks wrong|input is off",
      "Those figures are all right as I gave them.", times=2, scope="all"),
  ]},
)


def _coh(snap):
  return (((snap or {}).get("fin") or {}).get("_coherence")) or {}


def _walk_turns(rec):
  return [t for t in rec.turns if _coh(t["snap"]).get("status") in ("walking", "converged", "parked")]


def w1_first_round_is_authored(rec):
  """The author is on the hook: the FIRST round the walk offers was authored
  by the agent and priced by the engine, not the legacy planner."""
  walking = [t for t in rec.turns if _coh(t["snap"]).get("status") == "walking" and _coh(t["snap"]).get("round")]
  if not walking:
    return None, "the walk never opened (no walking round stored)"
  rnd = _coh(walking[0]["snap"])["round"]
  opts = rnd.get("options") or []
  labels = "; ".join("%s (%s)" % (o.get("label"), o.get("closes_display")) for o in opts)
  st = _coh(walking[0]["snap"])
  if rnd.get("key") != "authored":
    return False, "first round key %r, fallback=%s: %s" % (rnd.get("key"), st.get("authored_fallback"), labels)
  return True, "turn %d authored %d option(s): %s" % (walking[0]["i"], len(opts), labels)


_PATCH_RENT = ("monthly_rent_expense",)
_PATCH_PAYROLL = ("payroll_adjustment", "baseline_payroll_year1", "current_payroll")


def _option_fields(o):
  out = set()
  for fp in ((o or {}).get("patch") or {}).get("fields") or []:
    out.add(str((fp or {}).get("field") or ""))
  return out


def w2_refusal_binds(rec):
  """After 'the lease is signed... not cutting the crews': rent and payroll are
  client floors, and no round offered afterwards carries an option that
  writes rent or payroll."""
  t = rec.turn_of("walk_refuse")
  if t is None:
    return None, "the refusal was never sent"
  # both floors must be in force by the next offer after the refusal: the
  # router and the author each read the refusal, and one read can land one
  # of two refusals a turn late (run 8) - the guarantee that matters is that
  # nothing offered afterwards touches either
  landed_at = None
  for x in rec.turns:
    if x["i"] < t["i"]:
      continue
    fl = _coh(x["snap"]).get("client_floors") or {}
    if fl.get("rent") and fl.get("payroll"):
      landed_at = x["i"]
      break
  st = _coh(t["snap"])
  floors = st.get("client_floors") or {}
  if landed_at is None or landed_at > t["i"] + 1:
    return False, "floors after the refusal: %s; both rent and payroll never landed within a turn" % floors
  lag = " (the crews floor landed one turn late)" if landed_at > t["i"] else ""
  later = [x for x in rec.turns if x["i"] >= t["i"]]
  bad = []
  for x in later:
    for o in (_coh(x["snap"]).get("round") or {}).get("options") or []:
      f = _option_fields(o)
      if f & set(_PATCH_RENT) or f & set(_PATCH_PAYROLL):
        bad.append("turn %d option %s writes %s" % (x["i"], o.get("id"), sorted(f)))
  if bad:
    return False, "; ".join(bad[:4])
  offered = sum(len((_coh(x["snap"]).get("round") or {}).get("options") or []) for x in later)
  return True, "floors rent and payroll held%s; %d option(s) offered afterwards, none writes rent or payroll" % (lag, offered)


def w3_pick_applies_a_lever(rec):
  """'Option 1.' is applied by code against a named lever: a lever write is
  recorded and the open gap moved."""
  t = rec.turn_of("walk_pick")
  if t is None:
    return None, "no option was picked"
  before = next((x for x in rec.turns if x["i"] == t["i"] - 1), None)
  gap_before = num(_coh(before["snap"]).get("gap_open")) if before else None
  st = _coh(t["snap"])
  writes = st.get("_lever_writes") or {}
  gap_after = num(st.get("gap_open"))
  if not writes:
    return False, "no lever write recorded after the pick (gap %s -> %s, status %s)" % (gap_before, gap_after, st.get("status"))
  moved = gap_before is not None and gap_after is not None and gap_after < gap_before - 0.5
  detail = "wrote %s; gap %s -> %s; status %s" % (
    "; ".join("%s %s->%s" % (k, (v or {}).get("from"), (v or {}).get("to")) for k, v in writes.items()),
    gap_before, gap_after, st.get("status"))
  return (True, detail) if (moved or st.get("status") == "converged") else (False, "gap did not move: " + detail)


_LEVER_ID = re.compile(r"(?<![a-z])(gna|cogs|owner_draw|hire_timing|_d\d\d)(?![a-z])")


def w4_options_read_plain(rec):
  """Every authored option carries a plain label, a why with no lever id, and
  the engine's closure; the message shows the closure."""
  seen = 0
  for t in rec.turns:
    rnd = _coh(t["snap"]).get("round") or {}
    if rnd.get("key") != "authored":
      continue
    for o in rnd.get("options") or []:
      seen += 1
      if not o.get("label") or not o.get("why") or not o.get("closes_display"):
        return False, "turn %d option %s lacks label/why/closure" % (t["i"], o.get("id"))
      if _LEVER_ID.search(str(o.get("why"))) or _LEVER_ID.search(str(o.get("label"))):
        return False, "turn %d option %s shows a lever id: %r" % (t["i"], o.get("id"), o.get("why"))
    if not re.search(r"(?i)(option \d|\d\))", t["reply"]):
      continue   # a park or a hold: the round is stored but nothing was offered this turn
    if not re.search(r"clos(e|es|ing) about \**\$[\d,]+", t["reply"], re.I):   # the naturaliser may bold the figure
      return False, "turn %d offered a round but the message shows no closure" % t["i"]
  if not seen:
    return None, "no authored option offered"
  return True, "%d authored option(s), each with a plain label, why and closure" % seen


def w5_numbers_clear_and_intake_completes(rec):
  if not rec.completed:
    return None, "intake not completed (final status %s)" % _coh(rec.final).get("status")
  st = _coh(rec.final)
  if st.get("status") != "converged":
    return False, "completed with coherence status %r" % st.get("status")
  last = rec.turns[-1]["reply"].lower()
  if "clear every structural test" not in last:
    return False, "completed without the readback"
  return True, "converged after %d walk turn(s); readback appended" % len(_walk_turns(rec))


def _guard_actions(snap):
  return (((snap or {}).get("fin") or {}).get("_guard") or {}).get("actions") or []


def g1_the_van_lease_never_reaches_rent(rec):
  """TRAP 1 (Nick 2026-09-12): 'The van lease never reaches rent.' The guard
  rewrites the patch before the write, and the reply says why in the
  client's words."""
  t = rec.turn_of("lease")
  if t is None:
    return None, "the lease line was never sent"
  rent = num(((t["snap"] or {}).get("fin") or {}).get("monthly_rent_expense"))
  if rent is None or abs(rent - 2600.0) > 0.005:
    return False, "after the lease line rent is %s (want 2,600 - run 1 wrote 2,400 onto it)" % rent
  later = [x for x in rec.turns if x["i"] >= t["i"]]
  for x in later:
    r2 = num(((x["snap"] or {}).get("fin") or {}).get("monthly_rent_expense"))
    if r2 is not None and abs(r2 - 2600.0) > 0.005:
      return False, "rent moved to %s at turn %d after the lease line" % (r2, x["i"])
  reply = t["reply"].lower()
  said_why = ("van" in reply or "lease" in reply) and ("rent" in reply)
  acted = any(a.get("action") == "rewrote_patch" and "rent" in str(a.get("field") or "") for a in _guard_actions(t["snap"]))
  if not acted and not said_why:
    return False, "rent held at 2,600 but neither a guard rewrite nor a receipt in the client's words is on record - was the router simply right this time?"
  return True, "rent stayed at 2,600; %s" % ("the guard rewrote the patch and the reply says why" if acted else "the reply says why")


def g2_the_stated_marketing_is_the_figure_the_plan_uses(rec):
  """TRAP 2: the client said $6,000 a year; the total the engine reads is
  6,000 from that turn on, and no reply claims another marketing figure."""
  t = rec.turn_of("marketing")
  if t is None:
    return None, "marketing was never stated"
  for x in rec.turns:
    if x["i"] < t["i"]:
      continue
    fin = (x["snap"] or {}).get("fin") or {}
    tot = num(fin.get("marketing_total_year1"))
    if tot is not None and abs(tot - 6000.0) > 0.005:
      return False, "marketing_total_year1 is %s at turn %d (stated 6,000)" % (tot, x["i"])
  return True, "marketing_total_year1 held at 6,000 from the turn it was stated"


def g3_no_reply_contradicts_the_store(rec):
  """TRAP 3 (door B): every figure a reply claims as recorded is in the
  store as it stood after that turn, and the closing receipt lists what
  the walk moved - never 'nothing moved' against real writes."""
  from client_intake_and_finmo.intake_guard.door_b import find_disagreements
  bad = []
  for x in rec.turns:
    snap = x["snap"] or {}
    store = {"financials": snap.get("fin") or {}, "ops": snap.get("ops") or {}, "people": snap.get("people") or {}}
    writes = ((snap.get("fin") or {}).get("_coherence") or {}).get("_lever_writes")
    for d in find_disagreements(x["reply"], store, writes):
      bad.append("turn %d %s: %s" % (x["i"], d.get("kind"), str(d.get("sentence"))[:80]))
  if bad:
    return False, "; ".join(bad[:5])
  if not rec.completed:
    return None, "intake not completed"
  last = rec.turns[-1]["reply"]
  if "levers moved" not in last and "Nothing you told me was moved" not in last:
    return False, "the closing reply carries no receipt of what the walk moved"
  return True, "no reply contradicted the store across %d turns; the closing receipt names what moved" % len(rec.turns)


PERSONAS["walk"] = {
  "about": "Northgate's shape losing a little: the walk opens, the client refuses rent and the crews in plain words, picks option 1 until the numbers clear",
  "bootstrap": WALK_BOOTSTRAP,
  "facts": WALK_FACTS,
  "brief": (
    "You are Tamsin Ferrier, sole owner of Brightwater Office Services in St. Paul, operating since April "
    "2018, a single-member LLC. One service: recurring evening office cleaning under monthly contracts, about "
    "$1,200 per client site per month; capacity about 40 sites a month, 34 under contract (85 percent). "
    "Clients are offices, clinics and small property managers in St. Paul and the east-metro suburbs. You pay "
    "yourself $6,500 a month; Luis Ortega, crew supervisor, earns $54,000 a year; eight part-time cleaners cost "
    "about $176,000 a year - ten people. Revenue about $490,000 a year; supplies about 6 percent of revenue; "
    "marketing $6,000 a year; rent $2,600 a month on a three-year lease signed last spring; other bills about "
    "$14,500 a month (three van leases at $2,400 together, insurance, a subcontracted floor-care crew, vehicle "
    "running costs, software, phones); equipment worth $20,000; the vans are leased month-to-month with nothing "
    "owed on them; $18,000 left on "
    "an equipment loan at $650 a month (about "
    "$1,100 interest and $6,700 principal a year); $60,000 invested; $35,000 in the bank; clients owe about "
    "$41,000; $4,000 of supplier bills; $3,000 of supplies. The business loses a little money and you want it to "
    "make some. If the consultant offers options to close a gap: the lease is signed, so rent cannot move, and you "
    "will not cut the crews; otherwise take the first option. Answer in one to three short sentences - only "
    "what is asked. If a question is outside these facts, answer plausibly and briefly and do not invent new "
    "dollar figures."
  ),
  "rules": WALK_RULES,
  "checks": [
    U1,
    U3,
    U4,
    ("W1", "the first round the walk offers is authored by the agent, not the legacy planner", w1_first_round_is_authored),
    ("W2", "a refusal in plain words binds: rent and the crews are floors and no later option writes them", w2_refusal_binds),
    ("W3", "'Option 1.' is applied by code against a named lever and the gap moves", w3_pick_applies_a_lever),
    ("W4", "every authored option reads plain: label, why with no lever id, and the engine's closure", w4_options_read_plain),
    ("W5", "the numbers clear, the intake completes, the readback is appended", w5_numbers_clear_and_intake_completes),
    ("G1", "the van lease never reaches rent, and the reply says why in the client's words", g1_the_van_lease_never_reaches_rent),
    ("G2", "the stated marketing figure is the figure the plan uses", g2_the_stated_marketing_is_the_figure_the_plan_uses),
    ("G3", "no reply contradicts the store; the closing receipt names what the walk moved", g3_no_reply_contradicts_the_store),
    ("U2", "every stated payroll figure stored exactly", u2_stated_figures_exact),
  ],
}
