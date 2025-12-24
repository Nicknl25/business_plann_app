import os
import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request

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


def create_app() -> Flask:
  if load_dotenv:
    try:
      # Force load variables from the project root .env (consistent across CWDs).
      root_dir = Path(__file__).resolve().parent.parent
      env_path = root_dir / ".env"
      load_dotenv(str(env_path))
    except Exception:
      # Failing to load .env should not prevent the app from starting;
      # environment variables may already be configured.
      pass

  app = Flask(__name__)

  # Allow importing local helper modules
  root_path = Path(__file__).resolve().parent
  sys.path.append(str(root_path / "client_intake_and_finmo"))

  if CORS is not None:
    # Enable CORS for all routes to support the separate frontend dev server.
    CORS(app)

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
    if request.method == "OPTIONS":
      return ("", 204)

    host = getenv("MYSQL_HOST")
    user = getenv("MYSQL_USER")
    password = getenv("MYSQL_PASSWORD")
    database = getenv("MYSQL_DB")

    missing = [
      key
      for key, val in (
        ("MYSQL_HOST", host),
        ("MYSQL_USER", user),
        ("MYSQL_PASSWORD", password),
        ("MYSQL_DB", database),
      )
      if not val
    ]
    if missing:
      return (
        jsonify(
          {
            "error": "missing_mysql_configuration",
            "missing": missing,
          }
        ),
        500,
      )

    try:
      import mysql.connector  # type: ignore
    except Exception:
      return (
        jsonify(
          {
            "error": "mysql_driver_not_installed",
            "detail": "Install mysql-connector-python in your environment.",
          }
        ),
        500,
      )

    try:
      conn = mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database,
      )
    except Exception:
      return (jsonify({"error": "database_connection_error"}), 500)

    try:
      cur = conn.cursor()
      cur.execute("SELECT business_types FROM naics_master WHERE business_types IS NOT NULL")
      rows = cur.fetchall()
      # Flatten comma-separated values
      values: List[str] = []
      for (bt,) in rows:
        if bt is None:
          continue
        parts = [p.strip() for p in str(bt).split(",")]
        for p in parts:
          if p:
            values.append(p)
      # Deduplicate and sort
      uniq = sorted(set(values), key=lambda x: x.lower())
      items = [{"id": idx + 1, "display_name": val} for idx, val in enumerate(uniq)]
      return jsonify(items)
    except Exception as exc:
      app.logger.exception("Error querying naics_master: %s", exc)
      return (
        jsonify(
          {
            "error": "database_query_error",
          }
        ),
        500,
      )
    finally:
      try:
        cur.close()
      except Exception:
        pass
      try:
        conn.close()
      except Exception:
        pass

  @app.route("/api/financials", methods=["POST", "OPTIONS"])
  def post_financials():
    """
    Receive intake submission and trigger downstream processing.
    """
    if request.method == "OPTIONS":
      return ("", 204)

    payload = request.get_json(silent=True) or {}
    app.logger.info("Intake payload received: %s", payload)
    print("Intake payload received:", payload)
    try:
      from intake_pipeline import (  # type: ignore
        IntakeValidationError,
        process_intake_submission,
      )
      from intake_submission import get_mysql_connection  # type: ignore
      from intake_consult_draft import get_draft, mark_submitted  # type: ignore
    except Exception as exc:
      app.logger.exception("Failed to import intake pipeline: %s", exc)
      return (jsonify({"error": "server_error", "detail": "pipeline unavailable"}), 500)

    try:
      draft_id = payload.get("draft_id")
      if not draft_id or not str(draft_id).strip():
        raise IntakeValidationError({"draft_id": "draft_id is required"})

      conn = get_mysql_connection()
      try:
        draft = get_draft(conn, draft_id=str(draft_id).strip())
      finally:
        try:
          conn.close()
        except Exception:
          pass

      draft_status = str(draft.get("status") or "").strip().lower()
      if draft_status == "submitted":
        return (
          jsonify(
            {
              "error": "duplicate_submit",
              "detail": "This draft was already submitted.",
              "intake_submission_id": draft.get("intake_submission_id"),
            }
          ),
          409,
        )
      if draft_status != "completed":
        raise IntakeValidationError(
          {"draft_id": "Consult draft must be completed before submitting intake."}
        )

      operating_model_raw = draft.get("operating_model_json")
      if not operating_model_raw:
        raise IntakeValidationError(
          {"draft_id": "Consult draft is missing operating_model_json."}
        )
      try:
        operating_model = json.loads(str(operating_model_raw))
      except Exception as exc:
        raise IntakeValidationError(
          {"draft_id": "operating_model_json is invalid JSON."}
        ) from exc
      if not isinstance(operating_model, dict):
        raise IntakeValidationError(
          {"draft_id": "operating_model_json must be a JSON object."}
        )

      # Ensure the submission is keyed to the consult draft's client_id and model.
      payload = dict(payload)
      payload["client_id"] = str(draft.get("client_id") or "").strip()
      payload.update(operating_model)
      if "confidence" in payload:
        payload["operating_model_confidence"] = payload.pop("confidence")

      result = process_intake_submission(payload)

      intake_submission_id = result.get("intake_submission_id")
      if intake_submission_id is not None:
        conn = get_mysql_connection()
        try:
          mark_submitted(
            conn,
            draft_id=str(draft_id).strip(),
            intake_submission_id=int(intake_submission_id),
          )
        finally:
          try:
            conn.close()
          except Exception:
            pass
      return jsonify(result)
    except IntakeValidationError as exc:
      return (jsonify({"error": "invalid_request", "errors": exc.errors}), 400)
    except Exception as exc:
      app.logger.exception("Failed processing intake submission: %s", exc)
      return (jsonify({"error": "server_error", "detail": str(exc)}), 500)

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
    if request.method == "OPTIONS":
      # Preflight request for CORS.
      return ("", 204)

    host = getenv("MYSQL_HOST")
    user = getenv("MYSQL_USER")
    password = getenv("MYSQL_PASSWORD")
    database = getenv("MYSQL_DB")

    missing = [
      key
      for key, val in (
        ("MYSQL_HOST", host),
        ("MYSQL_USER", user),
        ("MYSQL_PASSWORD", password),
        ("MYSQL_DB", database),
      )
      if not val
    ]
    if missing:
      app.logger.error(
        "Missing required MySQL environment variables: %s",
        ", ".join(missing),
      )
      return (
        jsonify(
          {
            "error": "missing_mysql_configuration",
            "missing": missing,
          }
        ),
        500,
      )

    try:
      import mysql.connector  # type: ignore
    except Exception as exc:  # pragma: no cover
      app.logger.exception("mysql-connector-python is not installed: %s", exc)
      return (
        jsonify(
          {
            "error": "mysql_driver_not_installed",
            "detail": "Install mysql-connector-python in your environment.",
          }
        ),
        500,
      )

    try:
      conn = mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database,
      )
    except Exception as exc:
      app.logger.exception("Failed to connect to MySQL: %s", exc)
      return (
        jsonify(
          {
            "error": "database_connection_error",
          }
        ),
        500,
      )

    try:
      cursor = conn.cursor()
      cursor.execute(
        "SELECT id, naics_code, display_name FROM industry_types ORDER BY display_name ASC"
      )
      rows: List[Tuple[Any, Any, Any]] = cursor.fetchall()
      items: List[Dict[str, Any]] = [
        {"id": row[0], "naics_code": row[1], "display_name": row[2]}
        for row in rows
      ]
      return jsonify(items)
    except Exception as exc:
      app.logger.exception("Error querying industry_types table: %s", exc)
      return (
        jsonify(
          {
            "error": "database_query_error",
          }
        ),
        500,
      )
    finally:
      try:
        cursor.close()
      except Exception:
        pass
      try:
        conn.close()
      except Exception:
        pass

  @app.route("/api/intake-consult", methods=["POST", "OPTIONS"])
  def post_intake_consult():
    """
    GPT-led operational intake consultant conversation (iterative).

    Request shape:
      { "client_id": "...", "message": "..." }
    """
    if request.method == "OPTIONS":
      return ("", 204)

    payload = request.get_json(silent=True) or {}
    draft_id = payload.get("draft_id")
    client_id = payload.get("client_id")
    raw_message = payload.get("message")
    message = raw_message
    if not draft_id or not str(draft_id).strip():
      return (
        jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
        400,
      )
    reset = bool(payload.get("reset", False))
    starting = message is None or not str(message).strip()
    if starting:
      message = "Start the operational intake. Ask your first question."

    try:
      from intake_consultant import (  # type: ignore
        consultant_chat_turn,
        consultant_finalize,
      )
      from intake_submission import get_mysql_connection  # type: ignore
      from intake_consult_draft import (  # type: ignore
        append_messages,
        get_draft,
      )
    except Exception as exc:
      app.logger.exception("Failed to import intake consultant helpers: %s", exc)
      return (jsonify({"error": "server_error"}), 500)

    try:
      conn = get_mysql_connection()
      try:
        draft = get_draft(conn, draft_id=str(draft_id).strip())
      finally:
        try:
          conn.close()
        except Exception:
          pass

      client_id_str = str(draft.get("client_id") or (client_id or "")).strip()
      draft_status = str(draft.get("status") or "").strip().lower()
      if draft_status in ("completed", "submitted"):
        operating_model_raw = draft.get("operating_model_json")
        if operating_model_raw:
          return jsonify(
            {
              "status": "ok",
              "draft_id": str(draft_id).strip(),
              "client_id": client_id_str,
              "done": True,
              "assistant_message": str(operating_model_raw),
            }
          )

      context = {
        "client_id": client_id_str,
        "business_name": payload.get("business_name"),
        "business_type": payload.get("business_type"),
      }

      app.logger.info(
        "Intake consult message for draft_id=%s client_id=%s: %s",
        draft_id,
        client_id_str,
        message,
      )
      print(f"Intake consult message draft_id={draft_id} client_id={client_id_str}:", str(message))

      history: List[Dict[str, str]] = []
      try:
        raw_messages = draft.get("messages_json")
        if raw_messages:
          parsed = json.loads(str(raw_messages))
          if isinstance(parsed, list):
            history = [m for m in parsed if isinstance(m, dict)]
      except Exception:
        history = []

      if reset:
        history = []

      user_msg = {"role": "user", "content": str(message).strip()}
      turn = consultant_chat_turn(
        intake_context=context,
        conversation_messages=[*history, user_msg],
      )
      assistant_text = str(turn.get("assistant_message") or "").strip()
      finalize_ready = bool(turn.get("finalize_ready", False))
      assistant_msg = {"role": "assistant", "content": assistant_text}
      new_messages = [user_msg, assistant_msg]

      done = False
      assistant_message = assistant_text

      if finalize_ready:
        final_obj = consultant_finalize(
          intake_context=context,
          conversation_messages=[*history, *new_messages],
        )
        if not isinstance(final_obj, dict):
          raise RuntimeError("Finalization did not return an object.")

        app.logger.info(
          "Intake consult final for draft_id=%s client_id=%s: %s",
          draft_id,
          client_id_str,
          final_obj,
        )
        print(f"Intake consult final draft_id={draft_id} client_id={client_id_str}:", final_obj)

        conn = get_mysql_connection()
        try:
          append_messages(
            conn,
            draft_id=str(draft_id).strip(),
            new_messages=new_messages,
            status="completed",
            operating_model_json=final_obj,
            completed=True,
          )
        finally:
          try:
            conn.close()
          except Exception:
            pass

        done = True
        assistant_message = json.dumps(final_obj, ensure_ascii=False)
      else:
        conn = get_mysql_connection()
        try:
          # Persist conversation after each turn (durable draft).
          append_messages(
            conn,
            draft_id=str(draft_id).strip(),
            new_messages=new_messages,
            status="in_progress",
          )
        finally:
          try:
            conn.close()
          except Exception:
            pass

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id_str,
          "done": done,
          "assistant_message": assistant_message,
        }
      )
    except Exception as exc:
      app.logger.exception("Failed intake consult: %s", exc)
      return (jsonify({"error": "server_error", "detail": str(exc)}), 500)

  @app.route("/api/intake-consult/session", methods=["POST", "OPTIONS"])
  def post_intake_consult_session():
    """
    Create a new durable pre-submit consultant draft and return {draft_id, client_id}.
    """
    if request.method == "OPTIONS":
      return ("", 204)

    try:
      from intake_submission import generate_client_id, get_mysql_connection  # type: ignore
      from intake_consult_draft import create_draft  # type: ignore
    except Exception as exc:
      app.logger.exception("Failed to import generate_client_id: %s", exc)
      return (jsonify({"error": "server_error"}), 500)

    client_id = generate_client_id()
    conn = get_mysql_connection()
    try:
      draft = create_draft(conn, client_id=client_id)
      return jsonify({"status": "ok", **draft})
    finally:
      try:
        conn.close()
      except Exception:
        pass

  @app.route("/api/intake-consult/draft", methods=["GET", "OPTIONS"])
  def get_intake_consult_draft():
    if request.method == "OPTIONS":
      return ("", 204)

    draft_id = request.args.get("draft_id")
    if not draft_id:
      return (
        jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
        400,
      )

    try:
      from intake_submission import get_mysql_connection  # type: ignore
      from intake_consult_draft import get_draft  # type: ignore
    except Exception as exc:
      app.logger.exception("Failed to import consult draft helpers: %s", exc)
      return (jsonify({"error": "server_error"}), 500)

    conn = get_mysql_connection()
    try:
      draft = get_draft(conn, draft_id=str(draft_id).strip())
      return jsonify(
        {
          "status": "ok",
          "draft_id": draft.get("draft_id"),
          "client_id": draft.get("client_id"),
          "draft_status": draft.get("status"),
          "messages_json": draft.get("messages_json"),
          "operating_model_json": draft.get("operating_model_json"),
        }
      )
    finally:
      try:
        conn.close()
      except Exception:
        pass

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
