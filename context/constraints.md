# Constraints

## Hard Rules

### 1. Baby AI Cannot Prescribe Or Override
- Baby AI is advisory only.
- It may identify realism issues.
- It may not recommend fixes, rewrite facts, override the client, or control the planner.

### 2. Grid Logic Must Not Be Changed
- The grid is the contract between AI reasoning and direct model writes.
- Do not casually alter row semantics, controller-write mapping, or band logic.
- Changes here can silently break the whole planning system.

### 3. Direct Recalculation Enforces Realism
- The financial model recalculates immediately after exact driver writes.
- If a plan sounds good but the recalculated model breaks reality, the answer is to fix inputs or upstream assumptions.
- Do not bypass recalculated financial outputs with narrative or manual overrides.

### 4. No Reintroduction Of Heavy Closeout Logic
- Do not rebuild a large closeout governor, override engine, or controller layer.
- Do not add another AI that tries to centrally arbitrate everything.
- Keep validation light, targeted, and subordinate to the main pipeline.

## Design Implications
- Context can influence planning.
- Only the responsible layer should own decisions.
- Writing must reflect solved reality, not replace it.
