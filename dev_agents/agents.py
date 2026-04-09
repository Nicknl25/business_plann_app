from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .artifacts import extract_cash_violations
from .checkpoints import create_checkpoint
from .models import ArtifactBundle, Diagnosis, FeasibilityAssessment, FixAction, FixerResult, PromptAudit, RegressionResult
from .utils import classify_cash_shape, quarter_label, safe_float


_CAPITAL_ROW_LABELS = {
  "schedules::Capital Expenditures": "capex",
  "schedules::Less: Principal Repayments": "principal_repayments",
  "schedules::Plus: Additions (repayments), net": "debt_additions",
  "schedules::Plus: Net Additions": "net_additions",
  "expenses::Payroll": "payroll",
  "expenses::Marketing": "marketing",
}


def _rows_by_id(bundle: ArtifactBundle) -> Dict[str, Dict[str, object]]:
  rows = bundle.grid_response_json.get("rows") if isinstance(bundle.grid_response_json.get("rows"), list) else []
  return {
    str(item.get("row_id") or "").strip(): dict(item)
    for item in rows
    if isinstance(item, dict) and str(item.get("row_id") or "").strip()
  }


def _quarter_band(row: Dict[str, object], quarter_index: int) -> Dict[str, object]:
  for item in row.get("quarter_bands") or []:
    if int(safe_float((item or {}).get("quarter_index")) or 0) == int(quarter_index):
      return dict(item)
  return {}


class DiagnoserAgent:
  def run(self, bundle: ArtifactBundle) -> Diagnosis:
    violations = extract_cash_violations(bundle)
    first_bad = next((item for item in violations if str(item.get("direction")) != "inside"), None)
    diagnosis = Diagnosis(confidence="low")
    if not first_bad:
      diagnosis.primary_cause = "no_cash_band_violation_detected"
      diagnosis.secondary_cause = "none"
      diagnosis.confidence = "medium" if bundle.local_solver_summary else "low"
      return diagnosis

    diagnosis.first_failing_quarter = quarter_label(int(first_bad.get("quarter_index") or 0))
    diagnosis.band_violation = (
      f"{diagnosis.first_failing_quarter}: cash {float(first_bad.get('ending_cash') or 0.0):,.2f} "
      f"vs band {float(first_bad.get('band_min') or 0.0):,.2f} to {float(first_bad.get('band_max') or 0.0):,.2f}"
    )
    diagnosis.max_violation = max(abs(float(item.get("delta") or 0.0)) for item in violations)
    diagnosis.mismatch_count = len([item for item in violations if str(item.get("direction")) != "inside"])

    rows = _rows_by_id(bundle)
    q = int(first_bad.get("quarter_index") or 0)
    affected_rows: List[str] = []
    capital_pressure = False
    for row_id, label in _CAPITAL_ROW_LABELS.items():
      row = rows.get(row_id) or {}
      band = _quarter_band(row, q)
      band_min = safe_float(band.get("min_value"))
      band_max = safe_float(band.get("max_value"))
      if band_min is None or band_max is None:
        continue
      width = abs(band_max - band_min)
      if width <= 0.000001 or (label in {"capex", "principal_repayments", "debt_additions", "net_additions"} and width < 10000):
        affected_rows.append(label)
        capital_pressure = True
      elif label in {"payroll", "marketing"} and width < max(5000.0, abs(band_max) * 0.08):
        affected_rows.append(label)
    diagnosis.affected_rows = sorted(set(affected_rows))

    direction = str(first_bad.get("direction") or "")
    if direction == "above_max":
      diagnosis.primary_cause = "capital allocation insufficient" if capital_pressure else "cash band too tight"
      diagnosis.secondary_cause = "engine overpowered"
    else:
      diagnosis.primary_cause = "cash band too loose on downside"
      diagnosis.secondary_cause = "operating engine underpowered"
    diagnosis.confidence = "high" if diagnosis.mismatch_count > 0 else "medium"
    return diagnosis


