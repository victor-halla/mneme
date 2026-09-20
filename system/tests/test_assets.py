"""Testes do cache de assets: rclone genérico, erros limpos e cópia real.

Os caminhos de erro usam um rclone de mentira que registra as chamadas; a cópia
de ponta a ponta usa o rclone de verdade com um remote local ad-hoc (`:local:`),
que não exige configuração nem rede.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parents[1]
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import yaml  # noqa: E402

from core.config import MnemeConfig  # noqa: E402
from core.instance import initialize_instance  # noqa: E402
from providers.assets import (  # noqa: E402
    check_assets,
    get_asset_provider,
    rclone_info,
    resolve_remote,
    summarize_error,
    sync_assets,
)

RCLONE_AVAILABLE = bool(shutil.which("rclone"))

FAKE_RCLONE = '''#!/usr/bin/env python3
"""Stub do rclone: responde o mínimo e registra as chamadas."""
import json
import os
import sys

args = sys.argv[1:]
record = os.environ.get("RCLONE_ARGS_OUT")
if record:
    with open(record, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(args) + "\\n")
if not args:
    sys.exit(2)

command = args[0]
if command == "version":
    print("rclone v0.0.0-fake")
elif command == "config":
    print(json.dumps(json.loads(os.environ.get("RCLONE_REMOTES", "{}"))))
elif command == "copy":
    print("Transferred:            2 / 2, 100%")
    if "--dry-run" in args:
        print("NOTICE: pasta/arquivo.pdf: Skipped copy as --dry-run is set (size 10)")
        print("NOTICE: pasta: Skipped set directory modification time as --dry-run is set")
elif command == "lsjson":
    print(json.dumps({"Path": "x", "Size": 3, "MimeType": "text/plain"}))
elif command == "link":
    print("https://exemplo.invalido/link")

sys.exit(int(os.environ.get("RCLONE_EXIT", "0")))
'''


class AssetCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="mneme-assets-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.recorder = self.temp / "rclone-calls.jsonl"
        self.fake = self.temp / "rclone"
        self.fake.write_text(FAKE_RCLONE, encoding="utf-8")
        self.fake.chmod(0o700)
        self.env = dict(os.environ, RCLONE_ARGS_OUT=str(self.recorder))

    # -- helpers ---------------------------------------------------------------

    def make_instance(self, **assets) -> Path:
        merged = {
            "enabled": True,
            "provider": "rclone",
            "remote": "gdrive:",
            "folder_id": "",
            "cache_dir": "assets/drive",
        }
        merged.update(assets)
        root = self.temp / "mneme"
        initialize_instance(root, drive_folder_id=str(merged["folder_id"]))
        path = root / "mneme.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw["providers"]["assets"] = merged
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        return root

    def calls(self) -> list[list[str]]:
        if not self.recorder.is_file():
            return []
        return [json.loads(line) for line in self.recorder.read_text(encoding="utf-8").splitlines()]

    def fake_env(self, remotes: dict | None = None, exit_code: int = 0) -> dict[str, str]:
        return dict(
            self.env,
            RCLONE_REMOTES=json.dumps(remotes if remotes is not None else {"gdrive": {"type": "drive"}}),
            RCLONE_EXIT=str(exit_code),
        )

    # -- caminhos de erro ------------------------------------------------------

    def test_rclone_ausente_falha_com_erro_limpo(self) -> None:
        root = self.make_instance(folder_id="pasta-1")

        result = sync_assets(MnemeConfig(root=root), executable=str(self.temp / "nao-existe"))

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "rclone_ausente")
        self.assertIn("rclone não encontrado", result["error"])
        self.assertIn("rclone", result["hint"])

    def test_remote_nao_configurado_falha_antes_de_copiar(self) -> None:
        root = self.make_instance(folder_id="pasta-1")

        result = sync_assets(
            MnemeConfig(root=root), executable=str(self.fake), environment=self.fake_env(remotes={})
        )

        self.assertFalse(result["ok"])
        self.assertIn("remote não configurado: gdrive:", result["error"])
        self.assertNotIn("copy", [call[0] for call in self.calls()])

    def test_cache_fora_do_padrao_e_recusado(self) -> None:
        root = self.make_instance(folder_id="pasta-1", cache_dir="../outside")

        result = sync_assets(MnemeConfig(root=root), executable=str(self.fake), environment=self.fake_env())

        self.assertFalse(result["ok"])
        self.assertIn("cache_dir", result["error"])
        self.assertFalse((self.temp / "outside").exists())

    def test_drive_sem_folder_id_e_recusado(self) -> None:
        root = self.make_instance(folder_id="")

        result = sync_assets(MnemeConfig(root=root), executable=str(self.fake), environment=self.fake_env())

        self.assertFalse(result["ok"])
        self.assertIn("copiaria a raiz inteira", result["error"])

    # -- caminhos de sucesso com stub -----------------------------------------

    def test_remote_drive_usa_folder_id_e_cache_gitignorado(self) -> None:
        root = self.make_instance(folder_id="pasta-1")

        result = sync_assets(MnemeConfig(root=root), executable=str(self.fake), environment=self.fake_env())

        self.assertTrue(result["ok"], result)
        copy = [call for call in self.calls() if call and call[0] == "copy"][0]
        self.assertEqual(copy[0:2], ["copy", "gdrive:"])
        self.assertIn("--drive-root-folder-id", copy)
        self.assertIn("pasta-1", copy)
        self.assertNotIn("--dry-run", copy)

    def test_dry_run_mostra_o_que_seria_copiado(self) -> None:
        root = self.make_instance(folder_id="pasta-1")

        result = sync_assets(
            MnemeConfig(root=root), executable=str(self.fake), environment=self.fake_env(), dry_run=True
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "dry_run")
        self.assertIn("--dry-run", [call for call in self.calls() if call and call[0] == "copy"][0])
        self.assertEqual(result["would_copy"], ["pasta/arquivo.pdf"])

    def test_backend_nao_drive_ignora_folder_id(self) -> None:
        root = self.make_instance(folder_id="pasta-1", remote="meu-s3:balde")

        result = sync_assets(
            MnemeConfig(root=root),
            executable=str(self.fake),
            environment=self.fake_env(remotes={"meu-s3": {"type": "s3"}}),
        )

        self.assertTrue(result["ok"], result)
        copy = [call for call in self.calls() if call and call[0] == "copy"][0]
        self.assertEqual(copy[1], "meu-s3:balde")
        self.assertNotIn("--drive-root-folder-id", copy)
        self.assertTrue(any("ignorado" in warning for warning in result["warnings"]), result["warnings"])

    def test_remote_da_configuracao_tem_precedencia_sobre_o_padrao(self) -> None:
        root = self.make_instance(folder_id="", remote="outro:prefixo")

        self.assertEqual(resolve_remote(MnemeConfig(root=root)), "outro:prefixo")
        self.assertEqual(resolve_remote(MnemeConfig(root=root), remote="gdrive:"), "gdrive:")

    def test_check_assets_resume_binario_remote_e_tipo(self) -> None:
        root = self.make_instance(folder_id="pasta-1")

        state = check_assets(MnemeConfig(root=root), executable=str(self.fake), environment=self.fake_env())

        self.assertTrue(state["ok"], state)
        self.assertEqual(state["status"], "pronto")
        self.assertEqual(state["remote_type"], "drive")
        self.assertEqual(state["rclone"]["version"], "rclone v0.0.0-fake")

    # -- rclone de verdade -----------------------------------------------------

    @unittest.skipUnless(RCLONE_AVAILABLE, "rclone não instalado neste ambiente")
    def test_copia_real_com_remote_local(self) -> None:
        origem = self.temp / "origem"
        (origem / "pasta").mkdir(parents=True)
        (origem / "a.txt").write_text("documento um", encoding="utf-8")
        (origem / "pasta" / "b.txt").write_text("documento dois", encoding="utf-8")
        root = self.make_instance(remote=f":local:{origem}")

        resultado = sync_assets(MnemeConfig(root=root), executable="rclone")
        cache = root / "assets" / "drive"

        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(resultado["status"], "sincronizado")
        self.assertTrue((cache / "a.txt").is_file())
        self.assertTrue((cache / "pasta" / "b.txt").is_file())
        self.assertEqual(resultado["files_local"], 2)
        self.assertGreater(resultado["bytes_local"], 0)

        # Idempotente: a segunda passada não recopia nem apaga nada.
        novamente = sync_assets(MnemeConfig(root=root), executable="rclone")
        self.assertTrue(novamente["ok"], novamente)
        self.assertTrue((cache / "a.txt").is_file())

    @unittest.skipUnless(RCLONE_AVAILABLE, "rclone não instalado neste ambiente")
    def test_dry_run_real_nao_escreve(self) -> None:
        origem = self.temp / "origem-dry"
        origem.mkdir(parents=True)
        (origem / "a.txt").write_text("documento um", encoding="utf-8")
        root = self.make_instance(remote=f":local:{origem}")

        resultado = sync_assets(MnemeConfig(root=root), executable="rclone", dry_run=True)
        cache = root / "assets" / "drive"

        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(resultado["status"], "dry_run")
        self.assertTrue(any("a.txt" in item for item in resultado["would_copy"]), resultado["would_copy"])
        self.assertEqual([path for path in cache.rglob("*")], [], "dry-run não pode copiar nada")

    @unittest.skipUnless(RCLONE_AVAILABLE, "rclone não instalado neste ambiente")
    def test_provider_envia_recebe_e_apaga_no_backend_local(self) -> None:
        origem = self.temp / "backend"
        origem.mkdir(parents=True)
        (origem / "nota.txt").write_text("conteúdo no backend", encoding="utf-8")
        root = self.make_instance(remote=f":local:{origem}")
        config = MnemeConfig(root=root)

        provider = get_asset_provider(config)
        self.assertEqual(provider.name, "rclone")

        baixado = provider.get("nota.txt", self.temp / "baixado.txt")
        self.assertTrue(baixado["ok"], baixado)
        self.assertEqual((self.temp / "baixado.txt").read_text(encoding="utf-8"), "conteúdo no backend")

        local = self.temp / "novo.txt"
        local.write_text("novo conteúdo", encoding="utf-8")
        enviado = provider.put(local)
        self.assertTrue(enviado["ok"], enviado)
        self.assertTrue((origem / "novo.txt").is_file())

        meta = provider.metadata("novo.txt")
        self.assertTrue(meta["ok"], meta)
        self.assertEqual(meta["metadata"]["Size"], len("novo conteúdo".encode("utf-8")))

        removido = provider.delete("novo.txt")
        self.assertTrue(removido["ok"], removido)
        self.assertFalse((origem / "novo.txt").exists())

        self.assertEqual(provider.share("nota.txt")["status"], "unsupported")

    @unittest.skipUnless(RCLONE_AVAILABLE, "rclone não instalado neste ambiente")
    def test_remote_inexistente_no_rclone_real_da_erro_limpo(self) -> None:
        root = self.make_instance(remote="nao-existe:")

        resultado = sync_assets(MnemeConfig(root=root), executable="rclone")

        self.assertFalse(resultado["ok"])
        self.assertIn("remote não configurado", resultado["error"])
        self.assertNotIn("Traceback", json.dumps(resultado))

    # -- CLI -------------------------------------------------------------------

    def test_cli_check_e_sync_sem_rclone_nao_explodem(self) -> None:
        root = self.make_instance(folder_id="pasta-1")
        for action in ("check", "sync"):
            with self.subTest(action=action):
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(SYSTEM_DIR / "scripts" / "brain.py"),
                        "--root",
                        str(root),
                        "assets",
                        action,
                        "--rclone",
                        str(self.temp / "nao-existe"),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                self.assertEqual(completed.returncode, 1, completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)
                self.assertIn("rclone", completed.stderr + completed.stdout)


class SummarizeErrorTest(unittest.TestCase):
    def test_prefere_a_linha_critica_sem_timestamp(self) -> None:
        log = (
            "2026/09/20 15:26:30 NOTICE: gdrive: aviso irrelevante\n"
            '2026/09/20 15:26:30 CRITICAL: Failed to create file system for "gdrive:": empty token\n'
            "2026/09/20 15:26:30 INFO  : ruído final\n"
        )

        self.assertEqual(
            summarize_error(log),
            'Failed to create file system for "gdrive:": empty token',
        )

    def test_sem_marcador_usa_a_ultima_linha(self) -> None:
        self.assertEqual(summarize_error("linha um\nlinha dois\n"), "linha dois")
        self.assertEqual(summarize_error(""), "")


if __name__ == "__main__":
    unittest.main()
