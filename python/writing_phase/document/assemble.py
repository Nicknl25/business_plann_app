"""PLAN ASSEMBLER - authored sections into ONE growing docx.

Nick (2026-09-06): "One file per section is wrong. As sections are authored
the document accumulates - The Business, then Products & Services, in
registry order, in one growing docx. Every re-author replaces its own
section and leaves the others alone." So the deliverable is
    "<Business Name> -- Business Plan.docx"
in C:\\dev\\Client Written Plans - ONE file (the ship-one-file law),
rebuilt from the stored section payloads each time a section passes, its
title page saying WORKING DRAFT so nobody mistakes it for a delivered plan.
The run identifier sits in a minimal appendix, never on a client-facing
page (rule 21).

Sections whose registry entry says per_line_subsections render each line
under a real Heading 2 (Nick 2026-09-06: "Real heading styles, so they
appear in the TOC and a reader can scan to a line") - the heading text is
the line's own name fact, title-cased, never writer-authored.

Everything is a real Word style, including the note references: a character
style "Plan Note Ref" carries the superscript, so no run is ever directly
formatted (rule 22) and the probe stays clean.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches as _Inches, Pt as _Pt

from .. import rules as R
from ..checks import FACT_TOKEN, _SUPERSCRIPT_MARKER
from ..facts.catalog import FactCatalog
from . import renderer as REN

_UNSAFE = re.compile(r'[\\/:*?"<>|]+')


def _note_ref_style(doc: Document) -> None:
  st = doc.styles
  ref = st.add_style("Plan Note Ref", WD_STYLE_TYPE.CHARACTER)
  ref.font.superscript = True


def _runs(text: str, cat: FactCatalog) -> List[Tuple[str, str]]:
  """Split a sentence into (kind, value) runs: 'text' with tokens rendered
  through the one formatter, and 'noteref' for each [^n] marker."""
  def _sub(m):
    f = cat.get_quiet(m.group(1))
    return f.render() if f is not None else m.group(0)

  rendered = FACT_TOKEN.sub(_sub, str(text or ""))
  out: List[Tuple[str, str]] = []
  pos = 0
  for m in _SUPERSCRIPT_MARKER.finditer(rendered):
    if m.start() > pos:
      out.append(("text", rendered[pos:m.start()]))
    out.append(("noteref", m.group(1)))
    pos = m.end()
  if pos < len(rendered):
    out.append(("text", rendered[pos:]))
  return out


def _line_heading(cat: FactCatalog, line_no: int) -> str:
  """The Heading 2 text for per-line subsections: the line's own name fact,
  title-cased for a heading. Never authored by the writer - the tag picks
  the line, the fact names it."""
  f = cat.get_quiet("annual.lob%d_name" % line_no)
  name = f.render() if f is not None else "Line %d" % line_no
  return " ".join(w[:1].upper() + w[1:] for w in str(name).split())


def _emit_section_body(doc: Document, payload: Dict[str, Any],
                       cat: FactCatalog, spec: Dict[str, Any]) -> None:
  paras: Dict[int, List[Dict[str, Any]]] = {}
  for s in payload.get("sentences") or []:
    paras.setdefault(int(s.get("paragraph") or 1), []).append(s)
  per_line = bool(spec.get("per_line_subsections"))
  current_sub = 0
  for pno in sorted(paras):
    if per_line:
      sub = min(int(s.get("subsection") or 0) for s in paras[pno])
      if sub > 0 and sub != current_sub:
        doc.add_paragraph(_line_heading(cat, sub), style="Heading 2")
      current_sub = sub
    p = doc.add_paragraph()
    for i, s in enumerate(paras[pno]):
      if i:
        p.add_run(" ")
      for kind, value in _runs(str(s.get("text") or ""), cat):
        r = p.add_run(value)
        if kind == "noteref":
          r.style = doc.styles["Plan Note Ref"]


def _emit_notes(doc: Document, payload: Dict[str, Any], cat: FactCatalog,
                heading_style: str) -> None:
  notes = payload.get("notes") or []
  if not notes:
    return
  doc.add_paragraph(R.NOTES_SECTION_TITLE, style=heading_style)
  for n in notes:
    p = doc.add_paragraph()
    r = p.add_run(str(n.get("id") or ""))
    r.style = doc.styles["Plan Note Ref"]
    body = FACT_TOKEN.sub(
      lambda m: (cat.get_quiet(m.group(1)).render()
                 if cat.get_quiet(m.group(1)) is not None else m.group(0)),
      str(n.get("text") or ""))
    # the kind stays in the payload for the checks; the reader gets the
    # note text alone (Nick 2026-09-02)
    p.add_run(" %s" % body)


def _toc_entries(sections: List[Tuple[str, Dict[str, Any]]],
                 cat: FactCatalog,
                 ordered: Dict[str, Dict[str, Any]]) -> List[Tuple[int, str]]:
  """The headings the document will carry, in emission order - the cached
  content of the TOC field mirrors exactly what Word rebuilds from the
  Heading 1/2 styles."""
  entries: List[Tuple[int, str]] = []
  for key, payload in sections:
    spec = ordered.get(key) or {"key": key, "title": key}
    entries.append((1, str(spec.get("title") or key)))
    if spec.get("per_line_subsections"):
      paras: Dict[int, List[Dict[str, Any]]] = {}
      for s in payload.get("sentences") or []:
        paras.setdefault(int(s.get("paragraph") or 1), []).append(s)
      seen: List[int] = []
      for pno in sorted(paras):
        sub = min(int(s.get("subsection") or 0) for s in paras[pno])
        if sub > 0 and sub not in seen:
          seen.append(sub)
      entries.extend((2, _line_heading(cat, sub)) for sub in seen)
    if payload.get("notes"):
      entries.append((2, str(R.NOTES_SECTION_TITLE)))
  entries.append((1, "Appendix"))
  return entries


def _fld_char(kind: str) -> Any:
  el = OxmlElement("w:fldChar")
  el.set(qn("w:fldCharType"), kind)
  r = OxmlElement("w:r")
  r.append(el)
  return r


def _toc_field(doc: Document, entries: List[Tuple[int, str]]) -> None:
  """A real Word TOC field over Heading 1-2 whose CACHED content is the
  actual heading list (Nick 2026-09-06: no placeholder), so the contents
  read correctly the moment the file opens; w:updateFields in settings has
  Word refresh the field - adding page numbers - on open."""
  st = doc.styles
  for name, indent in (("TOC 1", 0.0), ("TOC 2", 0.25)):
    try:
      style = st.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
      style.base_style = st["Normal"]
      style.paragraph_format.left_indent = _Inches(indent)
      style.paragraph_format.space_after = _Pt(2)
    except ValueError:
      pass    # already defined
  for i, (level, text) in enumerate(entries):
    p = doc.add_paragraph(style="TOC %d" % level)
    if i == 0:
      p._p.append(_fld_char("begin"))
      instr = OxmlElement("w:instrText")
      instr.set(qn("xml:space"), "preserve")
      instr.text = r' TOC \o "1-2" \h \z \u '
      ri = OxmlElement("w:r")
      ri.append(instr)
      p._p.append(ri)
      p._p.append(_fld_char("separate"))
    p.add_run(text)
    if i == len(entries) - 1:
      p._p.append(_fld_char("end"))
  upd = OxmlElement("w:updateFields")
  upd.set(qn("w:val"), "true")
  doc.settings.element.append(upd)


def build_plan_docx(*, business_name: str, run_id: str,
                    sections: List[Tuple[str, Dict[str, Any]]],
                    cat: FactCatalog,
                    out_dir: Optional[str] = None,
                    now: Optional[_dt.datetime] = None) -> str:
  """The ONE growing document: every stored section, registry order. Callers
  pass sections already ordered and re-read from the section store, so a
  re-author replaces its own section and leaves the others alone."""
  now = now or _dt.datetime.now()
  month_year = now.strftime("%B %Y")
  safe_name = _UNSAFE.sub(" ", str(business_name)).strip()
  fname = "%s -- Business Plan.docx" % safe_name
  out_path = os.path.join(out_dir or R.PLAN_OUTPUT_DIR, fname)

  doc = Document()
  REN._styles(doc)
  _note_ref_style(doc)

  # ---- title page (no header/footer; WORKING DRAFT named out loud)
  doc.add_paragraph(business_name, style="Title")
  doc.add_paragraph("Business Plan — Working Draft", style="Plan Subtitle")
  doc.add_paragraph("Prepared %s" % month_year, style="Plan Subtitle")

  # ---- contents, then the sections under the running header and footer
  s2 = doc.add_section(WD_SECTION.NEW_PAGE)
  REN._header(s2, business_name)
  REN._footer(s2, month_year)
  ordered = {sp["key"]: sp for sp in R.SECTION_REGISTRY}
  doc.add_paragraph("Contents", style="Heading 1")
  _toc_field(doc, _toc_entries(sections, cat, ordered))
  for key, payload in sections:
    spec = ordered.get(key) or {"key": key, "title": key}
    doc.add_page_break()
    doc.add_paragraph(spec.get("title") or key, style="Heading 1")
    _emit_section_body(doc, payload, cat, spec)
    _emit_notes(doc, payload, cat, heading_style="Heading 2")

  # ---- minimal appendix: the run identifier's ONLY legal home (rule 21)
  doc.add_paragraph("Appendix", style="Heading 1")
  doc.add_paragraph("Run identifier: %s" % run_id, style="Plan Chrome")

  os.makedirs(os.path.dirname(out_path), exist_ok=True)
  try:
    doc.save(out_path)
  except PermissionError:
    # the growing file is open in Word - do not lose the build; land a
    # stamped sibling and say so in the returned path
    stamped = os.path.join(
      os.path.dirname(out_path),
      "%s -- Business Plan -- %s.docx" % (safe_name,
                                          now.strftime(R.PLAN_FILENAME_STAMP_FORMAT)))
    doc.save(stamped)
    return stamped
  return out_path
