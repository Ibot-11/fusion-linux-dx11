import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("processes", Path(__file__).resolve().parents[1] / "processes.py")
processes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(processes)


class FusionProcessTest(unittest.TestCase):
    def test_fusion_renamed_by_chromium_is_still_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "42").mkdir()
            (root / "42/comm").write_text("CrBrowserMain\n")
            (root / "42/cmdline").write_bytes(b"C:\\Autodesk\\Fusion360.exe\0")
            with patch.object(processes, "Path", return_value=root):
                self.assertTrue(processes.fusion_running())

    def test_launcher_argument_does_not_count_as_running_fusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "42").mkdir()
            (root / "42/cmdline").write_bytes(b"steam.exe\0C:\\Autodesk\\Fusion360.exe\0")
            with patch.object(processes, "Path", return_value=root):
                self.assertFalse(processes.fusion_running())


if __name__ == "__main__":
    unittest.main(verbosity=2)
