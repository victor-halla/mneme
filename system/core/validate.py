"""Validação e segurança: YAML, IDs, relações, datas, segredos e tamanho.

Regra: nada entra no Git sem passar por aqui. `secret` significa NUNCA COMMITAR.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

import yaml

from . import models


class ValidationError(RuntimeError):
    def __init__(self, message: str, problems: Iterable[str] = ()):
        self.problems = list(problems)
        detail = "; ".join(self.problems[:8])
        super().__init__(f"{message}: {detail}" if detail else message)


# ---------------------------------------------------------------------------
# Segredos
# ---------------------------------------------------------------------------

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # tokens do GitHub: clássicos (ghp_/gho_/ghu_/ghs_/ghr_) e fine-grained (github_pat_)
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    # Anthropic vem ANTES do padrão genérico de OpenAI e é excluído dele (evita rotular duas vezes)
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai-key", re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_-]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("telegram-bot-token", re.compile(r"\b\d{8,14}:[A-Za-z0-9_-]{30,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|apikey|secret|client[_-]?secret|access[_-]?token|refresh[_-]?token|"
            r"password|passwd|senha|private[_-]?key)\b\s*[:=]\s*[\"']?([A-Za-z0-9\-_/+=~]{20,})"
        ),
    ),
)

# Senha/frase-senha com espaços não cabe no padrão acima: exige contexto e valor crível.
PASSWORD_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passphrase|senha|secret)\b\s*[:=]\s*(?:[\"']([^\"']{8,80})[\"']|([^\"'\n]{8,40}))",
)
SENTENCE_TAIL = re.compile(r"(?i)\b(esqueci|temporaria|provisoria|nova|antiga|padrao|default|exemplo|placeholder)\b")


def shannon_entropy(value: str) -> float:
    """Entropia da informação (bits por caractere). Chave real costuma passar de 3.2."""
    import math

    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    total = len(value)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _password_like(text: str) -> list[str]:
    """Detecta senha/frase-senha atribuída quando o valor parece credencial, não prosa."""
    hits: list[str] = []
    for match in PASSWORD_ASSIGNMENT.finditer(text or ""):
        value = (match.group(1) or match.group(2) or "").strip()
        if len(value) < 8:
            continue
        if SENTENCE_TAIL.search(value):
            continue
        has_class = bool(re.search(r"[0-9]", value)) or bool(re.search(r"[^A-Za-z0-9 ]", value))
        if has_class and (len(value.split()) > 1 or shannon_entropy(value) >= 2.6):
            hits.append("password-assignment")
    return hits

SENSITIVE_FILENAMES = re.compile(
    r"(?i)(^\.env|credentials|secrets?[._-]?|tokens?[._-]?|credenciais|senhas|chaves|\.pem$|\.key$|\.p12$|id_rsa|id_ed25519|known_hosts)"
)

MAX_TEXT_BYTES = 512 * 1024  # documento de texto do cérebro
MAX_ASSET_BYTES = 5 * 1024 * 1024  # binário: só metadados no Git


def scan_secrets(text: str) -> list[str]:
    if not text:
        return []
    hits = [name for name, pattern in SECRET_PATTERNS if pattern.search(text)]
    hits.extend(_password_like(text))
    return sorted(set(hits))


def looks_like_secret(text: str) -> bool:
    return bool(scan_secrets(text))


def is_sensitive_path(path: str | Path) -> bool:
    return bool(SENSITIVE_FILENAMES.search(Path(path).name))


def gitleaks_available() -> bool:
    return shutil.which("gitleaks") is not None


def run_gitleaks(root: str | Path) -> dict[str, Any]:
    """Usa gitleaks quando instalado; caso contrário devolve o scanner interno."""
    if not gitleaks_available():
        return {"available": False, "note": "gitleaks não instalado — usando scanner interno"}
    proc = subprocess.run(
        ["gitleaks", "detect", "--no-banner", "--redact", "--source", str(root)],
        capture_output=True,
        text=True,
    )
    # 0 = nada encontrado, 1 = vazamentos encontrados; detalhes são deliberadamente resumidos.
    findings = [line for line in (proc.stdout or "").splitlines() if "leaks found" in line.lower()]
    return {"available": True, "clean": proc.returncode == 0, "summary": findings[:3]}


# ---------------------------------------------------------------------------
# Validação de conteúdo
# ---------------------------------------------------------------------------


def validate_text(relpath: str, content: str) -> list[dict[str, str]]:
    """Valida um conteúdo específico (usado antes de qualquer escrita)."""
    problems: list[dict[str, str]] = []

    def add(level: str, message: str) -> None:
        problems.append({"path": relpath, "level": level, "message": message})

    if is_sensitive_path(relpath):
        add("error", "caminho sensível: nunca versionar (padrão de segredo no nome do arquivo)")
    hits = scan_secrets(content)
    if hits:
        add("error", f"possível segredo detectado ({', '.join(hits)}) — nunca versionar")

    size = len(content.encode("utf-8"))
    if size > MAX_TEXT_BYTES:
        add("error", f"arquivo de texto grande demais para o Git ({size} bytes)")

    if relpath.endswith((".md", ".yaml", ".yml")):
        try:
            meta, _ = models.split_document(content)
        except yaml.YAMLError as exc:
            add("error", f"YAML inválido no frontmatter: {exc}")
            return problems
        # Chave duplicada é aceita em silêncio pelo YAML: aqui vira erro.
        raw_front = _raw_frontmatter(content)
        if raw_front:
            try:
                models.strict_load(raw_front)
            except yaml.YAMLError as exc:
                add("error", f"frontmatter com chave duplicada ou inválida: {exc.problem if hasattr(exc, 'problem') else exc}")
        if meta:
            problems.extend(validate_meta(relpath, meta, content))
        elif relpath.endswith((".yaml", ".yml")):
            try:
                yaml.safe_load(content)
            except yaml.YAMLError as exc:
                add("error", f"YAML inválido: {exc}")
    return problems


def _raw_frontmatter(content: str) -> str:
    """Devolve o bloco YAML do frontmatter, sem o corpo, para parse estrito."""
    if not content.startswith("---\n"):
        return ""
    end = content.find("\n---", 3)
    if end == -1:
        return ""
    return content[4 : end + 1]


def validate_meta(relpath: str, meta: dict[str, Any], content: str = "") -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []

    def add(level: str, message: str) -> None:
        problems.append({"path": relpath, "level": level, "message": message})

    id_ = str(meta.get("id") or "")
    type_ = str(meta.get("type") or "")
    if not id_:
        add("error", "frontmatter sem 'id'")
    elif not models.is_valid_id(id_):
        add("error", f"id inválido: {id_!r} (esperado tipo-slug minúsculo)")
    if type_ and type_ not in models.TYPES:
        add("error", f"tipo desconhecido: {type_}")
    if id_ and type_ and not id_.startswith(f"{type_}-"):
        add("warning", f"id {id_!r} não começa com o tipo {type_!r}")
    if not meta.get("name"):
        add("warning", "frontmatter sem 'name'")

    sensitivity = str(meta.get("sensitivity") or "")
    if not sensitivity:
        add("warning", "sem 'sensitivity' — assume private")
    elif sensitivity not in models.SENSITIVITIES:
        add("error", f"sensitivity inválida: {sensitivity}")
    elif sensitivity in models.NEVER_COMMIT_SENSITIVITIES:
        add("error", f"sensitivity={sensitivity} nunca pode ser versionado")

    for field in ("created", "updated"):
        if meta.get(field) and not models.parse_date(str(meta[field])):
            add("error", f"data inválida em {field}: {meta[field]!r}")

    relations = meta.get("relations") or []
    if not isinstance(relations, list):
        add("error", "'relations' deve ser lista")
    else:
        for index, relation in enumerate(relations):
            if not isinstance(relation, dict):
                add("error", f"relations[{index}] deve ser mapa com type/target")
                continue
            if not relation.get("type") or not relation.get("target"):
                add("error", f"relations[{index}] precisa de 'type' e 'target'")
    return problems


def validate_root(root: str | Path) -> dict[str, Any]:
    """Valida o repositório inteiro: YAML, IDs únicos, relações, datas, segredos, tamanho."""
    root = Path(root)
    report: dict[str, Any] = {
        "root": str(root),
        "errors": [],
        "warnings": [],
        "documents": 0,
        "ids": {},
        "duplicate_ids": [],
        "unknown_relations": [],
        "code": [],
        "secrets": [],
        "large_files": [],
        "gitleaks": run_gitleaks(root),
    }

    for directory in ("entities", "projects", "areas", "knowledge", "timeline", "resources", "inbox"):
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relpath = str(path.relative_to(root))
            size = path.stat().st_size
            if size > MAX_ASSET_BYTES:
                report["large_files"].append({"path": relpath, "bytes": size})
                if path.suffix.lower() in (".md", ".yaml", ".yml"):
                    report["errors"].append({"path": relpath, "message": f"texto grande demais ({size} bytes)"})
                continue
            if path.suffix.lower() not in (".md", ".yaml", ".yml"):
                continue
            report["documents"] += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            for problem in validate_text(relpath, text):
                bucket = report["errors"] if problem["level"] == "error" else report["warnings"]
                bucket.append({"path": problem["path"], "message": problem["message"]})
            if scan_secrets(text):
                report["secrets"].append(relpath)
            try:
                meta, _ = models.split_document(text)
            except yaml.YAMLError:
                meta = {}  # YAML inválido já foi registrado como erro em validate_text
            id_ = meta.get("id")
            if id_:
                if id_ in report["ids"]:
                    report["duplicate_ids"].append(
                        {"id": id_, "paths": [report["ids"][id_], relpath]}
                    )
                    report["errors"].append({"path": relpath, "message": f"ID duplicado: {id_}"})
                else:
                    report["ids"][id_] = relpath

    # Relações apontando para IDs inexistentes
    knwon_ids = set(report["ids"])
    for id_, relpath in report["ids"].items():
        path = root / relpath
        try:
            meta, _ = models.split_document(path.read_text(encoding="utf-8"))
        except Exception:
            continue  # YAML inválido já foi reportado acima
        for relation in meta.get("relations") or []:
            if isinstance(relation, dict) and relation.get("target") and relation["target"] not in knwon_ids:
                report["unknown_relations"].append(
                    {"path": relpath, "target": relation["target"], "type": relation.get("type")}
                )
                report["warnings"].append(
                    {"path": relpath, "message": f"relação para ID inexistente: {relation['target']}"}
                )

    # Projetos
    projects_dir = root / "projects"
    if projects_dir.is_dir():
        for project in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
            brain_file = project / ".brain.yaml"
            entry = {"project": project.name, "ok": bool(brain_file.is_file()), "issues": []}
            if not brain_file.is_file():
                entry["issues"].append("sem .brain.yaml")
                report["warnings"].append({"path": str(project.relative_to(root)), "message": "sem .brain.yaml"})
            else:
                try:
                    data = yaml.safe_load(brain_file.read_text(encoding="utf-8")) or {}
                except yaml.YAMLError as exc:
                    entry["issues"].append(f".brain.yaml inválido: {exc}")
                    report["errors"].append(
                        {"path": f"{project.name}/.brain.yaml", "message": f"YAML inválido: {exc}"}
                    )
                    data = {}
                code = (data or {}).get("code") or {}
                if code.get("enabled"):
                    for repo in code.get("repositories") or []:
                        repo_path = Path(str(repo.get("path", "")))
                        if not repo_path.exists():
                            entry["issues"].append(f"codebase inexistente: {repo_path}")
                            report["warnings"].append(
                                {
                                    "path": f"{project.name}/.brain.yaml",
                                    "message": f"codebase path inexistente: {repo_path}",
                                }
                            )
            report["code"].append(entry)

    report["ok"] = not report["errors"] and not report["secrets"] and not report["duplicate_ids"]
    return report


def validate_and_raise(root: str | Path) -> dict[str, Any]:
    report = validate_root(root)
    if not report["ok"]:
        problems = [f"{e['path']}: {e['message']}" for e in report["errors"]]
        problems += [f"{p}: segredo detectado" for p in report["secrets"]]
        raise ValidationError("validação do repositório falhou", problems)
    return report
