# Phase 2 Conflict Rules

## Purpose

Define how the four-agent planner resolves conflicts without devolving into advisory mush.

## Core principle

`grid_agent` is the final integrator, not an unconstrained dictator.

It owns the final grid, but it may not ignore binding specialist outputs.

## Binding hierarchy

### 1. Hard invariants

Always binding:
- solver contract
- row ids
- row meanings
- min/max semantics
- quarter count
- no legacy planner dependencies

### 2. Specialist vetoes

Binding unless the specialist output is revised in the same run:
- realism vetoes
- operations vetoes
- capital vetoes

`grid_agent` may not overrule a veto by itself.

### 3. Specialist constraints

Binding planning rules that must be satisfied together where possible.

### 4. Specialist implications

Expected row-level and quarter-level consequences that inform the final grid.

## Conflict-resolution procedure

1. `grid_agent` receives the three specialist outputs.
2. `grid_agent` checks for direct contradictions.
3. If no contradiction exists, it builds the final grid under all constraints.
4. If contradictions exist, `grid_agent` must record them explicitly.
5. If a valid integrated plan still cannot be built, the planner must return blocked status rather than silently weakening constraints.

## Not allowed

- averaging contradictory guidance into a mushy compromise
- ignoring a specialist veto
- returning a grid that violates a binding specialist constraint
- returning a narrative that claims alignment while the rows disagree

## Examples of blocker categories

- realism vs operations contradiction
- operations vs capital contradiction
- realism vs capital contradiction
- no believable deployment mechanism for the selected strategy
- business-type realism and selected strategy cannot both be satisfied under current facts

## Required grid-agent self-check

Before final output, `grid_agent` must explicitly check:
- realism satisfied
- operations satisfied
- capital strategy satisfied
- row coherence satisfied
- solver contract preserved

If any are false, the output must explain why.

