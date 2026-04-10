from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


def _serialize(value: Any) -> Any:
  if isinstance(value, datetime):
    return value.isoformat()
  if isinstance(value, list):
    return [_serialize(item) for item in value]
  if isinstance(value, dict):
    return {str(key): _serialize(val) for key, val in value.items()}
  return value


@dataclass
class LoopConfig:
  command: str
  max_iterations: int = 5
  apply_fixes: bool = True
  allow_high_risk_fixes: bool = True
  confidence_threshold: str = "low"
  root_cause_only: bool = True
  focus: str = "cash"
  repo_root: str = ""
  session_dir: str = ""


@dataclass
class CommandResult:
  command: str
  returncode: int
  stdout: str
  stderr: str
  started_at: datetime
  ended_at: datetime
  detected_draft_id: str = ""


@dataclass
class ArtifactBundle:
  draft_id: str
  is_fresh_run: bool = False
  agent_context: Dict[str, Any] = field(default_factory=dict)
  row: Dict[str, Any] = field(default_factory=dict)
  planning_run_json: Dict[str, Any] = field(default_factory=dict)
  app_agents_run_json: Dict[str, Any] = field(default_factory=dict)
  prompt_file: str = ""
  prompt_file_text: str = ""
  gpt_narrative: str = ""
  gpt_grid_metadata: Dict[str, Any] = field(default_factory=dict)
  app_agents_trace: List[Dict[str, Any]] = field(default_factory=list)
  grid_response_json: Dict[str, Any] = field(default_factory=dict)
  solver_summary: Dict[str, Any] = field(default_factory=dict)
  local_solver_summary: Dict[str, Any] = field(default_factory=dict)
  local_solved_outputs: List[Dict[str, Any]] = field(default_factory=list)
  authoritative_cash_bands: List[Dict[str, Any]] = field(default_factory=list)
  authoritative_capital_rows: List[Dict[str, Any]] = field(default_factory=list)
  saved_paths: Dict[str, str] = field(default_factory=dict)
  command_result: Optional[CommandResult] = None

  def to_dict(self) -> Dict[str, Any]:
    return _serialize(asdict(self))


@dataclass
class Diagnosis:
  first_failing_quarter: str = ""
  band_violation: str = ""
  primary_cause: str = ""
  secondary_cause: str = ""
  affected_rows: List[str] = field(default_factory=list)
  confidence: str = "low"
  max_violation: float = 0.0
  mismatch_count: int = 0

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)


@dataclass
class PromptAudit:
  baseline_anchoring_detected: bool = False
  conflicting_instructions: bool = False
  prompt_leakage: bool = False
  cash_constraint_clear: bool = False
  grid_baseline_bias_risk: bool = False
  issues: List[str] = field(default_factory=list)
  evidence: List[str] = field(default_factory=list)

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)


@dataclass
class FeasibilityAssessment:
  cash_too_tight: bool = False
  levers_insufficient: bool = False
  engine_overpowered: bool = False
  recommendation: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)


@dataclass
class FixAction:
  action_type: str
  target: str
  summary: str
  details: Dict[str, Any] = field(default_factory=dict)
  risk_level: str = "medium"
  supported_for_auto_apply: bool = False
  applied: bool = False

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)


@dataclass
class FixerResult:
  actions: List[FixAction] = field(default_factory=list)
  applied_count: int = 0
  applicable_count: int = 0
  change_log: List[str] = field(default_factory=list)
  changed_files: List[str] = field(default_factory=list)
  checkpoint_manifest: str = ""
  no_fix_reason: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "actions": [item.to_dict() for item in self.actions],
      "applied_count": self.applied_count,
      "applicable_count": self.applicable_count,
      "change_log": list(self.change_log),
      "changed_files": list(self.changed_files),
      "checkpoint_manifest": self.checkpoint_manifest,
      "no_fix_reason": self.no_fix_reason,
    }


@dataclass
class RegressionResult:
  improved: bool = False
  regressed: bool = False
  moved_failure: str = ""
  shape_change: str = ""
  current_shape: str = ""
  previous_shape: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)


@dataclass
class OrchestratorDecision:
  decision: str
  reasons: List[str] = field(default_factory=list)
  escalate: bool = False

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)
