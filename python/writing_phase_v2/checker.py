"""THE CHECKER (stage 3) - deterministic; every number resolves or is a
finding. Faithful port of the kit's check_plan_v2.py (2026-09-08, including
the two approved fixes: sections judged by blocks, utf-8 file handling);
refactored only from print-to-stdout into a findings list so the editor and
the pipeline consume the same output. Change the kit copy and this together
until the kit is retired.
"""
from __future__ import annotations

import bisect
import json
import re
from typing import Any, Dict, List, Tuple

NUM = re.compile(r'(?<![\w.])(\$?)(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*'
                 r'(million|thousand|%|×|x\b|K\b|k\b)?', re.I)
YEAR = re.compile(r'^(19[5-9]\d|20[0-4]\d)$')
PUB = re.compile(r'census|bureau of labor|bls|oews|fred|federal reserve|sba|'
                 r'small business administration|irs|internal revenue|'
                 r'county business patterns|business dynamics|'
                 r'american community survey|acs\b', re.I)
VINT = re.compile(r'(19|20)\d{2}')
OWN = re.compile(r"owner|client|stated|projection|the plan|assessment|judg", re.I)
# absence language is banned about OUR DATA, never about the world (Nick
# 2026-09-08, after 'unavailable' caught a key EMPLOYEE three times: a plan
# that cannot say a person may be unavailable cannot write key-person risk).
# Bare 'unavailable'/'not available' are legal; the ban holds when the
# absence is about data, figures, information, records or estimates.
_DATAISH = r'(?:data|figures?|information|records?|estimates?|statistics)'
BAD = re.compile(r'\b(the model\b|modell?ed\b|engine|solver|pipeline|NAICS|lookup|'
                 r'bundle|the record\b|administrative record|intake|discrepanc\w*|'
                 r'reconcil\w*|rescal\w*|prepared for this plan|the assessment|'
                 r'the analysis|the review|executive[- ]judged|misclassif\w*|'
                 + _DATAISH + r'[^.]{0,30}(?:unavailable|not available)|'
                 r'(?:unavailable|not available)[^.]{0,30}' + _DATAISH + r'|'
                 r'no data|not provided|not computed|'
                 r'was not captured|we do not have|GPT|AI-generated|omitted from|'
                 r'omits?\b)', re.I)
# a four-digit number is only a CODE if it's used as one - years (19xx/20xx)
# near trade words are years (Nick 2026-09-08, third false-positive class);
# no NAICS sector 19 or 20 exists, so the lookahead costs nothing real
CODE = re.compile(r'\b(industry|trade|sector|classification|code)\b[^.]{0,40}'
                  r'\b(?!(?:19|20)\d{2}\b)\d{4,6}\b'
                  r'|\b(?!(?:19|20)\d{2}\b)\d{4,6}\b[^.]{0,20}'
                  r'\b(basis|classification|code)\b',
                  re.I)


# data_source parts that are internal machinery or generic words, never a
# citable publisher - 'judgment' especially must not make a judgment-citing
# note pass the publisher gate
_NOT_PUBLISHERS = {"judgment", "derived", "industry", "transaction", "reports",
                   "growth", "table", "raw"}


def _bundle_publishers(bundle: Dict[str, Any]) -> List[str]:
    """Publisher strings the bundle ITSELF cites (Nick 2026-09-08: if we
    handed the writer a source, the writer may cite it). Drawn from every
    warehouse row's data_source/source parts and the leading name segment
    of each source_citation."""
    out: set = set()
    for block in (bundle.get("warehouse") or {}).values():
        if not isinstance(block, list):
            continue
        for row in block:
            if not isinstance(row, dict):
                continue
            for field in ("data_source", "source"):
                for part in re.split(r"[_\s]+", str(row.get(field) or "")):
                    if len(part) >= 3 and part.lower() not in _NOT_PUBLISHERS:
                        out.add(part.lower())
            cite = str(row.get("source_citation") or "")
            lead = cite.split(",")[0].strip()
            if 4 <= len(lead) <= 60:
                out.add(lead.lower())
    return sorted(out)


