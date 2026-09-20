"""Mem0Provider — adapter fino sobre o mem0 self-hosted.

Contrato real do servidor (FastAPI):
  POST /search   {"query", "top_k", "filters"}     -> {"results": [...]}
  POST /memories {"messages", "user_id", "agent_id", "infer", "metadata"}
  PUT  /memories/{id} {"text"}
  DELETE /memories/{id}
Auth: header X-API-Key (a chave vive no ambiente, nunca no Git).

Quando o Mem0 está indisponível, o Mneme continua válido: o evento é enfileirado em
system/generated/mem0_pending.jsonl e reprocessado por `brain sync`.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class Mem0Provider:
    name = "mem0"

    def __init__(self, config: Any):
        self.config = config
        block = config.mem0 or {}
        self.host: str = str(block.get("host", "")).rstrip("/")
        self.user_id: str = str(block.get("user_id", "default"))
        self.agent_id: str = str(block.get("agent_id", "mneme"))
        self.timeout: int = int(block.get("timeout", 20))
        self.top_k: int = int(block.get("top_k", 8))
        self.api_key: str = config.mem0_api_key()
        self.enabled: bool = bool(block.get("enabled", True))
        self.pending_path: Path = config.pending_sync_path
        self.last_error: str = ""

    # -- HTTP -----------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.host:
            raise RuntimeError("mem0.host não configurado")
        url = f"{self.host}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body.strip() else {}

    def _redact(self, text: str) -> str:
        """Remove qualquer credencial antes de a mensagem ir para log, erro ou fila.

        O servidor pode refletir headers no corpo do erro; por isso o corpo nunca é
        persistido e a chave é substituída mesmo que apareça em outro formato.
        """
        out = str(text or "")
        if self.api_key:
            out = out.replace(self.api_key, "****")
        out = re.sub(
            r"(?i)\b(x-api-key|authorization|api[_-]?key|bearer)\b\"?\s*[:=]?\s*\"?[A-Za-z0-9\-_.]{6,}",
            r"\1=****",
            out,
        )
        return out[:200]

    def _safe_error(self, exc: Exception) -> str:
        """Mensagem de erro sanitizada, sem corpo de resposta do servidor."""
        if isinstance(exc, urllib.error.HTTPError):
            # Corpo do servidor pode conter a própria credencial refletida: não usar.
            return self._redact(f"HTTP {exc.code}: {exc.reason}")
        return self._redact(f"{type(exc).__name__}: {exc}")

    # -- interface SemanticMemoryProvider -------------------------------------
    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "status": "disabled", "reason": "provider desabilitado no mneme.yaml"}
        if not self.api_key:
            return {
                "ok": False,
                "status": "no_credentials",
                "reason": f"{self.config.mem0.get('api_key_env', 'MEM0_API_KEY')} ausente no ambiente",
            }
        try:
            result = self._request("POST", "/search", {"query": "health check", "top_k": 1, "filters": {"user_id": self.user_id}})
        except Exception as exc:
            self.last_error = self._safe_error(exc)
            return {"ok": False, "status": "unreachable", "reason": self.last_error, "host": self.host}
        results = result.get("results", result if isinstance(result, list) else [])
        health = {
            "ok": True,
            "status": "connected",
            "host": self.host,
            "user_id": self.user_id,
            "sample_results": len(results or []),
        }
        if self.host.startswith("http://") and not any(
            marker in self.host for marker in ("127.0.0.1", "localhost", "[::1]")
        ):
            health["warning"] = (
                "transporte HTTP sem TLS fora do loopback: a chave e o conteúdo trafegam em claro "
                "na rede interna — aceitável apenas em rede confiável, revisar antes de expor"
            )
        return health

    def add(self, text: str, metadata: dict[str, Any] | None = None, infer: bool = False) -> dict[str, Any]:
        """Grava uma memória derivada. Em falha, enfileira para reprocessar."""
        payload = {
            "messages": [{"role": "user", "content": text}],
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "infer": infer,
        }
        if metadata:
            payload["metadata"] = metadata
        try:
            response = self._request("POST", "/memories", payload)
            return {"ok": True, "response": response}
        except Exception as exc:
            error = self._safe_error(exc)
            self.last_error = error
            self.enqueue({"kind": "add", "payload": payload, "error": error})
            return {"ok": False, "queued": True, "error": error}

    def search(self, query: str, top_k: int | None = None, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        effective = {"user_id": self.user_id, **(filters or {})}
        try:
            result = self._request(
                "POST",
                "/search",
                {"query": query, "top_k": int(top_k or self.top_k), "filters": effective},
            )
        except Exception as exc:
            error = self._safe_error(exc)
            self.last_error = error
            return {"ok": False, "results": [], "error": error}
        results = result.get("results", result if isinstance(result, list) else [])
        normalized = [
            {
                "id": item.get("id"),
                "memory": item.get("memory") or item.get("text") or "",
                "score": item.get("score"),
                "metadata": item.get("metadata") or {},
                "created_at": item.get("created_at"),
            }
            for item in (results or [])
            if isinstance(item, dict)
        ]
        return {"ok": True, "results": normalized, "host": self.host}

    def update(self, memory_id: str, text: str) -> dict[str, Any]:
        try:
            self._request("PUT", f"/memories/{memory_id}", {"text": text})
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": self._safe_error(exc)}

    def delete(self, memory_id: str) -> dict[str, Any]:
        try:
            self._request("DELETE", f"/memories/{memory_id}")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": self._safe_error(exc)}

    # -- fila de pendências ---------------------------------------------------
    def enqueue(self, item: dict[str, Any]) -> None:
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        with self.pending_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"queued_at": _now(), **item}, ensure_ascii=False) + "\n")
        os.chmod(self.pending_path, 0o600)

    def pending(self) -> list[dict[str, Any]]:
        if not self.pending_path.is_file():
            return []
        items = []
        for line in self.pending_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return items

    def flush_pending(self, limit: int = 50) -> dict[str, Any]:
        items = self.pending()
        if not items:
            return {"flushed": 0, "failed": 0, "remaining": 0}
        flushed, failed, keep = 0, 0, []
        for index, item in enumerate(items):
            if index >= limit or failed:
                keep.append(item)
                continue
            if item.get("kind") != "add":
                keep.append(item)
                continue
            try:
                self._request("POST", "/memories", item["payload"])
                flushed += 1
            except Exception:
                failed += 1
                keep.append(item)
        if keep:
            self.pending_path.write_text(
                "\n".join(json.dumps(i, ensure_ascii=False) for i in keep) + "\n", encoding="utf-8"
            )
        elif self.pending_path.is_file():
            self.pending_path.unlink()
        return {"flushed": flushed, "failed": failed, "remaining": len(keep)}


def _now() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")
