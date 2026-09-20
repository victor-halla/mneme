"""Classificação de conteúdo e política de memória.

Decide se um texto deve ser persistido, com que tipo, em que arquivo e com que sensibilidade.
Heurística determinística (sem LLM): previsível, auditável e barata.
"""

from __future__ import annotations

import re
from typing import Any

from . import models

# Palavras que forçam a persistência mesmo em caso de dúvida.
FORCE_PATTERNS = (
    r"\bguarde\s+(isso|isto)\b",
    r"\bsalve\s+(isso|isto)\b",
    r"\blembre\s+(disso|desse|desta)\b",
    r"\banote\b",
    r"\bregistr[ae]\b",
    r"\badicione\s+ao\s+meu\s+c[ée]rebro\b",
    r"\bpro\s+c[ée]rebro\b",
)

BLOCK_PATTERNS = (
    r"\bn[ãa]o\s+precisa\s+guardar\b",
    r"\bn[ãa]o\s+guarde\b",
    r"\bisso\s+[ée]\s+tempor[áa]rio\b",
    r"\besque[cç]a\s+isso\b",
    r"\bn[ãa]o\s+anote\b",
)

TYPE_RULES: tuple[tuple[str, str], ...] = (
    ("decision", r"\b(decidim|decidid|decis[ãa]o|escolhemos|optamos|vamos\s+usar|ficou\s+definido|aprovad)"),
    ("commitment", r"\b(combinad|combinamos|ficou\s+de|prometi|compromisso|me\s+comprometi|vou\s+enviar|prazo\s+de)"),
    ("meeting", r"\b(reuni[ãa]o|call|meeting|1:1|daily\s+de|alinhamento\s+com)\b"),
    ("relationship", r"\b(trabalha\s+com|s[óo]cio|reporta\s+(a|para)|[ée]\s+filh|esposa|marido|contato\s+de|conhece\b)"),
    ("preference", r"\b(prefere|prefer[êe]ncia|gosta\s+de|n[ãa]o\s+gosta|odeia|costuma)"),
    ("project_change", r"\b(projeto\s+\w+|mudan[çc]a\s+de\s+escopo|nova\s+fase|iniciad|conclu[íi]d|entreg(ue|amos))"),
    ("learning", r"\b(aprendi|aprendizado|li[çc][ãa]o|descobri|insight|li\s+que)"),
    ("idea", r"\b(ideia|e\s+se\b|poder[íi]amos|sugest[ãa]o|brainstorm)"),
    ("event", r"\b(aconteceu|ocorreu|entrevista|viagem|hoje\s+foi|ontem\s+foi|marco\s+de)"),
)

# type -> (categoria de política, diretório, tipo de documento canônico)
TYPE_TARGETS: dict[str, tuple[str, str, str]] = {
    "decision": ("always", "projects/{project}/decisions.md", "note"),
    "commitment": ("always", "projects/{project}/tasks.md", "note"),
    "project_change": ("always", "projects/{project}/project.md", "note"),
    "relationship": ("always", "entities/people/{slug}.md", "person"),
    "preference": ("always", "knowledge/notes/{slug}.md", "note"),
    "event": ("always", "timeline/{date}.md", "daily"),
    "meeting": ("usually", "timeline/{date}.md", "daily"),
    "idea": ("usually", "knowledge/notes/{slug}.md", "note"),
    "learning": ("usually", "knowledge/notes/{slug}.md", "note"),
    "context": ("usually", "knowledge/notes/{slug}.md", "note"),
    "note": ("usually", "knowledge/notes/{slug}.md", "note"),
}

PROJECT_HINT = re.compile(r"\bprojeto\s+([A-Za-zÀ-ÿ0-9][\wÀ-ÿ-]*)", re.IGNORECASE)
PERSON_HINT = re.compile(r"\b([A-ZÀ-Ý][a-zà-ÿ]{2,})\s+([A-ZÀ-Ý][a-zà-ÿ]{2,})\b")

