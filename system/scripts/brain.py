#!/usr/bin/env python3
"""brain — CLI do Mneme (brain-manager).

Funciona em qualquer harness: Hermes, OpenClaw, Claude Code, Codex, Cursor, cron, shell.
Não depende de LLM, MCP nem de rede para as operações canônicas de Markdown/Git.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parents[1]
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from core import actions, classify as classify_mod, instance as instance_mod, migrate_hermes, models, routing, validate as validate_mod  # noqa: E402
from core.config import MnemeConfig  # noqa: E402
from providers.assets import sync_drive_cache  # noqa: E402

LEVEL_MARKS = {True: "✓", False: "✗"}


def _mark(ok: bool) -> str:
    return LEVEL_MARKS[bool(ok)]


def _emit(payload, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    if isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


def cmd_status(brain: actions.Brain, args) -> int:
    report = brain.status()
    if args.json:
        _emit(report, True)
        return 0
    git = report["git"]
    index = report["index"]
    mem0 = report["mem0"]
    code = report["code"]
    validation = report["validation"]
    harness = report["harness"]
    lines = [
        "Mneme",
        "",
        "Repository",
        f"{_mark(git.get('is_repo'))} {report['root']}",
        f"{_mark(git.get('is_repo'))} Git inicializado" + (f" (branch {git.get('branch')})" if git.get("branch") else ""),
        f"{_mark(git.get('clean'))} working tree {'limpo' if git.get('clean') else 'com alterações'}",
        f"{_mark(len(git.get('entries', [])) == 0)} {len(git.get('entries', []))} arquivo(s) pendente(s)",
        *( [f"! git: {git['error']}"] if git.get("error") else [] ),
        "",
        "Search",
        f"{_mark(brain.config.index_path.exists())} SQLite FTS — {index.get('documents', 0)} documento(s), {index.get('ids', 0)} ID(s)",
        "",
        "Semantic Memory",
        f"{_mark(mem0.get('ok'))} Mem0 {mem0.get('status')} — {mem0.get('host', 'n/d')}"
        + (f" ({mem0.get('reason')})" if mem0.get("reason") else ""),
        "",
        "Code Intelligence",
        f"{_mark(code.get('ok'))} Codebase Memory {code.get('status')} — {code.get('repositories', 0)} repositório(s) indexado(s)"
        + (f" ({code.get('reason')})" if code.get("reason") else ""),
        "",
        "Hermes",
        (
            f"{_mark(harness.get('brain_manager_installed'))} brain-manager instalada em {harness.get('skills_dir')}"
            if harness.get("skills_dir_visible", True)
            else f"· brain-manager declarada em {harness.get('skills_dir')} (host do Hermes; verificação local não é possível daqui)"
        ),
        f"  hooks detectados: {', '.join(harness.get('hooks', [])) or 'nenhum'}", 
        "",
        "Validation",
        f"{_mark(validation['ok'])} {validation['documents']} documento(s), {validation['errors']} erro(s), {validation['warnings']} aviso(s)",
        f"{_mark(not validation['secrets'])} varredura de segredos"
        + (f" — gitleaks: {'instalado' if validation['gitleaks'].get('available') else 'ausente (scanner interno)'}"),
        "",
        "Projects",
    ]
    lines += [f"- {project['id']} ({project['dir']})" for project in report["projects"]] or ["- nenhum projeto cadastrado"]
    lines += ["", "Codebases configuradas"]
    lines += [
        f"- {repo.get('id')} -> {repo.get('path')} ({repo.get('provider', 'codebase-memory')})"
        for repo in report["codebases"]
    ] or ["- nenhuma"]
    lines += ["", "Migration", "✓ scan / plan / apply disponíveis (ver docs/MIGRATION.md)"]
    print("\n".join(lines))
    return 0


def cmd_search(brain: actions.Brain, args) -> int:
    results = brain.search(args.query, limit=args.limit)
    if args.json:
        _emit(results, True)
        return 0 if results else 1
    if not results:
        print(f"nada encontrado para {args.query!r}")
        return 1
    for hit in results:
        print(f"{hit['score']:>6}  [{hit['type']}] {hit['id']}\n        {hit['path']}\n        {hit['snippet'][:200]}")
    return 0


def cmd_get(brain: actions.Brain, args) -> int:
    document = brain.get(args.id)
    if not document:
        print(f"documento não encontrado: {args.id}", file=sys.stderr)
        return 1
    _emit(document if args.json else document["text"], args.json)
    return 0


def cmd_remember(brain: actions.Brain, args) -> int:
    receipt = brain.remember(
        args.text,
        type_=args.type,
        project=args.project,
        entity_id=args.entity,
        timeline=not args.no_timeline,
        commit=not args.no_commit,
        sync_mem0=not args.no_mem0,
        force=args.force,
    )
    if args.json:
        _emit(receipt, True)
        return 0 if receipt.get("ok") else 1
    classification = receipt["classification"]
    print(f"classificação : {classification['type']} ({classification['decision']}, confiança {classification['confidence']})")
    print(f"motivo        : {classification['reason']}")
    if receipt.get("skipped"):
        print(f"resultado     : não gravado — {receipt['skipped']}")
        return 0
    for path in receipt.get("files", []):
        print(f"arquivo       : {path}")
    if receipt.get("timeline_event"):
        print(f"timeline      : {receipt['timeline_event']['event_id']} — {receipt['timeline_event']['title']}")
    print(f"commit        : {receipt.get('commit') or '(sem commit)'}")
    mem0 = receipt.get("mem0") or {}
    if mem0:
        if mem0.get("ok"):
            status = "sincronizado"
        elif mem0.get("disabled"):
            status = "desabilitado (mem0 desativado no mneme.yaml)"
        elif mem0.get("queued"):
            status = f"pendente ({mem0.get('error', 'indisponível')})"
        else:
            status = f"não enviado ({mem0.get('error', 'indisponível')})"
        print(f"mem0          : {status}")
    for warning in receipt.get("warnings", []):
        print(f"aviso         : {warning}")
    return 0


def cmd_context(brain: actions.Brain, args) -> int:
    result = brain.context(args.scope, query=args.query, budget=args.budget)
    if args.json:
        _emit({k: v for k, v in result.items() if k != "markdown"} | {"markdown": result["markdown"]}, True)
        return 0
    if not args.quiet:
        print(result["markdown"])
    print(
        f"\n[context compiler] escopo={result['resolved'].get('kind')} rota={result['route']['mode']} "
        f"seções={len(result['sections'])} tokens≈{result['used_tokens']}/{result['budget_tokens']}",
        file=sys.stderr,
    )
    if result["truncated"]:
        print(f"[context compiler] omitidas por orçamento: {', '.join(result['truncated'])}", file=sys.stderr)
    return 0


def cmd_history(brain: actions.Brain, args) -> int:
    result = brain.history(args.id, limit=args.limit)
    if args.json:
        _emit(result, True)
        return 0 if result.get("ok") else 1
    if not result.get("ok"):
        print(result["error"], file=sys.stderr)
        return 1
    print(f"{result['path']}\n")
    for commit in result["commits"]:
        print(f"{commit['sha'][:9]} {commit['date']} {commit['subject']}")
    if not result["commits"]:
        print("(sem commits para este arquivo)")
    return 0


def cmd_diff(brain: actions.Brain, args) -> int:
    result = brain.diff(args.id, rev=args.rev)
    if not result.get("ok"):
        print(result["error"], file=sys.stderr)
        return 1
    print(result["diff"] or "(sem diferenças)")
    return 0


def cmd_validate(brain: actions.Brain, args) -> int:
    report = brain.validate()
    if args.json:
        _emit(report, True)
        return 0 if report["ok"] else 1
    print(f"{_mark(report['ok'])} validação — {report['documents']} documentos, {len(report['errors'])} erro(s), {len(report['warnings'])} aviso(s)")
    for error in report["errors"][:20]:
        print(f"  ✗ {error['path']}: {error['message']}")
    for warning in report["warnings"][:20]:
        print(f"  ! {warning['path']}: {warning['message']}")
    if report["secrets"]:
        print("  ✗ segredos encontrados:")
        for path in report["secrets"]:
            print(f"      {path}")
    gitleaks = report["gitleaks"]
    print(f"  {'✓' if gitleaks.get('available') else '!'} gitleaks: {'disponível' if gitleaks.get('available') else gitleaks.get('note')}")
    return 0 if report["ok"] else 1


def cmd_reindex(brain: actions.Brain, args) -> int:
    stats = brain.reindex(incremental=not args.full)
    _emit(stats, args.json) if args.json else print(
        f"índice: {stats['indexed']} novos, {stats['updated']} atualizados, {stats['skipped']} inalterados, {stats['removed']} removidos"
    )
    for error in stats.get("errors", [])[:10]:
        print(f"  ! {error}", file=sys.stderr)
    return 0


def cmd_organize(brain: actions.Brain, args) -> int:
    report = brain.organize(dry_run=args.dry_run)
    if args.json:
        _emit(report, True)
        return 0
    print(f"inbox: {report['processed']} processado(s), {report['moved']} consolidado(s), "
          f"{report['duplicates']} duplicata(s), {report['kept']} mantido(s)"
          + (" [dry-run]" if report.get("dry_run") else ""))
    for item in report["items"]:
        target = item.get("target") or item.get("reason", "")
        print(f"  - {item['file']}: {item['action']} {target}")
    return 0


def cmd_sync(brain: actions.Brain, args) -> int:
    result = brain.sync(push=args.push, confirm=args.confirm)
    if args.json:
        _emit(result, True)
        return 0
    pending = result["mem0_pending"]
    print(f"mem0: {pending['flushed']} enviado(s), {pending['failed']} falha(s), {pending['remaining']} pendente(s)")
    git = result["git"]
    print(f"git : {'ok' if git.get('ok') else 'atenção'} {git.get('skipped') or git.get('output') or git.get('error', '')}")
    print(f"push: {result['push'].get('skipped') or result['push'].get('output', '')}")
    return 0


def cmd_route(brain: actions.Brain, args) -> int:
    result = routing.route(args.query)
    _emit(result, args.json) if args.json else (
        print(f"modo: {result['mode']}") or [print(f"  -> {s['source']}: {s['why']}") for s in result["sources"]]
    )
    return 0


def cmd_classify(brain: actions.Brain, args) -> int:
    result = classify_mod.classify_text(args.text, brain.config.policy)
    _emit(result, args.json) if args.json else [print(f"{key}: {value}") for key, value in result.items()]
    return 0


# -- code intelligence ---------------------------------------------------------


def cmd_project(brain: actions.Brain, args) -> int:
    from core import projects as projects_mod

    if args.project_action == "list":
        items = projects_mod.list_projects(brain)
        _emit(items, args.json) if args.json else [print(f"- {p['id']} ({p['dir']})") for p in items]
        return 0
    if args.project_action == "new":
        if not args.name:
            print("informe o nome do projeto", file=sys.stderr)
            return 2
        repos = [{"id": rid, "path": path} for rid, path in _parse_repos(args.code_repo or [])]
        try:
            result = projects_mod.create_project(brain, args.name, project_id=args.id, code_repos=repos or None)
        except ValueError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 2
        _emit(result, args.json) if args.json else print(
            f"{_mark(result['ok'])} {result.get('dir') or result.get('error')} (commit {result.get('commit')})"
        )
        return 0 if result["ok"] else 1
    if args.project_action == "show":
        target = args.name
        for project in projects_mod.list_projects(brain):
            if target in (project["id"], project["name"], models.slugify(project["name"])):
                text = brain.store.read(f"{project['dir']}/project.md")
                _emit(text, args.json) if not args.json else _emit({"project": project, "project_md": text}, True)
                return 0
        print(f"projeto não encontrado: {target}", file=sys.stderr)
        return 1
    print("ação desconhecida", file=sys.stderr)
    return 2


def _parse_repos(values: list[str]) -> list[tuple[str, str]]:
    repos: list[tuple[str, str]] = []
    for value in values:
        repo_id, _, path = value.partition("=")
        if path:
            repos.append((repo_id.strip(), path.strip()))
        else:
            repos.append((os.path.basename(repo_id.strip()), repo_id.strip()))
    return repos


def cmd_code(brain: actions.Brain, args) -> int:
    provider = brain.code
    if args.code_action == "list":
        repos = provider.list_repositories()
        _emit(repos, args.json) if args.json else [print(f"- {r.get('name')} ({r.get('root_path')}) {r.get('nodes', '?')} nós") for r in repos]
        return 0 if repos else 1
    if args.code_action == "health":
        health = provider.health()
        _emit(health, args.json) if args.json else print(f"{_mark(health.get('ok'))} {health}")
        return 0 if health.get("ok") else 1
    if args.code_action == "index":
        result = provider.register_repository(args.path, name=args.name, mode=args.mode)
        _emit(result, args.json) if args.json else print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    project = args.project
    if not project:
        print("informe o projeto indexado (use `brain code list`)", file=sys.stderr)
        return 2
    if args.code_action == "status":
        result = provider.status(project)
    elif args.code_action == "search":
        result = provider.search(project, args.query, limit=args.limit)
    elif args.code_action == "architecture":
        result = provider.architecture(project, aspects=args.aspects)
    elif args.code_action == "impact":
        result = provider.impact(project, args.target, depth=args.depth)
    elif args.code_action == "trace":
        result = provider.trace(project, args.target, direction=args.direction, depth=args.depth)
    elif args.code_action == "snippet":
        result = provider.snippet(project, args.target)
    elif args.code_action == "adr":
        result = provider.adr(project, mode=args.adr_mode)
    else:  # pragma: no cover
        print("ação desconhecida", file=sys.stderr)
        return 2
    if args.json:
        _emit(result, True)
    elif args.code_action == "impact":
        _print_impact(result)
    else:
        data = result.get("data", result)
        if isinstance(data, dict) and "text" in data:
            print(data["text"])
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2, default=str)[:8000])
    return 0 if result.get("ok", True) else 1


def _print_impact(result: dict) -> None:
    """Relatório legível de blast radius (a resposta que o agente cita)."""
    degrees = result.get("degrees") or {}
    print(f"Impacto de alterar {result['target']!r} em {result['project']}")
    print(f"símbolo resolvido : {result.get('resolved_symbol')}")
    print(f"graus no grafo    : in={degrees.get('in')} out={degrees.get('out')}")
    for label, key in (("Chamadores (quem quebra se mudar)", "callers"), ("Chamados (o que depende disso)", "callees")):
        block = result.get(key) or {}
        items = block.get("items") or []
        print(f"\n{label} — total {block.get('total')}")
        for item in items[:20]:
            hop = f" hop={item['hop']}" if item.get("hop") is not None else ""
            print(f"  - {item['qn']}{hop}")
        if not items:
            print("  (nenhum; confira se o diretório do chamador está no índice com `brain code status`)")


# -- assets --------------------------------------------------------------------


def cmd_assets(brain: actions.Brain, args) -> int:
    result = sync_drive_cache(
        brain.config,
        remote=args.remote,
        executable=args.rclone,
        dry_run=bool(args.dry_run),
    )
    if args.json:
        _emit(result, True)
    elif result.get("ok"):
        print(f"cache do Drive atualizado: {result['cache']}")
    else:
        print(f"erro: {result.get('error', 'falha no rclone')}", file=sys.stderr)
    return 0 if result.get("ok") else 1


# -- instância -----------------------------------------------------------------


def cmd_instance(args) -> int:
    root = args.instance_root or args.root or str(Path.home() / "mneme")
    if args.instance_action == "init":
        result = instance_mod.initialize_instance(
            root,
            remote=args.remote or "",
            drive_folder_id=args.drive_folder_id or "",
        )
    elif args.instance_action == "migrate":
        if not args.source:
            print("erro: --source é obrigatório para instance migrate", file=sys.stderr)
            return 2
        result = instance_mod.migrate_instance(args.source, root)
    else:  # pragma: no cover - argparse restringe as opções
        print("ação desconhecida", file=sys.stderr)
        return 2

    if args.json:
        _emit(result, True)
    elif result.get("ok"):
        print(f"instância: {result.get('root')}")
        if result.get("copied") is not None:
            print(f"copiados: {len(result.get('copied', []))} | ignorados: {len(result.get('skipped', []))}")
    else:
        print(f"erro: {result.get('error', 'operação recusada')}", file=sys.stderr)
        for blocked in result.get("blocked", []):
            print(f"  {blocked['path']}: {blocked['reason']}", file=sys.stderr)
    return 0 if result.get("ok") else 1


# -- assistente de instalação ---------------------------------------------------


def cmd_setup(args) -> int:
    from core import setup as setup_mod

    home = Path.home()
    plan = setup_mod.default_plan(home)
    if args.instance_root or args.root:
        plan.instance_root = args.instance_root or args.root
    if args.instance_remote:
        plan.instance_remote = args.instance_remote
    if args.drive_folder_id:
        plan.drive_folder_id = args.drive_folder_id
    if args.no_mem0:
        plan.mem0_host = ""
    elif args.mem0_host is not None:
        plan.mem0_host = args.mem0_host
    if args.mem0_user:
        plan.mem0_user = args.mem0_user
    if args.mem0_key_env:
        plan.mem0_key_env = args.mem0_key_env
    if args.hermes_profile:
        plan.hermes_profile = args.hermes_profile
    if args.harness:
        plan.harness = args.harness
    if args.skills_base:
        plan.skills_base = args.skills_base
    if args.package_root:
        plan.package_root = args.package_root
    plan.install = not args.no_install
    plan.commit = not args.no_commit

    interactive = not args.non_interactive and sys.stdin.isatty()
    if interactive:
        plan = setup_mod.interactive_plan(plan, home=home)
        print()
        print(setup_mod.describe(plan))
        print()
        if args.yes or input("aplicar? [s/N]: ").strip().lower() in {"s", "sim", "y", "yes"}:
            pass
        else:
            print("cancelado")
            return 1
    elif not args.non_interactive:
        print("Sem terminal interativo: nada foi feito. Valores que seriam aplicados:")
        print(setup_mod.describe(plan))
        print()
        print("Para aplicar sem perguntas, repita com --non-interactive e os valores desejados.")
        print("Para conferir sem escrever: acrescente --dry-run.")
        return 2

    result = setup_mod.apply_plan(plan, home=home, dry_run=getattr(args, "dry_run", False))
    if args.json:
        _emit(result, True)
    elif result.get("ok"):
        print(f"{_mark(True)} configuração aplicada em {result['instance_root']}")
        if result.get("files_created"):
            print(f"  arquivos criados: {', '.join(result['files_created'])}")
        commit = result.get("commit") or {}
        if commit.get("commit"):
            print(f"  commit: {commit['commit']}")
        print()
        print("próximos passos:")
        if plan.mem0_host is None:
            print(f"  confira o host do Mem0 e {plan.mem0_key_env} em {result['instance_root']}/mneme.yaml")
        elif plan.mem0_host:
            print(f"  defina {plan.mem0_key_env} no ambiente (chave do Mem0)")
        else:
            print("  Mem0 desativado nesta instância")
        if plan.drive_folder_id:
            print(f"  brain assets sync --remote gdrive:   # pasta {plan.drive_folder_id}")
        print(f"  brain status   # com MNEME_ROOT={result['instance_root']}")
    else:
        print("configuração não aplicada", file=sys.stderr)
        for error in result.get("errors", []) or [result.get("error", "erro desconhecido")]:
            print(f"  erro: {error}", file=sys.stderr)
        for warning in result.get("warnings", []):
            print(f"  aviso: {warning}", file=sys.stderr)
    for step in result.get("steps", []):
        if step.get("ok") is False and step.get("error"):
            print(f"  falha em {step.get('step')}: {step['error']}", file=sys.stderr)
    return 0 if result.get("ok") else 1


# -- migração ------------------------------------------------------------------


def cmd_migrate(brain: actions.Brain, args) -> int:
    home = args.home or os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    if args.migrate_action == "scan":
        report = migrate_hermes.scan(home)
        if args.json:
            _emit(report, True)
            return 0
        print(f"Hermes inventory — {report['hermes_home']}")
        print()
        for category, count in report["counts"].items():
            print(f"{category:<24} {count:>5}")
        print(f"\ntotal: {report['total_files']} arquivo(s), {round(report['total_bytes'] / 1024 / 1024, 1)} MB")
        return 0
    if args.migrate_action == "plan":
        result = migrate_hermes.plan(home, limit_files=args.limit)
        if args.json:
            _emit(result, True)
            return 0
        print(f"plano de migração — {result['hermes_home']}")
        print(f"a copiar: {result['copy']} | never_migrate: {result['never_migrate']} | metadata_only: {result['metadata_only']}")
        print()
        for entry in result["entries"]:
            print(f"  {entry['action']:<14} {entry['source']} -> {entry['destination']}")
        return 0
    if args.migrate_action == "apply":
        if args.backup:
            destination = migrate_hermes.backup_hermes(home, brain.config.generated_dir / "backups")
            print(f"backup: {destination}")
        result = migrate_hermes.apply(home, brain.config, brain.store, limit_files=args.limit, dry_run=args.dry_run)
        if args.json:
            _emit(result, True)
            return 0
        print(f"manifesto: {result['manifest']}")
        print(f"copiados: {result['copied']} | bloqueados: {result['blocked']}")
        for entry in result["applied"]:
            print(f"  {entry['status']:<18} {entry['source']} -> {entry.get('target', entry['destination'])}")
        return 0
    print("ação desconhecida", file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # Opções aceitas também depois do subcomando (ex.: `brain migrate-hermes scan --json`).
    COMMON = argparse.ArgumentParser(add_help=False)
    COMMON.add_argument("--json", action="store_true", help="saída em JSON")
    COMMON.add_argument("--dry-run", action="store_true", help="não escreve nada")

    parser = argparse.ArgumentParser(prog="brain", description="Mneme — cérebro persistente em Markdown/Git")
    parser.add_argument("--root", help="raiz da instância Mneme (default: MNEME_ROOT ou ~/mneme)")
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    parser.add_argument("--dry-run", action="store_true", help="não escreve nada")
    sub = parser.add_subparsers(dest="command", required=True)

    instance = sub.add_parser("instance", parents=[COMMON], help="inicializa ou migra uma instância de dados")
    instance.add_argument("instance_action", choices=["init", "migrate"])
    instance.add_argument("--root", dest="instance_root", help="raiz da instância (default: ~/mneme)")
    instance.add_argument("--source", help="raiz legada de onde copiar dados canônicos")
    instance.add_argument("--remote", help="URL do repositório Git privado da instância")
    instance.add_argument("--drive-folder-id", help="ID da pasta raiz no Google Drive")
    instance.set_defaults(func=cmd_instance)

    setup = sub.add_parser("setup", parents=[COMMON], help="assistente de instalação e configuração")
    setup.add_argument("--instance-root", help="raiz dos dados da instância (default: MNEME_ROOT ou ~/mneme)")
    setup.add_argument("--instance-remote", help="URL do repositório Git privado da instância")
    setup.add_argument("--drive-folder-id", help="ID da pasta raiz no Google Drive")
    setup.add_argument("--mem0-host", help="host do Mem0 (default: http://127.0.0.1:8888)")
    setup.add_argument("--no-mem0", action="store_true", help="desativa o Mem0 nesta instância")
    setup.add_argument("--mem0-user", help="user_id do Mem0 (default: default)")
    setup.add_argument("--mem0-key-env", help="variável de ambiente da chave do Mem0 (default: MEM0_API_KEY)")
    setup.add_argument("--hermes-profile", help="diretório do perfil do Hermes que recebe a skill")
    setup.add_argument("--harness", choices=["hermes", "claude"], help="onde instalar a skill (default: hermes)")
    setup.add_argument("--skills-base", help="base que recebe skills/brain-manager (ex.: ~/.claude)")
    setup.add_argument("--package-root", help="destino do runtime (default: ~/.local/share/mneme-package)")
    setup.add_argument("--non-interactive", action="store_true", help="aplica sem perguntar")
    setup.add_argument("--yes", action="store_true", help="confirma automaticamente no modo interativo")
    setup.add_argument("--no-install", action="store_true", help="não instala runtime, skill e CLI")
    setup.add_argument("--no-commit", action="store_true", help="não commita a configuração da instância")
    setup.set_defaults(func=cmd_setup)

    assets = sub.add_parser("assets", parents=[COMMON], help="cache local de arquivos do Google Drive")
    assets.add_argument("assets_action", choices=["sync"])
    assets.add_argument("--remote", default="gdrive:", help="remote configurado no rclone")
    assets.add_argument("--rclone", default="rclone", help="executável rclone")
    assets.set_defaults(func=cmd_assets)

    sub.add_parser("status", parents=[COMMON], help="estado de todas as camadas").set_defaults(func=cmd_status)

    search = sub.add_parser("search", parents=[COMMON], help="busca textual no cérebro")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=15)
    search.set_defaults(func=cmd_search)

    get = sub.add_parser("get", parents=[COMMON], help="lê um documento por ID ou caminho")
    get.add_argument("id")
    get.set_defaults(func=cmd_get)

    remember = sub.add_parser("remember", parents=[COMMON], help="persiste um fato no lugar correto")
    remember.add_argument("text")
    remember.add_argument("--type", help="força o tipo (decision, commitment, note, event, ...)")
    remember.add_argument("--project", help="slug do projeto de destino")
    remember.add_argument("--entity", help="ID de entidade (para relações)")
    remember.add_argument("--no-timeline", action="store_true")
    remember.add_argument("--no-commit", action="store_true")
    remember.add_argument("--no-mem0", action="store_true")
    remember.add_argument("--force", action="store_true", help="grava mesmo se a política sugerir ignorar")
    remember.set_defaults(func=cmd_remember)

    context = sub.add_parser("context", parents=[COMMON], help="contexto federado (Mneme + Mem0 + código)")
    context.add_argument("scope")
    context.add_argument("--query")
    context.add_argument("--budget", type=int)
    context.add_argument("--quiet", action="store_true", help="omite o markdown; só o resumo")
    context.set_defaults(func=cmd_context)

    history = sub.add_parser("history", parents=[COMMON], help="histórico Git de um documento")
    history.add_argument("id")
    history.add_argument("-n", "--limit", type=int, default=10)
    history.set_defaults(func=cmd_history)

    diff = sub.add_parser("diff", parents=[COMMON], help="diff Git de um documento")
    diff.add_argument("id")
    diff.add_argument("--rev", default="HEAD")
    diff.set_defaults(func=cmd_diff)

    validate = sub.add_parser("validate", parents=[COMMON], help="valida o repositório inteiro")
    validate.set_defaults(func=cmd_validate)

    reindex = sub.add_parser("reindex", parents=[COMMON], help="reconstrói/atualiza o índice FTS")
    reindex.add_argument("--full", action="store_true")
    reindex.set_defaults(func=cmd_reindex)

    organize = sub.add_parser("organize", parents=[COMMON], help="classifica e consolida o inbox")
    organize.set_defaults(func=cmd_organize)

    sync = sub.add_parser("sync", parents=[COMMON], help="reprocessa pendências do Mem0 e sincroniza o Git")
    sync.add_argument("--push", action="store_true")
    sync.add_argument("--confirm", action="store_true")
    sync.set_defaults(func=cmd_sync)

    route = sub.add_parser("route", parents=[COMMON], help="mostra quais fontes seriam consultadas")
    route.add_argument("query")
    route.set_defaults(func=cmd_route)

    classify = sub.add_parser("classify", parents=[COMMON], help="classifica um texto sem gravar")
    classify.add_argument("text")
    classify.set_defaults(func=cmd_classify)

    project = sub.add_parser("project", parents=[COMMON], help="criar/listar/mostrar projetos (unidade de contexto)")
    project.add_argument("project_action", choices=["new", "list", "show"])
    project.add_argument("name", nargs="?")
    project.add_argument("--id", help="ID estável do projeto (default: project-<slug>)")
    project.add_argument(
        "--code-repo",
        action="append",
        help="codebase associada no formato id=/caminho (repetível)",
    )
    project.set_defaults(func=cmd_project)

    code = sub.add_parser("code", parents=[COMMON], help="inteligência de código (Codebase Memory)")
    code.add_argument("code_action", choices=["list", "health", "index", "status", "search", "architecture", "impact", "trace", "snippet", "adr"])
    code.add_argument("project", nargs="?")
    code.add_argument("target", nargs="?")
    code.add_argument("query", nargs="?")
    code.add_argument("--path", help="caminho do repositório (ação index)")
    code.add_argument("--name", help="nome do projeto no índice")
    code.add_argument("--mode", default="full", choices=["full", "moderate", "fast", "cross-repo-intelligence"])
    code.add_argument("--direction", default="both", choices=["inbound", "outbound", "both"])
    code.add_argument("--depth", type=int, default=3)
    code.add_argument("--limit", type=int, default=25)
    code.add_argument("--aspects", nargs="*")
    code.add_argument("--adr-mode", default="outline", choices=["outline", "get", "sections"])
    code.set_defaults(func=cmd_code)

    migrate = sub.add_parser("migrate-hermes", parents=[COMMON], help="migração segura de ~/.hermes")
    migrate.add_argument("migrate_action", choices=["scan", "plan", "apply"])
    migrate.add_argument("--home", help="caminho de ~/.hermes (default: HERMES_HOME)")
    migrate.add_argument("--limit", type=int, default=40, help="máximo de arquivos a copiar")
    migrate.add_argument("--backup", action="store_true", help="gera backup dos candidatos antes de aplicar")
    migrate.set_defaults(func=cmd_migrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "instance":
        return cmd_instance(args)
    if args.command == "setup":
        # Roda antes de qualquer instância existir: não depende de mneme.yaml.
        return cmd_setup(args)
    try:
        config = MnemeConfig(root=args.root)
    except FileNotFoundError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    brain = actions.Brain(config, dry_run=bool(getattr(args, "dry_run", False)))
    try:
        return args.func(brain, args)
    except validate_mod.ValidationError as exc:
        print(f"validação recusou a operação: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
