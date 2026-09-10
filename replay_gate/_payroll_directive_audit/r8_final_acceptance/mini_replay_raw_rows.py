"""mini turn 17 - independent replay of the item-8 failure diagnosis.

(a) replay the four people-stage patches (verbatim from _api5050_server.err.log
    lines 103 / 107 / finalize / 117) through the REAL _merge_people_rows and
    reproduce the stored 12-row roster of draft a9db48dd;
(b) _person_row_identity is None for the router-shape rows and the '?' labels
    in the PEOPLE_PATCH lines are those rows;
(e) model_validate the stored payload (PeopleJsonContract on the saved file,
    IntakeDraftContract on the live DB row, read-only) and count 56.
Nothing is written anywhere.
"""
import ast, json, os, sys, re
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.join(ROOT, "python", "api_handlers"))
sys.path.insert(0, os.path.join(ROOT, "python", "client_intake_and_finmo"))
os.chdir(ROOT)

LOG = os.path.join(ROOT, "_api5050_server.err.log")
lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()

def _patch_from_line(ln: str):
    m = re.search(r"patch=(\{.*\})\s*$", ln)
    return ast.literal_eval(m.group(1))

turn45 = _patch_from_line(lines[102])   # 07:20:56 two raw rows + owner_pay_monthly
turn47 = _patch_from_line(lines[106])   # 07:21:15 two raw rows + bare Owner row
turn51 = _patch_from_line(lines[116])   # 07:22:11 four canonical + four raw
assert "TURN_INTENT" in lines[102] and "07:20:56" in lines[102]
assert "TURN_INTENT" in lines[106] and "07:21:15" in lines[106]
assert "TURN_INTENT" in lines[116] and "07:22:11" in lines[116]
print("turn45 rows", len(turn45["people.people"]), "keys", sorted(turn45["people.people"][0].keys()))
print("turn47 rows", len(turn47["people.people"]), "third row", turn47["people.people"][2])
print("turn51 rows", len(turn51["people.people"]), "shapes",
      [("canon" if "full_name" in r else "raw") for r in turn51["people.people"]])

# --- the real helpers, straight from the app module (no copy) ---
import intake_consult as ic  # type: ignore
merge = ic._merge_people_rows
ident = ic._person_row_identity
label = ic._label_person_row
OWNER_RE = ic._OWNER_TITLE_RE

# (b) identity of the raw rows
for r in turn45["people.people"]:
    print("identity(raw45)", ident(r), "label", repr(label(r)))
print("identity(bare Owner)", ident(turn47["people.people"][2]), "label", repr(label(turn47["people.people"][2])))
assert all(ident(r) is None for r in turn45["people.people"])
assert all(label(r) == "?" for r in turn45["people.people"])

# (a) replay, in log order
roster = []                                   # fresh draft, no people yet
roster, rep45 = merge(roster, turn45["people.people"])
print("after turn45 people door:", len(roster), "report", {k: rep45[k] for k in ("incoming", "restored", "field_kept")})
# the same turn carried people.owner_pay_monthly -> _apply_owner_pay_statement
# looks for an owner-titled ROLE_TITLE; the raw rows carry 'title', so it
# appends the bare Owner row (intake_consult 17183+). Reproduce that append.
if not any(OWNER_RE.search(str(p.get("role_title") or "")) for p in roster):
    roster.append({"role_title": "Owner", "annual_wage": 118000.0, "wage_source": "client_override"})
print("after owner-pay door:", len(roster), [label(r) for r in roster])
roster, rep47 = merge(roster, turn47["people.people"])
print("after turn47 people door:", len(roster), "report", {k: rep47[k] for k in ("incoming", "restored", "field_kept")},
      "| log said incoming=3 restored=['?', '?']")
assert rep47["incoming"] == 3 and rep47["restored"] == ["?", "?"]
# finalize (site=people_finalize_done_adding): four canonical rows from the
# model. The model's rows are not in the log verbatim; identity is all the
# merge reads, so use the four canonical rows of turn 51 as the model rows.
final_rows = [r for r in turn51["people.people"] if "full_name" in r]
roster, repF = merge(roster, final_rows)
print("after finalize merge:", len(roster), "report", {k: repF[k] for k in ("incoming", "restored", "field_kept")},
      "| log said incoming=4 restored=['?', '?', 'Owner', '?', '?']")
assert repF["incoming"] == 4 and repF["restored"] == ["?", "?", "Owner", "?", "?"]
# the recalc's owner-row pass (OWNER_ROW_UNIQUENESS merged=1 groups=2): the
# bare Owner row folds into the most complete named owner -> 9 -> 8 rows.
bare = [p for p in roster if OWNER_RE.search(str(p.get("role_title") or "")) and not str(p.get("full_name") or "").strip()]
assert len(bare) == 1
roster = [p for p in roster if p is not bare[0]]
print("after OWNER_ROW_UNIQUENESS fold:", len(roster))
roster, rep51 = merge(roster, turn51["people.people"])
print("after turn51 correction:", len(roster), "report", {k: rep51[k] for k in ("incoming", "restored", "field_kept")},
      "| log said incoming=8 restored=['?', '?', '?', '?']")
