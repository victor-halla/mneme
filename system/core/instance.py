"""Inicialização e migração de instâncias de dados do Mneme.

O pacote pode viver em qualquer checkout. A instância é um repositório separado,
normalmente ``~/mneme``, e contém apenas dados canônicos e configuração da instalação.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from . import validate as validate_mod

INSTANCE_DIRS = (
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
    "assets/drive",
    ".mneme",
)

CANONICAL_DATA_DIRS = (
    "inbox",
    "entities",
    "projects",
    "areas",
    "knowledge",
    "resources",
    "timeline",
)
MIGRATABLE_SUFFIXES = {".md", ".yaml", ".yml", ".txt", ".json"}

INSTANCE_GITIGNORE = """# Estado derivado e reconstruível
.mneme/

# Cache local dos binários do Google Drive (qualquer profundidade)
**/assets/drive/

# Segredos e credenciais
.env
.env.*
!.env.example
*.pem
*.key
*.p12
*.pfx
credentials*
secrets*
tokens*
*_token.txt

# Ruído local
__pycache__/
*.py[cod]
.DS_Store
*.swp
*~
"""

INSTANCE_AGENTS = """# Instância Mneme

Este repositório contém os dados canônicos do Mneme desta instalação, em Markdown e YAML.
Qualquer agente que saiba ler arquivos e executar comandos de shell usa estes dados, e este
arquivo é o contrato comum entre harnesses: Hermes, Claude Code, Codex e outros que leem
`AGENTS.md`.

- Markdown/YAML versionado é a fonte canônica.
- `.mneme/` contém estado derivado e nunca é versionado.
- `assets/drive/` é cache local do Google Drive e nunca é versionado (qualquer profundidade).
- Conteúdo `secret`, credenciais e tokens nunca entram no Git.
- Dado pessoal que não pode ser versionado tem destino próprio: veja
  "Dados que não vão para o Git".
- Não faça push sem autorização explícita do proprietário.

## Dados que não vão para o Git

Algumas categorias nunca entram no Git, nem em repositório privado. Elas ficam em um único arquivo
local do host, com permissão restrita (arquivo modo 600 e diretório pai 700), fora da instância e
fora de `~/.hermes`:

| Categoria | Exemplos |
| --- | --- |
| identificador | CPF, RG, CNH, CNS, PIS, título de eleitor, registro de classe, passaporte |
| contato | telefone, e-mail pessoal, perfil em rede social |
| endereço | logradouro, número, complemento, CEP, ponto de referência |
| saúde | condição, medicação, alergia, resultado de exame |
| documento | número, órgão emissor, validade, imagem digitalizada |

Regras:

1. O arquivo é declarado em `privacy.sensitive_file` no `mneme.yaml`, por padrão
   `~/.config/mneme/identificadores.md`. Ajuste o caminho se quiser; mantenha-o fora da instância,
   para que ele nunca seja alcançado por `git add`.
2. O cérebro guarda o **fato** e a **referência**, nunca o valor. Escreva que o dado existe e onde
   está, com o ID da entidade; não transcreva número de documento, telefone, e-mail nem endereço
   para Markdown versionado.
3. O arquivo não viaja com o Git: cada host mantém o seu. O que se compartilha entre máquinas é o
   fato e a referência, nunca o valor.
4. `~/.hermes` é runtime do harness e **nunca** base canônica de conhecimento. Gravar em pasta
   privada do harness também não é destino válido: o destino é o arquivo declarado em
   `privacy.sensitive_file`.
5. Ao receber um valor dessas categorias, grave o fato no cérebro e o valor no arquivo restrito,
   criando o diretório com 700 e o arquivo com 600 quando ainda não existirem.

## Como ler e escrever

```bash
brain status                                  # estado de todas as camadas
brain search "termo"                          # busca textual no cérebro
brain get project-exemplo                     # lê um documento por ID ou caminho
brain context project-exemplo --query "impacto"
brain remember "decidimos X por Y"            # grava no lugar certo e commita
brain validate                                # valida a árvore inteira
```

