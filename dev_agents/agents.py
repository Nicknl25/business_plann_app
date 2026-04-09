from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .artifacts import extract_cash_violations
from .checkpoints import create_checkpoint, restore_checkpoint
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
      command_error = ""
      if bundle.command_result is not None:
        command_error = "\n".join([
          str(bundle.command_result.stderr or "").strip(),
          str(bundle.command_result.stdout or "").strip(),
        ]).strip()
      lower_error = command_error.lower()
      if "q1 cash anchor was not derived and applied coherently" in lower_error:
        diagnosis.primary_cause = "q1_cash_anchor_incoherent"
        diagnosis.secondary_cause = "cash pipeline audit failed"
        diagnosis.band_violation = "Q1 cash anchor was not derived and applied coherently."
        diagnosis.affected_rows = ["cash_anchor", "cash_pipeline"]
        diagnosis.confidence = "high"
        return diagnosis
      if "planning_solver_failed" in lower_error:
        diagnosis.primary_cause = "planning_solver_failed"
        diagnosis.secondary_cause = "solver_feasibility_failure"
        diagnosis.band_violation = "Planning solver failed before a solved plan was produced."
        diagnosis.confidence = "high"
        return diagnosis
      if "system_run_failed" in lower_error:
        diagnosis.primary_cause = "system_run_failed"
        diagnosis.secondary_cause = "backend_pipeline_failure"
        diagnosis.band_violation = command_error[:300]
        diagnosis.confidence = "medium"
        return diagnosis
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
    guidance = bundle.agent_context.get("guidance_text") if isinstance(bundle.agent_context.get("guidance_text"), dict) else {}
    files = {
      "quarter_grid": self.repo_root / "python" / "client_intake_and_finmo" / "quarter_grid.py",
      "intake_consult": self.repo_root / "python" / "api_handlers" / "intake_consult.py",
    }
    text_by_file = {name: path.read_text(encoding="utf-8") for name, path in files.items() if path.exists()}
    for name, text in guidance.items():
      if isinstance(text, str) and text.strip():
        text_by_file[f"guidance_{name}"] = text
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
      command_error = ""
      if bundle.command_result is not None:
        command_error = "\n".join([
          str(bundle.command_result.stderr or "").strip(),
          str(bundle.command_result.stdout or "").strip(),
        ]).strip().lower()
      if "q1 cash anchor was not derived and applied coherently" in command_error:
        assessment.cash_too_tight = False
        assessment.levers_insufficient = False
        assessment.engine_overpowered = False
        assessment.recommendation = "Repair the Q1 cash-anchor derivation/application flow before evaluating downstream feasibility."
        return assessment
      if "planning_solver_failed" in command_error:
        assessment.cash_too_tight = True
        assessment.levers_insufficient = True
        assessment.engine_overpowered = True
        assessment.recommendation = "Treat this as a real planning failure and inspect the fresh run artifacts or backend error detail rather than stopping."
        return assessment
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

  def _action_key(self, action: FixAction) -> tuple:
    details = action.details or {}
    patch_kind = str(details.get("patch_kind") or "")
    return (
      str(action.target),
      patch_kind,
      str(details.get("old") or ""),
      str(details.get("needle") or ""),
      str(details.get("block") or ""),
      str(details.get("content") or "") if patch_kind == "rewrite_file" else "",
    )

  def _target_path(self, target: str) -> Path:
    normalized = str(target or "").replace("\\", "/").strip()
    if not normalized:
      raise RuntimeError("Unsupported fixer target: empty path")
    candidate = (self.repo_root / normalized).resolve()
    try:
      candidate.relative_to(self.repo_root)
    except ValueError as exc:
      raise RuntimeError(f"Fixer target must stay inside repo root: {target}") from exc
    return candidate

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

  def _apply_rewrite_file(self, *, file_path: Path, content: str) -> bool:
    if not file_path.exists():
      return False
    if not str(content or "").strip():
      return False
    existing = file_path.read_text(encoding="utf-8")
    if existing == content:
      return False
    file_path.write_text(content, encoding="utf-8")
    return True

  def _can_apply_action(self, action: FixAction) -> bool:
    details = action.details or {}
    patch_kind = str(details.get("patch_kind") or "").strip()
    try:
      file_path = self._target_path(action.target)
    except Exception:
      return False
    if not file_path.exists():
      return False
    text = file_path.read_text(encoding="utf-8")
    if patch_kind == "insert_after":
      needle = str(details.get("needle") or "")
      snippet = str(details.get("snippet") or "")
      return bool(needle and needle in text and snippet and snippet not in text)
    if patch_kind == "replace_once":
      old = str(details.get("old") or "")
      new = str(details.get("new") or "")
      return bool(old and old in text and new and new not in text)
    if patch_kind == "remove_block":
      block = str(details.get("block") or "")
      return bool(block and block in text)
    if patch_kind == "rewrite_file":
      content = details.get("content")
      return isinstance(content, str) and bool(content.strip()) and content != text
    return False

  def _dedupe_actions(self, actions: List[FixAction]) -> List[FixAction]:
    deduped: List[FixAction] = []
    seen = set()
    for action in actions:
      key = self._action_key(action)
      if key in seen:
        continue
      seen.add(key)
      deduped.append(action)
    return deduped

  def _apply_action(self, action: FixAction) -> bool:
    details = action.details or {}
    file_path = self._target_path(action.target)
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
    if patch_kind == "rewrite_file":
      return self._apply_rewrite_file(
        file_path=file_path,
        content=str(details.get("content") or ""),
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
        (
          "import compileall, pathlib; "
          "ok = compileall.compile_dir('python', quiet=1, force=False); "
          "print('OK imports' if ok else 'COMPILE_FAIL')"
        ),
      ],
      cwd=str(self.repo_root),
      env=env,
      text=True,
      capture_output=True,
    )
    return proc.returncode == 0

  def _read_file_safe(self, target: str) -> str:
    try:
      return self._target_path(target).read_text(encoding="utf-8")
    except Exception:
      return ""

  def _candidate_context_files(self, diagnosis: Diagnosis) -> List[str]:
    targets = [
      "python/client_intake_and_finmo/quarter_grid.py",
      "python/financial_model_engine/solver.py",
      "python/api_handlers/intake_consult.py",
      "Test Files/run_live_args_intake.py",
      "Test Files/run_dual_agent_intake.py",
    ]
    primary = str(diagnosis.primary_cause or "").strip().lower()
    if "anchor" in primary or "system_run_failed" in primary:
      targets.extend([
        "python/client_intake_and_finmo/intake_submission.py",
        "python/api_handlers/shared_context.py",
      ])
    if "solver" in primary:
      targets.extend([
        "python/financial_model_engine/finmo_model.py",
        "python/financial_model_engine/model_inputs.py",
      ])
    deduped: List[str] = []
    for item in targets:
      if item not in deduped:
        deduped.append(item)
    return deduped

  def _llm_actions(
    self,
    *,
    bundle: ArtifactBundle,
    diagnosis: Diagnosis,
    audit: PromptAudit,
    feasibility: FeasibilityAssessment,
    root_cause_only: bool,
    must_apply: bool = False,
    prior_no_fix_reason: str = "",
  ) -> List[FixAction]:
    api_key = str(os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
      return []
    try:
      from openai import OpenAI
    except Exception:
      return []

    likely_targets = self._candidate_context_files(diagnosis)
    context_files = {
      target: self._read_file_safe(target)[:30000]
      for target in likely_targets
      if self._read_file_safe(target)
    }
    guidance_text = bundle.agent_context.get("guidance_text") if isinstance(bundle.agent_context.get("guidance_text"), dict) else {}
    payload = {
      "draft_id": bundle.draft_id,
      "is_fresh_run": bundle.is_fresh_run,
      "agent_context": bundle.agent_context,
      "command_result": {
        "returncode": int(bundle.command_result.returncode) if bundle.command_result is not None else 0,
        "stdout_tail": str((bundle.command_result.stdout or "")[-4000:]) if bundle.command_result is not None else "",
        "stderr_tail": str((bundle.command_result.stderr or "")[-4000:]) if bundle.command_result is not None else "",
      },
      "diagnosis": diagnosis.to_dict(),
      "prompt_audit": audit.to_dict(),
      "feasibility": feasibility.to_dict(),
      "local_solver_summary": dict(bundle.local_solver_summary or {}),
      "authoritative_cash_bands_preview": list(bundle.authoritative_cash_bands[:6]),
      "local_solved_outputs_preview": list(bundle.local_solved_outputs[:6]),
      "root_cause_only": bool(root_cause_only),
      "context_files": context_files,
    }
    system_prompt = (
      "You are a dev-only repo repair agent for a financial planning application. "
      "Read the supplied playbook, critical context, app map, evaluation rules, persistent learnings, recent session summaries, artifacts, and code excerpts as authoritative context. "
      "Propose root-cause code edits to fix the planning/cash system. "
      "Prefer upstream fixes over bandaids. "
      "Treat solver as downstream unless the evidence clearly proves solver logic is the root issue. "
      "Preserve the current intended production shape: the runtime should use the original baby-AI plus grid-AI flow, "
      "with realistic P&L behavior and no reintroduction of deleted experimental cash-contract or capital-allocation AI modules unless absolutely necessary. "
      "You may modify any file inside the repo. "
      "Return strict JSON with shape "
      "{\"actions\":[{\"action_type\":\"llm_code_edit\",\"target\":\"repo/relative/path.py\","
      "\"summary\":\"...\",\"details\":{\"patch_kind\":\"rewrite_file|replace_once|insert_after|remove_block\","
      "\"content\":\"...full file text when rewrite_file...\",\"old\":\"...\",\"new\":\"...\",\"needle\":\"...\",\"snippet\":\"...\",\"block\":\"...\"},"
      "\"risk_level\":\"low|medium|high\",\"supported_for_auto_apply\":true}]}. "
      "You are allowed to rewrite entire files when necessary. "
      "Only include actions you expect to be applicable immediately. "
      "Do not suggest solver tuning if upstream root causes are present. "
      "Do not propose med-spa-specific hardcodes. "
      "Do not remove baseline visibility or realism context unless the evidence shows that exact prompt/payload authority is the root issue. "
      "Every returned action must be immediately applicable to the current file contents using the exact old/needle/block text you supply. "
      "For substantial logic changes, prefer rewrite_file so you can make real code edits instead of fragile anchor patches. "
      "Do not return speculative edits that will no-op."
    )
    if must_apply:
      system_prompt += (
        " The caller requires at least one immediately applicable root-cause edit before another paid rerun is allowed. "
        "Return only actions that can be applied to the current files right now."
      )
    user_prompt = json.dumps(payload, ensure_ascii=False)
    client = OpenAI(api_key=api_key)
    feedback = prior_no_fix_reason.strip()
    for _attempt in range(3 if must_apply else 1):
      try:
        prompt = user_prompt
        if feedback:
          prompt = user_prompt + "\n\nPrevious no-fix reason:\n" + feedback
        response = client.responses.create(
          model=str(os.getenv("OPENAI_DEV_AGENT_MODEL") or "gpt-5.1"),
          input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
          ],
        )
        raw = getattr(response, "output_text", "") or ""
        if not raw:
          continue
        parsed = json.loads(raw)
      except Exception:
        continue
      actions: List[FixAction] = []
      for item in parsed.get("actions") or []:
        if not isinstance(item, dict):
          continue
        target = str(item.get("target") or "").strip()
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        if not target or not details:
          continue
        try:
          self._target_path(target)
        except Exception:
          continue
        actions.append(
          FixAction(
            action_type=str(item.get("action_type") or "llm_code_edit"),
            target=target,
            summary=str(item.get("summary") or "LLM-generated code edit").strip(),
            details=details,
            risk_level=str(item.get("risk_level") or "medium").strip(),
            supported_for_auto_apply=bool(item.get("supported_for_auto_apply", True)),
          )
        )
      applicable = [action for action in self._dedupe_actions(actions) if self._can_apply_action(action)]
      if applicable:
        return applicable
      feedback = "The previous proposed edits were not immediately applicable to the current file contents. Return exact-match edits only."
    return []

  def run(
    self,
    *,
    bundle: ArtifactBundle,
    diagnosis: Diagnosis,
    audit: PromptAudit,
    feasibility: FeasibilityAssessment,
    apply: bool,
    allow_high_risk_fixes: bool = False,
    root_cause_only: bool = True,
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
    has_upstream_root_cause = bool(
      audit.prompt_leakage
      or audit.baseline_anchoring_detected
      or feasibility.cash_too_tight
      or feasibility.levers_insufficient
      or feasibility.engine_overpowered
      or diagnosis.primary_cause in {
        "capital allocation insufficient",
        "cash band too tight",
        "cash band too loose on downside",
      }
    )
    if not root_cause_only or not has_upstream_root_cause:
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
          supported_for_auto_apply=True,
        )
      )
    llm_actions = self._llm_actions(
      bundle=bundle,
      diagnosis=diagnosis,
      audit=audit,
      feasibility=feasibility,
      root_cause_only=root_cause_only,
    )
    result.actions.extend(llm_actions)
    result.actions = self._dedupe_actions(result.actions)
    result.actions = [action for action in result.actions if self._can_apply_action(action)]
    result.applicable_count = len(result.actions)
    if apply and result.applicable_count == 0:
      forced_llm_actions = self._llm_actions(
        bundle=bundle,
        diagnosis=diagnosis,
        audit=audit,
        feasibility=feasibility,
        root_cause_only=root_cause_only,
        must_apply=True,
        prior_no_fix_reason="No immediately applicable built-in or prior LLM fix was available for the current repo state.",
      )
      if forced_llm_actions:
        result.actions = self._dedupe_actions(forced_llm_actions)
        result.applicable_count = len(result.actions)
        result.change_log.append("Forced LLM repair mode produced at least one immediately applicable fix.")
    if apply and result.applicable_count == 0:
      result.no_fix_reason = "No immediately applicable root-cause fix was generated for the current repo state."
      result.change_log.append(result.no_fix_reason)
    if apply:
      applied_targets = [
        str(action.target)
        for action in result.actions
        if action.supported_for_auto_apply
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
        if self._apply_action(action):
          action.applied = True
          result.applied_count += 1
          if str(action.target) not in result.changed_files:
            result.changed_files.append(str(action.target))
          result.change_log.append(f"Applied {action.action_type} to {action.target}")
      if result.applied_count > 0 and not self._validate_imports():
        result.change_log.append("Import validation failed after applying fixes; restoring checkpoint.")
        if result.checkpoint_manifest:
          restored = restore_checkpoint(repo_root=self.repo_root, manifest_path=result.checkpoint_manifest)
          if restored:
            result.change_log.append("Restored files after failed validation: " + ", ".join(restored))
        for action in result.actions:
          if action.applied:
            action.applied = False
        result.applied_count = 0
        result.changed_files = []
        result.no_fix_reason = "Applied fixes failed validation and were restored from checkpoint."
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
        result.moved_failure = f"Q{prev_q} -> Q{cur_q}"
      elif cur_q < prev_q:
        result.regressed = True
        result.moved_failure = f"Q{prev_q} -> Q{cur_q}"
    if previous_diag.max_violation and current_diag.max_violation < previous_diag.max_violation:
      result.improved = True
    elif previous_diag.max_violation and current_diag.max_violation > previous_diag.max_violation:
      result.regressed = True
    result.shape_change = f"{previous_shape} -> {current_shape}" if previous_shape and previous_shape != current_shape else current_shape
    return result
