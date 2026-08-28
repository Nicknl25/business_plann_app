"""Revert half A (the key_person exemption) and/or half B (supporting-only factor solve)
in a worktree's schedule.py. usage: revert.py <wt_root> <A|B|AB|none>"""
import sys, io, os
root, mode = sys.argv[1], sys.argv[2]
p = os.path.join(root, "python", "client_intake_and_finmo", "post_intake_headcount", "schedule.py")
orig = open(p, "r", encoding="utf-8").read()
src = orig

HALF_A_NEW = '''  for r in rows:
    if str(r.get("staffing_class") or "").strip().lower() == "key_person":
      continue
    key = (
      str(r.get("position_title") or ""),
'''
HALF_A_OLD = '''  for r in rows:
    key = (
      str(r.get("position_title") or ""),
'''

HALF_B_NEW = '''  named_payroll_by_q: Dict[int, float] = {}
  for r in (payload.get("rows") or []):
    if not isinstance(r, dict):
      continue
    if str(r.get("staffing_class") or "").strip().lower() != "key_person":
      continue
    q_ = int(_safe_float(r.get("quarter_index")) or 0)
    named_payroll_by_q[q_] = named_payroll_by_q.get(q_, 0.0) + float(
      _safe_float(r.get("total_quarterly_payroll")) or 0.0
    )
  factor_by_q: Dict[int, float] = {}
  prev = 1.0
  for q in range(1, horizon + 1):
    authored_all = _safe_float((qt_by_q.get(q) or {}).get("payroll")) or 0.0
    named_q = named_payroll_by_q.get(q, 0.0)
    authored = max(0.0, authored_all - named_q)
    target_all = target_by_q.get(q)
    target = None if target_all is None else max(0.0, float(target_all) - named_q)
    f = 1.0
'''
HALF_B_OLD = '''  factor_by_q: Dict[int, float] = {}
  prev = 1.0
  for q in range(1, horizon + 1):
    authored = _safe_float((qt_by_q.get(q) or {}).get("payroll")) or 0.0
    target = target_by_q.get(q)
    f = 1.0
'''

def swap(s, new, old, label):
    assert s.count(new) == 1, f"{label}: expected exactly 1 occurrence, found {s.count(new)}"
    return s.replace(new, old)

if "A" in mode:
    src = swap(src, HALF_A_NEW, HALF_A_OLD, "half A")
if "B" in mode:
    src = swap(src, HALF_B_NEW, HALF_B_OLD, "half B")
open(p, "w", encoding="utf-8", newline="").write(src)
print(f"reverted {mode} in {p} ({len(orig)} -> {len(src)} bytes)")
