"""Probe: where does the discovered row's utilization come from? Full
assistant texts + per-turn ops row dump. Same clone recipe as
_live_stream_discovery_clones.py (rich), stops after the price answer."""
from __future__ import annotations
import json, sys, importlib.util
from pathlib import Path
from dotenv import load_dotenv
REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("clones", REPO_ROOT / "Test Files" / "_live_stream_discovery_clones.py")
clones = importlib.util.module_from_spec(spec); spec.loader.exec_module(clones)

def row(ops):
  for l in ops.get("lob_models") or []:
    for p in l.get("products") or []:
      if p.get("origin") == "discovery_confirmed":
        return p
  return None

def main():
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python")); sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection
  conn = get_mysql_connection()
  cid, kid, _ = clones.make_clone(conn, "sdprob")
  try:
    st, reply, _ = clones.post_turn(cid, kid, clones.GROWTH_LEVER_ANSWER)
    print("T1 <", reply); ops = clones.read_ops(conn, cid)
    latch = ops.get("stream_discovery") or {}
    tries = 0
    while not latch.get("asked") and "asked" not in latch and tries < 3:
      # the model asked its own last question first (GPT variance) - answer it
      tries += 1
      st, reply, _ = clones.post_turn(cid, kid, "Our edge is the integrated design-to-install flow and growing our own perennials.")
      print(f"T1+{tries} <", reply); ops = clones.read_ops(conn, cid)
      latch = ops.get("stream_discovery") or {}
    if not latch.get("asked"):
      print("no ask; latch:", json.dumps(latch)); return
    first = latch["candidates"][0]["label"]
    for ans in (f"Yes, {first} is part of it. The others no.",
                f"About 3 {first} jobs a week at full stretch.",
                f"About $400 per {first} job."):
      st, reply, _ = clones.post_turn(cid, kid, ans)
      print("\n>", ans); print("<", reply)
      ops = clones.read_ops(conn, cid)
      print("ROW:", json.dumps(row(ops)))
      if "competitive advantage" in reply.lower():
        break
    cur = conn.cursor(); conn.commit()
    cur.execute("SELECT messages_json FROM intake_consult_drafts WHERE draft_id=%s", (cid,))
    msgs = json.loads(cur.fetchone()[0])
    print("\nFULL TAIL OF TRANSCRIPT:")
    for m in msgs[31:]:
      print(f"[{m['role']}] {m['content']}\n")
  finally:
    clones.cleanup(conn, cid)

if __name__ == "__main__":
  main()
