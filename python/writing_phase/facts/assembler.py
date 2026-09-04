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
# the business without borrowing another section's sentences. naics_title
# DROPPED (Nick 2026-09-03): the classification is machinery - the client's
# own account names the trade, and the code was riding into every brief
# dressed as a client-stated fact.
IDENTITY_KEYS = ("entity.business_name", "entity.state_name")

# THE NARRATIVE MAP (Nick, 2026-08-30): a section gets the stored narrative its
# substance depends on and not the rest. Operations and Products are
# narrative-carried - written without these they read thin for a reason that
# has nothing to do with the writing. The map is the ONLY source of narrative
# for a brief, so a financial narrative cannot leak into the ops brief; the
# leak test reads this map and the assembled briefs both.
NARRATIVE_MAP = {
  # milestones dropped (Nick 2026-09-01): a milestone is an intake aspiration
  # nothing models and nothing validates - it must not dress as the objective
  # the projections were built toward. Coverage and the growth lever added the
  # same day: coverage is the most specific thing in the profile, and "where
  # it's going" exists only where the lever can carry it (empty values drop).
  "the_business": ("business_description_summary", "competitive_advantage",
                   "geographic_coverage", "primary_growth_lever"),
  "market_and_industry": ("target_market", "marketing_model"),
  "competitive_landscape": ("competitive_advantage", "substitute_pressure"),
  "products_and_services": ("lob_products", "financials_year1_lobs"),
  "marketing_and_sales": ("marketing_plan_summary", "marketing_model", "retention_rationale"),
  "operations_and_organisation": ("fulfillment", "operating_profile"),
  "management_team": ("people",),
  "staffing_and_human_capital": ("inferred_roles", "rest_of_team_payroll"),
  "risks_and_mitigations": ("risk_analysis",),
  "funding_request": ("debt_schedule", "funding_posture"),
  "financial_plan": ("coherence_analysis", "assumptions_ledger", "debt_schedule", "stage_ramp"),
  "disclosures": ("acceptance_verdict", "intake_policy", "estimation_flags"),
  "executive_summary": ("planning_context",),
}

# Person fields carried into the ops narrative. Wages stay OUT - the brief's
# FACTS carry every number (rule 17); the narrative carries who people are.
_PERSON_FIELDS = ("full_name", "role_title", "experience_years", "paragraph",
                  "primary_responsibilities", "relevant_background",
                  "why_strengthens_business")


def _jload(v):
  if v is None:
    return {}
  if isinstance(v, (dict, list)):
    return v
  try:
    return json.loads(v)
  except Exception:
    return {}


