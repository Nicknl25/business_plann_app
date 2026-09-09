import json, sys
a = json.load(open(sys.argv[1], encoding="utf-8")); b = json.load(open(sys.argv[2], encoding="utf-8"))
def leaves(o, p="", out=None):
    out = {} if out is None else out
    if isinstance(o, dict):
        for k, v in o.items(): leaves(v, f"{p}.{k}" if p else k, out)
    elif isinstance(o, list):
        for i, v in enumerate(o): leaves(v, f"{p}[{i}]", out)
    else: out[p] = o
    return out
for key in ("model_input", "finmo"):
    A, B = leaves(a[key]), leaves(b[key])
    added = sorted(set(B) - set(A)); removed = sorted(set(A) - set(B))
    changed = sorted(k for k in set(A) & set(B) if A[k] != B[k])
    print(f"{key}: A={len(A)} B={len(B)} shared_identical={len(set(A)&set(B))-len(changed)} ADDED={len(added)} CHANGED={len(changed)} REMOVED={len(removed)}")
    for k in changed: print("  CHANGED", k, A[k], "->", B[k])
    for k in removed: print("  REMOVED", k)
    vals = {B[k] for k in added}; names = {k.rsplit(".",1)[-1] for k in added}
    print(f"  added leaf names={names} values={vals}")
    tops = sorted({k.split(".quarter_logs")[0] for k in added}); print("  added under:", tops)
