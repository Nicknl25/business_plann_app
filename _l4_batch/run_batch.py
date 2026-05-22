"""P3.32 K11 Phase 2 — 12-draft x 3-run instrumented batch.

Drives Test Files/run_persisted_system_run.py (an HTTP client to the
5050 server, which runs the L-4-instrumented pipeline with
BPLAN_TRACE_VERBOSE=1). For each run it captures the fresh cloned
draft_id, outcome, duration, and persisted trace-row counts, retrying
only runs that produced ZERO traces (i.e. never reached the instrumented
layer). Emails after each draft and a final summary. Writes a ledger.
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
PER_RUN_TIMEOUT = 600          # hard cap per run subprocess (s)
PAUSE_BETWEEN = 6             # gap between runs to avoid rate clustering
LEDGER = os.path.join(HERE, "ledger.json")
LOG = os.path.join(HERE, "batch.log")

DRAFTS = [
  ("Sunny Glaze Donuts", "6d37c6b98ace41ee9c91dd5fbf68b83e", 3),
  ("Skyward Express Airlines", "82b485233e51409ba14b1407e4fded99", 6),  # extra retries
  ("CareFirst Home Health Services", "201d0ad18ae243dba933703d19cda4df", 3),
  ("Anderson & Blake Legal Associates", "25f746500d1d456da638ee216669b78e", 3),
  ("Luna Boutique", "25b8e17eda804fa7a46adf72a3503900", 3),
  ("Elegant Threads Boutique", "5dcd919aae314bd5af67849172aa52bb", 3),
  ("Revitalize Mobile IV Therapy", "5af71d361b324f62a3598e8da40c98c7", 3),
  ("North Ridge Auto Care", "1bef9076e6504af9a9fe223af128110b", 3),
  ("ValueMart Superstores", "0d0fb60aca754e00954f402a4fdec0ab", 3),
  ("Freedom Freight Logistics", "56b8623063a34e6d9c1803568a730825", 3),
  ("Pinnacle Logistics Inc.", "11d6cd0c19c3430e8aaf8916b550ea7f", 3),
  ("SwiftCargo Logistics", "26fc7c5b8d1349048a538f65b4f85beb", 3),
]

ledger = {"started_at": datetime.now().isoformat(), "drafts": []}


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


def trace_counts(draft_id):
  if not draft_id:
    return {"total": 0}
  try:
    conn = get_mysql_connection(); cur = conn.cursor()
    cur.execute(
      "SELECT COUNT(*), "
      "SUM(handler='gpt_io'), SUM(handler='h2_exhaustion'), "
      "SUM(handler='handler_c_payroll') "
      "FROM post_intake_handler_traces WHERE draft_id=%s", (draft_id,))
    r = cur.fetchone(); cur.close(); conn.close()
    return {"total": int(r[0] or 0), "gpt_io": int(r[1] or 0),
            "h2": int(r[2] or 0), "handler_c": int(r[3] or 0)}
  except Exception as e:
    return {"error": str(e)[:200], "total": 0}


def run_once(source_id):
  env = dict(os.environ); env["BPLAN_TRACE_VERBOSE"] = "1"
  t0 = time.time()
  try:
    p = subprocess.run([PY, RUNNER, "--draft-id", source_id],
                       capture_output=True, text=True,
                       timeout=PER_RUN_TIMEOUT, env=env, cwd=ROOT)
    out = (p.stdout or "") + "\n" + (p.stderr or ""); rc = p.returncode
  except subprocess.TimeoutExpired as e:
    out = (e.stdout or "") + "\n[HUNG > %ds]" % PER_RUN_TIMEOUT; rc = -9
  dur = round(time.time() - t0, 1)
  m = re.search(r"new draft:\s*([0-9a-f]{32})", out)
  new_id = m.group(1) if m else None
  if rc == -9:
    outcome = "hung"
  elif "System run duration" in out and rc == 0:
    outcome = "completed"
  elif "ERROR:" in out:
    em = re.search(r"ERROR:\s*(.*)", out)
    outcome = "failed: " + (em.group(1)[:240] if em else "unknown")
  else:
    outcome = "failed: rc=%d" % rc
  tc = trace_counts(new_id)
  return {"new_draft_id": new_id, "outcome": outcome,
          "duration_s": dur, "traces": tc}


def main():
  open(LOG, "w").close()
  total_runs = 0
  log("BATCH START: %d drafts x %d runs" % (len(DRAFTS), RUNS_PER_DRAFT))
  for di, (name, source_id, max_attempts) in enumerate(DRAFTS, 1):
    draft_entry = {"name": name, "source_id": source_id, "runs": []}
    for run_idx in range(1, RUNS_PER_DRAFT + 1):
      attempt = 0
      while True:
        attempt += 1
        total_runs += 1
        log("draft %d/%d %s | run %d/%d attempt %d"
            % (di, len(DRAFTS), name, run_idx, RUNS_PER_DRAFT, attempt))
        res = run_once(source_id)
        res["run_idx"] = run_idx; res["attempt"] = attempt
        log("  -> %s | %ss | traces=%s"
            % (res["outcome"], res["duration_s"], res["traces"]))
        captured = (res["traces"].get("total", 0) > 0)
        if captured or attempt >= max_attempts:
          draft_entry["runs"].append(res)
          break
        log("  zero traces; retrying (max %d)" % max_attempts)
        time.sleep(PAUSE_BETWEEN)
      time.sleep(PAUSE_BETWEEN)
    ledger["drafts"].append(draft_entry)
    with open(LEDGER, "w", encoding="utf-8") as f:
      json.dump(ledger, f, indent=2)
    # Per-draft email.
    lines = ["%s — %d runs:" % (name, len(draft_entry["runs"]))]
    for r in draft_entry["runs"]:
      lines.append("  run %d (try %d): %s | %ss | traces total=%d "
                   "(gpt_io=%s h2=%s handler_c=%s) | draft=%s"
                   % (r["run_idx"], r["attempt"], r["outcome"], r["duration_s"],
                      r["traces"].get("total", 0), r["traces"].get("gpt_io", "?"),
                      r["traces"].get("h2", "?"), r["traces"].get("handler_c", "?"),
                      r["new_draft_id"]))
    email("P3.32 K11 batch [%d/%d] %s done" % (di, len(DRAFTS), name),
          "\n".join(lines))
  ledger["finished_at"] = datetime.now().isoformat()
  ledger["total_runs"] = total_runs
  with open(LEDGER, "w", encoding="utf-8") as f:
    json.dump(ledger, f, indent=2)
  # Final summary.
  summ = ["P3.32 K11 — ALL %d DRAFTS DONE (%d total run-attempts)"
          % (len(DRAFTS), total_runs), ""]
  for d in ledger["drafts"]:
    caps = sum(1 for r in d["runs"] if r["traces"].get("total", 0) > 0)
    comp = sum(1 for r in d["runs"] if r["outcome"] == "completed")
    summ.append("%-36s captured=%d/%d completed=%d/%d"
                % (d["name"], caps, len(d["runs"]), comp, len(d["runs"])))
  summ.append("")
  summ.append("Ledger: %s" % LEDGER)
  summ.append("Traces queryable in post_intake_handler_traces by draft_id.")
  email("P3.32 K11 — all 36 runs persisted to traces", "\n".join(summ))
  log("BATCH COMPLETE")


if __name__ == "__main__":
  main()
