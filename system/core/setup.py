"""Assistente de instalação e configuração do Mneme.

Resolve os três valores que variam por máquina (raiz dos dados, repositório Git
da instância e pasta raiz do Google Drive), instala o runtime, a skill e a CLI,
e cria ou adota a instância de dados.

Regras de segurança, válidas em todos os modos:

- nunca sobrescreve dados existentes; adoção só altera chaves de configuração;
- nunca faz push; quando escreve configuração, commita apenas os arquivos que
  ele mesmo tocou;
- sem terminal interativo, usa os valores informados e os padrões em vez de
  esperar por entrada.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

SYSTEM_DIR = Path(__file__).resolve().parents[1]
PACKAGE_SRC = SYSTEM_DIR.parent
INSTALLER = SYSTEM_DIR / "scripts" / "install_skill.sh"

GIT_URL_RE = re.compile(r"^(?:https?://|ssh://|git://|git@[A-Za-z0-9._-]+:|file://|/)")
DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
MEM0_HOST_RE = re.compile(r"^https?://[^\s/]+")

CONFIG_FILES = ("mneme.yaml", ".gitignore", "AGENTS.md")


@dataclass
class SetupPlan:
    """Valores do assistente.

    Campos de texto usam "" como "não mexer" na adoção. O host do Mem0 usa None
    para "não mexer" e "" para "desativar", porque desativar é uma decisão
    explícita e não pode ser confundida com ausência de informação.
    """

    instance_root: str
    instance_remote: str = ""
    drive_folder_id: str = ""
    mem0_host: str | None = None
    mem0_user: str = ""
    mem0_key_env: str = "MEM0_API_KEY"
    hermes_profile: str = ""
    harness: str = "hermes"
    skills_base: str = ""
    package_root: str = ""
    install: bool = True
    commit: bool = True


def detect_hermes_profiles(home: Path) -> list[Path]:
    profiles = home / ".hermes" / "profiles"
    if not profiles.is_dir():
        return []
    return sorted(path for path in profiles.iterdir() if path.is_dir())


def default_profile(home: Path) -> str:
    profiles = detect_hermes_profiles(home)
    if not profiles:
        return str(home / ".hermes" / "profiles" / "dev")
    for profile in profiles:
        if profile.name == "dev":
            return str(profile)
    return str(profiles[0])


def default_plan(home: Path | None = None) -> SetupPlan:
    base = home or Path.home()
    return SetupPlan(
        instance_root=os.environ.get("MNEME_ROOT") or str(base / "mneme"),
        hermes_profile=os.environ.get("HERMES_HOME") or default_profile(base),
        package_root=os.environ.get("MNEME_PACKAGE_ROOT") or str(base / ".local" / "share" / "mneme-package"),
    )


def existing_config(instance_root: str | os.PathLike) -> dict[str, Any]:
    """Configuração da instância que já existe, para servir de valor sugerido."""

    path = Path(instance_root).expanduser() / "mneme.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def validate(plan: SetupPlan, home: Path | None = None) -> tuple[list[str], list[str]]:
    """Devolve (erros, avisos). Erro impede a aplicação; aviso só informa."""

    base = home or Path.home()
    errors: list[str] = []
    warnings: list[str] = []

    root = Path(plan.instance_root).expanduser()
    if not plan.instance_root:
        errors.append("raiz da instância não definida")
    elif str(root) in {str(base), "/", ""}:
        errors.append(f"raiz da instância insegura: {root}")
    elif root.resolve() == PACKAGE_SRC.resolve():
        errors.append("raiz da instância não pode ser o próprio checkout do pacote")
    elif (root / ".git").exists() and not (root / "mneme.yaml").exists() and any(
        path for path in root.iterdir() if path.name != ".git"
    ):
        errors.append(f"destino não vazio e sem mneme.yaml: {root}")

    if plan.instance_remote and not GIT_URL_RE.match(plan.instance_remote):
        errors.append(f"remote Git inválido: {plan.instance_remote} (use https://, ssh:// ou git@host:repo)")

    if plan.drive_folder_id and not DRIVE_ID_RE.match(plan.drive_folder_id):
        errors.append(f"ID de pasta do Drive inválido: {plan.drive_folder_id}")

    if plan.mem0_host and not MEM0_HOST_RE.match(plan.mem0_host):
        errors.append(f"host do Mem0 inválido: {plan.mem0_host} (use http:// ou https://)")

    skill_base = plan.skills_base or (
        str(base / ".claude") if plan.harness == "claude" else plan.hermes_profile
    )
    if skill_base and not Path(skill_base).expanduser().is_dir():
        warnings.append(f"base da skill ainda não existe: {skill_base} (será criada)")
    if plan.package_root and Path(plan.package_root).expanduser().is_relative_to(base) is False:
        warnings.append(f"runtime fora do home: {plan.package_root}")

    if plan.drive_folder_id:
        if not shutil.which("rclone"):
            warnings.append("rclone ausente: o cache do Drive não vai sincronizar")
        elif "gdrive" not in _rclone_remotes():
            warnings.append("nenhum remote 'gdrive' configurado no rclone: rode `rclone config`")

    return errors, warnings


def _rclone_remotes() -> str:
    try:
        result = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


def _git_config_value(key: str) -> str:
    try:
        result = subprocess.run(["git", "config", "--get", key], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _remote_state(url: str) -> str:
    """Classifica o repositório remoto: com-conteudo, vazio ou inacessivel."""

    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "--tags", url],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return "inacessivel"
    if result.returncode != 0:
        return "inacessivel"
    return "com-conteudo" if result.stdout.strip() else "vazio"


def _install(plan: SetupPlan, env: dict[str, str]) -> dict[str, Any]:
    if not INSTALLER.is_file():
        return {"ok": False, "error": f"instalador ausente: {INSTALLER}"}
    command = ["bash", str(INSTALLER)]
    if plan.skills_base:
        command += ["--base-dir", str(Path(plan.skills_base).expanduser())]
    elif plan.harness and plan.harness != "hermes":
        command += ["--harness", plan.harness]
    elif plan.hermes_profile:
        command.append(str(Path(plan.hermes_profile).expanduser()))
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        return {"ok": False, "error": (result.stderr or result.stdout).strip()[:400]}
    return {"ok": True, "output": result.stdout.strip()}


def _patch_config(config_path: Path, plan: SetupPlan) -> list[str]:
    """Aplica só as chaves conhecidas. Não remove nada e não inventa seções."""

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    changed: list[str] = []

    def put(container: dict[str, Any], key: str, value: Any, label: str) -> None:
        if value in (None, "") or container.get(key) == value:
            return
        container[key] = value
        changed.append(label)

    git_section = data.setdefault("git", {})
    providers = data.setdefault("providers", {})
    mem0 = providers.setdefault("mem0", {})
    assets = providers.setdefault("assets", {})

    put(git_section, "remote", plan.instance_remote, "git.remote")
    put(mem0, "user_id", plan.mem0_user, "providers.mem0.user_id")
    put(mem0, "api_key_env", plan.mem0_key_env, "providers.mem0.api_key_env")
    put(assets, "folder_id", plan.drive_folder_id, "providers.assets.folder_id")

    # None = não mexer; "" = desativar de propósito; qualquer host = informado.
    if plan.mem0_host:
        put(mem0, "host", plan.mem0_host, "providers.mem0.host")
        from providers.mem0_provider import resolve_protocol

        protocol = resolve_protocol(plan.mem0_host)
        put(mem0, "api", protocol, "providers.mem0.api")
        if mem0.get("enabled") is not True:
            mem0["enabled"] = True
            changed.append("providers.mem0.enabled")
    elif plan.mem0_host == "" and mem0.get("enabled") is True:
        mem0["enabled"] = False
        changed.append("providers.mem0.enabled=false")

    if plan.drive_folder_id and assets.get("enabled") is not True:
        assets["enabled"] = True
        changed.append("providers.assets.enabled")

    if changed:
        config_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return changed


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    identity = ["-c", "user.name=Hermes Agent", "-c", "user.email=hermes@agents.local"]
    return subprocess.run(["git", *identity, *args], cwd=cwd, capture_output=True, text=True, check=False)


def _commit_config(instance_root: Path, paths: list[str], message: str) -> dict[str, Any]:
    if not (instance_root / ".git").is_dir():
        return {"ok": False, "error": "não é repositório Git"}
    probe = _git(["status", "--porcelain", "--", *paths], instance_root, check=False)
    if not probe.stdout.strip():
        return {"ok": True, "skipped": True, "reason": "nada a commitar"}
    _git(["add", "--", *paths], instance_root)
    commit = _git(["commit", "-m", message, "--", *paths], instance_root, check=False)
    if commit.returncode != 0:
        return {"ok": False, "error": (commit.stderr or commit.stdout).strip()[:300]}
    head = _git(["rev-parse", "--short", "HEAD"], instance_root, check=False).stdout.strip()
    return {"ok": True, "commit": head}


def apply_plan(
    plan: SetupPlan,
    *,
    home: Path | None = None,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
    output: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Executa o plano. Devolve um resumo verificável, sem efeitos colaterais em caso de erro."""

    base = home or Path.home()
    environment = dict(os.environ if env is None else env)
    instance_root = Path(plan.instance_root).expanduser()
    steps: list[dict[str, Any]] = []
    warnings: list[str] = []

    errors, warnings = validate(plan, base)
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "steps": steps}

    if dry_run:
        steps.append({"step": "dry-run", "detail": "nada foi escrito"})
        return {"ok": True, "dry_run": True, "steps": steps, "warnings": warnings}

    if plan.install:
        environment.setdefault("HOME", str(base))
        if plan.package_root:
            environment["MNEME_PACKAGE_ROOT"] = str(Path(plan.package_root).expanduser())
        installed = _install(plan, environment)
        steps.append({"step": "instalação", **installed})
        if not installed["ok"]:
            return {"ok": False, "errors": [installed["error"]], "warnings": warnings, "steps": steps}

    config_path = instance_root / "mneme.yaml"
    created_files: list[str] = []

    if not config_path.exists() and instance_root.exists() and any(
        path.name != ".git" for path in instance_root.iterdir()
    ):
        return {
            "ok": False,
            "errors": [f"destino não vazio: {instance_root}"],
            "warnings": warnings,
            "steps": steps,
        }

    if not config_path.exists() and plan.instance_remote:
        state = _remote_state(plan.instance_remote)
        steps.append({"step": "consulta do remote", "ok": state != "inacessivel", "estado": state})
        if state == "inacessivel":
            return {
                "ok": False,
                "errors": [
                    f"remote inacessível: {plan.instance_remote} "
                    "(confira URL, credencial e conectividade; sem remote, crie a instância local)"
                ],
                "warnings": warnings,
                "steps": steps,
            }
        if state == "com-conteudo" and not instance_root.exists():
            clone = subprocess.run(
                ["git", "clone", plan.instance_remote, str(instance_root)],
                capture_output=True,
                text=True,
            )
            steps.append({"step": "clone", "ok": clone.returncode == 0})
            if clone.returncode != 0:
                return {
                    "ok": False,
                    "errors": [(clone.stderr or clone.stdout).strip()[:300]],
                    "warnings": warnings,
                    "steps": steps,
                }
            # O clone pode trazer uma instância pronta; a decisão vem depois dele.

    if config_path.exists():
        mode = "adotada"
    else:
        instance_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        sys.path.insert(0, str(SYSTEM_DIR))
        from core import instance as instance_mod

        result = instance_mod.initialize_instance(
            instance_root,
            remote=plan.instance_remote,
            drive_folder_id=plan.drive_folder_id,
        )
        steps.append({"step": "instância", **{k: result[k] for k in ("ok", "root") if k in result}})
        if not result.get("ok"):
            return {"ok": False, "errors": [result.get("error", "falha ao criar a instância")], "warnings": warnings, "steps": steps}
        mode = "criada"
        created_files = [name for name in CONFIG_FILES if (instance_root / name).exists()]

    changed = _patch_config(config_path, plan)
    steps.append({"step": "configuração", "ok": True, "changed": changed})

    committed: dict[str, Any] = {"ok": True, "skipped": True, "reason": "commit desativado"}
    if plan.commit:
        targets = created_files or ([config_path.name] if changed else [])
        if targets:
            committed = _commit_config(instance_root, targets, "chore: configuração da instância pelo assistente")
        steps.append({"step": "commit", **committed})

    report = {
        "ok": True,
        "mode": mode,
        "instance_root": str(instance_root),
        "config": str(config_path),
        "changed": changed,
        "commit": committed,
        "warnings": warnings,
        "steps": steps,
        "files_created": created_files,
    }
    output(f"instância {mode}: {instance_root}")
    if changed:
        output("configuração: " + ", ".join(changed))
    for warning in warnings:
        output(f"aviso: {warning}")
    return report


