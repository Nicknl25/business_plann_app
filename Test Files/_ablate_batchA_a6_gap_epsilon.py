"""A6: section.py:1099 epsilon — `if prev_gap is not None and gap < prev_gap - 0.5`.
Consumers (from code read): (1) the 'that moved the plan' ack sentence,
(2) rounds_done advancement — the active round is only marked done when the
gap closed by MORE than $0.50/q.  Question: did any real walk ever move a
gap by less than $0.50/q?  Scan every draft for coherence state and any
per-turn gap history in repair_guidance_json / planning_convergence_json."""
import json
import mysql.connector

conn = mysql.connector.connect(host="localhost", user="root",
                               password="Lovers251979!", database="biz_plan_revert",
                               autocommit=True)
cur = conn.cursor(dictionary=True)


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


cur.execute(
    "SELECT draft_id, business_name, financials_json, repair_guidance_json, "
    "planning_convergence_json, updated_at FROM intake_consult_drafts "
    "WHERE financials_json LIKE '%_coherence%' OR repair_guidance_json LIKE '%coherence%'"
)
rows = cur.fetchall()
print(f"drafts with any coherence trace: {len(rows)}")
n_hist = 0
for r in rows:
    fin = _j(r.get("financials_json"))
    st = fin.get("_coherence") or {}
    rg = _j(r.get("repair_guidance_json"))
    pc = _j(r.get("planning_convergence_json"))
    rg_coh = rg.get("coherence") if isinstance(rg, dict) else None
    interesting = st.get("status") in ("walking", "converged", "parked", "roadmap")
    if not (interesting or rg_coh):
        continue
    print(f"- {r['business_name'][:40]:40s} {r['draft_id'][:12]} status={st.get('status')} "
          f"gap_open={st.get('gap_open')} gap_initial={st.get('gap_initial')} "
          f"rounds_done={st.get('rounds_done')} has_round={'round' in st} "
          f"rg_coherence_keys={sorted(rg_coh.keys()) if isinstance(rg_coh, dict) else rg_coh}")
    # any list-shaped gap history anywhere?
    for label, blob in (("state", st), ("repair_guidance.coherence", rg_coh or {}),
                        ("planning_convergence", pc)):
        s = json.dumps(blob)
        if '"gap' in s:
            import re
            gaps = re.findall(r'"gap[a-z_]*":\s*([0-9.]+)', s)
            if len(gaps) > 1:
                n_hist += 1
                print(f"    {label} gap values: {gaps}")
print(f"\nblobs with >1 gap value: {n_hist}")
print("NOTE: state stores only gap_open (current) + gap_initial — no per-turn")
print("history is persisted anywhere in the draft row; per-turn gap sequence")
print("would only exist in conversation transcripts.")

# transcripts: look for the ack sentence which only fires when the epsilon
# test passes, and for repeated round questions (epsilon suppressing acks)
cur.execute("SHOW TABLES")
tables = [list(t.values())[0] for t in cur.fetchall()]
cands = [t for t in tables if "transcript" in t.lower() or "message" in t.lower() or "turn" in t.lower()]
print("\ntranscript-ish tables:", cands)
for t in cands:
    try:
        cur.execute(f"SELECT COUNT(*) c FROM {t}")
        print(f"  {t}: {cur.fetchone()['c']} rows")
    except Exception as e:
        print(f"  {t}: ERR {e}")
cur.close(); conn.close()
