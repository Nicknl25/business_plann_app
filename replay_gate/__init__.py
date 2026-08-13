# -*- coding: utf-8 -*-
"""Replay gate - a fast regression gate that runs BEFORE a full persona E2E.

Separate from the persona-run app on purpose: it seeds its own throwaway
drafts and never touches the naive full runs.
"""
__all__ = ["run_gate"]
