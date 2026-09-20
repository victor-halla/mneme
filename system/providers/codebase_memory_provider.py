"""CodebaseMemoryProvider — wrapper fino sobre o Codebase Memory MCP instalado.

Nomes de tools confirmados na instalação real (DeusData/codebase-memory-mcp, transporte CLI):

    index_repository  index_status  list_projects  delete_project
    search_graph      search_code   trace_path     detect_changes
    query_graph       get_graph_schema  get_code_snippet  get_architecture
    check_index_coverage  manage_adr  ingest_traces

Nada aqui reimplementa análise de código: o provider apenas traduz chamadas.
Se o binário não existir, degrada de forma explícita (`available: false`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class CodebaseMemoryProvider:
    name = "codebase-memory"

    TOOLS = (
        "index_repository",
        "index_status",
        "list_projects",
        "delete_project",
        "search_graph",
        "search_code",
        "trace_path",
        "detect_changes",
        "query_graph",
        "get_graph_schema",
        "get_code_snippet",
        "get_architecture",
        "check_index_coverage",
        "manage_adr",
        "ingest_traces",
        "get_file_outline",
        "compare_graphs",
        "get_architecture",
    )

    def __init__(self, config: Any):
        block = config.codebase_memory or {}
        self.enabled: bool = bool(block.get("enabled", True))
        self.command: str = str(block.get("command", "codebase-memory-mcp"))
        self.timeout: int = int(block.get("timeout", 120))
        self.transport: str = str(block.get("transport", "cli"))
        self.last_error: str = ""

    # -- disponibilidade ------------------------------------------------------
    @property
    def binary(self) -> str | None:
        if os.path.isabs(self.command):
            return self.command if Path(self.command).is_file() else None
        return shutil.which(self.command)

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.binary and self.transport == "cli")

    def call(self, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Executa uma tool do MCP via CLI. Devolve sempre um dict com 'ok'."""
        if not self.enabled:
            return {"ok": False, "error": "provider desabilitado (mneme.yaml: providers.codebase_memory.enabled)"}
        binary = self.binary
        if not binary:
            return {"ok": False, "error": f"binário não encontrado: {self.command}"}
        if tool not in self.TOOLS:
            return {"ok": False, "error": f"tool desconhecida: {tool}"}
        command = [binary, "cli", "--quiet", tool, json.dumps(args or {})]
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.last_error = f"timeout de {self.timeout}s em {tool}"
            return {"ok": False, "error": self.last_error, "tool": tool}
        if proc.returncode != 0:
            self.last_error = (proc.stderr or proc.stdout).strip()[:400]
            return {"ok": False, "error": self.last_error or f"exit {proc.returncode}", "tool": tool}
        raw = (proc.stdout or "").strip()
        if not raw:
            return {"ok": True, "data": {}, "tool": tool}
        try:
            return {"ok": True, "data": json.loads(raw), "tool": tool}
        except json.JSONDecodeError:
            # Alguns tools devolvem texto/tree; preserva como está.
            return {"ok": True, "data": {"text": raw}, "tool": tool}

    # -- interface CodeIntelligenceProvider -----------------------------------
    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "status": "disabled", "reason": "desabilitado no mneme.yaml"}
        if not self.binary:
            return {"ok": False, "status": "unavailable", "reason": f"binário não encontrado: {self.command}"}
        result = self.call("list_projects", {"format": "json", "limit": 100})
        if not result.get("ok"):
            return {"ok": False, "status": "error", "reason": result.get("error")}
        projects = result["data"].get("projects", []) if isinstance(result["data"], dict) else []
        return {"ok": True, "status": "connected", "repositories": len(projects), "binary": self.binary}

    def list_repositories(self) -> list[dict[str, Any]]:
        result = self.call("list_projects", {"detail": "stats", "format": "json", "limit": 200})
        if not result.get("ok"):
            return []
        data = result["data"]
        return data.get("projects", []) if isinstance(data, dict) else []

    def resolve_project(self, repo_path: str | Path | None = None, hint: str | None = None) -> str | None:
        """Mapeia caminho/hint de repositório para o nome do projeto indexado."""
        repos = self.list_repositories()
        if repo_path:
            target = str(Path(repo_path).resolve())
            for repo in repos:
                root = str(Path(str(repo.get("root_path", ""))).resolve()) if repo.get("root_path") else ""
                if root and (root == target or target.startswith(root + "/")):
                    return str(repo.get("name"))
        if hint:
            needle = str(hint).lower()
            for repo in repos:
                if needle and needle in str(repo.get("name", "")).lower():
                    return str(repo.get("name"))
        return None

    def status(self, project: str) -> dict[str, Any]:
        return self.call("index_status", {"project": project, "format": "json"})

    def search(self, project: str, query: str, limit: int = 25) -> dict[str, Any]:
        return self.call("search_graph", {"project": project, "query": query, "limit": limit, "format": "json"})

    def architecture(self, project: str, aspects: list[str] | None = None, path: str | None = None) -> dict[str, Any]:
        args: dict[str, Any] = {"project": project, "format": "json", "aspects": aspects or ["overview"]}
        if path:
            args["path"] = path
        return self.call("get_architecture", args)

    @staticmethod
    def _candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Normaliza os dois formatos de resposta do search_graph.

        - busca BM25 (`query`):  {"cols": ["qn", "label", "file", ...], "rows": [[...], ...]}
        - busca por regex:       {"groups": [{"qn_prefix", "file", "rows": [[name, label, lines, in, out]]}]}
          e a regra documentada: qn = qn_prefix ? prefix + "." + name : name
        """
        data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        if not isinstance(data, dict):
            return []
        out: list[dict[str, Any]] = []
        groups = data.get("groups")
        if groups:
            for group in groups:
                prefix = str(group.get("qn_prefix") or "")
                file_path = group.get("file")
                for row in group.get("rows") or []:
                    if not row:
                        continue
                    name = str(row[0])
                    label = str(row[1]) if len(row) > 1 else ""
                    inbound = row[3] if len(row) > 3 else None
                    outbound = row[4] if len(row) > 4 else None
                    out.append({
                        "qn": f"{prefix}.{name}" if prefix else name,
                        "name": name,
                        "label": label,
                        "file": file_path,
                        "in": inbound,
                        "out": outbound,
                    })
            return out
        cols = list(data.get("cols") or [])
        index = {name: position for position, name in enumerate(cols)}
        for row in data.get("rows") or []:
            qn = str(row[index.get("qn", 0)])
            out.append({
                "qn": qn,
                "name": str(row[index["name"]]) if "name" in index else qn.split(".")[-1],
                "label": str(row[index["label"]]) if "label" in index else "",
                "file": row[index["file"]] if "file" in index else None,
            })
        return out

    def search_symbols(self, project: str, target: str, limit: int = 10) -> list[dict[str, Any]]:
        return self._candidates(self.search(project, target, limit=limit))

    @staticmethod
    def _quality(candidate: dict[str, Any]) -> tuple[int, int, int]:
        """Ordena candidatos: classe/interface > função > método > dunder; empate por grau de entrada."""
        name = str(candidate.get("name") or "")
        label = str(candidate.get("label") or "")
        if name.startswith("__"):
            kind = 3
        else:
            kind = {"Class": 0, "Interface": 0, "Struct": 0, "Trait": 0, "Function": 1}.get(label, 2)
        inbound = candidate.get("in")
        inbound = int(inbound) if isinstance(inbound, (int, float)) else 0
        return (kind, -inbound, len(str(candidate.get("qn") or "")))

    def resolve_symbol(self, project: str, target: str) -> str:
        """Aceita nome curto ('remember'), qualified name ou padrão.

        'GitMemoryStore' -> a classe (não um método qualquer dela);
        'remember' -> mneme-core.system.core.actions.Brain.remember.
        """
        if "." in target:
            return target
        import re as _re

        # 1) correspondência exata de nome, com graus (formato groups)
        exact_match = self.call(
            "search_graph",
            {"project": project, "name_pattern": f"^{_re.escape(target)}$", "limit": 10, "format": "json"},
        )
        exact = self._candidates(exact_match)
        if exact:
            return str(sorted(exact, key=self._quality)[0]["qn"])

        # 2) busca textual: melhor palpite disponível
        candidates = self.search_symbols(project, target)
        if not candidates:
            return target
        return str(sorted(candidates, key=self._quality)[0]["qn"])

    @staticmethod
    def _flatten(data: Any) -> list[dict[str, Any]]:
        """Achata o formato `groups` do trace_path/search_graph em linhas planas."""
        if not isinstance(data, dict):
            return []
        out: list[dict[str, Any]] = []
        for group in data.get("groups") or []:
            prefix = str(group.get("qn_prefix") or "")
            for row in group.get("rows") or []:
                if not row:
                    continue
                name = str(row[0])
                out.append({
                    "qn": f"{prefix}.{name}" if prefix else name,
                    "name": name,
                    "hop": row[1] if len(row) > 1 else None,
                    "file": group.get("file"),
                })
        return out

    @staticmethod
    def _trace_totals(data: Any, direction: str) -> int | None:
        if not isinstance(data, dict):
            return None
        for key in (f"{direction}_total", "total"):
            if isinstance(data.get(key), int):
                return data[key]
        return None

    def _trace_once(self, project: str, symbol: str, direction: str, depth: int) -> dict[str, Any]:
        return self.call(
            "trace_path",
            {
                "project": project,
                "function_name": symbol,
                "direction": direction,
                "depth": depth,
                "format": "json",
                "risk_labels": True,
            },
        )

    def trace(self, project: str, function_name: str, direction: str = "both", depth: int = 3) -> dict[str, Any]:
        resolved = self.resolve_symbol(project, function_name)
        result = self._trace_once(project, resolved, direction, depth)
        data = result.get("data") or {}
        # O MCP responde `status: ambiguous` com sugestões: use a primeira e repita.
        if isinstance(data, dict) and data.get("status") == "ambiguous":
            suggestions = data.get("suggestions") or []
            if suggestions:
                resolved = str(suggestions[0].get("qualified_name") or resolved)
                result = self._trace_once(project, resolved, direction, depth)
                result["ambiguity"] = {"message": data.get("message"), "chosen": resolved}
        if resolved != function_name:
            result["resolved_symbol"] = resolved
        return result

    def impact(self, project: str, target: str, depth: int = 3) -> dict[str, Any]:
        """Blast radius: quem chama (inbound) + o que é chamado (outbound) + símbolos tocados.

        O alvo pode vir frouxo ('Store', 'GitMemoryStore.commit'): o nome é resolvido no
        grafo antes do trace, como faria um humano seguindo a dica do próprio MCP.
        """
        symbols = self.search(project, target, limit=10)
        candidates = self._candidates(symbols)
        resolved = self.resolve_symbol(project, target)
        inbound = self.trace(project, resolved, direction="inbound", depth=depth)
        outbound = self.trace(project, resolved, direction="outbound", depth=depth)
        selected = next((c for c in candidates if c["qn"] == resolved), None)
        inbound_data = inbound.get("data") or {}
        outbound_data = outbound.get("data") or {}
        return {
            "ok": all(r.get("ok") for r in (inbound, outbound)),
            "target": target,
            "resolved_symbol": resolved,
            "project": project,
            "degrees": {"in": (selected or {}).get("in"), "out": (selected or {}).get("out")},
            "candidates": candidates[:5],
            "callers": {
                "total": self._trace_totals(inbound_data, "callers"),
                "items": self._flatten((inbound_data.get("callers") if isinstance(inbound_data, dict) else None) or inbound_data),
                "raw": inbound,
            },
            "callees": {
                "total": self._trace_totals(outbound_data, "callees"),
                "items": self._flatten((outbound_data.get("callees") if isinstance(outbound_data, dict) else None) or outbound_data),
                "raw": outbound,
            },
            "symbols": symbols,
            "note": (
                "Graus 'in'/'out' vêm do search_graph. Diretórios fora do índice "
                "(ex.: system/scripts) não geram arestas de chamada."
            ),
        }

    def snippet(self, project: str, qualified_name: str) -> dict[str, Any]:
        return self.call("get_code_snippet", {"project": project, "qualified_name": qualified_name})

    def adr(self, project: str, mode: str = "outline") -> dict[str, Any]:
        return self.call("manage_adr", {"project": project, "mode": mode})

    def graph_schema(self, project: str) -> dict[str, Any]:
        return self.call("get_graph_schema", {"project": project})

    def query(self, project: str, cypher: str, max_rows: int = 100) -> dict[str, Any]:
        return self.call("query_graph", {"project": project, "query": cypher, "max_rows": max_rows, "format": "json"})

    def coverage(self, project: str, paths: list[str]) -> dict[str, Any]:
        return self.call("check_index_coverage", {"project": project, "paths": paths, "format": "json"})

    def register_repository(self, repo_path: str | Path, name: str | None = None, mode: str = "full") -> dict[str, Any]:
        args: dict[str, Any] = {"repo_path": str(repo_path), "mode": mode}
        if name:
            args["name"] = name
        return self.call("index_repository", args)


import os  # noqa: E402  (usado por binary/available; mantido no fim para clareza do topo)
