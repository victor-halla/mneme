"""Assets grandes: cache local via rclone, em qualquer backend suportado.

O Git guarda apenas metadados em `resources/`. Os binários vivem no backend
remoto, que é o Google Drive por padrão mas pode ser qualquer remote do rclone
(Google Drive, S3, WebDAV, OneDrive, Backblaze, um diretório local). O cache
fica em `assets/drive`, é ignorado pelo Git e é sempre reconstruível.

Regra de ouro: o backend é a fonte, o cache é descartável. Nada aqui apaga ou
move conteúdo remoto.
"""

from __future__ import annotations

import abc
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

CACHE_DIR = Path("assets/drive")
DEFAULT_REMOTE = "gdrive:"
INSTALL_HINT = (
    "instale o rclone (https://rclone.org/install/) e autorize o backend com `rclone config`; "
    "sem remote configurado o cache não sincroniza"
)
CONFIG_HINT = "configure o backend com `rclone config` (ou ajuste providers.assets.remote)"
TRANSFERRED_RE = re.compile(r"Transferred:\s+(\d+)\s*/\s*(\d+)")
DRY_RUN_FILE_RE = re.compile(r"NOTICE:\s+(.+?):\s+Skipped copy as --dry-run")
TIMEOUT = 1800


# -- infraestrutura ------------------------------------------------------------


def _env(environment: dict[str, str] | None) -> dict[str, str]:
    env = os.environ.copy()
    if environment:
        env.update(environment)
    return env


def binary_available(executable: str) -> bool:
    """Um caminho absoluto é conferido direto; um nome, pelo PATH."""

    if os.sep in executable:
        return Path(executable).is_file()
    return bool(shutil.which(executable))