assert rep51["incoming"] == 8 and rep51["restored"] == ["?", "?", "?", "?"]

stored = json.load(open(os.path.join(HERE, "people_json_a9db48dd.json"), encoding="utf-8"))["people"]
print("REPLAY rows", len(roster), "STORED rows", len(stored))
assert len(roster) == 12 == len(stored)
def _shape(r):
    return ("canon", r.get("full_name")) if "full_name" in r else ("raw", r.get("name"), r.get("years_experience"))
print("replay shapes", [_shape(r) for r in roster])
print("stored shapes", [_shape(r) for r in stored])
assert [_shape(r) for r in roster] == [_shape(r) for r in stored], "row order / shape differs"
raw_stored = [r for r in stored if "full_name" not in r]
assert len(raw_stored) == 8 and all(ident(r) is None for r in raw_stored)
print("(a)+(b) REPRODUCED: 2 -> (owner row) 3 -> 5 -> 9 -> 8 -> 12; the eight raw rows have identity None")

# (e) the boundary contract on the stored payload
from client_intake_and_finmo.post_intake_contracts.people_json_contract import PeopleJsonContract
from client_intake_and_finmo.post_intake_contracts.intake_draft_contract import IntakeDraftContract
from pydantic import ValidationError
people_full = json.load(open(os.path.join(HERE, "people_json_a9db48dd.json"), encoding="utf-8"))
try:
    PeopleJsonContract.model_validate(people_full)
    print("PeopleJsonContract: PASSED (unexpected)")
except ValidationError as e:
    errs = e.errors()
    locs = sorted({(er["loc"][1]) for er in errs if er["loc"][0] == "people"})
    fields = sorted({er["loc"][2] for er in errs if len(er["loc"]) > 2})
    print("PeopleJsonContract errors:", len(errs), "rows", locs, "fields", fields)

# the live row, read-only
from dotenv import load_dotenv; load_dotenv(".env")
from intake_submission import get_mysql_connection
conn = get_mysql_connection(); cur = conn.cursor(dictionary=True)
cur.execute("SELECT draft_id, business_name, updated_at, operating_model_json, target_market_json, people_json, "
            "financials_json, financials_year1_json, marketing_model_json, planning_context_summary_json, fulfillment_json "
            "FROM intake_consult_drafts WHERE draft_id LIKE 'a9db48dd%'")
row = cur.fetchone()
print("DB draft", row["draft_id"], row["business_name"], "updated_at", row["updated_at"])
payload = {}
for k in ("operating_model_json", "target_market_json", "people_json", "financials_json", "financials_year1_json",
          "marketing_model_json", "planning_context_summary_json", "fulfillment_json"):
    v = row.get(k)
    payload[k] = json.loads(v) if isinstance(v, (str, bytes)) else v
db_people = payload["people_json"]["people"]
print("DB people rows", len(db_people), "raw rows", sum(1 for r in db_people if "full_name" not in r))
try:
    IntakeDraftContract.model_validate(payload)
    print("IntakeDraftContract on the live row: PASSED (unexpected)")
except ValidationError as e:
    errs = e.errors()
    rows_hit = sorted({er["loc"][2] for er in errs if er["loc"][:2] == ("people_json", "people")})
    fields = sorted({er["loc"][3] for er in errs if er["loc"][:2] == ("people_json", "people") and len(er["loc"]) > 3})
    print("IntakeDraftContract on the live row: errors", len(errs), "rows", rows_hit, "fields", fields)
    other = [er for er in errs if er["loc"][:2] != ("people_json", "people")]
    print("errors outside people_json.people:", len(other), [er["loc"] for er in other][:5])
    print("first error:", errs[0]["loc"], errs[0]["msg"])
print("NOTE: planning_context_summary_json is NULL on the draft row (the boundary aggregates it at run time) - that one error is my payload assembly, not a 57th defect; the people count is 56.")
cur.execute("SELECT planning_run_id, run_status, current_stage, current_stage_status, failure_reason, started_at FROM planning_runs WHERE draft_id LIKE 'a9db48dd%' ORDER BY started_at")
for r in cur.fetchall():
    print("planning_run", r["planning_run_id"][:8], r["run_status"], r["current_stage"], r["current_stage_status"], r["started_at"], "|", str(r["failure_reason"] or "")[:200])
cur.execute("SELECT issue_id, status, clean_exercise_count, runs_since_last_seen, resolution_basis, probe_json FROM issues WHERE issue_id=571")
for r in cur.fetchall():
    print("issue 571:", {k: (str(v)[:160] if v is not None else None) for k, v in r.items()})
cur.close(); conn.close()
