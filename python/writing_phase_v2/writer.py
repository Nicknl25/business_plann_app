"""THE WRITER (stage 2) - one call, standing brief + bundle -> whole plan.

Model-agnostic per the spec: the bundle, the brief and the output contract
are the interface. GPT goes through the app's own door
(post_openai_with_retries: GPT lock + vitals); Claude goes through the
Anthropic SDK, streamed, with the contract's schema travelling verbatim in
Anthropic's tool envelope. Nothing here edits the brief, the contract or
the bundle - the standing rules hold at the call site.

The brief and contract are the versioned copies in assets/ - the kit files
were their source (2026-09-08) and assets/ is canonical from now on.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ASSETS = Path(__file__).resolve().parent / "assets"

SYSTEM = (
    "You are a senior business consultant writing a complete, lender-grade business plan for one client. "
    "The STANDING BRIEF governs how you write; the BUNDLE is the only source of facts. Read everything before writing. "
    "Write the whole document in one pass and submit it through the submit_plan tool exactly as the contract specifies. "
    "Every figure in the prose must come from the bundle or from a derivation you declare. Do not quote the transcript; "
    "understand it. The document never refers to itself, its sources, or how it was produced; the projections are the plan's numbers."
)

GPT_MODEL = lambda: (os.getenv("PLAN_WRITER_MODEL") or "gpt-5.1").strip()
CLAUDE_MODEL = lambda: (os.getenv("PLAN_WRITER_MODEL_ANTHROPIC") or "claude-opus-5").strip()
MAX_OUTPUT_TOKENS = 40000


def load_brief() -> str:
    return (ASSETS / "brief_v2.md").read_text(encoding="utf-8")


def load_contract() -> Dict[str, Any]:
    return json.loads((ASSETS / "output_contract_v2.json").read_text(encoding="utf-8"))


def build_user(bundle: Dict[str, Any], *, brief: Optional[str] = None,
               contract: Optional[Dict[str, Any]] = None,
               extra: str = "") -> str:
    brief = brief if brief is not None else load_brief()
    contract = contract if contract is not None else load_contract()
    return (
        "== STANDING BRIEF ==\n" + brief +
        "\n\n== OUTPUT CONTRACT (the submit_plan tool) ==\n" +
        json.dumps(contract["notes_for_writer"], ensure_ascii=False, indent=1) +
        "\n\n== BUNDLE ==\n" +
        json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) +
        extra
    )


def _plan_stats(plan: Dict[str, Any]) -> str:
    words = sum(len(b.get("text", "").split())
                for s in plan.get("sections", [])
                for b in s.get("blocks", []) if b.get("type") == "paragraph")
    return ("sections=%d words=%s notes=%d derivations=%d"
            % (len(plan.get("sections", [])), format(words, ","),
               len(plan.get("notes", [])), len(plan.get("derivations", []))))


# ---------------------------------------------------------------------------
# GPT - through the app's door (locked, vitals)
# ---------------------------------------------------------------------------
def write_plan_gpt(bundle: Dict[str, Any], *, user: Optional[str] = None,
                   seed: Optional[int] = None) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], str]:
    """Returns (plan or None, raw response, stats line)."""
    from client_intake_and_finmo.openai_http import post_openai_with_retries
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY unset")
    contract = load_contract()
    body = {
        "model": GPT_MODEL(),
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user or build_user(bundle)}],
        "tools": [contract["tool"]],
        "tool_choice": {"type": "function", "function": {"name": "submit_plan"}},
        "max_completion_tokens": MAX_OUTPUT_TOKENS,
        # PLAN_WRITER_SEED re-rolls a locked draft; the lock keys on the
        # payload, so a new seed is a genuinely fresh call
        "seed": int(seed if seed is not None
                    else (os.getenv("PLAN_WRITER_SEED") or 11)),
    }
    t0 = time.time()
    resp = post_openai_with_retries(
        url="https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer %s" % api_key,
                 "Content-Type": "application/json"},
        payload=body, timeout_seconds=1800.0,
        retryable_status=(429, 500, 502, 503, 504), max_attempts=3)
    raw = resp.json()
    usage = raw.get("usage") or {}
    finish = (raw.get("choices") or [{}])[0].get("finish_reason")
    tc = ((raw.get("choices") or [{}])[0].get("message", {})
          .get("tool_calls") or [{}])[0].get("function", {})
    try:
        plan = json.loads(tc.get("arguments") or "")
    except Exception:
        plan = None
    stats = ("gpt %s | %.0fs | in=%s out=%s | finish=%s | %s"
             % (GPT_MODEL(), time.time() - t0,
                usage.get("prompt_tokens"), usage.get("completion_tokens"),
                finish, _plan_stats(plan) if plan else "NO PLAN PARSED"))
    return plan, raw, stats


# ---------------------------------------------------------------------------
# Claude - Anthropic SDK, streamed, schema verbatim in the Anthropic envelope
# ---------------------------------------------------------------------------
def write_plan_claude(bundle: Dict[str, Any], *, user: Optional[str] = None
                      ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], str]:
    import anthropic
    if not (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        raise RuntimeError("ANTHROPIC_API_KEY unset")
    contract = load_contract()
    fn = contract["tool"]["function"]
    tool = {"name": fn["name"], "description": fn.get("description", ""),
            "input_schema": fn["parameters"]}
    client = anthropic.Anthropic()
    info = client.models.retrieve(CLAUDE_MODEL())
    max_out = getattr(info, "max_tokens", None)
    if max_out is not None and max_out < MAX_OUTPUT_TOKENS:
        raise RuntimeError("model max output %s below plan budget %s - stop, "
                           "never split" % (max_out, MAX_OUTPUT_TOKENS))
    t0 = time.time()
    # a connection dropped MID-STREAM raises after the SDK's request-level
    # retries no longer apply; one bounded re-issue distinguishes transport
    # failure (no draft ever arrived) from a failing draft (never retried)
    last_exc: Optional[Exception] = None
    response = None
    for attempt in range(3):
        try:
            with client.messages.stream(
                model=CLAUDE_MODEL(), max_tokens=MAX_OUTPUT_TOKENS, system=SYSTEM,
                messages=[{"role": "user", "content": user or build_user(bundle)}],
                tools=[tool], tool_choice={"type": "tool", "name": "submit_plan"},
            ) as stream:
                response = stream.get_final_message()
            break
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
            last_exc = exc
        except Exception as exc:  # httpx2.RemoteProtocolError and kin
            if "RemoteProtocolError" not in type(exc).__name__ and \
                    "Incomplete" not in type(exc).__name__:
                raise
            last_exc = exc
        time.sleep(15 * (attempt + 1))
    if response is None:
        raise RuntimeError("claude stream failed %d times: %r" % (3, last_exc))
    raw = json.loads(response.to_json())
    plan = next((b.input for b in response.content
                 if b.type == "tool_use" and b.name == "submit_plan"), None)
    u = response.usage
    stats = ("claude %s | %.0fs | in=%s out=%s | stop=%s | %s"
             % (CLAUDE_MODEL(), time.time() - t0, u.input_tokens,
                u.output_tokens, response.stop_reason,
                _plan_stats(plan) if plan else "NO PLAN PARSED"))
    return plan, raw, stats


WRITERS = {"gpt": write_plan_gpt, "claude": write_plan_claude}
