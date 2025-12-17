import os
import sys
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
      # Load variables from the project-level .env if present.
      load_dotenv()
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
    Populate the FINMO workbook using the submitted business_type.
    """
    if request.method == "OPTIONS":
      return ("", 204)

    payload = request.get_json(silent=True) or {}
    business_type = payload.get("business_type")
    if not business_type or not str(business_type).strip():
      return (
        jsonify({"error": "invalid_request", "detail": "business_type is required"}),
        400,
      )

    try:
      from intake_values import populate_finmo  # type: ignore
    except Exception as exc:
      app.logger.exception("Failed to import populate_finmo: %s", exc)
      return (
        jsonify({"error": "server_error", "detail": "populate_finmo unavailable"}),
        500,
      )

    try:
      info = populate_finmo(str(business_type).strip())
      return jsonify({"status": "ok", "populated": info})
    except Exception as exc:
      app.logger.exception("Failed to populate FINMO: %s", exc)
      return (
        jsonify({"error": "server_error", "detail": str(exc)}),
        500,
      )

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
