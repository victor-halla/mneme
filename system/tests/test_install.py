"""Testes black-box do bootstrap público (`install.sh`)."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = PACKAGE_ROOT / "install.sh"


class BootstrapInstallerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="mneme-bootstrap-", dir=PACKAGE_ROOT.parent))
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)
        self.home = self.workspace / "home"
        self.home.mkdir()
        self.archive = self.workspace / "mneme.tar.gz"
        with tarfile.open(self.archive, "w:gz") as bundle:
            for path in PACKAGE_ROOT.iterdir():
                if path.name in {".git", "__pycache__"}:
                    continue
                bundle.add(path, arcname=f"mneme-0.1.0/{path.name}")
        self.sha256 = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.env = dict(
            os.environ,
            HOME=str(self.home),
            HERMES_HOME=str(self.home / ".hermes" / "profiles" / "dev"),
            MNEME_INSTALL_ROOT=str(self.home / ".local" / "share" / "mneme"),
            MNEME_BIN_DIR=str(self.home / ".local" / "bin"),
        )

    def install(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                str(INSTALLER),
                "--archive-url",
                self.archive.as_uri(),
                "--sha256",
                self.sha256,
                "--non-interactive",
                "--no-mem0",
                "--no-commit",
                *extra,
            ],
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_instala_release_cli_skill_e_instancia(self) -> None:
        completed = self.install()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        current = Path(self.env["MNEME_INSTALL_ROOT"]) / "current"
        self.assertTrue(current.is_symlink())
        self.assertTrue((current / ".venv" / "bin" / "python").is_file())
        self.assertTrue((Path(self.env["MNEME_BIN_DIR"]) / "brain").is_file())
        self.assertTrue((Path(self.env["HERMES_HOME"]) / "skills" / "brain-manager" / "SKILL.md").is_file())
        self.assertTrue((self.home / "mneme" / "mneme.yaml").is_file())

        version_env = dict(self.env)
        version_env.pop("MNEME_INSTALL_ROOT")
        version = subprocess.run(
            [str(Path(self.env["MNEME_BIN_DIR"]) / "brain"), "version"],
            env=version_env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), "Mneme 0.1.0")

    def test_checksum_incorreto_falha_antes_de_criar_destino(self) -> None:
        completed = subprocess.run(
            [
                "bash",
                str(INSTALLER),
                "--archive-url",
                self.archive.as_uri(),
                "--sha256",
                "0" * 64,
                "--non-interactive",
            ],
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("checksum divergente", completed.stderr)
        self.assertFalse(Path(self.env["MNEME_INSTALL_ROOT"]).exists())
        self.assertFalse((self.home / "mneme").exists())

    def test_reinstalacao_remove_arquivo_obsoleto_da_skill(self) -> None:
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        stale = Path(self.env["HERMES_HOME"]) / "skills" / "brain-manager" / "obsoleto.txt"
        stale.write_text("versão anterior", encoding="utf-8")

        second = self.install()

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse(stale.exists())

    def test_execucao_por_pipe_funciona_em_modo_nao_interativo(self) -> None:
        completed = subprocess.run(
            [
                "bash",
                "-s",
                "--",
                "--archive-url",
                self.archive.as_uri(),
                "--sha256",
                self.sha256,
                "--non-interactive",
                "--no-mem0",
                "--no-commit",
            ],
            input=INSTALLER.read_text(encoding="utf-8"),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=180,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((self.home / "mneme" / "mneme.yaml").is_file())

    def test_sem_tty_e_sem_flag_nao_cria_instancia(self) -> None:
        completed = subprocess.run(
            [
                "bash",
                str(INSTALLER),
                "--archive-url",
                self.archive.as_uri(),
                "--sha256",
                self.sha256,
                "--no-mem0",
                "--no-commit",
            ],
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
        )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertIn("Sem terminal interativo", completed.stdout)
        self.assertFalse((self.home / "mneme").exists())


if __name__ == "__main__":
    unittest.main()