class PromptAuditorAgent:
  def __init__(self, repo_root: Path) -> None:
    self.repo_root = repo_root

  def run(self, bundle: ArtifactBundle) -> PromptAudit:
    audit = PromptAudit()
    files = {
      "quarter_grid": self.repo_root / "python" / "client_intake_and_finmo" / "quarter_grid.py",
      "cash_contract": self.repo_root / "python" / "client_intake_and_finmo" / "cash_contract_baby_ai.py",
      "capital_allocation": self.repo_root / "python" / "client_intake_and_finmo" / "capital_allocation_baby_ai.py",
    }
    text_by_file = {name: path.read_text(encoding="utf-8") for name, path in files.items() if path.exists()}
    if bundle.prompt_file_text:
      text_by_file["planning_mode_prompt"] = bundle.prompt_file_text
    leak_patterns = [
      "\"baseline_summary\": _sanitize_canonical_live_payload",
      "\"baseline_cash_path\": _sanitize_canonical_live_payload",
      "baseline values as reference context",
      "Baseline treatment:",
    ]
    for name, text in text_by_file.items():
      for pattern in leak_patterns:
        if pattern in text:
          audit.prompt_leakage = True
          audit.evidence.append(f"{name}: found '{pattern}'")
    audit.cash_constraint_clear = any("hard cash law" in text or "cash constraint as binding" in text for text in text_by_file.values())
    if any("carry no planning authority" in text or "Do not infer later-quarter defaults" in text for text in text_by_file.values()):
      audit.grid_baseline_bias_risk = False
    else:
      audit.grid_baseline_bias_risk = True
      audit.issues.append("Later-quarter placeholder non-authority language is missing from one or more AI paths.")
    if any("spread-placeholder" in text or "placeholder-like" in text for text in text_by_file.values()):
      audit.baseline_anchoring_detected = False
    else:
      audit.baseline_anchoring_detected = True
      audit.issues.append("Prompt stack still appears to give later-quarter placeholders authority.")
    if "do not override core business drivers" in text_by_file.get("quarter_grid", "") and "fair game for material change" not in text_by_file.get("quarter_grid", ""):
      audit.conflicting_instructions = True
      audit.issues.append("Main planner prompt may be preserving operating baseline too strongly.")
    return audit


class FeasibilityAgent:
  def run(self, bundle: ArtifactBundle) -> FeasibilityAssessment:
    violations = extract_cash_violations(bundle)
    outside = [item for item in violations if str(item.get("direction")) != "inside"]
    assessment = FeasibilityAssessment()
    if not outside:
      assessment.recommendation = "Current run is solver-feasible under the current cash bands."
      return assessment

    q = int(outside[0].get("quarter_index") or 0)
    solved_q = next((item for item in bundle.local_solved_outputs if int(safe_float(item.get("quarter_index")) or 0) == q), {})
    revenue = safe_float(solved_q.get("revenue")) or 0.0
    ebitda = safe_float(solved_q.get("ebitda")) or 0.0
    assessment.cash_too_tight = str(outside[0].get("direction")) == "above_max"
    assessment.engine_overpowered = revenue > 0 and ebitda > max(50000.0, revenue * 0.12)

    rows = _rows_by_id(bundle)
    weak_capital_rows = 0
    for row_id in [
      "schedules::Capital Expenditures",
      "schedules::Less: Principal Repayments",
      "schedules::Plus: Additions (repayments), net",
      "schedules::Plus: Net Additions",
    ]:
      band = _quarter_band(rows.get(row_id) or {}, q)
      band_min = safe_float(band.get("min_value"))
      band_max = safe_float(band.get("max_value"))
      if band_min is None or band_max is None:
        continue
      if abs(band_max - band_min) < 10000.0:
        weak_capital_rows += 1
    assessment.levers_insufficient = weak_capital_rows >= 2

    recommendations: List[str] = []
    if assessment.cash_too_tight:
      recommendations.append("Relax the later-quarter cash path or add materially wider deployment capacity where the first failing quarter breaks.")
    if assessment.levers_insufficient:
      recommendations.append("Strengthen capital-allocation rows in the first failing window rather than relying on small schedule ranges.")
    if assessment.engine_overpowered:
      recommendations.append("Reduce the operating engine or widen non-cash absorption so cash generation does not outrun the bands.")
    assessment.recommendation = " ".join(recommendations).strip() or "Investigate the first failing quarter."
    return assessment


