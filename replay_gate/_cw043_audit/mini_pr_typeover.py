"""(d)(e) type-over demos with Excel on a NEW-tree build of an untouched draft. usage: <new xlsx> <draft_prefix>"""
import sys, os, json, shutil, time, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC, D = sys.argv[1], sys.argv[2]
from dotenv import load_dotenv; load_dotenv(r"C:\dev\business_plann_app\.env")
import mysql.connector, openpyxl
import win32com.client as win32
FIRST = 27
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True); cur.execute("SELECT payroll_headcount FROM intake_consult_drafts WHERE draft_id LIKE %s", (D + '%',))
rows = [x for x in json.loads(cur.fetchone()["payroll_headcount"]).get("rows") or [] if isinstance(x, dict)]; cur.close(); c.close()
# layout via openpyxl
F = openpyxl.load_workbook(SRC); ws = F["Payroll Schedule"]; fin = F["FINMO"]
lab = {str(ws.cell(r, 1).value).strip(): r for r in range(1, FIRST) if isinstance(ws.cell(r, 1).value, str)}
TP, TE = lab["Total Payroll"], lab["Total Ending FTE"]
hdr = None
for r in range(1, 8):
    for cc in range(1, 40):
        v = ws.cell(r, cc).value
        if v == "Q1" or (v == 1 and "Q" in str(ws.cell(r, cc).number_format)):
            hdr = (r, cc); break
    if hdr: break
HR, C1 = hdr  # Q1 column
QCOL = {q: C1 + q - 1 for q in range(1, 21)}
finlab = {str(fin.cell(r, 1).value).strip(): r for r in range(1, fin.max_row + 1) if isinstance(fin.cell(r, 1).value, str)}
FIN_ROWS = {k: r for k, r in finlab.items() if "payroll" in k.lower()}
fhdr = None
for r in range(1, 8):
    for cc in range(1, 40):
        v = fin.cell(r, cc).value
        if v == "Q1" or (v == 1 and "Q" in str(fin.cell(r, cc).number_format)):
            fhdr = (r, cc); break
    if fhdr: break
FQCOL = {q: fhdr[1] + q - 1 for q in range(1, 21)}
print(f"layout: Total Payroll r{TP}, Total Ending FTE r{TE}, Q1 col {C1} (hdr row {HR}); FINMO payroll rows {FIN_ROWS} Q1 col {fhdr[1]}")
# role map
keyrows = collections.defaultdict(dict); seen = {}; cq = None
for i, x in enumerate(rows):
    q = int(x.get("quarter_index") or 0)
    if q != cq:
        cq, seen = q, {}
    bk = (str(x.get("staffing_class") or "").strip(), str(x.get("position_title") or "").strip(), str(x.get("person_name") or "").strip())
    o = seen.get(bk, 0); seen[bk] = o + 1
    keyrows[bk + (o,)][q] = (FIRST + i, x)
role = next(k for k, v in keyrows.items() if len(v) == 20)
R = keyrows[role]
eng = {q: {f: float(R[q][1].get(f) or 0) for f in ("starting_fte", "hires", "annual_wage", "payroll_taxes_benefits_percent")} for q in range(1, 21)}
print("role:", role, "rows", {q: R[q][0] for q in (1, 7, 10, 20)})

x = win32.gencache.EnsureDispatch("Excel.Application"); x.Visible = False; x.DisplayAlerts = False


def open_copy(tag):
    p = os.path.join(os.path.dirname(SRC), f"typeover_{tag}.xlsx"); shutil.copy(SRC, p)
    w = x.Workbooks.Open(p)
    for _ in range(20):
        try:
            w.Sheets(1).Name; break
        except Exception:
            time.sleep(1.0)
    return w


def read(w):
    p = w.Worksheets("Payroll Schedule"); f = w.Worksheets("FINMO"); k = w.Worksheets("Checks")
    tp = {q: float(p.Cells(TP, QCOL[q]).Value or 0) for q in range(1, 21)}
    te = {q: float(p.Cells(TE, QCOL[q]).Value or 0) for q in range(1, 21)}
    fr = {lab: {q: float(f.Cells(r, FQCOL[q]).Value or 0) for q in range(1, 21)} for lab, r in FIN_ROWS.items()}
    return tp, te, fr, k.Range("B2").Value


w = open_copy("base"); x.CalculateFullRebuild(); base_tp, base_te, base_fin, base_b2 = read(w); w.Close(False)
print("baseline Checks!B2:", base_b2)
ok_all = True

# ---- (d1) wage typed at Q7 ----
w = open_copy("wage"); p = w.Worksheets("Payroll Schedule")
W = eng[7]["annual_wage"] + 5000.0
p.Cells(R[7][0], 9).Value = W; x.CalculateFullRebuild()
exp = {}; v = W
for q in range(7, 21):
    if q > 7:
        dlt = eng[q]["annual_wage"] - eng[q - 1]["annual_wage"]
        v = v if abs(dlt) <= 1e-9 else round(v + dlt, 6)
    exp[q] = v
