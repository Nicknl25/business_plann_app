"""Peek at repair_guidance_json.restructure structure for the corner
backtest (read-only)."""
import json
import os

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


def walk(d, prefix="", depth=0):
    if depth > 3 or not isinstance(d, dict):
        return
    for k, v in d.items():
        if isinstance(v, dict):
            print(f"{prefix}{k}: dict[{', '.join(list(v)[:10])}]")
            if k in ("bounds", "restructure", "baseline", "final", "chosen", "team", "facility", "cost_floors"):
                walk(v, prefix + "  ", depth + 1)
        elif isinstance(v, list):
            head = v[0] if v else None
            inner = f" first={json.dumps(head)[:220]}" if head is not None else ""
            print(f"{prefix}{k}: list(n={len(v)}){inner}")
        else:
            sv = json.dumps(v)
            print(f"{prefix}{k} = {sv[:160]}")


for draft_like in ("ea30f6dc", "195d85e4"):
    cur.execute(
        "SELECT draft_id, business_name, repair_guidance_json FROM intake_consult_drafts "
        "WHERE draft_id LIKE %s", (draft_like + "%",))
    r = cur.fetchone()
    if not r:
        print(draft_like, "not found")
        continue
    rg = _j(r.get("repair_guidance_json"))
    rest = rg.get("restructure") or {}
    print(f"=== {r['business_name']} ({r['draft_id'][:12]}) restructure keys: {list(rest)} ===")
    walk(rest, "  ")
    print()

cur.close()
conn.close()
