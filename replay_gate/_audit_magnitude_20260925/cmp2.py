import sys, os, json, logging
logging.disable(logging.CRITICAL)
root = sys.argv[1]
sys.path.insert(0, os.path.join(root, "python"))
sys.path.append(os.path.join(root, "python", "client_intake_and_finmo"))
from dotenv import load_dotenv; load_dotenv(os.path.join(root, ".env"), override=True)
from api_handlers import intake_consult as ic
tests = json.load(open(sys.argv[2], encoding="utf-8"))
out = {}
for s in tests:
    try:
        out[s] = [ic._message_figures(s), ""]
    except Exception as exc:
        out[s] = [[], "ERR:" + type(exc).__name__]
json.dump(out, open(sys.argv[3], "w"))
print("scanned", len(out))