# Evita falso positivo de "nomes próprios" que na verdade são termos técnicos
# (ex.: "Codebase Memory", "Claude Code", "Google Drive").
PERSON_STOPWORDS = {
    "codebase", "memory", "mem0", "git", "github", "gitlab", "cloud", "data", "banco",
    "system", "store", "project", "projeto", "nota", "arquivo", "sqlite", "mcp", "hermes",
    "openclaw", "telegram", "google", "drive", "agent", "agente", "claude", "codex", "cursor",
    "insight", "api", "token", "brain", "mneme", "pix", "open", "finance", "openfinance",
}
SECRET_HINT = re.compile(
    r"(?i)\b(senha|password|token|api[_-]?key|chave\s+privada|secret|credencial)\b"
)


def detect_command(text: str) -> str | None:
    for pattern in BLOCK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return "block"
    for pattern in FORCE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return "force"
    return None


def detect_type(text: str) -> tuple[str, str]:
    for type_, pattern in TYPE_RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return type_, f"casou com padrão de {type_}"
    return "note", "sem padrão específico — nota genérica"


def detect_project(text: str) -> str | None:
    match = PROJECT_HINT.search(text)
    if match:
        return models.slugify(match.group(1))
    return None


def detect_entities(text: str) -> list[str]:
    """IDs prováveis de pessoas (heurística de nomes próprios)."""
    found: list[str] = []
    for first, last in PERSON_HINT.findall(text or ""):
        if first.lower() in PERSON_STOPWORDS or last.lower() in PERSON_STOPWORDS:
            continue
        candidate = models.make_id("person", f"{first} {last}")
        if candidate not in found:
            found.append(candidate)
    return found[:5]


def policy_decision(type_: str, policy: dict[str, Any] | None = None) -> str:
    """Devolve always | usually | ignore para um tipo de memória."""
    policy = policy or {}

    def normalize(entries: list[str]) -> set[str]:
        """Aceita 'decisions', 'commitments', 'important_preferences' e os tipos singulares."""
        names: set[str] = set()
        for entry in entries:
            value = str(entry).strip().lower()
            if not value:
                continue
            names.add(value)
            names.add(value.rstrip("s"))
            names.add(value.split("_")[-1])
            names.add(value.split("_")[-1].rstrip("s"))
        return names

    always = normalize(policy.get("always") or [])
    usually = normalize(policy.get("usually") or [])
    ignore = normalize(policy.get("ignore") or [])
    if type_ in always:
        return "always"
    if type_ in usually:
        return "usually"
    if type_ in ignore:
        return "ignore"
    # 'context' é o nome interno usado para conversa casual
    if type_ in ("casual_conversation", "temporary_requests", "repeated_information"):
        return "ignore"
    return "usually"


def classify_text(text: str, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classifica um texto e devolve o plano de persistência."""
    clean = (text or "").strip()
    if not clean:
        return {"type": "note", "decision": "ignore", "reason": "texto vazio", "sensitivity": "private"}

    type_, reason = detect_type(clean)
    decision = policy_decision(type_, policy)
    command = detect_command(clean)

    if command == "block":
        decision = "ignore"
        reason = "comando explícito de não persistir"
    elif command == "force":
        if decision == "ignore":
            decision = "usually"
        reason = f"{reason}; comando explícito de guardar"

    sensitivity = "private"
    if SECRET_HINT.search(clean):
        sensitivity = "secret"
        decision = "ignore"
        reason = f"{reason}; conteúdo parece credencial — nunca commitar"

    entities = detect_entities(clean)
    project = detect_project(clean)
    slug = models.slugify(clean.splitlines()[0][:60])
    target_type = TYPE_TARGETS.get(type_, ("usually", "knowledge/notes/{slug}.md", "note"))[2]
    template = TYPE_TARGETS.get(type_, ("usually", "knowledge/notes/{slug}.md", "note"))[1]
    target = template.format(
        project=project or "inbox",
        slug=slug,
        date=models.today_iso(),
    )

    confidence = 0.9 if command else (0.65 if type_ != "note" else 0.4)
    return {
        "type": type_,
        "document_type": target_type,
        "decision": decision,
        "target": target,
        "sensitivity": sensitivity,
        "confidence": confidence,
        "reason": reason,
        "entities": entities,
        "project": project,
        "slug": slug,
    }
