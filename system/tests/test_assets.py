"""Testes do cache local de assets do Google Drive."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parents[1]
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from core.config import MnemeConfig
from core.instance import initialize_instance
from providers.assets import sync_drive_cache


class TestDriveCache(unittest.TestCase):
    def test_sync_uses_configured_folder_and_gitignored_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-drive-") as temp:
            root = Path(temp) / "mneme"
            initialize_instance(root, drive_folder_id="folder-123")
            config = MnemeConfig(root=root)
            recorder = Path(temp) / "rclone-args.json"
            fake = Path(temp) / "rclone"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "open(os.environ['RCLONE_ARGS_OUT'], 'w').write(json.dumps(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)

            result = sync_drive_cache(
                config,
                remote="gdrive:",
                executable=str(fake),
                environment={"RCLONE_ARGS_OUT": str(recorder)},
                dry_run=True,
            )

            self.assertTrue(result["ok"], result)
            args = json.loads(recorder.read_text(encoding="utf-8"))
            self.assertEqual(args[:3], ["copy", "gdrive:", str(root / "assets/drive")])
            self.assertIn("--drive-root-folder-id", args)
            self.assertIn("folder-123", args)
            self.assertIn("--dry-run", args)

    def test_sync_rejects_cache_outside_instance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-drive-escape-") as temp:
            root = Path(temp) / "mneme"
            initialize_instance(root, drive_folder_id="folder-123")
            config_path = root / "mneme.yaml"
            import yaml

            raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            raw["providers"]["assets"]["cache_dir"] = "../outside"
            config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            fake = Path(temp) / "rclone"
            fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake.chmod(0o700)

            result = sync_drive_cache(MnemeConfig(root=root), executable=str(fake))

            self.assertFalse(result["ok"], result)
            self.assertIn("cache_dir", result["error"])
            self.assertFalse((Path(temp) / "outside").exists())

    def test_cli_exposes_drive_cache_sync(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mneme-drive-cli-") as temp:
            root = Path(temp) / "mneme"
            initialize_instance(root, drive_folder_id="folder-123")
            recorder = Path(temp) / "rclone-args.json"
            fake = Path(temp) / "rclone"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "open(os.environ['RCLONE_ARGS_OUT'], 'w').write(json.dumps(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)
            env = os.environ.copy()
            env["RCLONE_ARGS_OUT"] = str(recorder)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SYSTEM_DIR / "scripts/brain.py"),
                    "--root",
                    str(root),
                    "assets",
                    "sync",
                    "--remote",
                    "gdrive:",
                    "--rclone",
                    str(fake),
                    "--dry-run",
                    "--json",
                ],
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            self.assertTrue(recorder.is_file())


if __name__ == "__main__":
    unittest.main()
