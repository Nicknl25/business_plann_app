STATUS: awaiting-mini

TURN: 0/16

TASK:
  two things, and the second is from a live client run rather than from me. FIRST, audit 2e7e177 - the three follow-ups you left me on R49, which landed AFTER your green on ac3f46f, so you have not seen them and they moved the blessed digest (91d4fa285c75 -> 4d5d81484fd8, 2,572 -> 2,575 cells). (a) your finding (3): the intersection is now surface.static_intersection at module level and the tests import it with the leg's own _DATE_TEXT; I red-proved it with your exact tamper (delete the intersection AND the filter) and it now fails 2 tests where all 8 passed before - but check whether the tests would catch a subtler break than a total deletion, because that is the standard you held the extraction to. (b) your nit: _patch_reference_constants now shifts as_of and source only when they carry a value, so the three em-dash placeholders come back as chrome; confirm those three cells are the ones you meant and that nothing else came back with them. (c) your finding (5) is documented in alt_single_line_payload rather than fixed, on your own measurement that exposure is zero - tell me if writing it down is actually the right call or if I took the cheap option. SECOND, from the Cowork run that just completed clean (draft 85f5825d, Harrow Lane Grooming, coherence converged, 0 errors, both this morning's blockers verified live - Cash Y1 == Ending Cash Y1 == 118,139 and equity 460,784 = EV 463,784 - net debt today 3,000): the client gave DISTINCT per-line COGS, 15% for a full groom and 2% for a nail trim, and the app captured both correctly and computed the right revenue-weighted blend of 14.27%. But both services sit under ONE lob_model, so cogs_percent_of_line_revenue does not appear in model_input_json at all - the model carries only the blend. No client-facing number is wrong and total COGS is exact, so I am NOT calling it a defect and I did not stop the run. The question for you is whether the per-line COGS work (WS1/WS2, #138) was meant to key on LOB or on PRODUCT, because a two-product single-LOB business is a shape the goldens may not cover - R32's leg asserts a single-line workbook has exactly one COGS row, and I do not know of a leg that asserts a two-PRODUCT one has two. If that is a real gap it is Nick's ruling, not a build.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
