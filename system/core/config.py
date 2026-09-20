"""Resolução de raiz, configuração (mneme.yaml) e carregamento de ambiente.

Regras:
- A raiz do repositório é encontrada por MNEME_ROOT, mneme.yaml ou caminhos padrão.
- Segredos NUNCA vêm do mneme.yaml: vêm de variáveis de ambiente, opcionalmente carregadas
  de um arquivo `mneme.env` fora do repositório, com permissão 600.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ENV_FILE_CANDIDATES = (
    "~/.config/mneme/mneme.env",
)
ROOT_CANDIDATES = (
    "~/mneme",
)


def load_env_file(path: str | os.PathLike | None = None) -> list[str]:
    """Carrega KEY=VALUE de um arquivo fora do Git sem sobrescrever o ambiente atual."""
    paths = [Path(path).expanduser()] if path else [Path(p).expanduser() for p in ENV_FILE_CANDIDATES]
    loaded: list[str] = []
    for candidate in paths:
        if not candidate.is_file():
            continue
        mode = candidate.stat().st_mode & 0o777
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if key not in os.environ:
                os.environ[key] = value
                loaded.append(key)
        if mode & 0o077:
            loaded.append(f"WARN:permissao_aberta:{candidate}")
    return loaded


def find_root(explicit: str | os.PathLike | None = None) -> Path:
    """Descobre a raiz do Mneme. Nunca cria nada aqui."""
    candidates: list[str | os.PathLike] = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("MNEME_ROOT"):
        candidates.append(os.environ["MNEME_ROOT"])
    candidates.extend(ROOT_CANDIDATES)
    for candidate in candidates:
        root = Path(candidate).expanduser()
        if (root / "mneme.yaml").is_file():
            return root.resolve()
    raise FileNotFoundError(
        "mneme.yaml não encontrado. Defina MNEME_ROOT ou use --root. "
        f"Testados: {[str(Path(c).expanduser()) for c in candidates]}"
    )


class MnemeConfig:
    """Configuração efetiva do Mneme."""

    def __init__(self, root: str | os.PathLike | None = None, env_file: str | None = None):
        self.env_loaded = load_env_file(env_file)
        self.root = find_root(root)
        self.path = self.root / "mneme.yaml"
        self.data: dict[str, Any] = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}

    # -- acesso ---------------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        value = self.get(name, {})
        return value if isinstance(value, dict) else {}

    # -- caminhos -------------------------------------------------------------
    @property
    def index_path(self) -> Path:
        return self.root / self.get("mneme.index", "system/generated/index.db")

    @property
    def state_path(self) -> Path:
        return self.root / self.get("mneme.state", "system/generated/state.json")

    @property
    def pending_sync_path(self) -> Path:
        return self.root / self.get("mneme.pending_sync", "system/generated/mem0_pending.jsonl")

    @property
    def generated_dir(self) -> Path:
        configured = self.get("mneme.generated_dir")
        path = self.root / configured if configured else self.index_path.parent
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)  # contém índice, contadores e fila de pendências
        except OSError:
            pass
        return path

    # -- providers ------------------------------------------------------------
    @property
    def mem0(self) -> dict[str, Any]:
        return self.section("providers").get("mem0", {}) or {}

    @property
    def codebase_memory(self) -> dict[str, Any]:
        return self.section("providers").get("codebase_memory", {}) or {}

    @property
    def assets(self) -> dict[str, Any]:
        return self.section("providers").get("assets", {}) or {}

    # -- memória / contexto ---------------------------------------------------
    @property
    def policy(self) -> dict[str, Any]:
        return self.section("memory_policy")

    @property
    def context_budget(self) -> int:
        return int(self.get("context.budget_tokens", 4000))

    @property
    def timeline_days(self) -> int:
        return int(self.get("context.timeline_days", 14))

    @property
    def allow_push(self) -> bool:
        return bool(self.get("git.allow_push", False))

    @property
    def git_identity(self) -> dict[str, str]:
        identity = self.get("git.identity", {}) or {}
        return {
            "name": identity.get("name", "Hermes Agent"),
            "email": identity.get("email", "hermes@agents.local"),
        }

    def mem0_api_key(self) -> str:
        env_name = self.mem0.get("api_key_env", "MEM0_API_KEY")
        return os.environ.get(env_name, "")

    def secret_available(self, env_name: str) -> bool:
        return bool(os.environ.get(env_name, ""))
