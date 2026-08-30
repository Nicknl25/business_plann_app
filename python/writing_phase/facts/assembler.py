"""THE BRIEF ASSEMBLER (2026-08-30). Per-section briefs from the catalogue.

THE DESIGN DECISION, made deliberately (Nick's directive): WHICH FACTS GO IN
WHICH SECTION'S BRIEF is derived from the sentence list and nothing else. Each
sentence in sentences.py already names its keys and its section; a section's
brief is the union of the keys its sentences need (plus the entity identity
keys every section may address the business by). A brief carrying all 129
facts means GPT wanders and the section stops being about anything.

THINNESS IS LOUD AT ASSEMBLY TIME, not quiet at generation time. Sentences
marked core=True are the section's anchors: a section whose core sentences
cannot all be filled is flagged THIN in the assembly result, and the result
carries exactly which sentences resolved, which did not, and why - so when a
section reads thin later, the log answers whether it was the brief or the
writing.

Every assembly is LOGGED to writing_phase_brief_log: one row per section per
assembly, with the keys the brief actually contained.

Nothing here writes prose or calls GPT.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import rules as R
from . import sentences as S
from .catalog import FactCatalog

# Identity keys every section's brief carries - a section must be able to name
# the business and its trade without borrowing another section's sentences.
IDENTITY_KEYS = ("entity.business_name", "entity.naics_title", "entity.state_name")

BRIEF_LOG_TABLE = "writing_phase_brief_log"


@dataclass
class SectionBrief:
  section_key: str
  facts: Dict[str, Dict[str, Any]] = field(default_factory=dict)   # key -> rendered brief entry
  sentences_resolved: List[str] = field(default_factory=list)      # sentence ids fully filled
  sentences_unfilled: Dict[str, List[str]] = field(default_factory=dict)  # id -> missing keys
  core_unfilled: List[str] = field(default_factory=list)           # core sentence ids not filled
  thin: bool = False

  @property
  def fact_count(self) -> int:
    return len(self.facts)


@dataclass
class BriefAssembly:
  draft_id: str
  sections: Dict[str, SectionBrief] = field(default_factory=dict)
  thin_sections: List[str] = field(default_factory=list)

  def summary_lines(self) -> List[str]:
    out = []
    for key, b in self.sections.items():
      flag = "  <-- THIN (core unfilled: %s)" % ",".join(b.core_unfilled) if b.thin else ""
      out.append("%-30s facts=%-3d sentences %d/%d%s"
                 % (key, b.fact_count, len(b.sentences_resolved),
                    len(b.sentences_resolved) + len(b.sentences_unfilled), flag))
    return out


def assemble(cat: FactCatalog, *, sections: Optional[List[str]] = None) -> BriefAssembly:
  """Build every section's brief from the catalogue. Uses cat.get(), so every
  key a brief wanted and could not have lands in the miss log with its reason."""
  asm = BriefAssembly(draft_id=cat.draft_id)
  wanted = sections or [s["key"] for s in R.SECTION_REGISTRY
                        if s["key"] not in ("appendix", "sources_and_notes")]
  for section_key in wanted:
    brief = SectionBrief(section_key=section_key)
    sents = S.sentences_for_section(section_key)
    # identity keys first - quiet lookups, they are not sentence demand
    for k in IDENTITY_KEYS:
      f = cat.get_quiet(k)
      if f is not None:
        brief.facts[k] = _entry(f)
    for sent in sents:
      missing: List[str] = []
      for k in sent["needs"]:
        f = cat.get(k, section_key=section_key)
        if f is None:
          missing.append(k)
        else:
          brief.facts[k] = _entry(f)
      if missing:
        brief.sentences_unfilled[str(sent["id"])] = missing
        if sent.get("core"):
          brief.core_unfilled.append(str(sent["id"]))
      else:
        brief.sentences_resolved.append(str(sent["id"]))
    brief.thin = bool(brief.core_unfilled)
    if brief.thin:
      asm.thin_sections.append(section_key)
    asm.sections[section_key] = brief
  return asm


def _entry(f) -> Dict[str, Any]:
  return {"rendered": f.render(), "label": f.label,
          "grounding": f.provenance.grounding,
          "note_kind": f.provenance.note_kind,
          "basis": f.provenance.basis}


# ---------------------------------------------------------------------------
# THE LOG - one row per section per assembly, keys included, so "was it the
# brief or the writing" is answerable months later.
# ---------------------------------------------------------------------------
_LOG_READY = False


def ensure_brief_log_table(conn) -> None:
  global _LOG_READY
  if _LOG_READY:
    return
  cur = conn.cursor()
  try:
    cur.execute(
      f"""
      CREATE TABLE IF NOT EXISTS {BRIEF_LOG_TABLE} (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        draft_id VARCHAR(64) NOT NULL,
        section_key VARCHAR(64) NOT NULL,
        fact_count INT NOT NULL,
        fact_keys_json JSON NOT NULL,
        sentences_resolved_json JSON NOT NULL,
        sentences_unfilled_json JSON NOT NULL,
        thin TINYINT(1) NOT NULL DEFAULT 0,
        core_unfilled_json JSON NOT NULL,
        assembled_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        KEY ix_draft (draft_id),
        KEY ix_section (section_key)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
      """
    )
    conn.commit()
    _LOG_READY = True
  finally:
    try:
      cur.close()
    except Exception:
      pass


def log_assembly(conn, asm: BriefAssembly) -> int:
  ensure_brief_log_table(conn)
  cur = conn.cursor()
  written = 0
  try:
    for key, b in asm.sections.items():
      cur.execute(
        f"""INSERT INTO {BRIEF_LOG_TABLE}
            (draft_id, section_key, fact_count, fact_keys_json,
             sentences_resolved_json, sentences_unfilled_json, thin, core_unfilled_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (asm.draft_id, key, b.fact_count, json.dumps(sorted(b.facts)),
         json.dumps(b.sentences_resolved), json.dumps(b.sentences_unfilled),
         1 if b.thin else 0, json.dumps(b.core_unfilled)),
      )
      written += 1
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return written
