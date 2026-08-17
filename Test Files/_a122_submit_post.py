"""A-122: POST a completed draft through the REAL submit door (/api/financials)
with the same 9 contact fields the browser sends. Prints status + body."""
import json, sys, requests
draft_id = sys.argv[1]
bname = sys.argv[2]
payload = {
  "draft_id": draft_id,
  "business_name": bname,
  "address": None, "product_keywords": None,
  "first_name": "Nick", "last_name": "Henry",
  "email_address": "ignatius.henry@tithefinancial.com",
  "phone_number": None, "how_did_you_hear": "a122-verify",
  "business_start_date": "2024-01-15",
}
r = requests.post("http://127.0.0.1:5050/api/financials", json=payload, timeout=120)
print("STATUS", r.status_code)
try:
  print(json.dumps(r.json(), indent=1, sort_keys=True)[:2500])
except Exception:
  print(r.text[:2000])
