# HANDOFF INBOX — plain English only. The WATCHER seeds the task and flips
# STATUS itself. Nick never edits HANDOFF.md, STATUS, config, or code.

TURN-TIMEOUT-MINUTES: 240

CW-032 ALDERFEN BATCH (Nick, 2026-08-14) — the full 8-item CW-031/032
issues list, ONE loop batch, BLOCKERS FIRST, artifact-level verification
throughout (the false-green class came from proposal-level checking —
never repeat it). Evidence base: draft 158f6816, run 414a3b0a, workbook
"Alderfen Nursery and Garden -- 08-13-2026 23-13-03.xlsx", the three
registry filings, VS_NOTES CW-032 sections.

THE COGS BREAKOUT — CORRECT LAYOUT (Nick's ruling, hold to it exactly):
- MODEL INPUTS sheet: FOUR per-line COGS DRIVERS, one row per line
  (plant %, hardgoods %, install %, design %). These are the source
  assumption cells.
- P&L (FINMO) sheet: ONE COGS line — the total — computed as
  Sigma(each line's revenue x that line's COGS driver from Model
  Inputs). One consolidated line on the P&L, driven by the four
  Model-Inputs drivers.
NOTE FOR VS — THIS IS A LAYOUT CHANGE: the current finmo_sheet.py
inserts per-line COGS rows INTO THE P&L with the total as =SUM over
them. Nick rules the breakout lives on Model Inputs; the P&L stays
clean with ONE COGS line whose formula rolls up the four drivers
(line revenue x line driver, summed in the one cell). Move it.

HARD RULE — ALL-OR-NOTHING, CLEAN OR NOT AT ALL (Nick): if it cannot
be set up correctly (four drivers on Model Inputs AND a P&L COGS line
that PROVABLY sums them), then DO NOT do it — fall back to the single
blended rate. A half-built breakout (drivers that do not tie to the
P&L line, or a partial that ships broken) is WORSE than the clean
blend, because it shows the client detail that does not reconcile.
Fully correct, or the single blend. No half-state, no silent
degradation. The existing all-or-nothing enforcement
(intake_consult.py ~:8803 + the bridge activation rule) IS this
guarantee — route ALL FOUR lines; if any fails, it correctly falls to
blend. DO NOT WEAKEN ALL-OR-NOTHING.

TIER 1 — THE THREE BLOCKERS ARE ONE ROOT (A-110):
The downstream is already built and correct
(_reconcile_per_line_cogs_rows, the bridge per-line emit,
_apply_per_line_cogs_to_ops the complete writer) — they are STARVED
because a client COGS/collapse sentence in the STAGE never becomes a
financials.cogs_per_line_overrides patch. FIX = ONE ROUTER CHANGE:
route the client's per-line COGS sentence AND the collapse sentence
into the patch, IN-STAGE (the surface where the proposal is made and
correction invited). This closes corrections-write, the four
Model-Inputs drivers appearing, and the collapse — together. Include
the multi-figure parse (a real owner answers "Plants are 46%.
Hardgoods 73%. Install 17%. Design 3%" in ONE message — land all N,
one turn) and fix the clarifier copy (after a per-line answer fails,
it currently asks for ONE singular blend figure — the recovery
question must preserve the per-line shape, plain English).
ARTIFACT VERIFICATION (mini): cogs_per_line_overrides non-null on all
4; FOUR COGS driver rows on the Model Inputs sheet; ONE P&L COGS line
that provably equals Sigma(line rev x line driver) per period; the
collapse stores a /shared/ key naming whose structure it shares.
Also: the stage ack must obey the receipt law — the Alderfen ack
claimed a recorded blend AND said "I haven't recorded cogs percent
yet" in the same message. Words match state, one source.

TIER 2 — A-113 CAPACITY SMEAR (rank 2, same parent law): the client's
post-stage per-line capacity correction (install 5 -> 7) was LOST, and
the build then applied a UNIFORM 1.11220 factor to EVERY line —
putting 3 lines 11.2% above what the client stated, in a plan they
read as theirs. FIX: a post-stage capacity write path that lands the
correction on the named line, OR an honest refusal — NEVER a silent
uniform smear. The app must not silently alter what the client
declared.

TIER 3 — DEPRECIATION (NO client question — the policy exists):
_CAPEX_USEFUL_LIFE_YEARS = 5.0 default and initial_assets (~$386k
opening PPE) are both present and straight-line logic is wired. BUG:
new capex depreciates, the OPENING PPE never gets the useful-life
schedule. FIX: apply the existing default 5-year straight-line
schedule to opening PPE, same as new capex. NO intake question about
asset age/life — normal owners cannot answer it and we have a sensible
default. State the assumption in the plan output ("equipment
depreciated straight-line over 5 years").

TIER 4 — THE REMAINING FILED ITEMS from the 8: the
collapse-invitation timing item and any receipt/label items still
open. Fix at source; mini artifact-verifies each.

SETTLED (Nick): SS6 is 13/13 exact, fifth consecutive — REMOVE it
from A-103's retest list.

PROCESS: blockers first. Standing laws hold (backend restart + ONE
listener after app-code edits, Sunny_V3 canary before any batch of
runs, foreground-only long jobs, red-proofs red for the right
reason). When the batch is clean + live-verified (canary + multi-line
E2E + an IN-STAGE conversation check on a fresh 4-line clone —
proposal -> full multi-line correction in one message -> all four rows
carry the client's numbers -> Model Inputs shows four drivers -> P&L
shows ONE summing line), STAGES flips per-line-COGS LIVE=passed and
COWORK clears. Nick then re-runs the garden center to SEE the four
drivers and the one summing P&L line. THEN discovery research.
