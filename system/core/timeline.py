"""Timeline: acontecimentos do mundo/projeto (não histórico técnico do Git).

Arquivo: timeline/YYYY/MM/YYYY-MM-DD.md
Evento:  event-YYYYMMDD-NNNN (contador persistido em system/generated/state.json)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from . import models


class Timeline:
    def __init__(self, root: str | Path, state_path: str | Path | None = None):
        self.root = Path(root)
        self.state_path = Path(state_path or (self.root / "system/generated/state.json"))

    # -- estado ---------------------------------------------------------------
    def _state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {"event_counters": {}}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"event_counters": {}}
        data.setdefault("event_counters", {})
        return data

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def next_event_id(self, date_str: str | None = None) -> str:
        date_str = date_str or models.today_iso()
        state = self._state()
        counter = int(state["event_counters"].get(date_str, 0)) + 1
        state["event_counters"][date_str] = counter
        self._save_state(state)
        return f"event-{date_str.replace('-', '')}-{counter:04d}"

    def peek_event_id(self, date_str: str | None = None) -> str:
        date_str = date_str or models.today_iso()
        counter = int(self._state()["event_counters"].get(date_str, 0)) + 1
        return f"event-{date_str.replace('-', '')}-{counter:04d}"

    # -- arquivos -------------------------------------------------------------
    def day_path(self, date_str: str) -> str:
        year, month, _ = date_str.split("-")
        return f"timeline/{year}/{month}/{date_str}.md"

    def _render_day(self, date_str: str, events: list[dict[str, Any]]) -> str:
        meta = models.new_meta(
            f"daily-{date_str}",
            "daily",
            f"Eventos de {date_str}",
            sensitivity="private",
            extra={"date": date_str},
        )
        lines = [f"# {date_str}", ""]
        for event in events:
            lines.append(f"## {event.get('event_id', 'event')} — {event.get('title', 'sem título')}")
            meta_lines = [
                f"- kind: {event.get('kind', 'event')}",
                f"- recorded_at: {event.get('recorded_at', models.now_iso())}",
            ]
            entities = event.get("entities") or []
            if entities:
                meta_lines.append(f"- entities: {', '.join(map(str, entities))}")
            if event.get("project"):
                meta_lines.append(f"- project: {event['project']}")
            lines.extend(meta_lines)
            lines.append("")
            lines.append(str(event.get("body", "")).strip())
            lines.append("")
        return models.join_document(meta, "\n".join(lines))

    def read_events(self, date_str: str) -> list[dict[str, Any]]:
        path = self.root / self.day_path(date_str)
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
        events: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        def flush() -> None:
            if current is None:
                return
            current["body"] = current["body"].strip("\n")
            events.append(current)

        for line in text.splitlines():
            if line.startswith("## "):
                flush()
                head = line[3:].strip()
                event_id, _, title = head.partition(" — ")
                current = {
                    "event_id": event_id.strip(),
                    "title": title.strip(),
                    "kind": "event",
                    "entities": [],
                    "project": None,
                    "body": "",
                }
                continue
            if current is None:
                continue
            # Reconstrói os campos do evento a partir do bloco de metadados.
            field = None
            for key, name in (("kind", "kind"), ("recorded_at", "recorded_at"), ("entities", "entities"), ("project", "project")):
                if line.startswith(f"- {key}:"):
                    field = name
                    break
            if field in ("kind", "recorded_at"):
                value = line.split(":", 1)[1].strip()
                current[field] = None if value in ("", "-") else value
                continue
            if field in ("entities", "project"):
                value = line.split(":", 1)[1].strip()
                if field == "entities":
                    current["entities"] = [item.strip() for item in value.split(",") if item.strip()]
                else:
                    current["project"] = value or None
                continue
            if line.startswith("- ") and not current["body"]:
                # linha de metadado desconhecida no topo do evento: preserva no corpo
                current["body"] += line + "\n"
                continue
            current["body"] += line + "\n"
        flush()
        return events

    def append(
        self,
        title: str,
        body: str = "",
        *,
        kind: str = "event",
        entities: Iterable[str] = (),
        project: str | None = None,
        when: str | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Adiciona um evento ao dia. Não commita — quem chama decide o commit."""
        date_str = when or models.today_iso()
        events = self.read_events(date_str)
        record = {
            "event_id": event_id or self.next_event_id(date_str),
            "title": title.strip(),
            "body": body,
            "kind": kind,
            "entities": list(entities),
            "project": project,
            "recorded_at": models.now_iso(),
        }
        events.append(record)
        relpath = self.day_path(date_str)
        content = self._render_day(date_str, events)
        return {"path": relpath, "content": content, "event": record}

    def recent(self, days: int = 14, today: str | None = None) -> list[dict[str, Any]]:
        """Eventos dos últimos N dias, do mais recente para o mais antigo."""
        base = models.parse_date(today or models.today_iso()) or datetime.now()
        found: list[dict[str, Any]] = []
        for offset in range(days):
            date_str = (base - timedelta(days=offset)).strftime("%Y-%m-%d")
            for event in self.read_events(date_str):
                event["date"] = date_str
                found.append(event)
        return found

    def day_files(self) -> list[Path]:
        base = self.root / "timeline"
        return sorted(base.rglob("*.md")) if base.is_dir() else []
