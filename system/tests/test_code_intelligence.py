"""Testes do provider de inteligência de código (Codebase Memory MCP).

Requisitos 14-20 da Fase 27. Usa a instalação REAL quando presente e degrada
de forma explícita quando não está.
"""

from __future__ import annotations

import unittest

from .helpers import (
    CODE_COMMAND,
    INDEXED_PROJECT,
    INDEXED_REPO,
    MnemeTestCase,
    code_provider_available,
    code_requirements_available,
)

from providers.codebase_memory_provider import CodebaseMemoryProvider


class TestCodeIntelligence(MnemeTestCase):
    def _provider(self, command: str = CODE_COMMAND, enabled: bool = True) -> CodebaseMemoryProvider:
        self.config_data["providers"]["codebase_memory"] = {
            "enabled": enabled,
            "command": command,
            "transport": "cli",
            "timeout": 120,
        }
        brain = self._make_brain()
        return brain.code

    # 14/15) detecção do provider + health
    def test_14_15_provider_detected_and_health(self) -> None:
        available, reason = code_requirements_available()
        if not available:
            self.skipTest(reason)
        provider = self._provider()
        self.assertTrue(provider.available, reason)
        health = provider.health()
        self.assertTrue(health["ok"], health)
        self.assertGreaterEqual(health["repositories"], 1)

    # 16) identificar projeto indexado por caminho de repositório
    def test_16_resolve_indexed_project(self) -> None:
        available, reason = code_requirements_available()
        if not available:
            self.skipTest(reason)
        provider = self._provider()
        resolved = provider.resolve_project(repo_path=INDEXED_REPO)
        self.assertEqual(resolved, INDEXED_PROJECT)

    # 17) busca estrutural
    def test_17_structural_search(self) -> None:
        available, reason = code_requirements_available()
        if not available:
            self.skipTest(reason)
        provider = self._provider()
        result = provider.search(INDEXED_PROJECT, "index", limit=5)
        self.assertTrue(result["ok"], result)
        self.assertIn("data", result)

    # 18) arquitetura
    def test_18_architecture(self) -> None:
        available, reason = code_requirements_available()
        if not available:
            self.skipTest(reason)
        provider = self._provider()
        result = provider.architecture(INDEXED_PROJECT, aspects=["overview"])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result.get("data"), "arquitetura vazia: o grafo não devolveu nada")

    # 19) impacto (blast radius)
    def test_19_impact(self) -> None:
        available, reason = code_requirements_available()
        if not available:
            self.skipTest(reason)
        provider = self._provider()
        result = provider.impact(INDEXED_PROJECT, "index", depth=2)
        self.assertIn("callers", result)
        self.assertIn("callees", result)
        self.assertTrue(result.get("resolved_symbol"), result)
        self.assertTrue(
            (result["callers"].get("items") is not None) and (result["callees"].get("items") is not None),
            "impacto sem listas normalizadas de chamadores/chamados",
        )

    # 20) Mneme continua funcionando sem o provider
    def test_20_mneme_works_without_provider(self) -> None:
        provider = self._provider(command="/caminho/inexistente/codebase-memory-mcp")
        self.assertFalse(provider.available)
        health = provider.health()
        self.assertFalse(health["ok"])
        self.assertEqual(health["status"], "unavailable")
        degraded = provider.search("qualquer", "algo")
        self.assertFalse(degraded["ok"])
        receipt = self.brain.remember("O Mneme opera sem code intelligence.", type_="note", sync_mem0=False)
        self.assertTrue(receipt["ok"])
        self.assertTrue(receipt["files"])

    # Normalização das respostas do MCP (formatos `groups` e `cols/rows`)
    def test_21_mcp_payload_normalization(self) -> None:
        provider = CodebaseMemoryProvider.__new__(CodebaseMemoryProvider)
        groups_payload = {
            "groups": [
                {
                    "qn_prefix": "mneme-core.system.core.store",
                    "file": "system/core/store.py",
                    "rows": [["GitMemoryStore", "Class", "26-266", 1, 0]],
                }
            ]
        }
        flattened = provider._flatten(groups_payload)
        self.assertEqual(
            flattened,
            [{"qn": "mneme-core.system.core.store.GitMemoryStore", "name": "GitMemoryStore",
              "hop": "Class", "file": "system/core/store.py"}],
        )
        candidates = provider._candidates(groups_payload)
        self.assertEqual(candidates[0]["qn"], "mneme-core.system.core.store.GitMemoryStore")
        self.assertEqual(candidates[0]["in"], 1)

        rows_payload = {
            "cols": ["qn", "label", "file", "lines", "rank"],
            "rows": [["mneme-core.system.core.store.GitMemoryStore.commit", "Method", "system/core/store.py", "135-151", -1.0]],
        }
        candidates = provider._candidates(rows_payload)
        self.assertEqual(candidates[0]["name"], "GitMemoryStore.commit".split(".")[-1])
        self.assertEqual(candidates[0]["label"], "Method")
        self.assertEqual(provider._candidates({"cols": [], "rows": []}), [])

        # classes ganham de métodos na escolha do alvo
        ranked = sorted(
            [
                {"qn": "p.a.Cls.__init__", "name": "__init__", "label": "Method", "in": 9},
                {"qn": "p.a.Cls", "name": "Cls", "label": "Class", "in": 0},
                {"qn": "p.a.Cls.run", "name": "run", "label": "Method", "in": 3},
            ],
            key=provider._quality,
        )
        self.assertEqual(ranked[0]["qn"], "p.a.Cls")

    # Context Compiler cita procedência das duas fontes
    def test_20b_context_compiler_provenance(self) -> None:
        self.make_project("Mneme", project_id="project-mneme")
        brain = self._make_brain()
        result = brain.context("project-mneme", query="arquitetura do mneme")
        self.assertIn("## Procedência", result["markdown"])
        sources = {section["source"] for section in result["sections"]}
        self.assertIn("mneme", sources)
        # Projeto de teste não declara codebase em .brain.yaml: portanto a seção de código
        # NÃO deve aparecer (procedência tem de refletir só o que foi realmente consultado).
        self.assertNotIn("code-intelligence", sources, sources)


if __name__ == "__main__":
    unittest.main()
