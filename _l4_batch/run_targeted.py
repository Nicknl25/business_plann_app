"""P3.32 K12 Stage 1 TARGETED verification.

Re-runs ONLY the drafts that hit B2 (network_retry_exhausted) yesterday,
3 runs each, under the L-4-instrumented + compaction server. Question:
did Handler C context compaction reduce the B2 rate, and what surfaces
underneath where B2 is gone?

Own ledger/log so the K11 baseline and partial-K12 ledgers are preserved.
"""
import subprocess, sys, os, time, json, smtplib, re
from email.mime.text import MIMEText
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "python"))
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"), override=False)
from client_intake_and_finmo.intake_submission import get_mysql_connection

PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
RUNNER = os.path.join(ROOT, "Test Files", "run_persisted_system_run.py")
RUNS_PER_DRAFT = 3
PER_RUN_TIMEOUT = 600
PAUSE_BETWEEN = 6
LEDGER = os.path.join(HERE, "ledger_k12_stage1_targeted.json")
LOG = os.path.join(HERE, "batch_targeted.log")

# Only the 5 drafts that hit B2 yesterday (per K11 ledger).
DRAFTS = [
  ("Sunny Glaze Donuts", "6d37c6b98ace41ee9c91dd5fbf68b83e"),
  ("Skyward Express Airlines", "82b485233e51409ba14b1407e4fded99"),
  ("Elegant Threads Boutique", "5dcd919aae314bd5af67849172aa52bb"),
  ("ValueMart Superstores", "0d0fb60aca754e00954f402a4fdec0ab"),
  ("Pinnacle Logistics Inc.", "11d6cd0c19c3430e8aaf8916b550ea7f"),
]

ledger = {"started_at": datetime.now().isoformat(), "stage": "k12_stage1_targeted", "drafts": []}


def log(msg):
  line = "[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg)
  print(line, flush=True)
  with open(LOG, "a", encoding="utf-8") as f:
    f.write(line + "\n")


def email(subject, body):
  try:
    host = os.getenv("EMAIL_HOST"); port = int(os.getenv("EMAIL_PORT") or 587)
    user = os.getenv("EMAIL_USER"); pw = os.getenv("EMAIL_PASSWORD")
    sender = os.getenv("EMAIL_FROM") or user; to = os.getenv("EMAIL_ALERTS_ADDRESS")
    m = MIMEText(body); m["Subject"] = subject; m["From"] = sender; m["To"] = to
    with smtplib.SMTP(host, port) as s:
      s.starttls(); s.login(user, pw); s.send_message(m)
    log("emailed: " + subject)
  except Exception as e:
    log("EMAIL_FAIL %s" % e)


def classify(outcome):
  if outcome == "completed":
    return "PASS"
  o = outcome or ""
  if "network_retry_exhausted" in o or "payroll_tool_calling_session_turn_failed" in o:
    return "B2"
  if "payroll_tool_calling_session_exhausted" in o:
    return "B3"
  if "stage_ramp_revenue_path_not_applied" in o:
    return "B1"
  if "pre_cash_gate" in o:
    return "B4"
  if "stage_ramp_handler_exhausted" in o:
    return "B5"
  return "OTHER"


def hc_latencies(draft_id):
  """Handler C propose-turn latencies (ms) for a draft, from gpt_io traces."""
  try:
    conn = get_mysql_connection(); cur = conn.cursor()
    cur.execute(
      "SELECT elapsed_ms, trace_json FROM post_intake_handler_traces "
      "WHERE draft_id=%s AND handler='gpt_io' ORDER BY seq", (draft_id,))
    out = []
    for elapsed, tj in cur.fetchall():
      try:
        p = json.loads(tj).get("payload", {})
      except Exception:
        p = {}
      name = p.get("consultant_name") or ""
      if "payroll_handler_c" in name:
        out.append({"ms": elapsed, "in": (p.get("usage") or {}).get("input_tokens"),
                    "err": bool(p.get("error"))})
    cur.close(); conn.close()
    return out
  except Exception as e:
    return [{"error": str(e)[:120]}]


def trace_total(draft_id):
  try:
    conn = get_mysql_connection(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(handler='h2_exhaustion'), SUM(handler='handler_c_payroll') "
                "FROM post_intake_handler_traces WHERE draft_id=%s", (draft_id,))
    r = cur.fetchone(); cur.close(); conn.close()
    return {"total": int(r[0] or 0), "h2": int(r[1] or 0), "hc": int(r[2] or 0)}
  except Exception:
    return {"total": 0}


