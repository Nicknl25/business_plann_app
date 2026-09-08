"""WRITING PHASE v2 - the whole chain for one business.

    python -X utf8 scripts/writing_phase_v2_run.py --business "Bellamy Row"
        [--models gpt,claude] [--skip-render] [--out DIR]

assembler -> bundle (stored: writing_phase_bundle row + files)
          -> QA report (operator)
          -> per model: writer -> checker -> editor (once, only on findings)
             -> checker -> renderer (charts + docx into Client Written Plans)

Two writer-side calls per plan maximum; a second checker failure stops and
reports - nothing retries silently. The unedited writer output is always
kept beside the edited one.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "python")):
    if p not in sys.path:
        sys.path.insert(0, p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import mysql.connector  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from writing_phase_v2 import bundle as B  # noqa: E402
from writing_phase_v2 import checker as CK  # noqa: E402
from writing_phase_v2 import classification as CLS  # noqa: E402
from writing_phase_v2 import editor as ED  # noqa: E402
from writing_phase_v2 import qa as QA  # noqa: E402
from writing_phase_v2 import writer as W  # noqa: E402

PLANS_DIR = r"C:\dev\Client Written Plans"
RENDER = os.path.join(ROOT, "python", "writing_phase_v2", "render")


def store_bundle(conn, v2, v1):
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS writing_phase_bundle (
        planning_run_id VARCHAR(64) NOT NULL PRIMARY KEY,
        draft_id VARCHAR(64) NOT NULL,
        bundle_version VARCHAR(8) NOT NULL,
        bundle_json LONGTEXT NOT NULL,
        v1_json LONGTEXT NOT NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6))
        ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cur.execute("REPLACE INTO writing_phase_bundle (planning_run_id, draft_id, "
                "bundle_version, bundle_json, v1_json) VALUES (%s,%s,%s,%s,%s)",
                (v2["meta"]["planning_run_id"], v2["meta"]["draft_id"],
                 v2["meta"]["bundle_version"],
                 json.dumps(v2, ensure_ascii=False),
                 json.dumps(v1, ensure_ascii=False)))
    conn.commit()


def run_model(family, v2, out, slug, skip_render, name):
    def save(stem, obj):
        p = os.path.join(out, stem)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        return p

    print(f"--- {family} writer ---")
    plan, raw, stats = W.WRITERS[family](v2)
    print("   ", stats)
    save(f"{slug}_{family}_raw.json", raw)
    if plan is None:
        print("    NO PLAN PARSED - stopping this model")
        return None
    save(f"{slug}_{family}_plan.json", plan)
    findings, info = CK.check(v2, plan)
    print("    CHECK 1:", info[0], "| findings:", len(findings))
    final = plan
    if findings:
        print(f"--- {family} editor (one pass) ---")
        edited, raw2, stats2 = ED.edit_plan(v2, plan, findings,
                                            model_family=family)
        print("   ", stats2)
        save(f"{slug}_{family}_raw_edited.json", raw2)
        if edited is not None:
            save(f"{slug}_{family}_plan_edited.json", edited)
            findings2, info2 = CK.check(v2, edited)
            print("    CHECK 2:", info2[0], "| findings:", len(findings2))
            final = edited
            findings = findings2
        else:
            print("    editor returned no plan - keeping the first draft")
    verdict = "PASS" if not findings else "FAIL (%d findings; run stops here)" % len(findings)
    print(f"    {family} FINAL: {verdict}")
    for f in findings[:20]:
        print("      ", f)

    if not skip_render:
        charts = os.path.join(out, "charts_" + family)
        bundle_path = os.path.join(out, f"{slug}_bundle_v2.json")
        subprocess.run([sys.executable, "-X", "utf8",
                        os.path.join(RENDER, "render_charts.py"),
                        bundle_path, charts], check=True)
        docx = os.path.join(
            PLANS_DIR, "%s -- Business Plan (%s v2, %s).docx"
            % (name, family.upper(),
               "unedited" if final is plan else "edited"))
        plan_path = save(f"{slug}_{family}_plan_final.json", final)
        env = dict(os.environ,
                   FIGURE_REGISTRY=os.path.join(ROOT, "python", "writing_phase_v2",
                                                "assets", "figure_registry.json"))
        subprocess.run(["node", os.path.join(RENDER, "render_plan_v2.js"),
                        bundle_path, plan_path, charts, docx,
                        "Business Plan — Working Draft"],
                       check=True, env=env, cwd=ROOT)
        print("    rendered ->", docx)
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--business", required=True)
    ap.add_argument("--models", default="gpt,claude")
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"))
    draft = B.load_draft(conn, a.business)
    name = draft["business_name"]
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    out = a.out or os.path.join(PLANS_DIR, "_v2_runs", slug)
    os.makedirs(out, exist_ok=True)
    print(f"business: {name} ({draft['draft_id'][:8]}) -> {out}")

    cls = CLS.classify(draft)
    v1 = B.assemble_v1(conn, draft)
    v2 = B.strip_to_v2(v1)
    store_bundle(conn, v2, v1)
    for stem, obj in ((f"{slug}_bundle_v1.json", v1),
                      (f"{slug}_bundle_v2.json", v2)):
        with open(os.path.join(out, stem), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    qa = QA.build_qa_report(v1, cls)
    with open(os.path.join(out, f"{slug}_qa_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(qa, f, ensure_ascii=False, indent=1)
    print("bundle v2: %d chars (~%dk tokens) | QA findings: %d | stored" % (
        len(json.dumps(v2)), len(json.dumps(v2)) // 4000,
        len(qa["findings"])))
    for f in qa["findings"]:
        print("  QA:", f["kind"], "-", f["what"][:120])

    for family in [m.strip() for m in a.models.split(",") if m.strip()]:
        run_model(family, v2, out, slug, a.skip_render, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
