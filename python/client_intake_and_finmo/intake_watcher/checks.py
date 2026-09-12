"""Deterministic checks - every one a computed answer on the transcript and
the store, none a judgment. They run on every persisted turn.

Input: a Turn - the client's message, the app's reply, the draft BEFORE and
AFTER the turn (ops, people, financials, status, focus, pending question),
and the earlier messages of this draft.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from client_intake_and_finmo import field_basis as _fb
from client_intake_and_finmo import intake_required_fields as _rf
from client_intake_and_finmo.intake_watcher.vocabulary import observation

# Which lever field belongs to which client-asserted floor (mirrors the
# coherence section's map; kept here so the watcher never imports the door
# it watches).
FIELD_FLOOR_COST = {
  "monthly_rent_expense": "rent",
  "other_operating_expense": "gna",
  "other_opex_absolute": "gna",
  "payroll_adjustment": "payroll",
  "baseline_payroll_year1": "payroll",
  "marketing_total_year1": "marketing",
  "marketing_percent_of_revenue": "marketing",
  "cogs_total_year1": "cogs",
  "current_cogs": "cogs",
  "cogs_percent_of_revenue": "cogs",
}

# Leaves the app derives from others: a move here is a consequence, not a
# cause, and is never "without cause" on its own.
DERIVED_LEAVES = {
  "payroll_total_year1", "baseline_payroll_year1", "current_payroll",
  "payroll_basis_people_roles", "other_opex_absolute", "owner_compensation",
  "cogs_total_year1", "current_cogs", "cogs_percent_of_revenue",
  "marketing_percent_of_revenue", "payroll_adjustment", "current_num_employees",
  "inferred_roles", "inferred_roles_summary", "business_naics_6", "confidence",
  "rest_of_team_payroll_year1",
}


@dataclass
class Turn:
  draft_id: str
  turn: int
  user_text: str
  assistant_text: str
  before: Dict[str, Any]
  after: Dict[str, Any]
  prior_user_texts: List[str] = field(default_factory=list)
  prior_assistant_texts: List[str] = field(default_factory=list)


# ----------------------------------------------------------------- helpers

_NUM_RE = re.compile(r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|m|million)?\b", re.I)


def figures_in(text: str, *, at_least: float = 1000.0) -> List[float]:
  out: List[float] = []
  for m in _NUM_RE.finditer(str(text or "")):
    raw = m.group(1).replace(",", "")
    try:
      v = float(raw)
    except ValueError:
      continue
    mult = (m.group(2) or "").lower()
    if mult in ("k", "thousand"):
      v *= 1000.0
    elif mult in ("m", "million"):
      v *= 1_000_000.0
    if v >= at_least:
      out.append(v)
  return out


def _f(v: Any) -> Optional[float]:
  try:
    if v is None or isinstance(v, bool):
      return None
    return float(v)
  except (TypeError, ValueError):
    return None


def numeric_leaves(obj: Any, prefix: str = "") -> Dict[str, float]:
  """Flatten numeric leaves: {"financials.monthly_rent_expense": 22000.0, ...}.
  Lists of dicts are indexed; private keys (leading underscore) skipped."""
  out: Dict[str, float] = {}
  if isinstance(obj, dict):
    for k, v in obj.items():
      if str(k).startswith("_"):
        continue
      out.update(numeric_leaves(v, f"{prefix}.{k}" if prefix else str(k)))
  elif isinstance(obj, list):
    for i, v in enumerate(obj):
      out.update(numeric_leaves(v, f"{prefix}[{i}]"))
  else:
    fv = _f(obj)
    if fv is not None and prefix:
      out[prefix] = fv
  return out


def _equivalents(v: float) -> Tuple[float, ...]:
  return (v, v * 12.0, v / 12.0, v * 4.0, v / 4.0, v * 3.0, v / 3.0)


def _close(a: float, b: float, rel: float = 0.005) -> bool:
  return abs(a - b) <= max(0.5, abs(b) * rel)


def figure_in_store(v: float, leaves: Dict[str, float]) -> Optional[str]:
  for path, stored in leaves.items():
    for e in _equivalents(v):
      if _close(stored, e):
        return path
  return None


def _norm(text: str) -> str:
  return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _section(d: Dict[str, Any], name: str) -> Dict[str, Any]:
  v = (d or {}).get(name)
  return v if isinstance(v, dict) else {}


# ------------------------------------------------------------------ checks

def check_roster_not_in_basis(t: Turn) -> List[Dict[str, Any]]:
  people = _section(t.after, "people").get("people") or []
  basis = _section(t.after, "financials").get("payroll_basis_people_roles") or []
  named = {str(r.get("full_name") or "").strip().lower() for r in basis if isinstance(r, dict) and r.get("full_name")}
  out = []
  for p in people:
    if not isinstance(p, dict):
      continue
    name = str(p.get("full_name") or "").strip()
    wage = _f(p.get("annual_wage"))
    if name and wage and wage > 0 and name.lower() not in named:
      out.append(observation("roster_not_in_basis", draft_id=t.draft_id, turn=t.turn, field="financials.payroll_basis_people_roles",
                             stored_value=[r.get("full_name") for r in basis if isinstance(r, dict)], expected=name,
                             why=f"{name} is on the roster at {wage:,.0f} and absent from the payroll basis"))
  return out


def check_basis_sum_mismatch(t: Turn) -> List[Dict[str, Any]]:
  fin = _section(t.after, "financials")
  basis = fin.get("payroll_basis_people_roles") or []
  if not basis:
    return []
  total = sum((_f(r.get("year1_payroll_amount")) or 0.0) for r in basis if isinstance(r, dict))
  stored = _f(fin.get("payroll_total_year1")) or _f(fin.get("current_payroll"))
  if stored is None or total <= 0:
    return []
  if not _close(total, stored):
    return [observation("basis_sum_mismatch", draft_id=t.draft_id, turn=t.turn, field="financials.payroll_total_year1",
                        stored_value=stored, expected=round(total, 2),
                        why="the basis rows do not sum to the stored payroll total")]
  return []


def check_unit_copied(t: Turn) -> List[Dict[str, Any]]:
  before = numeric_leaves(_section(t.before, "financials"), "financials")
  after = numeric_leaves(_section(t.after, "financials"), "financials")
  out = []
  for path, v in after.items():
    if before.get(path) == v:
      continue
    declared = _fb.basis_of(path)
    if declared not in (_fb.MONTHLY, _fb.ANNUAL, _fb.QUARTERLY):
      continue
    stated = _fb.stated_basis_in_text(t.user_text, v)
    if stated and stated != declared:
      out.append(observation("unit_copied", draft_id=t.draft_id, turn=t.turn, field=path, stored_value=v,
                             expected=round(_fb.convert_between(v, stated, declared), 2),
                             client_words=t.user_text,
                             why=f"the client said {v:,.0f} {stated}; the field is stored {declared} and holds the figure unconverted"))
  return out


def check_refusal_violated(t: Turn) -> List[Dict[str, Any]]:
  state = _section(t.after, "financials").get("_coherence") or {}
  floors = {k for k, v in (state.get("client_floors") or {}).items() if v}
  if not floors:
    return []
  before = numeric_leaves(_section(t.before, "financials"), "financials")
  after = numeric_leaves(_section(t.after, "financials"), "financials")
  out = []
  for path, v in after.items():
    leaf = path.rsplit(".", 1)[-1]
    cost = FIELD_FLOOR_COST.get(leaf)
    if cost in floors and path in before and not _close(before[path], v):
      # the client's own restatement of a floored figure is not a violation
      if _fb.stated_basis_in_text(t.user_text, v) or any(_close(v, e) for f_ in figures_in(t.user_text) for e in _equivalents(f_)):
        continue
      out.append(observation("refusal_violated", draft_id=t.draft_id, turn=t.turn, field=path,
                             stored_value=v, expected=before[path], client_words=t.user_text,
                             why=f"{cost} is floored by the client and {leaf} moved from {before[path]:,.0f} to {v:,.0f}"))
  return out


def check_option_touches_refusal(t: Turn) -> List[Dict[str, Any]]:
  state = _section(t.after, "financials").get("_coherence") or {}
  floors = {k for k, v in (state.get("client_floors") or {}).items() if v}
  rnd = state.get("round") if isinstance(state.get("round"), dict) else {}
  out = []
  for o in rnd.get("options") or []:
    if not isinstance(o, dict):
      continue
    spec = o.get("patch") or {}
    touched = set()
    if spec.get("kind") == "ops_prices" and "pricing" in floors:
      touched.add("pricing")
    if spec.get("kind") == "ops_volume" and "volume" in floors:
      touched.add("volume")
    for fp in spec.get("fields") or []:
      cost = FIELD_FLOOR_COST.get(str((fp or {}).get("field") or ""))
      if cost in floors:
        touched.add(cost)
    if touched:
      out.append(observation("option_touches_refusal", draft_id=t.draft_id, turn=t.turn, field=f"coherence.option:{o.get('id')}",
                             stored_value=o.get("id"), expected="not generated",
                             why=f"offered option moves {', '.join(sorted(touched))}, which the client refused"))
  return out


def check_recommendation_not_largest(t: Turn) -> List[Dict[str, Any]]:
  state = _section(t.after, "financials").get("_coherence") or {}
  rnd = state.get("round") if isinstance(state.get("round"), dict) else {}
  opts = [o for o in (rnd.get("options") or []) if isinstance(o, dict)]
  rec = [o for o in opts if o.get("recommended")]
  if not rec:
    return []
  rec_close = _f(rec[0].get("closes_quarterly")) or 0.0
  qualifying = [o for o in opts if (_f(o.get("closes_quarterly")) or 0.0) > 0 and not o.get("deep_cut") and not o.get("lease_unknown")]
  best = max((_f(o.get("closes_quarterly")) or 0.0) for o in qualifying) if qualifying else 0.0
  gap = _f(state.get("gap_open")) or 0.0
  if best > rec_close + 0.5 or (gap > 0 and rec_close < 0.05 * gap and len(opts) > 1):
    return [observation("recommendation_not_largest", draft_id=t.draft_id, turn=t.turn, field="coherence.round.recommended",
                        stored_value=rec[0].get("id"), expected=f"largest qualifying closure ({best:,.0f})",
                        why=f"recommended option closes {rec_close:,.0f} of a {gap:,.0f} gap")]
  return []


def check_reply_repeated(t: Turn) -> List[Dict[str, Any]]:
  cur = _norm(t.assistant_text)
  if len(cur) < 60:
    return []
  for prev in t.prior_assistant_texts:
    if _norm(prev) == cur:
      return [observation("reply_repeated", draft_id=t.draft_id, turn=t.turn, field="assistant_message",
                          stored_value=t.assistant_text[:160], why="identical to an earlier reply in this intake")]
  return []


_QUESTION_RE = re.compile(r"([^.?!]*\?)")


def check_loop(t: Turn) -> List[Dict[str, Any]]:
  qs = [_norm(q) for q in _QUESTION_RE.findall(t.assistant_text or "") if len(q.strip()) > 25]
  if not qs:
    return []
  history = " ".join(_norm(x) for x in t.prior_assistant_texts)
  for q in qs:
    if history.count(q) >= 2:
      return [observation("loop", draft_id=t.draft_id, turn=t.turn, field="assistant_message",
                          stored_value=q[:160], why="the same question has now been asked three or more times")]
  return []


def check_raw_field_name_shown(t: Turn) -> List[Dict[str, Any]]:
  keys = set(_fb.FIELD_BASIS.keys()) | set(_rf.FIELD_LABELS.keys()) | set(_rf.OPS_BUSINESS_WIDE_REQUIRED)
  text = str(t.assistant_text or "")
  shown = sorted(k for k in keys if "_" in k and re.search(rf"(?<![\w.]){re.escape(k)}(?![\w])", text))
  if shown:
    return [observation("raw_field_name_shown", draft_id=t.draft_id, turn=t.turn, field=shown[0],
                        stored_value=shown, why="the client was shown a machine field name")]
  return []


def check_required_field_empty_at_wrap(t: Turn) -> List[Dict[str, Any]]:
  bf = str((t.before or {}).get("active_focus") or "").lower()
  af = str((t.after or {}).get("active_focus") or "").lower()
  if bf == "ops" and af and af != "ops":
    missing = _rf.missing_ops_fields(_section(t.after, "ops"))
    if missing:
      return [observation("required_field_empty_at_wrap", draft_id=t.draft_id, turn=t.turn, field=f"ops.{missing[0]}",
                          stored_value=missing, expected="asked before the section closes",
                          why="the section closed with a field the submit gate requires still empty")]
  return []


def check_completed_with_hold_open(t: Turn) -> List[Dict[str, Any]]:
  if str((t.after or {}).get("status") or "").lower() != "completed":
    return []
  if str((t.before or {}).get("status") or "").lower() == "completed":
    return []
  fin = _section(t.after, "financials")
  holds = {k: v for k, v in fin.items() if "hold" in str(k).lower() and v}
  pending = (t.after or {}).get("pending_question_key")
  if holds or pending:
    return [observation("completed_with_hold_open", draft_id=t.draft_id, turn=t.turn, field="status",
                        stored_value={"holds": list(holds.keys()), "pending_question_key": pending},
                        why="the intake completed while a hold or a pending question was still open")]
  return []


def check_value_moved_without_cause(t: Turn) -> List[Dict[str, Any]]:
  user_figs = figures_in(t.user_text, at_least=1.0)
  if user_figs:
    return []
  out = []
  for sec in ("financials", "ops", "people"):
    before = numeric_leaves(_section(t.before, sec), sec)
    after = numeric_leaves(_section(t.after, sec), sec)
    for path, v in after.items():
      leaf = re.sub(r"\[\d+\]", "", path).rsplit(".", 1)[-1]
      if leaf in DERIVED_LEAVES or leaf.startswith("_"):
        continue
      if path not in before or _close(before[path], v):
        continue
      # accounted for when the reply speaks the new figure (a lever the client accepted by option id)
      if any(_close(v, e) for f_ in figures_in(t.assistant_text, at_least=1.0) for e in _equivalents(f_)):
        continue
      out.append(observation("value_moved_without_cause", draft_id=t.draft_id, turn=t.turn, field=path,
                             stored_value=v, expected=before[path], client_words=t.user_text,
                             why="moved on a turn whose message carried no figure and whose reply does not account for it"))
  return out


_RECEIPT_LINE_RE = re.compile(r"([a-z][a-z /&\-]+?)\s*(?:→|->)\s*\$?([\d,]+(?:\.\d+)?)(?:\s*per\s+(month|year|quarter))?", re.I)


def check_receipt_disagrees_with_store(t: Turn) -> List[Dict[str, Any]]:
  """The deterministic receipt format is 'label → $N per period'. Each
  labelled figure must be in the store in the label's basis."""
  try:
    from client_intake_and_finmo.capture_receipt import _LABELS  # type: ignore
  except Exception:
    return []
  by_label = {}
  for path, (label, per) in _LABELS.items():
    by_label.setdefault(str(label).lower(), []).append((path, per))
  leaves = numeric_leaves({k: v for k, v in (t.after or {}).items() if k in ("financials", "ops", "people")})
  # a receipt label names a LEAF; the leaf may live on a product row
  # (ops.lob_models[0].products[1].units_per_week_capacity), so match by
  # leaf name anywhere in the store, and accept a percent rendered x100.
  by_leaf: Dict[str, List[float]] = {}
  for path, v in leaves.items():
    by_leaf.setdefault(re.sub(r"\[\d+\]", "", path).rsplit(".", 1)[-1], []).append(v)
  out = []
  for m in _RECEIPT_LINE_RE.finditer(t.assistant_text or ""):
    label = m.group(1).strip().lower()
    try:
      value = float(m.group(2).replace(",", ""))
    except ValueError:
      continue
    if label not in by_label:
      continue
    matched = False
    for path, _per in by_label[label]:
      leaf = path.rsplit(".", 1)[-1]
      for stored in by_leaf.get(leaf, []):
        if any(_close(stored, e) for e in _equivalents(value) + (value / 100.0, value * 100.0)):
          matched = True
          break
      if matched:
        break
    if not matched:
      out.append(observation("receipt_disagrees_with_store", draft_id=t.draft_id, turn=t.turn, field=by_label[label][0][0],
                             stored_value=by_leaf.get(by_label[label][0][0].rsplit(".", 1)[-1]), expected=value,
                             why=f"the receipt says '{label} → {value:,.0f}' and the store does not hold it"))
  return out


