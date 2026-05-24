"""Phase 9 P3.33 Phase 3 step 4e — response-tool stubs.

The four structured responses GPT can give to a restructure proposal
(spec §6.4). These stubs validate the shape only; the session driver
that lands in step 5 wires them into the amalgamated session's tool
catalog and dispatches on the returned ProposalResponse.

Hermetic tests confirm:

  - confirm_proposal returns kind='confirm' with no validation errors.
  - veto_proposal needs a non-empty reason; reason is truncated to the
    600-char inbound cap.
  - choose_option accepts A/B/C (case-insensitive); other strings
    populate validation_errors with a structured code.
  - other_proposal validates required fields (section, field, value,
    reason), unknown-section rejection (stub 0 protection at the
    response-tool layer), numeric-value coercion.
  - ProposalResponse.validated flips false iff validation_errors non-
    empty.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class ConfirmProposalTest(unittest.TestCase):
  def test_returns_confirm_with_no_errors(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      confirm_proposal,
    )
    r = confirm_proposal()
    self.assertEqual(r.kind, "confirm")
    self.assertEqual(r.validation_errors, [])
    self.assertTrue(r.validated)


class VetoProposalTest(unittest.TestCase):
  def test_requires_reason(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      veto_proposal,
    )
    r = veto_proposal()
    self.assertEqual(r.kind, "veto")
    self.assertFalse(r.validated)
    self.assertEqual(r.validation_errors[0]["code"], "veto_reason_required")

  def test_empty_reason_rejected(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      veto_proposal,
    )
    r = veto_proposal(reason="   ")
    self.assertFalse(r.validated)

  def test_reason_truncated_to_inbound_cap(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      veto_proposal,
    )
    r = veto_proposal(reason="x" * 1200)
    self.assertTrue(r.validated)
    self.assertEqual(len(r.reason or ""), 600)

  def test_valid_reason_accepted(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      veto_proposal,
    )
    r = veto_proposal(reason="premium positioning; cohort target inapplicable")
    self.assertTrue(r.validated)
    self.assertIn("premium positioning", r.reason)


class ChooseOptionTest(unittest.TestCase):
  def test_accepts_uppercase_letters(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      choose_option,
    )
    for letter in ("A", "B", "C"):
      r = choose_option(option_id=letter)
      self.assertTrue(r.validated, msg=letter)
      self.assertEqual(r.option_id, letter)

  def test_accepts_lowercase_with_normalisation(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      choose_option,
    )
    r = choose_option(option_id="b")
    self.assertTrue(r.validated)
    self.assertEqual(r.option_id, "B")

  def test_rejects_unknown_option(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      choose_option,
    )
    r = choose_option(option_id="D")
    self.assertFalse(r.validated)
    self.assertEqual(r.validation_errors[0]["code"], "invalid_option_id")
    self.assertIsNone(r.option_id)

  def test_missing_option_rejected(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      choose_option,
    )
    r = choose_option()
    self.assertFalse(r.validated)


class OtherProposalTest(unittest.TestCase):
  def test_happy_path_accepts(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      other_proposal,
    )
    r = other_proposal(
      section="drivers",
      field="expenses::Cost of Goods Sold",
      value=0.62,
      reason="airline supply costs require a tighter than cohort target",
    )
    self.assertTrue(r.validated)
    self.assertEqual(r.section, "drivers")
    self.assertEqual(r.field, "expenses::Cost of Goods Sold")
    self.assertEqual(r.value, 0.62)

  def test_missing_section_rejected(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      other_proposal,
    )
    r = other_proposal(field="f", value=1.0, reason="x")
    self.assertFalse(r.validated)
    codes = [e["code"] for e in r.validation_errors]
    self.assertIn("other_section_required", codes)

  def test_unknown_section_rejected(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      other_proposal,
    )
    r = other_proposal(section="stub_0_naics", field="any", value=1, reason="x")
    self.assertFalse(r.validated)
    codes = [e["code"] for e in r.validation_errors]
    self.assertIn("other_section_unknown", codes)

  def test_missing_value_rejected(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      other_proposal,
    )
    r = other_proposal(section="drivers", field="f", reason="x")
    self.assertFalse(r.validated)
    codes = [e["code"] for e in r.validation_errors]
    self.assertIn("other_value_required", codes)

  def test_non_numeric_value_rejected(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      other_proposal,
    )
    r = other_proposal(section="drivers", field="f", value="banana", reason="x")
    self.assertFalse(r.validated)
    codes = [e["code"] for e in r.validation_errors]
    self.assertIn("other_value_not_numeric", codes)
    self.assertIsNone(r.value)

  def test_missing_reason_rejected(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      other_proposal,
    )
    r = other_proposal(section="drivers", field="f", value=0.5)
    self.assertFalse(r.validated)
    codes = [e["code"] for e in r.validation_errors]
    self.assertIn("other_reason_required", codes)

  def test_integer_value_coerced_to_float(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E501
      other_proposal,
    )
    r = other_proposal(
      section="payroll", field="classes.sales.fte_q12", value=4,
      reason="cut headcount to fit payroll percent of revenue band",
    )
    self.assertTrue(r.validated)
    self.assertEqual(r.value, 4.0)
    self.assertIsInstance(r.value, float)


class PackageReexportTest(unittest.TestCase):
  def test_response_tools_re_exported_from_protocol(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol import (
      confirm_proposal, veto_proposal, choose_option, other_proposal,
      ProposalResponse,
    )
    for fn in (confirm_proposal, veto_proposal, choose_option, other_proposal):
      self.assertTrue(callable(fn))
    self.assertTrue(hasattr(ProposalResponse, "validated"))


if __name__ == "__main__":
  unittest.main()
