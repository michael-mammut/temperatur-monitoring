import importlib.util
import os
import sys
import tempfile
import unittest
from unittest.mock import call, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

import deploy_esp32


class CompilesToMpyTests(unittest.TestCase):
    def test_regular_modules_are_compiled(self):
        self.assertTrue(deploy_esp32.compiles_to_mpy("WebServer/webserver.py"))
        self.assertTrue(deploy_esp32.compiles_to_mpy("WlanNetwork/setupmode.py"))

    def test_boot_and_main_stay_py_because_only_those_are_auto_run(self):
        self.assertFalse(deploy_esp32.compiles_to_mpy("boot.py"))
        self.assertFalse(deploy_esp32.compiles_to_mpy("main.py"))

    def test_the_program_itself_is_compiled(self):
        """main.py is only a starter; compiling the 10 KB program on the
        board cost ~2.6 KB RAM (measured)."""
        self.assertIn("aquarium.py", deploy_esp32.FILES)
        self.assertTrue(deploy_esp32.compiles_to_mpy("aquarium.py"))

    def test_config_files_stay_py_so_they_remain_editable(self):
        self.assertFalse(deploy_esp32.compiles_to_mpy("config.py"))
        self.assertFalse(deploy_esp32.compiles_to_mpy("WlanNetwork/config.py"))

    def test_package_markers_stay_py(self):
        self.assertFalse(deploy_esp32.compiles_to_mpy("WebServer/pages/__init__.py"))

    def test_every_deployed_file_still_exists(self):
        """Regression guard: WebServer/pages/datetimesettings.py was once
        missing from FILES, so a fresh board crashed on import."""
        root = deploy_esp32.PROJECT_ROOT
        for rel_path in deploy_esp32.FILES:
            if rel_path.endswith("config.py"):
                continue  # real configs are git-ignored, only *.example.py are in the repo
            self.assertTrue(os.path.exists(os.path.join(root, rel_path)), rel_path)

    def test_every_project_module_is_deployed(self):
        root = deploy_esp32.PROJECT_ROOT
        deployed = set(deploy_esp32.FILES)
        for folder in ("WebServer", "WebServer/pages", "WlanNetwork", "Monitoring", "Notification",
                       "Temperature", "GpioControl", "Airpump"):
            for name in os.listdir(os.path.join(root, folder)):
                if name.endswith(".py") and not name.endswith(".example.py"):
                    self.assertIn(folder + "/" + name, deployed)


class CompilerSelectionTests(unittest.TestCase):
    def test_unknown_mpy_version_aborts(self):
        with self.assertRaises(SystemExit):
            deploy_esp32.mpy_compiler_for(99)

    def test_missing_compiler_aborts_with_install_hint(self):
        with patch("builtins.__import__", side_effect=ImportError):
            with self.assertRaises(SystemExit) as ctx:
                deploy_esp32.mpy_compiler_for(5)
        self.assertIn("pip install mpy-cross-v5", str(ctx.exception))


class UploadTests(unittest.TestCase):
    def test_compiled_module_is_uploaded_as_mpy_and_old_py_removed(self):
        """MicroPython prefers x.py over x.mpy - a leftover .py would keep
        the old code running."""
        with patch.object(deploy_esp32, "compile_to_mpy", return_value="/tmp/x.mpy"), \
             patch.object(deploy_esp32, "write_file") as write_file, \
             patch.object(deploy_esp32, "remove_file") as remove_file:
            deploy_esp32.upload("ser", "WebServer/webserver.py", "mpy_cross_v5", "/tmp")

        write_file.assert_called_once_with("ser", "WebServer/webserver.mpy", "/tmp/x.mpy")
        remove_file.assert_called_once_with("ser", "WebServer/webserver.py")

    def test_main_py_is_uploaded_unchanged(self):
        with patch.object(deploy_esp32, "compile_to_mpy") as compile_to_mpy, \
             patch.object(deploy_esp32, "write_file") as write_file, \
             patch.object(deploy_esp32, "remove_file") as remove_file:
            deploy_esp32.upload("ser", "main.py", "mpy_cross_v5", "/tmp")

        compile_to_mpy.assert_not_called()
        write_file.assert_called_once_with("ser", "main.py")
        remove_file.assert_not_called()

    def test_no_mpy_uploads_plain_py(self):
        with patch.object(deploy_esp32, "write_file") as write_file:
            deploy_esp32.upload("ser", "WebServer/webserver.py", None, "/tmp")

        write_file.assert_called_once_with("ser", "WebServer/webserver.py")


@unittest.skipUnless(importlib.util.find_spec("mpy_cross_v5"), "mpy-cross-v5 not installed")
class RealCompilerTests(unittest.TestCase):
    def test_compiles_a_project_module_to_mpy_v5(self):
        with tempfile.TemporaryDirectory() as out_dir:
            out = deploy_esp32.compile_to_mpy("mpy_cross_v5", "WlanNetwork/dnsserver.py", out_dir)
            with open(out, "rb") as f:
                header = f.read(2)

        self.assertEqual(header, b"M\x05")  # .mpy magic + format version 5


if __name__ == "__main__":
    unittest.main()
