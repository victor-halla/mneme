"""Suporte comum aos testes: cria um repositório Mneme temporário e isolado."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

import sys

SYSTEM_DIR = Path(__file__).resolve().parents[1]
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import yaml  # noqa: E402

BASE_MNEME_YAML: dict[str, Any] = {
    "mneme": {
        "version": 1,
        "index": "system/generated/index.db",
        "state": "system/generated/state.json",
        "pending_sync": "system/generated/mem0_pending.jsonl",
    },
    "git": {
        "identity": {"name": "Hermes Agent", "email": "hermes@agents.local", "scope": "local"},
        "allow_push": False,
        "remote": "",
    },
    "memory_policy": {
        "always": ["decisions", "commitments", "project_changes", "relationships", "important_preferences", "important_events"],
        "usually": ["ideas", "learnings", "meetings", "useful_context"],
        "ignore": ["casual_conversation", "repeated_information", "temporary_requests"],
    },
    "context": {"budget_tokens": 4000, "timeline_days": 14, "max_documents": 40},
    "providers": {
        "mem0": {
            "enabled": False,
            "host": "http://127.0.0.1:9",
            "user_id": "test-user",
            "agent_id": "mneme-test",
            "api_key_env": "MEM0_API_KEY",
            "timeout": 3,
            "top_k": 5,
        },
        "codebase_memory": {"enabled": False, "command": "codebase-memory-mcp-not-installed", "transport": "cli", "timeout": 30},
        "assets": {"enabled": False, "provider": "gdrive"},
    },
    "sessions": [],
}

DOC_DIRS = (
    "inbox",
    "entities/people",
    "entities/organizations",
    "entities/places",
    "entities/things",
    "entities/animals",
    "projects",
    "areas",
    "knowledge/notes",
    "knowledge/topics",
    "resources",
    "timeline",
    "system/generated",
    "system/manifests",
)


class MnemeTestCase(unittest.TestCase):
    """Base: cria raiz temporária, mneme.yaml e repositório Git limpo."""

    mem0_enabled = False

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mneme-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        config_data = yaml.safe_load(yaml.safe_dump(BASE_MNEME_YAML))
        config_data["providers"]["mem0"]["enabled"] = self.mem0_enabled
        if self.mem0_enabled:
            config_data["providers"]["mem0"]["host"] = MEM0_HOST
        (self.tmp / "mneme.yaml").write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")
        for directory in DOC_DIRS:
            (self.tmp / directory).mkdir(parents=True, exist_ok=True)
        self.config_data = config_data
        self._init_git()
        self.brain = self._make_brain()

    def _init_git(self) -> None:
        subprocess.run(["git", "init", "-b", "main"], cwd=self.tmp, capture_output=True, text=True, check=True)
        subprocess.run(["git", "config", "user.name", "Hermes Agent"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.email", "hermes@agents.local"], cwd=self.tmp, check=True)
        subprocess.run(["git", "add", "--", "mneme.yaml"], cwd=self.tmp, check=True)
        subprocess.run(["git", "commit", "-m", "chore: init mneme de teste"], cwd=self.tmp, capture_output=True, check=True)

    def _make_brain(self, dry_run: bool = False):
        from core.actions import Brain
        from core.config import MnemeConfig

        # Alterações feitas em self.config_data precisam existir no disco.
        (self.tmp / "mneme.yaml").write_text(
            yaml.safe_dump(self.config_data, sort_keys=False), encoding="utf-8"
        )
        config = MnemeConfig(root=self.tmp)
        return Brain(config, dry_run=dry_run)

    # -- helpers ---------------------------------------------------------------
    def write(self, relpath: str, content: str) -> Path:
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read(self, relpath: str) -> str:
        return (self.tmp / relpath).read_text(encoding="utf-8")

    def exists(self, relpath: str) -> bool:
        return (self.tmp / relpath).exists()

    def git_log(self) -> str:
        return subprocess.run(
            ["git", "log", "--pretty=format:%h %s"], cwd=self.tmp, capture_output=True, text=True
        ).stdout

    def make_project(self, name: str = "Mneme", project_id: str | None = None) -> str:
        from core.projects import create_project

        result = create_project(self.brain, name, project_id=project_id)
        self.assertTrue(result["ok"], result)
        return result["dir"]

    def snapshot(self) -> dict[str, float]:
        return {str(p.relative_to(self.tmp)): p.stat().st_mtime for p in self.tmp.rglob("*") if p.is_file()}


def mem0_available() -> tuple[bool, str]:
    """Verifica Mem0 real: chave no ambiente + servidor respondendo."""
    import json
    import os
    import urllib.request

    key = os.environ.get("MEM0_API_KEY", "")
    if not key:
        return False, "MEM0_API_KEY ausente no ambiente"
    # O mem0 self-hosted exige filters com user_id/agent_id/run_id
    request = urllib.request.Request(
        f"{MEM0_HOST}/search",
        data=json.dumps({"query": "health", "top_k": 1, "filters": {"user_id": "default"}}).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            if response.status != 200:
                return False, f"HTTP {response.status}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, "ok"


# Infraestrutura de teste: sempre vem do ambiente, com padrões inofensivos.
MEM0_HOST = os.environ.get("MNEME_TEST_MEM0_HOST", "http://127.0.0.1:8888")
CODE_COMMAND = os.environ.get("MNEME_TEST_CODE_COMMAND", "codebase-memory-mcp")
INDEXED_REPO = os.environ.get("MNEME_TEST_INDEXED_REPO", "")
INDEXED_PROJECT = os.environ.get("MNEME_TEST_INDEXED_PROJECT", "")


def code_provider_available(command: str = CODE_COMMAND) -> tuple[bool, str]:
    """O binário do provider de código existe neste ambiente?"""
    if shutil.which(command) or Path(command).is_file():
        return True, "ok"
    return False, f"binário ausente: {command}"


def indexed_repo_available() -> tuple[bool, str]:
    """Teste estrutural exige um repositório real já indexado no provider."""
    if not INDEXED_REPO or not Path(INDEXED_REPO).is_dir():
        return False, "MNEME_TEST_INDEXED_REPO não aponta para um diretório existente"
    if not INDEXED_PROJECT:
        return False, "MNEME_TEST_INDEXED_PROJECT não definido"
    return True, "ok"


def code_requirements_available() -> tuple[bool, str]:
    """Binário e repositório indexado, exigidos pelos testes de code intelligence."""
    available, reason = code_provider_available()
    if not available:
        return available, reason
    return indexed_repo_available()
