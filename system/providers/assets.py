"""AssetProvider — interface para binários grandes (fase seguinte: Google Drive).

O Git guarda apenas metadados: id, provider, file_id, mime_type, size, sha256, relations.
"""

from __future__ import annotations

import abc
import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any


class AssetProvider(abc.ABC):
    """Interface de armazenamento de ativos grandes."""

    name = "abstract"

    @abc.abstractmethod
    def put(self, path: str | Path, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def get(self, file_id: str, destination: str | Path) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def metadata(self, file_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def share(self, file_id: str, email: str, role: str = "reader") -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def delete(self, file_id: str) -> dict[str, Any]:
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


class GoogleDriveAssetProvider(AssetProvider):
    """Provider futuro. Não implementado nesta versão (Fase 21 do plano)."""

    name = "gdrive"

    def __init__(self, credentials_path: str | None = None):
        self.credentials_path = credentials_path

    def _todo(self, operation: str) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "not_implemented",
            "provider": self.name,
            "operation": operation,
            "note": (
                "AssetProvider preparado. Implemente com a API do Google Drive "
                "(google-workspace/Composio) quando o core estiver em uso. "
                "Enquanto isso, registre apenas metadados em resources/."
            ),
        }

    def put(self, path: str | Path, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._todo("put")

    def get(self, file_id: str, destination: str | Path) -> dict[str, Any]:
        return self._todo("get")

    def metadata(self, file_id: str) -> dict[str, Any]:
        return self._todo("metadata")

    def share(self, file_id: str, email: str, role: str = "reader") -> dict[str, Any]:
        return self._todo("share")

    def delete(self, file_id: str) -> dict[str, Any]:
        return self._todo("delete")


def sync_drive_cache(
    config: Any,
    *,
    remote: str = "gdrive:",
    executable: str = "rclone",
    environment: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Atualiza o cache local a partir do Drive sem apagar arquivos locais."""
    assets = getattr(config, "assets", {}) or {}
    folder_id = str(assets.get("folder_id", "")).strip()
    if not folder_id:
        return {"ok": False, "error": "providers.assets.folder_id não configurado"}
    cache_setting = str(assets.get("cache_dir", "assets/drive")).strip()
    cache_relative = Path(cache_setting)
    if cache_relative != Path("assets/drive"):
        return {"ok": False, "error": "providers.assets.cache_dir deve ser assets/drive"}
    root = Path(config.root).resolve()
    cache = root / cache_relative
    current = root
    for part in cache_relative.parts:
        current = current / part
        if current.is_symlink():
            return {"ok": False, "error": f"cache_dir contém symlink: {current.relative_to(root)}"}
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", cache_relative.as_posix()],
        cwd=root,
        capture_output=True,
    )
    if ignored.returncode != 0:
        return {"ok": False, "error": "assets/drive não está ignorado pelo Git"}
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache.chmod(0o700)
    command = [
        executable,
        "copy",
        remote,
        str(cache),
        "--drive-root-folder-id",
        folder_id,
        "--create-empty-src-dirs",
    ]
    if dry_run:
        command.append("--dry-run")
    env = os.environ.copy()
    if environment:
        env.update(environment)
    completed = subprocess.run(command, capture_output=True, text=True, env=env)
    return {
        "ok": completed.returncode == 0,
        "cache": str(cache),
        "folder_id": folder_id,
        "remote": remote,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "error": completed.stderr.strip() if completed.returncode else "",
    }


def get_asset_provider(config: Any) -> AssetProvider:
    block = getattr(config, "assets", {}) or {}
    provider = str(block.get("provider", "gdrive"))
    if provider == "gdrive":
        return GoogleDriveAssetProvider()
    raise ValueError(f"provider de assets desconhecido: {provider}")


def _guess_mime(path: Path) -> str:
    import mimetypes

    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"
