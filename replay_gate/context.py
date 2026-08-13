# -*- coding: utf-8 -*-
"""The per-leg execution context handed to every leg's run()."""
import json
import re

from .surface import Surface


class GateContext(Surface):
    def __init__(self, conn, read_conn):
        Surface.__init__(self, conn, read_conn)
        self.last_turn = None

    def reset(self):
        self.last_turn = None

    def note_turn(self, turn):
        """A leg that drives a real turn registers it here so the
        forward-move judgment (dead end / verbatim repeat / empty) runs
        over it. Legs that exercise a pure function never call this and
        are judged on their assertion alone."""
        self.last_turn = turn

    # ---- real captured answers from previous runs -----------------------
    def captured(self, pattern, fallback, draft_hint=None):
        """The client's ACTUAL words from the run that broke, pulled out
        of that draft in the DB. Falls back to the recorded literal and
        records that it did, so a pruned draft degrades the evidence
        visibly instead of the check quietly becoming synthetic."""
        rx = re.compile(pattern, re.I)
        tries = []
        if draft_hint:
            tries.append((
                "SELECT draft_id, messages_json FROM intake_consult_drafts "
                "WHERE draft_id LIKE %s ORDER BY updated_at DESC LIMIT 3",
                (draft_hint + "%",)))
        tries.append((
            "SELECT draft_id, messages_json FROM intake_consult_drafts "
            "WHERE messages_json IS NOT NULL ORDER BY updated_at DESC LIMIT 80",
            ()))
        for sql, args in tries:
            try:
                cur = self.read_conn.cursor()
                try:
                    cur.execute(sql, args)
                    rows = cur.fetchall()
                finally:
                    cur.close()
            except Exception:
                self.provenance = "recorded literal (DB read failed)"
                return fallback
            for row in rows or []:
                blob = row[1]
                try:
                    msgs = json.loads(blob) if isinstance(blob, (str, bytes)) else (blob or [])
                except Exception:
                    continue
                for m in msgs or []:
                    if not isinstance(m, dict):
                        continue
                    if str(m.get("role") or "").lower() != "user":
                        continue
                    text = str(m.get("content") or m.get("text") or "")
                    if rx.search(text):
                        self.provenance = f"captured client answer, draft {str(row[0])[:8]}"
                        return text
        self.provenance = "recorded literal (no captured answer in DB)"
        return fallback

    provenance = ""
