"""THE ONE-READER REPORT - what the shadow window measured (one-reader build, step 1).

Nick asked for the real reader count once the shadow data is in. Cowork (1055)
set the measure: every client turn lands in exactly ONE state, and missing is
never agreement:

  agreed              the shadow ran, and its figures are the router's figures
  disagreed           the shadow ran, and one side has a figure the other lacks
  shadow_missing      no shadow row for the turn, or its status is error - the
                      error is named; the long multi-claim sentences most likely
                      to break a new reader show up HERE, not as agreement
  router_less         no router interpretation of her message on the turn - there
                      is no reading to agree with, so it is counted apart

Beside that, for every other reader that returned figures from her message on
the turn: the figures it found that the shadow did not (extra) and the shadow's
figures it did not find (missed). And the count Nick asked for: the distinct
readers that read her words, with the turns and paths on which each did.

This reads only what was already recorded - the router's record, the shadow
rows, the reader notes. It never reads a client's words.

Named limits: figures are compared as numbers (a 480 is a 480 whatever it was
per); a turn whose shadow and router hold no figures at all is agreed-on-nothing,
reported as its own count; derived values the app wrote are not in the router's
patch and so are not compared.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

TOL = 1e-6


def _numeric_leaves(obj: Any) -> List[float]:
  out: List[float] = []
  if isinstance(obj, bool):
    return out
  if isinstance(obj, (int, float)):
    return [float(obj)]
  if isinstance(obj, dict):
    for v in obj.values():
      out.extend(_numeric_leaves(v))
  elif isinstance(obj, (list, tuple)):
    for v in obj:
      out.extend(_numeric_leaves(v))
  elif isinstance(obj, str):
    try:
      out.extend(_numeric_leaves(json.loads(obj)))
    except Exception:
      pass
  return out


def _figure_set(values: Iterable[float]) -> List[float]:
  kept: List[float] = []
  for v in values:
    if not any(abs(v - k) <= TOL * max(1.0, abs(k)) for k in kept):
      kept.append(float(v))
  return sorted(kept)


def _minus(a: List[float], b: List[float]) -> List[float]:
  return [x for x in a if not any(abs(x - y) <= TOL * max(1.0, abs(y)) for y in b)]


def router_figures(router_rows: List[Dict[str, Any]]) -> Tuple[bool, List[float]]:
  """(had a reading of her message, figures in it). Only rows whose sentence WAS
  her message count; the proposal extractor reading the app's reply does not."""
  own = [r for r in router_rows if r.get("is_client_message") and r.get("status") == "ok"]
  vals: List[float] = []
  for r in own:
    vals.extend(_numeric_leaves(r.get("patch")))
    for f in r.get("unresolved_figures") or []:
      vals.extend(_numeric_leaves((f or {}).get("value")))
  return bool(own), _figure_set(vals)


def shadow_figures(interpretation: Optional[Dict[str, Any]]) -> List[float]:
  vals: List[float] = []
  for c in (interpretation or {}).get("claims") or []:
    if not isinstance(c, dict):
      continue
    for key in ("value_number", "value_low", "value_high"):
      if c.get(key) is not None:
        vals.extend(_numeric_leaves(c.get(key)))
  for u in (interpretation or {}).get("unresolved") or []:
    if isinstance(u, dict) and u.get("value_number") is not None:
      vals.extend(_numeric_leaves(u.get("value_number")))
  return _figure_set(vals)


