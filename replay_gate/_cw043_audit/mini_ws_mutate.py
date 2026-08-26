"""mini (e) for F3 (236ac8b): does tests/test_cw043_payroll_chain_grid.py now catch a bridge column pointed at a same-title
twin's block? Tampers are applied to a scratch HEAD WORKTREE's schedule_sheets.py (never the real tree), anchored on the NEW
column-14 line `_text_ref(R["Wage source"], qcol)`, and reverted with git checkout.   usage: <wt_head>"""
import sys, os, subprocess, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
WT = sys.argv[1]
PY = r"C:\dev\business_plann_app\.venv\Scripts\python.exe"
SS = os.path.join(WT, "client_statements_output_excel", "schedule_sheets.py")
TEST = "tests/test_cw043_payroll_chain_grid.py"
ANCHOR = '    ws.cell(row=row, column=14, value=_text_ref(R["Wage source"], qcol))\n'
TWIN = '    _R2 = next(v for k_, v in role_layout.items() if k_[:2] == base_key[:2])\n'
F3 = "test_every_bridge_cell_points_at_its_own_identitys_block"
F1 = "test_the_bridge_wage_source_follows_the_quarter_not_the_role"
WAGE = "test_every_bridge_row_points_at_its_own_persons_block"


def pytest_in_wt(tag):
    p = subprocess.run([PY, "-m", "pytest", TEST, "-q", "-p", "no:cacheprovider"], cwd=WT, capture_output=True, text=True, timeout=900)
    tail = [l for l in p.stdout.splitlines() if re.search(r"passed|failed|error", l)]
    fails = [l.strip() for l in p.stdout.splitlines() if l.startswith("FAILED") or l.startswith("ERROR")]
    names = {l.split("::")[-1].split(" ")[0] for l in fails}
    print(f"   [{tag}] rc={p.returncode} {tail[-1] if tail else p.stdout[-300:]}")
    for f in fails[:6]:
        print("      ", f[:170])
    print(f"      F3 own-identity test RED={F3 in names}; F1 wage-source-per-quarter test RED={F1 in names}; wage-only test RED={WAGE in names}")
    return p.returncode, names


def patch(old, new, count=1):
    src = open(SS, encoding="utf-8").read()
    assert src.count(old) == count, (old, src.count(old))
    open(SS, "w", encoding="utf-8").write(src.replace(old, new))


def restore():
    subprocess.run(["git", "checkout", "--", "client_statements_output_excel/schedule_sheets.py"], cwd=WT, check=True, capture_output=True)
    assert open(SS, encoding="utf-8").read().count(ANCHOR) == 1


res = {}
print("== T0 baseline in the worktree")
res["T0"] = pytest_in_wt("baseline")[0]

print("== T2 ONLY the bridge Starting FTE column points at the first same-title block; every other column right")
patch(ANCHOR, ANCHOR + TWIN + '    ws.cell(row=row, column=5, value=f"={local_ref(_R2[\'Starting FTE\'], qcol)}")\n')
res["T2"] = pytest_in_wt("T2 twin Starting FTE")
restore()

print("== T3a ONLY the bridge Total Payroll column (M) points at the twin's block")
patch(ANCHOR, ANCHOR + TWIN + '    ws.cell(row=row, column=13, value=f"={local_ref(_R2[\'Total Payroll\'], qcol)}")\n')
res["T3a"] = pytest_in_wt("T3a twin Total Payroll")
restore()

print("== T3b text column N (Wage source) points at the twin's block, same quarter column")
patch(ANCHOR, TWIN + '    ws.cell(row=row, column=14, value=_text_ref(_R2["Wage source"], qcol))\n')
res["T3b"] = pytest_in_wt("T3b twin Wage source")
restore()

print("== T3c text column D (OEWS title) points at the twin's block")
patch(ANCHOR, ANCHOR + TWIN + '    ws.cell(row=row, column=4, value=_text_ref(_R2["oews"], 2))\n')
res["T3c"] = pytest_in_wt("T3c twin OEWS")
restore()

print("== T3d column N on the OWN block but the PREVIOUS quarter column (the per-role collapse, one column back)")
patch(ANCHOR, '    ws.cell(row=row, column=14, value=_text_ref(R["Wage source"], max(qcol - 1, PERIOD_START_COL + 1)))\n')
res["T3d"] = pytest_in_wt("T3d own block, wrong quarter")
restore()

print("== T3e text columns B/C (Title, Class) point at the twin's header")
patch(ANCHOR, ANCHOR + TWIN + '    ws.cell(row=row, column=2, value=_text_ref(_R2["header"], 2))\n    ws.cell(row=row, column=3, value=_text_ref(_R2["header"], 1))\n')
res["T3e"] = pytest_in_wt("T3e twin Title/Class")
restore()

print("\nT-SUMMARY", {k: (v if isinstance(v, int) else (v[0], sorted(v[1]))) for k, v in res.items()})
