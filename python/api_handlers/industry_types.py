import os
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify


def getenv(name: str) -> Optional[str]:
  value = os.getenv(name)
  if value is None:
    return None
  value = value.strip()
  return value or None


def get_industry_types_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:get_industry_types (Phase 1 sweep).
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

