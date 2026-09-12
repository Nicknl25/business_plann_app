"""Replay the intake watcher over a finished draft's transcript.

  python scripts/intake_watch_replay.py --draft 3d57edc6 [--no-model] [--json out.json]

What this can and cannot do, honestly: a finished draft holds its FINAL
store, not the store after every turn. So the transcript-based checks
(repeated replies, loops, raw field names, the client's stated figures
against the final store) and the model read (with the final floors and
options, and an empty per-turn diff) run on every turn exactly as they
would have; the store-DIFF checks (a value moved without cause, a refusal
violated by a move, a unit copied on this turn) can only fire live, when
the watcher sees each turn's before and after. The live watcher runs on
every persisted turn; this script is for reading what it would have said
about a transcript that already happened.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from client_intake_and_finmo.intake_submission import get_mysql_connection  # noqa: E402
from client_intake_and_finmo.intake_consult_draft import get_draft  # noqa: E402
from client_intake_and_finmo.intake_watcher.observe import MemoryStore, observe_draft_turn, snapshot_from_draft  # noqa: E402


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--draft", required=True, help="draft id or its first 8 characters")
  ap.add_argument("--no-model", action="store_true", help="checks only, no GPT read")
  ap.add_argument("--json", default="", help="write observations to this file")
  args = ap.parse_args()

  conn = get_mysql_connection()
  cur = conn.cursor()
  cur.execute("SELECT draft_id FROM intake_consult_drafts WHERE draft_id LIKE %s", (args.draft.strip() + "%",))
  rows = cur.fetchall()
  cur.close()
  if len(rows) != 1:
    print(f"no single draft matches {args.draft!r} ({len(rows)} rows)")
    return 2
  draft = get_draft(conn, draft_id=rows[0][0]) or {}
  conn.close()
  msgs = draft.get("messages_json") or []
  if isinstance(msgs, str):
    msgs = json.loads(msgs or "[]")
  msgs = [m for m in msgs if isinstance(m, dict)]
  final = snapshot_from_draft(draft)

  store = MemoryStore()
  # seed the snapshot with the FINAL store so per-turn diffs are empty (see docstring)
  store.save_snapshot(str(draft.get("draft_id")), 0, final)
  all_obs = []
  print(f"replaying {draft.get('business_name')} ({str(draft.get('draft_id'))[:8]}), {len(msgs)} messages, model={'off' if args.no_model else 'on'}")
  for i in range(len(msgs)):
    if msgs[i].get("role") != "assistant":
      continue
    partial = dict(draft)
    partial["messages_json"] = msgs[: i + 1]
    obs = observe_draft_turn(draft=partial, store=store, run_model=not args.no_model)
    for o in obs:
      all_obs.append(o)
      print(f"  turn {i:>3}  [{o.get('severity')}] {o.get('kind')}  {o.get('field') or ''}  - {str(o.get('why') or '')[:150]}")
  print(f"observations: {len(all_obs)}")
  if args.json:
    with open(args.json, "w", encoding="utf-8") as fh:
      json.dump(all_obs, fh, ensure_ascii=False, indent=1, default=str)
    print("written", args.json)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