class FixerAgent:
  def __init__(self, repo_root: Path) -> None:
    self.repo_root = repo_root
    self.allowed_targets = {
      "python/client_intake_and_finmo/quarter_grid.py",
      "python/client_intake_and_finmo/cash_contract_baby_ai.py",
      "python/client_intake_and_finmo/capital_allocation_baby_ai.py",
      "python/financial_model_engine/solver.py",
    }

  def _allowed_path(self, target: str) -> Path:
    normalized = str(target or "").replace("\\", "/").strip()
    if normalized not in self.allowed_targets:
      raise RuntimeError(f"Unsupported fixer target: {target}")
    return self.repo_root / normalized

  def _apply_insert_after(self, *, file_path: Path, needle: str, snippet: str) -> bool:
    if not file_path.exists():
      return False
    text = file_path.read_text(encoding="utf-8")
    if snippet in text or needle not in text:
      return False
    file_path.write_text(text.replace(needle, needle + snippet, 1), encoding="utf-8")
    return True

  def _apply_replace_once(self, *, file_path: Path, old: str, new: str) -> bool:
    if not file_path.exists():
      return False
    text = file_path.read_text(encoding="utf-8")
    if old not in text or new in text:
      return False
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True

  def _apply_remove_block(self, *, file_path: Path, block: str) -> bool:
    if not file_path.exists():
      return False
    text = file_path.read_text(encoding="utf-8")
    if block not in text:
      return False
    file_path.write_text(text.replace(block, "", 1), encoding="utf-8")
    return True

  def _apply_action(self, action: FixAction) -> bool:
    details = action.details or {}
    file_path = self._allowed_path(action.target)
    patch_kind = str(details.get("patch_kind") or "").strip()
    if patch_kind == "insert_after":
      return self._apply_insert_after(
        file_path=file_path,
        needle=str(details.get("needle") or ""),
        snippet=str(details.get("snippet") or ""),
      )
    if patch_kind == "replace_once":
      return self._apply_replace_once(
        file_path=file_path,
        old=str(details.get("old") or ""),
        new=str(details.get("new") or ""),
      )
    if patch_kind == "remove_block":
      return self._apply_remove_block(
        file_path=file_path,
        block=str(details.get("block") or ""),
      )
    raise RuntimeError(f"Unsupported patch_kind: {patch_kind}")

  def _validate_imports(self) -> bool:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = "python"
    python_exe = self.repo_root / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
      return False
    proc = subprocess.run(
      [
        str(python_exe),
        "-B",
        "-c",
        "import client_intake_and_finmo.quarter_grid, client_intake_and_finmo.cash_contract_baby_ai, client_intake_and_finmo.capital_allocation_baby_ai, financial_model_engine.solver; print('OK imports')",
      ],
      cwd=str(self.repo_root),
      env=env,
      text=True,
      capture_output=True,
    )
    return proc.returncode == 0

  def run(
    self,
    *,
    diagnosis: Diagnosis,
    audit: PromptAudit,
    feasibility: FeasibilityAssessment,
    apply: bool,
    allow_high_risk_fixes: bool = False,
    checkpoint_dir: Optional[Path] = None,
  ) -> FixerResult:
    result = FixerResult()
    if audit.prompt_leakage or audit.baseline_anchoring_detected:
      result.actions.append(
        FixAction(
          action_type="prompt_modification",
          target="python/client_intake_and_finmo/quarter_grid.py",
          summary="Strengthen later-quarter non-authority language in the main planner prompt.",
          details={
            "patch_kind": "insert_after",
            "needle": "\"- the displayed Q2 through Q20 row values are intentionally blank; do not infer hidden defaults from them\\n\",",
            "snippet": "      \"- every Q2 through Q20 cell must be actively chosen from business reality and the hard cash law rather than reconstructed from placeholder history\\n\",\n",
          },
          risk_level="low",
          supported_for_auto_apply=True,
        )
      )
      result.actions.append(
        FixAction(
          action_type="payload_sanitization",
          target="python/client_intake_and_finmo/quarter_grid.py",
          summary="Remove raw fixed-facts model views from the AI-facing planning-mode payload.",
          details={
            "patch_kind": "remove_block",
            "block": "    \"fixed_facts\": {\n      \"model_input_json\": _sanitize_canonical_live_payload(model_input_json or {}),\n      \"finmo_json\": _sanitize_canonical_live_payload(finmo_json or {}),\n    },\n",
          },
          risk_level="medium",
          supported_for_auto_apply=True,
        )
      )
    if diagnosis.primary_cause == "capital allocation insufficient":
      result.actions.append(
        FixAction(
          action_type="capex_range_expansion",
          target="python/client_intake_and_finmo/capital_allocation_baby_ai.py",
          summary="Widen capex / schedule deployment behavior in the first failing window.",
          details={
            "patch_kind": "insert_after",
            "needle": "\"In particular, do not leave Capital Expenditures, Principal Repayments, debt movement rows, or Net Additions as tiny or repeated placeholder-like ranges if the cash posture requires real deployment.\\n\",\n",
            "snippet": "      \"When the first failing quarter shows cash still above band, widen the relevant schedule-style deployment rows materially in that quarter and the immediately following window rather than making only cosmetic increases.\\n\",\n",
            "first_failing_quarter": diagnosis.first_failing_quarter,
            "affected_rows": diagnosis.affected_rows,
          },
          risk_level="medium",
          supported_for_auto_apply=True,
        )
      )
    if feasibility.cash_too_tight:
      result.actions.append(
        FixAction(
          action_type="cash_band_adjustment",
          target="python/client_intake_and_finmo/cash_contract_baby_ai.py",
          summary="Relax later-quarter cash posture where the business cannot credibly absorb the surplus.",
          details={
            "patch_kind": "insert_after",
            "needle": "\"If the business is likely to generate more cash than it can credibly redeploy in a given horizon, relax the cash path instead of forcing an unrealistically low balance.\\n\",\n",
            "snippet": "      \"If a quarter would only be feasible with implausibly small retained cash or implausibly large deployment, widen that quarter and the next few quarters rather than forcing the planner into infeasible bands.\\n\",\n",
            "recommendation": feasibility.recommendation,
          },
          risk_level="medium",
          supported_for_auto_apply=True,
        )
      )
    if feasibility.engine_overpowered:
      result.actions.append(
        FixAction(
          action_type="prompt_modification",
          target="python/client_intake_and_finmo/quarter_grid.py",
          summary="Strengthen non-cash planning pressure against an overpowered operating engine.",
          details={
            "patch_kind": "insert_after",
            "needle": "\"- if the cash law requires meaningful deployment or absorption, you are expected to move discretionary non-cash rows materially after Q1 when that is what a believable business would do\\n\",",
            "snippet": "      \"- if the operating engine still generates excess cash after that, you must also moderate the operating rows realistically rather than assuming deployment rows alone can absorb everything\\n\",\n",
          },
          risk_level="medium",
          supported_for_auto_apply=True,
        )
      )
      result.actions.append(
        FixAction(
          action_type="solver_tuning",
          target="python/financial_model_engine/solver.py",
          summary="Increase midpoint pressure so feasible solves gravitate more strongly toward band centers.",
          details={
            "patch_kind": "replace_once",
            "old": "  target_center_weight: float = 1.0\n",
            "new": "  target_center_weight: float = 2.5\n",
          },
          risk_level="high",
          supported_for_auto_apply=False,
        )
      )
    if apply:
      applied_targets = [
        str(action.target)
        for action in result.actions
        if action.supported_for_auto_apply and (
          allow_high_risk_fixes or str(action.risk_level or "medium").strip().lower() != "high"
        )
      ]
      if applied_targets and checkpoint_dir is not None:
        result.checkpoint_manifest = create_checkpoint(
          repo_root=self.repo_root,
          targets=applied_targets,
          checkpoint_dir=checkpoint_dir,
        )
      for action in result.actions:
        if not action.supported_for_auto_apply:
          continue
        if str(action.risk_level or "medium").strip().lower() == "high" and not allow_high_risk_fixes:
          continue
        if self._apply_action(action):
          action.applied = True
          result.applied_count += 1
          if str(action.target) not in result.changed_files:
            result.changed_files.append(str(action.target))
          result.change_log.append(f"Applied {action.action_type} to {action.target}")
      if result.applied_count > 0 and not self._validate_imports():
        result.change_log.append("Import validation failed after applying fixes; restore from checkpoint before continuing.")
    return result


