from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional

from .capital_agent import CapitalAgent
from .grid_agent import GridAgent
from .operations_agent import OperationsAgent
from .realism_agent import RealismAgent
from .run_payload import build_app_agents_run_payload
from .schema_loader import load_schema
from .schema_validation import validate_data_against_schema
from .shared_context import build_shared_context
from .validation import evaluate_app_agents_run


class AppAgentsPlanner:
  def __init__(
    self,
    *,
    realism_agent: Optional[RealismAgent] = None,
    operations_agent: Optional[OperationsAgent] = None,
    capital_agent: Optional[CapitalAgent] = None,
    grid_agent: Optional[GridAgent] = None,
    trace_callback: Optional[Callable[[Dict[str, str]], None]] = None,
    snapshot_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
  ) -> None:
    self.realism_agent = realism_agent or RealismAgent()
    self.operations_agent = operations_agent or OperationsAgent()
    self.capital_agent = capital_agent or CapitalAgent()
    self.grid_agent = grid_agent or GridAgent()
    self.trace_callback = trace_callback
    self.snapshot_callback = snapshot_callback
    self.execution_trace: List[Dict[str, str]] = []

  def _build_grid_revision_directive(
    self,
    *,
    shared_context: Dict[str, Any],
    realism_output: Dict[str, Any],
    operations_output: Dict[str, Any],
    capital_output: Dict[str, Any],
    blocked_grid_output: Dict[str, Any],
    quality_gate: Optional[Dict[str, Any]] = None,
  ) -> str:
    business_name = str((((shared_context.get("contract") or {}) if isinstance(shared_context.get("contract"), dict) else {}).get("business_name")) or "").strip()
    business_type = str((((shared_context.get("business_profile") or {}) if isinstance(shared_context.get("business_profile"), dict) else {}).get("business_type")) or "").strip()
    strategy_label = str((((shared_context.get("strategy_profile") or {}) if isinstance(shared_context.get("strategy_profile"), dict) else {}).get("cash_strategy_label")) or "").strip()
    mechanics = (shared_context.get("business_mechanics") or {}) if isinstance(shared_context.get("business_mechanics"), dict) else {}
    blocking_conflicts = [str(item or "").strip() for item in (((blocked_grid_output.get("blocking_conflicts") or []) if isinstance(blocked_grid_output, dict) else [])) if str(item or "").strip()]

    def _collect_row_ids(payload: Dict[str, Any]) -> List[str]:
      rows: List[str] = []
      for item in (payload.get("must_change_rows") or []):
        if not isinstance(item, dict):
          continue
        row_id = str(item.get("row_id") or "").strip()
        if row_id and row_id not in rows:
          rows.append(row_id)
      for item in (payload.get("row_implications") or []):
        if not isinstance(item, dict):
          continue
        row_id = str(item.get("row_id") or "").strip()
        if row_id and row_id not in rows:
          rows.append(row_id)
      for item in (payload.get("constraints") or []):
        if not isinstance(item, dict):
          continue
        for row_id_raw in item.get("affected_rows") or []:
          row_id = str(row_id_raw or "").strip()
          if row_id and row_id not in rows:
            rows.append(row_id)
      return rows

    def _collect_review_revisions(payload: Dict[str, Any]) -> List[str]:
      out: List[str] = []
      draft_review = payload.get("draft_review") if isinstance(payload.get("draft_review"), dict) else {}
      for item in (draft_review.get("required_revisions") or []):
        if not isinstance(item, dict):
          continue
        row_id = str(item.get("row_id") or "").strip()
        change = str(item.get("required_change") or "").strip()
        reason = str(item.get("business_reason") or "").strip()
        urgency = str(item.get("urgency") or "").strip()
        snippet = f"{row_id}: {change}"
        if urgency:
          snippet += f" [{urgency}]"
        if reason:
          snippet += f" because {reason}"
        if snippet.strip():
          out.append(snippet.strip())
      return out

    realism_rows = _collect_row_ids(realism_output)
    operations_rows = _collect_row_ids(operations_output)
    capital_rows = _collect_row_ids(capital_output)
    all_rows: List[str] = []
    for row_id in realism_rows + operations_rows + capital_rows:
      if row_id not in all_rows:
        all_rows.append(row_id)

    lines = [
      f"Revision pass for {business_name or 'this business'} ({business_type or 'unknown type'}) under {strategy_label or 'unknown strategy'}.",
      "Your first pass blocked. You must now revise the grid bands instead of restating the conflict labels.",
      "Preserve solver contract and row ids, but change the quarter bands for the rows needed to satisfy the specialist constraints together.",
    ]
    planning_mode = str(mechanics.get("planning_mode") or "").strip()
    planning_mode_reason = str(mechanics.get("planning_mode_reason") or "").strip()
    if planning_mode:
      lines.append(f"Business-mechanics planning mode: {planning_mode}.")
    if planning_mode_reason:
      lines.append(planning_mode_reason)
    if blocking_conflicts:
      lines.append("Blocking conflicts to resolve: " + "; ".join(blocking_conflicts))
    if all_rows:
      lines.append("Most relevant rows from specialist outputs: " + ", ".join(all_rows[:30]))
    review_revisions: List[str] = []
    for payload in (realism_output, operations_output, capital_output):
      review_revisions.extend(_collect_review_revisions(payload))
    if review_revisions:
      lines.append("Specialist review revisions: " + "; ".join(review_revisions[:25]))
    capital_signature = capital_output.get("strategy_signature") if isinstance(capital_output.get("strategy_signature"), dict) else {}
    if capital_signature:
      signature_bits: List[str] = []
      for key in (
        "selected_strategy",
        "liquidity_posture",
        "cash_shape_rule",
        "cash_monotonicity_expectation",
      ):
        value = str(capital_signature.get(key) or "").strip()
        if value:
          signature_bits.append(f"{key}={value}")
      primary_rows = [str(item or "").strip() for item in (capital_signature.get("primary_deployment_rows") or []) if str(item or "").strip()]
      secondary_rows = [str(item or "").strip() for item in (capital_signature.get("secondary_deployment_rows") or []) if str(item or "").strip()]
      protected_rows = [str(item or "").strip() for item in (capital_signature.get("protected_rows") or []) if str(item or "").strip()]
      forbidden_patterns = [str(item or "").strip() for item in (capital_signature.get("forbidden_patterns") or []) if str(item or "").strip()]
      if signature_bits:
        lines.append("Capital strategy signature: " + "; ".join(signature_bits))
      if primary_rows:
        lines.append("Capital primary deployment rows: " + ", ".join(primary_rows[:12]))
      if secondary_rows:
        lines.append("Capital secondary deployment rows: " + ", ".join(secondary_rows[:12]))
      if protected_rows:
        lines.append("Capital protected rows: " + ", ".join(protected_rows[:12]))
      if forbidden_patterns:
        lines.append("Capital forbidden patterns: " + "; ".join(forbidden_patterns[:10]))
    capital_phases = capital_output.get("capital_phases") if isinstance(capital_output.get("capital_phases"), list) else []
    phase_lines: List[str] = []
    for item in capital_phases[:4]:
      if not isinstance(item, dict):
        continue
      phase_id = str(item.get("phase_id") or "").strip()
      quarter_start = str(item.get("quarter_start") or "").strip()
      quarter_end = str(item.get("quarter_end") or "").strip()
      cash_posture = str(item.get("cash_posture") or "").strip()
      financing_posture = str(item.get("financing_posture") or "").strip()
      deployment_rows = [str(row_id or "").strip() for row_id in (item.get("deployment_priority_rows") or []) if str(row_id or "").strip()]
      explanation = str(item.get("explanation") or "").strip()
      snippet = f"{phase_id or 'phase'} Q{quarter_start}-Q{quarter_end}: cash={cash_posture}"
      if financing_posture:
        snippet += f"; financing={financing_posture}"
      if deployment_rows:
        snippet += f"; deploy={', '.join(deployment_rows[:8])}"
      if explanation:
        snippet += f"; why={explanation}"
      phase_lines.append(snippet)
    if phase_lines:
      lines.append("Capital phase plan: " + " | ".join(phase_lines))
    quality_issues = self._quality_gate_issues(quality_gate)
    if quality_issues:
      lines.append("Deterministic planner quality failures: " + "; ".join(quality_issues[:20]))
    pressure_points = [str(item or "").strip() for item in (mechanics.get("baseline_pressure_points") or []) if str(item or "").strip()]
    if pressure_points:
      lines.append("Business pressure points: " + "; ".join(pressure_points[:10]))
    interaction_rules = mechanics.get("interaction_rules") if isinstance(mechanics.get("interaction_rules"), list) else []
    if interaction_rules:
      summarized_rules = []
      for item in interaction_rules[:8]:
        if not isinstance(item, dict):
          continue
        description = str(item.get("description") or "").strip()
        required_rows = [str(row_id or "").strip() for row_id in (item.get("required_rows") or []) if str(row_id or "").strip()]
        if description:
          if required_rows:
            summarized_rules.append(f"{description} Required rows: {', '.join(required_rows[:10])}")
          else:
            summarized_rules.append(description)
      if summarized_rules:
        lines.append("Business interaction rules: " + "; ".join(summarized_rules))
    lines.extend(
      [
        "If utilization or growth is strong, marketing and support rows must not stay flat.",
        "If the business has a growth story, Revenue and at least one core revenue driver group must visibly move.",
        "If the strategy is reinvest or balanced, capital deployment rows must visibly move when excess cash builds.",
        "If scaling requires labor or support, payroll and operating support rows must move with it.",
        "If growth changes cash conversion, working-capital and tax-sensitive rows must reflect that.",
        "Flat 20-quarter rows are presumed wrong unless the business logic clearly justifies staying flat.",
        "Do not let the narrative claim change while the key driver rows remain basically unchanged.",
        "Only return blocked if you truly cannot resolve the conflict set with legal row-band changes.",
      ]
    )
    return "\n".join(lines)

  def _has_review_failures(self, *payloads: Dict[str, Any]) -> bool:
    for payload in payloads:
      draft_review = payload.get("draft_review") if isinstance(payload.get("draft_review"), dict) else {}
      failures = [str(item or "").strip() for item in (draft_review.get("failures") or []) if str(item or "").strip()]
      required_revisions = [item for item in (draft_review.get("required_revisions") or []) if isinstance(item, dict)]
      if failures or required_revisions:
        return True
    return False

  def _quality_gate_issues(self, quality_gate: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(quality_gate, dict):
      return []
    issues: List[str] = []
    for key in ("strategy_visibility", "staircase_risk", "row_coherence", "business_mechanics"):
      section = quality_gate.get(key) if isinstance(quality_gate.get(key), dict) else {}
      for item in (section.get("issues") or []):
        text = str(item or "").strip()
        if text and text not in issues:
          issues.append(text)
    return issues

  def _evaluate_quality_gate(
    self,
    *,
    shared_context: Dict[str, Any],
    realism_output: Dict[str, Any],
    operations_output: Dict[str, Any],
    capital_output: Dict[str, Any],
    grid_output: Dict[str, Any],
  ) -> Dict[str, Any]:
    payload = build_app_agents_run_payload(
      shared_context=shared_context,
      realism_agent=realism_output,
      operations_agent=operations_output,
      capital_agent=capital_output,
      grid_agent=grid_output,
      execution_trace=self.execution_trace,
    )
    scenario_id = str((((shared_context.get("contract") or {}) if isinstance(shared_context.get("contract"), dict) else {}).get("draft_id")) or "live").strip() or "live"
    return evaluate_app_agents_run(
      scenario_id=scenario_id,
      shared_context=shared_context,
      app_agents_run_json=payload,
    )

  def _force_quality_block(self, *, grid_output: Dict[str, Any], quality_gate: Dict[str, Any]) -> Dict[str, Any]:
    blocked = copy.deepcopy(grid_output or {})
    issues = self._quality_gate_issues(quality_gate)
    blocked["planner_status"] = "blocked"
    existing = [str(item or "").strip() for item in (blocked.get("blocking_conflicts") or []) if str(item or "").strip()]
    for issue in issues:
      if issue not in existing:
        existing.append(issue)
    blocked["blocking_conflicts"] = existing
    summary = str(blocked.get("summary") or "").strip()
    quality_summary = "Planner quality gate rejected the grid because it remained too flat or incoherent: " + "; ".join(issues[:8])
    blocked["summary"] = quality_summary if not summary else f"{quality_summary} Existing grid summary: {summary}"
    self_check = blocked.get("self_check") if isinstance(blocked.get("self_check"), dict) else {}
    self_check["row_coherence_satisfied"] = False
    self_check["capital_satisfied"] = False
    blocked["self_check"] = {
      "realism_satisfied": bool(self_check.get("realism_satisfied")),
      "operations_satisfied": bool(self_check.get("operations_satisfied")),
      "capital_satisfied": bool(self_check.get("capital_satisfied")),
      "row_coherence_satisfied": bool(self_check.get("row_coherence_satisfied")),
      "solver_contract_preserved": bool(self_check.get("solver_contract_preserved") if "solver_contract_preserved" in self_check else True),
    }
    return blocked

  def _review_specialist_outputs(
    self,
    *,
    shared_context: Dict[str, Any],
    realism_output: Dict[str, Any],
    operations_output: Dict[str, Any],
    capital_output: Dict[str, Any],
    grid_output: Dict[str, Any],
  ) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    reviewed_realism = realism_output
    reviewed_operations = operations_output
    reviewed_capital = capital_output

    self._emit_trace(event="specialist_review_round", status="started", component="planner")

    try:
      reviewed_realism = self.realism_agent.generate(
        shared_context=shared_context,
        draft_grid_output=grid_output,
        review_mode=True,
        prior_output=realism_output,
      )
      self._validate_specialist("realism_agent_output.schema.json", reviewed_realism)
      self._emit_trace(event="realism_review", status="completed", component="realism_agent")
    except Exception as exc:
      self._emit_trace(event="realism_review", status="failed", component="realism_agent", detail=str(exc))

    try:
      reviewed_operations = self.operations_agent.generate(
        shared_context=shared_context,
        draft_grid_output=grid_output,
        review_mode=True,
        prior_output=operations_output,
      )
      self._validate_specialist("operations_agent_output.schema.json", reviewed_operations)
      self._emit_trace(event="operations_review", status="completed", component="operations_agent")
    except Exception as exc:
      self._emit_trace(event="operations_review", status="failed", component="operations_agent", detail=str(exc))

    try:
      reviewed_capital = self.capital_agent.generate(
        shared_context=shared_context,
        draft_grid_output=grid_output,
        review_mode=True,
        prior_output=capital_output,
      )
      self._validate_specialist("capital_agent_output.schema.json", reviewed_capital)
      self._emit_trace(event="capital_review", status="completed", component="capital_agent")
    except Exception as exc:
      self._emit_trace(event="capital_review", status="failed", component="capital_agent", detail=str(exc))

    self._emit_trace(event="specialist_review_round", status="completed", component="planner")
    return reviewed_realism, reviewed_operations, reviewed_capital

  def _emit_trace(self, *, event: str, status: str, component: str = "", detail: str = "") -> None:
    payload = {
      "event": str(event or "").strip(),
      "status": str(status or "").strip(),
      "component": str(component or "").strip(),
      "detail": str(detail or "").strip(),
    }
    self.execution_trace.append(payload)
    if self.trace_callback is not None:
      self.trace_callback(dict(payload))

  def _emit_snapshot(
    self,
    *,
    shared_context: Optional[Dict[str, Any]] = None,
    realism_output: Optional[Dict[str, Any]] = None,
    operations_output: Optional[Dict[str, Any]] = None,
    capital_output: Optional[Dict[str, Any]] = None,
    grid_output: Optional[Dict[str, Any]] = None,
    planner_status: str = "running",
  ) -> None:
    if self.snapshot_callback is None:
      return
    payload: Dict[str, Any] = {
      "contract_version": "in_progress",
      "planner_status": str(planner_status or "running").strip() or "running",
      "execution_trace": [dict(item) for item in self.execution_trace],
    }
    if isinstance(shared_context, dict):
      payload["shared_context"] = copy.deepcopy(shared_context)
    if isinstance(realism_output, dict):
      payload["realism_agent"] = copy.deepcopy(realism_output)
    if isinstance(operations_output, dict):
      payload["operations_agent"] = copy.deepcopy(operations_output)
    if isinstance(capital_output, dict):
      payload["capital_agent"] = copy.deepcopy(capital_output)
    if isinstance(grid_output, dict):
      payload["grid_agent"] = copy.deepcopy(grid_output)
    self.snapshot_callback(payload)

  def build_shared_context(self, **kwargs: Any) -> Dict[str, Any]:
    self._emit_trace(event="shared_context_build", status="started", component="shared_context")
    try:
      context = build_shared_context(**kwargs)
      self._validate_shared_context(context)
    except Exception as exc:
      self._emit_trace(
        event="shared_context_build",
        status="failed",
        component="shared_context",
        detail=str(exc),
      )
      raise
    self._emit_trace(event="shared_context_build", status="completed", component="shared_context")
    self._emit_snapshot(shared_context=context, planner_status="running")
    return context

  def run(
    self,
    *,
    shared_context: Dict[str, Any],
    realism_override: Optional[Dict[str, Any]] = None,
    operations_override: Optional[Dict[str, Any]] = None,
    capital_override: Optional[Dict[str, Any]] = None,
    grid_override: Optional[Dict[str, Any]] = None,
  ) -> Dict[str, Any]:
    self.execution_trace = []
    self._emit_trace(event="planner_run", status="started", component="planner")
    self._validate_shared_context(shared_context)
    self._emit_trace(event="shared_context_validate", status="completed", component="shared_context")
    self._emit_snapshot(shared_context=shared_context, planner_status="running")

    self._emit_trace(event="realism_agent", status="started", component="realism_agent")
    try:
      realism_output = copy.deepcopy(realism_override) if isinstance(realism_override, dict) else self.realism_agent.generate(shared_context=shared_context)
      self._validate_specialist("realism_agent_output.schema.json", realism_output)
    except Exception as exc:
      self._emit_trace(event="realism_agent", status="failed", component="realism_agent", detail=str(exc))
      self._emit_snapshot(shared_context=shared_context, planner_status="failed")
      raise
    self._emit_trace(event="realism_agent", status="completed", component="realism_agent")
    self._emit_snapshot(
      shared_context=shared_context,
      realism_output=realism_output,
      planner_status="running",
    )

    self._emit_trace(event="operations_agent", status="started", component="operations_agent")
    try:
      operations_output = copy.deepcopy(operations_override) if isinstance(operations_override, dict) else self.operations_agent.generate(shared_context=shared_context)
      self._validate_specialist("operations_agent_output.schema.json", operations_output)
    except Exception as exc:
      self._emit_trace(event="operations_agent", status="failed", component="operations_agent", detail=str(exc))
      self._emit_snapshot(
        shared_context=shared_context,
        realism_output=realism_output,
        planner_status="failed",
      )
      raise
    self._emit_trace(event="operations_agent", status="completed", component="operations_agent")
    self._emit_snapshot(
      shared_context=shared_context,
      realism_output=realism_output,
      operations_output=operations_output,
      planner_status="running",
    )

    self._emit_trace(event="capital_agent", status="started", component="capital_agent")
    try:
      capital_output = copy.deepcopy(capital_override) if isinstance(capital_override, dict) else self.capital_agent.generate(shared_context=shared_context)
      self._validate_specialist("capital_agent_output.schema.json", capital_output)
    except Exception as exc:
      self._emit_trace(event="capital_agent", status="failed", component="capital_agent", detail=str(exc))
      self._emit_snapshot(
        shared_context=shared_context,
        realism_output=realism_output,
        operations_output=operations_output,
        planner_status="failed",
      )
      raise
    self._emit_trace(event="capital_agent", status="completed", component="capital_agent")
    self._emit_snapshot(
      shared_context=shared_context,
      realism_output=realism_output,
      operations_output=operations_output,
      capital_output=capital_output,
      planner_status="running",
    )

    self._emit_trace(event="grid_agent", status="started", component="grid_agent")
    try:
      grid_output = (
        copy.deepcopy(grid_override)
        if isinstance(grid_override, dict)
        else self.grid_agent.generate(
          shared_context=shared_context,
          realism_agent_output=realism_output,
          operations_agent_output=operations_output,
          capital_agent_output=capital_output,
        )
      )
      self._validate_specialist("grid_agent_output.schema.json", grid_output)
    except Exception as exc:
      self._emit_trace(event="grid_agent", status="failed", component="grid_agent", detail=str(exc))
      self._emit_snapshot(
        shared_context=shared_context,
        realism_output=realism_output,
        operations_output=operations_output,
        capital_output=capital_output,
        planner_status="failed",
      )
      raise
    self._emit_trace(event="grid_agent", status="completed", component="grid_agent")
    self._emit_snapshot(
      shared_context=shared_context,
      realism_output=realism_output,
      operations_output=operations_output,
      capital_output=capital_output,
      grid_output=grid_output,
      planner_status=str((grid_output or {}).get("planner_status") or "running"),
    )

    quality_gate = self._evaluate_quality_gate(
      shared_context=shared_context,
      realism_output=realism_output,
      operations_output=operations_output,
      capital_output=capital_output,
      grid_output=grid_output,
    )

    if not isinstance(grid_override, dict):
      needs_review = (
        str((grid_output or {}).get("planner_status") or "").strip().lower() == "blocked"
        or not bool(quality_gate.get("overall_pass"))
      )
      if needs_review:
        reviewed_realism, reviewed_operations, reviewed_capital = self._review_specialist_outputs(
          shared_context=shared_context,
          realism_output=realism_output,
          operations_output=operations_output,
          capital_output=capital_output,
          grid_output=grid_output,
        )
        realism_output = reviewed_realism
        operations_output = reviewed_operations
        capital_output = reviewed_capital
        quality_gate = self._evaluate_quality_gate(
          shared_context=shared_context,
          realism_output=realism_output,
          operations_output=operations_output,
          capital_output=capital_output,
          grid_output=grid_output,
        )
        self._emit_snapshot(
          shared_context=shared_context,
          realism_output=realism_output,
          operations_output=operations_output,
          capital_output=capital_output,
          grid_output=grid_output,
          planner_status=str((grid_output or {}).get("planner_status") or "running"),
        )

      needs_final_revision = (
        not bool(quality_gate.get("overall_pass"))
        or str((grid_output or {}).get("planner_status") or "").strip().lower() == "blocked"
        or self._has_review_failures(realism_output, operations_output, capital_output)
      )
      if needs_final_revision:
        self._emit_trace(
          event="grid_agent_reconciliation",
          status="started",
          component="grid_agent",
          detail="single_pass | " + " | ".join(self._quality_gate_issues(quality_gate)[:4]),
        )
        revision_directive = self._build_grid_revision_directive(
          shared_context=shared_context,
          realism_output=realism_output,
          operations_output=operations_output,
          capital_output=capital_output,
          blocked_grid_output=grid_output,
          quality_gate=quality_gate,
        )
        try:
          revised_grid_output = self.grid_agent.generate(
            shared_context=shared_context,
            realism_agent_output=realism_output,
            operations_agent_output=operations_output,
            capital_agent_output=capital_output,
            previous_grid_output=grid_output,
            revision_directive=revision_directive,
          )
          self._validate_specialist("grid_agent_output.schema.json", revised_grid_output)
          grid_output = revised_grid_output
          quality_gate = self._evaluate_quality_gate(
            shared_context=shared_context,
            realism_output=realism_output,
            operations_output=operations_output,
            capital_output=capital_output,
            grid_output=grid_output,
          )
          self._emit_trace(
            event="grid_agent_reconciliation",
            status="completed",
            component="grid_agent",
            detail=str((grid_output or {}).get("planner_status") or ""),
          )
          self._emit_snapshot(
            shared_context=shared_context,
            realism_output=realism_output,
            operations_output=operations_output,
            capital_output=capital_output,
            grid_output=grid_output,
            planner_status=str((grid_output or {}).get("planner_status") or "running"),
          )
        except Exception as exc:
          self._emit_trace(
            event="grid_agent_reconciliation",
            status="failed",
            component="grid_agent",
            detail=str(exc),
          )

      if bool((grid_output or {}).get("planner_status") == "ready") and not bool(quality_gate.get("overall_pass")):
        grid_output = self._force_quality_block(grid_output=grid_output, quality_gate=quality_gate)
        self._emit_trace(
          event="planner_quality_gate",
          status="blocked",
          component="planner",
          detail=" | ".join(self._quality_gate_issues(quality_gate)[:6]),
        )
        self._emit_snapshot(
          shared_context=shared_context,
          realism_output=realism_output,
          operations_output=operations_output,
          capital_output=capital_output,
          grid_output=grid_output,
          planner_status="blocked",
        )

    payload = build_app_agents_run_payload(
      shared_context=shared_context,
      realism_agent=realism_output,
      operations_agent=operations_output,
      capital_agent=capital_output,
      grid_agent=grid_output,
      execution_trace=self.execution_trace,
    )
    self._validate_run_payload(payload)
    self._emit_trace(
      event="planner_run",
      status="completed",
      component="planner",
      detail=str(payload.get("planner_status") or ""),
    )
    self._emit_snapshot(
      shared_context=shared_context,
      realism_output=realism_output,
      operations_output=operations_output,
      capital_output=capital_output,
      grid_output=grid_output,
      planner_status=str(payload.get("planner_status") or "running"),
    )
    return payload

  def _validate_shared_context(self, shared_context: Dict[str, Any]) -> None:
    schema = load_schema("shared_context.schema.json")
    errors = validate_data_against_schema(data=shared_context, schema=schema)
    if errors:
      raise ValueError("shared_context validation failed: " + " | ".join(errors[:12]))

  def _validate_specialist(self, schema_file: str, payload: Dict[str, Any]) -> None:
    schema = load_schema(schema_file)
    errors = validate_data_against_schema(data=payload, schema=schema)
    if errors:
      raise ValueError(f"{schema_file} validation failed: " + " | ".join(errors[:12]))

  def _validate_run_payload(self, payload: Dict[str, Any]) -> None:
    schema = load_schema("app_agents_run.schema.json")
    errors = validate_data_against_schema(data=payload, schema=schema)
    if errors:
      raise ValueError("app_agents_run.schema.json validation failed: " + " | ".join(errors[:12]))
