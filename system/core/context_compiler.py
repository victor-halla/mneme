"""Context Compiler — federa Mneme + Mem0 + Codebase Memory em contexto ranqueado.

Nunca envia o repositório inteiro: aplica orçamento de tokens e prioriza
(1) estado do projeto, (2) decisões vigentes, (3) tarefas abertas, (4) eventos recentes,
(5) fatos semânticos, (6) inteligência de código relevante à pergunta.

Cada seção carrega sua procedência, para que a resposta final possa citar de onde veio.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import models, routing

PROVENANCE = {
    "mneme": "memória canônica (Mneme/Git)",
    "timeline": "timeline (Mneme)",
    "mem0": "memória semântica (Mem0, derivada)",
    "code-intelligence": "inteligência de código (Codebase Memory MCP, derivada)",
}


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class ContextCompiler:
    def __init__(self, config: Any, store: Any, index: Any = None, mem0: Any = None, code: Any = None, timeline: Any = None):
        self.config = config
        self.store = store
        self.index = index
        self.mem0 = mem0
        self.code = code
        self.timeline = timeline

    # -- resolução de escopo ---------------------------------------------------
    def projects(self) -> list[dict[str, Any]]:
        projects_dir = self.config.root / "projects"
        found: list[dict[str, Any]] = []
        if not projects_dir.is_dir():
            return found
        for directory in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
            brain = directory / ".brain.yaml"
            data: dict[str, Any] = {}
            if brain.is_file():
                try:
                    data = yaml.safe_load(brain.read_text(encoding="utf-8")) or {}
                except yaml.YAMLError:
                    data = {}
            found.append(
                {
                    "dir": str(directory.relative_to(self.config.root)),
                    "name": directory.name,
                    "id": str(data.get("id") or models.make_id("project", directory.name)),
                    "data": data,
                }
            )
        return found

    def resolve_scope(self, scope: str) -> dict[str, Any]:
        scope = (scope or "").strip()
        lowered = scope.lower()
        if lowered in ("today", "hoje", "daily", "timeline"):
            return {"kind": "timeline", "id": "timeline", "label": "timeline recente"}

        for project in self.projects():
            if lowered in (project["id"].lower(), project["name"].lower(), models.slugify(project["name"])):
                return {"kind": "project", **project, "label": f"projeto {project['name']}"}

        if self.index is not None:
            path = self.index.lookup_id(scope)
            if path:
                meta, _ = models.read_document(self.config.root / path)
                return {
                    "kind": "document",
                    "id": meta.get("id") or scope,
                    "type": meta.get("type"),
                    "path": path,
                    "label": str(meta.get("name") or scope),
                }
            hits = self.index.search(scope, limit=1)
            if hits:
                meta, _ = models.read_document(self.config.root / hits[0]["path"])
                return {
                    "kind": "document",
                    "id": meta.get("id") or hits[0]["id"],
                    "type": meta.get("type"),
                    "path": hits[0]["path"],
                    "label": str(meta.get("name") or scope),
                }
        return {"kind": "unknown", "id": scope, "label": scope}

    # -- compilação ------------------------------------------------------------
    def compile(
        self,
        scope: str,
        query: str | None = None,
        budget_tokens: int | None = None,
        use_mem0: bool = True,
        use_code: bool = True,
    ) -> dict[str, Any]:
        budget = int(budget_tokens or self.config.context_budget)
        resolved = self.resolve_scope(scope)
        route = routing.route(query or scope)
        sections: list[dict[str, Any]] = []

        if resolved["kind"] == "project":
            sections.extend(self._project_sections(resolved, query))
        elif resolved["kind"] == "document":
            sections.extend(self._document_sections(resolved))
        elif resolved["kind"] == "timeline":
            sections.extend(self._timeline_sections())
        else:
            sections.append(
                {
                    "title": f"Escopo não resolvido: {scope}",
                    "source": "mneme",
                    "priority": 0,
                    "text": "Nenhum projeto/entidade com esse identificador. Confirme o ID com `brain search`.",
                }
            )

        sections.extend(self._timeline_sections(limit_events=5, priority=40, only_if_missing=True))
        if use_mem0:
            sections.extend(self._mem0_sections(query or scope, resolved))
        if use_code and resolved["kind"] == "project":
            sections.extend(self._code_sections(resolved, query))

        # Ranqueamento por prioridade + orçamento de tokens
        ordered = sorted(sections, key=lambda s: (-int(s.get("priority", 0)), s.get("title", "")))
        kept: list[dict[str, Any]] = []
        used = 0
        truncated: list[str] = []
        for section in ordered:
            cost = estimate_tokens(section["text"])
            if used + cost > budget and kept:
                truncated.append(section["title"])
                continue
            kept.append(section)
            used += cost

        markdown = self._render(scope, resolved, route, kept, truncated, used, budget)
        return {
            "scope": scope,
            "resolved": resolved,
            "route": route,
            "budget_tokens": budget,
            "used_tokens": used,
            "sections": [{"title": s["title"], "source": s["source"], "tokens": estimate_tokens(s["text"])} for s in kept],
            "truncated": truncated,
            "markdown": markdown,
        }

    # -- construtores de seção -------------------------------------------------
    def _read_if_exists(self, relpath: str) -> str:
        path = self.config.root / relpath
        if not path.is_file():
            return ""
        meta, body = models.read_document(path)
        return body.strip()

    def _project_sections(self, project: dict[str, Any], query: str | None) -> list[dict[str, Any]]:
        base = project["dir"]
        sections: list[dict[str, Any]] = []
        for filename, title, priority in (
            ("project.md", f"Estado atual — {project['name']}", 100),
            ("decisions.md", "Decisões vigentes", 90),
            ("tasks.md", "Tarefas abertas", 80),
        ):
            body = self._read_if_exists(f"{base}/{filename}")
            if body:
                sections.append({"title": title, "source": "mneme", "priority": priority, "text": body})

        # Entidades relacionadas
        relations: list[str] = []
        meta, _ = models.read_document(self.config.root / f"{base}/project.md")
        for relation in meta.get("relations") or []:
            if isinstance(relation, dict) and relation.get("target"):
                relations.append(str(relation["target"]))
        entity_lines: list[str] = []
        for entity_id in relations[:10]:
            if self.index is not None:
                path = self.index.lookup_id(entity_id)
                if path:
                    entity_meta, entity_body = models.read_document(self.config.root / path)
                    summary = " ".join(entity_body.strip().splitlines()[:3])[:280]
                    entity_lines.append(f"- {entity_id} ({entity_meta.get('type')}): {summary}")
        if entity_lines:
            sections.append(
                {
                    "title": "Entidades relacionadas",
                    "source": "mneme",
                    "priority": 60,
                    "text": "\n".join(entity_lines),
                }
            )

        # Documentos relacionados por busca textual, se veio pergunta
        if query and self.index is not None:
            hits = self.index.search(query, limit=6)
            lines = [
                f"- [{hit['type']}] {hit['name']} ({hit['path']}): {hit['snippet']}"
                for hit in hits
                if not hit["path"].startswith(base)
            ]
            if lines:
                sections.append(
                    {"title": f"Documentos relacionados à pergunta", "source": "mneme", "priority": 55, "text": "\n".join(lines)}
                )
        return sections

    def _document_sections(self, resolved: dict[str, Any]) -> list[dict[str, Any]]:
        path = resolved.get("path")
        if not path:
            return []
        text = (self.config.root / path).read_text(encoding="utf-8")
        return [
            {
                "title": f"{resolved['label']} ({path})",
                "source": "mneme",
                "priority": 100,
                "text": text.strip(),
            }
        ]

    def _timeline_sections(self, limit_events: int | None = None, priority: int = 70, only_if_missing: bool = False) -> list[dict[str, Any]]:
        if self.timeline is None:
            return []
        events = self.timeline.recent(days=self.config.timeline_days)
        if not events:
            return []
        if limit_events:
            events = events[:limit_events]
        lines = [f"- {event['date']} {event.get('event_id', '')} — {event['title']}" for event in events]
        return [
            {
                "title": "Eventos recentes (timeline)",
                "source": "timeline",
                "priority": priority,
                "text": "\n".join(lines),
            }
        ]

    def _mem0_sections(self, query: str, resolved: dict[str, Any]) -> list[dict[str, Any]]:
        if self.mem0 is None:
            return []
        result = self.mem0.search(query, top_k=int(self.config.mem0.get("top_k", 8)))
        if not result.get("ok"):
            return [
                {
                    "title": "Mem0 indisponível",
                    "source": "mem0",
                    "priority": 10,
                    "text": f"Mem0 não respondeu ({result.get('error', 'erro desconhecido')}). Conhecimento canônico segue válido.",
                }
            ]
        results = result.get("results") or []
        if not results:
            return []
        lines = [
            f"- ({round(float(item.get('score') or 0), 3)}) {item['memory']}" for item in results[:8] if item.get("memory")
        ]
        return [{"title": "Fatos semânticos relacionados (Mem0)", "source": "mem0", "priority": 50, "text": "\n".join(lines)}]

    def _code_sections(self, project: dict[str, Any], query: str | None) -> list[dict[str, Any]]:
        if self.code is None:
            return []
        code_config = (project.get("data") or {}).get("code") or {}
        if not code_config.get("enabled"):
            return []
        sections: list[dict[str, Any]] = []
        repositories = code_config.get("repositories") or []
        indexed: list[dict[str, Any]] = self.code.list_repositories()
        for repo in repositories:
            repo_path = str(repo.get("path", ""))
            name = self.code.resolve_project(repo_path=repo_path, hint=repo.get("id"))
            if not name:
                sections.append(
                    {
                        "title": f"Codebase não indexada — {repo.get('id') or repo_path}",
                        "source": "code-intelligence",
                        "priority": 20,
                        "text": f"Caminho {repo_path} não aparece em list_projects. Rode: brain code index {repo_path}",
                    }
                )
                continue
            if query:
                terms = _search_terms(query)
                search = self.code.search(name, terms or query, limit=8)
                text = _json_compact(search)
                title = f"Código: busca estrutural por {terms or query!r} em {name}"
                priority = 65
            else:
                architecture = self.code.architecture(name, aspects=["overview"])
                text = _json_compact(architecture)
                title = f"Código: arquitetura de {name}"
                priority = 45
            if text:
                sections.append({"title": title, "source": "code-intelligence", "priority": priority, "text": text})
        total = len(indexed)
        if total:
            sections.append(
                {
                    "title": "Repositórios indexados",
                    "source": "code-intelligence",
                    "priority": 15,
                    "text": "\n".join(f"- {repo.get('name')} ({repo.get('root_path')})" for repo in indexed[:10]),
                }
            )
        return sections

    # -- render ---------------------------------------------------------------
    def _render(
        self,
        scope: str,
        resolved: dict[str, Any],
        route: dict[str, Any],
        sections: list[dict[str, Any]],
        truncated: list[str],
        used: int,
        budget: int,
    ) -> str:
        lines = [
            f"# Contexto Mneme — {scope}",
            "",
            f"- escopo: {resolved.get('kind')} / {resolved.get('label')}",
            f"- rota aplicada: {route.get('mode')}",
            f"- orçamento: ~{used}/{budget} tokens",
            "",
        ]
        for section in sections:
            lines.append(f"## {section['title']}  [{section['source']}]")
            lines.append("")
            lines.append(section["text"].strip())
            lines.append("")
        if truncated:
            lines.append(f"_Seções omitidas por orçamento: {', '.join(truncated)}_")
            lines.append("")
        lines.append("## Procedência")
        lines.append("")
        lines.append("| origem | o que é |")
        lines.append("| --- | --- |")
        for source in sorted({section["source"] for section in sections}):
            lines.append(f"| {source} | {PROVENANCE.get(source, source)} |")
        return "\n".join(lines)


CODE_QUERY_STOPWORDS = {
    "impacto", "impactos", "alterar", "mudar", "remover", "quebra", "quebrar", "afeta", "afetar",
    "componente", "componentes", "codigo", "código", "função", "funcao", "classe", "metodo",
    "método", "quem", "chama", "chamadas", "onde", "esta", "está", "implementado", "implementa",
    "arquitetura", "estrutura", "projeto", "se", "eu", "o", "a", "os", "as", "de", "do", "da",
    "em", "no", "na", "que", "para", "por", "com", "e", "the", "of",
}


def _search_terms(query: str) -> str:
    """Extrai termos úteis para o grafo (ex.: 'impacto de alterar o store' -> 'store')."""
    import re as _re

    tokens = [t for t in _re.findall(r"[0-9A-Za-zÀ-ÿ_]{3,}", query or "")]
    useful = [t for t in tokens if t.lower() not in CODE_QUERY_STOPWORDS]
    return " ".join(useful[:4]) or ""


def _json_compact(payload: dict[str, Any], limit: int = 2400) -> str:
    """Renderiza respostas do provider de código em linhas legíveis (não YAML cru)."""
    if not payload:
        return ""
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    if isinstance(data, dict) and ("cols" in data or "groups" in data):
        lines: list[str] = []
        cols = list(data.get("cols") or [])
        index = {name: position for position, name in enumerate(cols)}
        for row in data.get("rows") or []:
            if "qn" in index:
                label = row[index["label"]] if "label" in index and len(row) > index["label"] else ""
                file_path = row[index["file"]] if "file" in index and len(row) > index["file"] else ""
                lines_path = row[index["lines"]] if "lines" in index and len(row) > index["lines"] else ""
                lines.append(f"- {row[index['qn']]} ({label}) {file_path}:{lines_path}")
            else:
                lines.append("- " + " | ".join(str(value) for value in row))
        for group in data.get("groups") or []:
            prefix = str(group.get("qn_prefix") or "")
            for row in group.get("rows") or []:
                if not row:
                    continue
                name = str(row[0])
                qualified = f"{prefix}.{name}" if prefix else name
                extra = " | ".join(str(value) for value in row[1:])
                lines.append(f"- {qualified} | {extra}")
        if data.get("total") is not None:
            lines.append(f"(total: {data.get('total')})")
        return "\n".join(lines[:40]).strip()
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return text[:limit].strip()
