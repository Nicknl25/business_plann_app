"""Issue database HTTP surface.

  POST /api/issues        -> Cowork's write path (report one sighting)
  GET  /api/admin/issues  -> JSON for the dashboard (registry + occurrences
                             + resolution events + counts)
  GET  /admin/issues      -> self-contained HTML dashboard

The write path validates loudly (400 with the vocabulary error) — a typo in
category/severity must bounce, not mint a phantom taxonomy. Reads are
read-only. Schema + lifecycle logic live in
client_intake_and_finmo/issue_registry.py.
"""

from __future__ import annotations

from typing import Any, Dict, List

from flask import jsonify


def _stringify(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  return [
    {k: (str(v) if v is not None else None) for k, v in r.items()}
    for r in rows
  ]


def post_issue_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)
  from intake_submission import get_mysql_connection  # type: ignore
  from client_intake_and_finmo import issue_registry  # type: ignore

  payload = request.get_json(silent=True) or {}
  conn = get_mysql_connection()
  try:
    try:
      state = issue_registry.report_issue(
        conn,
        signature=payload.get("signature"),
        category=payload.get("category"),
        severity=payload.get("severity"),
        observed=payload.get("observed"),
        expected=payload.get("expected"),
        draft_id=payload.get("draft_id") or "",
        planning_run_id=payload.get("planning_run_id") or "",
        business_name=payload.get("business_name") or "",
        persona=payload.get("persona") or "",
        turn_index=payload.get("turn_index"),
        section=payload.get("section") or "",
        stage=payload.get("stage") or "",
        title=payload.get("title") or "",
        resolution_class=payload.get("resolution_class") or "",
        probe=payload.get("probe"),
        evidence=payload.get("evidence"),
        source=payload.get("source") or "cowork",
      )
    except ValueError as exc:
      return (jsonify({"error": "invalid_issue", "detail": str(exc)}), 400)
    state = {k: (str(v) if v is not None else None) for k, v in state.items()}
    return jsonify({"status": "ok", "issue": state})
  finally:
    try:
      conn.close()
    except Exception:
      pass


def get_admin_issues_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)
  from intake_submission import get_mysql_connection  # type: ignore
  from client_intake_and_finmo import issue_registry  # type: ignore

  limit = min(500, max(1, int(request.args.get("limit") or 200)))
  status = str(request.args.get("status") or "")
  category = str(request.args.get("category") or "")
  conn = get_mysql_connection()
  try:
    try:
      issues = issue_registry.list_issues(
        conn, status=status, category=category, limit=limit
      )
    except ValueError as exc:
      return (jsonify({"error": "invalid_filter", "detail": str(exc)}), 400)
    occurrences = issue_registry.recent_occurrences(conn, limit=limit)
    cur = conn.cursor()
    try:
      cur.execute(
        """
        SELECT status, COUNT(*) AS n FROM issues GROUP BY status
        """
      )
      status_counts = {str(r[0]): int(r[1]) for r in cur.fetchall()}
      cur.execute(
        """
        SELECT category, status, COUNT(*) AS n
        FROM issues GROUP BY category, status
        """
      )
      category_counts: Dict[str, Dict[str, int]] = {}
      for cat, st, n in cur.fetchall():
        category_counts.setdefault(str(cat), {})[str(st)] = int(n)
      cur.execute(
        """
        SELECT e.id, e.signature, e.draft_id, e.event_type,
               LEFT(e.detail_json, 300) AS detail, e.created_at
        FROM issue_resolution_events e
        ORDER BY e.id DESC LIMIT %s
        """,
        (limit,),
      )
      cols = [d[0] for d in cur.description]
      events = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
      cur.close()
  finally:
    try:
      conn.close()
    except Exception:
      pass
  return jsonify(
    {
      "status_counts": status_counts,
      "category_counts": category_counts,
      "issues": _stringify(issues),
      "recent_occurrences": _stringify(occurrences),
      "resolution_events": _stringify(events),
    }
  )


