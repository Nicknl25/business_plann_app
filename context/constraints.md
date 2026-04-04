# Constraints

## Hard Rules

### 1. Baby AI Cannot Prescribe Or Override
- Baby AI is advisory only.
- It may identify realism issues.
- It may not recommend fixes, rewrite facts, override the client, or control the planner.

### 2. Grid Logic Must Not Be Changed
- The grid is the contract between AI reasoning and solver enforcement.
- Do not casually alter row semantics, controller-write mapping, or band logic.
- Changes here can silently break the whole planning system.

### 3. Solver Enforces Realism
- The solver is the final feasibility check.
- If a plan sounds good but fails solver reality, the answer is to fix inputs, constraints, or upstream assumptions.
- Do not bypass solver pressure with narrative or manual overrides.

### 4. No Reintroduction Of Heavy Consistency Logic
- Do not rebuild a large consistency governor, override engine, or controller layer.
- Do not add another AI that tries to centrally arbitrate everything.
- Keep validation light, targeted, and subordinate to the main pipeline.

## Design Implications
- Context can influence planning.
- Only the responsible layer should own decisions.
- Writing must reflect solved reality, not replace it.
