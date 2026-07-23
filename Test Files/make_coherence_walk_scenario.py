"""Author the coherence-walk E2E control file: an early-stage urban
mushroom farm whose STATED configuration clearly fails the structural
checks (mature-quarter EBITDA negative under any judgment) but whose
believable corner should pass — so the coherence walk triggers and can
converge. Modeled on the Understory fleet case; new workbook so the
user's scenario file is untouched."""
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).resolve().parent / "Coherence Walk Scenario.xlsx"

wb = Workbook()
ws = wb.active
ws.title = "Understory Redux (Walk)"

rows = [
    ("Scenario",
     "Test an early-stage urban gourmet mushroom farm about eight months into operating, "
     "run by a hands-on founder. It sells fresh specialty mushrooms wholesale to restaurants "
     "and grow-kits direct to consumers - two separate lines. The founder is candid that costs "
     "are heavy right now (marketing spend to build accounts, generous overhead) and prices were "
     "set low to win early customers. The founder is open-minded and decisive: when the consultant "
     "presents options with concrete numbers, pick the one that is marked suggested or otherwise "
     "the middle option, in your own words - never repeat wording verbatim, answer naturally. "
     "If asked to choose how to close a viability gap, engage constructively and decide."),
    ("Business name", "Understory Redux Mushroom Co."),
    ("Business address", "4460 W Vernor Hwy, Detroit, MI 48209, USA"),
    ("Business start date", "11/15/2025"),
    ("", ""),
    ("Controlled answers", ""),
    ("Line structure", "Two lines of business tracked separately: (1) Fresh Gourmet Mushrooms sold wholesale to restaurants, (2) Retail Grow Kits sold direct to consumers."),
    ("Customer type", "Mixed - restaurants (b2b) for fresh mushrooms, consumers for grow kits."),
    ("Fresh - unit definition", "For fresh mushrooms, one unit is one pound of mushrooms."),
    ("Fresh - cadence", "Monthly - capacity is pounds we can grow and sell per month."),
    ("Fresh - capacity", "About 3,000 pounds per month at full build-out."),
    ("Fresh - utilization", "Use 55% utilization - that is where we really are; insist on 55% if another number is proposed."),
    ("Fresh - price", "About $12 per pound wholesale."),
    ("Kits - unit definition", "For grow kits, one unit is one kit."),
    ("Kits - cadence", "Monthly - kits shipped per month."),
    ("Kits - capacity", "About 400 kits per month."),
    ("Kits - utilization", "Use 45% utilization on kits - insist on 45%."),
    ("Kits - price", "$28 per kit."),
    ("Revenue", "Right now the business brings in about $298,000 a year across both lines."),
    ("COGS", "Direct costs run about 35% of revenue - substrate, spawn, packaging, shipping."),
    ("Team", "Besides the founder Mara Ellison (who takes $42,000 a year), there are three people: Devon (grow lead, $36,000), Priya (sales and deliveries, $34,000), and Cole (part-time packer, $18,000)."),
    ("Owner compensation", "Mara's pay is the $42,000 already mentioned - no separate draw."),
    ("Rent", "The warehouse is $6,500 a month."),
    ("Other operating expenses", "Utilities, insurance, software and the rest run about $8,000 a month - power for climate control is heavy."),
    ("Marketing", "We spend about $40,000 a year on marketing - farmers market fees, ads, samples for chefs. It has been our main growth push."),
    ("Cash on hand", "About $8,000 in the bank."),
    ("Initial equity / investment", "I put in about $45,000 of equipment and improvements to get started; no outside investors yet."),
    ("Debt", "No debt outstanding."),
    ("Capex", "Recently spent about $12,000 on additional grow racks."),
    ("Funding preference", "Prefer equity - my own money plus maybe an investor later; not keen on loans."),
    ("Cash strategy", "Reinvest extra cash into growing the business."),
    ("Milestone", "Within 12 months: land 15 standing restaurant accounts."),
    ("Coherence conduct", "If the consultant shows that the plan does not work yet and offers levers with numbers (pricing, new lines, cost floors), engage seriously: pick the suggested option for pricing in your own words; accept cost right-sizing if offered; you may decline brand-new business lines this round. Do not argue that the plan is fine - the goal is to land a plan that works."),
]

for label, content in rows:
    ws.append([label, content])

ws.column_dimensions["A"].width = 28
ws.column_dimensions["B"].width = 120

wb.save(str(OUT))
print("wrote", OUT)
