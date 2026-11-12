import logging
from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from adb_clicker import ClickerApp
from click_engine import Display
from screen_preview import previewCommand, runPreview


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.handlers = list(logging.getLogger().handlers)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = ClickerApp(self.root, self.temp.name)
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.app.serial.set("test")
        self.app.resetDisplays()

    def tearDown(self):
        self.app.stopPreview()
        if self.app.previewThread is not None:
            self.app.previewThread.join(3)
        self.root.destroy()
        logging.getLogger().handlers[:] = self.handlers
        self.temp.cleanup()

    def finish(self):
        self.app.previewThread.join(3)
        while True:
            event, value = self.app.events.get_nowait()
            if event == "preview-ended":
                self.app.receivePreviewEnd(value)
                return

    def test_default_off_and_normal_window_close_do_not_restart(self):
        with patch("adb_clicker.runPreview") as run:
            self.app.queuePreview()
            run.assert_not_called()
            self.app.previewEnabled.set(True)
            self.app.togglePreview()
            self.app.queuePreview()
            self.finish()
            self.assertFalse(self.app.previewEnabled.get())
            self.app.queuePreview()
            run.assert_called_once()

    def test_switch_screen_cancels_old_session_before_starting_new_one(self):
        entered = threading.Event()
        def run(client, stop, report):
            entered.set()
            stop.wait(3)
        with patch("adb_clicker.runPreview", side_effect=run) as worker:
            self.app.previewEnabled.set(True)
            self.app.queuePreview()
            self.assertTrue(entered.wait(2))
            self.app.screen.set("222")
            self.app.queuePreview()
            self.assertTrue(self.app.previewStop.is_set())
            self.finish()
            self.assertTrue(self.app.previewEnabled.get())
            self.app.queuePreview()
            self.app.stopPreview()
            self.finish()
            self.assertEqual(worker.call_count, 2)
            self.assertFalse(self.app.previewEnabled.get())
            self.assertFalse(self.app.stopEvent.is_set())

    def test_start_failure_only_disables_preview(self):
        self.app.previewEnabled.set(True)
        self.app.setBusy(True, running=True)
        with patch("adb_clicker.runPreview", side_effect=RuntimeError("device offline")):
            self.app.queuePreview()
            self.finish()
        self.assertFalse(self.app.previewEnabled.get())
        self.assertTrue(self.app.busy)
        self.assertFalse(self.app.stopEvent.is_set())
        self.assertIn("device offline", self.app.status.get())

    def test_scrcpy_command_and_environment_use_selected_device_and_logical_screen(self):
        client = Mock(serial="serial-1", physicalDisplayId="222", executable="C:/portable/adb/adb.exe")
        client.displays.return_value = [Display("222", 1, 1060, 2376, "ON")]
        process = Mock(returncode=0)
        process.communicate.return_value = (b"", None)
        process.poll.return_value = 0
        with patch("screen_preview.subprocess.Popen", return_value=process) as launch:
            runPreview(client, threading.Event(), Mock())
        args = launch.call_args.args[0]
        self.assertIn("--serial=serial-1", args)
        self.assertIn("--display-id=1", args)
        self.assertNotIn("--no-control", args)
        self.assertIn("--mouse=sdk", args)
        self.assertIn("--keyboard=disabled", args)
        self.assertIn("--no-clipboard-autosync", args)
        self.assertIn("--no-audio", args)
        self.assertIn("--hwdec=disabled", args)
        self.assertIn("--no-window-aspect-ratio-lock", args)
        self.assertIn("--render-fit=letterbox", args)
        self.assertNotIn("--window-borderless", args)
        self.assertEqual(launch.call_args.kwargs["env"]["ADB"], client.executable)
        client.screenshot.assert_not_called()
        client.tap.assert_not_called()

    def test_cancel_before_start_never_launches_scrcpy(self):
        client = Mock(serial="test", physicalDisplayId="")
        client.displays.return_value = [Display("222", 0, 1060, 2376, "ON")]
        stop = threading.Event()
        stop.set()
        with patch("screen_preview.subprocess.Popen") as launch:
            runPreview(client, stop, Mock())
            launch.assert_not_called()

    def test_stop_terminates_only_owned_process(self):
        client = Mock(serial="test", physicalDisplayId="")
        client.displays.return_value = [Display("222", 0, 1060, 2376, "ON")]
        process = Mock(returncode=-1)
        process.communicate.return_value = (b"", None)
        process.poll.side_effect = [None, -1]
        stop = threading.Event()
        with patch("screen_preview.subprocess.Popen", return_value=process):
            runPreview(client, stop, lambda _: stop.set())
        process.terminate.assert_called_once()
        process.stdout.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