def _run(
    command: list[str],
    environment: dict[str, str] | None = None,
    timeout: int = TIMEOUT,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess | None:
    """Executa sem deixar exceção de processo escapar: devolve None se não subiu."""

    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=_env(environment),
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def rclone_info(executable: str = "rclone", environment: dict[str, str] | None = None) -> dict[str, Any]:
    """Versão e remotes configurados. Nunca falha: devolve o que conseguir apurar."""

    info: dict[str, Any] = {
        "executable": executable,
        "available": binary_available(executable),
        "version": "",
        "remotes": {},
    }
    if not info["available"]:
        return info

    version = _run([executable, "version"], environment, timeout=60)
    if version is not None:
        text = (version.stdout or version.stderr).strip()
        info["version"] = text.splitlines()[0].strip() if text else ""

    dump = _run([executable, "config", "dump"], environment, timeout=60)
    if dump is not None:
        payload = dump.stdout[dump.stdout.find("{") :] if "{" in dump.stdout else ""
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            info["remotes"] = {
                name: str((block or {}).get("type", "?")) for name, block in parsed.items()
            }
    return info


def resolve_remote(config: Any, remote: str = "") -> str:
    """Precedência: argumento explícito, configuração da instância, padrão."""

    block = getattr(config, "assets", {}) or {}
    chosen = str(remote or block.get("remote", "") or DEFAULT_REMOTE).strip()
    return chosen or DEFAULT_REMOTE


def remote_name(remote: str) -> str:
    """Nome do remote configurado, ou vazio quando é caminho local ou remote ad-hoc."""

    if remote.startswith(":") or ":" not in remote:
        return ""
    return remote.split(":", 1)[0]


def summarize_error(text: str) -> str:
    """Prefere a linha crítica do rclone, sem timestamp, em vez do log inteiro."""

    lines = [line.strip() for line in (text or "").strip().splitlines() if line.strip()]
    priority = [
        line
        for line in lines
        if "CRITICAL:" in line or "ERROR:" in line or "Fatal error:" in line or "NOTICE:" in line
    ]
    chosen = (priority or lines or [""])[-1]
    cleaned = re.sub(r"^\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\s+", "", chosen)
    cleaned = re.sub(r"^(?:CRITICAL|ERROR|NOTICE|INFO|DEBUG)\s*:\s*", "", cleaned)
    return cleaned[:400]


def _cache_checks(config: Any) -> tuple[Path, Path, list[str], list[str]]:
    """Valida o destino do cache antes de qualquer cópia."""

    block = getattr(config, "assets", {}) or {}
    problems: list[str] = []
    warnings: list[str] = []
    root = Path(config.root).resolve()
    cache_setting = str(block.get("cache_dir", CACHE_DIR.as_posix())).strip() or CACHE_DIR.as_posix()
    cache_relative = Path(cache_setting)
    if cache_relative != CACHE_DIR:
        problems.append(f"providers.assets.cache_dir deve ser {CACHE_DIR.as_posix()} (veio {cache_setting})")
        return root, root / CACHE_DIR, problems, warnings
    current = root
    for part in cache_relative.parts:
        current = current / part
        if current.is_symlink():
            problems.append(f"cache_dir contém symlink: {current.relative_to(root)}")
    ignored = _run(["git", "check-ignore", "-q", "--", cache_relative.as_posix()], timeout=60, cwd=root)
    if ignored is None or ignored.returncode != 0:
        problems.append(f"{CACHE_DIR.as_posix()} não está ignorado pelo Git")
    return root, root / cache_relative, problems, warnings


def check_assets(
    config: Any,
    *,
    remote: str = "",
    executable: str = "rclone",
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Diagnóstico completo: binário, remote, tipo, pasta do Drive, cache e Git."""

    block = getattr(config, "assets", {}) or {}
    enabled = bool(block.get("enabled", True))
    chosen = resolve_remote(config, remote)
    folder_id = str(block.get("folder_id", "")).strip()
    info = rclone_info(executable, environment)
    root, cache, problems, warnings = _cache_checks(config)

    name = remote_name(chosen)
    remote_type = info["remotes"].get(name, "") if name else "local"
    if not info["available"]:
        problems.append(f"rclone não encontrado: {executable}")
    elif name and name not in info["remotes"]:
        problems.append(f"remote não configurado: {chosen}")
    if remote_type == "drive" and not folder_id:
        problems.append("remote do Google Drive sem providers.assets.folder_id: copiaria a raiz inteira")
    if folder_id and remote_type not in ("", "drive"):
        warnings.append(
            f"folder_id é do Google Drive e será ignorado no remote {chosen} (tipo {remote_type})"
        )
    if not enabled and folder_id:
        warnings.append(
            "providers.assets.enabled está false: a pasta está configurada mas o cache não sincroniza"
        )

    return {
        "ok": not problems,
        "status": "pronto" if not problems else ("rclone_ausente" if not info["available"] else "incompleto"),
        "enabled": enabled,
        "root": str(root),
        "cache": str(cache),
        "remote": chosen,
        "remote_name": name,
        "remote_type": remote_type or "desconhecido",
        "folder_id": folder_id,
        "rclone": info,
        "problems": problems,
        "warnings": warnings,
        "hint": "" if info["available"] else INSTALL_HINT,
    }


def _cache_size(cache: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for path in cache.rglob("*"):
        if path.is_file() and not path.is_symlink():
            files += 1
            total += path.stat().st_size
    return files, total


def sync_assets(
    config: Any,
    *,
    remote: str = "",
    executable: str = "rclone",
    environment: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Copia do backend para o cache local, sem apagar nada.

    Falha com erro limpo, e não com exceção, quando o rclone não existe, o remote
    não está configurado ou o cache não é o esperado.
    """

    report = check_assets(config, remote=remote, executable=executable, environment=environment)
    context = {
        key: report[key]
        for key in ("cache", "remote", "remote_name", "remote_type", "folder_id", "rclone", "warnings")
    }
    if not report["ok"]:
        return {
            "ok": False,
            "status": report["status"],
            "error": "; ".join(report["problems"]),
            "hint": report["hint"] or (CONFIG_HINT if not report["rclone"]["available"] else ""),
            **context,
        }

    cache = Path(report["cache"])
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache.chmod(0o700)

    command = [executable, "copy", report["remote"], str(cache), "--create-empty-src-dirs"]
    if report["remote_type"] == "drive" and report["folder_id"]:
        command += ["--drive-root-folder-id", report["folder_id"]]
    if dry_run:
        command += ["--dry-run", "-v"]

    completed = _run(command, environment)
    if completed is None:
        return {
            "ok": False,
            "status": "falha_ao_executar",
            "error": f"não foi possível executar {executable}",
            "hint": INSTALL_HINT,
            "command": command,
            **context,
        }

    output = f"{completed.stdout or ''}{completed.stderr or ''}"
    transferred = TRANSFERRED_RE.search(output)
    planned = DRY_RUN_FILE_RE.findall(output)
    files_local, bytes_local = _cache_size(cache) if not dry_run else (0, 0)
    return {
        "ok": completed.returncode == 0,
        "status": "dry_run" if dry_run else ("sincronizado" if completed.returncode == 0 else "falhou"),
        "cache": str(cache),
        "remote": report["remote"],
        "remote_name": report["remote_name"],
        "remote_type": report["remote_type"],
        "folder_id": report["folder_id"],
        "rclone": report["rclone"],
        "warnings": report["warnings"],
        "command": command,
        "dry_run": dry_run,
        "would_copy": planned[:20],
        "would_copy_count": len(planned),
        "transferred": int(transferred.group(1)) if transferred else None,
        "files_local": files_local,
        "bytes_local": bytes_local,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "")[-2000:],
        "error": summarize_error(completed.stderr) if completed.returncode else "",
        "stderr": (completed.stderr or "").strip()[-2000:] if completed.returncode else "",
    }


# -- provider de ativos --------------------------------------------------------


class AssetProvider(abc.ABC):
    """Interface de armazenamento de ativos grandes."""

    name = "abstract"

    @abc.abstractmethod
    def put(self, path: str | Path, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def get(self, path: str, destination: str | Path) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def metadata(self, path: str) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def share(self, path: str) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def delete(self, path: str) -> dict[str, Any]:
        raise NotImplementedError

    # -- utilidades comuns ----------------------------------------------------
    @staticmethod
    def checksum(path: str | Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @classmethod
    def describe(cls, path: str | Path, provider: str) -> dict[str, Any]:
        target = Path(path)
        return {
            "id": f"resource-{target.stem.lower().replace(' ', '-')}",
            "provider": provider,
            "file_id": None,
            "mime_type": _guess_mime(target),
            "size": target.stat().st_size if target.exists() else None,
            "sha256": cls.checksum(target) if target.exists() else None,
            "relations": [],
        }


class RcloneAssetProvider(AssetProvider):
    """Acesso a arquivos no backend por rclone.

    `path` é sempre relativo à raiz do remote configurado. Com remote do Google
    Drive, a raiz é `providers.assets.folder_id`; nos demais backends, é a raiz
    do próprio remote.
    """

    name = "rclone"

    def __init__(self, config: Any, remote: str = "", executable: str = "rclone"):
        self.config = config
        self.remote = resolve_remote(config, remote)
        self.executable = executable
        state = check_assets(config, remote=self.remote, executable=executable)
        self.ready = state["ok"]
        self.reason = "; ".join(state["problems"])
        self.flags: list[str] = []
        if state["remote_type"] == "drive" and state["folder_id"]:
            self.flags = ["--drive-root-folder-id", state["folder_id"]]

    def _remote_path(self, path: str) -> str:
        return f"{self.remote.rstrip('/')}/{path.lstrip('/')}" if path else self.remote

    def _blocked(self) -> dict[str, Any] | None:
        if not self.ready:
            return {"ok": False, "status": "unavailable", "error": self.reason, "provider": self.name}
        return None

    def _call(self, operation: str, *args: str) -> tuple[dict[str, Any] | None, str]:
        command = [self.executable, operation, *args, *self.flags]
        completed = _run(command, timeout=600)
        if completed is None:
            return None, f"não foi possível executar {self.executable}"
        if completed.returncode != 0:
            return None, summarize_error(completed.stderr or completed.stdout)
        return {"command": command}, (completed.stdout or "").strip()

    def put(self, path: str | Path, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        blocked = self._blocked()
        if blocked:
            return blocked
        local = Path(path)
        if not local.is_file():
            return {"ok": False, "provider": self.name, "error": f"arquivo local inexistente: {local}"}
        remote_path = self._remote_path((metadata or {}).get("remote_path") or local.name)
        result, output = self._call("copyto", str(local), remote_path)
        if result is None:
            return {"ok": False, "provider": self.name, "error": output, "remote_path": remote_path}
        return {
            "ok": True,
            "provider": self.name,
            "remote_path": remote_path,
            "sha256": self.checksum(local),
            "size": local.stat().st_size,
        }

    def get(self, path: str, destination: str | Path) -> dict[str, Any]:
        blocked = self._blocked()
        if blocked:
            return blocked
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        result, output = self._call("copyto", self._remote_path(path), str(target))
        if result is None:
            return {"ok": False, "provider": self.name, "error": output, "remote_path": path}
        return {"ok": True, "provider": self.name, "remote_path": path, "local_path": str(target)}

    def metadata(self, path: str) -> dict[str, Any]:
        blocked = self._blocked()
        if blocked:
            return blocked
        result, output = self._call("lsjson", "--stat", self._remote_path(path))
        if result is None:
            return {"ok": False, "provider": self.name, "error": output, "remote_path": path}
        try:
            payload = json.loads(output[output.find("{") :]) if "{" in output else {}
        except json.JSONDecodeError:
            payload = {}
        return {"ok": True, "provider": self.name, "remote_path": path, "metadata": payload}

    def share(self, path: str) -> dict[str, Any]:
        blocked = self._blocked()
        if blocked:
            return blocked
        state = check_assets(self.config, remote=self.remote, executable=self.executable)
        if state["remote_type"] != "drive":
            return {
                "ok": False,
                "provider": self.name,
                "status": "unsupported",
                "error": f"compartilhamento por link exige remote do Google Drive (atual: {state['remote_type']})",
            }
        result, output = self._call("link", self._remote_path(path))
        if result is None:
            return {"ok": False, "provider": self.name, "error": output}
        return {"ok": True, "provider": self.name, "remote_path": path, "url": output}

    def delete(self, path: str) -> dict[str, Any]:
        blocked = self._blocked()
        if blocked:
            return blocked
        result, output = self._call("deletefile", self._remote_path(path))
        if result is None:
            return {"ok": False, "provider": self.name, "error": output, "remote_path": path}
        return {"ok": True, "provider": self.name, "deleted": path}


def get_asset_provider(config: Any) -> AssetProvider:
    block = getattr(config, "assets", {}) or {}
    provider = str(block.get("provider", "rclone"))
    if provider in {"rclone", "gdrive"}:
        return RcloneAssetProvider(config)
    raise ValueError(f"provider de assets desconhecido: {provider}")


def _guess_mime(path: Path) -> str:
    import mimetypes

    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"
