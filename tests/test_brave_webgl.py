"""Exercise CLI startup with recording apps and simulated GPU availability."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


DESK = Path(__file__).resolve().parents[1] / "desk"


class BraveWebGLTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="desk-webgl-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = self.root / "brave-arguments.json"
        self.profile = self.root / "config/BraveSoftware/Brave-Browser"
        self.env = dict(os.environ)
        self.env.update(
            GOINFRE=str(self.root / "storage"),
            XDG_CONFIG_HOME=str(self.root / "config"),
            XDG_DATA_HOME=str(self.root / "data"),
            DESK_TEST_RECORD_DIR=str(self.root),
            DESK_TEST_SCRIPT=str(DESK),
            DESK_TEST_BIN=str(self.root / "bin"),
            DESK_TEST_HAS_GPU="0",
        )
        for app in ("brave/brave", "vscode/bin/code"):
            binary = self.root / "storage/apps" / app
            binary.parent.mkdir(parents=True)
            binary.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "record = Path(os.environ['DESK_TEST_RECORD_DIR']) / "
                "(Path(sys.argv[0]).name + '-arguments.json')\n"
                "record.write_text(json.dumps(sys.argv[1:]))\n"
            )
            binary.chmod(0o755)
        # Avoid importing any real Flatpak/Snap profiles found in the user's
        # home. GPU availability and network maintenance are controlled below;
        # all main/launch/argument handling still comes from the actual script.
        for profile in ("BraveSoftware/Brave-Browser", "Code"):
            imported = self.root / "config" / profile / ".desk-import"
            imported.parent.mkdir(parents=True)
            imported.touch()
        self.runner = self.root / "bin/desk"
        self.runner.parent.mkdir()
        self.runner.write_text(
            '#!/usr/bin/env bash\n'
            'source "$DESK_TEST_SCRIPT"\n'
            'BIN_DIR="$DESK_TEST_BIN"\n'
            'has_gpu_render_device() { [ "$DESK_TEST_HAS_GPU" = 1 ]; }\n'
            'prepare_all() { return 0; }\n'
            'free_ram() { :; }\n'
            'main "$@"\n'
        )
        self.runner.chmod(0o755)

    def launch(self, *args, command="b"):
        self.record.unlink(missing_ok=True)
        result = subprocess.run(
            [str(self.runner), command, *args],
            env=self.env, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 5
        while not self.record.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        return json.loads(self.record.read_text())

    def test_missing_render_device_enables_workaround_automatically(self):
        url = "https://example.org/path with spaces"
        args = self.launch(url)
        self.assertIn("--ignore-gpu-blocklist", args)
        self.assertFalse(any(a.startswith("--user-data-dir") for a in args))
        self.assertNotIn("--no-sandbox", args)
        self.assertEqual(args[-1], url)
        self.assertFalse((self.root / "config/desk/brave-webgl").exists())

    def test_available_render_device_keeps_default_graphics_flags(self):
        self.env["DESK_TEST_HAS_GPU"] = "1"
        args = self.launch("brave://gpu")
        self.assertNotIn("--ignore-gpu-blocklist", args)
        self.assertFalse(any(a.startswith("--user-data-dir") for a in args))
        self.assertEqual(args[-1], "brave://gpu")

    def test_launches_preserve_existing_profile_files(self):
        files = {
            "Local State": '{"hardware_acceleration_mode":{"enabled":true}}',
            "Default/History": "existing history",
            "Default/Network/Cookies": "existing account cookies",
            "Default/Preferences": '{"extensions":{"settings":{}}}',
        }
        for name, content in files.items():
            path = self.profile / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        first = self.launch("brave://gpu")
        second = self.launch("brave://gpu")
        self.assertEqual(first, second)
        for name, content in files.items():
            self.assertEqual((self.profile / name).read_text(), content)

    def test_explicit_profile_arguments_still_work(self):
        for args in (("--user-data-dir=/tmp/other",),
                     ("--user-data-dir", "/tmp/other")):
            with self.subTest(args=args):
                forwarded = self.launch(*args)
                self.assertEqual(forwarded[-len(args):], list(args))
                self.assertIn("--ignore-gpu-blocklist", forwarded)

    def test_arguments_after_separator_are_forwarded_literally(self):
        args = self.launch("--", "--user-data-dir=literal")
        self.assertEqual(args[-2:], ["--", "--user-data-dir=literal"])

    def test_explicit_open_preserves_both_apps_usual_profiles(self):
        args = self.launch("code", "brave", command="open")
        code_record = self.root / "code-arguments.json"
        deadline = time.monotonic() + 5
        while not code_record.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertIn("--extensions-dir", json.loads(code_record.read_text()))
        self.assertIn("--ignore-gpu-blocklist", args)
        self.assertFalse(any(a.startswith("--user-data-dir") for a in args))

    def test_render_device_detection_requires_usable_character_device(self):
        devices = self.root / "devices"
        devices.mkdir()

        def detect():
            return subprocess.run(
                ["bash", "-c", 'source "$1"; has_gpu_render_device "$2"',
                 "test", str(DESK), str(devices)],
                capture_output=True, timeout=5,
            ).returncode

        self.assertEqual(detect(), 1)
        node = devices / "renderD128"
        node.touch()
        self.assertEqual(detect(), 1)
        node.unlink()
        # /dev/null supplies a harmless readable/writable character-device
        # fixture; this tests file-type detection, not real GPU rendering.
        node.symlink_to("/dev/null")
        self.assertEqual(detect(), 0)


if __name__ == "__main__":
    unittest.main()