def compare_turn(router_rows: List[Dict[str, Any]], shadow_rows: List[Dict[str, Any]],
                 reader_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
  had_router, r_figs = router_figures(router_rows)
  shadow_ok = [s for s in shadow_rows if s.get("status") == "ok" and isinstance(s.get("interpretation"), dict)]
  out: Dict[str, Any] = {"router_figures": r_figs, "shadow_figures": None, "readers": {}}
  if not had_router:
    out["state"] = "router_less"
  elif not shadow_ok:
    out["state"] = "shadow_missing"
    errors = [s.get("error") for s in shadow_rows if s.get("status") != "ok"]
    out["shadow_error"] = errors[0] if errors else "no shadow row for this turn"
  if shadow_ok:
    s_figs = shadow_figures(shadow_ok[-1]["interpretation"])
    out["shadow_figures"] = s_figs
    if "state" not in out:
      router_only, shadow_only = _minus(r_figs, s_figs), _minus(s_figs, r_figs)
      if not router_only and not shadow_only:
        out["state"] = "agreed_on_nothing" if not r_figs else "agreed"
      else:
        out["state"] = "disagreed"
        out["router_only"], out["shadow_only"] = router_only, shadow_only
  basis = out["shadow_figures"] if out["shadow_figures"] is not None else r_figs
  by_reader: Dict[str, List[float]] = defaultdict(list)
  for n in reader_rows:
    if not n.get("is_client_text") or n.get("error"):
      continue
    figs = _numeric_leaves(n.get("result"))
    if figs:
      by_reader[n["reader"]].extend(figs)
  for name, figs in by_reader.items():
    fs = _figure_set(figs)
    out["readers"][name] = {"figures": fs, "extra": _minus(fs, basis), "missed": _minus(basis, fs)}
  return out


def build(router_rows: List[Dict[str, Any]], shadow_rows: List[Dict[str, Any]],
          reader_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
  """All rows carry draft_id and turn. One entry per (draft, turn) that had a
  client message recorded anywhere."""
  keys = set()
  grouped: Dict[str, Dict[Tuple[str, Any], List[Dict[str, Any]]]] = {"r": defaultdict(list), "s": defaultdict(list),
                                                                     "n": defaultdict(list)}
  for tag, rows in (("r", router_rows), ("s", shadow_rows), ("n", reader_rows)):
    for row in rows:
      k = (str(row.get("draft_id")), row.get("turn"))
      grouped[tag][k].append(row)
      if tag == "r" and not row.get("is_client_message"):
        continue
      if tag == "n" and not row.get("is_client_text"):
        continue
      keys.add(k)
  turns = []
  states: Counter = Counter()
  reader_turns: Dict[str, set] = defaultdict(set)
  reader_sites: Dict[str, set] = defaultdict(set)
  reader_disagree: Counter = Counter()
  for k in sorted(keys, key=lambda x: (x[0], x[1] if isinstance(x[1], int) else -1)):
    cmp = compare_turn(grouped["r"][k], grouped["s"][k], grouped["n"][k])
    cmp["draft_id"], cmp["turn"] = k
    states[cmp["state"]] += 1
    turns.append(cmp)
    for n in grouped["n"][k]:
      if n.get("is_client_text"):
        reader_turns[n["reader"]].add(k)
        if n.get("call_site"):
          reader_sites[n["reader"]].add(n["call_site"])
    for name, rd in cmp["readers"].items():
      if rd["extra"] or rd["missed"]:
        reader_disagree[name] += 1
  readers = [{"reader": name, "turns": len(reader_turns[name]), "call_sites": sorted(reader_sites[name]),
              "turns_disagreeing_with_the_one_reading": reader_disagree.get(name, 0)}
             for name in sorted(reader_turns, key=lambda n: (-len(reader_turns[n]), n))]
  return {"client_turns": len(turns), "states": dict(states), "distinct_readers_of_her_words": len(readers),
          "readers": readers, "turns": turns}


def load(conn, draft_id: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
  """Read the three records and build the report. Read-only."""
  from client_intake_and_finmo import interpretation_contract as _shadow  # type: ignore
  from client_intake_and_finmo import reader_log as _readers  # type: ignore
  from client_intake_and_finmo import turn_interpretations as _router  # type: ignore

  def rows(table: str, cols: str, json_cols: Tuple[Tuple[str, str], ...]) -> List[Dict[str, Any]]:
    where, params = [], []
    if draft_id:
      where.append("draft_id=%s")
      params.append(str(draft_id))
    if since:
      where.append("created_at >= %s")
      params.append(str(since))
    sql = "SELECT draft_id, turn, %s FROM %s%s ORDER BY id" % (cols, table, (" WHERE " + " AND ".join(where)) if where else "")
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(sql, tuple(params))
      out = []
      for r in cur.fetchall():
        row = dict(r)
        for src, dst in json_cols:
          raw = row.pop(src, None)
          try:
            row[dst] = json.loads(raw) if raw else None
          except Exception:
            row[dst] = raw
        out.append(row)
      return out
    finally:
      cur.close()

  _router._ensure(conn)
  _shadow._ensure(conn)
  _readers._ensure(conn)
  router_rows = rows(_router.TABLE, "is_client_message, status, patch_json, unresolved_json",
                     (("patch_json", "patch"), ("unresolved_json", "unresolved_figures")))
  for r in router_rows:
    r["is_client_message"] = bool(r.get("is_client_message"))
  shadow_rows = rows(_shadow.TABLE, "status, error, contract_version, interpretation_json",
                     (("interpretation_json", "interpretation"),))
  reader_rows = rows(_readers.TABLE, "reader, call_site, is_client_text, result_json, error",
                     (("result_json", "result"),))
  for r in reader_rows:
    r["is_client_text"] = bool(r.get("is_client_text"))
  report = build(router_rows, shadow_rows, reader_rows)
  report["filters"] = {"draft_id": draft_id, "since": since}
  report["contract_versions"] = dict(Counter(str(s.get("contract_version")) for s in shadow_rows))
  return report
