"""Mneme — core do cérebro persistente (Markdown/YAML + Git).

Este pacote é desacoplado de qualquer harness: Hermes, OpenClaw, Claude Code, Codex
e Cursor usam a mesma CLI (`system/scripts/brain.py`) ou importam estes módulos.
"""

from __future__ import annotations

__all__ = [
    "actions",
    "classify",
    "config",
    "context_compiler",
    "index",
    "migrate_hermes",
    "models",
    "organize",
    "projects",
    "routing",
    "store",
    "timeline",
    "validate",
]
