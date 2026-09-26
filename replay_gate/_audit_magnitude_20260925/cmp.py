import sys, os, json, logging
logging.disable(logging.CRITICAL)
root=sys.argv[1]
from dotenv import load_dotenv; load_dotenv(r"C:devbusiness_plann_app.env")
sys.path.insert(0, os.path.join(root,"python")); sys.path.append(os.path.join(root,"python","client_intake_and_finmo"))
os.chdir(root)
from api_handlers import intake_consult as ic
tests=json.load(open(sys.argv[2]))
out={s:[ic._message_figures(s), ic._normalize_word_numbers(s.lower().replace(",",""))] for s in tests}
json.dump(out, open(sys.argv[3],"w"))
for msg in ["No, the six hundred and twenty thousand is just for the nine fabricators and fitters, so it doesn\u2019t include Dev."]:
  print("RESOLVE", ic._rest_inclusion_resolve(pending={"stated":620000.0,"named_sum":95000.0,"remainder":525000.0}, user_message=msg))
