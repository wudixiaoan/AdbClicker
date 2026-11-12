import random
import subprocess
import struct
import unittest
from unittest.mock import patch

from click_engine import AdbClient, Region, Settings, runTask


class FakeDevice:
    def __init__(self):
        self.taps = []

    def screenshot(self):
        return b"", 1080, 2400

    def tap(self, x, y):
        self.taps.append((x, y))


class FakeStop:
    def __init__(self, stopAt=None):
        self.waits = []
        self.stopped = False
        self.stopAt = stopAt

    def is_set(self):
        return self.stopped

    def wait(self, delay):
        self.waits.append(delay)
        self.stopped = len(self.waits) == self.stopAt
        return self.stopped


class EngineTests(unittest.TestCase):
    def test_screenshot_extracts_png_after_device_warning_without_changing_bytes(self):
        # 模拟真实设备多显示屏警告；图片内的换行字节不能被替换。
        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
               + struct.pack(">II", 2156, 2344) + b"\x08\x06\x00\x00\x00" + b"\x00" * 4
               + b"\r\n\r\r\n")
        client = AdbClient(serial="test")
        for prefix in (b"", b"[Warning] Multiple displays were found!\n" + b"x" * 300):
            with self.subTest(prefixLength=len(prefix)), patch.object(client, "run", return_value=prefix + png):
                data, width, height = client.screenshot()
                self.assertEqual(data, png)
                self.assertEqual((width, height), (2156, 2344))

    def test_screenshot_rejects_empty_text_truncated_and_invalid_headers(self):
        client = AdbClient(serial="test")
        for data in (b"", b"Permission denied", b"\x89PNG\r\n\x1a\n", b"\x89PNG\r\n\x1a\n" + b"x" * 40):
            with self.subTest(data=data), patch.object(client, "run", return_value=data):
                with self.assertRaises(RuntimeError):
                    client.screenshot()

    def test_region_order_and_three_independent_wait_types(self):
        device = FakeDevice()
        stop = FakeStop()
        regions = [Region("A", 10, 20, 10, 20, 2, 2), Region("B", 30, 40, 30, 40, 2, 2)]
        settings = Settings(intervalMin=20, intervalMax=20, gapMin=.2, gapMax=.2,
                            rounds=2, regionGapMin=3, regionGapMax=3)
        count = runTask(device, regions, settings, stop, lambda _: None)
        self.assertEqual(count, 8)
        self.assertEqual(device.taps, [(10, 20), (10, 20), (30, 40), (30, 40)] * 2)
        self.assertEqual(stop.waits, [20, .2, 3, .2] * 2)

    def test_random_counts_and_coordinates_remain_in_each_region(self):
        device = FakeDevice()
        regions = [Region("A", 0, 0, 10, 10, 1, 3), Region("B", 100, 100, 120, 120, 2, 4)]
        messages = []
        stop = FakeStop()
        count = runTask(device, regions, Settings(rounds=100), stop, messages.append, random.Random(42))
        self.assertTrue(300 <= count <= 700)
        for x, y in device.taps:
            self.assertTrue((0 <= x <= 10 and 0 <= y <= 10) or (100 <= x <= 120 and 100 <= y <= 120))
        for message in messages:
            if " · A · " in message:
                planned = int(message.split(" · ")[2].split("/")[1])
                self.assertTrue(1 <= planned <= 3)
            if " · B · " in message:
                planned = int(message.split(" · ")[2].split("/")[1])
                self.assertTrue(2 <= planned <= 4)
        self.assertGreater(len(set(device.taps)), 20)

    def test_stop_at_each_wait_boundary(self):
        for boundary, expected in ((1, 0), (2, 1), (3, 2), (4, 3)):
            with self.subTest(boundary=boundary):
                device = FakeDevice()
                regions = [Region("A", 0, 0, 0, 0, 2, 2), Region("B", 1, 1, 1, 1, 2, 2)]
                count = runTask(device, regions, Settings(rounds=1), FakeStop(boundary), lambda _: None)
                self.assertEqual(count, expected)
                self.assertEqual(len(device.taps), expected)

    def test_invalid_bounds_prevent_all_taps(self):
        device = FakeDevice()
        with self.assertRaises(ValueError):
            runTask(device, [Region("越界", 0, 0, 1080, 10)], Settings(rounds=1), FakeStop(), lambda _: None)
        self.assertEqual(device.taps, [])

    def test_invalid_settings(self):
        for settings in (Settings(intervalMin=float("nan")), Settings(gapMax=float("inf")),
                         Settings(regionGapMin=3, regionGapMax=2), Settings(rounds=-1)):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                settings.validate()

    def test_adb_failure_aborts_without_retry(self):
        device = FakeDevice()
        def fail(x, y):
            raise RuntimeError("设备离线")
        device.tap = fail
        with self.assertRaisesRegex(RuntimeError, "设备离线"):
            runTask(device, [Region("A", 0, 0, 1, 1)], Settings(rounds=2), FakeStop(), lambda _: None)

    @patch("click_engine.subprocess.run")
    def test_adb_targets_selected_device_and_uses_argument_list(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        AdbClient("C:/with space/adb.exe", "serial-1").tap(12, 34)
        self.assertEqual(run.call_args.args[0], ["C:/with space/adb.exe", "-s", "serial-1", "shell", "input", "tap", "12", "34"])
        self.assertEqual(run.call_args.kwargs["timeout"], 15)


if __name__ == "__main__":
    unittest.main()
