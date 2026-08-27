import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
o = json.load(open(sys.argv[1])); n = json.load(open(sys.argv[2]))
com = [d for d in n if d in o]
# VS's framing: drafts where the OLD scaler moved a NAMED FULL-TIMER (fte >= 1 before)
movedfull = [d for d in com if any(round(e[2],4) >= 0.999 for e in (o[d].get("moved_examples") or []))]
print(f"drafts driven (both trees): {len(com)}")
print(f"drafts where the OLD scaler moved a named row at all: {sum(1 for d in com if o[d].get('named_rows_moved'))}")
print(f"  ... of which a named FULL-TIMER (>=1.0 before) was moved (sampled examples): {len(movedfull)}")
newly = [d for d in com if n[d].get('over_target_quarters',0) > 0 and o[d].get('over_target_quarters',0) == 0]
print(f"drafts NEWLY over target (old: none, new: >=1 quarter): {len(newly)} {newly[:10]}")
worse = [d for d in com if n[d].get('over_target_quarters',0) > o[d].get('over_target_quarters',0)]
expl = [d for d in worse if n[d].get('over_but_named_alone_exceeds',0) > 0]
print(f"drafts over target in MORE quarters on new: {len(worse)}; of those, any quarter where NAMED PAYROLL ALONE exceeds target: {len(expl)}")
print(f"drafts (any tree) with a quarter where named payroll alone exceeds target, new tree: {sum(1 for d in com if n[d].get('over_but_named_alone_exceeds',0))}")
