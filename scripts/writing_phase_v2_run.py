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

    outcome = {"family": family, "state": "crashed", "detail": "", "docx": "",
               "findings": []}
    print(f"--- {family} writer ---")
    plan, raw, stats = W.WRITERS[family](v2)
    print("   ", stats)
    save(f"{slug}_{family}_raw.json", raw)
    if plan is None:
        print("    NO PLAN PARSED - stopping this model")
        outcome.update(state="crashed", detail="writer returned no parseable plan")
        return outcome
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
    passed = not findings
    verdict = "PASS" if passed else "FAIL (%d findings; run stops here)" % len(findings)
    print(f"    {family} FINAL: {verdict}")
    for f in findings[:20]:
        print("      ", f)

    if not skip_render:
        charts = os.path.join(out, "charts_" + family)
        bundle_path = os.path.join(out, f"{slug}_bundle_v2.json")
        # the renderer reads MORE than the writer's bundle (Nick 2026-09-08:
        # a chart isn't prose, the writer never sees it) - render_data.json
        # carries the renderer-only slices the run wrote from the draft
        render_data = os.path.join(out, f"{slug}_render_data.json")
        subprocess.run([sys.executable, "-X", "utf8",
                        os.path.join(RENDER, "render_charts.py"),
                        bundle_path, charts, render_data], check=True)
        # NO DOCUMENT SHIPS ON A FAILED FINAL CHECK (Nick 2026-09-08): a
        # passing plan lands in Client Written Plans; a failing draft
        # renders operator-side in _v2_runs, clearly named, never in the
        # ship folder - the Luna E2E proved the auto path needs this split.
        if passed:
            docx = os.path.join(
                PLANS_DIR, "%s -- Business Plan (%s v2, %s).docx"
                % (name, family.upper(),
                   "unedited" if final is plan else "edited"))
        else:
            docx = os.path.join(
                out, "%s -- FAILED DRAFT (%s v2).docx" % (name, family.upper()))
        plan_path = save(f"{slug}_{family}_plan_final.json", final)
        env = dict(os.environ,
                   FIGURE_REGISTRY=os.path.join(ROOT, "python", "writing_phase_v2",
                                                "assets", "figure_registry.json"))

        def _render(target):
            subprocess.run(["node", os.path.join(RENDER, "render_plan_v2.js"),
                            bundle_path, plan_path, charts, target,
                            "Business Plan — Working Draft"],
                           check=True, env=env, cwd=ROOT)
            return target
        try:
            rendered_to = _render(docx)
            print("    rendered ->", rendered_to)
        except subprocess.CalledProcessError:
            # the deliverable is open in Word (EBUSY) - land a stamped
            # sibling rather than losing the run
            rendered_to = _render(docx.replace(
                ".docx", " -- %s.docx" % _dt.datetime.now().strftime("%H-%M-%S")))
            print("    target locked; rendered ->", rendered_to)

        # THE COMPLETENESS GATE (Nick 2026-09-08): everything we check is
        # about what's ON the page - this checks what SHOULD be there.
        # Every registry item builds, or its absence carries a real data
        # reason; an absence with no reason FAILS the run.
        registry = json.load(open(os.path.join(
            ROOT, "python", "writing_phase_v2", "assets",
            "figure_registry.json"), encoding="utf-8"))["items"]
        report = {r["id"]: r for r in json.load(
            open(rendered_to + ".render_report.json", encoding="utf-8"))}
        unexplained = []
        for it in registry:
            r = report.get(it["id"])
            if r is None:
                unexplained.append("%s: not attempted by the renderer" % it["id"])
            elif not r.get("placed") and not r.get("reason"):
                unexplained.append("%s: absent with NO recorded reason" % it["id"])
            elif not r.get("placed") and str(r.get("reason", "")).startswith("RENDERER ERROR"):
                # a bug is not a data reason - the other figures survived,
                # but the run fails loudly
                unexplained.append("%s: %s" % (it["id"], r["reason"]))
            elif not r.get("placed"):
                print("    absent  %-32s %s" % (it["id"], r["reason"]))
        if unexplained:
            print("    COMPLETENESS: FAIL")
            for u in unexplained:
                print("      ", u)
            outcome.update(state="failed",
                           detail="completeness gate failed",
                           findings=unexplained, docx=rendered_to)
            return outcome
        print("    COMPLETENESS: PASS (%d of %d items on the page)"
              % (sum(1 for r in report.values() if r.get("placed")),
                 len(registry)))
        outcome["docx"] = rendered_to
    if passed:
        outcome.update(state="shipped", detail="final check clean")
    else:
        outcome.update(state="failed",
                       detail="final check failed (%d findings)" % len(findings),
                       findings=list(findings))
    return outcome


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--business", required=True)
    # THE MODEL IS DECIDED (Nick 2026-09-08): Claude writes the plans -
    # three consecutive Bellamy rolls passed where GPT failed on undeclared
    # arithmetic. A config value, never a code path: PLAN_WRITER_FAMILY
    # overrides, --models overrides that, and the GPT door stays runnable
    # on demand so the fallback never rots.
    ap.add_argument("--models",
                    default=os.getenv("PLAN_WRITER_FAMILY") or "claude")
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--planning-run-id", default=None,
                    help="THE RUN-ID GATE: the document and the workbook come "
                         "from the same planning run. When set (the automatic "
                         "trigger always sets it), the draft's current "
                         "planning_run_id must match or the run refuses.")
    a = ap.parse_args()

    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"))
    draft = B.load_draft(conn, a.business)
    if a.planning_run_id and str(draft.get("planning_run_id") or "") != a.planning_run_id:
        msg = ("RUN-ID GATE: draft %s carries planning_run_id %s but the trigger "
               "was for %s - a newer run superseded this one; refusing so the "
               "document can never pair with another run's workbook"
               % (draft["draft_id"][:8], draft.get("planning_run_id"),
                  a.planning_run_id))
        # a refusal is a terminal state and REPORTS like every other
        # (a silent stop is the failure mode that matters most)
        try:
            subprocess.run([sys.executable,
                            os.path.join(ROOT, "scripts", "notify_push_email.py"),
                            "[Written Plan] %s -- SUPERSEDED (run-id gate)"
                            % draft["business_name"], msg],
                           timeout=120, check=False)
        except Exception:
            pass
        raise SystemExit(msg)
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
    ms = json.loads(draft.get("marketing_schedule_json") or "{}") \
        if isinstance(draft.get("marketing_schedule_json"), (str, bytes)) \
        else (draft.get("marketing_schedule_json") or {})
    with open(os.path.join(out, f"{slug}_render_data.json"), "w",
              encoding="utf-8") as f:
        json.dump({"marketing_periods": ms.get("periods") or []}, f)
    qa = QA.build_qa_report(v1, cls)
    with open(os.path.join(out, f"{slug}_qa_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(qa, f, ensure_ascii=False, indent=1)
    print("bundle v2: %d chars (~%dk tokens) | QA findings: %d | stored" % (
        len(json.dumps(v2)), len(json.dumps(v2)) // 4000,
        len(qa["findings"])))
    for f in qa["findings"]:
        print("  QA:", f["kind"], "-", f["what"][:120])

    outcomes = []
    for family in [m.strip() for m in a.models.split(",") if m.strip()]:
        try:
            outcomes.append(run_model(family, v2, out, slug, a.skip_render, name))
        except Exception as exc:
            outcomes.append({"family": family, "state": "crashed",
                             "detail": "%s: %s" % (type(exc).__name__,
                                                   str(exc)[:400]),
                             "docx": "", "findings": []})
    if a.planning_run_id:
        _report_outcome(name, a.planning_run_id, qa, outcomes)
    return 0 if all(o.get("state") == "shipped" for o in outcomes) else 1


def _report_outcome(name, run_id, qa, outcomes):
    """EVERY automatic run reports its outcome (Nick 2026-09-08): passed
    and shipped, failed the check with findings, or crashed - by email,
    the same tail as the workbook mail. Best-effort: a failed send is
    logged, never a crash of its own."""
    try:
        states = {o.get("state") for o in outcomes}
        verdict = ("SHIPPED" if states == {"shipped"}
                   else "FAILED" if "crashed" not in states else "CRASHED")
        lines = ["Business: %s" % name, "Planning run: %s" % run_id, ""]
        attach = []
        for o in outcomes:
            lines.append("[%s] %s - %s" % (o.get("family", "?").upper(),
                                           o.get("state", "?").upper(),
                                           o.get("detail", "")))
            if o.get("docx"):
                lines.append("  document: %s" % o["docx"])
                if o.get("state") == "shipped":
                    attach.append(o["docx"])
            for f in (o.get("findings") or [])[:15]:
                lines.append("  finding: %s" % str(f)[:200])
            lines.append("")
        for f in (qa or {}).get("findings", []):
            lines.append("QA (operator): %s - %s" % (f.get("kind"), str(f.get("what"))[:160]))
        subject = "[Written Plan] %s -- %s" % (name, verdict)
        cmd = [sys.executable,
               os.path.join(ROOT, "scripts", "notify_push_email.py"),
               subject, "\n".join(lines)] + attach
        subprocess.run(cmd, timeout=120, check=False)
        print("outcome email sent: %s" % subject)
    except Exception as exc:
        print("outcome email FAILED: %s: %s" % (type(exc).__name__, str(exc)[:200]))


def _crash_report(business, run_id, exc):
    try:
        subprocess.run([sys.executable,
                        os.path.join(ROOT, "scripts", "notify_push_email.py"),
                        "[Written Plan] %s -- CRASHED" % business,
                        "Planning run: %s\n\nThe writing phase crashed before "
                        "producing an outcome:\n%s: %s" % (
                            run_id, type(exc).__name__, str(exc)[:1500])],
                       timeout=120, check=False)
    except Exception:
        pass


if __name__ == "__main__":
    # A RUN THAT STARTS ALWAYS ENDS IN ONE OF THREE REPORTED STATES
    # (Nick 2026-09-08): shipped, failed with findings, or crashed. A run
    # that stops silently is the failure mode that matters most - so any
    # exception ABOVE the per-model loop (assembly, the run-id gate, the
    # DB) still reports CRASHED before exiting, whenever the run was
    # triggered automatically (--planning-run-id present).
    _biz, _rid = "?", ""
    for _i, _v in enumerate(sys.argv):
        if _v == "--business" and _i + 1 < len(sys.argv):
            _biz = sys.argv[_i + 1]
        if _v == "--planning-run-id" and _i + 1 < len(sys.argv):
            _rid = sys.argv[_i + 1]
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as _exc:
        if _rid:
            _crash_report(_biz, _rid, _exc)
        raise