A CLI fica em `~/.local/bin/brain`, o runtime em `~/.local/share/mneme-package`, e ambos
respeitam `MNEME_PACKAGE_ROOT` e `MNEME_ROOT`. Sem a CLI, os arquivos continuam legíveis e
graváveis por qualquer editor: a CLI só organiza, indexa e commita.

## Permissões

O Git registra apenas o bit executável: um clone materializa arquivos conforme o umask local.
Em máquina compartilhada, clone com `umask 077` e reconfira com `find . -type f ! -perm 600`.
"""


def _instance_config(remote: str, drive_folder_id: str) -> dict[str, Any]:
    return {
        "mneme": {
            "version": 1,
            "index": ".mneme/index.db",
            "state": ".mneme/state.json",
            "pending_sync": ".mneme/mem0_pending.jsonl",
        },
        "git": {
            "identity": {"name": "Hermes Agent", "email": "hermes@agents.local", "scope": "local"},
            "allow_push": False,
            "remote": remote,
        },
        "memory_policy": {
            "always": [
                "decisions",
                "commitments",
                "project_changes",
                "relationships",
                "important_preferences",
                "important_events",
            ],
            "usually": ["ideas", "learnings", "meetings", "useful_context"],
            "ignore": ["casual_conversation", "repeated_information", "temporary_requests"],
        },
        "context": {"budget_tokens": 4000, "timeline_days": 14, "max_documents": 40},
        "privacy": {
            # Dado pessoal que não pode ser versionado (identificador, contato, endereço,
            # saúde, documento) fica neste arquivo local, fora do Git e fora da instância.
            # Cada host mantém o seu; o valor nunca é copiado para o Markdown versionado.
            "sensitive_file": "~/.config/mneme/identificadores.md",
        },
        "providers": {
            "mem0": {
                "enabled": True,
                # Mem0 cloud por padrão; para self-hosted use api: self-hosted e
                # host: http://127.0.0.1:8888 (servidor `mem0 serve`).
                "api": "platform",
                "host": "https://api.mem0.ai",
                "user_id": "default",
                "agent_id": "mneme",
                "api_key_env": "MEM0_API_KEY",
                "timeout": 20,
                "top_k": 8,
            },
            "codebase_memory": {
                "enabled": True,
                "command": "codebase-memory-mcp",
                "transport": "cli",
                "timeout": 120,
            },
            "assets": {
                # Binários grandes: o backend remoto é a fonte e o cache local é
                # descartável. Qualquer remote do rclone serve; o Google Drive é o
                # padrão e usa `folder_id`. Sem backend configurado, fica desligado.
                "enabled": bool(drive_folder_id),
                "provider": "rclone",
                "remote": "gdrive:",
                "folder_id": drive_folder_id,
                "cache_dir": "assets/drive",
            },
        },
        "sessions": [],
    }


def initialize_instance(
    root: str | os.PathLike,
    *,
    remote: str = "",
    drive_folder_id: str = "",
) -> dict[str, Any]:
    """Cria uma instância sem sobrescrever configuração ou conteúdo existente."""
    target = Path(root).expanduser().resolve()
    existing = {path.name for path in target.iterdir()} if target.exists() else set()
    if existing - {".git"}:
        return {"ok": False, "error": f"destino não está vazio: {target}", "root": str(target)}
    existing_remote = ""
    git_dir = target / ".git"
    if git_dir.exists() or git_dir.is_symlink():
        if git_dir.is_symlink() or not git_dir.is_dir():
            return {"ok": False, "error": f".git inválido (não é diretório regular): {git_dir}", "root": str(target)}
        probe_repo = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=target,
            capture_output=True,
            text=True,
        )
        if probe_repo.returncode != 0:
            return {"ok": False, "error": f"Git inválido em {target} (use um clone real ou remova .git)", "root": str(target)}
        probe = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=target,
            capture_output=True,
            text=True,
        )
        existing_remote = probe.stdout.strip() if probe.returncode == 0 else ""
        if remote and existing_remote and existing_remote != remote:
            return {
                "ok": False,
                "error": f"origin divergente: {existing_remote}",
                "root": str(target),
            }
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.chmod(0o700)

    config_path = target / "mneme.yaml"
    if config_path.exists():
        return {"ok": False, "error": f"instância já existe: {config_path}", "root": str(target)}

    created: list[str] = []
    for relative in INSTANCE_DIRS:
        directory = target / relative
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        created.append(relative)

    files = {
        "mneme.yaml": yaml.safe_dump(_instance_config(remote, drive_folder_id), sort_keys=False, allow_unicode=True),
        ".gitignore": INSTANCE_GITIGNORE,
        "AGENTS.md": INSTANCE_AGENTS,
    }
    for relative, content in files.items():
        path = target / relative
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
        created.append(relative)

    if not (target / ".git").exists():
        subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Hermes Agent"], cwd=target, check=True)
    subprocess.run(["git", "config", "user.email", "hermes@agents.local"], cwd=target, check=True)
    if remote and not existing_remote:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=target, check=True)

    return {"ok": True, "root": str(target), "created": created, "remote": remote}


def _destination_issue(root: Path, relative: Path) -> str | None:
    """Rejeita escapes e qualquer componente symlink no destino."""
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return f"componente symlink no destino: {current.relative_to(root)}"
    try:
        (root / relative).resolve(strict=False).relative_to(root)
    except ValueError:
        return "destino fora da raiz da instância"
    return None


def _copy_without_following_symlinks(source: Path, target: Path, relative: Path) -> None:
    current = target
    for part in relative.parent.parts:
        current = current / part
        if current.is_symlink():
            raise OSError(f"componente symlink no destino: {current.relative_to(target)}")
        current.mkdir(mode=0o700, exist_ok=True)
        current.chmod(0o700)
    destination = target / relative
    issue = _destination_issue(target, relative)
    if issue:
        raise OSError(issue)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
    finally:
        os.close(descriptor)
    destination.chmod(0o600)


def migrate_instance(source: str | os.PathLike, root: str | os.PathLike) -> dict[str, Any]:
    """Copia dados canônicos para uma instância inicializada, sem alterar a origem."""
    origin = Path(source).expanduser().resolve()
    target = Path(root).expanduser().resolve()
    if not (target / "mneme.yaml").is_file():
        return {"ok": False, "error": f"instância não inicializada: {target}"}
    if origin == target:
        return {"ok": False, "error": "origem e destino são a mesma raiz"}

    planned: list[tuple[Path, Path, str]] = []
    skipped: list[str] = []
    blocked: list[dict[str, Any]] = []
    for top_level in CANONICAL_DATA_DIRS:
        base = origin / top_level
        if not base.is_dir():
            continue
        for source_path in sorted(base.rglob("*")):
            if not source_path.is_file() or source_path.is_symlink():
                continue
            relative = source_path.relative_to(origin).as_posix()
            if source_path.name != ".gitkeep" and source_path.suffix.lower() not in MIGRATABLE_SUFFIXES:
                skipped.append(relative)
                continue
            text = source_path.read_text(encoding="utf-8", errors="replace")
            validation_errors = [
                problem["message"]
                for problem in validate_mod.validate_text(relative, text)
                if problem["level"] == "error"
            ]
            if validation_errors:
                blocked.append({"path": relative, "reason": "; ".join(validation_errors)})
                continue
            relative_path = Path(relative)
            issue = _destination_issue(target, relative_path)
            if issue:
                blocked.append({"path": relative, "reason": issue})
                continue
            destination = target / relative_path
            if destination.exists():
                if destination.read_bytes() == source_path.read_bytes():
                    skipped.append(relative)
                    continue
                blocked.append({"path": relative, "reason": "colisão no destino"})
                continue
            planned.append((source_path, destination, relative))

    if blocked:
        return {
            "ok": False,
            "error": "migração recusada no preflight",
            "blocked": blocked,
            "planned": [relative for _, _, relative in planned],
            "copied": [],
            "skipped": skipped,
            "originals_deleted": False,
        }

    copied: list[str] = []
    for source_path, _destination, relative in planned:
        _copy_without_following_symlinks(source_path, target, Path(relative))
        copied.append(relative)

    return {
        "ok": True,
        "source": str(origin),
        "root": str(target),
        "copied": copied,
        "skipped": skipped,
        "blocked": [],
        "originals_deleted": False,
    }
