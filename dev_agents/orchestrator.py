from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from .agents import DiagnoserAgent, FeasibilityAgent, FixerAgent, PromptAuditorAgent, RegressionAgent
from .artifacts import build_artifact_bundle, run_planning_command
from .checkpoints import restore_checkpoint
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
    if bundle.local_solver_summary.get("success"):
      reasons.append("Solver succeeded under the current grid.")
      return OrchestratorDecision(decision="stop", reasons=reasons, escalate=False)
    if audit.conflicting_instructions:
      reasons.append("Prompt audit found conflicting instructions.")
      return OrchestratorDecision(decision="escalate", reasons=reasons, escalate=True)
    if iteration_index >= self.config.max_iterations:
      reasons.append("Reached max iterations.")
      return OrchestratorDecision(decision="stop", reasons=reasons, escalate=True)
    if not fixer_result.actions:
      reasons.append("No actionable fix proposal was generated.")
      return OrchestratorDecision(decision="stop", reasons=reasons, escalate=True)
    if self.config.apply_fixes and fixer_result.applied_count > 0:
      reasons.append("Applied at least one supported fix; continue iteration.")
      return OrchestratorDecision(decision="continue", reasons=reasons, escalate=False)
    if self.config.apply_fixes and fixer_result.applied_count == 0:
      reasons.append("Only unsupported auto-fix actions remain.")
      return OrchestratorDecision(decision="stop", reasons=reasons, escalate=True)
    reasons.append("Fix proposals prepared; auto-apply is disabled so the loop stops here.")
    return OrchestratorDecision(decision="stop", reasons=reasons, escalate=False)

  def _confidence_value(self, label: str) -> int:
    mapping = {"low": 1, "medium": 2, "high": 3}
    return mapping.get(str(label or "").strip().lower(), 0)

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
        ]
      )
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

  def run(self) -> Dict[str, object]:
    previous_bundle: Optional[ArtifactBundle] = None
    previous_diagnosis: Optional[Diagnosis] = None
    previous_fixer_result = None
    iteration_summaries: List[Dict[str, object]] = []
    final_decision = OrchestratorDecision(decision="stop", reasons=["Loop did not run."], escalate=True)
    no_improvement_streak = 0

    for iteration_index in range(1, max(1, int(self.config.max_iterations)) + 1):
      iter_dir = self.session_dir / f"iteration_{iteration_index:02d}"
      iter_dir.mkdir(parents=True, exist_ok=True)

      command_result = run_planning_command(command=self.config.command, cwd=self.repo_root)
      bundle = build_artifact_bundle(command_result=command_result)
      diagnosis = self.diagnoser.run(bundle)
      audit = self.prompt_auditor.run(bundle)
      feasibility = self.feasibility.run(bundle)
      fixer_result = self.fixer.run(
        diagnosis=diagnosis,
        audit=audit,
        feasibility=feasibility,
        apply=bool(self.config.apply_fixes),
        allow_high_risk_fixes=bool(getattr(self.config, "allow_high_risk_fixes", False)),
        checkpoint_dir=iter_dir / "checkpoint",
      )
      regression_result = self.regression.run(
        current=bundle,
        previous=previous_bundle,
        current_diag=diagnosis,
        previous_diag=previous_diagnosis,
      )
      confidence_threshold_value = self._confidence_value(self.config.confidence_threshold)
      diagnosis_confidence_value = self._confidence_value(diagnosis.confidence)
      if diagnosis_confidence_value < confidence_threshold_value:
        final_decision = OrchestratorDecision(
          decision="escalate",
          reasons=[f"Diagnosis confidence {diagnosis.confidence} fell below threshold {self.config.confidence_threshold}."],
          escalate=True,
        )
      elif regression_result.regressed and previous_fixer_result and getattr(previous_fixer_result, "checkpoint_manifest", ""):
        restored = restore_checkpoint(repo_root=self.repo_root, manifest_path=str(previous_fixer_result.checkpoint_manifest))
        final_decision = OrchestratorDecision(
          decision="escalate",
          reasons=[f"Regression detected after applied fixes; restored {len(restored)} file(s) from previous checkpoint."],
          escalate=True,
        )
      else:
        if previous_bundle is not None:
          if regression_result.improved:
            no_improvement_streak = 0
          else:
            no_improvement_streak += 1
        decision = self._decision_for_iteration(
          iteration_index=iteration_index,
          bundle=bundle,
          audit=audit,
          fixer_result=fixer_result,
        )
        if no_improvement_streak >= 2:
          decision = OrchestratorDecision(
            decision="escalate",
            reasons=["No improvement for two consecutive iterations."],
            escalate=True,
          )
        high_risk_actions = [
          item.summary
          for item in fixer_result.actions
          if str(item.risk_level or "medium").strip().lower() == "high" and not item.applied
        ]
        if high_risk_actions and not bool(getattr(self.config, "allow_high_risk_fixes", False)):
          decision = OrchestratorDecision(
            decision="escalate",
            reasons=["High-risk change requires user review: " + "; ".join(high_risk_actions)],
            escalate=True,
          )
        final_decision = decision
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
      previous_fixer_result = fixer_result
      if final_decision.decision != "continue":
        break

    final_payload: Dict[str, object] = {
      "session_dir": str(self.session_dir),
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
    return final_payload