_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Issues — admin</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 1.5rem; background: #111; color: #ddd; }
  h1 { font-size: 1.2rem; } h2 { font-size: 1rem; margin-top: 2rem; }
  table { border-collapse: collapse; width: 100%; font-size: 0.8rem; }
  th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #333; white-space: nowrap; }
  td.wrap { white-space: normal; max-width: 420px; }
  .open { color: #f77; } .recurring { color: #fa5; } .resolved { color: #7c7; }
  .blocker { color: #f55; font-weight: bold; } .major { color: #fa5; }
  .minor { color: #cc8; } .note { color: #999; }
  .confirmed { color: #7c7; } .observational { color: #cc8; }
  .hard_break { color: #f77; } .flow { color: #7bf; }
  .verdict { color: #d9f; } .experience { color: #fc7; }
  #counts span { margin-right: 1.2rem; }
  .muted { color: #888; }
  code { background: #222; padding: 1px 4px; border-radius: 3px; }
</style></head><body>
<h1>Issue registry <span class="muted" id="refreshed"></span></h1>
<div id="counts"></div>
<table id="issues"><thead><tr>
  <th>signature</th><th>title</th><th>cat</th><th>class</th><th>sev</th>
  <th>status</th><th>occ</th><th>first seen</th><th>last seen</th>
  <th>clean/quiet</th><th>resolution</th>
</tr></thead><tbody></tbody></table>
<h2>Recent occurrences</h2>
<table id="occ"><thead><tr>
  <th>at</th><th>signature</th><th>draft</th><th>business</th><th>persona</th>
  <th>turn</th><th>section</th><th>src</th><th>observed → expected</th>
</tr></thead><tbody></tbody></table>
<h2>Resolution events</h2>
<table id="events"><thead><tr>
  <th>at</th><th>signature</th><th>draft</th><th>event</th><th>detail</th>
</tr></thead><tbody></tbody></table>
<script>
async function refresh() {
  const r = await fetch('/api/admin/issues?limit=200');
  const data = await r.json();
  document.getElementById('refreshed').textContent =
    'refreshed ' + new Date().toLocaleTimeString();
  const catBits = Object.entries(data.category_counts || {}).map(([cat, m]) =>
    `<span class="${cat}">${cat}: <b>${Object.values(m).reduce((a, b) => a + b, 0)}</b></span>`);
  document.getElementById('counts').innerHTML =
    Object.entries(data.status_counts || {})
      .map(([k, v]) => `<span class="${k}">${k}: <b>${v}</b></span>`).join('') +
    ' | ' + catBits.join('');
  const ib = document.querySelector('#issues tbody'); ib.innerHTML = '';
  for (const i of data.issues) {
    const tr = document.createElement('tr');
    const res = i.resolution_basis
      ? `${i.resolution_basis} <span class="${i.resolution_confidence}">(${i.resolution_confidence})</span>`
      : '';
    tr.innerHTML = `<td><code>${i.signature}</code></td>
      <td class="wrap">${i.title || ''}</td>
      <td class="${i.category}">${i.category}</td>
      <td>${i.resolution_class}</td>
      <td class="${i.severity}">${i.severity}</td>
      <td class="${i.status}">${i.status}${i.reopened_count > 0 ? ' ×' + i.reopened_count : ''}</td>
      <td>${i.occurrence_count}</td>
      <td>${(i.first_seen_at || '').slice(0, 19)}</td>
      <td>${(i.last_seen_at || '').slice(0, 19)}</td>
      <td>${i.clean_exercise_count}/${i.runs_since_last_seen}</td>
      <td>${res}</td>`;
    ib.appendChild(tr);
  }
  const ob = document.querySelector('#occ tbody'); ob.innerHTML = '';
  for (const o of data.recent_occurrences) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${(o.created_at || '').slice(0, 19)}</td>
      <td><code>${o.signature}</code></td>
      <td>${(o.draft_id || '').slice(0, 8)}</td>
      <td>${o.business_name || ''}</td><td>${o.persona || ''}</td>
      <td>${o.turn_index ?? ''}</td><td>${o.section || ''}</td>
      <td>${o.source}</td>
      <td class="wrap">${(o.observed || '').slice(0, 160)} <span class="muted">→</span> ${(o.expected || '').slice(0, 160)}</td>`;
    ob.appendChild(tr);
  }
  const eb = document.querySelector('#events tbody'); eb.innerHTML = '';
  for (const e of data.resolution_events) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${(e.created_at || '').slice(0, 19)}</td>
      <td><code>${e.signature}</code></td>
      <td>${(e.draft_id || '').slice(0, 8)}</td>
      <td>${e.event_type}</td>
      <td class="wrap">${(e.detail || '').slice(0, 240)}</td>`;
    eb.appendChild(tr);
  }
}
refresh();
setInterval(refresh, 30000);
</script></body></html>
"""


def get_admin_issues_page_handler(*, app, request):
  return _PAGE, 200, {"Content-Type": "text/html; charset=utf-8"}
