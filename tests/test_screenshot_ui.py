import logging
import struct
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
import zlib

from adb_clicker import ClickerApp


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
        with patch.object(self.root, "winfo_screenheight", return_value=540), \
                patch.object(self.root, "winfo_screenwidth", return_value=1000):
            self.app.showScreenshot((makePng(201, 401), 201, 401))
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


if __name__ == "__main__":
    unittest.main()
