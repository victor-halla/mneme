"""Testes do assistente de instalação (`brain setup`).

O assistente é a única parte do pacote que escreve fora da instância, então os
testes cobrem as duas garantias que importam: nunca sobrescrever dados e nunca
esperar por entrada quando não há terminal.
"""

from __future__ import annotations

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

from core import setup as setup_mod  # noqa: E402

PACKAGE_SRC = SYSTEM_DIR.parent
BRAIN_PY = SYSTEM_DIR / "scripts" / "brain.py"


class SetupTest(unittest.TestCase):
    """Todo efeito colateral acontece dentro de um home temporário."""

    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="mneme-setup-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.profile = self.home / ".hermes" / "profiles" / "dev"
        self.instance = self.home / "mneme"
        self.package_root = self.home / ".local" / "share" / "mneme-package"
        self.env = dict(os.environ, HOME=str(self.home))

    # -- helpers ---------------------------------------------------------------

    def plan(self, **overrides) -> setup_mod.SetupPlan:
        base = setup_mod.SetupPlan(
            instance_root=str(self.instance),
            hermes_profile=str(self.profile),
            package_root=str(self.package_root),
        )
        for key, value in overrides.items():
            setattr(base, key, value)
        return base

    def apply(self, plan: setup_mod.SetupPlan | None = None, **kwargs) -> dict:
        return setup_mod.apply_plan(plan or self.plan(), home=self.home, env=self.env, output=lambda *_: None, **kwargs)

    def config(self) -> dict:
        return yaml.safe_load((self.instance / "mneme.yaml").read_text(encoding="utf-8"))

    # -- criação ---------------------------------------------------------------

    def test_cria_instancia_instala_runtime_e_commita(self) -> None:
        result = self.apply()

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mode"], "criada")
        self.assertTrue((self.instance / "mneme.yaml").is_file())
        self.assertTrue((self.instance / "entities" / "people").is_dir())

        data = self.config()
        self.assertEqual(data["providers"]["mem0"]["host"], "https://api.mem0.ai")
        self.assertEqual(data["providers"]["mem0"]["api"], "platform")
        self.assertEqual(data["providers"]["mem0"]["user_id"], "default")
        self.assertTrue(data["providers"]["mem0"]["enabled"])

        self.assertTrue((self.profile / "skills" / "brain-manager" / "SKILL.md").is_file())
        cli = self.home / ".local" / "bin" / "brain"
        self.assertTrue(cli.is_file())
        self.assertTrue(os.access(cli, os.X_OK))
        self.assertTrue((self.package_root / "system" / "scripts" / "brain.py").is_file())

        log = subprocess.run(
            ["git", "log", "--pretty=format:%s"], cwd=self.instance, capture_output=True, text=True
        ).stdout
        self.assertIn("configuração da instância", log)
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=self.instance, capture_output=True, text=True
        ).stdout.split()
        self.assertIn("mneme.yaml", tracked)

    def test_aplica_drive_e_mem0_sem_remote(self) -> None:
        result = self.apply(
            self.plan(
                drive_folder_id="1HoB7M3S-HMcTEeUFApLbQHO2SrPKeh3b",
                mem0_host="http://172.16.123.19:8888",
                mem0_user="victor",
            )
        )

        self.assertTrue(result["ok"], result)
        data = self.config()
        self.assertEqual(data["providers"]["assets"]["folder_id"], "1HoB7M3S-HMcTEeUFApLbQHO2SrPKeh3b")
        self.assertTrue(data["providers"]["assets"]["enabled"])
        self.assertEqual(data["providers"]["mem0"]["host"], "http://172.16.123.19:8888")
        self.assertEqual(data["providers"]["mem0"]["user_id"], "victor")
        self.assertEqual(data["providers"]["mem0"]["api_key_env"], "MEM0_API_KEY")

    def test_mem0_self_hosted_grava_protocolo_correto(self) -> None:
        self.assertTrue(self.apply(self.plan(install=False, mem0_host="http://172.16.123.19:8888"))["ok"])

        data = self.config()["providers"]["mem0"]
        self.assertEqual(data["host"], "http://172.16.123.19:8888")
        self.assertEqual(data["api"], "self-hosted")

    def test_instalacao_da_skill_para_claude_code(self) -> None:
        claude_home = self.home / ".claude"

        completed = subprocess.run(
            ["bash", str(SYSTEM_DIR / "scripts" / "install_skill.sh"), "--harness", "claude"],
            env=dict(self.env, CLAUDE_HOME=str(claude_home)),
            capture_output=True,
            text=True,
            timeout=180,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((claude_home / "skills" / "brain-manager" / "SKILL.md").is_file())

    def test_setup_instala_para_o_harness_claude(self) -> None:
        plan = self.plan(harness="claude", hermes_profile="")

        result = setup_mod.apply_plan(plan, home=self.home, env=self.env, output=lambda *_: None)

        self.assertTrue(result["ok"], result)
        self.assertTrue((self.home / ".claude" / "skills" / "brain-manager" / "SKILL.md").is_file())

    def _bare_remote(self, with_content: bool = False) -> str:
        """Remote local de verdade: testa clone e consulta sem depender de rede."""

        bare = self.home / ("remoto-com-dados.git" if with_content else "remoto-vazio.git")
        subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
        if with_content:
            seed = self.home / "semente"
            subprocess.run(["git", "clone", str(bare), str(seed)], check=True, capture_output=True)
            (seed / "mneme.yaml").write_text(
                yaml.safe_dump({"providers": {"mem0": {"host": "http://exemplo.invalido:1"}}}, sort_keys=False),
                encoding="utf-8",
            )
            (seed / "knowledge").mkdir(exist_ok=True)
            (seed / "knowledge" / "nota.md").write_text("dado que já existia no remoto", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=seed, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.name=semente", "-c", "user.email=semente@local", "commit", "-m", "dados"],
                cwd=seed,
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "push", "-u", "origin", "main"], cwd=seed, check=True, capture_output=True)
            shutil.rmtree(seed)
        return str(bare)

    def test_remote_vazio_inicializa_e_configura_origin(self) -> None:
        remote = self._bare_remote()

        result = self.apply(self.plan(install=False, instance_remote=remote))

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mode"], "criada")
        self.assertEqual(self.config()["git"]["remote"], remote)
        origin = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=self.instance, capture_output=True, text=True
        ).stdout.strip()
        self.assertEqual(origin, remote)

    def test_remote_com_conteudo_clona_e_adota_sem_perder_dados(self) -> None:
        remote = self._bare_remote(with_content=True)

        result = self.apply(self.plan(install=False, instance_remote=remote))

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mode"], "adotada")
        self.assertEqual((self.instance / "knowledge" / "nota.md").read_text(encoding="utf-8"), "dado que já existia no remoto")
        # Adoção preserva a configuração trazida pelo clone: nada foi informado sobre o Mem0.
        self.assertEqual(self.config()["providers"]["mem0"]["host"], "http://exemplo.invalido:1")

    def test_remote_inacessivel_falha_antes_de_criar_qualquer_coisa(self) -> None:
        ausente = str(self.home / "nao-existe.git")

        result = self.apply(self.plan(install=False, instance_remote=ausente))

        self.assertFalse(result["ok"])
        self.assertTrue(any("inacessível" in erro for erro in result["errors"]), result)
        self.assertFalse(self.instance.exists())

    def test_no_install_nao_toca_no_home(self) -> None:
        result = self.apply(self.plan(install=False))

        self.assertTrue(result["ok"], result)
        self.assertTrue((self.instance / "mneme.yaml").is_file())
        self.assertFalse((self.home / ".local" / "bin" / "brain").exists())

    def test_no_commit_deixa_configuracao_fora_do_git(self) -> None:
        result = self.apply(self.plan(commit=False))

        self.assertTrue(result["ok"], result)
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=self.instance, capture_output=True, text=True
        ).stdout
        self.assertNotIn("mneme.yaml", tracked)

    # -- garantias de segurança ------------------------------------------------

    def test_recusa_destino_nao_vazio(self) -> None:
        self.instance.mkdir(parents=True)
        (self.instance / "anotacoes.txt").write_text("dados do usuário", encoding="utf-8")

        result = self.apply(self.plan(install=False))

        self.assertFalse(result["ok"])
        self.assertTrue(any("não vazio" in erro for erro in result["errors"]), result)
        self.assertEqual((self.instance / "anotacoes.txt").read_text(encoding="utf-8"), "dados do usuário")

    def test_adota_instancia_existente_e_preserva_dados(self) -> None:
        self.assertTrue(self.apply()["ok"])
        note = self.instance / "knowledge" / "notes" / "existente.md"
        note.write_text("conteúdo que não pode ser perdido", encoding="utf-8")

        result = self.apply(self.plan(install=False, mem0_host="http://172.16.123.19:8888"))

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mode"], "adotada")
        self.assertEqual(note.read_text(encoding="utf-8"), "conteúdo que não pode ser perdido")
        self.assertEqual(self.config()["providers"]["mem0"]["host"], "http://172.16.123.19:8888")

    def test_adota_preserva_mem0_quando_nada_e_informado(self) -> None:
        self.assertTrue(
            self.apply(self.plan(install=False, mem0_host="http://172.16.123.19:8888", mem0_user="victor"))["ok"]
        )

        result = self.apply(self.plan(install=False))  # mem0_host None = não mexer

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["changed"], [])
        data = self.config()
        self.assertEqual(data["providers"]["mem0"]["host"], "http://172.16.123.19:8888")
        self.assertEqual(data["providers"]["mem0"]["user_id"], "victor")
        self.assertTrue(data["providers"]["mem0"]["enabled"])

    def test_interativo_sugere_os_valores_da_instancia_existente(self) -> None:
        self.assertTrue(
            self.apply(
                self.plan(
                    install=False,
                    mem0_host="http://172.16.123.19:8888",
                    mem0_user="victor",
                    drive_folder_id="1HoB7M3S-HMcTEeUFApLbQHO2SrPKeh3b",
                )
            )["ok"]
        )

        answers = iter([""] * 9)
        plan = setup_mod.interactive_plan(
            self.plan(install=False),
            home=self.home,
            input_fn=lambda _prompt: next(answers),
            output=lambda *_: None,
        )

        self.assertEqual(plan.mem0_host, "http://172.16.123.19:8888")
        self.assertEqual(plan.mem0_user, "victor")
        self.assertEqual(plan.drive_folder_id, "1HoB7M3S-HMcTEeUFApLbQHO2SrPKeh3b")

    def test_backend_de_assets_vai_para_a_configuracao(self) -> None:
        result = self.apply(
            self.plan(install=False, drive_remote="s3:meu-balde", drive_folder_id="")
        )

        self.assertTrue(result["ok"], result)
        assets = self.config()["providers"]["assets"]
        self.assertEqual(assets["remote"], "s3:meu-balde")
        self.assertEqual(assets["provider"], "rclone")
        self.assertTrue(assets["enabled"])

    def test_remote_de_assets_invalido_e_recusado(self) -> None:
        result = self.apply(self.plan(install=False, drive_remote="sem dois pontos"))

        self.assertFalse(result["ok"])
        self.assertTrue(any("remote do rclone inválido" in erro for erro in result["errors"]), result)

    def test_dry_run_nao_escreve_nada(self) -> None:
        result = self.apply(self.plan(install=False), dry_run=True)

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["dry_run"])
        self.assertFalse(self.instance.exists())

    def test_recusa_entradas_invalidas(self) -> None:
        cases = (
            {"instance_remote": "/caminho/local/sem-url"},
            {"drive_folder_id": "curto"},
            {"mem0_host": "172.16.123.19:8888"},
        )
        for case in cases:
            with self.subTest(case=case):
                result = self.apply(self.plan(install=False, **case))
                self.assertFalse(result["ok"], result)
                self.assertFalse(self.instance.exists(), "destino não pode ser criado quando a validação falha")

    def test_recusa_raiz_igual_ao_checkout_do_pacote(self) -> None:
        result = setup_mod.validate(self.plan(instance_root=str(PACKAGE_SRC), install=False), self.home)
        self.assertTrue(any("checkout do pacote" in erro for erro in result[0]), result)

    # -- modo não interativo ---------------------------------------------------

    def test_sem_terminal_nao_escreve_e_explica(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(BRAIN_PY), "setup"],
            cwd=self.home,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertIn("--non-interactive", completed.stdout)
        self.assertFalse(self.instance.exists())
        self.assertFalse((self.home / ".local").exists())

    def test_non_interactive_aplica_com_flags(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(BRAIN_PY),
                "setup",
                "--non-interactive",
                "--instance-root",
                str(self.instance),
                "--hermes-profile",
                str(self.profile),
                "--package-root",
                str(self.package_root),
                "--mem0-host",
                "http://127.0.0.1:9",
                "--no-mem0",
            ],
            cwd=self.home,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((self.instance / "mneme.yaml").is_file())
        self.assertFalse(self.config()["providers"]["mem0"]["enabled"])

    # -- modo interativo -------------------------------------------------------

    def test_interativo_aceita_padroes_e_desativa_mem0(self) -> None:
        answers = iter(["", "git@github.com:exemplo/dados.git", "", "", "-", "", "", ""])
        lines: list[str] = []
        plan = setup_mod.interactive_plan(
            self.plan(),
            home=self.home,
            input_fn=lambda _prompt: next(answers),
            output=lines.append,
        )

        self.assertEqual(plan.instance_root, str(self.instance))
        self.assertEqual(plan.instance_remote, "git@github.com:exemplo/dados.git")
        self.assertEqual(plan.drive_remote, "gdrive:")
        self.assertEqual(plan.mem0_host, "")
        self.assertEqual(plan.hermes_profile, str(self.profile))
        self.assertTrue(lines)

    def test_interativo_repergunta_valor_invalido(self) -> None:
        answers = iter(
            ["", "isso não é url", "https://github.com/exemplo/dados.git", "", "", "", "", "", ""]
        )
        lines: list[str] = []
        plan = setup_mod.interactive_plan(
            self.plan(),
            home=self.home,
            input_fn=lambda _prompt: next(answers),
            output=lines.append,
        )

        self.assertEqual(plan.instance_remote, "https://github.com/exemplo/dados.git")
        self.assertTrue(any("https://" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
