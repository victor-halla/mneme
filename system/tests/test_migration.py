"""Testes da migração de `~/.hermes` (scan, plan, apply seguro, secrets).

Requisitos 21-24 da Fase 27.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .helpers import MnemeTestCase

from core import migrate_hermes


def _fake_hermes_home(base: Path) -> Path:
    home = base / ".hermes"
    (home / "skills" / "brain-manager").mkdir(parents=True)
    (home / "sessions").mkdir(parents=True)
    (home / "logs").mkdir(parents=True)
    (home / "memories").mkdir(parents=True)

    (home / "config.yaml").write_text("model:\n  default: gpt-5\n", encoding="utf-8")
    (home / ".env").write_text("TELEGRAM_BOT_TOKEN=123456:AAFakeTokenForTestsOnly1234567890\n", encoding="utf-8")
    (home / "sessions" / "abc.json").write_text('{"messages": []}', encoding="utf-8")
    (home / "logs" / "agent.log").write_text("info\n", encoding="utf-8")
    (home / "skills" / "brain-manager" / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    (home / "memories" / "notas-do-usuario.md").write_text(
        "# Notas\n\nO projeto Orquestra usa Git como fonte canônica.\n", encoding="utf-8"
    )
    (home / "projeto-tasteo.md").write_text(
        "---\nid: project-tasteo\ntype: project\nname: Tasteo\n---\n\nRoadmap do projeto Tasteo.\n", encoding="utf-8"
    )
    (home / "credenciais.md").write_text("api_key = abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    return home


class TestMigration(MnemeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.hermes = _fake_hermes_home(self.tmp)

    # 21) scan não altera nada
    def test_21_scan_is_read_only(self) -> None:
        before = self.snapshot()
        report = migrate_hermes.scan(self.hermes)
        after = self.snapshot()
        self.assertEqual(before, after)
        self.assertGreater(report["total_files"], 0)
        self.assertGreaterEqual(report["counts"]["sensitive / never Git"], 2, report["counts"])
        self.assertGreaterEqual(report["counts"]["runtime/config"], 1)

    # 22) plan
    def test_22_plan(self) -> None:
        result = migrate_hermes.plan(self.hermes)
        sources = {entry["source"] for entry in result["entries"]}
        self.assertIn("memories/notas-do-usuario.md", sources)
        self.assertIn("projeto-tasteo.md", sources)
        never = [entry for entry in result["entries"] if entry["action"] == "never_migrate"]
        self.assertTrue(never, "credenciais precisam ser marcadas como never_migrate")
        self.assertTrue(all(entry["destination"] != "NEVER_MIGRATE" or entry["action"] == "never_migrate" for entry in result["entries"]))

    # 23) apply em modo seguro
    def test_23_apply_copy_only(self) -> None:
        result = migrate_hermes.apply(self.hermes, self.brain.config, self.brain.store, limit_files=10)
        self.assertGreaterEqual(result["copied"], 1)
        self.assertTrue(Path(result["manifest"]).is_file())
        manifest = Path(result["manifest"]).read_text(encoding="utf-8")
        self.assertIn("originals_deleted: false", manifest)
        # originais intactos
        self.assertTrue((self.hermes / "memories" / "notas-do-usuario.md").is_file())
        copied = [entry for entry in result["applied"] if entry.get("status") == "copied"]
        for entry in copied:
            self.assertTrue(self.exists(entry["target"]), entry["target"])

    # 24) nunca migrar secrets
    def test_24_never_migrate_secrets(self) -> None:
        result = migrate_hermes.apply(self.hermes, self.brain.config, self.brain.store, limit_files=10)
        copied = [entry for entry in result["applied"] if entry.get("status") == "copied"]
        self.assertTrue(copied)
        for entry in copied:
            self.assertNotIn(".env", entry["source"])
            self.assertNotIn("credenciais", entry["source"])
        for path in self.tmp.rglob("*"):
            if self.hermes in path.parents or path == self.hermes:
                continue  # o falso ~/.hermes é a origem, não o destino
            if path.is_file() and path.suffix in (".md", ".yaml", ".yml"):
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("AAFakeTokenForTestsOnly", text)
                self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", text)
        report = self.brain.validate()
        self.assertTrue(report["ok"], report["errors"])

    # dry-run não escreve
    def test_25_apply_dry_run(self) -> None:
        result = migrate_hermes.apply(self.hermes, self.brain.config, self.brain.store, limit_files=5, dry_run=True)
        self.assertEqual(result["copied"], 0)
        copied_targets = [entry.get("target") for entry in result["applied"] if entry.get("status") == "dry_run"]
        self.assertTrue(copied_targets, "o dry-run precisa listar os destinos planejados")
        for target in copied_targets:
            self.assertFalse(self.exists(target))
        self.assertFalse(Path(result["manifest"]).is_file(), "dry-run não deve escrever manifesto")


if __name__ == "__main__":
    unittest.main()
