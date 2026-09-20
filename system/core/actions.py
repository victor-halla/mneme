"""Camada de serviço do Mneme: o que um harness (Hermes/OpenClaw/CLI) realmente chama.

Fluxo canônico de escrita (`remember`):
    classificar -> resolver entidade -> escrever Markdown -> validar
    -> commit pequeno -> sincronizar Mem0 (derivado)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import classify as classify_mod
from . import context_compiler, models, routing, timeline as timeline_mod, validate as validate_mod
from .index import SearchIndex
from .store import GitMemoryStore


class Brain:
    def __init__(self, config: Any, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.store = GitMemoryStore(config.root, config=config, dry_run=dry_run)
        self.index = SearchIndex(config.index_path)
        self.timeline = timeline_mod.Timeline(config.root, config.state_path)
        self._mem0 = None
        self._code = None
        self._compiler = None

    # -- providers preguiçosos ------------------------------------------------
    @property
    def mem0(self):
        if self._mem0 is None:
            from providers.mem0_provider import Mem0Provider

            self._mem0 = Mem0Provider(self.config)
        return self._mem0

    @property
    def code(self):
        if self._code is None:
            from providers.codebase_memory_provider import CodebaseMemoryProvider

            self._code = CodebaseMemoryProvider(self.config)
        return self._code

    @property
    def compiler(self) -> context_compiler.ContextCompiler:
        if self._compiler is None:
            self._compiler = context_compiler.ContextCompiler(
                self.config, self.store, index=self.index, mem0=self.mem0, code=self.code, timeline=self.timeline
            )
        return self._compiler

    # -- leitura --------------------------------------------------------------
    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.index.search(query, limit=limit)

    def get(self, id_or_path: str) -> dict[str, Any] | None:
        path = self.store.resolve_path(id_or_path)
        if not path:
            return None
        text = self.store.read(path)
        meta, body = models.split_document(text)
        return {"path": path, "meta": meta, "body": body, "text": text}

    def context(self, scope: str, query: str | None = None, budget: int | None = None) -> dict[str, Any]:
        return self.compiler.compile(scope, query=query, budget_tokens=budget)

    def history(self, id_or_path: str, limit: int = 10) -> dict[str, Any]:
        path = self.store.resolve_path(id_or_path)
        if not path:
            return {"ok": False, "error": f"documento não encontrado: {id_or_path}"}
        return {"ok": True, "path": path, "commits": self.store.history(path, limit=limit)}

    def diff(self, id_or_path: str, rev: str = "HEAD") -> dict[str, Any]:
        path = self.store.resolve_path(id_or_path)
        if not path:
            return {"ok": False, "error": f"documento não encontrado: {id_or_path}"}
        return {"ok": True, "path": path, "diff": self.store.diff(path, rev)}

    def validate(self) -> dict[str, Any]:
        return validate_mod.validate_root(self.config.root)

    def reindex(self, incremental: bool = True) -> dict[str, Any]:
        return self.index.reindex(self.config.root, incremental=incremental)

    # -- escrita --------------------------------------------------------------
    def remember(
        self,
        text: str,
        *,
        type_: str | None = None,
        project: str | None = None,
        entity_id: str | None = None,
        timeline: bool = True,
        commit: bool = True,
        sync_mem0: bool = True,
        force: bool = False,
    ) -> dict[str, Any]:
        """Persiste um fato no lugar correto e devolve um recibo auditável."""
        classification = classify_mod.classify_text(text, self.config.policy)
        if type_:
            classification["type"] = type_
        decision = classification["decision"]
        if force:
            decision = "always" if decision == "ignore" else decision
        receipt: dict[str, Any] = {
            "ok": True,
            "text": text.strip(),
            "classification": classification,
            "files": [],
            "commit": None,
            "timeline_event": None,
            "mem0": None,
            "warnings": [],
        }
        if decision == "ignore":
            receipt["ok"] = True
            receipt["skipped"] = f"política de memória: {classification['reason']}"
            return receipt

        if classification.get("sensitivity") == "secret":
            receipt["ok"] = False
            receipt["skipped"] = "conteúdo parece credencial — nunca versionar (mneme.yaml: sensitivity secret)"
            return receipt

        writes: dict[str, str] = {}
        type_bucket = classification["type"]
        project_slug = project or classification.get("project")

        # 1) Documento de conhecimento / entidade (nunca para tipos que vão ao projeto)
        if type_bucket in ("note", "preference", "idea", "learning", "context", "relationship"):
            doc_result = self._write_knowledge_document(text, classification, entity_id=entity_id)
            if doc_result:
                writes[doc_result["path"]] = doc_result["content"]
                receipt["document"] = {
                    "path": doc_result["path"],
                    "action": doc_result["action"],
                }

        # 2) Projeto (decisão, compromisso, mudança) ou inbox quando o projeto não existe
        if type_bucket in ("decision", "commitment", "project_change", "meeting"):
            project_result = self._write_project_update(text, classification, project_slug)
            if project_result:
                writes[project_result["path"]] = project_result["content"]
                receipt["project_update"] = {
                    "path": project_result["path"],
                    "action": project_result["action"],
                }
                if project_result["action"] == "inbox":
                    receipt["warnings"].append(
                        f"projeto não resolvido ({project_slug or 'não informado'}) — gravado no inbox"
                    )

        # 3) Timeline
        if timeline and type_bucket in ("event", "meeting", "decision", "commitment", "project_change"):
            event = self.timeline.append(
                _title_for(text),
                text.strip(),
                kind=type_bucket,
                entities=classification.get("entities") or [],
                project=project_slug,
            )
            writes[event["path"]] = event["content"]
            receipt["timeline_event"] = event["event"]

        if not writes:
            receipt["skipped"] = "nada a gravar (política de memória)"
            return receipt

        # 4) Validar conteúdo e segredos ANTES de escrever qualquer coisa
        problems = []
        for path, content in writes.items():
            for problem in validate_mod.validate_text(path, content):
                if problem["level"] == "error":
                    problems.append(f"{path}: {problem['message']}")
        if problems:
            raise validate_mod.ValidationError("escrita recusada pela validação", problems)

        # Escrita composta: prepara tudo e só então promove (sem estado parcial).
        self.store.write_many(writes)

        commit_sha = None
        if commit and not self.dry_run:
            commit_sha = self.store.commit(list(writes), self._commit_message(classification, text))
        receipt["files"] = list(writes)
        receipt["commit"] = commit_sha

        # 5) Índice + Mem0 (derivado)
        if not self.dry_run:
            self.index.reindex(self.config.root, incremental=True)
        if sync_mem0:
            receipt["mem0"] = self._sync_mem0(text, classification, commit_sha, list(writes))
        return receipt

    # -- detalhes de escrita --------------------------------------------------
    def _write_knowledge_document(
        self, text: str, classification: dict[str, Any], entity_id: str | None = None
    ) -> dict[str, Any] | None:
        type_bucket = classification["type"]
        doc_type = classification["document_type"]
        slug = classification["slug"]

        if type_bucket == "relationship" and (classification.get("entities") or entity_id):
            entity = entity_id or classification["entities"][0]
            relpath = models.path_for_id(entity, "person")
            existing = (self.config.root / relpath)
            if existing.is_file():
                meta, body = models.read_document(existing)
                meta["updated"] = models.today_iso()
                body = f"{body.strip()}\n\n### {models.today_iso()} — atualização\n\n{text.strip()}\n"
                return {"path": relpath, "content": models.join_document(meta, body), "action": "append"}
            # Nome derivado do ID estável: o texto do fato é conteúdo, não nome de entidade.
            meta = models.new_meta(entity, "person", models.title_from_id(entity))
            body = f"{text.strip()}\n"
            return {"path": relpath, "content": models.join_document(meta, body), "action": "create"}

        if doc_type == "daily":
            return None  # timeline é tratada separadamente

        relpath = f"knowledge/notes/{slug}.md"
        existing = self.config.root / relpath
        if existing.is_file():
            meta, body = models.read_document(existing)
            if _similar(body, text):
                return {"path": relpath, "content": models.join_document(meta, body), "action": "duplicate_skipped"}
            meta["updated"] = models.today_iso()
            body = f"{body.strip()}\n\n### {models.today_iso()} — atualização\n\n{text.strip()}\n"
            return {"path": relpath, "content": models.join_document(meta, body), "action": "append"}

        meta = models.new_meta(
            models.make_id("note", slug),
            "note",
            _title_for(text),
            tags=[type_bucket],
            extra={"memory_type": type_bucket},
        )
        body = f"{text.strip()}\n"
        return {"path": relpath, "content": models.join_document(meta, body), "action": "create"}

    def _find_project_dir(self, slug: str) -> Path | None:
        projects_dir = self.config.root / "projects"
        if not projects_dir.is_dir():
            return None
        for directory in projects_dir.iterdir():
            if not directory.is_dir():
                continue
            if models.slugify(directory.name) == models.slugify(slug):
                return directory
            brain = directory / ".brain.yaml"
            if brain.is_file():
                meta, _ = models.split_document(brain.read_text(encoding="utf-8"))
                if str(meta.get("id", "")).lower() == f"project-{models.slugify(slug)}":
                    return directory
        return None

    def _write_project_update(self, text: str, classification: dict[str, Any], project_slug: str) -> dict[str, Any] | None:
        directory = self._find_project_dir(project_slug)
        type_bucket = classification["type"]
        if directory is None:
            # Sem projeto resolvido: nunca inventar projeto — cai no inbox.
            slug = classification["slug"]
            relpath = f"inbox/{slug}-{models.today_iso()}.md"
            meta = models.new_meta(
                models.make_id("note", f"{slug}-{models.today_iso()}"),
                "note",
                _title_for(text),
                tags=[type_bucket, "inbox"],
                extra={"memory_type": type_bucket, "project_hint": project_slug},
            )
            return {"path": relpath, "content": models.join_document(meta, text.strip() + "\n"), "action": "inbox"}
        filename = {
            "decision": "decisions.md",
            "commitment": "tasks.md",
            "project_change": "project.md",
            "meeting": "decisions.md",
        }.get(type_bucket, "decisions.md")
        target = directory / filename
        relpath = str(target.relative_to(self.config.root))
        if target.is_file():
            meta, body = models.read_document(target)
            meta["updated"] = models.today_iso()
            body = f"{body.strip()}\n\n### {models.today_iso()} — {_title_for(text)}\n\n{text.strip()}\n"
        else:
            meta = models.new_meta(
                models.make_id("note", f"{directory.name}-{filename.split('.')[0]}"),
                "note",
                f"{directory.name} — {filename.split('.')[0]}",
                extra={"project": models.make_id("project", directory.name)},
            )
            body = f"# {directory.name} — {filename.split('.')[0]}\n\n### {models.today_iso()} — {_title_for(text)}\n\n{text.strip()}\n"
        return {"path": relpath, "content": models.join_document(meta, body), "action": "append"}

    def _commit_message(self, classification: dict[str, Any], text: str) -> str:
        type_bucket = classification["type"]
        slug = classification["slug"][:40]
        prefix = {
            "decision": "memory(decision)",
            "commitment": "memory(commitment)",
            "project_change": "project",
            "relationship": "memory(person)",
            "preference": "memory(preference)",
            "event": "timeline",
            "meeting": "timeline",
            "idea": "knowledge",
            "learning": "knowledge",
        }.get(type_bucket, "memory(note)")
        return f"{prefix}: {slug}"

    def _sync_mem0(
        self, text: str, classification: dict[str, Any], commit_sha: str | None, files: list[str]
    ) -> dict[str, Any]:
        metadata = {
            "entity_id": None,
            "type": classification["type"],
            "source_file": files[0] if files else None,
            "source_commit": commit_sha,
            "source_agent": "hermes",
            "recorded_at": models.now_iso(),
            "sensitivity": classification.get("sensitivity", "private"),
        }
        if classification.get("project"):
            metadata["entity_id"] = models.make_id("project", classification["project"])
        # O tipo já vai em metadata.type: a memória fica legível sem prefixo duplicado.
        distilled = text.strip()
        return self.mem0.add(distilled, metadata=metadata, infer=False)

    # -- operações de manutenção ----------------------------------------------
    def sync(self, push: bool = False, confirm: bool = False) -> dict[str, Any]:
        pending = self.mem0.flush_pending() if self.mem0.enabled else {"flushed": 0, "failed": 0, "remaining": 0}
        git_sync = self.store.sync()
        pushed: dict[str, Any] = {"ok": True, "skipped": "não solicitado"}
        if push:
            pushed = self.store.push(confirm=confirm)
        return {"mem0_pending": pending, "git": git_sync, "push": pushed}

    def status(self) -> dict[str, Any]:
        git_state = self.store.status()
        index_stats = self.index.stats() if self.config.index_path.exists() else {"documents": 0, "ids": 0}
        mem0_health = self.mem0.health()
        code_health = self.code.health()
        validation = validate_mod.validate_root(self.config.root)
        try:
            from adapters import get_adapter

            adapter = get_adapter(
                "hermes",
                hermes_home=self.config.get("harness.hermes.home"),
                skills_dir=self.config.get("harness.hermes.skills_dir"),
            ).capabilities()
        except Exception as exc:  # pragma: no cover
            adapter = {"harness": "hermes", "error": str(exc)}
        projects = self.compiler.projects()
        code_repos: list[dict[str, Any]] = []
        for project in projects:
            repositories = ((project.get("data") or {}).get("code") or {}).get("repositories") or []
            for repository in repositories:
                code_repos.append({"project": project["id"], **repository})
        return {
            "root": str(self.config.root),
            "git": git_state,
            "index": index_stats,
            "mem0": mem0_health,
            "code": code_health,
            "validation": {
                "ok": validation["ok"],
                "errors": len(validation["errors"]),
                "warnings": len(validation["warnings"]),
                "documents": validation["documents"],
                "secrets": validation["secrets"],
                "gitleaks": validation["gitleaks"],
            },
            "harness": adapter,
            "projects": [{"id": project["id"], "dir": project["dir"]} for project in projects],
            "codebases": code_repos,
            "migration": {"scan": True, "plan": True, "apply": True},
        }

    # -- organização do inbox --------------------------------------------------
    def organize(self, dry_run: bool | None = None) -> dict[str, Any]:
        from .organize import organize_inbox

        return organize_inbox(self, dry_run=self.dry_run if dry_run is None else dry_run)


# ---------------------------------------------------------------------------
# utilitários
# ---------------------------------------------------------------------------


def _title_for(text: str) -> str:
    first = (text or "").strip().splitlines()[0] if text.strip() else "sem título"
    cleaned = re.sub(r"^\s*[-*#>\d.\s]+", "", first).strip()
    return cleaned[:120] or "sem título"


def _similar(body: str, text: str) -> bool:
    """Detecção simples de duplicata: sobreposição alta de tokens significativos."""
    def tokens(value: str) -> set[str]:
        return {token for token in re.findall(r"[0-9A-Za-zÀ-ÿ]{4,}", value.lower())}

    existing, new = tokens(body), tokens(text)
    if not new:
        return True
    return len(existing & new) / len(new) > 0.8
