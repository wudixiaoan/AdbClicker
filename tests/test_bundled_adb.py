from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from click_engine import AdbClient, BUILTIN_ADB, bundledAdbPath, resolveAdbPath


class BundledAdbTests(unittest.TestCase):
    def test_frozen_path_uses_exe_directory_not_working_directory(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", "C:/portable/AdbClicker.exe"):
            self.assertEqual(bundledAdbPath(), Path("C:/portable/adb/adb.exe"))

    def test_builtin_and_legacy_adb_use_packaged_binary(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            binary = Path(directory) / "adb.exe"
            binary.touch()
            with patch("click_engine.bundledAdbPath", return_value=binary):
                self.assertEqual(AdbClient().executable, str(binary))
                self.assertEqual(resolveAdbPath(BUILTIN_ADB), str(binary))
                self.assertEqual(resolveAdbPath("C:/custom/adb.exe"), "C:/custom/adb.exe")

    def test_incomplete_portable_package_reports_actionable_error(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            with patch("click_engine.bundledAdbPath", return_value=Path(directory) / "missing.exe"):
                with self.assertRaisesRegex(ValueError, "完整解压"):
                    resolveAdbPath(BUILTIN_ADB)


if __name__ == "__main__":
    unittest.main()
