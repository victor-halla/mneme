"""Migração segura de `~/.hermes` para o Mneme: scan -> plan -> apply.

Regras: nunca apagar originais, nunca migrar segredos, sempre gerar manifest,
e nunca tratar `~/.hermes` como base canônica (ele continua sendo runtime do harness).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any, Iterable

import yaml

from . import models, validate as validate_mod

SKIP_DIRS = {
    "hermes-agent",  # instalação do Hermes
    "venv",
    ".venv",
    "node_modules",
    ".git",
    "__pycache__",
    "site-packages",
    "generated",
    "skills",  # skills pertencem ao runtime do harness (decisão documentada)
}

# Diretórios do runtime do harness: inventariados, nunca candidatos a migração.
RUNTIME_DIRS = {
    "sandboxes",
    "workspace",
    "hooks",
    "cron",
    "platforms",
    "plugins",
    "runtime",
    "bin",
    "home",
    "skins",
    "pairing",
    "mcp",
    "profiles",
}
CACHE_DIRS = {"cache", "image_cache", "audio_cache", ".curator_backups", "models", "tmp"}
HISTORY_DIRS = {"sessions", "pastes", "backups"}

# Só texto estruturado entra no plano de migração.
MIGRATION_SUFFIXES = (".md", ".yaml", ".yml", ".txt")
MAX_MIGRATION_BYTES = 256 * 1024

def _unique_target(store: Any, relpath: str, source_rel: str, occupied: set[str]) -> tuple[str, bool]:
    """Garante destino único por origem.

    Destinos calculados a partir do nome do arquivo podem colidir (mesmo nome em
    pastas diferentes). Nesse caso o destino ganha sufixo derivado do caminho de
    origem, e a colisão é registrada em vez de sobrescrever em silêncio.
    """
    candidate = relpath
    root = store.root
    if candidate not in occupied and not (root / candidate).exists():
        return candidate, False
    suffix = hashlib.sha1(source_rel.encode("utf-8")).hexdigest()[:6]
    path = Path(relpath)
    candidate = str(path.with_name(f"{path.stem}-{suffix}{path.suffix}"))
    counter = 2
    while candidate in occupied or (root / candidate).exists():
        candidate = str(path.with_name(f"{path.stem}-{suffix}-{counter}{path.suffix}"))
        counter += 1
    return candidate, True


DESTINATION_BY_TYPE = {
    "knowledge": "knowledge/notes/",
    "project": "projects/",
    "event": "timeline/",
    "person": "entities/people/",
    "organization": "entities/organizations/",
    "place": "entities/places/",
    "thing": "entities/things/",
    "animal": "entities/animals/",
    "uncertain": "inbox/",
    "secret": "NEVER_MIGRATE",
}

RUNTIME_NAMES = {
    "config.yaml",
    "profile.yaml",
    ".env",
    "auth.json",
    "state.db",
    "projects.db",
    "models_dev_cache.json",
    ".hermes_history",
    "context_length_cache.yaml",
    "provider_models_cache.json",
}

TEXT_SUFFIXES = (".md", ".yaml", ".yml", ".txt", ".json")
ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".pdf", ".mp4", ".zip", ".gz", ".tar", ".docx", ".xlsx")

CATEGORIES = (
    "runtime/config",
    "sessions/history",
    "skills",
    "cache",
    "logs",
    "possible knowledge",
    "possible project",
    "possible asset",
    "unknown",
    "sensitive / never Git",
)


def scan(hermes_home: str | Path, limit: int | None = None) -> dict[str, Any]:
    """Inventário somente-leitura: classifica arquivos sem mover nada."""
    home = Path(hermes_home).expanduser()
    report: dict[str, Any] = {
        "hermes_home": str(home),
        "counts": {category: 0 for category in CATEGORIES},
        "examples": {category: [] for category in CATEGORIES},
        "total_files": 0,
        "total_bytes": 0,
    }
    if not home.is_dir():
        report["error"] = "diretório inexistente"
        return report

    for path in _walk(home):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        category = categorize(path, home)
        report["counts"][category] += 1
        report["total_files"] += 1
        report["total_bytes"] += size
        if len(report["examples"][category]) < 12:
            report["examples"][category].append(
                {"path": str(path.relative_to(home)), "bytes": size}
            )
        if limit and report["total_files"] >= limit:
            break
    return report


def categorize(path: Path, home: Path) -> str:
    rel = path.relative_to(home)
    parts = rel.parts
    name = path.name
    lowered = name.lower()

    if validate_mod.is_sensitive_path(name) or lowered.endswith((".pem", ".key", ".p12")):
        return "sensitive / never Git"
    if parts[0] in HISTORY_DIRS or name == ".hermes_history":
        return "sessions/history"
    if parts[0] in CACHE_DIRS:
        return "cache"
    if parts[0] in ("logs",):
        return "logs"
    if parts[0] == "skills" or "skills" in parts[:-1]:
        return "skills"
    if name.endswith(("_cache.json", "_cache.yaml", ".etag")) or name.startswith(".update_check"):
        return "cache"
    # `private/` guarda documentos e credenciais pessoais: nunca migrar.
    if parts[0] == "private":
        return "sensitive / never Git"
    if name in RUNTIME_NAMES or parts[0] in RUNTIME_DIRS or lowered.endswith((".db", ".sqlite", ".db-wal", ".db-shm")):
        return "runtime/config"
    if path.suffix.lower() in ASSET_SUFFIXES:
        return "possible asset"
    if path.suffix.lower() in TEXT_SUFFIXES:
        if lowered in ("soul.md", "agents.md", "claude.md", "readme.md"):
            return "possible knowledge"
        if "project" in lowered or "plan" in lowered or "handoff" in lowered or "readme" in lowered:
            return "possible project"
        if parts[0] in ("memories", "knowledge", "notes", "plans", "docs") or "note" in lowered or "memory" in lowered:
            return "possible knowledge"
        return "unknown"
    if lowered.endswith((".json", ".jsonl")):
        return "runtime/config"
    return "unknown"


def _walk(home: Path) -> Iterable[Path]:
    for path in sorted(home.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(home).parts[:-1]):
            continue
        if path.is_file():
            yield path


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def plan(hermes_home: str | Path, limit_files: int = 40) -> dict[str, Any]:
    """Plano de migração: para cada candidato, destino e motivo. Não altera nada."""
    home = Path(hermes_home).expanduser()
    entries: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    for path in _walk(home):
        rel = str(path.relative_to(home))
        category = categorize(path, home)
        if category == "sensitive / never Git":
            # Segredos são listados explicitamente como never_migrate (auditável, nunca copiados).
            if sum(1 for e in entries if e["action"] == "never_migrate") < 50:
                entries.append({
                    "source": rel,
                    "destination": DESTINATION_BY_TYPE["secret"],
                    "category": category,
                    "action": "never_migrate",
                    "reason": "nome/caminho sensível",
                })
            skipped[category] = skipped.get(category, 0) + 1
            continue
        if category in ("runtime/config", "sessions/history", "skills", "cache", "logs"):
            # Runtime, histórico, caches e logs permanecem no harness (documentado).
            skipped[category] = skipped.get(category, 0) + 1
            continue
        if category == "possible asset":
            entries.append({"source": rel, "destination": "resources/ (metadados apenas)", "category": category, "action": "metadata_only"})
            continue
        if path.suffix.lower() not in MIGRATION_SUFFIXES or path.stat().st_size > MAX_MIGRATION_BYTES:
            skipped["não-texto ou grande demais"] = skipped.get("não-texto ou grande demais", 0) + 1
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if validate_mod.scan_secrets(text):
            entries.append({
                "source": rel,
                "destination": DESTINATION_BY_TYPE["secret"],
                "category": category,
                "action": "never_migrate",
                "reason": "conteúdo com possível segredo",
            })
            continue
        guessed = _guess_type(text, category)
        entries.append({
            "source": rel,
            "destination": DESTINATION_BY_TYPE.get(guessed, "inbox/"),
            "category": category,
            "action": "copy",
            "guessed_type": guessed,
        })
        if len([e for e in entries if e["action"] == "copy"]) >= limit_files:
            break
    return {
        "hermes_home": str(home),
        "entries": entries,
        "copy": sum(1 for e in entries if e["action"] == "copy"),
        "never_migrate": sum(1 for e in entries if e["action"] == "never_migrate"),
        "metadata_only": sum(1 for e in entries if e["action"] == "metadata_only"),
        "skipped": skipped,
        "note": (
            "Nada é apagado na origem. Runtime (config, sessões, skills, caches, logs) e "
            "segredos permanecem no harness por decisão de arquitetura."
        ),
    }


def _guess_type(text: str, category: str) -> str:
    """Classificação conservadora: na dúvida, o item vai para o inbox."""
    import re as _re

    meta, body = models.split_document(text)
    declared = str(meta.get("type") or "").strip().lower()
    if declared in ("project",):
        return "project"
    if declared in ("person", "organization", "place", "thing", "animal"):
        return declared
    if declared:
        return "knowledge"
    lowered = body.lower()
    if _re.search(r"^#\s*projeto\b", lowered, _re.M):
        return "project"
    if "roadmap" in lowered and ("projeto" in lowered or "projeto" in lowered):
        return "project"
    if "reunião" in lowered and "ata" in lowered:
        return "event"
    if category == "possible project":
        return "uncertain"
    if category == "possible knowledge" and len(body.strip()) > 120:
        return "knowledge"
    return "uncertain"


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply(
    hermes_home: str | Path,
    config: Any,
    store: Any,
    *,
    manifest_dir: str | Path | None = None,
    limit_files: int = 40,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Copia (nunca move) os candidatos para o Mneme, com manifest auditável."""
    home = Path(hermes_home).expanduser()
    migration_plan = plan(home, limit_files=limit_files)
    manifest_dir = Path(manifest_dir or (config.root / "system/manifests"))
    manifest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    manifest_path = manifest_dir / f"hermes-migration-{stamp}.yaml"
    counter = 2
    while manifest_path.exists():
        manifest_path = manifest_dir / f"hermes-migration-{stamp}-{counter}.yaml"
        counter += 1

    applied: list[dict[str, Any]] = []
    occupied: set[str] = set()
    manifest: dict[str, Any] = {
        "generated_at": models.now_iso(),
        "hermes_home": str(home),
        "mneme_root": str(config.root),
        "mode": "copy",
        "originals_deleted": False,
        "entries": applied,
    }

    for entry in migration_plan["entries"]:
        if entry["action"] != "copy":
            applied.append({**entry, "status": "skipped"})
            continue
        source = home / entry["source"]
        if not source.is_file():
            applied.append({**entry, "status": "missing"})
            continue
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            applied.append({**entry, "status": "unreadable"})
            continue
        if validate_mod.scan_secrets(text):
            applied.append({**entry, "status": "blocked_secret"})
            continue

        slug = models.slugify(source.stem)
        destination = entry["destination"]
        if destination.startswith("projects/"):
            relpath = f"projects/{source.stem}/documents/{source.name}"
        elif destination.startswith("timeline/"):
            relpath = f"timeline/{models.today_iso()[:4]}/{models.today_iso()[5:7]}/{models.today_iso()}.md"
        elif destination.startswith("entities/"):
            relpath = f"{destination}{source.stem}.md"
        elif destination.startswith("resources/"):
            relpath = f"resources/{source.stem}.yaml"
        else:
            relpath = f"{destination}{models.today_iso().replace('-', '')}-migrated-{slug}.md"

        if relpath.endswith(".md") and not models.split_document(text)[0]:
            meta = models.new_meta(
                models.make_id("note", f"migrated-{slug}"),
                "note",
                source.stem,
                tags=["migrado-hermes"],
                sensitivity="private",
                extra={"origin": f"~/.hermes/{entry['source']}", "migrated_at": models.now_iso()},
            )
            content = models.join_document(meta, text)
        else:
            content = text

        # Colisão: origem diferente apontando para o mesmo destino não pode sobrescrever.
        relpath, collided = _unique_target(store, relpath, entry["source"], occupied)
        occupied.add(relpath)

        if dry_run:
            applied.append({**entry, "status": "dry_run", "target": relpath, "collision": collided})
            continue

        problems = [p for p in validate_mod.validate_text(relpath, content) if p["level"] == "error"]
        if problems:
            applied.append({**entry, "status": "blocked_validation", "reason": problems[0]["message"]})
            continue

        store.write_file(relpath, content)
        applied.append({
            **entry,
            "status": "copied_renamed" if collided else "copied",
            "target": relpath,
            "bytes": len(content.encode("utf-8")),
            "collision": collided,
        })

    if not dry_run:
        copied = [entry["target"] for entry in applied if entry["status"] == "copied"]
        if copied:
            store.commit(copied, f"migration(hermes): importar {len(copied)} documento(s) do runtime")
        manifest["copied"] = len(copied)
        manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")

    return {"manifest": str(manifest_path), "planned": migration_plan, "applied": applied,
            "copied": sum(1 for a in applied if a.get("status") == "copied"),
            "blocked": sum(1 for a in applied if str(a.get("status", "")).startswith("blocked"))}


# ---------------------------------------------------------------------------
# Snapshot de segurança (antes de aplicar)
# ---------------------------------------------------------------------------


def backup_hermes(home: str | Path, destination_dir: str | Path, label: str = "hermes-runtime") -> str:
    """Copia apenas os candidatos (não o runtime inteiro) para um diretório de backup."""
    home = Path(home).expanduser()
    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in _walk(home):
        category = categorize(path, home)
        if category in ("runtime/config", "sessions/history", "skills", "cache", "logs", "unknown"):
            continue
        if category == "sensitive / never Git":
            continue
        target = destination / path.relative_to(home)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    index = {"home": str(home), "files": count, "created_at": models.now_iso(), "label": label}
    (destination / "backup-index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return str(destination)
