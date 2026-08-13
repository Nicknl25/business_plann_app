# -*- coding: utf-8 -*-
"""DEPRECATED - superseded by legs.py.

The known-break replays moved into the leg registry so every pinned bug
carries its own fix commit and broken baseline and can be proved
individually. Import from .legs instead.
"""
from .legs import REGRESSIONS  # noqa: F401

REGISTRY = REGRESSIONS
