from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from .agents import DiagnoserAgent, FeasibilityAgent, FixerAgent, PromptAuditorAgent, RegressionAgent
from .artifacts import build_artifact_bundle, run_planning_command
from .models import ArtifactBundle, Diagnosis, LoopConfig, OrchestratorDecision
from .utils import repo_root_from_here, utcish_timestamp, write_json, write_text


class OrchestratorAgent:
  def __init__(self, config: LoopConfig) -> None:
    self.config = config
    self.repo_root = Path(config.repo_root or repo_root_from_here()).resolve()
    self.session_dir = Path(config.session_dir or (self.repo_root / "dev_agents" / "runs" / utcish_timestamp())).resolve()
    self.session_dir.mkdir(parents=True, exist_ok=True)
    self.diagnoser = DiagnoserAgent()
    self.prompt_auditor = PromptAuditorAgent(self.repo_root)
    self.feasibility = FeasibilityAgent()
    self.fixer = FixerAgent(self.repo_root)
    self.regression = RegressionAgent()

  def _decision_for_iteration(self, *, iteration_index: int, bundle: ArtifactBundle, audit, fixer_result) -> OrchestratorDecision:
    reasons: List[str] = []
    current_shape = ""
    try:
      current_shape = self.regression.run(
        current=bundle,
        previous=None,
        current_diag=Diagnosis(),
        previous_diag=None,
      ).current_shape
    except Exception:
      current_shape = ""
    if bundle.local_solver_summary.get("success"):
      if current_shape and current_shape != "staircase":
        reasons.append(f"Solver succeeded and cash shape is no longer a generic staircase ({current_shape}).")
        return OrchestratorDecision(decision="stop", reasons=reasons, escalate=False)
      if self.config.apply_fixes and fixer_result.applied_count <= 0:
        reasons.append("Solver succeeded but staircase remains, and no real fix was applied; stopping to avoid burning another paid rerun.")
        if fixer_result.no_fix_reason:
          reasons.append(fixer_result.no_fix_reason)
        return OrchestratorDecision(decision="stop", reasons=reasons, escalate=False)
      reasons.append("Solver succeeded, but cash shape is still a generic staircase; continue iterating on visible strategy expression.")
      return OrchestratorDecision(decision="continue", reasons=reasons, escalate=False)
    if iteration_index >= self.config.max_iterations:
      reasons.append("Reached max iterations.")
      return OrchestratorDecision(decision="stop", reasons=reasons, escalate=False)
    if self.config.apply_fixes and fixer_result.applied_count > 0:
      reasons.append("Applied at least one fix; continue iteration.")
      return OrchestratorDecision(decision="continue", reasons=reasons, escalate=False)
    if fixer_result.actions:
      reasons.append("Fixes were generated but none landed on disk; stopping to avoid a no-change rerun.")
      if fixer_result.no_fix_reason:
        reasons.append(fixer_result.no_fix_reason)
      return OrchestratorDecision(decision="stop", reasons=reasons, escalate=False)
    reasons.append("No fix proposal was generated; stopping instead of spending another run unchanged.")
    if fixer_result.no_fix_reason:
      reasons.append(fixer_result.no_fix_reason)
    return OrchestratorDecision(decision="stop", reasons=reasons, escalate=False)

  def _iteration_user_summary(
    self,
    *,
    bundle: ArtifactBundle,
    diagnosis,
    feasibility,
    fixer_result,
    regression_result,
    decision,
  ) -> Dict[str, object]:
    applied = [item.summary for item in fixer_result.actions if item.applied]
    proposed = [item.summary for item in fixer_result.actions if not item.applied]
    status = "Run succeeded" if bundle.local_solver_summary.get("success") else f"Run failed in {diagnosis.first_failing_quarter or 'unknown quarter'}"
    return {
      "status": status,
      "draft_id": bundle.draft_id,
      "root_cause": {
        "primary": diagnosis.primary_cause or "unknown",
        "secondary": diagnosis.secondary_cause or "unknown",
        "affected_rows": list(diagnosis.affected_rows or []),
        "band_violation": diagnosis.band_violation or "",
      },
      "feasibility": feasibility.to_dict(),
      "fix_applied": applied,
      "fix_proposed": proposed,
      "replay_result": {
        "moved_failure": regression_result.moved_failure or "n/a",
        "shape_change": regression_result.shape_change or regression_result.current_shape or "unknown",
        "current_shape": regression_result.current_shape or "unknown",
      },
      "decision": decision.decision,
      "decision_reasons": list(decision.reasons or []),
      "no_fix_reason": str(fixer_result.no_fix_reason or ""),
      "fix_status": {
        "applied_count": int(fixer_result.applied_count or 0),
        "applicable_count": int(fixer_result.applicable_count or 0),
        "changed_files": list(fixer_result.changed_files or []),
      },
    }

  def _render_iteration_markdown(self, payload: Dict[str, object]) -> str:
    root = payload.get("root_cause") if isinstance(payload.get("root_cause"), dict) else {}
    replay = payload.get("replay_result") if isinstance(payload.get("replay_result"), dict) else {}
    feasibility = payload.get("feasibility") if isinstance(payload.get("feasibility"), dict) else {}
    lines: List[str] = [
      str(payload.get("status") or "Run status unknown"),
      "",
      "Root cause:",
      f"- primary: {str(root.get('primary') or 'unknown')}",
      f"- secondary: {str(root.get('secondary') or 'unknown')}",
      f"- affected rows: {', '.join(root.get('affected_rows') or []) or 'n/a'}",
    ]
    if str(root.get("band_violation") or "").strip():
      lines.append(f"- band violation: {str(root.get('band_violation') or '').strip()}")
    lines.extend(
      [
        "",
        "Feasibility:",
        f"- cash too tight: {bool(feasibility.get('cash_too_tight'))}",
        f"- levers insufficient: {bool(feasibility.get('levers_insufficient'))}",
        f"- engine overpowered: {bool(feasibility.get('engine_overpowered'))}",
        f"- recommendation: {str(feasibility.get('recommendation') or 'n/a')}",
        "",
        "Fix applied:",
      ]
    )
    applied = list(payload.get("fix_applied") or [])
    proposed = list(payload.get("fix_proposed") or [])
    lines.extend([f"- {item}" for item in applied] or ["- none"])
    lines.extend(
      [
        "",
        "Fix proposed:",
      ]
    )
    lines.extend([f"- {item}" for item in proposed] or ["- none"])
    no_fix_reason = str(payload.get("no_fix_reason") or "").strip()
    fix_status = payload.get("fix_status") if isinstance(payload.get("fix_status"), dict) else {}
    lines.extend(
      [
        "",
        "Fix status:",
        f"- applied count: {int(fix_status.get('applied_count') or 0)}",
        f"- applicable count: {int(fix_status.get('applicable_count') or 0)}",
        f"- changed files: {', '.join(fix_status.get('changed_files') or []) or 'none'}",
      ]
    )
    if no_fix_reason:
      lines.append(f"- no-fix reason: {no_fix_reason}")
    lines.extend(
      [
        "",
        "Replay result:",
        f"- moved failure: {str(replay.get('moved_failure') or 'n/a')}",
        f"- shape change: {str(replay.get('shape_change') or 'unknown')}",
        "",
        "Decision:",
        f"- {str(payload.get('decision') or 'unknown')}",
      ]
    )
    for reason in payload.get("decision_reasons") or []:
      lines.append(f"- {reason}")
    return "\n".join(lines)

  def _render_final_markdown(self, *, iteration_summaries: List[Dict[str, object]], final_decision: OrchestratorDecision) -> str:
    lines: List[str] = [
      f"Session: {self.session_dir.name}",
      f"Iterations completed: {len(iteration_summaries)}",
      "",
    ]
    latest = iteration_summaries[-1]["user_summary"] if iteration_summaries else {}
    if isinstance(latest, dict) and latest:
      latest_fix_status = latest.get("fix_status") if isinstance(latest.get("fix_status"), dict) else {}
      lines.extend(
        [
          "Where We Are At:",
          str(latest.get("status") or "Run status unknown"),
          "",
          "Root cause:",
          f"- primary: {str(((latest.get('root_cause') or {}) if isinstance(latest.get('root_cause'), dict) else {}).get('primary') or 'unknown')}",
          f"- secondary: {str(((latest.get('root_cause') or {}) if isinstance(latest.get('root_cause'), dict) else {}).get('secondary') or 'unknown')}",
          "",
          "Replay result:",
          f"- moved failure: {str(((latest.get('replay_result') or {}) if isinstance(latest.get('replay_result'), dict) else {}).get('moved_failure') or 'n/a')}",
          f"- shape change: {str(((latest.get('replay_result') or {}) if isinstance(latest.get('replay_result'), dict) else {}).get('shape_change') or 'unknown')}",
          "",
          "Fix status:",
          f"- applied count: {int(latest_fix_status.get('applied_count') or 0)}",
          f"- applicable count: {int(latest_fix_status.get('applicable_count') or 0)}",
          f"- changed files: {', '.join(latest_fix_status.get('changed_files') or []) or 'none'}",
          "",
        ]
      )
      if str(latest.get("no_fix_reason") or "").strip():
        lines.append(f"No-fix reason: {str(latest.get('no_fix_reason') or '').strip()}")
        lines.append("")
    lines.append("Iteration timeline:")
    for item in iteration_summaries:
      user_summary = item.get("user_summary") if isinstance(item.get("user_summary"), dict) else {}
      lines.extend(
        [
          f"- Iteration {item['iteration']}: {str(user_summary.get('status') or 'unknown status')}",
          f"  draft_id: {item['draft_id']}",
          f"  decision: {str(user_summary.get('decision') or 'unknown')}",
        ]
      )
    lines.extend(
      [
        "",
        "Final decision:",
        f"- {final_decision.decision}",
      ]
    )
    lines.extend(f"- {reason}" for reason in final_decision.reasons)
    return "\n".join(lines)

  def _update_persistent_learnings(self, *, final_payload: Dict[str, object], iteration_summaries: List[Dict[str, object]]) -> None:
    learning_path = self.repo_root / "dev_agents" / "LEARNINGS_APP_AGENTS.md"
    latest = iteration_summaries[-1]["user_summary"] if iteration_summaries else {}
    if not isinstance(latest, dict):
      latest = {}
    latest_root = latest.get("root_cause") if isinstance(latest.get("root_cause"), dict) else {}
    latest_replay = latest.get("replay_result") if isinstance(latest.get("replay_result"), dict) else {}
    status = str(latest.get("status") or "unknown")
    decision = str(latest.get("decision") or "unknown")
    primary = str(latest_root.get("primary") or "unknown")
    secondary = str(latest_root.get("secondary") or "unknown")
    applied = [str(item) for item in (latest.get("fix_applied") or []) if str(item).strip()]
    proposed = [str(item) for item in (latest.get("fix_proposed") or []) if str(item).strip()]
    shape = str(latest_replay.get("current_shape") or "unknown")
    shape_change = str(latest_replay.get("shape_change") or "unknown")
    iterations_completed = len(iteration_summaries)

    verdict = "mixed"
    if "succeeded" in status.lower() and shape != "staircase":
      verdict = "good"
    elif "failed" in status.lower():
      verdict = "bad"
    elif "succeeded" in status.lower():
      verdict = "mixed"

    confidence = "low"
    if iterations_completed >= 3 and verdict == "good":
      confidence = "medium"
    if iterations_completed >= 4 and verdict == "good" and shape not in {"unknown", "staircase"}:
      confidence = "high"
    if verdict == "bad":
      confidence = "medium" if iterations_completed >= 2 else "low"

    scope = "unknown"
    notes_parts: List[str] = []
    if any("med-spa" in item.lower() for item in applied + proposed):
      scope = "case-specific"
    elif confidence == "high" and "architecture" not in f"{primary} {secondary}".lower():
      scope = "general"
    elif confidence in {"low", "medium"}:
      scope = "unknown"
    if shape == "staircase":
      notes_parts.append("Solver success still produced a staircase cash shape.")
    if applied:
      notes_parts.append("Applied fixes: " + "; ".join(applied))
    elif proposed:
      notes_parts.append("Only proposed fixes were available: " + "; ".join(proposed))
    final_reasons = list((final_payload.get("final_decision") or {}).get("reasons") or []) if isinstance(final_payload.get("final_decision"), dict) else []
    if final_reasons:
      notes_parts.append("Final reasons: " + "; ".join(str(item) for item in final_reasons))
    if "architecture" in f"{primary} {secondary}".lower():
      confidence = "low"
      scope = "unknown"
      notes_parts.append("Architecture-level takeaway kept conservative unless repeated evidence accumulates.")

    block_lines = [
      "",
      f"## Learning {self.session_dir.name}",
      "",
      f"- issue: {primary} / {secondary}",
      f"- fix_attempted: {'; '.join(applied) if applied else ('; '.join(proposed) if proposed else 'none')}",
      f"- result: {status}; cash shape={shape}; shape_change={shape_change}; decision={decision}",
      f"- verdict: {verdict}",
      f"- learning_confidence: {confidence}",
      f"- scope: {scope}",
      f"- notes: {' '.join(notes_parts).strip() or 'n/a'}",
    ]

    existing = ""
    try:
      existing = learning_path.read_text(encoding="utf-8")
    except Exception:
      existing = "# Persistent Learnings\n"
    learning_path.write_text(existing.rstrip() + "\n" + "\n".join(block_lines) + "\n", encoding="utf-8")

  def run(self) -> Dict[str, object]:
    previous_bundle: Optional[ArtifactBundle] = None
    previous_diagnosis: Optional[Diagnosis] = None
    iteration_summaries: List[Dict[str, object]] = []
    final_decision = OrchestratorDecision(decision="stop", reasons=["Loop did not run."], escalate=False)

    for iteration_index in range(1, max(1, int(self.config.max_iterations)) + 1):
      iter_dir = self.session_dir / f"iteration_{iteration_index:02d}"
      iter_dir.mkdir(parents=True, exist_ok=True)

      command_result = run_planning_command(command=self.config.command, cwd=self.repo_root)
      bundle = build_artifact_bundle(command_result=command_result)
      if not bundle.is_fresh_run and command_result.returncode == 0 and iteration_index > 1:
        final_decision = OrchestratorDecision(
          decision="stop",
          reasons=["No fresh draft/run artifact was detected after rerun; stopping instead of reusing stale artifacts."],
          escalate=False,
        )
        write_json(iter_dir / "command_result.json", {
          "command": command_result.command,
          "returncode": command_result.returncode,
          "stdout": command_result.stdout,
          "stderr": command_result.stderr,
          "started_at": command_result.started_at.isoformat(),
          "ended_at": command_result.ended_at.isoformat(),
          "detected_draft_id": command_result.detected_draft_id,
        })
        write_json(iter_dir / "artifact_bundle.json", bundle.to_dict())
        write_json(iter_dir / "decision.json", final_decision.to_dict())
        iteration_summaries.append(
          {
            "iteration": iteration_index,
            "draft_id": bundle.draft_id,
            "diagnosis": {},
            "prompt_audit": {},
            "feasibility": {},
            "fixer": {},
            "regression": {},
            "decision": final_decision.to_dict(),
            "user_summary": {
              "status": "No fresh run artifact detected",
              "draft_id": bundle.draft_id,
              "root_cause": {
                "primary": "stale_artifact_reuse",
                "secondary": "command_did_not_create_new_run",
                "affected_rows": [],
                "band_violation": "",
              },
              "feasibility": {},
              "fix_applied": [],
              "fix_proposed": [],
              "no_fix_reason": "No fresh draft/run artifact was detected after rerun.",
              "fix_status": {"applied_count": 0, "applicable_count": 0, "changed_files": []},
              "replay_result": {"moved_failure": "n/a", "shape_change": "unknown", "current_shape": "unknown"},
              "decision": final_decision.decision,
              "decision_reasons": list(final_decision.reasons or []),
            },
          }
        )
        break
      if not bundle.is_fresh_run and command_result.returncode != 0 and not str(bundle.draft_id or "").strip():
        bundle.command_result = command_result
      diagnosis = self.diagnoser.run(bundle)
      audit = self.prompt_auditor.run(bundle)
      feasibility = self.feasibility.run(bundle)
      fixer_result = self.fixer.run(
        bundle=bundle,
        diagnosis=diagnosis,
        audit=audit,
        feasibility=feasibility,
        apply=bool(self.config.apply_fixes),
        allow_high_risk_fixes=bool(getattr(self.config, "allow_high_risk_fixes", False)),
        root_cause_only=bool(getattr(self.config, "root_cause_only", True)),
        checkpoint_dir=iter_dir / "checkpoint",
      )
      regression_result = self.regression.run(
        current=bundle,
        previous=previous_bundle,
        current_diag=diagnosis,
        previous_diag=previous_diagnosis,
      )
      final_decision = self._decision_for_iteration(
        iteration_index=iteration_index,
        bundle=bundle,
        audit=audit,
        fixer_result=fixer_result,
      )
      user_summary = self._iteration_user_summary(
        bundle=bundle,
        diagnosis=diagnosis,
        feasibility=feasibility,
        fixer_result=fixer_result,
        regression_result=regression_result,
        decision=final_decision,
      )

      write_json(iter_dir / "command_result.json", {
        "command": command_result.command,
        "returncode": command_result.returncode,
        "stdout": command_result.stdout,
        "stderr": command_result.stderr,
        "started_at": command_result.started_at.isoformat(),
        "ended_at": command_result.ended_at.isoformat(),
        "detected_draft_id": command_result.detected_draft_id,
      })
      write_json(iter_dir / "artifact_bundle.json", bundle.to_dict())
      write_json(iter_dir / "diagnosis.json", diagnosis.to_dict())
      write_json(iter_dir / "prompt_audit.json", audit.to_dict())
      write_json(iter_dir / "feasibility.json", feasibility.to_dict())
      write_json(iter_dir / "fixer.json", fixer_result.to_dict())
      write_json(iter_dir / "regression.json", regression_result.to_dict())
      write_json(iter_dir / "decision.json", final_decision.to_dict())
      write_json(iter_dir / "user_summary.json", user_summary)
      write_text(iter_dir / "summary.md", self._render_iteration_markdown(user_summary))

      iteration_summaries.append(
        {
          "iteration": iteration_index,
          "draft_id": bundle.draft_id,
          "diagnosis": diagnosis.to_dict(),
          "prompt_audit": audit.to_dict(),
          "feasibility": feasibility.to_dict(),
          "fixer": fixer_result.to_dict(),
          "regression": regression_result.to_dict(),
          "decision": final_decision.to_dict(),
          "user_summary": user_summary,
        }
      )
      previous_bundle = bundle
      previous_diagnosis = diagnosis
      if final_decision.decision != "continue":
        break

    final_payload: Dict[str, object] = {
      "session_dir": str(self.session_dir),
      "agent_runtime_context": {
        "expected_runtime_commit": "",
        "production_ai_shape": "app_agents_four_agent_planner",
        "max_iterations": int(self.config.max_iterations),
        "root_cause_only": bool(getattr(self.config, "root_cause_only", True)),
      },
      "iterations": iteration_summaries,
      "final_decision": final_decision.to_dict(),
    }
    write_json(self.session_dir / "final_report.json", final_payload)
    executive_payload: Dict[str, object] = {
      "session_dir": str(self.session_dir),
      "iterations_completed": len(iteration_summaries),
      "latest": iteration_summaries[-1]["user_summary"] if iteration_summaries else {},
      "final_decision": final_decision.to_dict(),
      "timeline": [
        {
          "iteration": item["iteration"],
          "draft_id": item["draft_id"],
          "status": (item.get("user_summary") or {}).get("status"),
          "decision": (item.get("user_summary") or {}).get("decision"),
        }
        for item in iteration_summaries
      ],
    }
    write_json(self.session_dir / "executive_summary.json", executive_payload)
    write_text(self.session_dir / "final_report.md", self._render_final_markdown(iteration_summaries=iteration_summaries, final_decision=final_decision))
    write_text(self.session_dir / "executive_summary.md", self._render_final_markdown(iteration_summaries=iteration_summaries, final_decision=final_decision))
    self._update_persistent_learnings(final_payload=final_payload, iteration_summaries=iteration_summaries)
    return final_payload
