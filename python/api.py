import os
import sys
import json
import logging
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
  # Silence Werkzeug's per-request logs in dev.
  logging.getLogger("werkzeug").setLevel(logging.ERROR)

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
    from api_handlers.business_types import get_business_types_handler

    return get_business_types_handler(app=app, request=request)

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

  @app.route("/api/financials-consult/session", methods=["POST", "OPTIONS"])
  def post_financials_consult_session():
    """
    Ensure a durable Financials draft exists for an existing intake draft_id.
    """
    from api_handlers.financials_consult import post_financials_consult_session_handler

    return post_financials_consult_session_handler(app=app, request=request)

  @app.route("/api/financials-consult/draft", methods=["GET", "OPTIONS"])
  def get_financials_consult_draft():
    from api_handlers.financials_consult import get_financials_consult_draft_handler

    return get_financials_consult_draft_handler(app=app, request=request)

  @app.route("/api/financials-consult", methods=["POST", "OPTIONS"])
  def post_financials_consult():
    """
    GPT-led financials intake consult (iterative).
    """
    from api_handlers.financials_consult import post_financials_consult_handler

    return post_financials_consult_handler(app=app, request=request)

  @app.route("/api/shared-context", methods=["GET", "OPTIONS"])
  def get_shared_context():
    """
    Return the latest read-only shared context built from draft tables for a given draft_id.

    IMPORTANT: This endpoint is read-only and MUST NOT trigger GPT or mutate any drafts.
    """
    from api_handlers.shared_context import get_shared_context_handler

    return get_shared_context_handler(app=app, request=request)

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
