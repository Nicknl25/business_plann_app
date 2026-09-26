"""ONE MOUTH - the material the consultant carries in its own sentence.

Nick 2026-09-25: "The LLM talks. Not the machine. NOTHING IS APPENDED TO THE
MODEL'S REPLY. Not a receipt, not a note, not a correction, not a 'couldn't
apply that'. Ever. What the code wants to say goes INTO the consultant call
as material and the model writes one sentence that carries it."

Every manners defect a client ever saw was the same move - a clean sentence
with a machine parenthetical stapled to the end:

    "(Adjusted while finalizing: income min -> 75,000; income max -> 999,999.)"
    "(One note: I haven't recorded baseline cogs, cogs basis naics ... yet.)"
    "(Noted: weekly capacity -> 12 (624 a year); utilization -> 75.0%.)"

The code still decides WHAT happened. It stops writing the sentence.

THE MODEL NEVER SEES A FIELD NAME. Entries carry `about` in plain English,
already the words to use. A fact with no English label never becomes material
at all (api_handlers.intake_consult._client_label returns None and the entry
is dropped), because given the key the model will say the key.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

MATERIAL_KEY = "turn_material"
INSTRUCTION_KEY = "how_to_say_what_the_app_did"

MATERIAL_INSTRUCTION = """
WHAT THE APP DID THIS TURN (intake_context.turn_material)
- turn_material, when present, is what the app decided and recorded on this
  turn. You are the only one who speaks to the client; the app never adds a
  line of its own after yours.
- Carry EVERY entry inside your own sentence, the way a consultant would say
  it out loud. Never as a list, a bracket, a parenthetical aside, a "(Noted:
  ...)" or any note appended after your reply.
- `about` is already plain English and is the wording to use. Never turn it
  into a field name, a key, a column heading or an internal term, and never
  invent a name for an entry that has no `about`.
- `kind` tells you what happened:
    landed        - you recorded this value; say it back naturally
    not_landed    - the change did not apply; say so plainly, no blame, and
                    invite the correction
    still_needed  - not captured yet; only mention it if it is this turn's
                    question, otherwise stay quiet about it
    corrected     - you adjusted what was captured; say what it now is
    held          - something is open and the turn waits on the client
    adjusted      - a value was reshaped while finalizing; say what it is now
    noted         - context to weave in only if it helps the client
- A value with no `about` is context for you, not something to read out.
- If material and your own question would make the reply long, lead with the
  material in one clause and ask the question in the next sentence.
""".strip()


def context_with_material(intake_context: Optional[Dict[str, Any]],
                          material: Optional[List[Dict[str, Any]]],
                          ) -> Dict[str, Any]:
  """A copy of the consultant's context carrying this turn's material.

  Absent or empty material leaves the context untouched, so a turn with
  nothing to say reads exactly as it did before.
  """
  ctx = dict(intake_context or {})
  cleaned = [e for e in (material or []) if isinstance(e, dict) and e.get("kind")]
  if cleaned:
    # The instruction travels WITH the material, inside the context the call
    # already serialises. Appending it to the prompt blob instead would have
    # reached four finalize calls that emit strict-schema JSON and want no
    # sentence at all, and would have put prose under a "(JSON)" label.
    ctx[MATERIAL_KEY] = cleaned
    ctx[INSTRUCTION_KEY] = MATERIAL_INSTRUCTION
  else:
    ctx.pop(MATERIAL_KEY, None)
    ctx.pop(INSTRUCTION_KEY, None)
  return ctx


def has_material(intake_context: Optional[Dict[str, Any]]) -> bool:
  return bool((intake_context or {}).get(MATERIAL_KEY))


def describe(material: Optional[List[Dict[str, Any]]]) -> str:
  """For logs and audit rows - never for a client."""
  return json.dumps(material or [], ensure_ascii=False)[:2000]
