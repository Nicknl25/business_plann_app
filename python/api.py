import os
import sys
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
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response

  @app.route("/api/business-types", methods=["GET", "OPTIONS"])
  def get_business_types():
    """
    Return the list of business types from MySQL.

    Response shape:
    [
      { "id": 1, "display_name": "Accounting Firm" },
      { "id": 2, "display_name": "Auto Repair" },
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
        "SELECT id, display_name FROM business_types ORDER BY display_name ASC"
      )
      rows: List[Tuple[Any, Any]] = cursor.fetchall()
      items: List[Dict[str, Any]] = [
        {"id": row[0], "display_name": row[1]} for row in rows
      ]
      return jsonify(items)
    except Exception as exc:
      app.logger.exception("Error querying business_types table: %s", exc)
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
