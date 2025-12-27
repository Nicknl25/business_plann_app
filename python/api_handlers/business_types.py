from __future__ import annotations

import os
from typing import List, Optional

from flask import jsonify


def getenv(name: str) -> Optional[str]:
  value = os.getenv(name)
  if value is None:
    return None
  value = value.strip()
  return value or None


def get_business_types_handler(*, app, request):
  """
  Relocated verbatim from python/api.py:get_business_types (Phase 1).
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
