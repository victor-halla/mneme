"""Política de roteamento: o agente não consulta todas as fontes para toda pergunta."""

from __future__ import annotations

import re
from typing import Any

# Cada rota tem: nome das fontes, por que, e o modo de recuperação.
CODE_PATTERNS = (
    r"\b(quem\s+chama|callers?|callees?|chamadas?)\b",
    r"\b(fun[çc][ãa]o|m[ée]todo|classe|s[íi]mbolo|m[óo]dulo|arquivo\s+fonte)\b",
    r"\b(c[óo]digo|codebase|reposit[óo]rio|repo)\b",
    r"\b(rota|endpoint|route|handler)\b",
    r"\b(dead\s+code|c[óo]digo\s+morto|refator|refactor)\b",
    r"\b(depend[êe]ncia|importa|imports|grafo)\b",
    r"\b(implementa|onde\s+est[áa]\s+(a|o)\s+(função|classe|rota))\b",
    r"\b[a-zA-Z_][A-Za-z0-9_]*\(\)",  # identificador seguido de () = símbolo de código
)

IMPACT_PATTERNS = (
    r"\bimpacto\b",
    r"\bblast\s+radius\b",
    r"\bo\s+que\s+(pode\s+)?quebrar\b",
    r"\bse\s+eu\s+(alterar|mudar|remover)\b",
    r"\bafeta\b",
)

MOTIVATION_PATTERNS = (
    r"\bpor\s+que\b",
    r"\bporqu[êe]\b",
    r"\bmotivo\b",
    r"\bjustificativa\b",
    r"\bracional\b",
)

TIMELINE_PATTERNS = (
    r"\bontem\b",
    r"\bhoje\b",
    r"\bsemana\s+passada\b",
    r"\bm[êe]s\s+passado\b",
    r"\bo\s+que\s+aconteceu\b",
    r"\bhist[óo]rico\s+de\s+eventos\b",
    r"\bquando\s+(foi|aconteceu)\b",
    r"\blinha\s+do\s+tempo\b",
)

DECISION_PATTERNS = (
    r"\bdecidim",
    r"\bdecis[ãa]o\b",
    r"\bdecidid",
    r"\bficou\s+definido\b",
    r"\bacordad",
)

STATUS_PATTERNS = (
    r"\bcomo\s+est[áa]\s+(o\s+)?projeto\b",
    r"\bonde\s+estamos\b",
    r"\bsitua[çc][ãa]o\s+(geral|do\s+projeto)\b",
    r"\bstatus\b",
    r"\bpainel\b",
)


def _any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def route(query: str) -> dict[str, Any]:
    """Devolve as fontes a consultar, em ordem de prioridade, com justificativa."""
    text = (query or "").strip()
    sources: list[dict[str, str]] = []

    is_code = _any(CODE_PATTERNS, text)
    is_impact = _any(IMPACT_PATTERNS, text)
    is_motive = _any(MOTIVATION_PATTERNS, text)
    is_timeline = _any(TIMELINE_PATTERNS, text)
    is_decision = _any(DECISION_PATTERNS, text)
    is_status = _any(STATUS_PATTERNS, text)

    # Perguntas sobre código: o grafo vem primeiro.
    if is_impact:
        sources.append({"source": "codebase-memory", "why": "análise de impacto exige call graph"})
        sources.append({"source": "mneme", "why": "decisões e restrições do projeto"})
        return {"query": text, "mode": "code-impact", "sources": sources}

    if is_code and is_motive:
        sources.append({"source": "mneme", "why": "decisão humana registrada (decisions.md)"})
        sources.append({"source": "timeline", "why": "contexto temporal da decisão"})
        sources.append({"source": "codebase-memory", "why": "ADR técnica, arquitetura e call graph"})
        sources.append({"source": "git-history", "why": "histórico do commit que introduziu a mudança"})
        return {"query": text, "mode": "why-code", "sources": sources}

    if is_code:
        sources.append({"source": "codebase-memory", "why": "pergunta estrutural de código"})
        sources.append({"source": "mneme", "why": "contexto do projeto associado à codebase"})
        return {"query": text, "mode": "code", "sources": sources}

    if is_timeline:
        sources.append({"source": "timeline", "why": "pergunta temporal"})
        sources.append({"source": "mneme", "why": "documentos citados pelos eventos"})
        return {"query": text, "mode": "timeline", "sources": sources}

    if is_decision:
        sources.append({"source": "mneme", "why": "decisões canônicas do projeto"})
        sources.append({"source": "mem0", "why": "recuperação semântica de decisões relacionadas"})
        sources.append({"source": "timeline", "why": "quando a decisão foi tomada"})
        return {"query": text, "mode": "decision", "sources": sources}

    if is_status:
        sources.append({"source": "mneme", "why": "estado do projeto, tarefas e decisões"})
        sources.append({"source": "mem0", "why": "fatos recentes relacionados"})
        sources.append({"source": "codebase-memory", "why": "arquitetura das codebases do projeto"})
        sources.append({"source": "timeline", "why": "últimos eventos"})
        return {"query": text, "mode": "status", "sources": sources}

    sources.append({"source": "mneme", "why": "fatos e entidades canônicas"})
    sources.append({"source": "mem0", "why": "memória semântica relacionada"})
    return {"query": text, "mode": "memory", "sources": sources}
