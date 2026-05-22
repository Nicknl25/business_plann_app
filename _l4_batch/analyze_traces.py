"""P3.32 K11 Phase 2 — extract forensic tables from handler traces.

Given a draft_id, reconstructs from post_intake_handler_traces:
  P2.1  H2 per-probe cost-ratio exploration (COGS/mkt/EBITDA + checks)
  P2.2  H2 mini_finmo violation history (per-probe failing checks + viol)
  P2.3  Handler C tool-call sequence (tool, args summary, validator outcome)
  GPT-IO latency / token / timeout profile (Skyward call-#2 signal)

Usage: python analyze_traces.py <draft_id> [draft_id...]
"""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "python"))
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"), override=False)
from client_intake_and_finmo.intake_submission import get_mysql_connection
from client_intake_and_finmo.post_intake_handler_traces import load_traces_for_draft


def _anchor(args, field, q):
  try:
    return round(float(((args or {}).get(field) or {}).get(q)), 3)
  except Exception:
    return None


def analyze(draft_id):
  conn = get_mysql_connection()
  rows = load_traces_for_draft(conn, draft_id=draft_id)
  conn.close()
  out = ["", "=" * 78, "DRAFT %s — %d trace rows" % (draft_id, len(rows)), "=" * 78]

  # ---- P2.1 + P2.2 H2 exploration + violations ----
  h2 = [r for r in rows if r["handler"] == "h2_exhaustion" and r["trace_kind"] == "per_call"]
  out.append("\n[P2.1/P2.2] H2 exploration — %d probes" % len(h2))
  if h2:
    out.append("call | COGSq11 COGSq20 MKTq11 | EBITq11 EBITq20 | all_pass | failing_checks / #viol")
    for r in h2:
      p = r.get("trace", {}).get("payload", {}); a = p.get("arguments", {})
      vc = p.get("viability_checks", {}) or {}; em = p.get("ebitda_margins", {}) or {}
      failing = sorted(k for k, v in vc.items() if k != "all_pass" and str(v).upper() == "FAIL")
      nviol = len(p.get("stage_ramp_violations") or [])
      out.append("  %-3s | %-7s %-7s %-6s | %-7s %-7s | %-7s | %s / %d" % (
        r.get("call_n"),
        _anchor(a, "cogs_percent_of_revenue", "q11"), _anchor(a, "cogs_percent_of_revenue", "q20"),
        _anchor(a, "marketing_percent_of_revenue", "q11"),
        round(em.get("q11"), 3) if em.get("q11") is not None else None,
        round(em.get("q20"), 3) if em.get("q20") is not None else None,
        vc.get("all_pass"), ",".join(s.replace("stage_ramp_", "").replace("_respected", "") for s in failing) or "(none)", nviol))

  # ---- P2.3 Handler C tool sequence ----
  hc = [r for r in rows if r["handler"] == "handler_c_payroll" and r["trace_kind"] == "per_call"]
  out.append("\n[P2.3] Handler C tool sequence — %d calls" % len(hc))
  for r in hc:
    p = r.get("trace", {}).get("payload", {})
    out.append("  call %-2s %-38s accepted=%s err=%s" % (
      r.get("call_n"), p.get("tool_name"), p.get("validator_accepted"),
      (p.get("validator_error_code") or "")[:40]))

  # ---- GPT-IO latency / timeout profile ----
  io = [r for r in rows if r["handler"] == "gpt_io"]
  out.append("\n[GPT-IO] %d turns — latency / tokens / errors" % len(io))
  for r in io:
    p = r.get("trace", {}).get("payload", {}); u = p.get("usage") or {}; err = p.get("error")
    flag = " <<< ERROR/TIMEOUT" if err else ""
    out.append("  %-52s %6sms in=%s out=%s%s" % (
      (p.get("consultant_name") or "")[:52], p.get("elapsed_ms"),
      u.get("input_tokens"), u.get("output_tokens"),
      (" " + (err.get("final_failure_kind") or "err") if err else "") + flag))
  return "\n".join(out)


if __name__ == "__main__":
  targets = sys.argv[1:] or ["36cdcfb5c10d425aba9321a4e0cc1141"]
  for d in targets:
    print(analyze(d))
