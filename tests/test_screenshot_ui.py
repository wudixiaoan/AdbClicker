import logging
import json
from pathlib import Path
import struct
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
import zlib

from adb_clicker import ClickerApp
from click_engine import AdbClient, Display


def makePng(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    pixels = (b"\x00" + b"\xcc\xdd\xee" * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


class ScreenshotTests(unittest.TestCase):
    def setUp(self):
        self.handlers = list(logging.getLogger().handlers)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = ClickerApp(self.root)
        self.callbackErrors = []
        self.root.report_callback_exception = lambda *error: self.callbackErrors.append(error)

    def tearDown(self):
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.root.destroy()
        logging.getLogger().handlers[:] = self.handlers
        self.assertEqual(self.callbackErrors, [])

    def test_capture_requires_device(self):
        with patch.object(self.app, "error") as error, patch.object(self.app, "background") as background:
            self.app.capture()
            error.assert_called_once()
            background.assert_not_called()

    def test_multiple_selections_on_scaled_screenshot(self):
        self.root.deiconify()
        self.root.update()
        self.app.values["waitAfterMin"].set("2.125")
        self.app.values["waitAfterMax"].set("3.375")
        client = AdbClient(serial="test")
        with patch.object(client, "run", return_value=b"[Warning] Multiple displays were found!\n" + makePng(201, 401)), \
                patch.object(client, "displays", return_value=[Display("123", 0, 201, 401, "ON")]):
            screenshot = client.screenshot()
        with patch.object(self.root, "winfo_screenheight", return_value=540), \
                patch.object(self.root, "winfo_screenwidth", return_value=1000):
            self.app.showScreenshot(screenshot)
        window = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel))
        window.update()
        canvas = next(child for child in window.winfo_children() if isinstance(child, tk.Canvas))
        actions = window.winfo_children()[-1]
        addButton = next(child for child in actions.winfo_children()
                         if isinstance(child, ttk.Button) and child.cget("text") == "添加此区域")
        self.assertTrue(addButton.instate(["disabled"]))
        # Reverse drag on a 3x downscaled preview must map to original device pixels.
        canvas.event_generate("<ButtonPress-1>", x=40, y=60)
        canvas.event_generate("<B1-Motion>", x=10, y=20)
        canvas.event_generate("<ButtonRelease-1>", x=10, y=20)
        addButton.invoke()
        region = self.app.regions[0]
        self.assertEqual((region.waitAfterMin, region.waitAfterMax), (2.125, 3.375))
        self.assertEqual((region.x1, region.y1, region.x2, region.y2), (30, 60, 122, 182))
        self.assertTrue(addButton.instate(["disabled"]))
        self.assertTrue(window.winfo_exists())
        # Off-image pointer coordinates are clamped, including the partial last pixel.
        canvas.event_generate("<ButtonPress-1>", x=0, y=0)
        canvas.event_generate("<B1-Motion>", x=1000, y=1000)
        canvas.event_generate("<ButtonRelease-1>", x=1000, y=1000)
        addButton.invoke()
        self.assertEqual(len(self.app.regions), 2)
        region = self.app.regions[1]
        self.assertEqual((region.x1, region.y1, region.x2, region.y2), (0, 0, 200, 400))
        self.assertEqual(len(canvas.find_withtag("saved")), 4)
        self.assertEqual(len(self.app.tree.get_children()), 2)

    def test_screen_choice_targets_physical_id_and_resets_when_device_changes(self):
        self.app.serial.set("device-a")
        self.app.resetDisplays()
        self.app.screen.set(Display("222", 1, 1060, 2376, "ON").label)
        self.assertEqual(self.app.client().physicalDisplayId, "222")
        self.app.serial.set("device-b")
        self.assertEqual(self.app.client().physicalDisplayId, "")

    def test_screen_choice_survives_config_save_and_load(self):
        self.app.serial.set("device-a")
        self.app.resetDisplays()
        self.app.screen.set(Display("222", 0, 1060, 2376, "ON").label)
        self.app.values["waitAfterMin"].set("2.125")
        self.app.values["waitAfterMax"].set("3.375")
        self.app.addRegion()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = str(Path(directory) / "config.json")
            with patch("adb_clicker.filedialog.asksaveasfilename", return_value=path), \
                    patch.object(self.app, "error", side_effect=AssertionError("保存失败")):
                self.app.saveConfig()
            self.app.resetDisplays()
            with patch("adb_clicker.filedialog.askopenfilename", return_value=path), \
                    patch.object(self.app, "error", side_effect=AssertionError("加载失败")):
                self.app.loadConfig()
            self.assertEqual(self.app.client().physicalDisplayId, "222")
            self.assertEqual((self.app.regions[0].waitAfterMin, self.app.regions[0].waitAfterMax), (2.125, 3.375))

    def test_load_legacy_config_migrates_global_wait_to_each_region(self):
        config = {"version": 1, "adb": "adb", "serial": "test",
                  "settings": {"regionGapMin": 4.125, "regionGapMax": 5.375},
                  "regions": [{"name": name, "x1": 0, "y1": 0, "x2": 10, "y2": 10} for name in ("A", "B")]}
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch("adb_clicker.filedialog.askopenfilename", return_value=str(path)), \
                    patch.object(self.app, "error", side_effect=AssertionError("迁移失败")):
                self.app.loadConfig()
        self.assertEqual(len(self.app.regions), 2)
        for region in self.app.regions:
            self.assertEqual((region.waitAfterMin, region.waitAfterMax), (4.125, 5.375))
        self.app.tree.selection_set("0")
        self.app.selectRegion()
        self.app.values["waitAfterMin"].set("0.250")
        self.app.values["waitAfterMax"].set("0.750")
        self.app.updateRegion()
        self.assertEqual(self.app.regions[0].waitAfterMin, .25)
        self.assertEqual(self.app.regions[1].waitAfterMin, 4.125)


if __name__ == "__main__":
    unittest.main()
