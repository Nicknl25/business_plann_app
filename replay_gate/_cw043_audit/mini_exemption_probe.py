"""Does the named-person exemption in enforce_labor_scaling_on_payload actually
HOLD - on drafts VS did not use, and ESPECIALLY where named payroll exceeds the
target (which is where both defects lived)?

Drives the real scaler on stored payloads with a target that FORCES a scale-down
(and one that forces a scale-UP - the 1.21-people direction), and reports whether
any key_person FTE moved. A control run on the pre-exemption behaviour is the
red side: without the exemption every named FTE moves by the factor.
(mini, 2026-08-28)

usage: python mini_exemption_probe.py [limit]
"""
import copy, json, os, sys
import mysql.connector
from dotenv import load_dotenv

ROOT = r"C:\dev\business_plann_app"
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.join(ROOT, "python", "client_intake_and_finmo"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(os.path.join(ROOT, ".env"))
from client_intake_and_finmo.post_intake_headcount import schedule as S

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 400
VS_USED = {"52cf5792", "7042ce1a", "cc8b7081", "1b9b4e45", "ecd0e148", "46ae584a"}


def L(v):
    if v is None:
        return {}
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return {}


def support_map(rows):
    out = {}
    for i, r in enumerate(rows or []):
        if isinstance(r, dict) and str(r.get("staffing_class") or "").lower() != "key_person":
            out[i] = round(float(r.get("ending_fte") or 0.0), 4)
    return out


def named_map(rows):
    out = {}
    for r in rows or []:
        if isinstance(r, dict) and str(r.get("staffing_class") or "").lower() == "key_person":
            out[(int(r.get("quarter_index") or 0), str(r.get("person_name") or r.get("position_title") or "?"))] = \
                round(float(r.get("ending_fte") or 0.0), 4)
    return out


c = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
                            password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), autocommit=True)
cur = c.cursor(dictionary=True)
cur.execute("SELECT draft_id, business_name, payroll_headcount, model_input_json FROM intake_consult_drafts "
            "WHERE payroll_headcount IS NOT NULL ORDER BY updated_at DESC LIMIT %s", (LIMIT,))
drafts = cur.fetchall(); cur.close(); c.close()
print("drafts examined:", len(drafts), flush=True)

horizon = 20
moved_down, moved_up, over_target, examined, skipped = [], [], [], 0, 0
fired_down, fired_up, no_support = 0, 0, 0
for d in drafts:
    ph = L(d["payroll_headcount"])
    rows = ph.get("rows") or []
    if not any(str(r.get("staffing_class") or "").lower() == "key_person" for r in rows if isinstance(r, dict)):
        continue
    short = str(d["draft_id"])[:8]
    qt = ph.get("quarter_totals") or []
    payload_base = {"rows": rows, "quarter_totals": qt, "schedule_horizon_quarters": horizon}

    # named payroll per quarter, and the authored total - where named EXCEEDS a
    # plausible target is the shape both defects lived on.
    named_q1 = sum(float(r.get("total_quarterly_payroll") or 0.0) for r in rows
                   if isinstance(r, dict) and str(r.get("staffing_class") or "").lower() == "key_person"
                   and int(r.get("quarter_index") or 0) == 1)
    all_q1 = next((float(x.get("payroll") or 0.0) for x in qt if int(x.get("quarter_index") or 0) == 1), 0.0)
    if named_q1 > all_q1 * 0.999 and named_q1 > 0:
        over_target.append(short)

    for label, factor, sd in (("DOWN", 0.35, True), ("UP", 2.4, False)):
        payload = copy.deepcopy(payload_base)
        before = named_map(payload["rows"])
        sbefore = support_map(payload["rows"])
        anchor = {"per_quarter": [{"q": q, "payroll_budget": max(1.0, all_q1 * factor)}
                                  for q in range(1, horizon + 1)]}
        try:
            S.enforce_labor_scaling_on_payload(payload, anchor, allow_scale_down=sd)
        except Exception as e:
            skipped += 1
            if skipped <= 2:
                print("  scaler error:", type(e).__name__, str(e)[:120], flush=True)
            break
        after = named_map(payload["rows"])
        safter = support_map(payload["rows"])
        if not sbefore:
            no_support += 1
        elif sbefore != safter:
            if label == "DOWN":
                fired_down += 1
            else:
                fired_up += 1
        diff = {k: (before[k], after[k]) for k in before if before.get(k) != after.get(k)}
        if diff:
            (moved_down if label == "DOWN" else moved_up).append(
                (short, d["business_name"], len(diff), list(diff.items())[:2]))
    examined += 1

print("\ndrafts with named people examined:", examined)
print("drafts where named payroll >= the whole authored payroll (named-heavy):", len(over_target))
print("   sample:", over_target[:14])
print("   of those, NOT used by VS:", sorted(set(over_target) - VS_USED)[:14])
print("\n=== named FTEs MOVED by a forced SCALE-DOWN (target = 35%%): %d ===" % len(moved_down))
for m in moved_down[:12]:
    print("   ", m)
print("=== named FTEs MOVED by a forced SCALE-UP (target = 240%%): %d ===" % len(moved_up))
for m in moved_up[:12]:
    print("   ", m)
print("\n=== CONTROL: did the scaler actually FIRE? ===")
print("   drafts whose SUPPORTING FTEs moved on the scale-DOWN:", fired_down)
print("   drafts whose SUPPORTING FTEs moved on the scale-UP  :", fired_up)
print("   drafts with NO supporting block at all (nothing to scale):", no_support)
if not moved_down and not moved_up:
    print("\nEXEMPTION HOLDS: not one named person's FTE moved on any draft, in either direction.")
