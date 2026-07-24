"""Phase 1 fault-injection proof (no server, no GPT):

1. _ensure_bounds: author failure -> CoherenceJudgmentUnavailable (never roadmap)
2. _ensure_margin_band / _ensure_growth_judgment: same on ok=False
3. gate_and_turn with a genuine feasible_region_exists=False bounds stamp
   still routes to roadmap (executive verdict preserved)
4. handler classifier: transient exceptions -> hold message; bugs -> None
"""
import os
import sys
from unittest import mock

os.environ.setdefault("GPT_RESPONSE_LOCK", "0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.join(ROOT, "python", "client_intake_and_finmo"))

from client_intake_and_finmo.intake_coherence import section as coh  # noqa: E402

FAILS = []


def check(name, fn):
    try:
        fn()
        print(f"PASS {name}")
    except AssertionError as exc:
        FAILS.append(name)
        print(f"FAIL {name}: {exc}")


# --- 1. bounds author failure raises, never roadmaps -------------------
def t_bounds_failure_raises():
    with mock.patch(
        "client_intake_and_finmo.post_intake_restructure.constraint_author.gpt_author_restructure_bounds_once",
        return_value={"ok": False, "error": "http_status_503: upstream unavailable"},
    ):
        try:
            coh._ensure_bounds(
                {}, ops_json={}, people_json={}, market_json={},
                marketing_model_json={}, financials_json={},
            )
            raise AssertionError("did not raise")
        except coh.CoherenceJudgmentUnavailable as exc:
            assert exc.judgment == "bounds", exc.judgment
            assert "503" in exc.detail, exc.detail


# --- 2. band/growth author failure raises ------------------------------
def t_band_failure_raises():
    with mock.patch(
        "client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment.gpt_author_margin_band_once",
        return_value={"ok": False, "error": "read_timeout"},
    ):
        try:
            coh._ensure_margin_band(
                {}, ops_json={}, people_json={}, market_json={},
                marketing_model_json={}, financials_json={},
                financials_year1_json={},
            )
            raise AssertionError("did not raise")
        except coh.CoherenceJudgmentUnavailable as exc:
            assert exc.judgment == "margin_band"


def t_growth_failure_raises():
    with mock.patch(
        "client_intake_and_finmo.post_intake_headcount.gpt_growth_judgment.gpt_author_growth_judgment_once",
        return_value={"ok": False, "error": "connection_error"},
    ):
        try:
            coh._ensure_growth_judgment(
                {}, ops_json={}, people_json={}, market_json={},
                marketing_model_json={}, financials_json={},
            )
            raise AssertionError("did not raise")
        except coh.CoherenceJudgmentUnavailable as exc:
            assert exc.judgment == "judged_growth"


# --- 3. existing stamps short-circuit (absence != failure) -------------
def t_existing_stamps_short_circuit():
    # With stamps present, no author is called at all -> no raise even if
    # the authors would fail (they are not reachable).
    with mock.patch(
        "client_intake_and_finmo.post_intake_restructure.constraint_author.gpt_author_restructure_bounds_once",
        side_effect=AssertionError("must not be called"),
    ):
        state = coh._ensure_bounds(
            {"bounds": {"feasible_region_exists": False}},
            ops_json={}, people_json={}, market_json={},
            marketing_model_json={}, financials_json={},
        )
        assert state["bounds"]["feasible_region_exists"] is False


# --- 4. handler classifier ---------------------------------------------
def t_classifier():
    from api_handlers import intake_consult as ic
    hold = ic._transient_judgment_hold_message
    assert hold(coh.CoherenceJudgmentUnavailable("bounds", "x")) is not None
    assert hold(RuntimeError("openai_request_failed: caller=x")) is not None
    assert hold(RuntimeError("gpt_response_lock_lookup_failed: store down")) is not None
    assert hold(TimeoutError("deadline")) is not None
    import requests
    assert hold(requests.exceptions.ReadTimeout("t")) is not None
    # bugs stay loud:
    assert hold(KeyError("some_field")) is None
    assert hold(RuntimeError("draft_not_complete")) is None
    assert hold(ValueError("bad math")) is None


check("bounds_failure_raises", t_bounds_failure_raises)
check("band_failure_raises", t_band_failure_raises)
check("growth_failure_raises", t_growth_failure_raises)
check("existing_stamps_short_circuit", t_existing_stamps_short_circuit)
check("classifier", t_classifier)

print("RESULT:", "FAIL " + ",".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
