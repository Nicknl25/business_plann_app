"""Phase 9 P3.9 — Auto-email workbooks for every planning run.

Reads SMTP credentials from the same `.env` keys the existing
`scripts/notify_push_email.py` helper uses:
  EMAIL_USER, EMAIL_PASSWORD, EMAIL_HOST, EMAIL_PORT, EMAIL_ALERTS_ADDRESS

Never raises. If env vars are missing or send fails, returns a dict
describing the outcome; the caller decides whether to log. The workbook
generation path must NOT depend on email success.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


logger = logging.getLogger(__name__)


REQUIRED_ENV_VARS = (
  "EMAIL_USER",
  "EMAIL_PASSWORD",
  "EMAIL_HOST",
  "EMAIL_PORT",
  "EMAIL_ALERTS_ADDRESS",
)


def _attach_file(msg: EmailMessage, path_str: str) -> bool:
  p = Path(path_str)
  if not p.is_file():
    return False
  ctype, encoding = mimetypes.guess_type(str(p))
  if ctype is None or encoding is not None:
    ctype = "application/octet-stream"
  maintype, subtype = ctype.split("/", 1)
  with open(p, "rb") as fh:
    data = fh.read()
  msg.add_attachment(
    data, maintype=maintype, subtype=subtype, filename=p.name,
  )
  return True


def send_workbook_alert(
  *,
  subject: str,
  body: str,
  attachment_paths: Optional[Iterable[str]] = None,
  recipient_override: Optional[str] = None,
) -> Dict[str, Any]:
  """Send an alert email with optional file attachments. Returns a
  dict describing the outcome (success/failure + reason). Never raises.

  Reuses the SMTP envelope used by `scripts/notify_push_email.py` so
  push notifications and workbook auto-emails share one configuration.
  """
  missing = [k for k in REQUIRED_ENV_VARS if not (os.getenv(k) or "").strip()]
  if missing:
    return {
      "sent": False,
      "reason": "missing_env_vars",
      "missing": missing,
    }
  recipient = recipient_override or (os.getenv("EMAIL_ALERTS_ADDRESS") or "").strip()
  if not recipient:
    return {"sent": False, "reason": "no_recipient"}
  msg = EmailMessage()
  msg["Subject"] = str(subject or "(no subject)")[:200]
  msg["From"] = os.getenv("EMAIL_USER") or ""
  msg["To"] = recipient
  msg.set_content(str(body or ""))

  attached: list = []
  skipped: list = []
  for ap in attachment_paths or ():
    try:
      ok = _attach_file(msg, str(ap))
      (attached if ok else skipped).append(str(ap))
    except Exception as exc:
      skipped.append(f"{ap}: {type(exc).__name__}: {str(exc)[:200]}")

  try:
    port = int(os.getenv("EMAIL_PORT") or "587")
  except Exception:
    port = 587

  try:
    with smtplib.SMTP(os.getenv("EMAIL_HOST"), port, timeout=60) as smtp:
      smtp.starttls()
      smtp.login(os.getenv("EMAIL_USER"), os.getenv("EMAIL_PASSWORD"))
      smtp.send_message(msg)
  except Exception as exc:
    logger.warning(
      "workbook_email_send_failed: %s: %s",
      type(exc).__name__, str(exc)[:200],
    )
    return {
      "sent": False,
      "reason": "smtp_failed",
      "error": f"{type(exc).__name__}: {str(exc)[:200]}",
      "attached": attached,
      "skipped": skipped,
      "recipient": recipient,
    }
  return {
    "sent": True,
    "recipient": recipient,
    "attached": attached,
    "skipped": skipped,
  }


def send_failure_alert(
  *,
  business_name: str,
  exception_class: str,
  exception_message: str,
  failure_diagnostic: Optional[Dict[str, Any]] = None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  attachment_paths: Optional[Iterable[str]] = None,
  recipient_override: Optional[str] = None,
) -> Dict[str, Any]:
  """Phase 9 P3.10 Commit 5 Part B — send a post-intake failure alert.

  Mirrors ``send_workbook_alert`` semantics: never raises, returns a
  status dict. SMTP misconfiguration / SMTP transport failure during a
  hard-fail is logged at ERROR (the run is already failing; we must
  not make it worse) and the dict reports ``sent=False`` so the API
  caller can include the email outcome in its HTTP response.
  """
  subject = (
    f"POST-INTAKE FAILURE: {business_name or '(unknown business)'} - "
    f"{exception_class or 'Unknown'}"
  )
  body = build_run_failure_email_body(
    business_name=business_name,
    exception_class=exception_class,
    exception_message=exception_message,
    failure_diagnostic=failure_diagnostic or {},
    draft_id=draft_id,
    planning_run_id=planning_run_id,
  )
  missing = [k for k in REQUIRED_ENV_VARS if not (os.getenv(k) or "").strip()]
  if missing:
    logger.error(
      "workbook_failure_email_missing_env_vars: %s; alert NOT sent for draft %s",
      missing, draft_id,
    )
    return {
      "sent": False,
      "reason": "missing_env_vars",
      "missing": missing,
      "subject": subject,
    }
  recipient = recipient_override or (os.getenv("EMAIL_ALERTS_ADDRESS") or "").strip()
  if not recipient:
    logger.error(
      "workbook_failure_email_no_recipient; alert NOT sent for draft %s",
      draft_id,
    )
    return {"sent": False, "reason": "no_recipient", "subject": subject}

  msg = EmailMessage()
  msg["Subject"] = str(subject)[:200]
  msg["From"] = os.getenv("EMAIL_USER") or ""
  msg["To"] = recipient
  msg.set_content(str(body or ""))

  attached: list = []
  skipped: list = []
  for ap in attachment_paths or ():
    try:
      ok = _attach_file(msg, str(ap))
      (attached if ok else skipped).append(str(ap))
    except Exception as exc:
      skipped.append(f"{ap}: {type(exc).__name__}: {str(exc)[:200]}")

  try:
    port = int(os.getenv("EMAIL_PORT") or "587")
  except Exception:
    port = 587

  try:
    with smtplib.SMTP(os.getenv("EMAIL_HOST"), port, timeout=60) as smtp:
      smtp.starttls()
      smtp.login(os.getenv("EMAIL_USER"), os.getenv("EMAIL_PASSWORD"))
      smtp.send_message(msg)
  except Exception as exc:
    logger.error(
      "workbook_failure_email_send_failed: %s: %s; draft %s",
      type(exc).__name__, str(exc)[:200], draft_id,
    )
    return {
      "sent": False,
      "reason": "smtp_failed",
      "error": f"{type(exc).__name__}: {str(exc)[:200]}",
      "attached": attached,
      "skipped": skipped,
      "recipient": recipient,
      "subject": subject,
    }
  return {
    "sent": True,
    "recipient": recipient,
    "attached": attached,
    "skipped": skipped,
    "subject": subject,
  }


def build_run_failure_email_body(
  *,
  business_name: str,
  exception_class: str,
  exception_message: str,
  failure_diagnostic: Optional[Dict[str, Any]] = None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
) -> str:
  """Phase 9 P3.10 Commit 5 Part B — compose a failure-alert email body.

  The body leads with the exception class and headline message, then
  unpacks the structured diagnostic (operation, pipeline_stage,
  expected, actual, details, cause) when present. Format is plain
  text so it renders readably across mail clients.
  """
  d = failure_diagnostic or {}
  lines = [
    "Post-intake pipeline raised a hard-fail.",
    "",
    f"Business:              {business_name or '(unknown)'}",
    f"Draft ID:              {draft_id or '(unknown)'}",
    f"Planning run ID:       {planning_run_id or '(unknown)'}",
    "",
    f"Exception class:       {exception_class or 'Unknown'}",
    "Exception message:",
    f"  {str(exception_message or '').strip()[:2000]}",
    "",
  ]
  operation = d.get("operation")
  pipeline_stage = d.get("pipeline_stage")
  expected = d.get("expected")
  actual = d.get("actual")
  details = d.get("details") if isinstance(d.get("details"), dict) else {}
  cause_class = d.get("cause_class")
  cause_detail = d.get("cause_detail")
  if operation or pipeline_stage or expected or actual:
    lines.extend([
      "Structured diagnostic:",
      f"  operation:           {operation or '(none)'}",
      f"  pipeline_stage:      {pipeline_stage or '(none)'}",
      f"  expected:            {expected or '(none)'}",
      f"  actual:              {actual or '(none)'}",
    ])
    if cause_class or cause_detail:
      lines.append(f"  cause_class:         {cause_class or '(none)'}")
      lines.append(f"  cause_detail:        {str(cause_detail or '(none)')[:600]}")
    if details:
      lines.append("  details:")
      for k, v in details.items():
        lines.append(f"    {k}: {str(v)[:300]}")
    lines.append("")
  lines.extend([
    "Workbook attachment (if any) carries whatever partial state was "
    "generated before the failure.",
    "",
    "Captured by Phase 9 P3.10 Commit 5 Part B email-on-failure.",
  ])
  return "\n".join(lines)


def build_run_email_body(payload: Dict[str, Any]) -> str:
  """Compose a brief plain-text body from the diagnostic payload.
  Includes business name, draft_id, planning run id, acceptance score,
  handler outcome (when fired), and the cash strategy name.
  """
  payload = payload or {}
  name = payload.get("business_name") or "(unknown)"
  draft_id = payload.get("draft_id") or "(unknown)"
  run_id = payload.get("planning_run_id") or "(unknown)"
  score = payload.get("acceptance_score") or "(unknown)"
  passed = payload.get("acceptance_passed")
  verdict = (
    "PASSED" if passed is True
    else "FAILED" if passed is False
    else "UNKNOWN"
  )
  planning_mode = payload.get("planning_mode") or "(unknown)"
  cash_strategy = payload.get("cash_strategy_name") or "(unknown)"
  stage = payload.get("business_stage") or "(unknown)"
  start_date = payload.get("business_start_date") or "(unknown)"
  naics = payload.get("business_naics_6") or "(unknown)"

  handler_fired = bool(payload.get("handler_fired"))
  if handler_fired:
    handler_lines = [
      f"Handler:               FIRED",
      f"  status:              {payload.get('handler_status') or '(unknown)'}",
      f"  scope:               {payload.get('handler_scope') or '(none)'}",
      f"  tool_calls_used:     {payload.get('tool_calls_used')}",
      f"  budget_extension:    {payload.get('budget_extension_triggered')}",
    ]
  else:
    handler_lines = ["Handler:               not fired (restoration loop landed)"]

  checks = payload.get("realism_checks") or []
  fail_metrics = [
    c.get("metric_key") for c in checks
    if isinstance(c, dict) and c.get("passed") is False
  ]
  if fail_metrics:
    fail_block = (
      f"Failing realism metrics ({len(fail_metrics)}):\n  - "
      + "\n  - ".join(str(m) for m in fail_metrics if m)
    )
  else:
    fail_block = "Failing realism metrics: (none)"

  body = "\n".join([
    "Planning run completed.",
    "",
    f"Business:              {name}",
    f"NAICS-6:               {naics}",
    f"Stage:                 {stage}",
    f"Start date:            {start_date}",
    f"Draft ID:              {draft_id}",
    f"Planning run ID:       {run_id}",
    f"Planning mode:         {planning_mode}",
    f"Cash strategy:         {cash_strategy}",
    "",
    f"Acceptance gate:       {verdict}  ({score})",
    *handler_lines,
    "",
    fail_block,
    "",
    "Workbook attached. The Diagnostics sheet at the end of the "
    "workbook carries the full per-metric realism breakdown.",
  ])
  return body
