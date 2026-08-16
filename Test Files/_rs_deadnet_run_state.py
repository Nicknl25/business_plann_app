"""Snapshot a draft's run-level artifacts for the dead-net E2E (before/after)."""
import os, sys, json
from dotenv import load_dotenv; import mysql.connector; load_dotenv()
prefix = sys.argv[1]
c = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"), password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True)
cur = c.cursor(dictionary=True)
cur.execute("SELECT draft_id, planning_run_id, planning_run_status, planning_failure_reason, updated_at, repair_guidance_json, planning_run_json FROM intake_consult_drafts WHERE draft_id LIKE %s", (prefix + "%",))
row = cur.fetchone()
did = row["draft_id"]
print("draft", did, "| planning_run_id", row["planning_run_id"], "| planning_run_status", row["planning_run_status"], "| failure", row["planning_failure_reason"], "| updated", row["updated_at"])
pr = json.loads(row["planning_run_json"] or "{}")
print("planning_run_json: run_status", pr.get("run_status"), "stage", pr.get("stage"), "failure_reason", pr.get("failure_reason"))
rg = json.loads(row["repair_guidance_json"] or "{}").get("restructure") or {}
print("repair_guidance.restructure: final_passed", rg.get("final_passed"), "dead_net", rg.get("dead_net"), "attempt_wb", rg.get("attempt_workbook_path"))
for h in rg.get("history") or []:
  print("  ", h.get("stage"), "found", h.get("found"), "evals", h.get("evals"), "dead_net", h.get("dead_net"), "verdict_after", h.get("verdict_after"), ("review approved " + str((h.get("review") or {}).get("approved"))) if h.get("stage","").startswith("review") else "")
  for t in (h.get("trace") or [])[:12]:
    print("      ", str(t)[:200])
cur.execute("SELECT planning_run_id, run_status, failure_reason, completed_at, created_at, acceptance_verdict_json FROM planning_runs WHERE draft_id=%s ORDER BY created_at DESC LIMIT 4", (did,))
for r in cur.fetchall():
  v = json.loads(r.pop("acceptance_verdict_json") or "{}")
  print("planning_runs:", r, "| verdict passed", v.get("passed"), "failed_checks", v.get("failed_checks"), "score", v.get("score"))
cur.execute("SELECT planning_run_id, acceptance_passed, acceptance_score, diagnostics_json, created_at FROM post_intake_run_diagnostics WHERE draft_id=%s ORDER BY created_at DESC LIMIT 4", (did,))
for r in cur.fetchall():
  dj = json.loads(r.pop("diagnostics_json") or "{}")
  print("diagnostics:", r, "| label", dj.get("acceptance_score_label"), "| failure_exception_class", dj.get("failure_exception_class"), "| failure_detail", str(dj.get("failure_detail") or "")[:160])
