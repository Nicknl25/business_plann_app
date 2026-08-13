"""CW-031 round-7 mini audit -- ITEM 1, THE ONE THAT MATTERS.

Round 7's whole safety rests on the LIVE router emitting cogs_percent_unit. A
GPT field is not a guarantee, so this drives wordings the router has to judge
and reads the ARTIFACT (the ops product rows) rather than the reply.

Two populations, deliberately:

  U*  AMBIGUOUS BY CONSTRUCTION -- a bare figure whose unit lives only in how a
      human would hear it ("design runs at 1"), a unit stated in an EARLIER
      turn, and a mixed message ("plants 48 percent, install 0.19"). Here a
      refusal is a PASS. The unacceptable outcome is a WRONG NUMBER on the
      right line -- 1 stored as 1.0, "a tenth" stored as 10.

  C*  CLEAR BY ANY READING -- the client said the unit in the same sentence.
      Here a refusal is a MISS, and the miss RATE is the number VS asked for:
      if the router drops the unit often, clients get asked when they were
      clear and refusal becomes the norm.

Every case runs on a FRESH clone of the real Ravenwood draft (four lines,
all four fully weighted), through the live :5050 backend and the live router.
Each turn also dumps financials_json's door-key residue, because the door's
TRANSPORT keys are scoped patch keys and _apply_scoped_patch persists any
"financials.<field>" verbatim.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r7_unit_wording.py" [U|C]
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:5050"
SOURCE_DRAFT = "1070c6a560a04f3d971019a3787180bf"

# expect: {line_name: stored ratio the wording actually means}. None => refusal
# is the honest outcome and any write of that line is judged against `wrong_if`.
CASES = [
  {
    "id": "U1", "pop": "U",
    "messages": ["On direct costs, the design consult line runs at 1."],
    "line": "Design consult",
    "true_readings": [0.01, 1.0],
    "why": "a bare 1: 1% and 100% are both readable, and no threshold separates them",
  },
  {
    "id": "U2", "pop": "U",
    "messages": ["Materials on the install project are point five on that line."],
    "line": "Install project",
    "true_readings": [0.5, 0.005],
    "why": "'point five' reads as 0.5 to one ear and half a percent to another",
  },
  {
    "id": "U3", "pop": "U",
    "messages": ["For plant sale, direct costs are call it a tenth."],
    "line": "Plant sale",
    "true_readings": [0.1],
    "why": "'a tenth' is 10% by any reading; 10.0 or 0.001 would be a wrong number",
  },
  {
    "id": "U4", "pop": "U",
    "messages": [
      "I'm going to give you the direct-cost numbers as percentages of each "
      "line's revenue, one line at a time.",
      "Hard goods sale, 71.",
    ],
    "line": "Hard goods sale",
    "true_readings": [0.71],
    "why": "the unit is stated in an EARLIER turn and the figure arrives bare",
  },
  {
    "id": "U5", "pop": "U",
    "messages": ["Plant sale is 48 percent in direct costs and install project is 0.19."],
    "lines": {"Plant sale": [0.48], "Install project": [0.19]},
    "why": "one message, two units -- a per-item unit, not a per-message one",
  },
  # B* -- THE BOUNDARY. The router instruction supplies a default for a bare
  # figure ("runs at 4" -> percent) and tells the model to omit the unit only
  # when the wording "genuinely does not say which". These three sit exactly on
  # that line: a bare sub-1 decimal, a bare integer, and a word-fraction. They
  # are how we learn whether the door's refusal branch can fire at all live.
  {
    "id": "B1", "pop": "B",
    "messages": ["Design consult is 0.5 on direct costs."],
    "line": "Design consult", "true_readings": [0.5, 0.005],
    "why": "a bare sub-1 decimal with no unit word",
  },
  {
    "id": "B2", "pop": "B",
    "messages": ["Design consult sits at 4 for materials."],
    "line": "Design consult", "true_readings": [0.04, 4.0],
    "why": "a bare integer with no unit word -- the instruction's own example",
  },
  {
    "id": "B3", "pop": "B",
    "messages": ["On hard goods sale, make the direct costs a half."],
    "line": "Hard goods sale", "true_readings": [0.5, 0.005],
    "why": "a word-fraction: 'a half' is 50% to one ear and half a percent to another",
  },
  {
    "id": "C1", "pop": "C",
    "messages": ["Hard goods sale runs 71% of that line's revenue in direct costs."],
    "line": "Hard goods sale", "true_readings": [0.71],
    "why": "percent sign, in the same sentence",
  },
  {
    "id": "C2", "pop": "C",
    "messages": ["Direct costs on the install project are about 38 percent of that line."],
    "line": "Install project", "true_readings": [0.38],
    "why": "the word percent, in the same sentence",
  },
  {
    "id": "C3", "pop": "C",
    "messages": ["For design consult, materials and subs come to 6% of that line's revenue."],
    "line": "Design consult", "true_readings": [0.06],
    "why": "a small percent -- the reading the old clamp got backwards",
  },
  {
    "id": "C4", "pop": "C",
    "messages": ["Plant sale: the direct-cost ratio is 0.55 of that line's revenue."],
    "line": "Plant sale", "true_readings": [0.55],
    "why": "the word ratio with a sub-1 figure",
  },
]

VERDICTS: list = []


def _commit(conn):
  try:
    conn.commit()
  except Exception:
    pass


def ops_rates(conn, draft_id):
  # commit() FIRST: REPEATABLE READ otherwise serves the snapshot from this
  # connection's first read and a correct write reads back as null.
  _commit(conn)
  cur = conn.cursor()
  cur.execute("SELECT operating_model_json, financials_json FROM intake_consult_drafts "
              "WHERE draft_id=%s", (draft_id,))
  row = cur.fetchone()
  cur.close()
  ops = json.loads((row[0] if row else None) or "{}")
  fin = json.loads((row[1] if row else None) or "{}")
  out = {}
  for lob in ops.get("lob_models") or []:
    for product in lob.get("products") or []:
      out[str(product.get("product_name"))] = {
        "pct": product.get("cogs_percent_of_line_revenue"),
        "group": product.get("cogs_cost_structure_group"),
      }
  residue = {k: v for k, v in fin.items()
             if "cogs_per_line" in k or "cogs_shared" in k or k in ("cogs_percent", "cogs_percent_unit")}
  return out, residue


def clone(conn):
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
  src = cur.fetchone()
  cur.close()
  if not src:
    raise SystemExit("source Ravenwood draft missing")
  clone_id = "mini" + uuid.uuid4().hex[:28]
  client_id = "MINI" + uuid.uuid4().hex[:14].upper()
  columns = [c for c in src.keys() if c != "id"]
  values = []
  for c in columns:
    v = src[c]
    if c == "draft_id":
      v = clone_id
    elif c == "client_id":
      v = client_id
    values.append(v)
  write = conn.cursor()
  write.execute(
    f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
    f"VALUES ({', '.join(['%s'] * len(columns))})", tuple(values))
  conn.commit()
  write.close()
  return clone_id, client_id


def _asks(reply: str) -> bool:
  low = reply.lower()
  return ("could be a percent or a fraction" in low
          or "won't guess" in low or "won’t guess" in low
          or "couldn't tell which line" in low or "couldn’t tell which line" in low
          or "which one should i change" in low)


def main() -> int:
  only = (sys.argv[1].strip().upper() if len(sys.argv) > 1 else "")
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  made: list = []
  try:
    for case in CASES:
      if only and not case["id"].startswith(only):
        continue
      draft_id, client_id = clone(conn)
      made.append(draft_id)
      before, _ = ops_rates(conn, draft_id)
      print("=" * 78)
      print(f"{case['id']} [{case['pop']}]  {case['why']}")
      print(f"  clone {draft_id[:16]}")
      print(f"  before: { {k: v['pct'] for k, v in before.items()} }")
      reply = ""
      for message in case["messages"]:
        print(f"  > {message}")
        resp = requests.post(
          f"{BASE_URL}/api/intake-consult",
          json={"draft_id": draft_id, "client_id": client_id, "message": message},
          timeout=300,
        )
        body = resp.json() if resp.status_code == 200 else {}
        reply = str(body.get("assistant_message") or "")
        print(f"  < [{resp.status_code}] {reply[:400]}")
      after, residue = ops_rates(conn, draft_id)
      print(f"  after : { {k: v['pct'] for k, v in after.items()} }")
      if residue:
        print(f"  FINANCIALS DOOR-KEY RESIDUE: {json.dumps(residue)[:300]}")

      expected = case.get("lines") or {case["line"]: case["true_readings"]}
      changed = {name: value["pct"] for name, value in after.items()
                 if value["pct"] != before.get(name, {}).get("pct")}
      wrong_line = sorted(set(changed) - set(expected))
      wrong_number = sorted(
        f"{name}={changed[name]}" for name in changed
        if name in expected and changed[name] not in expected[name])
      missed = sorted(set(expected) - set(changed))
      if wrong_line:
        verdict = "WRONG-LINE"
      elif wrong_number:
        verdict = "WRONG-NUMBER"
      elif not changed and _asks(reply):
        verdict = "HONEST-ASK"
      elif not changed:
        verdict = "SILENT-DROP"
      elif missed:
        verdict = "PARTIAL"
      else:
        verdict = "LANDED"
      print(f"  wrote={changed}  wrong_line={wrong_line}  wrong_number={wrong_number}")
      print(f"  VERDICT: {verdict}\n")
      VERDICTS.append((case["id"], case["pop"], verdict, changed, bool(residue), reply[:220]))
  finally:
    for draft_id in made:
      try:
        cur = conn.cursor()
        cur.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))
        conn.commit()
        cur.close()
      except Exception:
        pass
    print(f"  ({len(made)} clone(s) removed)")
    try:
      conn.close()
    except Exception:
      pass

  print("=" * 78)
  for case_id, pop, verdict, changed, residue, _reply in VERDICTS:
    print(f"  {case_id} [{pop}]: {verdict:<14} wrote={changed} residue={residue}")
  clear = [v for v in VERDICTS if v[1] == "C"]
  asked = [v for v in clear if v[2] in ("HONEST-ASK", "SILENT-DROP")]
  bad = [v for v in VERDICTS if v[2] in ("WRONG-NUMBER", "WRONG-LINE")]
  if clear:
    print(f"  CLEAR-WORDING REFUSAL RATE: {len(asked)}/{len(clear)}")
  if bad:
    print(f"  UNACCEPTABLE: {[v[0] for v in bad]} wrote a wrong number or a wrong line.")
    return 1
  print("  No wording wrote a wrong number or a wrong line.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
