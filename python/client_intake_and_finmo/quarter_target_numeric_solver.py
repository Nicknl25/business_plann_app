"""Compatibility shim for the canonical numeric solver.

This module is retained temporarily so any lingering imports do not create a
second numeric engine. All real numeric fitting now lives in numeric_solver.py.
"""

from __future__ import annotations

try:
  from client_intake_and_finmo.numeric_solver import solve_review_plan  # type: ignore
except Exception:
  from numeric_solver import solve_review_plan  # type: ignore

__all__ = ["solve_review_plan"]