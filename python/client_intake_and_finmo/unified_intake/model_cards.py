from __future__ import annotations

from flask import jsonify


def post_intake_model_cards_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  # Model cards are no longer part of the unified intake flow.
  return jsonify({"status": "ok", "detail": "model_cards_disabled"}), 200