def _signed(text: str, start: int, x: float) -> float:
    """A token written as 'negative 24.8%' or '-24.8%' means -24.8 - the
    sign lives just before the match (Nick 2026-09-08: a negative result
    about a real business must resolve). A hyphen preceded by a digit,
    %, x or letter is a RANGE hyphen ('2020-2025', '2.0x-3.5x'), never a
    sign."""
    before = text[max(0, start - 30):start]
    # accounting English carries signs in words: "a net loss of $7,009",
    # "shortfall of", "24.8% below" is BELOW-context read at the token that
    # follows. The writer did not compute anything - it rendered a negative
    # bundle value's magnitude - so the instrument reads the sign word
    # (Nick 2026-09-08: a robust pipeline must not fail at the last step
    # over the grammar of a loss).
    if re.search(r"\b(?:negative|minus|loss(?:es)?|deficit|shortfall)\b[^.;]{0,22}$",
                 before, re.I):
        return -x
    # a sign hyphen sits IMMEDIATELY before the number with whitespace (or
    # start, or an opening bracket) before it; anything else - 'net-30',
    # '2020-2025', '2.0x-3.5x' - is a compound or a range
    if before and before[-1] in "-−–":
        prev = before[:-1]
        if not prev or prev[-1] in " \t(([{":
            return -x
    return x


def _universe(bundle: Dict[str, Any], plan: Dict[str, Any]):
    vals: List[Tuple[float, str]] = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, path + '/' + str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, path + f'[{i}]')
        elif isinstance(o, bool):
            pass
        elif isinstance(o, (int, float)):
            vals.append((float(o), path))
        elif isinstance(o, str) and path.count('transcript') == 0 and len(o) < 60:
            for m in re.finditer(r'(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?%?', o):
                try:
                    vals.append((float(m.group(0).replace('$', '').replace(',', '')
                                       .replace('%', '')), path + '~str'))
                except Exception:
                    pass

    walk({k: v for k, v in bundle.items() if k != 'record'}, '')
    walk({k: v for k, v in bundle['record'].items() if k != 'transcript'}, '/record')
    deriv_vals: List[float] = []
    for d in plan.get('derivations', []):
        try:
            v = float(d['value'])
            vals.append((v, 'derivation:' + d['id']))
            deriv_vals.append(v)
        except Exception:
            pass
    for m in bundle['record']['transcript']:
        if m['role'] == 'user':
            for x in re.finditer(r'(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)', m['content']):
                v = float(x.group(1).replace(',', ''))
                vals.append((v, 'transcript:user'))
                if v < 1000:
                    vals.append((v * 1000, 'transcript:user*1000'))
    universe = (vals
                + [(v * 100, p + '*100') for v, p in vals if 0 < abs(v) <= 1.5]
                + [(v / 1e6, p + '/1e6') for v, p in vals if abs(v) >= 100000]
                + [(v / 1000, p + '/1e3') for v, p in vals if abs(v) >= 1000])
    U = sorted(universe, key=lambda t: t[0])
    keys = [u[0] for u in U]

    # DECLARED derivation values, sign-insensitively: prose carries a sign
    # lexically ("a net loss of $7,009", "negative margin of safety") that
    # token extraction cannot always see; a negative result from a declared
    # derivation resolves either way (Nick 2026-09-08). Undeclared numbers
    # get no such grace.
    dset = sorted(set(deriv_vals)
                  | {v * 100 for v in deriv_vals if 0 < abs(v) <= 1.5}
                  | {v / 1e6 for v in deriv_vals if abs(v) >= 100000}
                  | {v / 1000 for v in deriv_vals if abs(v) >= 1000})

    def nearest(x, tol_abs, tol_rel):
        i = bisect.bisect_left(keys, x - tol_abs - abs(x) * tol_rel)
        best = None
        while i < len(keys) and keys[i] <= x + tol_abs + abs(x) * tol_rel:
            d = abs(keys[i] - x)
            if best is None or d < best[0]:
                best = (d, U[i])
            i += 1
        if best:
            return best[1]
        for v in dset:
            if abs(abs(v) - abs(x)) <= tol_abs + abs(x) * tol_rel:
                return (v, 'derivation~sign')
        return None

    return nearest


