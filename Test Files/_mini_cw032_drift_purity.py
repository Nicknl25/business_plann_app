# -*- coding: utf-8 -*-
"""CW-032 turn 1 (mini): R31 DRIFT PURITY PROOF.

Nick ratified the R31 move as the ruled opening-PPE depreciation landing
(7b26ff6). Ratification covers WHY the numbers moved; this script proves
ONLY those numbers moved. It rebuilds the R31 golden payloads through the
gate's own frozen path (surface.single_line_payloads - committed fixture,
frozen lookups, frozen anchor) at TWO roots:

    OLD = the R31 baseline worktree (9d2c41c, pre-depreciation)
    NEW = the home repo at HEAD (post-depreciation)

verifies the four digests equal EXACTLY the ones the DRIFT report printed
(so we are diffing the very bytes that drifted, not a reconstruction), then
walks both JSON trees leaf by leaf and prints EVERY differing leaf path.

Usage (run once per root, then diff):
    python "Test Files/_mini_cw032_drift_purity.py" --root <tree> --out <dir>
    python "Test Files/_mini_cw032_drift_purity.py" --diff <old_dir> <new_dir>
"""
import argparse
import hashlib
import json
import os
import sys

HOME = r"C:\dev\business_plann_app"


def canon_sha(payload):
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def dump(root, out_dir):
    sys.path.insert(0, HOME)
    from replay_gate import _bootstrap
    _bootstrap.utf8_stdout()
    _bootstrap.bind_root(root)
    from replay_gate.context import GateContext

    ctx = GateContext(None, None)
    draft, mij, finmo, note = ctx.single_line_payloads()
    if not draft or mij is None or finmo is None:
        print(f"SETUP FAILURE at root {root}: {note}")
        return 2

    os.makedirs(out_dir, exist_ok=True)
    for name, payload in (("model_input", mij), ("finmo", finmo)):
        path = os.path.join(out_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True, indent=1, default=str)
        print(f"SHA {name} {canon_sha(payload)}")
    print(f"SHA single_line_input {ctx.draft_input_sha}")
    print(f"note: {note}")
    return 0


def _leaves(node, prefix, acc):
    if isinstance(node, dict):
        for k in sorted(node):
            _leaves(node[k], f"{prefix}.{k}" if prefix else str(k), acc)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _leaves(v, f"{prefix}[{i}]", acc)
    else:
        acc[prefix] = node


def diff(old_dir, new_dir):
    rc = 0
    for name in ("model_input", "finmo"):
        with open(os.path.join(old_dir, f"{name}.json"), encoding="utf-8") as fh:
            old = json.load(fh)
        with open(os.path.join(new_dir, f"{name}.json"), encoding="utf-8") as fh:
            new = json.load(fh)
        a, b = {}, {}
        _leaves(old, "", a)
        _leaves(new, "", b)
        added = sorted(set(b) - set(a))
        removed = sorted(set(a) - set(b))
        changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        print(f"\n=== {name}: {len(changed)} changed, {len(added)} added, "
              f"{len(removed)} removed (of {len(a)} old / {len(b)} new leaves) ===")
        for k in changed:
            print(f"  CHANGED {k}: {a[k]!r} -> {b[k]!r}")
        for k in added:
            print(f"  ADDED   {k}: {b[k]!r}")
        for k in removed:
            print(f"  REMOVED {k}: {a[k]!r}")
        if added or removed or changed:
            rc = 1
    return rc


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root")
    p.add_argument("--out")
    p.add_argument("--diff", nargs=2)
    args = p.parse_args()
    if args.diff:
        return diff(*args.diff)
    if not (args.root and args.out):
        p.error("--root/--out or --diff required")
    return dump(args.root, args.out)


if __name__ == "__main__":
    sys.exit(main())
