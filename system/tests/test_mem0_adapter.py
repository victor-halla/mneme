"""Testes do adapter Mem0: real quando disponível, degradação sempre.

Requisitos 10-13 da Fase 27.
"""

from __future__ import annotations

import http.server
import json
import os
import threading
import unittest

from .helpers import MEM0_HOST, MnemeTestCase, mem0_available

from providers.mem0_provider import Mem0Provider


class _FakeMem0(http.server.BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append({"path": self.path, "body": body, "key": self.headers.get("X-API-Key")})
        payload = {"results": [{"id": "1", "memory": "fake", "score": 0.9}]} if self.path == "/search" else {"ok": True}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # silencia o log do servidor de teste
        return


class TestMem0Adapter(MnemeTestCase):
    # 12) continua funcionando quando o Mem0 está fora
    def test_12_degrades_when_mem0_down(self) -> None:
        self.config_data["providers"]["mem0"]["enabled"] = True
        brain = self._make_brain()  # host 127.0.0.1:9 (porta morta)
        health = brain.mem0.health()
        self.assertFalse(health["ok"])
        receipt = brain.remember("Decidimos manter o Mneme mesmo sem Mem0.", type_="decision", sync_mem0=True)
        self.assertTrue(receipt["ok"], "o Git precisa continuar válido")
        self.assertTrue(receipt["commit"])
        self.assertFalse(receipt["mem0"]["ok"])
        self.assertTrue(receipt["mem0"].get("queued"))
        pending = brain.mem0.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["kind"], "add")

    # 13) retry posterior: a fila é enviada quando o servidor volta
    def test_13_retry_later(self) -> None:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeMem0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def _stop() -> None:
            server.shutdown()
            server.server_close()

        self.addCleanup(_stop)
        host = f"http://127.0.0.1:{server.server_address[1]}"

        self.config_data["providers"]["mem0"]["enabled"] = True
        brain = self._make_brain()
        brain.mem0.enqueue({"kind": "add", "payload": {"messages": [{"role": "user", "content": "pendência"}], "user_id": "t", "agent_id": "a", "infer": False}})
        self.assertEqual(len(brain.mem0.pending()), 1)

        brain.mem0.host = host
        os.environ["MEM0_API_KEY"] = os.environ.get("MEM0_API_KEY", "chave-de-teste")
        result = brain.mem0.flush_pending()
        self.assertEqual(result["flushed"], 1)
        self.assertEqual(result["remaining"], 0)
        self.assertTrue(_FakeMem0.received, "o servidor fake não recebeu nada")
        self.assertEqual(_FakeMem0.received[0]["path"], "/memories")
        self.assertTrue(_FakeMem0.received[0]["key"], "o header X-API-Key precisa ser enviado")
        _FakeMem0.received.clear()

    # 10/11) add e search contra o Mem0 real
    def test_10_11_real_mem0_add_and_search(self) -> None:
        available, reason = mem0_available()
        if not available:
            self.skipTest(f"Mem0 real indisponível: {reason}")
        self.config_data["providers"]["mem0"]["enabled"] = True
        brain = self._make_brain()
        brain.mem0.host = MEM0_HOST
        brain.mem0.user_id = "default"
        brain.mem0.agent_id = "mneme-test"
        marker = "teste automatizado do brain-manager: mem0 integrado ao mneme"
        added = brain.mem0.add(marker, metadata={"type": "test", "source_agent": "mneme-tests"}, infer=False)
        self.assertTrue(added["ok"], added)

        def limpar() -> None:
            """Cleanup registrado já: roda mesmo se um assert falhar depois."""
            atual = brain.mem0.search("teste automatizado brain-manager", top_k=10)
            for item in atual.get("results") or []:
                if marker in (item.get("memory") or ""):
                    brain.mem0.delete(item["id"])

        self.addCleanup(limpar)
        found = brain.mem0.search("teste automatizado brain-manager", top_k=5)
        self.assertTrue(found["ok"], found)
        hits = [item for item in found["results"] if marker in (item.get("memory") or "")]
        self.assertTrue(hits, "o teste precisa encontrar a memória que acabou de criar")
        # Limpeza: teste automatizado nunca deixa lixo na memória real do usuário.
        removed = 0
        for item in hits:
            if brain.mem0.delete(item["id"]).get("ok"):
                removed += 1
        self.assertGreater(removed, 0, "não foi possível limpar a memória de teste")
        after = brain.mem0.search("teste automatizado brain-manager", top_k=5)
        remaining = [
            item for item in (after.get("results") or []) if marker in (item.get("memory") or "")
        ]
        self.assertEqual(remaining, [], "a memória de teste continua no Mem0")


if __name__ == "__main__":
    unittest.main()
