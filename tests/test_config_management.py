import json
import logging
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from adb_clicker import ClickerApp
from config_store import ConfigStore, writeConfig


class ConfigManagementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.path = Path(self.directory.name)
        self.handlers = list(logging.getLogger().handlers)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = ClickerApp(self.root, self.path)
        self.app.addRegion()

    def tearDown(self):
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.root.destroy()
        logging.getLogger().handlers[:] = self.handlers
        self.directory.cleanup()

    def select(self, name):
        names = self.app.configList.get(0, "end")
        self.app.configList.selection_clear(0, "end")
        self.app.configList.selection_set(names.index(name))

    def test_create_load_update_current_not_merely_selected_and_delete(self):
        self.app.configName.set("方案A")
        self.app.saveNewConfig()
        self.app.configName.set("方案B")
        self.app.saveNewConfig()
        self.select("方案A")
        self.app.loadListedConfig()
        self.select("方案B")
        self.app.values["rounds"].set("5")
        self.app.updateCurrentConfig()
        self.assertEqual(json.loads((self.path / "方案A.json").read_text(encoding="utf-8"))["settings"]["rounds"], 5)
        self.assertEqual(json.loads((self.path / "方案B.json").read_text(encoding="utf-8"))["settings"]["rounds"], 0)
        with patch("adb_clicker.messagebox.askyesno", return_value=False):
            self.app.deleteListedConfig()
        self.assertTrue((self.path / "方案B.json").exists())
        with patch("adb_clicker.messagebox.askyesno", return_value=True):
            self.app.deleteListedConfig()
        self.assertFalse((self.path / "方案B.json").exists())
        self.assertEqual(self.app.currentConfig.stem, "方案A")
        self.select("方案A")
        with patch("adb_clicker.messagebox.askyesno", return_value=True):
            self.app.deleteListedConfig()
        self.assertIsNone(self.app.currentConfig)
        self.assertEqual(len(self.app.regions), 1)

    def test_existing_name_and_invalid_json_preserve_current_data(self):
        self.app.configName.set("原配置")
        self.app.saveNewConfig()
        original = (self.path / "原配置.json").read_bytes()
        with patch.object(self.app, "error") as error:
            self.app.saveNewConfig()
            error.assert_called_once()
        self.assertEqual((self.path / "原配置.json").read_bytes(), original)
        (self.path / "损坏.json").write_text("{bad", encoding="utf-8")
        self.app.refreshConfigList()
        self.select("损坏")
        with patch.object(self.app, "error") as error:
            self.app.loadListedConfig()
            error.assert_called_once()
        self.assertEqual(self.app.currentConfig.stem, "原配置")
        self.assertEqual(len(self.app.regions), 1)

    def test_failed_atomic_update_keeps_previous_file(self):
        path = self.path / "original.json"
        writeConfig(path, {"value": 1})
        with patch("config_store.Path.replace", side_effect=OSError("写入失败")):
            with self.assertRaises(OSError):
                writeConfig(path, {"value": 2})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})
        self.assertEqual(list(self.path.glob("*.tmp")), [])

    def test_invalid_names_cannot_escape_config_directory(self):
        store = ConfigStore(self.path)
        for name in ("", "../other", "..\\other", "C:\\other", "CON", "A:B", "test."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                store.path(name)
        self.assertEqual(store.path("中文配置"), self.path / "中文配置.json")
        self.assertEqual(store.path("example.json"), self.path / "example.json.json")


if __name__ == "__main__":
    unittest.main()
