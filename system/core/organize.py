"""Organização do inbox: classifica, detecta duplicatas, move e consolida.

`brain organize` faz commits pequenos e por arquivo, e sincroniza o Mem0 no final.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import classify as classify_mod
from . import models, validate as validate_mod


def organize_inbox(brain: Any, dry_run: bool = False) -> dict[str, Any]:
    root: Path = brain.config.root
    inbox = root / "inbox"
    report: dict[str, Any] = {"processed": 0, "moved": 0, "kept": 0, "duplicates": 0, "items": [], "dry_run": dry_run}
    if not inbox.is_dir():
        return report

    existing_texts = _corpus(root, exclude_prefix="inbox/")

    for path in sorted(inbox.glob("*.md")):
        meta, body = models.read_document(path)
        relpath = str(path.relative_to(root))
        item: dict[str, Any] = {"file": relpath, "id": meta.get("id"), "action": "kept", "target": None}
        classification = classify_mod.classify_text(body, brain.config.policy)

        if classification["sensitivity"] == "secret" or validate_mod.scan_secrets(body):
            item["action"] = "kept"
            item["reason"] = "possível segredo — nunca migrar/commitado; revise manualmente"
            report["items"].append(item)
            report["kept"] += 1
            report["processed"] += 1
            continue

        if _is_duplicate(existing_texts, body):
            item["action"] = "duplicate"
            item["reason"] = "conteúdo já existe no cérebro"
            if not dry_run:
                path.unlink()
                # A remoção faz parte da organização: precisa entrar em um commit.
                brain.store.commit([relpath], f"inbox: remover duplicata {path.stem}")
            report["duplicates"] += 1
            report["processed"] += 1
            report["items"].append(item)
            continue

        if classification["decision"] == "ignore" or classification["confidence"] < 0.5:
            item["action"] = "kept"
            item["reason"] = "confiança insuficiente na classificação — permanece no inbox"
            report["items"].append(item)
            report["kept"] += 1
            report["processed"] += 1
            continue

        # Consolidar: escreve o documento canônico e remove o item do inbox (mesmo commit)
        result = brain.remember(
            body.strip(),
            type_=classification["type"],
            project=classification.get("project"),
            timeline=classification["type"] in ("event", "meeting", "decision"),
            commit=False,
            sync_mem0=False,
            force=True,
        )
        if not result.get("files"):
            item["action"] = "kept"
            item["reason"] = result.get("skipped", "sem destino")
            report["items"].append(item)
            report["kept"] += 1
            report["processed"] += 1
            continue

        item["action"] = "moved"
        item["target"] = result["files"]
        item["type"] = classification["type"]
        report["items"].append(item)
        report["moved"] += 1
        report["processed"] += 1
        if not dry_run:
            path.unlink()
            files = [*result["files"], relpath]
            brain.store.commit(files, f"inbox: organizar {path.stem}")
            brain.mem0.add(
                f"[{classification['type']}] {body.strip()}",
                metadata={
                    "type": classification["type"],
                    "source_file": result["files"][0] if result["files"] else relpath,
                    "source_agent": "hermes",
                    "recorded_at": models.now_iso(),
                },
                infer=False,
            )

    if not dry_run and report["moved"]:
        brain.index.reindex(root, incremental=True)
    return report


def _corpus(root: Path, exclude_prefix: str = "") -> list[str]:
    texts: list[str] = []
    for directory in ("entities", "projects", "areas", "knowledge", "timeline", "resources"):
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            relpath = str(path.relative_to(root))
            if exclude_prefix and relpath.startswith(exclude_prefix):
                continue
            try:
                _, body = models.read_document(path)
            except Exception:
                continue
            texts.append(body)
    return texts


def _is_duplicate(corpus: list[str], body: str) -> bool:
    def tokens(value: str) -> set[str]:
        import re

        return {token for token in re.findall(r"[0-9A-Za-zÀ-ÿ]{4,}", value.lower())}

    new = tokens(body)
    if not new:
        return True
    for text in corpus:
        existing = tokens(text)
        if existing and len(existing & new) / len(new) > 0.85:
            return True
    return False
