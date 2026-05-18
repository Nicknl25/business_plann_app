"""Phase 9 P3.21 Part 2 housekeeping cleanups.

Three minor doctrine-aligned cleanups from the Part 1 handler
audits:

1. Handler A stale docstring (intake_consult.py:107-110). No test
   needed -- docstring change only.

2. Handler B Site 2 FINMO rebuild silent-swallow
   (orchestrator.py:2167-2168). The rebuild exception now gets
   captured into completion_trace["pre_cash_gate_handler"][
   "post_handler_finmo_rebuild_error"] instead of being silently
   `pass`-swallowed. Mirrors Site 1's pattern at
   orchestrator.py:2002-2010. Tested via a unit-level inspection
   of the file source to confirm the pattern moved from
   `except Exception: pass` to a capture-and-record shape.

3. Handler C overly-broad RuntimeError catch
   (schedule.py:2595). PostIntakePreconditionFailed now re-raises
   immediately instead of being routed through GPT retry. Tested
   via source-shape regression confirming the explicit re-raise
   precedes the RuntimeError catch.

Source-shape tests are sufficient here because both fixes are
small structural rearrangements; end-to-end behavior verification
will land at the P3.22 single-E2E checkpoint per the directive.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYTHON_DIR = _REPO_ROOT / "python"
if str(_PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(_PYTHON_DIR))

_INTAKE_CONSULT = (
  _REPO_ROOT / "python" / "api_handlers" / "intake_consult.py"
)
_ORCHESTRATOR = (
  _REPO_ROOT / "python" / "client_intake_and_finmo"
  / "post_intake_solver" / "orchestrator.py"
)
_PAYROLL_SCHEDULE = (
  _REPO_ROOT / "python" / "client_intake_and_finmo"
  / "post_intake_headcount" / "schedule.py"
)


class HandlerAStaleDocstringFixedTests(unittest.TestCase):

  def setUp(self) -> None:
    self._src = _INTAKE_CONSULT.read_text(encoding="utf-8")

  def test_stale_legacy_gpt_fallback_claim_removed(self) -> None:
    """The pre-housekeeping docstring at line 107-110 claimed a
    'falls back to the legacy GPT call' behavior that the code
    never implemented. Confirm the misleading line is gone."""
    self.assertNotIn(
      "falls back to the legacy GPT call so existing\n  behavior is preserved",
      self._src,
      "Stale legacy-GPT-fallback docstring claim must be removed",
    )

  def test_docstring_accurately_describes_reraise(self) -> None:
    """The docstring must describe what the code actually does:
    re-raise a prefixed RuntimeError on handler exhaustion."""
    self.assertIn(
      "RE-RAISES a prefixed RuntimeError",
      self._src,
      "Docstring must describe the actual re-raise behavior",
    )
    self.assertIn(
      "stage_ramp_handler_exhausted",
      self._src,
      "Docstring must name the prefix the wrapper emits",
    )


class HandlerBSite2RebuildErrorCapturedTests(unittest.TestCase):

  def setUp(self) -> None:
    self._src = _ORCHESTRATOR.read_text(encoding="utf-8")

  def test_bare_except_pass_removed(self) -> None:
    """The Site 2 FINMO rebuild's `except Exception: pass` must
    be replaced with a capture-and-record pattern."""
    # Find the Site 2 rebuild block, anchored on _build_finmo_for_gate
    # which is unique to Site 2.
    site2_idx = self._src.find("rebuilt = _build_finmo_for_gate(")
    self.assertGreater(site2_idx, 0, "Site 2 rebuild not found")
    # Slice a window around the rebuild block.
    block = self._src[site2_idx:site2_idx + 1200]
    # The bare pattern must be gone from this window.
    self.assertNotIn(
      "        except Exception:\n          pass\n      completion_trace[",
      block,
      "Site 2's bare `except Exception: pass` swallow must be replaced",
    )

  def test_rebuild_error_captured_into_completion_trace(self) -> None:
    """Site 2 must now capture the rebuild exception into
    completion_trace under post_handler_finmo_rebuild_error,
    matching Site 1's pattern."""
    self.assertIn(
      'gate_rebuild_error: Optional[str] = None',
      self._src,
      "Site 2 must declare a gate_rebuild_error capture variable",
    )
    self.assertIn(
      'gate_rebuild_error = f"{type(gate_rebuild_exc).__name__}: {str(gate_rebuild_exc)[:500]}"',
      self._src,
      "Site 2 must stringify the rebuild exception into gate_rebuild_error",
    )
    self.assertIn(
      'completion_trace["pre_cash_gate_handler"]["post_handler_finmo_rebuild_error"]',
      self._src,
      "Site 2 must surface gate_rebuild_error under completion_trace[pre_cash_gate_handler][post_handler_finmo_rebuild_error]",
    )

  def test_site1_pattern_preserved(self) -> None:
    """Sanity: Site 1's analogous rebuild_error capture (which
    Site 2 is being aligned with) must still be in place."""
    self.assertIn(
      'rebuild_error: Optional[str] = None',
      self._src,
      "Site 1's rebuild_error capture must still be in place",
    )
    self.assertIn(
      '["post_handler_finmo_rebuild_error"] = rebuild_error',
      self._src,
      "Site 1's completion_trace surfacing must still be in place",
    )