class RegressionAgent:
  def run(self, *, current: ArtifactBundle, previous: Optional[ArtifactBundle], current_diag: Diagnosis, previous_diag: Optional[Diagnosis]) -> RegressionResult:
    current_shape = classify_cash_shape(float(item.get("ending_cash") or 0.0) for item in current.local_solved_outputs)
    previous_shape = classify_cash_shape(float(item.get("ending_cash") or 0.0) for item in (previous.local_solved_outputs if previous else [])) if previous else ""
    result = RegressionResult(current_shape=current_shape, previous_shape=previous_shape)
    if previous_diag is None:
      result.shape_change = current_shape
      return result

    def quarter_num(text: str) -> int:
      try:
        return int(str(text or "").replace("Q", "").strip())
      except Exception:
        return 0

    cur_q = quarter_num(current_diag.first_failing_quarter)
    prev_q = quarter_num(previous_diag.first_failing_quarter)
    if prev_q and cur_q:
      if cur_q > prev_q:
        result.improved = True
        result.moved_failure = f"Q{prev_q} → Q{cur_q}"
      elif cur_q < prev_q:
        result.regressed = True
        result.moved_failure = f"Q{prev_q} → Q{cur_q}"
    if previous_diag.max_violation and current_diag.max_violation < previous_diag.max_violation:
      result.improved = True
    elif previous_diag.max_violation and current_diag.max_violation > previous_diag.max_violation:
      result.regressed = True
    result.shape_change = f"{previous_shape} → {current_shape}" if previous_shape and previous_shape != current_shape else current_shape
    return result
