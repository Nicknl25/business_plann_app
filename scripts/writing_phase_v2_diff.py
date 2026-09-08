"""THE ACCEPTANCE GATE for the v2 assembler: leaf-by-leaf equality with the
hand-built Thornfield reference, in both shapes.

    python -X utf8 scripts/writing_phase_v2_diff.py [--block meta,record,...]

Compares assemble_v1(Thornfield) to bundle_thornfield.json and the strip of
it to bundle_thornfield_v2.json. bundle_prepared is the one legal
difference (the reference says 2026-09-08; a rebuild says today).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "python")):
    if p not in sys.path:
        sys.path.insert(0, p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import mysql.connector  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from writing_phase_v2 import bundle as B  # noqa: E402

REF_DIR = r"C:\dev\Client Written Plans\_gpt_test"
IGNORE = {"/meta/bundle_prepared"}
# the v1 reference predates the 1.7 ruling and still carries discrepancies;
# the assembler NEVER builds them (QA material goes to the operator report)
IGNORE_PREFIX = ("/discrepancies",)


def leaves(o, p=""):
    out = {}
    if isinstance(o, dict):
        for k, v in o.items():
            out.update(leaves(v, p + "/" + str(k)))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            out.update(leaves(v, p + "[%d]" % i))
    else:
        out[p] = o
    return out


def diff(name, mine, ref, blocks):
    ml, rl = leaves(mine), leaves(ref)
    ml = {k: v for k, v in ml.items() if not k.startswith(IGNORE_PREFIX)}
    rl = {k: v for k, v in rl.items() if not k.startswith(IGNORE_PREFIX)}
    miss = [k for k in rl if k not in ml and not any(k in IGNORE for _ in [0])
            and k not in IGNORE]
    miss = [k for k in miss if blocks is None or k.split("/")[1] in blocks]
    extra = [k for k in ml if k not in rl and k not in IGNORE]
    extra = [k for k in extra if blocks is None or k.split("/")[1] in blocks]
    wrong = [k for k in rl if k in ml and ml[k] != rl[k] and k not in IGNORE]
    wrong = [k for k in wrong if blocks is None or k.split("/")[1] in blocks]
    scope = "all blocks" if blocks is None else ",".join(sorted(blocks))
    print(f"{name} [{scope}]: ref_leaves={len(rl)} missing={len(miss)} "
          f"extra={len(extra)} wrong={len(wrong)}")
    for label, ks in (("MISSING", miss), ("EXTRA", extra), ("WRONG", wrong)):
        for k in ks[:12]:
            got = repr(ml.get(k))[:60]
            want = repr(rl.get(k))[:60]
            print(f"  {label} {k}\n    mine={got} ref={want}")
        if len(ks) > 12:
            print(f"  ... {len(ks) - 12} more {label}")
    return not (miss or extra or wrong)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", default=None,
                    help="comma list of top-level blocks to compare (default all)")
    a = ap.parse_args()
    blocks = set(a.block.split(",")) if a.block else None

    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"))
    draft = B.load_draft(conn, "eae0ac3f")
    v1 = B.assemble_v1(conn, draft)
    ref1 = json.load(open(os.path.join(REF_DIR, "bundle_thornfield.json"), encoding="utf-8"))
    ok1 = diff("v1", v1, ref1, blocks)
    ref2 = json.load(open(os.path.join(REF_DIR, "bundle_thornfield_v2.json"), encoding="utf-8"))
    ok2 = diff("v2", B.strip_to_v2(v1), ref2, blocks)
    print("GATE:", "PASS" if ok1 and ok2 else "FAIL")
    return 0 if ok1 and ok2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