class HandlerCPostIntakePreconditionFailedReraisedTests(unittest.TestCase):

  def setUp(self) -> None:
    self._src = _PAYROLL_SCHEDULE.read_text(encoding="utf-8")

  def test_post_intake_precondition_failed_imported_in_function_scope(self) -> None:
    """PostIntakePreconditionFailed must be imported within
    estimate_payroll_headcount_schedule_with_gpt so the new
    explicit re-raise in the iteration loop resolves the name."""
    # Locate the function.
    fn_idx = self._src.find(
      "def estimate_payroll_headcount_schedule_with_gpt("
    )
    self.assertGreater(fn_idx, 0)
    # Find the next top-level `def` to bound the function body.
    next_def_idx = self._src.find("\ndef ", fn_idx + 1)
    self.assertGreater(next_def_idx, fn_idx)
    fn_body = self._src[fn_idx:next_def_idx]
    self.assertIn(
      "from client_intake_and_finmo.fail_fast.common import",
      fn_body,
      "fail_fast.common must be imported inside estimate_payroll_headcount_schedule_with_gpt",
    )
    self.assertIn(
      "PostIntakePreconditionFailed",
      fn_body,
      "PostIntakePreconditionFailed must be imported into function scope",
    )

  def test_explicit_reraise_precedes_runtime_error_catch(self) -> None:
    """The validator/feasibility try-block at schedule.py:2576 must
    catch PostIntakePreconditionFailed explicitly (re-raise) BEFORE
    its `except RuntimeError`, so machinery violations propagate
    immediately instead of being routed through GPT retry."""
    # Anchor on the validator call site.
    validate_idx = self._src.find(
      "contract = validate_payroll_headcount_contract_payload(parsed)"
    )
    self.assertGreater(validate_idx, 0)
    # Slice a window covering the try-block + except handlers.
    block = self._src[validate_idx:validate_idx + 2500]
    pp_idx = block.find("except PostIntakePreconditionFailed:")
    rt_idx = block.find("except RuntimeError as exc:")
    self.assertGreater(pp_idx, 0, "explicit PostIntakePreconditionFailed except missing")
    self.assertGreater(rt_idx, 0, "RuntimeError catch missing")
    self.assertLess(
      pp_idx, rt_idx,
      "except PostIntakePreconditionFailed must precede except RuntimeError "
      "so machinery violations re-raise before the RuntimeError catch routes "
      "them through GPT retry"
    )

  def test_reraise_body_is_bare_raise(self) -> None:
    """The PostIntakePreconditionFailed handler body must be a
    bare `raise` (re-raise the original exception, preserving its
    structure and chain), NOT something like `raise e from None`
    or `raise CustomError(...) from e` which would alter the
    exception."""
    validate_idx = self._src.find(
      "contract = validate_payroll_headcount_contract_payload(parsed)"
    )
    self.assertGreater(validate_idx, 0)
    block = self._src[validate_idx:validate_idx + 2500]
    pp_idx = block.find("except PostIntakePreconditionFailed:")
    self.assertGreater(pp_idx, 0)
    # Next ~600 chars should contain a bare `raise` before the next except.
    handler_window = block[pp_idx:pp_idx + 700]
    rt_in_window = handler_window.find("except RuntimeError")
    self.assertGreater(rt_in_window, 0, "RuntimeError except should follow")
    handler_body = handler_window[:rt_in_window]
    # Find the bare `raise` line.
    self.assertIn(
      "\n        raise\n",
      handler_body,
      "PostIntakePreconditionFailed handler body must be a bare `raise`",
    )


if __name__ == "__main__":
  unittest.main()