def extract_narratives(draft: Dict[str, Any], extras: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
  """The narrative pool, keyed by the names NARRATIVE_MAP uses. Empty values
  are dropped, so a missing narrative is simply absent from the brief - the
  section writes shorter, never explains why (rule 3)."""
  om = _jload(draft.get("operating_model_json"))
  tm = _jload(draft.get("target_market_json"))
  pj = _jload(draft.get("people_json"))
  out: Dict[str, Any] = {}
  # milestones are deliberately NOT pooled (Nick 2026-09-01): an unmodelled
  # intake aspiration has no place in any section's narrative grant.
  for key, val in (
    ("business_description_summary", str(om.get("business_description_summary") or "").strip()),
    ("competitive_advantage", str(om.get("competitive_advantage") or "").strip()),
    ("geographic_coverage", str(om.get("geographic_coverage") or "").strip()),
    ("primary_growth_lever", str(om.get("primary_growth_lever") or "").strip()),
    ("lob_products", om.get("lob_models") or []),
    ("fulfillment", _jload(draft.get("fulfillment_json"))),
    ("marketing_plan_summary", str(tm.get("marketing_plan_summary") or "").strip()),
  ):
    if val:
      out[key] = val
  people = []
  for p in (pj.get("people") or []):
    if isinstance(p, dict):
      row = {k: p.get(k) for k in _PERSON_FIELDS if p.get(k) not in (None, "")}
      if row:
        people.append(row)
  if people:
    out["people"] = people

  # ---- map v2 (2026-08-31): the wider grants ------------------------------
  fin = _jload(draft.get("financials_json"))
  coh = fin.get("_coherence") or {}
  mm = _jload(draft.get("marketing_model_json"))
  fy = _jload(draft.get("financials_year1_json"))
  mi = _jload(draft.get("model_input_json"))
  ms = _jload(draft.get("marketing_schedule_json"))
  pcs = _jload(draft.get("planning_context_summary_json"))
  si = (mi.get("solver_input") or {}) if isinstance(mi, dict) else {}

  tm_full = {k: v for k, v in tm.items()
             if k != "marketing_plan_summary" and v not in (None, "", [], {})}
  if tm_full:
    out["target_market"] = tm_full
  mm_slice = {k: mm.get(k) for k in ("marketing_basis_summary", "geography_basis",
                                     "b2b_basis_counts", "b2c_basis_counts",
                                     "expected_customers_or_clients_year1",
                                     "expected_units_year1", "capture_rate_year1",
                                     "marketing_intensity", "market_basis_type")
              if mm.get(k) not in (None, "", [], {})}
  if mm_slice:
    out["marketing_model"] = mm_slice
  sub = ((coh.get("demand_response") or {}).get("price_response") or {}).get("basis")
  if sub:
    out["substitute_pressure"] = sub
  if fy.get("lobs"):
    out["financials_year1_lobs"] = fy["lobs"]
  ret = ((ms.get("assumptions") or {}).get("retention") or {})
  if ret.get("rationale"):
    out["retention_rationale"] = {"rationale": ret.get("rationale"), "basis": ret.get("basis")}
  op = {k: om.get(k) for k in ("shipping_method", "sales_modality", "capacity_driver",
                               "geographic_coverage", "business_stage")
        if om.get(k) not in (None, "")}
  op.update({k: v for k, v in ((pcs.get("operating_profile") or {}) if isinstance(pcs, dict) else {}).items()
             if k in ("shipping_method", "sales_modality") and v})
  if op:
    out["operating_profile"] = op
  inf = {k: pj.get(k) for k in ("inferred_roles", "inferred_roles_summary")
         if pj.get(k) not in (None, "", [])}
  if inf:
    out["inferred_roles"] = inf
  if pj.get("rest_of_team_payroll_year1") not in (None, "", 0):
    out["rest_of_team_payroll"] = pj.get("rest_of_team_payroll_year1")
  risk = {k: coh.get(k) for k in ("demand_response", "walls") if coh.get(k)}
  if risk:
    out["risk_analysis"] = risk
  coh_full = {k: coh.get(k) for k in ("margin_band_judgment", "demand_response",
                                      "essentials_response", "judged_growth",
                                      "walls", "converged_suffix", "status")
              if coh.get(k) not in (None, "", [], {})}
  if coh_full:
    out["coherence_analysis"] = coh_full
  ledger = {k: si.get(k) for k in ("judgment_ledger", "wc_judgment", "cash_judgment",
                                   "margin_band_judgment")
            if si.get(k) not in (None, "", [], {})}
  if fin.get("_cogs_baseline_resolution"):
    ledger["cogs_baseline_resolution"] = fin.get("_cogs_baseline_resolution")
  if fin.get("cogs_basis"):
    ledger["cogs_basis"] = fin.get("cogs_basis")
  if ledger:
    out["assumptions_ledger"] = ledger
  if isinstance(pcs, dict) and pcs.get("stage_ramp_contract"):
    out["stage_ramp"] = pcs.get("stage_ramp_contract")
  sched = ((mi.get("sections") or {}).get("schedules") or {}) if isinstance(mi, dict) else {}
  rows_ = [{"label": r.get("label"), "values": r.get("values")}
           for r in (sched.get("rows") or []) if isinstance(r, dict)]
  seeds = {k: v for k, v in sched.items() if k != "rows" and v not in (None, "")}
  if rows_ or seeds:
    out["debt_schedule"] = {"seeds": seeds, "rows": rows_}
  posture = {k: fin.get(k) for k in ("funding_preference", "cash_strategy") if fin.get(k)}
  if posture:
    out["funding_posture"] = posture
  flags = {}
  if mm.get("estimation_method"):
    flags["marketing_estimation"] = {k: mm.get(k) for k in ("estimation_method", "estimation_status")}
  if ret.get("basis"):
    flags["retention_basis"] = ret.get("basis")
  if flags:
    out["estimation_flags"] = flags
  if isinstance(pcs, dict) and pcs.get("intake_non_binding_policy"):
    out["intake_policy"] = pcs.get("intake_non_binding_policy")
  if isinstance(pcs, dict) and pcs:
    out["planning_context"] = pcs
  for k, v in (extras or {}).items():
    if v not in (None, "", [], {}):
      out[k] = v
  return out

BRIEF_LOG_TABLE = "writing_phase_brief_log"

# CORE NARRATIVES (Nick 2026-09-01): the THIN flag watched only core FACTS, so
# a missing description or transcript was quiet at assembly - the one thing the
# assembler exists to make loud. These are the narrative grants whose absence
# makes the section thin for a reason that has nothing to do with the writing.
# Checked only when a draft row is supplied (no draft = no narratives at all,
# and flagging that would be noise, not signal).
CORE_NARRATIVES = {
  "the_business": ("business_description_summary",),
  "products_and_services": ("lob_products",),
  "operations_and_organisation": ("fulfillment",),
  "management_team": ("people",),
}


@dataclass
class SectionBrief:
  section_key: str
  facts: Dict[str, Dict[str, Any]] = field(default_factory=dict)   # key -> rendered brief entry
  narratives: Dict[str, Any] = field(default_factory=dict)         # NARRATIVE_MAP slice for this section
  sentences_resolved: List[str] = field(default_factory=list)      # sentence ids fully filled
  sentences_unfilled: Dict[str, List[str]] = field(default_factory=dict)  # id -> missing keys
  core_unfilled: List[str] = field(default_factory=list)           # core sentence ids not filled
  narrative_unfilled: List[str] = field(default_factory=list)      # core narrative keys absent from the pool
  thin: bool = False

  @property
  def fact_count(self) -> int:
    return len(self.facts)


@dataclass
class BriefAssembly:
  draft_id: str
  sections: Dict[str, SectionBrief] = field(default_factory=dict)
  thin_sections: List[str] = field(default_factory=list)
  transcript_absent: bool = False   # replay-built drafts have no client voice

  def summary_lines(self) -> List[str]:
    out = []
    if self.transcript_absent:
      out.append("TRANSCRIPT ABSENT - no client voice anywhere in this draft")
    for key, b in self.sections.items():
      why = ",".join(b.core_unfilled + ["narrative:%s" % k for k in b.narrative_unfilled])
      flag = "  <-- THIN (%s)" % why if b.thin else ""
      out.append("%-30s facts=%-3d sentences %d/%d%s"
                 % (key, b.fact_count, len(b.sentences_resolved),
                    len(b.sentences_resolved) + len(b.sentences_unfilled), flag))
    return out


def assemble(cat: FactCatalog, *, sections: Optional[List[str]] = None,
             draft: Optional[Dict[str, Any]] = None,
             extras: Optional[Dict[str, Any]] = None) -> BriefAssembly:
  """Build every section's brief from the catalogue. Uses cat.get(), so every
  key a brief wanted and could not have lands in the miss log with its reason.
  When the draft row is supplied, each section also receives EXACTLY the
  narrative slice NARRATIVE_MAP grants it - nothing else."""
  asm = BriefAssembly(draft_id=cat.draft_id)
  pool = extract_narratives(draft, extras) if draft else {}
  if draft is not None:
    msgs = _jload(draft.get("messages_json"))
    asm.transcript_absent = not any(
      isinstance(m, dict) and m.get("role") == "user" and str(m.get("content") or "").strip()
      for m in (msgs if isinstance(msgs, list) else []))
  wanted = sections or [s["key"] for s in R.SECTION_REGISTRY
                        if s["key"] not in ("appendix", "sources_and_notes")]
  for section_key in wanted:
    brief = SectionBrief(section_key=section_key)
    for nk in NARRATIVE_MAP.get(section_key, ()):  # the map is the whole grant
      if nk in pool:
        brief.narratives[nk] = pool[nk]
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
    if draft is not None:
      brief.narrative_unfilled = [nk for nk in CORE_NARRATIVES.get(section_key, ())
                                  if nk not in brief.narratives]
    brief.thin = bool(brief.core_unfilled or brief.narrative_unfilled)
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
        narrative_keys_json JSON NULL,
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
    try:
      cur.execute(f"ALTER TABLE {BRIEF_LOG_TABLE} ADD COLUMN narrative_keys_json JSON NULL AFTER fact_keys_json")
      conn.commit()
    except Exception:
      pass   # already present
    try:
      cur.execute(f"ALTER TABLE {BRIEF_LOG_TABLE} ADD COLUMN narrative_unfilled_json JSON NULL AFTER narrative_keys_json")
      conn.commit()
    except Exception:
      pass   # already present
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
            (draft_id, section_key, fact_count, fact_keys_json, narrative_keys_json,
             narrative_unfilled_json, sentences_resolved_json, sentences_unfilled_json,
             thin, core_unfilled_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (asm.draft_id, key, b.fact_count, json.dumps(sorted(b.facts)),
         json.dumps(sorted(b.narratives)), json.dumps(b.narrative_unfilled),
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
