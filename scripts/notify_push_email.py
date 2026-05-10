"""Send an email alert after a successful `git push`.

Usage:
  python scripts/notify_push_email.py "<subject>" "<body>"

Reads SMTP credentials from the .env file at the repo root:
  EMAIL_USER, EMAIL_PASSWORD, EMAIL_HOST, EMAIL_PORT, EMAIL_ALERTS_ADDRESS
"""

from __future__ import annotations

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


def main(argv: list[str]) -> int:
  if len(argv) < 3:
    print("usage: notify_push_email.py <subject> <body>", file=sys.stderr)
    return 2
  _load_env()
  subject = argv[1]
  body = argv[2]
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
  try:
    with smtplib.SMTP(os.getenv("EMAIL_HOST"), int(os.getenv("EMAIL_PORT") or "587"), timeout=30) as smtp:
      smtp.starttls()
      smtp.login(os.getenv("EMAIL_USER"), os.getenv("EMAIL_PASSWORD"))
      smtp.send_message(msg)
  except Exception as exc:
    print(f"email send failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1
  print(f"email sent to {os.getenv('EMAIL_ALERTS_ADDRESS')}: {subject}")
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv))
