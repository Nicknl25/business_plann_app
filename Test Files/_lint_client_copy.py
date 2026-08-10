# -*- coding: utf-8 -*-
"""CW-024 Item 9: forbidden-vocabulary lint over client-facing copy.

Nick-ruled ban list for anything a client can read: "judged",
"believable", "range" as a noun-of-record ("believable range"/"judged
range"), raw field names, "plan builder". The lint walks the AST of the
modules that produce client-visible sentences and flags banned tokens in
any string literal that looks like client copy (>= 6 words). Docstrings
are excluded; comments never reach the AST. Internal keys are too short
to trip the sentence heuristic.

This is a PIN, not a one-time sweep: new copy that reintroduces the
vocabulary fails this test.
"""
import ast
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "python"

MODULES = [
  ROOT / "client_intake_and_finmo" / "intake_coherence" / "section.py",
  ROOT / "client_intake_and_finmo" / "intake_coherence" / "controller.py",
  ROOT / "client_intake_and_finmo" / "capture_receipt.py",
  ROOT / "api_handlers" / "intake_consult.py",
]

BANNED = [
  (re.compile(r"\bjudged\b", re.I), '"judged"'),
  (re.compile(r"\bbelievable\b", re.I), '"believable"'),
  (re.compile(r"\bplan builder\b", re.I), '"plan builder"'),
  # Raw store field names a client must never see (CW-024 #89 class).
  (re.compile(
    r"\b(current_payroll|current_revenue|current_cogs|owner_compensation|"
    r"marketing_total_year1|payroll_total_year1|cogs_total_year1|"
    r"baseline_[a-z_]+|payroll_adjustment|marketing_adjustment|"
    r"cogs_adjustment|units_per_week_capacity|units_per_period_capacity|"
    r"cogs_percent_of_revenue|utilization_rate|rest_of_team_payroll_year1)\b"
  ), "raw field name"),
]

_WORDS = re.compile(r"[A-Za-z']+")

# Internal-audience strings (prompts to GPT arbiters, never rendered to
# the client). Each entry must name its audience; anything not listed
# and sentence-shaped is treated as client copy.
ALLOWLIST = [
  # section.py: burden-ceiling basis-contradiction re-author prompt —
  # addressed to the band AUTHOR (GPT arbitration), not the client.
  ("section.py", re.compile(r"implies a business obeying your ceiling")),
]


def _docstring_nodes(tree):
  out = set()
  for node in ast.walk(tree):
    if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
      body = getattr(node, "body", [])
      if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
         and isinstance(body[0].value.value, str):
        out.add(id(body[0].value))
  return out


def lint_module(path):
  src = path.read_text(encoding="utf-8-sig")
  tree = ast.parse(src)
  doc_ids = _docstring_nodes(tree)
  flags = []
  for node in ast.walk(tree):
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
      continue
    if id(node) in doc_ids:
      continue
    text = node.value
    # Client-copy heuristic: sentences, not keys/labels/format fragments.
    if " " not in text or len(_WORDS.findall(text)) < 6:
      continue
    if any(fn == path.name and rx.search(text) for fn, rx in ALLOWLIST):
      continue
    for pattern, name in BANNED:
      m = pattern.search(text)
      if m:
        flags.append((path.name, node.lineno, name, text.strip()[:110]))
  return flags


def main():
  all_flags = []
  for mod in MODULES:
    all_flags.extend(lint_module(mod))
  if all_flags:
    print("FORBIDDEN VOCABULARY IN CLIENT COPY:")
    for fname, line, token, snippet in all_flags:
      print(f"  {fname}:{line} [{token}] {snippet!r}")
    print(f"FAIL: {len(all_flags)} banned-vocabulary hits")
    return 1
  print("PASS: no banned vocabulary in client-facing copy "
        f"({len(MODULES)} modules)")
  return 0


if __name__ == "__main__":
  sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
  sys.exit(main())
