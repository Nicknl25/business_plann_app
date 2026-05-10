"""Send an email alert after a successful `git push` or test run.

Usage:
  python scripts/notify_push_email.py "<subject>" "<body>" [<attachment_path> ...]

Optional attachment paths after subject + body get attached to the
email. Used by the "run passed 16/16" notification path to attach
the generated client workbook.

Reads SMTP credentials from the .env file at the repo root:
  EMAIL_USER, EMAIL_PASSWORD, EMAIL_HOST, EMAIL_PORT, EMAIL_ALERTS_ADDRESS
"""

from __future__ import annotations

import mimetypes
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path


def _load_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  env_path = Path(__file__).resolve().parent.parent / ".env"
  if env_path.exists():
    load_dotenv(env_path, override=False)


def _attach_file(msg: EmailMessage, path_str: str) -> None:
  p = Path(path_str)
  if not p.is_file():
    print(f"warning: attachment not found, skipping: {path_str}", file=sys.stderr)
    return
  ctype, encoding = mimetypes.guess_type(str(p))
  if ctype is None or encoding is not None:
    ctype = "application/octet-stream"
  maintype, subtype = ctype.split("/", 1)
  with open(p, "rb") as fh:
    data = fh.read()
  msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=p.name)


def main(argv: list[str]) -> int:
  if len(argv) < 3:
    print("usage: notify_push_email.py <subject> <body> [<attachment> ...]", file=sys.stderr)
    return 2
  _load_env()
  subject = argv[1]
  body = argv[2]
  attachments = argv[3:]
  required = ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_HOST", "EMAIL_PORT", "EMAIL_ALERTS_ADDRESS")
  missing = [k for k in required if not (os.getenv(k) or "").strip()]
  if missing:
    print(f"missing env vars: {missing}", file=sys.stderr)
    return 1
  msg = EmailMessage()
  msg["Subject"] = subject
  msg["From"] = os.getenv("EMAIL_USER")
  msg["To"] = os.getenv("EMAIL_ALERTS_ADDRESS")
  msg.set_content(body)
  for path_str in attachments:
    _attach_file(msg, path_str)
  try:
    with smtplib.SMTP(os.getenv("EMAIL_HOST"), int(os.getenv("EMAIL_PORT") or "587"), timeout=60) as smtp:
      smtp.starttls()
      smtp.login(os.getenv("EMAIL_USER"), os.getenv("EMAIL_PASSWORD"))
      smtp.send_message(msg)
  except Exception as exc:
    print(f"email send failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1
  attached_note = (
    f" with {len(attachments)} attachment(s)" if attachments else ""
  )
  print(f"email sent to {os.getenv('EMAIL_ALERTS_ADDRESS')}{attached_note}: {subject}")
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv))