def _asks_about(text: str, v: float) -> bool:
  for sent in re.split(r"(?<=[.?!])\s+", str(text or "")):
    if "?" in sent and any(_close(v, e) for f_ in figures_in(sent, at_least=1.0) for e in _equivalents(f_)):
      return True
  return False


def check_figure_unplaced(t: Turn) -> List[Dict[str, Any]]:
  figs = figures_in(t.user_text)
  if not figs:
    return []
  leaves = numeric_leaves({k: v for k, v in (t.after or {}).items() if k in ("financials", "ops", "people")})
  last_app = t.prior_assistant_texts[-1] if t.prior_assistant_texts else ""
  app_figs = figures_in(last_app) + figures_in(t.assistant_text)
  out = []
  for v in figs:
    if figure_in_store(v, leaves):
      continue
    if any(_close(v, e) for f_ in app_figs for e in _equivalents(f_)) and not _asks_about(t.assistant_text, v):
      # the client quoted the app's own number back; not a fact of theirs
      continue
    if _asks_about(t.assistant_text, v):
      continue
    out.append(observation("figure_unplaced", draft_id=t.draft_id, turn=t.turn, field="",
                           stored_value=None, expected=v, client_words=t.user_text,
                           why=f"the client stated {v:,.0f}; it appears in no stored leaf and the app did not ask about it"))
  return out


