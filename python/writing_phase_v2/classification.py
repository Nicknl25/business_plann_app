"""THE CLASSIFICATION CHECK (spec 1.9) - which trade groups the warehouse is
fetched for, and whether the record's NAICS survives.

Two layers, per the spec: a pinned table first (seeded with the Thornfield
reference resolution, hand-made 2026-09-07 when the record's 517121 telecom
code failed), then a model call through the app's own GPT door (locked, so
deterministic) for a business the table has not seen. The record's failed
code never travels in the bundle; the mismatch goes to the QA report, never
to the writer.

A trade group is {role, description, naics: [codes for warehouse slicing]}.
meta carries role->description; the warehouse builder takes the codes.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# the pinned table - the reference resolutions. Key: draft_id prefix, because
# the resolution belongs to the business as intaken, not to a type string.
# ---------------------------------------------------------------------------
PINNED: Dict[str, Dict[str, Any]] = {
    "eae0ac3f": {
        "record_code_fits": False,
        "groups": [
            {"role": "online_retail_trade_group",
             "description": "454110 / 4541 (Census 2017 basis: electronic shopping and mail-order houses)",
             "naics": ["454110", "4541"]},
            {"role": "product_trade",
             "description": "459910 / 4599 (NAICS 2022: pet and pet supplies retailers; 453910 in 2017 basis)",
             "naics": ["459910", "4599", "453910"]},
            {"role": "wholesale_line",
             "description": "424990 (other miscellaneous nondurable goods merchant wholesalers)",
             "naics": ["424990"]},
        ],
    },
}

_SYSTEM = (
    "You classify one small business for statistical-data lookup. Judge whether "
    "the NAICS code on its record matches what the business actually does, and "
    "name the trade groups (NAICS codes) government data should be pulled for. "
    "Roles are short snake_case labels for how each group is used (e.g. "
    "online_retail_trade_group, product_trade, wholesale_line, primary_trade). "
    "Descriptions name the code(s) and the trade in plain words, in the form "
    "'<code> / <code4> (<basis>: <trade in words>)'. Give 1-3 groups: the "
    "primary trade always; an online-retail group when the business sells "
    "mainly through its own site; a wholesale group only when wholesale is a "
    "real line of the business."
)

_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_classification",
        "description": "The classification verdict and trade groups.",
        "parameters": {
            "type": "object",
            "properties": {
                "record_code_fits": {"type": "boolean"},
                "why": {"type": "string"},
                "groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "description": {"type": "string"},
                            "naics": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["role", "description", "naics"],
                    },
                },
            },
            "required": ["record_code_fits", "why", "groups"],
        },
    },
}


def _gpt_classify(draft: Dict[str, Any], om: Dict[str, Any]) -> Dict[str, Any]:
    from client_intake_and_finmo.openai_http import post_openai_with_retries
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY unset - classification call impossible")
    user = json.dumps({
        "business_name": draft.get("business_name"),
        "business_type": om.get("business_type"),
        "description": om.get("business_description_summary"),
        "lines_of_business": [l.get("lob_name") for l in (om.get("lob_models") or [])],
        "state": draft.get("address_state"),
        "naics_code_on_record": om.get("business_naics_6"),
    }, ensure_ascii=False)
    body = {
        "model": (os.getenv("PLAN_WRITER_MODEL") or "gpt-5.1").strip(),
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": user}],
        "tools": [_TOOL],
        "tool_choice": {"type": "function", "function": {"name": "submit_classification"}},
        "seed": 7,
    }
    resp = post_openai_with_retries(
        url="https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer %s" % api_key,
                 "Content-Type": "application/json"},
        payload=body, timeout_seconds=120.0,
        retryable_status=(429, 500, 502, 503, 504), max_attempts=3)
    got = resp.json()
    args = got["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    return json.loads(args)


def classify(draft: Dict[str, Any]) -> Dict[str, Any]:
    """Returns {record_code_fits, groups: [{role, description, naics}], why?}."""
    for prefix, pinned in PINNED.items():
        if str(draft.get("draft_id", "")).startswith(prefix):
            return dict(pinned)
    om = draft.get("operating_model_json")
    om = json.loads(om) if isinstance(om, (str, bytes)) else (om or {})
    return _gpt_classify(draft, om)


def trade_codes_for_meta(cls: Dict[str, Any]) -> Dict[str, str]:
    return {g["role"]: g["description"] for g in cls.get("groups", [])}
