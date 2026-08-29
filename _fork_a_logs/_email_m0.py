import os, smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
load_dotenv(r"c:\dev\business_plann_app\.env", override=True)
msg = MIMEText(open(r"c:\dev\business_plann_app\_fork_a_logs\_email_m0_body.txt", encoding="utf-8").read())
msg["Subject"] = "[Fork A][M0] Ground truth: run dies at ROUND-1 payroll continuity BEFORE the cascade — GPT not yet observable (wall + fix)"
msg["From"] = os.environ["EMAIL_USER"]
msg["To"] = os.environ["EMAIL_ALERTS_ADDRESS"]
with smtplib.SMTP(os.environ["EMAIL_HOST"], int(os.environ.get("EMAIL_PORT","587"))) as s:
    s.starttls(); s.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASSWORD"])
    s.sendmail(os.environ["EMAIL_USER"], [os.environ["EMAIL_ALERTS_ADDRESS"]], msg.as_string())
print("sent")
