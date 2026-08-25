"""text-surface (R49) dump + diff for two roots, modeled on replay_gate._grid_dump. usage: <rootA> <rootB>
Writes txt_<basename>.json beside itself for each root and classifies every touched cell."""
import collections, hashlib, json, os, re, subprocess, sys
HOME = r"C:\dev\business_plann_app"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)


def child(root):
    root = os.path.abspath(root)
    from replay_gate import _bootstrap
    _bootstrap.bind_root(root)
    import client_statements_output_excel as pkg
    got = os.path.abspath(os.path.dirname(pkg.__file__)); want = os.path.abspath(os.path.join(root, "client_statements_output_excel"))
    assert os.path.normcase(got) == os.path.normcase(want), f"PROVENANCE FAIL {got} != {want}"
    from client_statements_output_excel import data as wbdata, workbook_builder
    from replay_gate.context import GateContext
    ctx = GateContext(None, None)
    surf = ctx.workbook_text_surface(builder=workbook_builder.build_client_financial_model_workbook, from_row=wbdata.draft_data_from_row)
    if not surf:
        raise SystemExit("no surface: " + str(getattr(ctx, "text_gap", "")))
    sys.stdout.write("@@TXT@@" + json.dumps(surf, sort_keys=True, default=str))


def get(root):
    p = subprocess.run([sys.executable, __file__, "--child", root], cwd=HOME, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if "@@TXT@@" not in (p.stdout or ""):
        raise SystemExit(f"dump failed {root}: {(p.stderr or p.stdout)[-800:]}")
    surf = json.loads(p.stdout.split("@@TXT@@", 1)[1])
    blob = json.dumps(surf, sort_keys=True, separators=(",", ":"), default=str)
    sha = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    json.dump(surf, open(os.path.join(HERE, "txt_" + os.path.basename(os.path.abspath(root)) + ".json"), "w", encoding="utf-8"), sort_keys=True)
    leaves = {(s, a): t for s, cells in surf.items() for a, t in cells.items()}
    print(f"ROOT {root}\nSHA  {sha}\nTEXT {len(leaves)} cells across {len(surf)} sheets")
    return leaves


def up(k, dr):
    m = re.match(r"([A-Z]+)(\d+)", k[1]); return (k[0], f"{m.group(1)}{int(m.group(2)) + dr}")


if sys.argv[1] == "--child":
    child(sys.argv[2]); sys.exit(0)
O, N = get(sys.argv[1]), get(sys.argv[2])
touched = sorted(k for k in set(O) | set(N) if O.get(k) != N.get(k))
gone = [k for k in touched if k not in N]; added = [k for k in touched if k not in O]; chg = [k for k in touched if k in O and k in N]
print(f"\nDIFF shared={len(set(O) & set(N))} changed={len(chg)} gone={len(gone)} added={len(added)}  (total touched {len(touched)})")
print("by sheet:", dict(collections.Counter(k[0] for k in touched)))
cls = collections.Counter(); ex = collections.defaultdict(list)
for k in touched:
    if k[0] == "Checks":
        if N.get(k) is not None and N.get(k) == O.get(up(k, 1)):
            kind = "moved-up-1: new text == old text one row below"
        elif N.get(k) is None and O.get(k) == N.get(up(k, -1)):
            kind = "moved-up-1: last row fell off (old text now one row above)"
        else:
            kind = "OTHER"
    else:
        kind = "sheet-text"
    cls[(k[0], kind)] += 1
    if not kind.startswith("moved-up-1: new"):
        ex[(k[0], kind)].append((k[1], str(O.get(k))[:90], str(N.get(k))[:90]))
for k, v in sorted(cls.items()):
    print("  ", v, k)
for k, v in ex.items():
    print(k)
    for x in v[:40]:
        print("     ", x)
print("old tie-out label at:", [k for k, t in O.items() if t == "Lease/rent feeds Model Inputs"], "| in new:", [k for k, t in N.items() if t == "Lease/rent feeds Model Inputs"])
