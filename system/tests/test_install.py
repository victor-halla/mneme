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

    def test_shim_da_skill_resolve_o_runtime_versionado(self) -> None:
        completed = self.install()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        shim = Path(self.env["HERMES_HOME"]) / "skills" / "brain-manager" / "scripts" / "brain"
        clean_env = {
            key: value
            for key, value in self.env.items()
            if key not in {"MNEME_PACKAGE_ROOT", "MNEME_INSTALL_ROOT"}
        }

        result = subprocess.run(
            [str(shim), "version"],
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(result.stdout.strip(), "Mneme 0.1.0")

        via_sh = subprocess.run(
            ["sh", str(shim), "version"],
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(via_sh.returncode, 0, via_sh.stderr or via_sh.stdout)
        self.assertEqual(via_sh.stdout.strip(), "Mneme 0.1.0")

    def _archive_with(self, name: str, version: str, extra: str = "") -> tuple[Path, str]:
        """Archive sintético com versão própria e, opcionalmente, um arquivo extra."""

        path = self.workspace / name
        with tarfile.open(path, "w:gz") as bundle:
            for entry in PACKAGE_ROOT.iterdir():
                if entry.name in {".git", "__pycache__", "VERSION"}:
                    continue
                bundle.add(entry, arcname=f"mneme-{version}/{entry.name}")
            version_file = self.workspace / f"VERSION-{version}"
            version_file.write_text(f"{version}\n", encoding="utf-8")
            bundle.add(version_file, arcname=f"mneme-{version}/VERSION")
            if extra:
                payload = self.workspace / f"extra-{version}.md"
                payload.write_text(extra, encoding="utf-8")
                bundle.add(payload, arcname=f"mneme-{version}/docs/extra.md")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _run_install(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(INSTALLER), *args],
            env=env or self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_versao_republicada_com_conteudo_diferente_e_recusada(self) -> None:
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        outro, other_sha = self._archive_with("outro.tar.gz", "0.1.0", extra="conteúdo diferente")

        second = self._run_install(
            "--archive-url",
            outro.as_uri(),
            "--sha256",
            other_sha,
            "--non-interactive",
        )

        self.assertNotEqual(second.returncode, 0)
        self.assertIn("imutáveis", second.stderr)

    def test_archive_com_traversal_e_recusado_sem_escrever_fora(self) -> None:
        malicious = self.workspace / "malicioso.tar.gz"
        with tarfile.open(malicious, "w:gz") as bundle:
            payload = self.workspace / "malicioso.txt"
            payload.write_text("conteúdo hostil", encoding="utf-8")
            bundle.add(payload, arcname="../../fora/malicioso.txt")

        completed = self._run_install(
            "--archive-url",
            malicious.as_uri(),
            "--non-interactive",
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("inseguro", completed.stderr)
        self.assertFalse((self.workspace / "fora").exists())

    def test_archive_com_link_e_recusado(self) -> None:
        linked = self.workspace / "link.tar.gz"
        with tarfile.open(linked, "w:gz") as bundle:
            entry = tarfile.TarInfo("mneme-0.1.0/atalho")
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/etc/passwd"
            bundle.addfile(entry)

        completed = self._run_install(
            "--archive-url",
            linked.as_uri(),
            "--non-interactive",
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("não permitido", completed.stderr)

    def test_falha_na_promocao_restaura_a_versao_anterior(self) -> None:
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        releases = Path(self.env["MNEME_INSTALL_ROOT"]) / "releases"
        skill_parent = Path(self.env["HERMES_HOME"]) / "skills"
        _, sha = self._archive_with("v2.tar.gz", "0.2.0")

        skill_parent.chmod(0o500)
        self.addCleanup(skill_parent.chmod, 0o700)
        failed = self._run_install(
            "--archive-url",
            (self.workspace / "v2.tar.gz").as_uri(),
            "--sha256",
            sha,
            "--non-interactive",
        )
        skill_parent.chmod(0o700)

        self.assertNotEqual(failed.returncode, 0)
        current = Path(self.env["MNEME_INSTALL_ROOT"]) / "current"
        self.assertEqual(os.readlink(current), "releases/0.1.0")
        # A release nova pode ficar pronta em disco, mas nunca parcial nem ativa.
        nova = releases / "0.2.0"
        if nova.exists():
            self.assertTrue((nova / ".venv" / "bin" / "python").is_file())
            self.assertTrue((nova / ".mneme-release.json").is_file())
        instalada = subprocess.run(
            ["bash", "-c", f'PATH="{self.env["MNEME_BIN_DIR"]}:$PATH" brain version'],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(instalada.stdout.strip(), "Mneme 0.1.0")
        self.assertFalse(
            any(p.name.startswith(".brain-manager") for p in skill_parent.iterdir()),
            "staging residual não deve sobrar",
        )
        self.assertTrue((skill_parent / "brain-manager" / "SKILL.md").is_file())

    def test_falha_na_primeira_instalacao_nao_deixa_current(self) -> None:
        skill_parent = Path(self.env["HERMES_HOME"]) / "skills"
        skill_parent.mkdir(parents=True)
        skill_parent.chmod(0o500)
        self.addCleanup(skill_parent.chmod, 0o700)

        failed = self._run_install(
            "--archive-url",
            self.archive.as_uri(),
            "--sha256",
            self.sha256,
            "--non-interactive",
            "--no-mem0",
        )
        skill_parent.chmod(0o700)

        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(
            (Path(self.env["MNEME_INSTALL_ROOT"]) / "current").exists(),
            "promoção incompleta não pode deixar current apontando para release nova",
        )
        self.assertFalse((Path(self.env["MNEME_BIN_DIR"]) / "brain").exists())

    def test_relata_a_instancia_informada(self) -> None:
        outro = self.workspace / "dados"
        completed = self.install("--instance-root", str(outro))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"instância: {outro}", completed.stdout)
        self.assertTrue((outro / "mneme.yaml").is_file())

    def test_harness_invalido_falha_antes_de_promover(self) -> None:
        completed = self._run_install("--harness", "invalido", "--non-interactive")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("harness inválido", completed.stderr)
        self.assertFalse((Path(self.env["MNEME_INSTALL_ROOT"]) / "releases").exists())
        self.assertFalse((Path(self.env["MNEME_BIN_DIR"]) / "brain").exists())

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
        install_root = Path(self.env["MNEME_INSTALL_ROOT"])
        self.assertFalse((install_root / "releases").exists(), "release não pode ser criada")
        self.assertFalse((install_root / "current").exists(), "current não pode ser promovido")
        self.assertFalse((Path(self.env["MNEME_BIN_DIR"]) / "brain").exists(), "CLI não pode ser instalada")
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
