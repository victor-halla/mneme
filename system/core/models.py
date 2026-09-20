"""Modelo de dados canônico: IDs estáveis, tipos, sensibilidade e frontmatter YAML."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

TYPES = (
    "person",
    "organization",
    "place",
    "thing",
    "animal",
    "project",
    "area",
    "note",
    "topic",
    "resource",
    "daily",
)

SENSITIVITIES = ("public", "internal", "private", "confidential", "secret")

# Tipos que NUNCA podem ser commitados.
NEVER_COMMIT_SENSITIVITIES = ("secret",)

TYPE_DIRS = {
    "person": "entities/people",
    "organization": "entities/organizations",
    "place": "entities/places",
    "thing": "entities/things",
    "animal": "entities/animals",
    "project": "projects",
    "area": "areas",
    "note": "knowledge/notes",
    "topic": "knowledge/topics",
    "resource": "resources",
    "daily": "timeline",
}

# Tipos que também existem como "tipo de memória" no fluxo de remember/classify.
MEMORY_TYPES = (
    "decision",
    "commitment",
    "project_change",
    "relationship",
    "preference",
    "event",
    "idea",
    "learning",
    "meeting",
    "context",
    "note",
)

ID_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def slugify(text: str, max_len: int = 60) -> str:
    """Slug ASCII, minúsculo, com hífens. Nunca vazio."""
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    ascii_text = re.sub(r"-{2,}", "-", ascii_text)
    if len(ascii_text) > max_len:
        ascii_text = ascii_text[:max_len].rstrip("-")
    return ascii_text or "sem-titulo"


def make_id(type_: str, name: str, max_len: int = 60) -> str:
    return f"{slugify(type_, 20)}-{slugify(name, max_len)}"


def is_valid_id(value: str) -> bool:
    return bool(ID_RE.match(value or ""))


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today_iso() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

FM_DELIM = "---"


class StrictLoader(yaml.SafeLoader):
    """SafeLoader que recusa chaves duplicadas em um mesmo mapa."""

    def construct_mapping(self, node, deep=False):  # noqa: ANN001, ANN201
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"chave duplicada: {key!r}", key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def strict_load(text: str) -> Any:
    """Carrega YAML recusando chave duplicada (usado na validação)."""
    return yaml.load(text, Loader=StrictLoader)


def split_document(text: str) -> tuple[dict[str, Any], str]:
    """Separa frontmatter YAML do corpo. Ausência de frontmatter devolve ({}, texto)."""
    if not text.startswith(FM_DELIM + "\n"):
        return {}, text
    end = text.find("\n" + FM_DELIM, len(FM_DELIM))
    if end == -1:
        return {}, text
    raw = text[len(FM_DELIM) + 1 : end + 1]
    body = text[end + 1 + len(FM_DELIM) :]
    body = body[1:] if body.startswith("\n") else body
    meta = yaml.safe_load(raw) or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body.lstrip("\n")


def join_document(meta: dict[str, Any], body: str) -> str:
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False).strip()
    body = (body or "").strip("\n")
    return f"{FM_DELIM}\n{front}\n{FM_DELIM}\n\n{body}\n"


def read_document(path: str | Path) -> tuple[dict[str, Any], str]:
    return split_document(Path(path).read_text(encoding="utf-8"))


def write_document(path: str | Path, meta: dict[str, Any], body: str) -> Path:
    """Escreve um documento privado: diretórios 0700, arquivos 0600."""
    import os

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(join_document(meta, body))
    os.chmod(target, 0o600)
    return target


def new_meta(
    id_: str,
    type_: str,
    name: str,
    *,
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    relations: list[dict[str, str]] | None = None,
    sensitivity: str = "private",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stamp = today_iso()
    meta: dict[str, Any] = {
        "id": id_,
        "type": type_,
        "name": name,
        "aliases": list(aliases or []),
        "tags": list(tags or []),
        "relations": list(relations or []),
        "created": stamp,
        "updated": stamp,
        "sensitivity": sensitivity,
    }
    if extra:
        for key, value in extra.items():
            if key not in meta:
                meta[key] = value
    return meta


def documents_dir_for(type_: str) -> str:
    return TYPE_DIRS.get(type_, "knowledge/notes")


def path_for_id(id_: str, type_: str | None = None) -> str:
    """Caminho canônico de um documento a partir do ID (`tipo-slug`)."""
    if type_ is None:
        type_ = id_.split("-", 1)[0]
    return f"{documents_dir_for(type_)}/{id_}.md"
