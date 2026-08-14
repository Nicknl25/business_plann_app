# HANDOFF INBOX — plain English only. The WATCHER seeds the task and flips
# STATUS itself. Nick never edits HANDOFF.md, STATUS, config, or code.

mini: TURN-TIMEOUT-MINUTES: 240

NICK RATIFIES THE DRIFT — but re-baselining is CONDITIONAL on a purity
proof, and the proof is the point. His words:

The DRIFT is EXPECTED. R31:single-line-golden-moved-by-ruled-depreciation
moved because the depreciation fix Nick RULED (opening PPE now gets the
5-year straight-line schedule) changes the numbers for every business
with opening assets, including single-line ones (Sunny carries 20k).
That is not a regression — it is the golden-master correctly catching a
real change which happens to be the ordered one. The floor did its job:
flagged a moved negative control and stopped. Nick confirms the move was
intended.

YOUR TASK, in order:
1. VERIFY THE DRIFT IS PURE before touching any baseline. Structurally
   diff the moved single-line digests (old vs new finmo_json and
   model_input_json): EVERY changed leaf must trace to the depreciation
   schedule now applying to opening PPE — the depreciation expense rows,
   accumulated depreciation, PPE roll-forward, and their arithmetic
   descendants (net income, taxes, retained earnings, cash, totals).
   ZERO changes from anything else. Expected-drift can MASK a real one —
   that is why this verification exists. Do not re-bless on Nick's word
   alone; his word covers WHY the numbers moved, your diff proves ONLY
   those numbers moved.
2. IF the diff is 100% depreciation-attributable: re-bless R31's golden
   baseline to the new post-depreciation values, re-baseline the
   byte-floor goldens the same way, and re-point the layout legs (R32's
   old per-line-P&L expectation is overruled by Nick's Model-Inputs
   layout ruling — the assertion is four drivers on Model Inputs + ONE
   P&L roll-up cell). Then run the full prove IN THE FOREGROUND and read
   it in the same turn.
3. IF ANY leaf moved for a reason OTHER than depreciation: STOP. Do not
   re-baseline anything. VERDICT: drift again, with the impure leaves
   named precisely — that is a real regression hiding under the expected
   one, and Nick looks at it before anything gets blessed.

Evidence base: VS turn-1 commits e26af21..5716ba4, the prove output from
VS's turn, _live_cw032_instage_cogs_turn.py, the VS_NOTES CW-032 batch
section. All standing laws hold (foreground-only long jobs; artifact
level; a clean table after re-baseline = VERDICT green so the watcher
stops for Nick's blessing).
