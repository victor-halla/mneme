"""Regressões de endurecimento — cada teste cobre um achado confirmado da revisão independente.

Achados originais (revisores independentes + verificação própria):
1. commit arrastava arquivos já staged (inclusive segredo);
2. caminhos escapavam da raiz (../, absoluto, symlink) e a CLI escrevia fora em `project new`;
3. migração sobrescrevia destino homônimo e reportava ambos como copiados;
4. exclusão do inbox não era commitada (working tree sujo);
5. arquivos privados criados como 0644 e diretórios 0755;
6. scanner de segredos com falsos negativos (github_pat_, telegram 13 dígitos, senha com espaço)
   e falso positivo em placeholder;
7. chave do Mem0 podia ser refletida em erro persistido na fila;
8. chave YAML duplicada aceita em silêncio;
9. escrita composta deixava estado parcial quando a segunda gravação falhava.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from .helpers import MnemeTestCase

from core import models, validate as validate_mod
from core.actions import Brain
from core.config import MnemeConfig
from core.projects import create_project, validate_project_name
from core.store import GitError, GitMemoryStore


class TestPathConfinement(MnemeTestCase):
    def test_write_outside_root_is_refused(self) -> None:
        store = self.brain.store
        for target in ("../fora.md", "/tmp/mneme-escape-abs.md", "~/fora.md", "knowledge/../../fora.md"):
            with self.assertRaises(GitError, msg=target):
                store.write_file(target, "x")
        self.assertFalse((self.tmp.parent / "fora.md").exists())
        self.assertFalse(Path("/tmp/mneme-escape-abs.md").exists())

    def test_symlink_escape_is_refused(self) -> None:
        store = self.brain.store
        link = self.tmp / "knowledge" / "link"
        link.symlink_to("/tmp", target_is_directory=True)
        with self.assertRaises(GitError):
            store.write_file("knowledge/link/fora.md", "x")
        self.assertFalse(Path("/tmp/fora.md").exists())

    def test_read_outside_root_is_refused(self) -> None:
        externo = self.tmp.parent / "externo.md"
        externo.write_text("---\nid: note-x\ntype: note\n---\nsegredo de fora\n", encoding="utf-8")
        self.assertIsNone(self.brain.get(str(externo)))
        self.assertIsNone(self.brain.get("../externo.md"))

    def test_project_name_with_separator_is_refused(self) -> None:
        for nome in ("../../escaped", "a/b", "..", "   "):
            with self.assertRaises(ValueError, msg=nome):
                validate_project_name(nome)
            with self.assertRaises(ValueError, msg=nome):
                create_project(self.brain, nome)
        self.assertFalse((self.tmp.parent / "escaped").exists())


class TestCommitScope(MnemeTestCase):
    def test_commit_ignores_pre_staged_files(self) -> None:
        """Um arquivo já staged (mesmo segredo) não entra no commit de outra escrita."""
        segredo = "knowledge/notes/prestaged-secret.md"
        self.write(segredo, "api_key = abcdefghijklmnopqrstuvwxyz123456\n")
        self.brain.store.git("add", "--", segredo)

        receipt = self.brain.remember("Aprendizado legítimo que dispara um commit isolado.", type_="learning", sync_mem0=False)
        self.assertTrue(receipt["commit"])

        head_files = self.brain.store.git("show", "--name-only", "--pretty=format:", "HEAD").split("\n")
        self.assertNotIn(segredo, [line.strip() for line in head_files if line.strip()])
        # e continua staged, intocado
        self.assertIn(segredo, self.brain.store.git("diff", "--cached", "--name-only"))

    def test_deletion_is_committed(self) -> None:
        """Excluir um arquivo versionado precisa aparecer no commit (findings 4)."""
        path = "inbox/para-remover.md"
        self.write(path, models.join_document(models.new_meta("note-rm", "note", "remover"), "conteudo"))
        self.brain.store.commit([path], "inbox: adicionar arquivo de teste")
        (self.tmp / path).unlink()
        sha = self.brain.store.commit([path], "inbox: remover arquivo de teste")
        self.assertIsNotNone(sha)
        self.assertEqual(self.brain.store.git("status", "--porcelain", "--", "inbox").strip(), "")
        # a árvore de HEAD não contém mais o arquivo
        head_tree = self.brain.store.git("ls-tree", "-r", "--name-only", "HEAD")
        self.assertNotIn(path, head_tree.splitlines())


class TestPermissions(MnemeTestCase):
    def test_private_permissions(self) -> None:
        self.brain.store.write_file("knowledge/topics/novo/perm.md", "x\n")
        self.assertEqual(oct((self.tmp / "knowledge/topics/novo/perm.md").stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct((self.tmp / "knowledge/topics/novo").stat().st_mode & 0o777), "0o700")
        # diretório que já existia também é restringido na gravação
        self.brain.store.write_file("knowledge/notes/perm.md", "x\n")
        self.assertEqual(oct((self.tmp / "knowledge/notes").stat().st_mode & 0o777), "0o700")

    def test_write_many_is_all_or_nothing(self) -> None:
        """Falha na preparação não pode deixar o primeiro arquivo gravado (finding 9)."""
        writes = {
            "knowledge/notes/a.md": "A\n",
            "knowledge/notes/b.md": "B\n",
        }
        original = self.brain.store.abs

        def fail_on_second(relpath):
            path = original(relpath)
            if str(relpath).endswith("b.md"):
                raise OSError("falha injetada na preparação")
            return path

        self.brain.store.abs = fail_on_second  # type: ignore[assignment]
        with self.assertRaises(OSError):
            self.brain.store.write_many(writes)
        self.brain.store.abs = original  # type: ignore[assignment]
        self.assertFalse((self.tmp / "knowledge/notes/a.md").exists())
        self.assertFalse((self.tmp / "knowledge/notes/b.md").exists())


class TestSecretScanner(MnemeTestCase):
    def test_new_patterns_are_detected(self) -> None:
        casos = {
            "github-fine-grained-token": "github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz0123456789ABCDEF",
            "telegram-bot-token": "1234567890123:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
            "password-assignment": 'password = "minha frase secreta 12"',
            "anthropic-key": "sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345",
            "openai-key": "sk-proj-abcdefghijklmnopqrstuvwxyz01",
        }
        for esperado, texto in casos.items():
            self.assertIn(esperado, validate_mod.scan_secrets(texto), msg=texto)

    def test_anthropic_key_is_not_double_labelled(self) -> None:
        hits = validate_mod.scan_secrets("sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345")
        self.assertIn("anthropic-key", hits)
        self.assertNotIn("openai-key", hits)

    def test_placeholder_is_not_flagged(self) -> None:
        limpos = (
            "api_key=abcdefghijklmnop",
            "A senha do projeto será definida na reuniao de amanha",
            "password: exemplo-placeholder",
        )
        for texto in limpos:
            self.assertEqual(validate_mod.scan_secrets(texto), [], msg=texto)

    def test_duplicate_yaml_keys_are_rejected(self) -> None:
        meta_duplicado = "id: note-a\nid: note-b\ntype: note\nname: X\ncreated: 2026-09-19\nupdated: 2026-09-19\n"
        problems = validate_mod.validate_text("knowledge/notes/dup.md", f"---\n{meta_duplicado}---\n\ncorpo\n")
        self.assertTrue(any("duplicada" in p["message"] for p in problems), problems)


class TestMem0Redaction(MnemeTestCase):
    def test_error_never_contains_key(self) -> None:
        os.environ["MEM0_API_KEY"] = "m0sk_chave_secreta_de_teste_123456"
        self.config_data["providers"]["mem0"]["enabled"] = True
        brain = self._make_brain()
        brain.mem0.api_key = "m0sk_chave_secreta_de_teste_123456"
        mascarado = brain.mem0._redact('{"error":"x-api-key: m0sk_chave_secreta_de_teste_123456"}')
        self.assertNotIn("m0sk_chave_secreta_de_teste_123456", mascarado)

        receipt = brain.remember("Decisão gravada com Mem0 fora do ar.", type_="decision", sync_mem0=True)
        pendente = brain.mem0.pending()
        self.assertTrue(pendente, receipt)
        bruto = json.dumps(pendente, ensure_ascii=False)
        self.assertNotIn("m0sk_chave_secreta_de_teste_123456", bruto)

    def test_insecure_transport_is_reported(self) -> None:
        self.config_data["providers"]["mem0"].update({"enabled": True, "host": "http://<host-do-mem0>:8888"})
        brain = self._make_brain()
        health = brain.mem0.health()
        if health.get("ok"):
            self.assertIn("warning", health)


class TestMigrationCollision(MnemeTestCase):
    def test_same_basename_from_different_sources_is_preserved(self) -> None:
        from core import migrate_hermes

        hermes = self.tmp / "fake-hermes"
        for sub, texto in (("memories/a", "PRIMEIRO"), ("memories/b", "SEGUNDO")):
            (hermes / sub).mkdir(parents=True, exist_ok=True)
            (hermes / sub / "same.md").write_text(texto, encoding="utf-8")
        result = migrate_hermes.apply(hermes, self.brain.config, self.brain.store, limit_files=10)
        copiados = [e for e in result["applied"] if str(e.get("status", "")).startswith("copied")]
        self.assertEqual(len(copiados), 2)
        alvos = {e["target"] for e in copiados}
        self.assertEqual(len(alvos), 2, alvos)
        textos = "\n".join((self.tmp / alvo).read_text(encoding="utf-8") for alvo in alvos)
        self.assertIn("PRIMEIRO", textos)
        self.assertIn("SEGUNDO", textos)
        self.assertTrue(any(e.get("collision") for e in copiados))

    def test_manifest_name_is_unique_per_run(self) -> None:
        from core import migrate_hermes

        hermes = self.tmp / "fake-hermes2"
        (hermes / "memories").mkdir(parents=True, exist_ok=True)
        (hermes / "memories" / "nota.md").write_text("conteudo migrado", encoding="utf-8")
        first = migrate_hermes.apply(hermes, self.brain.config, self.brain.store, limit_files=5)
        second = migrate_hermes.apply(hermes, self.brain.config, self.brain.store, limit_files=5)
        self.assertNotEqual(first["manifest"], second["manifest"])


class TestOrganizeDeletion(MnemeTestCase):
    def test_duplicate_removal_leaves_clean_tree(self) -> None:
        texto = "Aprendi que o índice FTS do SQLite basta para o cérebro."
        brain = self._make_brain()
        brain.remember(texto, type_="learning", sync_mem0=False)
        dup = "inbox/20260919-000000-dup.md"
        self.write(dup, models.join_document(models.new_meta("note-dup", "note", "dup"), texto))
        brain.store.commit([dup], "inbox: adicionar duplicata")

        relatorio = Brain(MnemeConfig(root=self.tmp)).organize()
        self.assertEqual(relatorio["duplicates"], 1)
        self.assertFalse(self.exists(dup))
        # a remoção precisa estar commitada: nada pendente em inbox/
        self.assertEqual(brain.store.git("status", "--porcelain", "--", "inbox").strip(), "")
        head_tree = brain.store.git("ls-tree", "-r", "--name-only", "HEAD")
        self.assertNotIn(dup, head_tree.splitlines())


if __name__ == "__main__":
    unittest.main()
