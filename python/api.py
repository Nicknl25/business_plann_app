import os
import sys
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, g, jsonify, request

try:
  from flask_cors import CORS  # type: ignore
except Exception:  # pragma: no cover
  CORS = None  # type: ignore

try:
  from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
  load_dotenv = None  # type: ignore


def getenv(name: str) -> Optional[str]:
  value = os.getenv(name)
  if value is None:
    return None
  value = value.strip()
  return value or None


def _configure_logging() -> None:
  """
  Timestamped stderr logging for the whole process.

  Configuring the root logger BEFORE app.logger is first touched keeps Flask
  from attaching its own (timestamp-less) default handler; every module
  logger then propagates here and shares one format. Idempotent so test
  harnesses that import api twice don't double-log.
  """
  root = logging.getLogger()
  if not any(getattr(handler, "_bplan_ts_handler", False) for handler in root.handlers):
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
      logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    handler._bplan_ts_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
  root.setLevel(logging.INFO)


def create_app() -> Flask:
  _configure_logging()
  if load_dotenv:
    try:
      # Force load variables from the project root .env (consistent across CWDs).
      root_dir = Path(__file__).resolve().parent.parent
      env_path = root_dir / ".env"
      load_dotenv(str(env_path), override=True)
    except Exception:
      # Failing to load .env should not prevent the app from starting;
      # environment variables may already be configured.
      pass

  app = Flask(__name__)
  # Silence Werkzeug's per-request logs in dev.
  logging.getLogger("werkzeug").setLevel(logging.ERROR)

  # Allow importing local helper modules
  root_path = Path(__file__).resolve().parent
  sys.path.append(str(root_path / "client_intake_and_finmo"))

  if CORS is not None:
    # Enable CORS for all routes to support the separate frontend dev server.
    CORS(app)

  # STARTUP ENSURE-PATH (Nick, 2026-08-30). Every lookup table is created AND
  # seeded here, once, when the app comes up - not on first use. On 2026-08-28
  # the payroll contract's DB row disagreed with its code for four live reruns
  # because the ensure ran only inside a snapshot helper nobody called. A
  # failure here is logged at ERROR and the app still starts; the writing
  # phase verifies its own table live before running and refuses on mismatch.
  try:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      _ensure_all_post_intake_lookup_tables, get_mysql_connection,
    )
    _conn = get_mysql_connection()
    try:
      _ensure_all_post_intake_lookup_tables(_conn)
    finally:
      try:
        _conn.close()
      except Exception:
        pass
    app.logger.info("STARTUP lookup tables ensured and seeded")
  except Exception as _exc:  # noqa: BLE001
    app.logger.error("STARTUP lookup ensure FAILED: %s: %s", type(_exc).__name__, str(_exc)[:300])

  @app.before_request
  def _stamp_request_start():
    g._bplan_req_start = time.monotonic()
    # GPT RUN IDENTITY AT THE REQUEST BOUNDARY (Nick 2026-09-10). Every
    # GPT call this request makes is recorded against this draft in the
    # response-store usage ledger, which is what keeps two concurrent
    # clients' judgments apart. Stamping it here - ONE door - rather
    # than per handler means a route added later cannot quietly miss it
    # (four of the fifteen judgments are made mid-conversation, and an
    # unstamped call is a judgment the written plan silently loses).
    # The run path re-stamps with its planning_run_id once it has one.
    try:
      draft_id = ""
      if request.method in ("POST", "PUT", "PATCH"):
        body = request.get_json(silent=True)
        if isinstance(body, dict):
          draft_id = str(body.get("draft_id") or "").strip()
      if not draft_id:
        draft_id = str(request.args.get("draft_id") or "").strip()
      if draft_id:
        from client_intake_and_finmo.openai_http import (  # type: ignore
          set_gpt_run_identity as _set_ident,
        )
        _set_ident(draft_id=draft_id)
    except Exception:
      pass

  @app.after_request
  def log_api_request(response):
    """
    One INFO line per /api request: method, path, status, duration, draft_id.
    Logging must never break a request, so failures here are swallowed by
    design (declared exception to the fail-loud rule).
    """
    try:
      if request.method != "OPTIONS" and request.path.startswith("/api/"):
        started = getattr(g, "_bplan_req_start", None)
        elapsed_ms = (time.monotonic() - started) * 1000.0 if started is not None else -1.0
        draft_id = request.args.get("draft_id") or ""
        if not draft_id and request.is_json:
          body = request.get_json(silent=True)
          if isinstance(body, dict):
            draft_id = str(body.get("draft_id") or "")
        app.logger.info(
          "REQ %s %s -> %s %.0fms draft=%s",
          request.method, request.path, response.status_code, elapsed_ms, draft_id or "-",
        )
        if request.method == "POST" and request.path == "/api/intake-consult":
          # THE REPLY THAT PERSISTED IS THE REPLY THAT IS SENT: door B of the
          # intake guard may have rewritten the assistant text before the
          # write; the response body follows it.
          _final = getattr(g, "_guard_final_text", None)
          if _final and response.is_json:
            _body = response.get_json(silent=True)
            if isinstance(_body, dict) and _body.get("assistant_message") and _body.get("assistant_message") != _final:
              _body["assistant_message"] = _final
              response.set_data(json.dumps(_body, ensure_ascii=False))
          # A receipt placeholder that never reached the persist door says nothing.
          if response.is_json:
            _body2 = response.get_json(silent=True)
            if isinstance(_body2, dict) and "[[app-receipt:" in str(_body2.get("assistant_message") or ""):
              from client_intake_and_finmo import receipt_after_guard as _rag
              _body2["assistant_message"] = _rag.strip(str(_body2.get("assistant_message") or ""))
              response.set_data(json.dumps(_body2, ensure_ascii=False))
          # Every read of her words this turn, written once (one-reader step 1b).
          try:
            from client_intake_and_finmo import reader_log as _reader_log
            _reader_log.flush()
          except Exception:
            pass
          # Flush the run-vitals turn row armed at TURN_BEGIN. Best-effort
          # by the same contract as the REQ log itself.
          from client_intake_and_finmo import run_vitals as _run_vitals
          _reply = response.get_json(silent=True)
          _run_vitals.finish_turn(
            http_status=response.status_code,
            latency_ms=int(elapsed_ms) if elapsed_ms >= 0 else None,
            reply_chars=response.calculate_content_length(),
            section_after=str((_reply or {}).get("active_focus") or "")
            if isinstance(_reply, dict)
            else "",
          )
    except Exception:
      pass
    return response

  @app.after_request
  def add_cors_headers(response):
    """
    Ensure CORS headers are present even if flask-cors is unavailable.
    """
    origin = request.headers.get("Origin")
    # In dev, allow any origin so Vite (5173) can call this API.
    response.headers["Access-Control-Allow-Origin"] = origin or "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Headers"] = (
      "Content-Type, Authorization"
    )
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

  @app.route("/api/ping", methods=["GET", "OPTIONS"])
  def ping():
    """THE STORE ANSWERS (Cowork 1270, 2026-09-15): one cheap call that tells 'the store is
    down' from 'my browser is down' - no database, no body to parse beyond this."""
    import os as _os
    import time as _time
    return jsonify({"ok": True, "pid": _os.getpid(), "time": _time.strftime("%Y-%m-%dT%H:%M:%S")})

  @app.route("/api/business-types", methods=["GET", "OPTIONS"])
  def get_business_types():
    """
    Return the list of business types sourced from naics_master.business_types.

    - Split comma-separated values
    - Trim whitespace
    - Drop blanks/nulls
    - Deduplicate

    Response shape:
    [
      { "id": 1, "display_name": "Accounting Firm" },
      { "id": 2, "display_name": "Auto Repair" },
      ...
    ]
    """
    from api_handlers.business_types import get_business_types_handler

    return get_business_types_handler(app=app, request=request)

  @app.route("/api/runtime-probe", methods=["GET", "OPTIONS"])
  def get_runtime_probe():
    from api_handlers.intake_consult import get_runtime_probe_payload

    return jsonify(get_runtime_probe_payload())

  @app.route("/api/financials", methods=["POST", "OPTIONS"])
  def post_financials():
    """
    Receive intake submission and trigger downstream processing.
    """
    from api_handlers.financials import post_financials_handler

    return post_financials_handler(app=app, request=request)

  @app.route("/api/industry-types", methods=["GET", "OPTIONS"])
  def get_industry_types():
    """
    Return the list of industry types from MySQL.

    Response shape:
    [
      { "id": 1, "naics_code": "721", "display_name": "Accommodation" },
      { "id": 2, "naics_code": "72", "display_name": "Accommodation and Food Services" },
      ...
    ]
    """
    from api_handlers.industry_types import get_industry_types_handler

    return get_industry_types_handler(app=app, request=request)

  @app.route("/api/intake-guard/<draft_id>", methods=["GET"])
  def get_intake_guard_actions(draft_id: str):
    """What the intake guard did on a draft: every rewrite, ask and hold,
    with the patch, the receipt and the why (Nick 2026-09-12)."""
    from client_intake_and_finmo.intake_submission import get_mysql_connection
    from client_intake_and_finmo.intake_guard import audit as _gaudit
    conn = get_mysql_connection()
    try:
      return jsonify({"draft_id": draft_id, "actions": _gaudit.actions_for(conn, draft_id)})
    finally:
      conn.close()

  @app.route("/api/intake-interpretations/<draft_id>", methods=["GET"])
  def get_intake_interpretations(draft_id: str):
    """What the app understood from each client sentence on a draft: every
    router result as it was returned, with the call site that asked and whether
    the sentence it read was the client's own (one-reader build, step 0,
    Nick 2026-09-14). Read beside the store to check understanding against
    what was written."""
    from client_intake_and_finmo.intake_submission import get_mysql_connection
    from client_intake_and_finmo import turn_interpretations as _ti
    from client_intake_and_finmo import interpretation_contract as _shadow
    from client_intake_and_finmo import reader_log as _reader_log
    conn = get_mysql_connection()
    try:
      return jsonify({"draft_id": draft_id, "interpretations": _ti.for_draft(conn, draft_id),
                      # step 1: the v1 contract read in shadow, same turns, side by side
                      "shadow": _shadow.for_draft(conn, draft_id),
                      # step 1b: every other reader of her words, and what it concluded
                      "readers": _reader_log.for_draft(conn, draft_id)})
    finally:
      conn.close()

  @app.route("/api/shadow-replays", methods=["GET"])
  def get_shadow_replays():
    """Every replayed or forced shadow row with its WHOLE source draft id and
    message index (Nick 2026-09-14: eight characters where thirty-two are needed).
    Optional ?prefix= (for example br_ or forced2_)."""
    from client_intake_and_finmo.intake_submission import get_mysql_connection
    from client_intake_and_finmo import interpretation_contract as _shadow
    conn = get_mysql_connection()
    try:
      return jsonify({"replays": _shadow.replays(conn, prefix=request.args.get("prefix") or "")})
    finally:
      conn.close()

  @app.route("/api/shadow-rescored", methods=["GET"])
  def get_shadow_rescored():
    """A replay family scored by TODAY's checks beside its stored score and the checks
    version that produced it (Cowork 1137). ?prefix= is required and matched literally."""
    from client_intake_and_finmo.intake_submission import get_mysql_connection
    from client_intake_and_finmo import interpretation_contract as _shadow
    prefix = str(request.args.get("prefix") or "").strip()
    if not prefix:
      return jsonify({"error": "prefix_required", "detail": "name a replay family, for example br_ or var14a_"}), 400
    conn = get_mysql_connection()
    try:
      return jsonify({"checks_version": _shadow.CHECKS_VERSION, "rows": _shadow.rescored(conn, prefix)})
    finally:
      conn.close()

  @app.route("/api/one-reader-report", methods=["GET"])
  def get_one_reader_report():
    """What the shadow window measured: per client turn, agreed / disagreed /
    shadow_missing / router_less, what every other reader of her words found,
    and the distinct count of those readers (one-reader build step 1; Cowork's
    three-state measure). Optional ?draft_id= and ?since=YYYY-MM-DD HH:MM:SS."""
    from client_intake_and_finmo.intake_submission import get_mysql_connection
    from client_intake_and_finmo import one_reader_report as _orr
    # A MALFORMED FILTER IS REFUSED BY NAME (2026-09-14): ?since=13:40 reached MySQL as a
    # timestamp and came back a 500 three times - the same class as the issues API's
    # unknown field: say what was wrong and what is accepted, write nothing, read nothing.
    _since = request.args.get("since") or None
    if _since is not None:
      import datetime as _dt
      _ok = False
      for _fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
          _dt.datetime.strptime(_since, _fmt)
          _ok = True
          break
        except ValueError:
          continue
      if not _ok:
        return jsonify({"error": "bad_since", "since": _since,
                        "accepted": "YYYY-MM-DD, YYYY-MM-DD HH:MM or YYYY-MM-DD HH:MM:SS"}), 400
    conn = get_mysql_connection()
    try:
      return jsonify(_orr.load(conn, draft_id=request.args.get("draft_id") or None, since=_since))
    finally:
      conn.close()

  @app.route("/api/intake-consult", methods=["POST", "OPTIONS"])
  def post_intake_consult():
    """
    GPT-led operational intake consultant conversation (iterative).

    Request shape:
      { "client_id": "...", "message": "..." }
    """
    from api_handlers.intake_consult import post_intake_consult_handler

    return post_intake_consult_handler(app=app, request=request)

  @app.route("/api/intake-consult/session", methods=["POST", "OPTIONS"])
  def post_intake_consult_session():
    """
    Create a new durable pre-submit consultant draft and return {draft_id, client_id}.
    """
    from api_handlers.intake_consult import post_intake_consult_session_handler

    return post_intake_consult_session_handler(app=app, request=request)

  @app.route("/api/intake-consult/draft", methods=["GET", "OPTIONS"])
  def get_intake_consult_draft():
    from api_handlers.intake_consult import get_intake_consult_draft_handler

    return get_intake_consult_draft_handler(app=app, request=request)

  @app.route("/api/intake-consult/system-run", methods=["POST", "OPTIONS"])
  def post_intake_consult_system_run():
    from api_handlers.intake_consult import post_intake_consult_system_run_handler

    return post_intake_consult_system_run_handler(app=app, request=request)

  @app.route("/api/intake-consult/system-run/control", methods=["POST", "OPTIONS"])
  def post_intake_consult_system_run_control():
    from api_handlers.intake_consult import post_intake_consult_system_run_control_handler

    return post_intake_consult_system_run_control_handler(app=app, request=request)

  @app.route("/api/intake-consult/system-run/status", methods=["GET", "OPTIONS"])
  def get_intake_consult_system_run_status():
    from api_handlers.intake_consult import get_intake_consult_system_run_status_handler

    return get_intake_consult_system_run_status_handler(app=app, request=request)

  @app.route("/debug/state/<draft_id>", methods=["GET", "OPTIONS"])
  def get_intake_consult_debug_state(draft_id):
    from api_handlers.intake_consult import get_intake_consult_debug_state_handler

    return get_intake_consult_debug_state_handler(app=app, request=request, draft_id=draft_id)

  @app.route("/api/target-market/session", methods=["POST", "OPTIONS"])
  def post_target_market_session():
    """
    Ensure a durable target market draft exists for an existing intake draft_id.
    """
    from api_handlers.target_market import post_target_market_session_handler

    return post_target_market_session_handler(app=app, request=request)

  @app.route("/api/people-capability/session", methods=["POST", "OPTIONS"])
  def post_people_capability_session():
    """
    Ensure a durable People & Capability draft exists for an existing intake draft_id.
    """
    from api_handlers.people_capability import post_people_capability_session_handler

    return post_people_capability_session_handler(app=app, request=request)

  @app.route("/api/people-capability/draft", methods=["GET", "OPTIONS"])
  def get_people_capability_draft():
    from api_handlers.people_capability import get_people_capability_draft_handler

    return get_people_capability_draft_handler(app=app, request=request)

  @app.route("/api/people-capability", methods=["POST", "OPTIONS"])
  def post_people_capability():
    """
    Durable People & Capability conversation.

    Request: { draft_id, message?, business_name?, business_type? }
    """
    from api_handlers.people_capability import post_people_capability_handler

    return post_people_capability_handler(app=app, request=request)

  @app.route("/api/target-market/draft", methods=["GET", "OPTIONS"])
  def get_target_market_draft():
    from api_handlers.target_market import get_target_market_draft_handler

    return get_target_market_draft_handler(app=app, request=request)

  @app.route("/api/target-market", methods=["POST", "OPTIONS"])
  def post_target_market_consult():
    """
    GPT-led target market discovery consult (iterative).

    Uses the operational consult summary as context and produces:
      - selections of ACS codes by segment (stored, not shown to user)
      - target_market_summary paragraph
      - confidence score
    """
    from api_handlers.target_market import post_target_market_consult_handler

    return post_target_market_consult_handler(app=app, request=request)

  @app.route("/api/admin/runs", methods=["GET", "OPTIONS"])
  def get_admin_runs():
    """
    Read-only run/supervisor state for the minimal admin view.
    """
    from api_handlers.admin_runs import get_admin_runs_handler

    return get_admin_runs_handler(app=app, request=request)

  @app.route("/admin/runs", methods=["GET"])
  def get_admin_runs_page():
    """
    Self-contained HTML admin page over /api/admin/runs.
    """
    from api_handlers.admin_runs import get_admin_runs_page_handler

    return get_admin_runs_page_handler(app=app, request=request)

  @app.route("/api/issues", methods=["POST", "OPTIONS"])
  def post_issue():
    """
    Persona-testing issue write path (Cowork): report one issue sighting.
    """
    from api_handlers.issues_api import post_issue_handler

    return post_issue_handler(app=app, request=request)

  @app.route("/api/issues", methods=["GET"])
  def get_issues():
    """The read half of the handshake: what was posted, filtered by kind and
    since. Without it Cowork could file and never read back, which is how
    three runs died on one defect it had already named (Nick 2026-09-13)."""
    from api_handlers.issues_api import get_issues_handler

    return get_issues_handler(app=app, request=request)

  @app.route("/api/issues/help", methods=["GET", "OPTIONS"])
  def get_issues_help():
    """The route, its parameters, the kind vocabulary and the claim shape."""
    from api_handlers.issues_api import get_issues_help_handler

    return get_issues_help_handler(app=app, request=request)

  @app.route("/api/issues/stream", methods=["GET", "OPTIONS"])
  def issues_stream():
    """EVERYTHING SINCE id N, with a SHORT hold. The bridge between VS and Cowork.

    WHY IT IS SHAPED EXACTLY LIKE THIS (Nick 2026-09-22, relaying Cowork's own
    measurements of its side):

      NOTHING CAN WAKE COWORK FROM OUTSIDE. No inbound endpoint, no POST, no
      signal. Its only wake is its own scheduled message back into its session,
      floor one minute. Clock-driven, never event-driven. So the bridge cannot
      push; it can only be there when Cowork looks.

      A COWORK TURN CANNOT BLOCK FOR MINUTES. Browser JavaScript is its only
      path to 127.0.0.1:5050 and there is a hard 45-second CDP timeout - 60s
      failed, 35s returned. So the hold is capped at 30 seconds and RETURNS
      EMPTY rather than hanging. Cowork chains several inside one turn, which
      gives sub-30-second latency while it is active with neither side on a
      timer. The hole is between its turns and is bounded by its wake floor.

      CURSOR, NEVER "THE NEXT MESSAGE". Cowork's extension and MCP servers drop
      mid-operation. A cursor read is idempotent in both directions: a DROPPED
      poll loses nothing, because the client has not advanced its cursor and the
      same call returns the same rows; a REPEATED poll duplicates nothing, for
      the same reason. "Give me the next message" is unsafe on a transport that
      can vanish after the server has spoken and before the client has heard.
      Cowork said this would matter more than the latency. It is right: latency
      costs minutes, a lost or doubled finding costs a run.

    GET /api/issues/stream?since_id=1221&wait=30&exclude_source=cowork
      -> {"rows": [...], "cursor": 1234, "count": 2, "waited_seconds": 0.0}

    cursor is what to pass as since_id next time. When nothing arrived it comes
    back unchanged, so a caller that stores it can never skip a row.
    """
    if request.method == "OPTIONS":
      return ("", 204)
    import time as _time
    from flask import jsonify as _jsonify
    from client_intake_and_finmo.intake_submission import get_mysql_connection as _conn

    # A CURSOR NAME WE DO NOT RECOGNISE IS AN ERROR, NEVER A ZERO
    # (Cowork's blocker, 2026-09-22, with a thirty-second curl repro).
    #
    # This endpoint shipped honouring exactly one spelling, `since_id`, and
    # SILENTLY DEFAULTING TO 0 for anything else. Cowork tried cursor, since,
    # after, from, cursor_id, min_cursor, since_cursor and last, got an
    # identical fifty-row payload every time, and correctly reported that the
    # cursor was ignored - because from the outside it was. cursor=99999
    # returning fifty rows is the tell: a fallback that manufactures a
    # plausible answer out of a caller's mistake. What was deployed was "the
    # first fifty rows, immediately", and the worst part is that it LOOKED like
    # it worked.
    #
    # Same class as everything else we have taken out this month: a silent
    # default standing in for a value nobody supplied. So every spelling a
    # caller might reasonably reach for is accepted, and anything we do not
    # recognise is a 400 that names what we do understand.
    _CURSOR_NAMES = ("since_id", "cursor", "since", "after", "from", "cursor_id",
                     "min_cursor", "since_cursor", "last", "since_cursor_id")
    _KNOWN = set(_CURSOR_NAMES) | {"wait", "limit", "exclude_source", "source", "nonce", "_"}
    _unknown = [k for k in request.args.keys() if k not in _KNOWN]
    if _unknown:
      from flask import jsonify as _jf
      return (_jf({"error": "unknown_parameter", "unknown": sorted(_unknown),
                   "detail": "refused rather than defaulted - an unrecognised "
                             "cursor name used to read as 0 and return the "
                             "first page, which looks like success",
                   "cursor_names": list(_CURSOR_NAMES),
                   "known": sorted(_KNOWN)}), 400)

    def _int_arg(name, default, lo, hi):
      try:
        return max(lo, min(hi, int(float(request.args.get(name, default)))))
      except (TypeError, ValueError):
        return default

    _given = {n: request.args.get(n) for n in _CURSOR_NAMES if request.args.get(n) is not None}
    _values = set()
    for _raw in _given.values():
      try:
        _values.add(int(float(_raw)))
      except (TypeError, ValueError):
        from flask import jsonify as _jf
        return (_jf({"error": "bad_cursor", "detail": "cursor must be a number",
                     "given": _given}), 400)
    if len(_values) > 1:
      from flask import jsonify as _jf
      return (_jf({"error": "conflicting_cursors", "given": _given,
                   "detail": "two cursor names with different values"}), 400)
    since_id = max(0, min(10 ** 12, _values.pop())) if _values else 0
    wait_s = _int_arg("wait", 0, 0, 30)          # HARD 30s CAP - CDP dies at 45
    limit = _int_arg("limit", 50, 1, 200)
    exclude = str(request.args.get("exclude_source") or request.args.get("source") or "").strip().lower()

    _sql = (
      "SELECT o.id, o.source, o.created_at, o.business_name, o.persona, "
      "       o.draft_id, o.turn_index, o.stage, o.severity, o.observed, "
      "       o.expected, i.category, i.title, i.signature, o.issue_id "
      "FROM issue_occurrences o LEFT JOIN issues i ON i.issue_id = o.issue_id "
      "WHERE o.id > %s "
    )
    _params = [since_id]
    if exclude:
      _sql += "AND (o.source IS NULL OR LOWER(o.source) <> %s) "
      _params.append(exclude)
    _sql += "ORDER BY o.id ASC LIMIT %s"

    def _fetch():
      conn = _conn()
      try:
        cur = conn.cursor()
        cur.execute(_sql, tuple(_params + [limit]))
        cols = ("id", "source", "created_at", "business_name", "persona",
                "draft_id", "turn_index", "stage", "severity", "observed",
                "expected", "category", "title", "signature", "issue_id")
        out = []
        for row in cur.fetchall():
          rec = dict(zip(cols, row))
          rec["id"] = int(rec["id"] or 0)
          rec["created_at"] = str(rec["created_at"] or "")
          # EVERY ROW CARRIES THE CURSOR TO RESUME FROM AFTER IT (Nick/Cowork
          # 2026-09-22). With the cursor only in the envelope, a client that
          # drops after processing ten of fifty rows can only re-request all
          # fifty or skip the other forty - it has no way to say where it got
          # to. Per row it can commit its cursor as it goes.
          #
          # And the two numbers are named apart, because their difference is
          # the whole trap: `occurrence_id` is one per FILING and only ever
          # increases - it is the cursor. `issue_id` is the DEDUPED identity
          # and is reused by every refiling of the same signature, so it goes
          # down as well as up and must never be used to resume.
          rec["occurrence_id"] = rec["id"]
          rec["cursor"] = rec["id"]
          out.append(rec)
        return out
      finally:
        try:
          conn.close()
        except Exception:
          pass

    _started = _time.time()
    try:
      rows = _fetch()
      # THE HOLD. Short sleeps rather than one long one, so the caller's own
      # timeout always wins and a worker is never parked longer than asked.
      while not rows and (_time.time() - _started) < wait_s:
        _time.sleep(0.5)
        rows = _fetch()
    except Exception as _exc:                                 # noqa: BLE001
      return (_jsonify({"error": "stream_unavailable",
                        "detail": "%s: %s" % (type(_exc).__name__, _exc),
                        "cursor": since_id, "rows": [], "count": 0}), 503)
    return _jsonify({
      "rows": rows,
      "count": len(rows),
      # UNCHANGED WHEN NOTHING CAME, so a client that stores it cannot skip.
      "cursor": max([r["id"] for r in rows], default=since_id),
      "waited_seconds": round(_time.time() - _started, 2),
      "max_wait_seconds": 30,
    })

  @app.route("/api/handoff", methods=["GET", "POST", "OPTIONS"])
  def handoff_turn():
    """ONE LOCK AND ONE STATUS LINE FOR ALL THREE (Nick 2026-09-22).

    VS and mini already share replay_gate/HANDOFF.md: its first line says whose
    turn it is, and the watcher launches whoever is named. Cowork drives the app
    as a client through a browser and cannot be launched that way, but it can
    hold and release the same lock - so this is that one line, over HTTP.

    GET  -> {"status", "holder", "turn", "task"}   whose turn it is right now.
    POST {"claim": "cowork"}    take the turn (refused when someone else holds it)
    POST {"release": "cowork", "to": "VS", "note": "..."}   hand it on.

    Deliberately thin: it reads and writes the first line of the file the
    watcher already owns. There is no second source of truth, because two
    places recording whose turn it is would be the same class of defect as two
    places recording a capacity.
    """
    if request.method == "OPTIONS":
      return ("", 204)
    from flask import jsonify as _jsonify
    from pathlib import Path as _Path
    _hand = _Path(__file__).resolve().parents[1] / "replay_gate" / "HANDOFF.md"
    _AGENTS = {"vs": "VS", "mini": "mini", "cowork": "cowork", "nick": "Nick"}

    def _read():
      _text = _hand.read_text(encoding="utf-8")
      _lines = _text.splitlines()
      _status = _lines[0].split(":", 1)[1].strip() if _lines and _lines[0].startswith("STATUS:") else ""
      _holder = _status.split("-", 1)[1] if _status.startswith("awaiting-") else ""
      import re as _re
      _t = _re.search(r"^TURN:\s*(\d+)\s*/\s*(\d+)\s*$", _text, _re.M)
      _task = ""
      if "TASK:" in _text:
        _after = _text.split("TASK:", 1)[1]
        _task = _after.split("RESULT:", 1)[0].strip()[:2000]
      return {"status": _status, "holder": _holder, "text": _text,
              "turn": int(_t.group(1)) if _t else 0,
              "cap": int(_t.group(2)) if _t else 0, "task": _task}

    def _write_status(new_status: str):
      _cur = _read()
      _lines = _cur["text"].splitlines()
      _lines[0] = "STATUS: %s" % new_status
      _hand.write_text("\n".join(_lines) + "\n", encoding="utf-8")

    try:
      if request.method == "GET":
        _s = _read()
        return _jsonify({"status": _s["status"], "holder": _s["holder"],
                         "turn": _s["turn"], "cap": _s["cap"], "task": _s["task"]})
      _body = request.get_json(silent=True) or {}
      _claim = str(_body.get("claim") or "").strip().lower()
      _release = str(_body.get("release") or "").strip().lower()
      _s = _read()
      if _claim:
        if _claim not in _AGENTS:
          return (_jsonify({"error": "unknown_agent", "known": sorted(_AGENTS)}), 400)
        # A LOCK THAT CAN BE TAKEN FROM ITS HOLDER IS NOT A LOCK. The only
        # status a claim may overwrite is one that names nobody working -
        # awaiting-Nick and the stopped-* family mean the floor is free.
        if _s["holder"] and _s["holder"].lower() not in ("nick",):
          return (_jsonify({"error": "turn_held", "holder": _s["holder"],
                            "detail": "%s holds the turn; wait for the release"
                                      % _s["holder"]}), 409)
        _write_status("awaiting-%s" % _AGENTS[_claim])
        return _jsonify({"ok": True, "status": "awaiting-%s" % _AGENTS[_claim]})
      if _release:
        if _s["holder"].lower() != _release:
          return (_jsonify({"error": "not_the_holder", "holder": _s["holder"]}), 409)
        _to = str(_body.get("to") or "Nick").strip().lower()
        if _to not in _AGENTS:
          return (_jsonify({"error": "unknown_agent", "known": sorted(_AGENTS)}), 400)
        _write_status("awaiting-%s" % _AGENTS[_to])
        return _jsonify({"ok": True, "status": "awaiting-%s" % _AGENTS[_to]})
      return (_jsonify({"error": "claim_or_release_required"}), 400)
    except Exception as _exc:                                 # noqa: BLE001
      return (_jsonify({"error": "handoff_unavailable",
                        "detail": "%s: %s" % (type(_exc).__name__, _exc)}), 500)

  @app.route("/api/intake-watch/<draft_id>", methods=["GET", "OPTIONS"])
  def get_intake_watch(draft_id: str):
    """
    The intake watcher's observations for one draft - what it NOTICED, turn
    by turn. Read-only; the watcher never writes the draft.
    """
    if request.method == "OPTIONS":
      return ("", 204)
    from flask import jsonify as _jsonify
    from client_intake_and_finmo.intake_submission import get_mysql_connection as _conn
    from client_intake_and_finmo.intake_watcher.observe import MySQLStore as _Store
    conn = _conn()
    try:
      cur = conn.cursor()
      try:
        cur.execute("SELECT draft_id FROM intake_consult_drafts WHERE draft_id LIKE %s LIMIT 2", (str(draft_id).strip() + "%",))
        rows = cur.fetchall()
      finally:
        cur.close()
      if len(rows) != 1:
        return (_jsonify({"error": "not_found", "detail": "no single draft matches"}), 404)
      full = rows[0][0]
      obs = _Store(conn).list_observations(full)
      return _jsonify({"draft_id": full, "count": len(obs), "observations": obs})
    finally:
      try:
        conn.close()
      except Exception:
        pass

  @app.route("/api/admin/issues", methods=["GET", "OPTIONS"])
  def get_admin_issues():
    """
    Read-only issue registry + occurrences + resolution events.
    """
    from api_handlers.issues_api import get_admin_issues_handler

    return get_admin_issues_handler(app=app, request=request)

  @app.route("/admin/issues", methods=["GET"])
  def get_admin_issues_page():
    """
    Self-contained HTML issue dashboard over /api/admin/issues.
    """
    from api_handlers.issues_api import get_admin_issues_page_handler

    return get_admin_issues_page_handler(app=app, request=request)

  @app.route("/api/shared-context", methods=["GET", "OPTIONS"])
  def get_shared_context():
    """
    Return the latest read-only shared context built from draft tables for a given draft_id.

    IMPORTANT: This endpoint is read-only and MUST NOT trigger GPT or mutate any drafts.
    """
    from api_handlers.shared_context import get_shared_context_handler

    return get_shared_context_handler(app=app, request=request)

  @app.route("/api/artifacts/help", methods=["GET", "OPTIONS"])
  def get_artifacts_help():
    """Discovery: every artifact route, its parameters and an example, in one
    call. Cowork spent four finding three."""
    from api_handlers.artifacts import get_artifacts_help_handler

    return get_artifacts_help_handler(app=app, request=request)

  @app.route("/api/artifacts", methods=["GET", "OPTIONS"])
  def get_artifacts():
    """
    The delivered artifacts on disk, newest first: workbooks and written plans.

    Read-only, loopback-only, scoped to the two delivered-artifact folders.
    This exists so reading a plan never depends on the device bridge again.
    """
    from api_handlers.artifacts import get_artifacts_handler

    return get_artifacts_handler(app=app, request=request)

  @app.route("/api/artifacts/workbook", methods=["GET", "OPTIONS"])
  def get_artifact_workbook():
    """
    Read a delivered workbook: sheet names, a sheet's dimensions, one cell, or
    a bounded range. `formulas=1` reads the stored formulas instead of the
    cached values (the A-136 distinction).
    """
    from api_handlers.artifacts import get_artifact_workbook_handler

    return get_artifact_workbook_handler(app=app, request=request)

  @app.route("/api/artifacts/plan", methods=["GET", "OPTIONS"])
  def get_artifact_plan():
    """
    Read a delivered written plan as text, or a sidecar render report verbatim.
    """
    from api_handlers.artifacts import get_artifact_plan_handler

    return get_artifact_plan_handler(app=app, request=request)

  return app


app = create_app()


if __name__ == "__main__":
  # Default to port 5000, which plays nicely with a Vite dev server
  # on 5173; override via the FLASK_RUN_PORT or PORT environment variable.
  port_str = os.getenv("FLASK_RUN_PORT") or os.getenv("PORT") or "5000"
  try:
    port = int(port_str)
  except ValueError:
    port = 5000

  app.run(host="0.0.0.0", port=port, debug=True)