def _ask(
    prompt: str,
    default: str,
    *,
    validate_value: Callable[[str], str | None] | None = None,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input_fn(f"{prompt}{suffix}: ").strip()
        if answer == "-":
            return ""
        if not answer:
            answer = default
        if validate_value:
            problem = validate_value(answer)
            if problem:
                output(f"  {problem}")
                continue
        return answer


def interactive_plan(
    plan: SetupPlan,
    *,
    home: Path | None = None,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
) -> SetupPlan:
    """Pergunta os valores que variam por máquina, um por vez, com validação."""

    base = home or Path.home()
    output("Assistente do Mneme. Enter aceita o valor entre colchetes; '-' desativa o Mem0.")
    profiles = [profile.name for profile in detect_hermes_profiles(base)]
    if profiles:
        output(f"Perfis do Hermes encontrados: {', '.join(profiles)}")

    # Valor sugerido: o que a instância já usa quando existe, senão o padrão do pacote.
    current = existing_config(plan.instance_root)
    providers = current.get("providers") or {}
    mem0_current = providers.get("mem0") or {}
    assets_current = providers.get("assets") or {}
    git_current = current.get("git") or {}
    remote_default = plan.instance_remote or str(git_current.get("remote") or "")
    folder_default = plan.drive_folder_id or str(assets_current.get("folder_id") or "")
    if plan.mem0_host is not None:
        host_default = plan.mem0_host
    elif mem0_current:
        host_default = str(mem0_current.get("host") or "") if mem0_current.get("enabled") else ""
    else:
        from providers.mem0_provider import DEFAULT_PLATFORM_HOST

        host_default = DEFAULT_PLATFORM_HOST
    user_default = plan.mem0_user or str(mem0_current.get("user_id") or ("default" if not mem0_current else ""))

    if not remote_default:
        suggestion = f"git@github.com:{_git_config_value('github.user') or 'SEU-USUARIO'}/mneme-hermes.git"
        output(f"Se o repositório privado dos dados ainda não existe, o nome sugerido é {suggestion}")

    root = _ask("1/6 raiz dos dados da instância", plan.instance_root, input_fn=input_fn, output=output)
    remote = _ask(
        "2/6 repositório Git da instância (privado; vazio = não mexer)",
        remote_default,
        validate_value=lambda value: None if not value or GIT_URL_RE.match(value) else "use https://, ssh:// ou git@host:repo",
        input_fn=input_fn,
        output=output,
    )
    folder = _ask(
        "3/6 pasta raiz do Google Drive (ID; vazio = não mexer)",
        folder_default,
        validate_value=lambda value: None if not value or DRIVE_ID_RE.match(value) else "ID do Drive parece inválido",
        input_fn=input_fn,
        output=output,
    )
    host = _ask(
        "4/6 host do Mem0 (cloud é o padrão; self-hosted seria http://127.0.0.1:8888; '-' desativa)",
        host_default,
        validate_value=lambda value: None if not value or MEM0_HOST_RE.match(value) else "use http:// ou https://",
        input_fn=input_fn,
        output=output,
    )
    user = _ask("5/6 user_id do Mem0", user_default, input_fn=input_fn, output=output)
    profile = _ask(
        "6/6 base da skill (perfil do Hermes; para Claude Code use ~/.claude)",
        plan.skills_base or plan.hermes_profile,
        input_fn=input_fn,
        output=output,
    )

    return SetupPlan(
        instance_root=root,
        instance_remote=remote,
        drive_folder_id=folder,
        mem0_host=host,
        mem0_user=user,
        mem0_key_env=plan.mem0_key_env,
        hermes_profile=profile,
        harness=plan.harness,
        skills_base=profile,
        package_root=plan.package_root,
        install=plan.install,
        commit=plan.commit,
    )


def describe(plan: SetupPlan) -> str:
    """Resumo antes de aplicar, para conferência humana."""

    if plan.mem0_host is None:
        mem0 = "(não mexer: mantém o que a instância já usa)"
    elif plan.mem0_host:
        mem0 = f"{plan.mem0_host} (user_id: {plan.mem0_user or '(não mexer)'})"
    else:
        mem0 = "(desativado)"

    lines = [
        f"raiz da instância     : {plan.instance_root}",
        f"remote Git da instância: {plan.instance_remote or '(sem remote)'}",
        f"pasta do Drive        : {plan.drive_folder_id or '(não mexer)'}",
        f"Mem0                  : {mem0}",
        f"skill ({plan.harness})          : {plan.skills_base or plan.hermes_profile}",
        f"runtime               : {plan.package_root}",
        f"instalar runtime/skill: {'sim' if plan.install else 'não'}",
    ]
    return "\n".join(lines)
