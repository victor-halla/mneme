"""Criação e leitura de projetos (unidade de contexto do Mneme)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import models

BRAIN_TEMPLATE: dict[str, Any] = {
    "type": "project",
    "memory": {"canonical": "git", "mem0": True},
    "search": {"markdown": True},
    "code": {"enabled": False, "provider": "codebase-memory", "repositories": []},
    "assets": {"provider": "gdrive", "enabled": False},
    "context": {
        "include": [
            "project",
            "decisions",
            "tasks",
            "related_entities",
            "timeline_recent",
            "mem0",
            "code_intelligence",
        ]
    },
    "sessions": [],
}

PROJECT_MD = """---
id: {project_id}
type: project
name: {name}
aliases: []
tags: [projeto]
relations: []
created: {today}
updated: {today}
sensitivity: private
status: active
---

# {name}

## Objetivo

(descreva o objetivo em uma frase)

## Resultado esperado

(qual entrega concreta define sucesso)

## Status

active

## Pessoas

- (ids de pessoas envolvidas)

## Organizações

- (ids de organizações envolvidas)

## Áreas

- (ids de áreas relacionadas)

## Lugares

- (ids de lugares relevantes)

## Métricas

- (como medimos progresso)

## Riscos

- (riscos conhecidos)

## Próximas ações

- [ ] (primeira ação)
"""

AGENTS_MD = """# {name} — regras do projeto

- Este diretório é a unidade de contexto do projeto: `project.md`, `decisions.md`, `tasks.md`.
- Escreva decisões em `decisions.md` (com data) e compromissos em `tasks.md`.
- Documentos de negócio/produto ficam em `documents/`; binários grandes vão para o provider de assets.
- Toda alteração persistente passa por `brain validate` e por um commit pequeno.
- Código-fonte NÃO é indexado aqui: use o provider de code intelligence (`brain code ...`).
"""

DECISIONS_MD = """---
id: note-{slug}-decisions
type: note
name: {name} — decisões
aliases: []
tags: [decisoes, projeto]
relations:
  - type: belongs_to
    target: {project_id}
created: {today}
updated: {today}
sensitivity: private
---

# {name} — decisões

(decisões de negócio, produto, processo e projeto. Decisões técnicas/arquiteturais da codebase
vivem no ADR do Codebase Memory e são apenas referenciadas aqui.)
"""

TASKS_MD = """---
id: note-{slug}-tasks
type: note
name: {name} — tarefas
aliases: []
tags: [tarefas, projeto]
relations:
  - type: belongs_to
    target: {project_id}
created: {today}
updated: {today}
sensitivity: private
---

# {name} — tarefas abertas

- [ ] (descreva a primeira tarefa)
"""


INVALID_NAME = ("/", "\\", "..", "~", "\x00")


def validate_project_name(name: str) -> str:
    """Normaliza e valida o nome do projeto: nada de separador, '..' nem nome vazio."""
    clean = " ".join(str(name or "").split())
    if not clean:
        raise ValueError("nome de projeto vazio")
    if any(token in clean for token in INVALID_NAME):
        raise ValueError(f"nome de projeto inválido (contém separador ou '..'): {name!r}")
    if not models.slugify(clean):
        raise ValueError(f"nome de projeto inválido: {name!r}")
    return clean


def create_project(brain: Any, name: str, project_id: str | None = None, code_repos: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Cria a estrutura de um projeto. Nunca sobrescreve um projeto existente."""
    root: Path = brain.config.root
    name = validate_project_name(name)
    project_id = project_id or models.make_id("project", name)
    slug = models.slugify(name)
    directory = root / "projects" / name
    if not str(directory.resolve()).startswith(str((root / "projects").resolve()) + "/"):
        return {"ok": False, "error": f"destino fora de projects/: {name!r}"}
    if directory.exists():
        return {"ok": False, "error": f"projeto já existe: {directory}", "dir": str(directory.relative_to(root))}

    today = models.today_iso()
    files: dict[str, str] = {
        "project.md": PROJECT_MD.format(project_id=project_id, name=name, today=today),
        "AGENTS.md": AGENTS_MD.format(name=name),
        "decisions.md": DECISIONS_MD.format(project_id=project_id, name=name, today=today, slug=slug),
        "tasks.md": TASKS_MD.format(project_id=project_id, name=name, today=today, slug=slug),
    }
    brain_config = dict(BRAIN_TEMPLATE)
    brain_config["id"] = project_id
    if code_repos:
        brain_config["code"] = {"enabled": True, "provider": "codebase-memory", "repositories": code_repos}
    files[".brain.yaml"] = yaml.safe_dump(brain_config, allow_unicode=True, sort_keys=False)

    for filename, content in files.items():
        brain.store.write_file(f"projects/{name}/{filename}", content)
    for subdir in ("documents", "assets", "scripts", "skills"):
        (directory / subdir).mkdir(parents=True, exist_ok=True)
        (directory / subdir / ".gitkeep").write_text("", encoding="utf-8")

    tracked = [f"projects/{name}/{filename}" for filename in files]
    tracked += [f"projects/{name}/{subdir}/.gitkeep" for subdir in ("documents", "assets", "scripts", "skills")]
    commit = brain.store.commit(tracked, f"project({slug}): criar estrutura do projeto")
    brain.index.reindex(root, incremental=True)
    return {"ok": True, "dir": f"projects/{name}", "id": project_id, "commit": commit, "files": tracked}


def list_projects(brain: Any) -> list[dict[str, Any]]:
    return brain.compiler.projects()
