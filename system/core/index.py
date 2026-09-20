"""Índice textual do Mneme (SQLite FTS5) — apenas Markdown/YAML do cérebro.

Nunca indexa código-fonte: isso é responsabilidade do Codebase Memory MCP.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from . import models

# Diretórios do cérebro que entram no índice (código e system/ ficam fora).
INDEXED_DIRS = ("entities", "projects", "areas", "knowledge", "timeline", "resources", "inbox")
INDEXED_SUFFIXES = (".md", ".yaml", ".yml")
SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
    id UNINDEXED, type UNINDEXED, path UNINDEXED,
    name, tags, relations, body,
    created UNINDEXED, updated UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS files(
    path TEXT PRIMARY KEY,
    sha TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ids(
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    type TEXT NOT NULL
);
"""


def _fts_query(query: str) -> str:
    tokens = re.findall(r"[0-9A-Za-zÀ-ÿ_]+", query or "")
    if not tokens:
        return ""
    return " ".join(f'"{token}"' for token in tokens if token not in {"AND", "OR", "NOT"})


class SearchIndex:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- indexação ------------------------------------------------------------
    @staticmethod
    def _sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _documents(self, root: Path) -> Iterable[Path]:
        for directory in INDEXED_DIRS:
            base = root / directory
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file() and path.suffix.lower() in INDEXED_SUFFIXES:
                    yield path

    def _row_for(self, root: Path, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8", errors="replace")
        relpath = str(path.relative_to(root))
        meta: dict[str, Any] = {}
        body = text
        if path.suffix.lower() in (".md", ".yaml", ".yml"):
            try:
                meta, body = models.split_document(text)
            except Exception:
                meta, body = {}, text
        name = str(meta.get("name") or "")
        if not name:
            for line in body.splitlines():
                if line.startswith("# "):
                    name = line[2:].strip()
                    break
        if not name:
            name = path.stem
        tags = meta.get("tags") or []
        relations = meta.get("relations") or []
        rel_text = " ".join(
            f"{r.get('type', '')} {r.get('target', '')}" if isinstance(r, dict) else str(r) for r in relations
        )
        return {
            "id": str(meta.get("id") or path.stem),
            "type": str(meta.get("type") or path.parent.name),
            "path": relpath,
            "name": name,
            "tags": " ".join(map(str, tags)),
            "relations": rel_text,
            "body": body,
            "created": str(meta.get("created") or ""),
            "updated": str(meta.get("updated") or ""),
            "sha": self._sha(text),
            "mtime": path.stat().st_mtime,
            "size": len(text.encode("utf-8")),
        }

    def reindex(self, root: str | Path, incremental: bool = True) -> dict[str, Any]:
        root = Path(root)
        conn = self.conn
        stats = {"indexed": 0, "updated": 0, "skipped": 0, "removed": 0, "errors": []}
        seen: set[str] = set()
        for path in self._documents(root):
            relpath = str(path.relative_to(root))
            seen.add(relpath)
            try:
                stat = path.stat()
                existing = conn.execute("SELECT sha, mtime FROM files WHERE path = ?", (relpath,)).fetchone()
                if incremental and existing and abs(existing["mtime"] - stat.st_mtime) < 0.001:
                    stats["skipped"] += 1
                    continue
                row = self._row_for(root, path)
                if existing and existing["sha"] == row["sha"]:
                    conn.execute(
                        "UPDATE files SET mtime = ?, indexed_at = ? WHERE path = ?",
                        (stat.st_mtime, models.now_iso(), relpath),
                    )
                    stats["skipped"] += 1
                    continue
                if existing:
                    conn.execute("DELETE FROM docs WHERE path = ?", (relpath,))
                    conn.execute("DELETE FROM ids WHERE path = ?", (relpath,))
                    stats["updated"] += 1
                else:
                    stats["indexed"] += 1
                conn.execute(
                    "INSERT INTO docs(id, type, path, name, tags, relations, body, created, updated)"
                    " VALUES (:id, :type, :path, :name, :tags, :relations, :body, :created, :updated)",
                    row,
                )
                conn.execute(
                    "INSERT OR REPLACE INTO files(path, sha, mtime, size, indexed_at) VALUES (?,?,?,?,?)",
                    (relpath, row["sha"], stat.st_mtime, row["size"], models.now_iso()),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO ids(id, path, type) VALUES (?,?,?)",
                    (row["id"], relpath, row["type"]),
                )
            except Exception as exc:  # índice nunca deve quebrar o fluxo principal
                stats["errors"].append(f"{relpath}: {exc}")
        for row in conn.execute("SELECT path FROM files").fetchall():
            if row["path"] not in seen:
                conn.execute("DELETE FROM docs WHERE path = ?", (row["path"],))
                conn.execute("DELETE FROM files WHERE path = ?", (row["path"],))
                conn.execute("DELETE FROM ids WHERE path = ?", (row["path"],))
                stats["removed"] += 1
        conn.commit()
        return stats

    # -- consultas ------------------------------------------------------------
    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        match = _fts_query(query)
        if not match:
            return []
        sql = (
            "SELECT id, type, path, name, bm25(docs) AS rank,"
            " snippet(docs, 6, '[', ']', ' … ', 14) AS snip"
            " FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?"
        )
        try:
            rows = self.conn.execute(sql, (match, limit)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "id": row["id"],
                "type": row["type"],
                "path": row["path"],
                "name": row["name"],
                "score": round(-float(row["rank"]), 3),
                "snippet": " ".join((row["snip"] or "").split()),
            }
            for row in rows
        ]

    def lookup_id(self, id_: str) -> str | None:
        row = self.conn.execute("SELECT path FROM ids WHERE id = ?", (id_,)).fetchone()
        return row["path"] if row else None

    def stats(self) -> dict[str, Any]:
        docs = self.conn.execute("SELECT COUNT(*) AS n FROM docs").fetchone()["n"]
        ids = self.conn.execute("SELECT COUNT(*) AS n FROM ids").fetchone()["n"]
        by_type = {
            row["type"]: row["n"]
            for row in self.conn.execute("SELECT type, COUNT(*) AS n FROM docs GROUP BY type ORDER BY n DESC")
        }
        return {"documents": docs, "ids": ids, "by_type": by_type, "db": str(self.db_path)}

    def all_ids(self) -> dict[str, dict[str, str]]:
        return {
            row["id"]: {"path": row["path"], "type": row["type"]}
            for row in self.conn.execute("SELECT id, path, type FROM ids")
        }
