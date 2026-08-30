"""Fact, ABSENT, provenance, formatters, and the catalogue that logs misses.

THREE THINGS NICK REQUIRED, each held here rather than by convention:

1. Every fact carries a key, a value, a formatter and provenance. A Fact
   cannot be constructed without all four.
2. A fact that cannot be computed is ABSENT - not zero, not None. ABSENT is a
   distinct sentinel; the catalogue never stores it, so a section simply does
   not make that claim and never says why (rule 3).
3. Every requested key that does not resolve is LOGGED with the reason. The
   gaps after ten plans come from real demand, not from guesswork now.

PROVENANCE, per ruling E (2026-08-30): only facts drawn from
post_intake_industry_baseline_lookup carry a SOURCE note with source + vintage.
Model and intake facts are GROUNDED with a BASIS ("the projections", "stated at
intake"). Everything computed from a raw warehouse table (CBP, BDS, SBA, ACS,
OEWS) is INFERRED with a BASIS note that still names the table-level vintage,
so it is citable the day the ruling widens.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import rules as R


class _Absent:
  """The sentinel for 'cannot be computed for this business'. Falsy, singleton,
  never stored, never rendered."""
  _inst = None

  def __new__(cls):
    if cls._inst is None:
      cls._inst = super().__new__(cls)
    return cls._inst

  def __bool__(self):
    return False

  def __repr__(self):
    return "ABSENT"


ABSENT = _Absent()


# ---------------------------------------------------------------------------
# FORMATTERS - rule 16, one renderer per shape. GPT never sees a number.
# ---------------------------------------------------------------------------
def fmt_money(v: float, *, exact: bool = False) -> str:
  v = float(v)
  neg = v < 0
  a = abs(v)
  if exact or a < R.NUMBER_STYLE["prose_exact_below"]:
    s = "${:,.0f}".format(a)
  elif a >= R.NUMBER_STYLE["millions_threshold"]:
    m = a / 1_000_000.0
    s = ("$%.1f million" % m) if m < 100 else ("$%.0f million" % m)
    if s.endswith(".0 million"):
      s = s.replace(".0 million", " million")
  else:
    s = "${:,.0f}".format(round(a / 1000.0) * 1000)
  return "-" + s if neg else s


def fmt_money_exact(v: float) -> str:
  return fmt_money(v, exact=True)


def fmt_percent(v: float) -> str:
  """One decimal only where it means something: 12.0% -> 12%, 12.4% -> 12.4%."""
  p = float(v) * 100.0
  if abs(p - round(p)) < 0.05:
    return "%d%%" % int(round(p))
  return "%.1f%%" % p


def fmt_points(v: float) -> str:
  p = float(v) * 100.0
  s = "%.1f" % abs(p)
  if s.endswith(".0"):
    s = s[:-2]
  return "%s point%s" % (s, "" if s == "1" else "s")


def fmt_count(v: float) -> str:
  return "{:,.0f}".format(float(v))


def fmt_multiple(v: float) -> str:
  return "%.1fx" % float(v)


def fmt_ratio(v: float) -> str:
  return "%.2f" % float(v)


def fmt_months(v: float) -> str:
  m = float(v)
  s = ("%.1f" % m).rstrip("0").rstrip(".")
  return "%s month%s" % (s, "" if s == "1" else "s")


def fmt_year(v: int) -> str:
  return "Year %d" % int(v)


def fmt_quarter_label(v: int) -> str:
  """quarter_index 1..20 -> 'the second quarter of Year 2'."""
  q = int(v)
  y = (q - 1) // 4 + 1
  n = (q - 1) % 4 + 1
  return "the %s quarter of Year %d" % (("first", "second", "third", "fourth")[n - 1], y)


def fmt_ordinal(v: int) -> str:
  n = int(v)
  suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
  return "%d%s" % (n, suf)


def fmt_text(v: Any) -> str:
  return str(v)


def fmt_list_text(v: Any) -> str:
  return ", ".join(str(x) for x in v)


FORMATTERS: Dict[str, Callable[[Any], str]] = {
  "money": fmt_money, "money_exact": fmt_money_exact, "percent": fmt_percent,
  "points": fmt_points, "count": fmt_count, "multiple": fmt_multiple,
  "ratio": fmt_ratio, "months": fmt_months, "year": fmt_year,
  "quarter_label": fmt_quarter_label, "text": fmt_text, "list": fmt_list_text,
  "ordinal": fmt_ordinal,
}


# ---------------------------------------------------------------------------
# PROVENANCE
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Provenance:
  grounding: str                      # GROUNDED | INFERRED
  note_kind: Optional[str]            # SOURCE | BASIS | None
  basis: str                          # the sentence the note is built from
  source_name: Optional[str] = None   # SOURCE only
  source_vintage: Optional[str] = None
  table_vintage: Optional[str] = None # raw-table facts: kept, not cited

  def __post_init__(self):
    if self.grounding not in (R.CLASS_GROUNDED, R.CLASS_INFERRED):
      raise ValueError("grounding must be GROUNDED or INFERRED")
    if self.note_kind == R.NOTE_KIND_SOURCE and not (self.source_name and self.source_vintage):
      raise ValueError("a SOURCE note needs source_name and source_vintage")


def prov_model(what: str) -> Provenance:
  return Provenance(R.CLASS_GROUNDED, R.NOTE_KIND_BASIS,
                    "Based on the financial projections prepared for this plan: %s." % what)


def prov_intake(what: str) -> Provenance:
  return Provenance(R.CLASS_GROUNDED, R.NOTE_KIND_BASIS,
                    "Based on figures stated at intake: %s." % what)


def prov_baseline(source_name: str, source_year: Any, metric_label: str,
                  naics_level: Any, sample_size: Any) -> Provenance:
  """The ONLY path to a SOURCE note (ruling E)."""
  vintage = str(source_year or "").strip() or "undated"
  basis = "%s, %s (%s benchmark at NAICS-%s%s)." % (
    source_name, vintage, metric_label, naics_level,
    ", n=%s" % sample_size if sample_size else "")
  return Provenance(R.CLASS_GROUNDED, R.NOTE_KIND_SOURCE, basis,
                    source_name=source_name, source_vintage=vintage)


def prov_raw(table_label: str, table_vintage: str, what: str) -> Provenance:
  """Raw warehouse tables: INFERRED + BASIS by ruling E. The vintage travels
  with the fact so nothing has to be rebuilt if the ruling widens."""
  return Provenance(R.CLASS_INFERRED, R.NOTE_KIND_BASIS,
                    "Based on %s (%s): %s." % (table_label, table_vintage, what),
                    table_vintage=table_vintage)


# ---------------------------------------------------------------------------
# FACT + CATALOGUE
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Fact:
  key: str
  value: Any
  formatter: str
  provenance: Provenance
  label: str = ""

  def __post_init__(self):
    if self.value is ABSENT or self.value is None:
      raise ValueError("a Fact cannot hold ABSENT or None - do not construct it")
    if self.formatter not in FORMATTERS:
      raise ValueError("unknown formatter %r" % self.formatter)
    ns = self.key.split(".", 1)[0]
    if ns not in R.FACT_NAMESPACES:
      raise ValueError("fact key %r is outside the namespaces" % self.key)

  @property
  def namespace(self) -> str:
    return self.key.split(".", 1)[0]

  def render(self) -> str:
    return FORMATTERS[self.formatter](self.value)


class FactCatalog:
  """What the brief is built from. `put` ignores ABSENT silently; `get` logs
  every miss with a reason through the sink the caller supplies."""

  def __init__(self, draft_id: str, *, miss_sink: Optional[Callable[..., None]] = None):
    self.draft_id = draft_id
    self._facts: Dict[str, Fact] = {}
    self._absent: Dict[str, str] = {}      # key -> why it was not computed
    self._misses: List[Tuple[str, str]] = []
    self._sink = miss_sink

  # -- authoring side -------------------------------------------------------
  def put(self, key: str, value: Any, formatter: str, provenance: Provenance,
          label: str = "", *, absent_reason: str = "") -> None:
    if value is ABSENT or value is None:
      self._absent[key] = absent_reason or "not computable for this business"
      return
    try:
      if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        self._absent[key] = "non-finite value"
        return
    except Exception:
      pass
    self._facts[key] = Fact(key, value, formatter, provenance, label)

  # -- consuming side -------------------------------------------------------
  def get(self, key: str, *, section_key: Optional[str] = None) -> Optional[Fact]:
    f = self._facts.get(key)
    if f is None:
      reason = self._absent.get(key, "never computed")
      self._misses.append((key, reason))
      if self._sink is not None:
        try:
          self._sink(draft_id=self.draft_id, fact_key=key, reason=reason,
                     section_key=section_key)
        except Exception:
          pass
    return f

  def get_quiet(self, key: str) -> Optional[Fact]:
    """For BUILDERS deriving one fact from another. Not a request from the
    writing side, so it is not a miss and is not logged."""
    return self._facts.get(key)

  def note_builder_failure(self, builder: str, why: str) -> None:
    """A builder raised. Every key it owns is now ABSENT with the failure
    text as the reason, so the miss log says WHY rather than 'never computed'."""
    self._absent["__builder__." + builder] = why
    for k in list(self._absent):
      if self._absent[k] == "not computable for this business":
        self._absent[k] = "builder %s failed: %s" % (builder, why)

  def builder_failures(self) -> Dict[str, str]:
    return {k.split(".", 1)[1]: v for k, v in self._absent.items() if k.startswith("__builder__.")}

  def has(self, key: str) -> bool:
    return key in self._facts

  def keys(self) -> List[str]:
    return sorted(self._facts)

  def absent(self) -> Dict[str, str]:
    return dict(self._absent)

  def misses(self) -> List[Tuple[str, str]]:
    return list(self._misses)

  def by_namespace(self, ns: str) -> List[Fact]:
    return [f for k, f in sorted(self._facts.items()) if f.namespace == ns]

  def as_brief(self, *, body: bool) -> Dict[str, Dict[str, Any]]:
    """The brief GPT receives. Body briefs carry only body-legal namespaces
    (rule 18 held structurally); the appendix brief carries everything."""
    out: Dict[str, Dict[str, Any]] = {}
    for k, f in sorted(self._facts.items()):
      if body and not R.namespace_allowed_in_body(k):
        continue
      out[k] = {"rendered": f.render(), "label": f.label,
                "grounding": f.provenance.grounding,
                "note_kind": f.provenance.note_kind,
                "basis": f.provenance.basis}
    return out
