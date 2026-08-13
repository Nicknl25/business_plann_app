"""A6 part 2: reconstruct per-turn gap sequences from draft transcripts
(messages_json) — the walk narrates the open gap every round question and
the ack narrates each closure > $0.50.  Look for any adjacent gap move
smaller than $0.50/quarter."""
import json
import re
import mysql.connector

conn = mysql.connector.connect(host="localhost", user="root",
                               password="Lovers251979!", database="biz_plan_revert",
                               autocommit=True)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT draft_id, business_name, messages_json FROM intake_consult_drafts "
    "WHERE messages_json LIKE '%work on paper%'"
)
rows = cur.fetchall()
print("drafts with coherence-walk phrasing in transcript:", len(rows))

pat = re.compile(
    r"closing a \$([0-9,]+) a quarter gap"
    r"|\$([0-9,]+) a quarter (?:still open|is what)"
    r"|\$([0-9,]+) to go"
    r"|gap just closed by \$([0-9,]+)"
)
small_moves = 0
for r in rows:
    try:
        msgs = json.loads(r["messages_json"] or "[]")
    except Exception:
        continue
    seq = []
    for m in msgs if isinstance(msgs, list) else []:
        txt = (m.get("content") or m.get("text") or "") if isinstance(m, dict) else str(m)
        for mm in pat.finditer(txt):
            idx = [g is not None for g in mm.groups()].index(True)
            kind = ["closing", "left", "togo", "closedby"][idx]
            val = float(mm.group(idx + 1).replace(",", ""))
            seq.append((kind, val))
    if not seq:
        continue
    # open-gap sequence = closing/left/togo entries in order
    opens = [v for k, v in seq if k != "closedby"]
    moves = [opens[i] - opens[i + 1] for i in range(len(opens) - 1) if opens[i] != opens[i + 1]]
    tiny = [mv for mv in moves if 0 < abs(mv) < 0.5]
    if tiny:
        small_moves += 1
    print(f"{r['business_name'][:35]:35s} {r['draft_id'][:12]} seq={seq[:12]}"
          + (f"  TINY MOVES {tiny}" if tiny else ""))
print("\ndrafts with an observed gap move < $0.50/q:", small_moves)
cur.close(); conn.close()
