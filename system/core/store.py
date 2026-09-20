"""GitMemoryStore — persistência canônica em arquivos + Git.

Regras de ouro implementadas aqui:
- nunca `git add .`: só arquivos explicitamente passados;
- validação antes do commit (secrets, YAML, tamanho);
- rebase seguro, preservando ambas as versões em conflito;
- push desabilitado por padrão (mneme.yaml: git.allow_push).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import models, validate as validate_mod


def _mkdir_private(directory: Path) -> None:
    """Cria diretórios privados (0700) sem alterar os que já existem."""
    missing: list[Path] = []
    node = directory
    while not node.exists():
        missing.append(node)
        if node.parent == node:
            break
        node = node.parent
    for path in reversed(missing):
        path.mkdir(exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass


class GitError(RuntimeError):
    pass


class GitMemoryStore:
    """Acesso ao repositório Mneme: leitura, escrita, histórico, commit e sync."""

    def __init__(self, root: str | Path, config: Any = None, dry_run: bool = False):
        self.root = Path(root).resolve()
        self.config = config
        self.dry_run = dry_run
        self.last_git_error = ""

    # -- git primitives -------------------------------------------------------
    def git(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            self.last_git_error = f"git {' '.join(args)}: {proc.stderr.strip() or proc.stdout.strip()}"
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} falhou: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout.strip()

    def is_repo(self) -> bool:
        try:
            self.git("rev-parse", "--is-inside-work-tree")
            return True
        except GitError:
            return False

    def ensure_identity(self) -> None:
        if not self.is_repo():
            return
        identity = (self.config.git_identity if self.config else None) or {
            "name": "Hermes Agent",
            "email": "hermes@agents.local",
        }
        self.git("config", "user.name", identity["name"])
        self.git("config", "user.email", identity["email"])
        self.git("config", "push.default", "nothing")

    def init(self) -> None:
        if self.is_repo():
            self.ensure_identity()
            return
        if self.dry_run:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self.git("init", "-b", "main")
        self.ensure_identity()

    def status(self) -> dict[str, Any]:
        if not self.is_repo():
            return {"is_repo": False, "clean": False, "entries": [], "error": self.last_git_error}
        entries = [line for line in self.git("status", "--porcelain").splitlines() if line.strip()]
        return {"is_repo": True, "clean": not entries, "entries": entries, "branch": self.current_branch()}

    def current_branch(self) -> str:
        try:
            return self.git("rev-parse", "--abbrev-ref", "HEAD")
        except GitError:
            return ""

    def has_commits(self) -> bool:
        try:
            self.git("rev-parse", "--verify", "HEAD")
            return True
        except GitError:
            return False

    # -- leitura / escrita ----------------------------------------------------
    def safe_relpath(self, relpath: str | Path) -> str:
        """Normaliza e confina um caminho relativo à raiz do repositório.

        Recusa caminho absoluto, componente `..`, caminho vazio e travessia por
        symlink. É o único ponto por onde passam leitura e escrita.
        """
        raw = str(relpath).strip()
        if not raw:
            raise GitError("caminho vazio")
        candidate = Path(raw)
        if candidate.is_absolute():
            raise GitError(f"caminho absoluto recusado: {raw}")
        if any(part == ".." for part in candidate.parts):
            raise GitError(f"caminho com '..' recusado: {raw}")
        if raw.startswith("~"):
            raise GitError(f"caminho com '~' recusado: {raw}")
        parent = (self.root / candidate).parent
        resolved_parent = parent.resolve()
        if resolved_parent != self.root and self.root not in resolved_parent.parents:
            raise GitError(f"caminho escapa da raiz do Mneme: {raw}")
        return str(candidate)

    def abs(self, relpath: str | Path) -> Path:
        return self.root / self.safe_relpath(relpath)

    def read(self, relpath: str | Path) -> str:
        return self.abs(relpath).read_text(encoding="utf-8")

    def write_file(self, relpath: str | Path, content: str) -> Path:
        """Escreve um arquivo privado: diretórios 0700, arquivos 0600."""
        target = self.abs(relpath)
        if self.dry_run:
            return target
        _mkdir_private(target.parent)
        if target.parent != self.root:
            try:
                os.chmod(target.parent, 0o700)
            except OSError:
                pass
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(target, 0o600)
        return target

    def write_many(self, contents: dict[str, str]) -> list[Path]:
        """Escrita composta: prepara todos os temporários e só então promove.

        Se qualquer preparação falhar, nenhum destino é tocado. A promoção é feita
        por os.replace, então não existe estado parcial visível.
        """
        prepared: list[tuple[Path, Path]] = []
        try:
            for relpath, content in contents.items():
                target = self.abs(relpath)
                if self.dry_run:
                    continue
                _mkdir_private(target.parent)
                temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
                fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(content)
                prepared.append((temporary, target))
            if self.dry_run:
                return [target for _, target in prepared]
            for temporary, target in prepared:
                os.replace(temporary, target)
                os.chmod(target, 0o600)
            return [target for _, target in prepared]
        except Exception:
            for temporary, _ in prepared:
                temporary.unlink(missing_ok=True)
            raise

    def write(
        self,
        relpath: str | Path,
        content: str,
        *,
        message: str | None = None,
        commit: bool = True,
        extra_files: Sequence[str | Path] = (),
        validate: bool = True,
    ) -> dict[str, Any]:
        """Escreve um documento, valida os arquivos afetados e commita só eles."""
        relpath = str(relpath)
        result: dict[str, Any] = {"path": relpath, "commit": None, "dry_run": self.dry_run}
        if validate:
            problems = validate_mod.validate_text(relpath, content)
            errors = [p for p in problems if p["level"] == "error"]
            if errors:
                raise validate_mod.ValidationError(
                    "validação recusou a escrita",
                    [f"{e['path']}: {e['message']}" for e in errors],
                )
        self.write_file(relpath, content)
        result["bytes"] = len(content.encode("utf-8"))
        if commit and not self.dry_run:
            files = [relpath, *[str(f) for f in extra_files]]
            result["commit"] = self.commit(files, message or default_commit_message(relpath))
        return result

    def is_tracked(self, relpath: str) -> bool:
        proc = subprocess.run(
            ["git", "-C", str(self.root), "ls-files", "--error-unmatch", "--", relpath],
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0

    def commit(self, files: Iterable[str], message: str) -> str | None:
        """Commita SOMENTE os caminhos autorizados, ignorando o resto do índice.

        O commit usa a forma com pathspec (`git commit -- <paths>`), então arquivos
        que já estavam staged por outra razão (inclusive segredos) NÃO entram.
        Exclusões de arquivos versionados também são aceitas.
        """
        staged: list[str] = []
        for raw in files:
            if not str(raw).strip():
                continue
            path = self.safe_relpath(raw)
            if path in staged:
                continue
            target = self.root / path
            if target.exists():
                self.git("add", "--", path)
                staged.append(path)
            elif self.is_tracked(path):
                self.git("add", "-u", "--", path)
                staged.append(path)
        if not staged or self.dry_run:
            return None
        # Sem mudança real nos caminhos autorizados: não há commit a fazer (idempotência).
        pending = [
            line for line in self.git("diff", "--cached", "--name-only", "--", *staged).splitlines()
            if line.strip()
        ]
        if not pending:
            return None
        untouched = [
            line for line in self.git("diff", "--cached", "--name-only").splitlines()
            if line.strip() and line not in staged
        ]
        self.git("commit", "-m", message, "-m", "Gerado por brain-manager", "--", *staged)
        if untouched:
            # Visível de propósito: havia staged alheio e ele ficou de fora do commit.
            print(
                "aviso: arquivos já staged ficaram fora deste commit: " + ", ".join(untouched),
                file=sys.stderr,
            )
        return self.git("rev-parse", "HEAD")

    def commit_all_pending(self, message: str) -> str | None:
        entries = [line[3:] for line in self.status().get("entries", [])]
        return self.commit(entries, message)

    # -- histórico ------------------------------------------------------------
    def resolve_path(self, id_or_path: str) -> str | None:
        """Aceita ID, caminho relativo ou nome de arquivo. Devolve caminho relativo.

        Caminho absoluto, `..` e `~` são recusados: o Mneme só lê o próprio repositório.
        """
        raw = str(id_or_path or "").strip()
        if not raw:
            return None
        candidate = Path(raw)
        if candidate.is_absolute() or any(part == ".." for part in candidate.parts) or raw.startswith("~"):
            return None
        try:
            safe = self.safe_relpath(candidate)
        except GitError:
            return None
        candidate = Path(safe)
        if candidate.suffix in (".md", ".yaml") and (self.root / candidate).exists():
            return str(candidate)
        # ID estável -> busca pelo frontmatter (rápida: só nos diretórios de documentos)
        index = _load_index(self)
        if index is not None:
            hit = index.lookup_id(id_or_path)
            if hit:
                return hit
        for directory in ("entities", "projects", "areas", "knowledge", "timeline", "resources", "inbox"):
            base = self.root / directory
            if not base.is_dir():
                continue
            for path in base.rglob("*.md"):
                if path.stem == id_or_path:
                    return str(path.relative_to(self.root))
                if id_or_path.startswith(("person-", "organization-", "project-", "note-", "topic-")) or True:
                    meta, _ = models.read_document(path)
                    if meta.get("id") == id_or_path:
                        return str(path.relative_to(self.root))
        return None

    def history(self, relpath: str, limit: int = 10) -> list[dict[str, str]]:
        if not self.is_repo():
            return []
        out = self.git(
            "log",
            f"-{limit}",
            "--date=short",
            "--pretty=format:%H%x09%ad%x09%an%x09%s",
            "--",
            relpath,
            check=False,
        )
        rows = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 4:
                rows.append({"sha": parts[0], "date": parts[1], "author": parts[2], "subject": parts[3]})
        return rows

    def diff(self, relpath: str, rev: str = "HEAD") -> str:
        if not self.is_repo():
            return ""
        return self.git("diff", rev, "--", relpath, check=False)

    def log(self, limit: int = 10) -> list[str]:
        if not self.is_repo() or not self.has_commits():
            return []
        return self.git("log", f"-{limit}", "--date=short", "--pretty=format:%h %ad %s").splitlines()

    # -- sincronização --------------------------------------------------------
    def remote(self) -> str:
        if not self.is_repo():
            return ""
        return self.git("remote", "get-url", "origin", check=False)

    def sync(self) -> dict[str, Any]:
        """fetch + pull --rebase. Conflito: aborta, preserva o estado e reporta."""
        remote = self.remote()
        if not remote:
            return {"ok": True, "skipped": "sem remoto configurado"}
        fetch = subprocess.run(
            ["git", "-C", str(self.root), "fetch", "--prune"],
            capture_output=True, text=True,
        )
        if fetch.returncode != 0:
            return {"ok": False, "stage": "fetch", "error": fetch.stderr.strip()}
        rebase = subprocess.run(
            ["git", "-C", str(self.root), "pull", "--rebase"],
            capture_output=True, text=True,
        )
        if rebase.returncode != 0:
            self.git("rebase", "--abort", check=False)
            branch = f"mneme/conflict-{time.strftime('%Y%m%d-%H%M%S')}"
            self.git("branch", branch, check=False)
            return {"ok": False, "stage": "rebase", "error": rebase.stderr.strip(), "preserved_branch": branch}
        return {"ok": True, "output": rebase.stdout.strip()}

    def push(self, confirm: bool = False) -> dict[str, Any]:
        if not confirm or not (self.config.allow_push if self.config else False):
            return {"ok": False, "skipped": "push exige autorização explícita (git.allow_push + --confirm)"}
        remote = self.remote()
        if not remote:
            return {"ok": False, "skipped": "sem remoto configurado"}
        proc = subprocess.run(
            ["git", "-C", str(self.root), "push", "-u", "origin", "HEAD"],
            capture_output=True, text=True,
        )
        return {"ok": proc.returncode == 0, "output": (proc.stdout + proc.stderr).strip()}

    # -- backup ---------------------------------------------------------------
    def snapshot(self, destination: str | Path, label: str = "mneme") -> Path:
        """Backup antes de qualquer migração.

        Inclui o conteúdo canônico e ignora `.git`, `system/generated` e caches —
        o arquivo gerado é um tar.gz com apenas o que importa.
        """
        import tarfile

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        archive = destination.parent / f"{label}-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
        excluded = {".git", "system/generated", "__pycache__", "node_modules"}

        def keep(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
            parts = Path(member.name).parts
            if any(part in excluded for part in parts):
                return None
            return member

        with tarfile.open(archive, "w:gz") as tar:
            tar.add(str(self.root), arcname=".", filter=keep)
        return archive

    def content_hash(self, relpath: str) -> str:
        return hashlib.sha256(self.abs(relpath).read_bytes()).hexdigest()


def default_commit_message(relpath: str) -> str:
    """Commits semânticos derivados do caminho (memory/timeline/project/resource)."""
    parts = Path(relpath).parts
    if not parts:
        return "chore: update"
    head = parts[0]
    stem = Path(parts[-1]).stem
    if head == "entities":
        kind = Path(relpath).parent.name.rstrip("s")
        return f"memory({kind}): update {stem}"
    if head == "projects":
        project = parts[1].lower().replace(" ", "-") if len(parts) > 1 else stem
        return f"project({project}): update {stem}"
    if head == "timeline":
        return f"timeline: log {stem}"
    if head == "knowledge":
        return f"knowledge: update {stem}"
    if head == "resources":
        return f"resource: register {stem}"
    if head == "inbox":
        return f"inbox: add {stem}"
    if head == "areas":
        return f"area: update {stem}"
    return f"chore: update {stem}"


def _load_index(store: "GitMemoryStore"):
    """Índice FTS opcional (evita import circular)."""
    try:
        from .index import SearchIndex
    except Exception:  # pragma: no cover - indevido acontecer
        return None
    config = store.config
    db_path = getattr(config, "index_path", None) if config else store.root / "system/generated/index.db"
    if db_path is None or not Path(db_path).exists():
        return None
    return SearchIndex(db_path)
