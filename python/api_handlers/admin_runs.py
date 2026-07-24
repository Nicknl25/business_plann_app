"""Minimal admin view: runs, statuses, failures, attempt chains.

The thin end of the ops dashboard — enough to see the state of every
run at a glance instead of relying on buried alert emails. Two routes:

  GET /api/admin/runs   -> JSON (runs + supervisor actions + counts)
  GET /admin/runs       -> self-contained HTML page over that JSON

Read-only. No GPT, no mutation.
"""

from __future__ import annotations

from typing import Any, Dict, List

from flask import jsonify


def _rows(cur) -> List[Dict[str, Any]]:
  return [dict(r) for r in (cur.fetchall() or [])]


def get_admin_runs_handler(*, app, request):
  from intake_submission import get_mysql_connection  # type: ignore

  limit = min(200, max(1, int(request.args.get("limit") or 50)))
  conn = get_mysql_connection()
  try:
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        """
        SELECT pr.planning_run_id, pr.draft_id, d.business_name,
               pr.run_status, pr.current_stage, pr.current_stage_status,
               pr.failure_reason, pr.trigger_type, pr.resume_count,
               pr.source_planning_run_id, pr.superseded_by_planning_run_id,
               pr.started_at, pr.completed_at, pr.last_heartbeat_at,
               TIMESTAMPDIFF(SECOND, COALESCE(pr.last_heartbeat_at, pr.updated_at), NOW())
                 AS heartbeat_age_seconds
        FROM planning_runs pr
        LEFT JOIN intake_consult_drafts d ON d.draft_id = pr.draft_id
        ORDER BY pr.started_at DESC
        LIMIT %s
        """,
        (limit,),
      )
      runs = _rows(cur)
      cur.execute(
        "SELECT run_status, COUNT(*) AS n FROM planning_runs GROUP BY run_status"
      )
      counts = {str(r["run_status"]): int(r["n"]) for r in _rows(cur)}
      try:
        cur.execute(
          """
          SELECT draft_id, planning_run_id, action, attempt_number, outcome,
                 LEFT(detail, 300) AS detail, created_at
          FROM supervisor_actions
          ORDER BY created_at DESC
          LIMIT %s
          """,
          (limit,),
        )
        actions = _rows(cur)
      except Exception:
        # Table appears after the supervisor's first pass.
        actions = []
    finally:
      cur.close()
  finally:
    conn.close()
  return jsonify(
    {
      "status_counts": counts,
      "runs": [{k: (str(v) if v is not None else None) for k, v in r.items()} for r in runs],
      "supervisor_actions": [
        {k: (str(v) if v is not None else None) for k, v in a.items()} for a in actions
      ],
    }
  )


_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Runs — admin</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 1.5rem; background: #111; color: #ddd; }
  h1 { font-size: 1.2rem; } h2 { font-size: 1rem; margin-top: 2rem; }
  table { border-collapse: collapse; width: 100%; font-size: 0.82rem; }
  th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #333; white-space: nowrap; }
  td.wrap { white-space: normal; max-width: 420px; }
  .completed { color: #7c7; } .failed { color: #f77; } .running { color: #7bf; }
  .paused, .stopped { color: #fc7; }
  .stale { background: #402; }
  #counts span { margin-right: 1.2rem; }
  .muted { color: #888; }
</style></head><body>
<h1>Planning runs <span class="muted" id="refreshed"></span></h1>
<div id="counts"></div>
<table id="runs"><thead><tr>
  <th>started</th><th>business</th><th>status</th><th>stage</th>
  <th>hb age</th><th>trigger</th><th>chain</th><th>failure</th>
</tr></thead><tbody></tbody></table>
<h2>Supervisor actions</h2>
<table id="actions"><thead><tr>
  <th>at</th><th>draft</th><th>action</th><th>#</th><th>outcome</th><th>detail</th>
</tr></thead><tbody></tbody></table>
<script>
async function refresh() {
  const r = await fetch('/api/admin/runs?limit=80');
  const data = await r.json();
  document.getElementById('refreshed').textContent =
    'refreshed ' + new Date().toLocaleTimeString();
  document.getElementById('counts').innerHTML = Object.entries(data.status_counts)
    .map(([k, v]) => `<span class="${k}">${k}: <b>${v}</b></span>`).join('');
  const rb = document.querySelector('#runs tbody'); rb.innerHTML = '';
  for (const run of data.runs) {
    const tr = document.createElement('tr');
    const hb = parseInt(run.heartbeat_age_seconds || '0', 10);
    const stale = run.run_status === 'running' && hb > 900;
    if (stale) tr.className = 'stale';
    const chain = (run.source_planning_run_id ? 'rerun-of ' + run.source_planning_run_id.slice(0, 8) : '') +
                  (run.superseded_by_planning_run_id ? ' → ' + run.superseded_by_planning_run_id.slice(0, 8) : '');
    tr.innerHTML = `<td>${run.started_at || ''}</td>
      <td>${run.business_name || run.draft_id.slice(0, 8)}</td>
      <td class="${run.run_status}">${run.run_status}${stale ? ' ⚠ stale' : ''}</td>
      <td>${run.current_stage || ''}</td>
      <td>${run.run_status === 'running' ? hb + 's' : ''}</td>
      <td>${run.trigger_type || ''}</td>
      <td>${chain}</td>
      <td class="wrap">${(run.failure_reason || '').slice(0, 240)}</td>`;
    rb.appendChild(tr);
  }
  const ab = document.querySelector('#actions tbody'); ab.innerHTML = '';
  for (const a of data.supervisor_actions) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${a.created_at || ''}</td><td>${(a.draft_id || '').slice(0, 8)}</td>
      <td>${a.action}</td><td>${a.attempt_number || ''}</td><td>${a.outcome}</td>
      <td class="wrap">${(a.detail || '').slice(0, 240)}</td>`;
    ab.appendChild(tr);
  }
}
refresh();
setInterval(refresh, 30000);
</script></body></html>
"""


def get_admin_runs_page_handler(*, app, request):
  return _PAGE, 200, {"Content-Type": "text/html; charset=utf-8"}