def check(bundle: Dict[str, Any], plan: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Returns (findings, info_lines). Empty findings = every hard gate passed."""
    findings: List[str] = []
    info: List[str] = []
    nearest = _universe(bundle, plan)

    total = ok = 0
    for s in plan['sections']:
        for b in s['blocks']:
            texts = []
            if b['type'] == 'paragraph':
                texts.append(b.get('text', ''))
            if b['type'] == 'table_inline':
                for r in b.get('rows', []):
                    texts.extend(r)
            for text in texts:
                for m in NUM.finditer(text):
                    raw = m.group(0)
                    dollars = m.group(1) == '$'
                    whole = m.group(2).replace(',', '')
                    frac = m.group(3)
                    unit = (m.group(4) or '').lower()
                    if YEAR.match(whole) and not dollars and not unit:
                        continue
                    x = float(whole + ('.' + frac if frac else ''))
                    if unit == 'million':
                        x *= 1e6
                    if unit in ('thousand', 'k'):
                        x *= 1e3
                    if not dollars and not unit and x <= 20 and not frac:
                        continue
                    if not dollars and not unit and re.search(r'\bQ' + whole + r'\b', text):
                        continue
                    total += 1
                    # a sign word makes the NEGATIVE reading primary, the
                    # positive a fallback - the word may govern an adjacent
                    # concept, never fail a number that resolves as written
                    x_signed = _signed(text, m.start(), x)
                    candidates = (x_signed,) if x_signed == x else (x_signed, x)

                    def _resolve(x):
                        if unit == '%':
                            return (nearest(x, 0.06 if frac else 0.6, 0.0)
                                    or nearest(x / 100, 0.0006 if frac else 0.006, 0.0))
                        if unit in ('×', 'x'):
                            return nearest(x, 0.06, 0.0)
                        if dollars:
                            if unit == 'million':
                                tol_abs = 0.5 * 10 ** (6 - len(frac or ''))
                            else:
                                tol_abs = (0.5e4 if abs(x) >= 1e6
                                           else (0.5e3 if abs(x) >= 10000 else 0.5))
                            return nearest(x, tol_abs, 0.0)
                        return nearest(x, 0.5 if not frac else 0.06, 0.0)

                    hit = None
                    for cand in candidates:
                        hit = _resolve(cand)
                        if hit:
                            break
                    if hit:
                        ok += 1
                    else:
                        findings.append(f"unresolved number [{s['key']}] {raw.strip()!r} :: {text[:140]}")
    info.append(f'numbers checked: {total}; resolved: {ok}; unresolved: {total - ok}')

    ids = {n['id'] for n in plan.get('notes', [])}
    used = set()
    for s in plan['sections']:
        for b in s['blocks']:
            if b['type'] == 'paragraph':
                used.update(re.findall(r'\[\^(\d+)\]', b.get('text', '')))
    for i in sorted(used - ids, key=int):
        findings.append(f'note marker [^{i}] has no note')
    for i in sorted(ids - used, key=int):
        findings.append(f'note {i} is never marked in the prose')
    handed = _bundle_publishers(bundle)
    for n in plan.get('notes', []):
        t = n['text']
        tl = t.lower()
        pub_ok = bool(PUB.search(t)) or any(h in tl for h in handed)
        if not pub_ok:
            findings.append(f"note {n['id']} names no public publisher: {t[:100]}")
        if not VINT.search(t):
            findings.append(f"note {n['id']} has no vintage: {t[:100]}")
        if OWN.search(t) and not pub_ok:
            findings.append(f"note {n['id']} cites the owner or the projections: {t[:100]}")
    sn = [x for x in plan['sections'] if x['key'] == 'sources_and_notes']
    if sn and sn[0]['blocks']:
        findings.append('sources_and_notes contains blocks (must be empty): %d'
                        % len(sn[0]['blocks']))
    info.append('notes: %d' % len(plan.get('notes', [])))

    if 'discrepancies_addressed' in plan:
        findings.append('plan carries discrepancies_addressed - contract v2 has no such field')

    for s in plan['sections']:
        for b in s['blocks']:
            if b['type'] == 'paragraph':
                for m in BAD.finditer(b.get('text', '')):
                    findings.append(f"vocabulary [{s['key']}]: "
                                    f"...{b['text'][max(0, m.start() - 60):m.end() + 40]}...")
                for m in CODE.finditer(b.get('text', '')):
                    findings.append(f"industry code in prose [{s['key']}]: "
                                    f"...{b['text'][max(0, m.start() - 40):m.end() + 20]}...")
            if b['type'] in ('figure', 'table'):
                findings.append(f"writer supplied a {b['type']} block in {s['key']} "
                                "- contract v2 has no such block")

    # TABLE COMPLETENESS (Nick 2026-09-08): a structure the writer builds
    # declares its columns, and every declared cell is filled. Building a
    # table is earned freedom; the obligation is that the data behind it
    # is complete. An empty or dashed cell ANYWHERE in a headed table is a
    # finding - the writer fills it from the bundle (declaring any
    # derivation), writes the true word ('none'), or drops the column or
    # row. Same shape as the completeness gate: what a structure PROMISED,
    # not just what's on the page.
    _dash = {'—', '-', '–', '', 'n/a', 'N/A', 'na'}
    for s in plan['sections']:
        for b in s['blocks']:
            if b['type'] != 'table_inline' or not b.get('rows'):
                continue
            headers = b.get('headers') or []
            ncols = max([len(r) for r in b['rows']] + [len(headers)])
            for i in range(ncols):
                cells = [str(r[i]).strip() if i < len(r) else '' for r in b['rows']]
                empty = sum(1 for c in cells if c in _dash)
                if empty:
                    head = headers[i] if i < len(headers) else 'column %d' % (i + 1)
                    findings.append(
                        f"table [{s['key']}] column {head!r} has {empty} empty "
                        f"cell(s) of {len(cells)} - a declared column is "
                        "filled in every row: fill it from the bundle "
                        "(declare any derivation), state the true word, or "
                        "drop the column or row")

    present = [s['key'] for s in plan['sections']
               if s['blocks'] or s['key'] == 'sources_and_notes']
    info.append('sections: %s' % present)
    ask = (bundle['record'].get('financials', {}).get('funding_request')
           or bundle['record'].get('financials', {}).get('loan_request_amount'))
    om = {o['key'] for o in plan.get('omitted_sections', [])}
    if 'funding_request' in present and not ask:
        findings.append('funding_request written but the record carries no ask - must be omitted')
    if 'funding_request' not in present and 'funding_request' not in om:
        findings.append('funding_request neither written nor listed in omitted_sections')
    fp = [s for s in plan['sections'] if s['key'] == 'financial_plan']
    if fp:
        subs = [b['text'].strip().lower() for b in fp[0]['blocks']
                if b['type'] == 'subheading']
        for need in ['basis of projections', 'assumptions', 'the forecast',
                     'break-even and sensitivity']:
            if need not in subs:
                findings.append('financial_plan missing subheading: ' + need)

    words = sum(len(b.get('text', '').split()) for s in plan['sections']
                for b in s['blocks'] if b['type'] == 'paragraph')
    info.append('prose words: %d' % words)
    info.append('derivations: %d' % len(plan.get('derivations', [])))
    return findings, info


def render_report(findings: List[str], info: List[str]) -> str:
    lines = list(info[:1])
    lines += ['  ' + f for f in findings]
    lines += info[1:]
    lines.append('CHECKER: %s (%d findings)'
                 % ('PASS' if not findings else 'FAIL', len(findings)))
    return '\n'.join(lines)
