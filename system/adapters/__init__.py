"""Adapters: ligam o core do Mneme a um harness específico.

V1: Hermes (perfil dev). Preparado para OpenClaw, Claude Code, Codex, Cursor e MCP genérico.
O core não importa nenhum adapter: a dependência aponta sempre do adapter para o core.
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Any

__all__ = ["HarnessAdapter", "GenericAdapter", "HermesAdapter", "get_adapter", "ADAPTERS"]


class HarnessAdapter(abc.ABC):
    name = "abstract"

    def __init__(self, hermes_home: str | None = None):
        self.hermes_home = hermes_home

    @abc.abstractmethod
    def capabilities(self) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def describe(self) -> dict[str, Any]:
        raise NotImplementedError


class GenericAdapter(HarnessAdapter):
    """Harness genérico: só a CLI, sem hooks nem caminhos conhecidos."""

    name = "generic"

    def capabilities(self) -> dict[str, Any]:
        return {
            "harness": self.name,
            "hooks": [],
            "skills_dir": None,
            "mcp_clients": ["cli"],
            "notes": "Use system/scripts/brain.py diretamente ou via MCP genérico.",
        }

    def describe(self) -> dict[str, Any]:
        return {"harness": self.name, "home": self.hermes_home}


class HermesAdapter(HarnessAdapter):
    """Adapter do Hermes: descobre home, perfil, skills, hooks, cron e MCP."""

    name = "hermes"

    def __init__(self, hermes_home: str | None = None, skills_dir: str | None = None):
        import os
        from pathlib import Path

        self.hermes_home = str(Path(hermes_home or os.environ.get("HERMES_HOME") or Path.home() / ".hermes"))
        self.declared_home = skills_dir

    def _home(self):
        from pathlib import Path

        return Path(self.hermes_home)

    def capabilities(self) -> dict[str, Any]:
        home = self._home()
        declared = getattr(self, "declared_home", None)
        skills_dir = Path(declared) if declared else home / "skills"
        hooks_dir = home / "hooks"
        cron_dir = home / "cron"
        return {
            "harness": self.name,
            "home": str(home),
            "hooks": [
                hook
                for hook, exists in (
                    ("after_message", hooks_dir.is_dir()),
                    ("after_session", hooks_dir.is_dir()),
                    ("after_git_commit", True),
                    ("daily_maintenance", cron_dir.is_dir()),
                )
                if exists
            ],
            "hooks_dir": str(hooks_dir) if hooks_dir.is_dir() else None,
            "cron_dir": str(cron_dir) if cron_dir.is_dir() else None,
            "skills_dir": str(skills_dir),
            "skills_dir_visible": Path(skills_dir).is_dir(),
            "declared_skills_dir": str(skills_dir) if declared else None,
            "brain_manager_installed": (Path(skills_dir) / "brain-manager" / "SKILL.md").is_file(),
            "mcp_clients": ["mcp"],
        }

    def describe(self) -> dict[str, Any]:
        return self.capabilities()

    # -- integrações opcionais -------------------------------------------------
    def install_skill(self, source_dir: str, target_name: str = "brain-manager") -> dict[str, Any]:
        import shutil
        from pathlib import Path

        source = Path(source_dir)
        target = self._home() / "skills" / target_name
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "SKILL.md", target / "SKILL.md")
        for folder in ("schemas", "scripts", "templates"):
            origin = source / folder
            if origin.is_dir():
                shutil.copytree(origin, target / folder, dirs_exist_ok=True)
        return {"ok": True, "target": str(target)}


ADAPTERS: dict[str, type[HarnessAdapter]] = {
    "hermes": HermesAdapter,
    "generic": GenericAdapter,
}


def get_adapter(name: str = "hermes", hermes_home: str | None = None, skills_dir: str | None = None) -> HarnessAdapter:
    # OpenClaw / Claude Code / Codex / Cursor ainda não têm adapter próprio:
    # até existir, usam o genérico com a mesma CLI.
    factory = ADAPTERS.get(name, GenericAdapter)
    if factory is HermesAdapter:
        return factory(hermes_home=hermes_home, skills_dir=skills_dir)
    return factory(hermes_home=hermes_home)
