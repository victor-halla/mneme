"""Testes de roteamento, Context Compiler, inbox e política de memória.

Cobrem a Fase 7 (política de roteamento), Fase 8 (context compiler) e Fase 10-11.
"""

from __future__ import annotations

import unittest

from .helpers import MnemeTestCase

from core import classify as classify_mod
from core import models, routing


class TestRoutingAndContext(MnemeTestCase):
    def test_personal_question_routes_to_mneme_and_mem0(self) -> None:
        result = routing.route("Quem é João Silva?")
        sources = [item["source"] for item in result["sources"]]
        self.assertEqual(result["mode"], "memory")
        self.assertIn("mneme", sources)
        self.assertIn("mem0", sources)

    def test_decision_question(self) -> None:
        result = routing.route("O que decidimos sobre o clearing Pix?")
        sources = [item["source"] for item in result["sources"]]
        self.assertEqual(result["mode"], "decision")
        self.assertIn("mneme", sources)
        self.assertIn("timeline", sources)

    def test_timeline_question(self) -> None:
        result = routing.route("O que aconteceu ontem no projeto?")
        self.assertEqual(result["mode"], "timeline")
        self.assertEqual(result["sources"][0]["source"], "timeline")

    def test_code_question(self) -> None:
        result = routing.route("Quem chama processPayment()?")
        self.assertEqual(result["mode"], "code")
        self.assertEqual(result["sources"][0]["source"], "codebase-memory")

    def test_impact_question(self) -> None:
        result = routing.route("Se eu alterar processPayment(), o que pode quebrar?")
        self.assertEqual(result["mode"], "code-impact")
        self.assertEqual(result["sources"][0]["source"], "codebase-memory")

    def test_why_code_question(self) -> None:
        result = routing.route("Por que processPayment() foi feito desta forma?")
        sources = [item["source"] for item in result["sources"]]
        self.assertEqual(result["mode"], "why-code")
        self.assertIn("mneme", sources)
        self.assertIn("codebase-memory", sources)
        self.assertIn("git-history", sources)

    def test_project_status_question(self) -> None:
        result = routing.route("Onde estamos no projeto Mneme?")
        sources = [item["source"] for item in result["sources"]]
        self.assertEqual(result["mode"], "status")
        self.assertIn("codebase-memory", sources)


class TestMemoryPolicy(MnemeTestCase):
    def test_explicit_save_command(self) -> None:
        result = classify_mod.classify_text("guarde isso: o fornecedor X foi aprovado", self.config_data["memory_policy"])
        self.assertEqual(result["decision"], "always")

    def test_explicit_block_command(self) -> None:
        result = classify_mod.classify_text("não precisa guardar isso, é temporário", self.config_data["memory_policy"])
        self.assertEqual(result["decision"], "ignore")

    def test_decision_detected(self) -> None:
        result = classify_mod.classify_text("Decidimos migrar o clearing para Kafka.", self.config_data["memory_policy"])
        self.assertEqual(result["type"], "decision")
        self.assertEqual(result["decision"], "always")

    def test_temporary_request_is_not_persisted(self) -> None:
        result = classify_mod.classify_text("me diga as horas, isso é temporário", self.config_data["memory_policy"])
        self.assertEqual(result["decision"], "ignore")

    def test_secret_detected_is_never_persisted(self) -> None:
        result = classify_mod.classify_text("minha api_key = abcdefghijklmnop1234", self.config_data["memory_policy"])
        self.assertEqual(result["sensitivity"], "secret")
        self.assertEqual(result["decision"], "ignore")


class TestContextCompiler(MnemeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.brain.remember(
            "Decidimos que o Mneme usa Git como fonte canônica e Mem0 como memória semântica.",
            type_="decision",
            project="mneme",
            sync_mem0=False,
        )

    def test_context_includes_project_sections_and_provenance(self) -> None:
        self.make_project("Mneme", project_id="project-mneme")
        brain = self._make_brain()
        result = brain.context("project-mneme", query="arquitetura e decisões")
        titles = [section["title"] for section in result["sections"]]
        self.assertTrue(any("Estado atual" in title for title in titles), titles)
        self.assertTrue(any("Decisões" in title for title in titles), titles)
        self.assertIn("Procedência", result["markdown"])
        self.assertLessEqual(result["used_tokens"], result["budget_tokens"])

    def test_budget_truncates(self) -> None:
        self.make_project("Mneme", project_id="project-mneme")
        brain = self._make_brain()
        result = brain.context("project-mneme", query="x", budget=60)
        self.assertLessEqual(result["used_tokens"], 60 * 3)
        self.assertIn("omitidas por orçamento", result["markdown"])

    def test_unresolved_scope_is_reported(self) -> None:
        result = self.brain.context("escopo-inexistente")
        self.assertEqual(result["resolved"]["kind"], "unknown")
        self.assertIn("Escopo não resolvido", result["markdown"])


class TestInboxOrganize(MnemeTestCase):
    def test_organize_moves_and_detects_duplicates(self) -> None:
        self.write(
            "inbox/20260919-120000-nota.md",
            models.join_document(
                models.new_meta("note-inbox-1", "note", "Nota do inbox"),
                "Decidimos adoentar o rollout do produto por duas semanas.",
            ),
        )
        brain = self._make_brain()
        report = brain.organize()
        self.assertEqual(report["processed"], 1)
        self.assertEqual(report["moved"], 1)
        self.assertFalse(self.exists("inbox/20260919-120000-nota.md"))

        # Duplicata: o mesmo conteúdo reenviado ao inbox é descartado
        self.write(
            "inbox/20260919-130000-nota2.md",
            models.join_document(
                models.new_meta("note-inbox-2", "note", "Nota do inbox"),
                "Decidimos adoentar o rollout do produto por duas semanas.",
            ),
        )
        second = self._make_brain().organize()
        # Duas duplicatas: o arquivo reenviado e o registro que o `remember` da rodada anterior
        # deixou no inbox por não haver projeto resolvido (o texto já está na timeline).
        self.assertEqual(second["duplicates"], 2)
        self.assertFalse(self.exists("inbox/20260919-130000-nota2.md"))

    def test_organize_dry_run_keeps_files(self) -> None:
        self.write(
            "inbox/20260919-140000-nota.md",
            models.join_document(models.new_meta("note-inbox-3", "note", "Nota"), "Aprendi que o FTS do SQLite basta."),
        )
        report = self._make_brain().organize(dry_run=True)
        self.assertEqual(report["moved"], 1)
        self.assertTrue(self.exists("inbox/20260919-140000-nota.md"))


if __name__ == "__main__":
    unittest.main()