got = {q: float(p.Cells(R[q][0], 9).Value) for q in range(7, 21)}
bumps = [q for q in range(8, 21) if exp[q] != exp[q - 1]]
same = all(got[q] == exp[q] for q in exp)
print(f"(d1) wage typed {W} at Q7 row {R[7][0]}: I carries to Q20 with the engine's bumps on top, float-exact: {same}; bump quarters {bumps}; Q20 typed-chain={got[20]} engine={eng[20]['annual_wage']} (delta carried {got[20]-eng[20]['annual_wage']})")
untouched = all(float(p.Cells(R[q][0], 9).Value) == eng[q]["annual_wage"] for q in range(1, 7))
tp, te, fr, b2 = read(w)
exp_d = {q: ((eng[q]["starting_fte"] + eng[q]["starting_fte"] + eng[q]["hires"]) / 2) * (exp[q] - eng[q]["annual_wage"]) / 4 * (1 + eng[q]["payroll_taxes_benefits_percent"]) for q in range(7, 21)}
tp_ok = all(abs((tp[q] - base_tp[q]) - exp_d[q]) <= 1e-6 * max(1, abs(exp_d[q])) for q in range(7, 21)) and all(tp[q] == base_tp[q] for q in range(1, 7))
fin_ok = {lab: all(abs((fr[lab][q] - base_fin[lab][q]) - exp_d[q]) <= 1e-6 * max(1, abs(exp_d[q])) for q in range(7, 21)) for lab in fr}
print(f"(d1) Q1-Q6 untouched {untouched}; Total Payroll moved by exactly avgFTE*dW/4*(1+ben) Q7-Q20 and 0 before: {tp_ok} (Q7 delta {tp[7]-base_tp[7]:.2f} exp {exp_d[7]:.2f}; Q20 delta {tp[20]-base_tp[20]:.2f} exp {exp_d[20]:.2f}); FINMO rows moved by the same: {fin_ok}; Checks!B2 {b2}")
ok_all &= same and untouched and tp_ok and all(fin_ok.values())
w.Close(False)

# ---- (d2) Starting FTE typed at Q10 ----
w = open_copy("fte"); p = w.Worksheets("Payroll Schedule")
S0 = eng[10]["starting_fte"] + 1.0
p.Cells(R[10][0], 5).Value = S0; x.CalculateFullRebuild()
exp_s = {}; s = S0
for q in range(10, 21):
    if q > 10:
        s = round(exp_s[q - 1] + eng[q - 1]["hires"], 6)
    exp_s[q] = s
got_s = {q: float(p.Cells(R[q][0], 5).Value) for q in range(10, 21)}
same_s = all(got_s[q] == exp_s[q] for q in exp_s)
hires_later = [q for q in range(10, 20) if eng[q]["hires"]]
print(f"(d2) Starting FTE typed {S0} at Q10 row {R[10][0]}: E carries to Q20 with later hires on top, float-exact: {same_s}; hire quarters after Q10 {hires_later}; Q20 typed-chain={got_s[20]} engine={eng[20]['starting_fte']}")
tp, te, fr, b2 = read(w)
exp_d2 = {q: ((exp_s[q] - eng[q]["starting_fte"])) * eng[q]["annual_wage"] / 4 * (1 + eng[q]["payroll_taxes_benefits_percent"]) for q in range(10, 21)}  # avg delta = start delta (hires unchanged)
tp_ok2 = all(abs((tp[q] - base_tp[q]) - exp_d2[q]) <= 1e-6 * max(1, abs(exp_d2[q])) for q in range(10, 21)) and all(tp[q] == base_tp[q] for q in range(1, 10))
te_ok2 = all(abs((te[q] - base_te[q]) - (exp_s[q] - eng[q]["starting_fte"])) <= 1e-9 for q in range(10, 21))
fin_ok2 = {lab: all(abs((fr[lab][q] - base_fin[lab][q]) - exp_d2[q]) <= 1e-6 * max(1, abs(exp_d2[q])) for q in range(10, 21)) for lab in fr}
print(f"(d2) Total Payroll moved by dFTE*wage/4*(1+ben) Q10-Q20, 0 before: {tp_ok2}; Total Ending FTE moved by dFTE: {te_ok2}; FINMO rows moved by the same: {fin_ok2}; Checks!B2 {b2}")
ok_all &= same_s and tp_ok2 and te_ok2 and all(fin_ok2.values())
w.Close(False)

# ---- (e) tamper B/C/N text: nothing computed moves ----
w = open_copy("tamper"); p = w.Worksheets("Payroll Schedule")
for cc in (2, 3, 14):
    p.Cells(R[7][0], cc).Value = "ZZZ TAMPER"
x.CalculateFullRebuild(); tp, te, fr, b2 = read(w)
tam_ok = tp == base_tp and te == base_te and fr == base_fin and b2 == base_b2
print(f"(e) B/C/N text typed over at row {R[7][0]}: Total Payroll/Total Ending FTE/FINMO/Checks!B2 all unchanged: {tam_ok}")
ok_all &= tam_ok
w.Close(False)
# ---- (e2) the Checks payroll tie-out keys on numeric A: type a Hires into an amber literal, Checks stays OK-consistent ----
w = open_copy("hires"); p = w.Worksheets("Payroll Schedule"); k = w.Worksheets("Checks")
before = [k.Cells(r, 9).Value for r in range(7, 60)]
p.Cells(R[5][0], 6).Value = eng[5]["hires"] + 0.5; x.CalculateFullRebuild()
after = [k.Cells(r, 9).Value for r in range(7, 60)]
tp2, te2, _, _ = read(w)
print(f"(e2) Hires +0.5 typed at Q5: Total Ending FTE Q5..Q20 all +0.5 (chain carried it): {all(abs((te2[q]-base_te[q])-0.5)<=1e-9 for q in range(5,21))}; Checks statuses unchanged (tie-outs still reconcile through the chain): {before == after}")
ok_all &= before == after
w.Close(False)
x.Quit()
print("TYPEOVER ALL OK:", bool(ok_all))
