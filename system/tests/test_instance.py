"""Testes da separação entre pacote e instância de dados."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SYSTEM_DIR = Path(__file__).resolve().parents[1]
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from core.config import MnemeConfig, find_root
from core.instance import initialize_instance, migrate_instance


class TestInstanceRoot(unittest.TestCase):
    def test_default_root_is_home_mneme_not_package_checkout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-home-") as temp:
            home = Path(temp)
            instance = home / "mneme"
            instance.mkdir()
            (instance / "mneme.yaml").write_text("mneme:\n  version: 1\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"HOME": str(home)}, clear=False):
                os.environ.pop("MNEME_ROOT", None)
                self.assertEqual(find_root(), instance.resolve())


class TestInstanceInitialization(unittest.TestCase):
    def test_initialize_creates_independent_git_instance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-instance-") as temp:
            root = Path(temp) / "mneme"
            result = initialize_instance(
                root,
                remote="<url do repositório de dados>",
                drive_folder_id="<drive-folder-id>",
            )

            self.assertTrue(result["ok"], result)
            self.assertTrue((root / ".git").is_dir())
            self.assertTrue((root / "mneme.yaml").is_file())
            self.assertTrue((root / "AGENTS.md").is_file())
            for directory in (
                "inbox",
                "entities/people",
                "projects",
                "areas",
                "knowledge/notes",
                "resources",
                "timeline",
                "assets/drive",
                ".mneme",
            ):
                self.assertTrue((root / directory).is_dir(), directory)

            ignore = (root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("**/assets/drive/", ignore)
            self.assertIn(".mneme/", ignore)
            nested = root / "projects/Mneme/assets/drive"
            nested.mkdir(parents=True)
            (nested / "cache.bin").write_bytes(b"binario")
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", "projects/Mneme/assets/drive/cache.bin"],
                cwd=root,
            )
            self.assertEqual(ignored.returncode, 0, "cache aninhado deve ser ignorado")

            import yaml

            config = yaml.safe_load((root / "mneme.yaml").read_text(encoding="utf-8"))
            self.assertNotIn("root", config["mneme"])
            self.assertEqual(config["mneme"]["index"], ".mneme/index.db")
            self.assertEqual(config["git"]["remote"], "<url do repositório de dados>")
            self.assertEqual(
                config["providers"]["assets"]["folder_id"],
                "<drive-folder-id>",
            )
            self.assertEqual(MnemeConfig(root=root).generated_dir, root / ".mneme")

    def test_agents_da_instancia_define_destino_para_dado_pessoal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-instance-") as temp:
            root = Path(temp) / "mneme"

            self.assertTrue(initialize_instance(root)["ok"])
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")

            self.assertIn("Dados que não vão para o Git", agents)
            for categoria in ("identificador", "contato", "endereço", "saúde", "documento"):
                self.assertIn(categoria, agents, categoria)
            self.assertIn("modo 600", agents)
            self.assertIn("~/.hermes", agents)
            self.assertIn("nunca o valor", agents)
            self.assertIn("permissão restrita", agents.lower())

    def test_config_declara_arquivo_de_dados_sensiveis_fora_do_git(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-instance-") as temp:
            root = Path(temp) / "mneme"

            self.assertTrue(initialize_instance(root)["ok"])
            import yaml

            config = yaml.safe_load((root / "mneme.yaml").read_text(encoding="utf-8"))
            sensitive = config["privacy"]["sensitive_file"]

            self.assertTrue(sensitive, "privacy.sensitive_file precisa ser declarado")
            self.assertTrue(sensitive.startswith("~") or sensitive.startswith("/"))
            self.assertFalse(sensitive.startswith("."), "arquivo sensível não pode ficar dentro da instância")

    def test_initialize_refuses_nonempty_destination_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-instance-") as temp:
            root = Path(temp) / "mneme"
            root.mkdir()
            agents = root / "AGENTS.md"
            agents.write_text("conteúdo existente\n", encoding="utf-8")

            result = initialize_instance(root)

            self.assertFalse(result["ok"], result)
            self.assertEqual(agents.read_text(encoding="utf-8"), "conteúdo existente\n")
            self.assertFalse((root / "mneme.yaml").exists())

    def test_initialize_accepts_empty_git_checkout_and_keeps_matching_origin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-instance-") as temp:
            root = Path(temp) / "mneme"
            root.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            remote = "<url do repositório de dados>"
            subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)

            result = initialize_instance(root, remote=remote)

            self.assertTrue(result["ok"], result)
            configured = subprocess.run(
                ["git", "remote", "get-url", "origin"], cwd=root, check=True, capture_output=True, text=True
            ).stdout.strip()
            self.assertEqual(configured, remote)

    def test_initialize_rejects_invalid_git_directory_without_partial_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-instance-invalid-git-") as temp:
            root = Path(temp) / "mneme"
            (root / ".git").mkdir(parents=True)

            result = initialize_instance(root)

            self.assertFalse(result["ok"], result)
            self.assertIn("Git inválido", result["error"])
            self.assertFalse((root / "mneme.yaml").exists())


class TestInstanceMigration(unittest.TestCase):
    def test_migrate_copies_only_canonical_data_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-migrate-") as temp:
            base = Path(temp)
            source = base / "package"
            target = base / "instance"
            (source / "entities/people").mkdir(parents=True)
            (source / "system/core").mkdir(parents=True)
            person = source / "entities/people/person-ana.md"
            person.write_text("---\nid: person-ana\ntype: person\n---\nAna\n", encoding="utf-8")
            (source / "system/core/package.py").write_text("PACKAGE = True\n", encoding="utf-8")
            initialize_instance(target)

            result = migrate_instance(source, target)

            self.assertTrue(result["ok"], result)
            self.assertTrue((target / "entities/people/person-ana.md").is_file())
            self.assertFalse((target / "system/core/package.py").exists())
            self.assertTrue(person.is_file(), "a origem deve ser preservada")

    def test_migrate_refuses_collision_before_copying_any_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-migrate-") as temp:
            base = Path(temp)
            source = base / "package"
            target = base / "instance"
            (source / "knowledge/notes").mkdir(parents=True)
            (source / "knowledge/notes/existing.md").write_text("origem\n", encoding="utf-8")
            (source / "knowledge/notes/new.md").write_text("novo\n", encoding="utf-8")
            initialize_instance(target)
            (target / "knowledge/notes/existing.md").write_text("destino\n", encoding="utf-8")

            result = migrate_instance(source, target)

            self.assertFalse(result["ok"], result)
            self.assertEqual(
                (target / "knowledge/notes/existing.md").read_text(encoding="utf-8"),
                "destino\n",
            )
            self.assertFalse((target / "knowledge/notes/new.md").exists())

    def test_migrate_refuses_secret_sensitivity_before_copying(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-migrate-secret-") as temp:
            base = Path(temp)
            source = base / "package"
            target = base / "instance"
            note = source / "knowledge/notes/classified.md"
            note.parent.mkdir(parents=True)
            note.write_text(
                "---\nid: note-classified\ntype: note\nname: Classified\n"
                "sensitivity: secret\n---\nconteúdo sem padrão de token\n",
                encoding="utf-8",
            )
            initialize_instance(target)

            result = migrate_instance(source, target)

            self.assertFalse(result["ok"], result)
            self.assertIn("sensitivity=secret", result["blocked"][0]["reason"])
            self.assertFalse((target / "knowledge/notes/classified.md").exists())

    def test_migrate_refuses_symlinked_destination_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-migrate-symlink-") as temp:
            base = Path(temp)
            source = base / "package"
            target = base / "instance"
            outside = base / "outside"
            note = source / "knowledge/notes/escaped.md"
            note.parent.mkdir(parents=True)
            note.write_text("---\nid: note-escaped\ntype: note\n---\ntexto\n", encoding="utf-8")
            initialize_instance(target)
            outside.mkdir()
            notes = target / "knowledge/notes"
            notes.rmdir()
            notes.symlink_to(outside, target_is_directory=True)

            result = migrate_instance(source, target)

            self.assertFalse(result["ok"], result)
            self.assertIn("symlink", result["blocked"][0]["reason"])
            self.assertFalse((outside / "escaped.md").exists())


class TestInstanceCli(unittest.TestCase):
    def test_instance_init_runs_before_a_config_exists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-cli-") as temp:
            root = Path(temp) / "mneme"
            command = [
                sys.executable,
                str(SYSTEM_DIR / "scripts/brain.py"),
                "instance",
                "init",
                "--root",
                str(root),
                "--remote",
                "<url do repositório de dados>",
                "--drive-folder-id",
                "<drive-folder-id>",
                "--json",
            ]

            completed = subprocess.run(command, capture_output=True, text=True)

            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            self.assertTrue((root / "mneme.yaml").is_file())

    def test_skill_wrapper_separates_package_path_from_data_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-wrapper-") as temp:
            root = Path(temp) / "mneme"
            initialize_instance(root)
            wrapper = SYSTEM_DIR.parent / "skills/brain-manager/scripts/brain"
            environment = os.environ.copy()
            environment["MNEME_PACKAGE_ROOT"] = str(SYSTEM_DIR.parent)
            environment["MNEME_ROOT"] = str(root)

            completed = subprocess.run(
                [str(wrapper), "validate", "--json"],
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            self.assertIn('"ok": true', completed.stdout)

    def test_human_status_detects_instance_index_in_dot_mneme(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-status-") as temp:
            root = Path(temp) / "mneme"
            initialize_instance(root)
            import yaml

            config_path = root / "mneme.yaml"
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            config["providers"]["mem0"]["enabled"] = False
            config["providers"]["codebase_memory"]["enabled"] = False
            config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            brain = str(SYSTEM_DIR / "scripts/brain.py")
            subprocess.run(
                [sys.executable, brain, "--root", str(root), "reindex", "--full"],
                check=True,
                capture_output=True,
                text=True,
            )

            completed = subprocess.run(
                [sys.executable, brain, "--root", str(root), "status"],
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            self.assertIn("✓ SQLite FTS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
