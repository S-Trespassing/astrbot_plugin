from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.self_update import SelfUpdateService
from services.storage import JsonStorage


class SelfUpdateServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.plugin_dir = self.root / "plugin"
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        self.service = SelfUpdateService(
            plugin_dir=self.plugin_dir,
            temp_dir=self.root / "temp",
            storage=JsonStorage(self.root, "self_update.json"),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_normalize_repo_url(self) -> None:
        self.assertEqual(
            SelfUpdateService.normalize_repo_url(
                "git@github.com:demo-user/astrbot-plugin.git"
            ),
            "https://github.com/demo-user/astrbot-plugin",
        )
        self.assertEqual(
            SelfUpdateService.normalize_repo_url(
                "https://github.com/demo-user/astrbot-plugin/"
            ),
            "https://github.com/demo-user/astrbot-plugin",
        )
        self.assertEqual(SelfUpdateService.normalize_repo_url("https://example.com/demo"), "")

    def test_locate_plugin_root(self) -> None:
        extracted_root = self.root / "archive"
        plugin_root = extracted_root / "repo-main" / "plugin"
        plugin_root.mkdir(parents=True, exist_ok=True)
        (plugin_root / "metadata.yaml").write_text("name: demo\n", encoding="utf-8")
        (plugin_root / "main.py").write_text("print('ok')\n", encoding="utf-8")

        self.assertEqual(
            SelfUpdateService.locate_plugin_root(extracted_root),
            plugin_root,
        )

    def test_apply_directory_snapshot_copies_and_removes_managed_files(self) -> None:
        self.service.storage.save(
            {
                "mode": "archive",
                "repo_url": "https://github.com/demo-user/astrbot-plugin",
                "branch": "main",
                "commit": "oldsha",
                "managed_files": ["old_file.txt"],
            }
        )
        (self.plugin_dir / "old_file.txt").write_text("old\n", encoding="utf-8")

        source_root = self.root / "source"
        (source_root / "services").mkdir(parents=True, exist_ok=True)
        (source_root / "main.py").write_text("print('new')\n", encoding="utf-8")
        (source_root / "metadata.yaml").write_text("version: v1.2.0\n", encoding="utf-8")
        (source_root / "services" / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")

        result = self.service.apply_directory_snapshot(
            source_root=source_root,
            repo_url="https://github.com/demo-user/astrbot-plugin",
            branch="main",
            commit="newsha",
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.copied_files, 3)
        self.assertEqual(result.removed_files, 1)
        self.assertFalse((self.plugin_dir / "old_file.txt").exists())
        self.assertTrue((self.plugin_dir / "main.py").exists())
        self.assertTrue((self.plugin_dir / "services" / "helper.py").exists())
        state = self.service.storage.load()
        self.assertEqual(state["commit"], "newsha")
        self.assertEqual(
            state["managed_files"],
            ["main.py", "metadata.yaml", "services/helper.py"],
        )


if __name__ == "__main__":
    unittest.main()
