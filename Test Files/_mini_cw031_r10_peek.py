import sys, json
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))
sys.path.insert(0, str(REPO / "python" / "client_intake_and_finmo"))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")
from intake_submission import get_mysql_connection

c = get_mysql_connection()
cur = c.cursor()
cur.execute("SELECT financials_json, operating_model_json, people_json "
            "FROM intake_consult_drafts WHERE draft_id=%s",
            ("1070c6a560a04f3d971019a3787180bf",))
fin, ops, ppl = cur.fetchone()
f = json.loads(fin or "{}")
o = json.loads(ops or "{}")
p = json.loads(ppl or "{}")
print("FIN numeric leaves:")
for k, v in f.items():
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        print("  ", k, "=", v)
for lob in o.get("lob_models", []):
    print("LOB", lob.get("lob_name"))
    for pr in lob.get("products", []):
        print("  ", {k: pr.get(k) for k in (
            "product_name", "unit_price", "units_per_period_capacity",
            "cogs_percent_of_line_revenue", "cogs_cost_structure_group",
            "cogs_cost_structure_group_members",
            "cogs_cost_structure_group_basis")})
print("PEOPLE numeric leaves (top level):")
def walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                print("  ", path + k, "=", v)
            else:
                walk(v, path + k + ".")
    elif isinstance(obj, list):
        for i, it in enumerate(obj):
            walk(it, path + str(i) + ".")
walk(p)
