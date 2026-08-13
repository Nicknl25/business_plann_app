"""mini, CW-031 round 9 audit, item 3: F1 residue.

  A. PATCH RATE: four blend statements, mini's own wordings, on fresh
     UNRATED Ravenwood clones (per-line rates all null, so the router's
     patch-as-fraction instruction applies). Per turn, classify:
       LANDED    - blend stored consistent with the stated figure
                   (fraction stored, or dollars basis with derived ratio)
       HONEST    - nothing stored, reply discloses the non-apply / asks
       FALSE-ACK - nothing stored, reply claims the figure  << unacceptable
  B. FALSE POSITIVES on _prose_acks_unwritten_figure:
       B1 restatement of a figure ALREADY ON FILE ("just to confirm, our
          annual revenue is 1,553,000") - must NOT be told "I haven't
          recorded that figure": it IS recorded.
       B2 a question turn asking about a number - must still quote it back.

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw031_r9_f1_residue.py"
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


def read_fin(conn, draft_id):
  try:
    conn.commit()
  except Exception:
    pass
  cur = conn.cursor()
  cur.execute("SELECT financials_json FROM intake_consult_drafts "
              "WHERE draft_id=%s", (draft_id,))
  row = cur.fetchone()
  cur.close()
  return json.loads((row[0] if row else None) or "{}")


def clone(conn):
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (SOURCE_DRAFT,))
  src = cur.fetchone()
  cur.close()
  clone_id = "m9" + uuid.uuid4().hex[:30]
  client_id = "M9" + uuid.uuid4().hex[:16].upper()
  columns = [c for c in src.keys() if c != "id"]
  values = [(clone_id if c == "draft_id" else client_id if c == "client_id" else src[c])
            for c in columns]
  write = conn.cursor()
  write.execute(
    f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) "
    f"VALUES ({', '.join(['%s'] * len(columns))})", tuple(values))
  conn.commit()
  write.close()
  return clone_id, client_id


def turn(draft_id, client_id, message):
  resp = requests.post(
    f"{BASE_URL}/api/intake-consult",
    json={"draft_id": draft_id, "client_id": client_id, "message": message},
    timeout=300)
  body = resp.json() if resp.status_code == 200 else {}
  return resp.status_code, str(body.get("assistant_message") or "")


HONEST_TOKENS = ("haven't recorded", "wasn't able", "couldn't", "didn't record",
                 "which field", "which line", "won't guess")


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  conn = get_mysql_connection()
  made, bad = [], []
  landed_n = honest_n = 0
  try:
    # ---- A: blend patch rate -------------------------------------------
    cases = (
      ("A1", "Across the whole business our direct costs come to 0.42 of revenue.", 0.42),
      ("A2", "Blended COGS runs about 45 percent of total revenue.", 0.45),
      ("A3", "Cost of goods overall is roughly 0.5 of sales.", 0.50),
      ("A4", "Set the overall COGS ratio to 0.41.", 0.41),
    )
    for case_id, message, means in cases:
      print("=" * 78)
      print(f"{case_id}: {message!r}")
      d, c = clone(conn)
      made.append(d)
      before = read_fin(conn, d)
      code, reply = turn(d, c, message)
      fin = read_fin(conn, d)
      stored = fin.get("cogs_percent_of_revenue")
      was = before.get("cogs_percent_of_revenue")
      dollars = fin.get("current_cogs")
      was_dollars = before.get("current_cogs")
      print(f"  < [{code}] {reply[:340]}")
      print(f"  stored ratio: {was} -> {stored}; dollars: {was_dollars} -> {dollars}; "
            f"basis: {fin.get('cogs_basis')}")
      moved = (
        (stored is not None and was is not None and abs(float(stored) - float(was)) > 1e-9)
        or (stored is not None and was is None)
        or (dollars is not None and was_dollars is not None
            and abs(float(dollars) - float(was_dollars)) > 0.01)
      )
      consistent = stored is not None and abs(float(stored) - means) <= 0.005
      reply_l = reply.lower()
      honest = any(tok in reply_l for tok in HONEST_TOKENS)
      if moved and consistent:
        landed_n += 1
        print(f"  CLASS: LANDED ({stored})")
      elif moved and not consistent:
        bad.append(f"{case_id}: WRONG NUMBER landed (meant {means}, "
                   f"stored ratio {stored} / dollars {dollars})")
      elif honest:
        honest_n += 1
        print("  CLASS: HONEST no-record")
      else:
        # nothing moved and no honest disclosure: did the reply claim it?
        echoes = any(tok in reply_l for tok in (
          f"{means:g}", f"{means * 100:g}%", f"{means * 100:g} percent"))
        if echoes:
          bad.append(f"{case_id}: FALSE ACK (nothing stored, reply echoes "
                     f"the figure: {reply[:160]!r})")
        else:
          honest_n += 1
          print("  CLASS: no claim, no write (counted as honest floor)")

    # ---- B1: restatement of a stored figure ----------------------------
    print("=" * 78)
    print("B1: restatement of the on-file annual revenue (no question mark)")
    d, c = clone(conn)
    made.append(d)
    before = read_fin(conn, d)
    on_file = before.get("current_revenue")
    print(f"  on file current_revenue: {on_file}")
    code, reply = turn(d, c, "Just to confirm, our annual revenue is 1,553,000.")
    fin = read_fin(conn, d)
    print(f"  < [{code}] {reply[:340]}")
    reply_l = reply.lower()
    if "haven't recorded that figure" in reply_l:
      bad.append("B1 FALSE POSITIVE: a figure that IS on file got "
                 "'I haven't recorded that figure'")
    rev_after = fin.get("current_revenue")
    if rev_after is not None and on_file is not None \
       and abs(float(rev_after) - float(on_file)) > 0.01:
      bad.append(f"B1: restatement CHANGED the stored figure ({on_file} -> {rev_after})")
    quoted = ("1,553,000" in reply) or ("1553000" in reply) or ("1.553" in reply) \
             or ("$1,553,000" in reply)
    print(f"  quoted-back: {quoted}")
    if not quoted and "match" not in reply_l and "already" not in reply_l \
       and "stays as you stated" not in reply_l:
      print("  NOTE: reply neither quotes nor references the match "
            "(not filed as a defect unless it also denies the figure)")

    # ---- B2: a question turn about a number ----------------------------
    print("=" * 78)
    print("B2: question turn - must still quote the number back")
    d, c = clone(conn)
    made.append(d)
    code, reply = turn(d, c, "What are we carrying for annual revenue right "
                             "now - is it still 1,553,000?")
    print(f"  < [{code}] {reply[:340]}")
    reply_l = reply.lower()
    quoted = ("1,553,000" in reply) or ("1553000" in reply) or ("1.553" in reply)
    if "haven't recorded that figure" in reply_l:
      bad.append("B2 FALSE POSITIVE: a question turn hit the figure gate")
    if not quoted:
      bad.append(f"B2: the answer did not quote the number back ({reply[:160]!r})")
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
  print(f"BLEND PATCH RATE: {landed_n} landed / {honest_n} honest floor "
        f"of {landed_n + honest_n} clean outcomes (4 wordings)")
  if bad:
    print("F1-RESIDUE RESULT: RED")
    for b in bad:
      print(f"  - {b}")
    return 1
  print("F1-RESIDUE RESULT: CLEAN (no wrong number, no false ack, no false positive)")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
