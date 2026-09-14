"""An issue row carrying a field the table would drop is refused, not emptied.

Nick ruled 2026-09-14: 400 on unknown fields, same as the artifact routes.
POST /api/issues used to accept any key with a 200 and silently store only the
ones it knew - so a row sent with evidence_json instead of evidence, or with a
body field, stored empty and read exactly like a correct row. It emptied two
of Cowork's rows of findings in one morning.

These pins state, for any payload shape:
  - any key outside the accepted set gets a 400 that names it, and nothing is
    written - the database is never even opened;
  - a body that is not a JSON object gets a 400;
  - a payload using only accepted keys reaches the registry unchanged;
  - the accepted set is exactly the set of keys the handler passes on.
"""
from __future__ import annotations

import itertools
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "client_intake_and_finmo"))


class UnknownFieldsBounce(unittest.TestCase):
  def setUp(self):
    from flask import Flask  # type: ignore
    import intake_submission  # type: ignore
    from api_handlers import issues_api as API  # type: ignore
    from client_intake_and_finmo import issue_registry  # type: ignore

    self.API, self.subm, self.reg = API, intake_submission, issue_registry
    self.app = Flask("pin")
    self.calls = []
    self._saved = (intake_submission.get_mysql_connection, issue_registry.report_issue)

    class _Conn:
      def close(self):
        pass

    def connect():
      self.calls.append("connect")
      return _Conn()

    def report_issue(conn, **kw):
      self.calls.append(("report", kw))
      return {"issue_id": 1, "signature": kw.get("signature")}

    intake_submission.get_mysql_connection = connect
    issue_registry.report_issue = report_issue

  def tearDown(self):
    self.subm.get_mysql_connection, self.reg.report_issue = self._saved

  def post(self, body):
    with self.app.test_request_context("/api/issues", method="POST", json=body):
      from flask import request  # type: ignore
      return self.API.post_issue_handler(app=self.app, request=request)

  def test_any_unknown_key_is_refused_before_anything_is_written(self):
    base = {"signature": "x", "category": "progress", "severity": "note", "observed": "o", "expected": "e"}
    for extra in ("evidence_json", "body", "details", "notes", "Evidence", "run_id", "verdict"):
      for combo in itertools.combinations(["evidence_json", "body", extra], 1):
        self.calls.clear()
        body = dict(base, **{k: "lost findings" for k in combo})
        resp = self.post(body)
        payload, status = resp[0].get_json(), resp[1]
        self.assertEqual(status, 400, combo)
        self.assertEqual(payload["error"], "unknown_fields")
        self.assertEqual(payload["unknown"], sorted(combo))
        self.assertEqual(self.calls, [], "the database was opened for a refused row")

  def test_a_body_that_is_not_an_object_is_refused(self):
    for body in ([], "text", 3):
      self.calls.clear()
      resp = self.post(body)
      self.assertEqual(resp[1], 400)
      self.assertEqual(self.calls, [])

  def test_accepted_keys_reach_the_registry_unchanged(self):
    body = {k: ("v-" + k) for k in self.API.ACCEPTED_KEYS if k not in ("turn_index", "probe", "evidence")}
    body.update({"turn_index": 11, "probe": {"a": 1}, "evidence": {"b": 2}})
    resp = self.post(body)
    got = [c for c in self.calls if isinstance(c, tuple)]
    self.assertEqual(len(got), 1)
    kw = got[0][1]
    for k, v in body.items():
      self.assertEqual(kw[k], v, k)
    self.assertEqual(resp.get_json()["status"], "ok")

  def test_the_accepted_set_is_exactly_what_the_handler_passes_on(self):
    src = (ROOT / "python" / "api_handlers" / "issues_api.py").read_text(encoding="utf-8-sig")
    handler = src[src.index("def post_issue_handler"):src.index("def get_admin_issues_handler")]
    read = set(re.findall(r'payload\.get\("([a-z_]+)"\)', handler))
    self.assertEqual(read, set(self.API.ACCEPTED_KEYS))


if __name__ == "__main__":
  unittest.main(verbosity=2)