def check_correction_ignored(t: Turn) -> List[Dict[str, Any]]:
  figs = figures_in(t.user_text)
  if not figs:
    return []
  leaves = numeric_leaves({k: v for k, v in (t.after or {}).items() if k in ("financials", "ops", "people")})
  earlier = [f_ for txt in t.prior_user_texts for f_ in figures_in(txt)]
  out = []
  for v in figs:
    if figure_in_store(v, leaves):
      continue
    if any(_close(v, e) for f_ in earlier for e in (f_,)):
      out.append(observation("correction_ignored", draft_id=t.draft_id, turn=t.turn, field="",
                             stored_value=None, expected=v, client_words=t.user_text,
                             why=f"{v:,.0f} has now been stated more than once and is still in no stored leaf"))
  return out


CHECKS = (
  check_roster_not_in_basis,
  check_basis_sum_mismatch,
  check_unit_copied,
  check_refusal_violated,
  check_option_touches_refusal,
  check_recommendation_not_largest,
  check_reply_repeated,
  check_loop,
  check_raw_field_name_shown,
  check_required_field_empty_at_wrap,
  check_completed_with_hold_open,
  check_value_moved_without_cause,
  check_receipt_disagrees_with_store,
  check_figure_unplaced,
  check_correction_ignored,
)


def run_checks(t: Turn) -> List[Dict[str, Any]]:
  out: List[Dict[str, Any]] = []
  for chk in CHECKS:
    try:
      out.extend(chk(t))
    except Exception as exc:  # a broken check is an observation, never a crash
      out.append({"kind": "watcher_check_error", "severity": "minor", "detector": "code", "draft_id": t.draft_id,
                  "turn": t.turn, "field": chk.__name__, "client_words": "", "stored_value": None,
                  "expected": None, "why": f"{type(exc).__name__}: {str(exc)[:200]}"})
  return out
