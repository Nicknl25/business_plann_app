# -*- coding: utf-8 -*-
"""Wrap-gate PRODUCER-side check: run the real intake completion tripwire
(_completion_model_input_tripwire) on Millgate's stored payloads with the
fixed builder - must return None (proceed), i.e. the boundary contract
accepts the model_input the fixed tree produces."""
import json, logging, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "python"))
import _redproof_ga_stub_denominator as rp
from client_intake_and_finmo import finmo_bridge as fb
from client_intake_and_finmo.intake_submission import get_mysql_connection
from api_handlers.intake_consult import _completion_model_input_tripwire
fb._load_root_env()
conn = get_mysql_connection(); cur = conn.cursor(dictionary=True)
cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s LIMIT 1", (rp.DRAFT_PREFIX + "%",))
row = cur.fetchone()
logging.basicConfig(level=logging.WARNING)
res = _completion_model_input_tripwire(
  business_facts=rp._facts(row), ops_value=rp._obj(row.get("operating_model_json")),
  people_value=rp._obj(row.get("people_json")), financials_value=rp._obj(row.get("financials_json")),
  financials_year1_value=rp._obj(row.get("financials_year1_json")), marketing_value=rp._obj(row.get("marketing_model_json")),
  logger=logging.getLogger("tripwire"), draft_id=row["draft_id"])
print("tripwire result:", res, "->", "PROCEED (contract accepted)" if res is None else "HOLD")
sys.exit(0 if res is None else 1)
