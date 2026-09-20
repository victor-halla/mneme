"""Testes dos dois protocolos do Mem0: cloud (platform) e self-hosted.

Nenhum teste aqui toca a rede: o transporte é substituído para conferir caminho,
cabeçalho de autenticação e corpo da requisição.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parents[1]
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from providers.mem0_provider import (  # noqa: E402
    DEFAULT_PLATFORM_HOST,
    PROTOCOL_PATHS,
    Mem0Provider,
    resolve_protocol,
)


class _FakeConfig:
    """Configuração mínima para exercitar o provider sem disco e sem rede."""

    def __init__(self, block: dict):
        self.mem0 = dict(block)
        self.pending_sync_path = Path(tempfile.mkdtemp(prefix="mneme-mem0-")) / "mem0_pending.jsonl"

    def mem0_api_key(self) -> str:
        return "chave-de-teste"


class Mem0ProtocolTest(unittest.TestCase):
    def provider(self, **block) -> Mem0Provider:
        base = {"enabled": True, "user_id": "u1", "agent_id": "a1", "api_key_env": "MEM0_API_KEY"}
        return Mem0Provider(_FakeConfig({**base, **block}))

    def test_cloud_e_inferido_do_host(self) -> None:
        self.assertEqual(DEFAULT_PLATFORM_HOST, "https://api.mem0.ai")
        self.assertEqual(resolve_protocol(DEFAULT_PLATFORM_HOST), "platform")
        self.assertEqual(resolve_protocol("https://api.mem0.ai"), "platform")
        self.assertEqual(resolve_protocol("http://mem0.exemplo.invalid:8888"), "self-hosted")
        self.assertEqual(resolve_protocol("http://127.0.0.1:8888"), "self-hosted")

    def test_host_parecido_com_o_da_plataforma_nao_vira_cloud(self) -> None:
        self.assertEqual(resolve_protocol("https://mem0.minhaempresa.com"), "self-hosted")
        self.assertEqual(resolve_protocol("api.mem0.ai.minhaempresa.com"), "self-hosted")

    def test_api_declarada_vence_a_inferencia(self) -> None:
        self.assertEqual(resolve_protocol("http://127.0.0.1:8888", "platform"), "platform")

    def test_cloud_autentica_com_token(self) -> None:
        provider = self.provider(host=DEFAULT_PLATFORM_HOST)

        self.assertEqual(provider.protocol, "platform")
        self.assertEqual(provider._headers()["Authorization"], "Token chave-de-teste")
        self.assertNotIn("X-API-Key", provider._headers())

    def test_self_hosted_autentica_com_x_api_key(self) -> None:
        provider = self.provider(host="http://127.0.0.1:8888")

        self.assertEqual(provider.protocol, "self-hosted")
        self.assertEqual(provider._headers()["X-API-Key"], "chave-de-teste")
        self.assertNotIn("Authorization", provider._headers())

    def test_caminhos_de_cada_protocolo(self) -> None:
        casos = (
            (DEFAULT_PLATFORM_HOST, "/v3/memories/add/", "/v3/memories/search/"),
            ("http://127.0.0.1:8888", "/memories", "/search"),
        )
        for host, add_path, search_path in casos:
            with self.subTest(host=host):
                chamadas: list[tuple[str, str]] = []
                provider = self.provider(host=host)

                def fake_request(method, path, payload=None):
                    chamadas.append((method, path))
                    return {"results": [], "ok": True}

                provider._request = fake_request  # type: ignore[method-assign]
                provider.add("texto")
                provider.search("consulta", top_k=1)

                self.assertEqual(chamadas, [("POST", add_path), ("POST", search_path)])

    def test_busca_manda_user_id_dentro_de_filters(self) -> None:
        enviados: list[dict] = []
        provider = self.provider(host=DEFAULT_PLATFORM_HOST)

        def fake_request(method, path, payload=None):
            enviados.append(payload or {})
            return {"results": []}

        provider._request = fake_request  # type: ignore[method-assign]
        provider.search("consulta")

        self.assertEqual(enviados[0]["query"], "consulta")
        self.assertEqual(enviados[0]["filters"], {"user_id": "u1"})

    def test_desabilitado_nao_toca_a_rede_nem_enfileira(self) -> None:
        provider = self.provider(host=DEFAULT_PLATFORM_HOST, enabled=False)

        def explode(*_args, **_kwargs):
            raise AssertionError("não deve chamar a rede com o provider desabilitado")

        provider._request = explode  # type: ignore[method-assign]
        added = provider.add("texto")
        found = provider.search("consulta")

        self.assertTrue(added["disabled"])
        self.assertFalse(added.get("queued"))
        self.assertTrue(found["disabled"])
        self.assertEqual(found["results"], [])
        self.assertFalse(provider.pending_path.exists())

    def test_plataforma_sem_chave_nao_vai_para_a_rede(self) -> None:
        provider = self.provider(host=DEFAULT_PLATFORM_HOST)
        provider.api_key = ""

        def explode(*_args, **_kwargs):
            raise AssertionError("não deve chamar a rede sem credencial")

        provider._request = explode  # type: ignore[method-assign]
        added = provider.add("texto")

        self.assertFalse(added["ok"])
        self.assertFalse(added.get("queued"))
        self.assertIn("MEM0_API_KEY", added["error"])
        self.assertFalse(provider.pending_path.exists())

    def test_self_hosted_sem_chave_ainda_tenta(self) -> None:
        """O servidor OSS pode rodar sem autenticação: ausência de chave não bloqueia."""

        provider = self.provider(host="http://127.0.0.1:8888")
        provider.api_key = ""
        chamadas: list[str] = []

        def fake_request(method, path, payload=None):
            chamadas.append(path)
            return {"results": []}

        provider._request = fake_request  # type: ignore[method-assign]
        provider.search("consulta")

        self.assertEqual(chamadas, ["/search"])

    def test_health_usa_o_caminho_do_protocolo(self) -> None:
        caminhos: list[str] = []
        provider = self.provider(host=DEFAULT_PLATFORM_HOST)

        def fake_request(method, path, payload=None):
            caminhos.append(path)
            return {"results": []}

        provider._request = fake_request  # type: ignore[method-assign]
        health = provider.health()

        self.assertTrue(health["ok"], health)
        self.assertEqual(caminhos, [PROTOCOL_PATHS["platform"]["search"]])

    def test_sem_chave_nao_vai_para_a_rede(self) -> None:
        provider = self.provider(host=DEFAULT_PLATFORM_HOST)
        provider.api_key = ""

        def explode(*_args, **_kwargs):
            raise AssertionError("não deve chamar a rede sem credencial")

        provider._request = explode  # type: ignore[method-assign]
        health = provider.health()

        self.assertEqual(health["status"], "no_credentials")


if __name__ == "__main__":
    unittest.main()