def run_once(source_id):
  env = dict(os.environ); env["BPLAN_TRACE_VERBOSE"] = "1"
  t0 = time.time()
  try:
    p = subprocess.run([PY, RUNNER, "--draft-id", source_id], capture_output=True,
                       text=True, timeout=PER_RUN_TIMEOUT, env=env, cwd=ROOT)
    out = (p.stdout or "") + "\n" + (p.stderr or ""); rc = p.returncode
  except subprocess.TimeoutExpired as e:
    out = (e.stdout or "") + "\n[HUNG]"; rc = -9
  dur = round(time.time() - t0, 1)
  m = re.search(r"new draft:\s*([0-9a-f]{32})", out)
  new_id = m.group(1) if m else None
  if rc == -9:
    outcome = "hung"
  elif "System run duration" in out and rc == 0:
    outcome = "completed"
  elif "ERROR:" in out:
    em = re.search(r"ERROR:\s*(.*)", out); outcome = (em.group(1)[:240] if em else "unknown")
  else:
    outcome = "failed: rc=%d" % rc
  return {"new_draft_id": new_id, "outcome": outcome, "duration_s": dur,
          "mode": classify(outcome), "traces": trace_total(new_id) if new_id else {"total": 0},
          "hc_latencies_ms": [x.get("ms") for x in hc_latencies(new_id)] if new_id else []}


def main():
  open(LOG, "w").close()
  log("TARGETED B2 VERIFICATION START: %d drafts x %d runs" % (len(DRAFTS), RUNS_PER_DRAFT))
  for di, (name, source_id) in enumerate(DRAFTS, 1):
    de = {"name": name, "source_id": source_id, "runs": []}
    for run_idx in range(1, RUNS_PER_DRAFT + 1):
      log("draft %d/%d %s | run %d/%d" % (di, len(DRAFTS), name, run_idx, RUNS_PER_DRAFT))
      res = run_once(source_id); res["run_idx"] = run_idx
      lat = [x for x in res["hc_latencies_ms"] if x]
      log("  -> %s [%s] | %ss | hc_lat_ms=%s | tr=%s" % (
        res["mode"], res["outcome"][:60], res["duration_s"], lat, res["traces"]))
      de["runs"].append(res)
      time.sleep(PAUSE_BETWEEN)
    ledger["drafts"].append(de)
    with open(LEDGER, "w", encoding="utf-8") as f:
      json.dump(ledger, f, indent=2)
    lines = ["%s -- %d runs (K12 compaction):" % (name, len(de["runs"]))]
    for r in de["runs"]:
      lat = [x for x in r["hc_latencies_ms"] if x]
      lines.append("  run %d: %s [%s] | %ss | HandlerC turn ms=%s"
                   % (r["run_idx"], r["mode"], r["outcome"][:70], r["duration_s"], lat))
    email("P3.32 K12 targeted [%d/5] %s" % (di, name), "\n".join(lines))
  ledger["finished_at"] = datetime.now().isoformat()
  with open(LEDGER, "w", encoding="utf-8") as f:
    json.dump(ledger, f, indent=2)
  # Final summary with B2-rate comparison framing.
  summ = ["P3.32 K12 STAGE 1 TARGETED VERIFICATION COMPLETE", ""]
  for d in ledger["drafts"]:
    modes = [r["mode"] for r in d["runs"]]
    b2 = modes.count("B2")
    summ.append("%-30s modes=%s  (B2=%d/%d)" % (d["name"], "/".join(modes), b2, len(modes)))
  total_b2 = sum(r["mode"] == "B2" for d in ledger["drafts"] for r in d["runs"])
  total = sum(len(d["runs"]) for d in ledger["drafts"])
  summ += ["", "TOTAL B2 this run: %d/%d (yesterday these 5 drafts hit B2 on 9/15 runs)" % (total_b2, total),
           "Ledger: %s" % LEDGER]
  email("P3.32 K12 Stage 1 targeted verification - B2 %d/%d" % (total_b2, total), "\n".join(summ))
  log("TARGETED VERIFICATION COMPLETE")


if __name__ == "__main__":
  main()
