# -*- coding: utf-8 -*-
"""RESEARCH: turn-level call labels for late turns of 50658fff."""
import json, sys, io
import mysql.connector

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
conn = mysql.connector.connect(host="localhost", user="root", password="Lovers251979!",
                               database="biz_plan_revert", charset="utf8mb4")
cur = conn.cursor(dictionary=True)
did = "50658fff105e480c896f714fa519f22e"
cur.execute("SELECT turn_index, section, section_after, message_chars, reply_chars, call_labels_json "
            "FROM run_vitals_turns WHERE draft_id=%s ORDER BY turn_index", (did,))
for r in cur.fetchall():
    labels = json.loads(r["call_labels_json"] or "[]")
    print(r["turn_index"], r["section"], "->", r["section_after"],
          "msg", r["message_chars"], "reply", r["reply_chars"], "|", labels)
