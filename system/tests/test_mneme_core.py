"""Testes do núcleo do Mneme: entidades, projetos, eventos, validação, Git e FTS.

Requisitos 1-9 da Fase 27 do plano.
"""

from __future__ import annotations

import unittest

from .helpers import MnemeTestCase

from core import models
from core.projects import create_project


class TestMnemeCore(MnemeTestCase):
    # 1) criar entidade
    def test_01_create_entity(self) -> None:
        receipt = self.brain.remember(
            "Ana Souza trabalha com Bruno na área de dados.",
            type_="relationship",
            entity_id="person-ana-souza",
            sync_mem0=False,
        )
        self.assertTrue(receipt["ok"], receipt)
        path = "entities/people/person-ana-souza.md"
        self.assertIn(path, receipt["files"])
        meta, body = models.read_document(self.tmp / path)
        self.assertEqual(meta["id"], "person-ana-souza")
        self.assertEqual(meta["type"], "person")
        self.assertIn("Ana Souza", body)

    # 2) atualizar entidade (append, sem perder histórico)
    def test_02_update_entity(self) -> None:
        self.brain.remember("Ana Souza é parceira de dados.", entity_id="person-ana-souza", type_="relationship", sync_mem0=False)
        self.brain.remember("Ana Souza assumiu a liderança do programa de IA.", entity_id="person-ana-souza", type_="relationship", sync_mem0=False)
        meta, body = models.read_document(self.tmp / "entities/people/person-ana-souza.md")
        self.assertIn("parceira de dados", body)
        self.assertIn("liderança do programa de IA", body)
        self.assertEqual(meta["updated"], models.today_iso())

    # 3) evitar duplicata simples
    def test_03_avoid_duplicate(self) -> None:
        text = "O padrão de commit do Mneme é semântico e com arquivos explícitos."
        first = self.brain.remember(text, type_="learning", sync_mem0=False)
        second = self.brain.remember(text, type_="learning", sync_mem0=False)
        self.assertEqual(first["document"]["path"], second["document"]["path"])
        self.assertEqual(second["document"]["action"], "duplicate_skipped")
        _, body = models.read_document(self.tmp / second["document"]["path"])
        self.assertEqual(body.count("arquivos explícitos"), 1)  # uma única cópia no corpo

    # 4) criar projeto
    def test_04_create_project(self) -> None:
        result = create_project(self.brain, "Mneme")
        self.assertTrue(result["ok"])
        for expected in ("project.md", "AGENTS.md", "decisions.md", "tasks.md", ".brain.yaml"):
            self.assertTrue(self.exists(f"projects/Mneme/{expected}"), expected)
        self.assertIn("project(mneme): criar estrutura do projeto", self.git_log())

    # 5) criar evento na timeline
    def test_05_create_event(self) -> None:
        receipt = self.brain.remember(
            "Reunião com a equipe de plataforma sobre o corte de escopo.", type_="meeting", sync_mem0=False
        )
        event = receipt["timeline_event"]
        self.assertTrue(event["event_id"].startswith("event-"))
        day = models.today_iso()
        path = f"timeline/{day[:4]}/{day[5:7]}/{day}.md"
        self.assertIn(path, receipt["files"])
        self.assertIn(event["event_id"], self.read(path))

    # 5b) segundo evento no mesmo dia (append preserva metadados do anterior)
    def test_05b_append_second_event_same_day(self) -> None:
        first = self.brain.remember("Reunião com a equipe de dados.", type_="meeting", sync_mem0=False)
        second = self.brain.remember("Decisão do dia: manter o escopo.", type_="decision", project="mneme", sync_mem0=False)
        day = models.today_iso()
        path = f"timeline/{day[:4]}/{day[5:7]}/{day}.md"
        self.assertIn(path, second["files"])
        content = self.read(path)
        self.assertIn(first["timeline_event"]["event_id"], content)
        self.assertIn(second["timeline_event"]["event_id"], content)
        events = self.brain.timeline.read_events(day)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["kind"], "meeting")
        self.assertTrue(events[1]["kind"] in ("decision", "project_change"))
        self.assertEqual(events[0]["title"], "Reunião com a equipe de dados.")
        self.assertTrue(self.brain.validate()["ok"])

    # 6) validar YAML / 7) detectar ID duplicado
    def test_06_validate_and_duplicate_ids(self) -> None:
        self.brain.remember("Fato válido para validação.", type_="note", sync_mem0=False)
        report = self.brain.validate()
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["duplicate_ids"], [])

        meta = models.new_meta("note-x", "note", "X")
        self.write("knowledge/notes/first.md", models.join_document(meta, "conteúdo"))
        self.write("knowledge/notes/second.md", models.join_document(meta, "conteúdo"))
        broken = self.brain.validate()
        self.assertFalse(broken["ok"])
        self.assertEqual(len(broken["duplicate_ids"]), 1)

    # 6b) YAML inválido é reportado
    def test_06b_validate_reports_invalid_yaml(self) -> None:
        self.write("knowledge/notes/quebrado.md", "---\nid: [sem fechar\n---\nconteúdo")
        report = self.brain.validate()
        self.assertFalse(report["ok"])
        self.assertTrue(any("YAML" in error["message"] for error in report["errors"]))

    # 8) commit local
    def test_08_commit_local(self) -> None:
        receipt = self.brain.remember("Decidimos usar Git como fonte canônica.", type_="decision", sync_mem0=False)
        self.assertTrue(receipt["commit"])
        log = self.git_log()
        self.assertIn("Decidimos usar Git como fonte canônica", self.read(receipt["files"][0]) + log)

    # 9) SQLite FTS
    def test_09_sqlite_fts(self) -> None:
        self.brain.remember("O projeto Orquestra usa fila de clearing instantâneo.", type_="note", sync_mem0=False)
        hits = self.brain.search("clearing instantâneo")
        self.assertTrue(hits, "FTS não retornou resultados")
        self.assertTrue(any("clearing" in hit["snippet"].lower() or "clearing" in hit["id"].lower() for hit in hits))

    # Segredos nunca entram
    def test_10_secret_blocked(self) -> None:
        from core import validate as validate_mod

        # o scanner direto precisa barrar antes de qualquer camada de classificação
        problemas = validate_mod.validate_text(
            "knowledge/notes/x.md", "---\nid: note-x\ntype: note\nname: X\n---\n\ntoken: ghp_abcdefghijklmnopqrstuvwxyz0123456789\n"
        )
        self.assertTrue(any("segredo" in p["message"] for p in problemas), problemas)

        receipt = self.brain.remember("Minha senha do banco é hunter2supersegredo", type_="note", sync_mem0=False)
        self.assertFalse(receipt.get("files"))
        report = self.brain.validate()
        self.assertTrue(report["ok"], report["errors"])

    # IDs estáveis, nunca caminho
    def test_11_stable_ids(self) -> None:
        self.assertEqual(models.make_id("person", "João Silva"), "person-joao-silva")
        self.assertTrue(models.is_valid_id("project-mneme"))
        self.assertFalse(models.is_valid_id("Project Mneme"))
        self.assertEqual(models.path_for_id("person-joao-silva"), "entities/people/person-joao-silva.md")


if __name__ == "__main__":
    unittest.main()
