"""Exercise selection, verified native installation, and terminal launch offline."""

import base64
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import pty
import select
import signal
import shutil
import struct
import subprocess
import tarfile
import termios
import tempfile
import time
import unittest


DESK = Path(__file__).resolve().parents[1] / "desk"


class ProgramTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="desk-programs-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.storage = self.root / "storage with spaces"
        self.state = self.home / ".config/desk"
        self.env = dict(os.environ)
        self.env.update(
            HOME=str(self.home),
            GOINFRE=str(self.storage),
            XDG_CONFIG_HOME=str(self.home / ".config"),
            XDG_DATA_HOME=str(self.home / ".local/share"),
            SHELL="/bin/bash",
            DESK_SCRIPT=str(DESK),
            DESK_FIXTURE=str(self.root),
            PYTHONDONTWRITEBYTECODE="1",
        )
        # Never use the host's credentials or Codex state in these tests.
        self.env.pop("CODEX_HOME", None)
        self.env.pop("CLAUDE_CONFIG_DIR", None)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = f"{self.bin}:{self.env['PATH']}"
        self.write_executable(self.bin / "uname", "#!/bin/sh\ncase \"$1\" in -s) echo Linux;; -m) echo x86_64;; esac\n")
        self.write_executable(self.bin / "curl", '''#!/usr/bin/env python3
import os, pathlib, sys
root = pathlib.Path(os.environ['DESK_FIXTURE'])
args = sys.argv[1:]
url = next(a for a in args if a.startswith('https://'))
with (root / 'requests').open('a') as f:
    f.write(url + '\\n')
if (root / 'offline').exists():
    sys.exit(22)
if '@anthropic-ai' in url:
    if url.endswith('/latest'):
        source = root / 'claude-latest.json'
    elif url.endswith('/2.3.4'):
        source = root / 'claude-platform.json'
    elif url.endswith('/claude-test.tgz'):
        source = root / 'claude-artifact.tgz'
    else:
        sys.exit('Unexpected Claude download: ' + url)
elif url.endswith('/latest'):
    source = root / 'latest.json'
elif url.endswith('/1.2.3-linux-x64'):
    source = root / 'platform.json'
elif url.endswith('/codex-test.tgz'):
    source = root / 'artifact.tgz'
else:
    sys.exit('Unexpected download: ' + url)
data = source.read_bytes()
if '-o' in args:
    pathlib.Path(args[args.index('-o') + 1]).write_bytes(data)
else:
    sys.stdout.buffer.write(data)
''')
        self.codex = self.storage / "apps/codex/bin/codex"
        binary = b'''#!/usr/bin/env python3
import json, os, pathlib, sys
if sys.argv[1:] == ['--version']:
    print('claude 2.3.4' if pathlib.Path(sys.argv[0]).name == 'claude' else 'codex-cli 1.2.3')
    sys.exit(0)
root = pathlib.Path(os.environ['DESK_FIXTURE'])
(root / 'launch.json').write_text(json.dumps({
    'args': sys.argv[1:],
    'cache': os.environ.get('XDG_CACHE_HOME'),
    'tmp': os.environ.get('TMPDIR'),
    'home': os.environ.get('CODEX_HOME'),
    'claude_config': os.environ.get('CLAUDE_CONFIG_DIR'),
    'claude_tmp': os.environ.get('CLAUDE_CODE_TMPDIR'),
    'updates_disabled': os.environ.get('DISABLE_AUTOUPDATER'),
    'stdin': sys.stdin.read(),
    'path': os.environ['PATH'],
}))
sys.exit(int(os.environ.get('DESK_TEST_EXIT', '0')))
'''
        with tarfile.open(self.root / "artifact.tgz", "w:gz") as archive:
            info = tarfile.TarInfo("package/vendor/x86_64-unknown-linux-musl/bin/codex")
            info.size, info.mode = len(binary), 0o755
            archive.addfile(info, io.BytesIO(binary))
        self.integrity = "sha512-" + base64.b64encode(
            hashlib.sha512((self.root / "artifact.tgz").read_bytes()).digest()
        ).decode()
        (self.root / "latest.json").write_text(json.dumps({
            "version": "1.2.3",
            "optionalDependencies": {
                "@openai/codex-linux-x64": "npm:@openai/codex@1.2.3-linux-x64"
            },
        }))
        self.platform = {
            "version": "1.2.3-linux-x64",
            "dist": {
                "tarball": "https://registry.npmjs.org/@openai/codex/-/codex-test.tgz",
                "integrity": self.integrity,
            },
        }
        self.write_platform()
        self.claude = self.storage / "apps/claude/claude"
        with tarfile.open(self.root / "claude-artifact.tgz", "w:gz") as archive:
            info = tarfile.TarInfo("package/claude")
            info.size, info.mode = len(binary), 0o755
            archive.addfile(info, io.BytesIO(binary))
        integrity = "sha512-" + base64.b64encode(
            hashlib.sha512((self.root / "claude-artifact.tgz").read_bytes()).digest()
        ).decode()
        (self.root / "claude-latest.json").write_text(json.dumps({
            "version": "2.3.4",
            "optionalDependencies": {
                "@anthropic-ai/claude-code-linux-x64": "2.3.4",
            },
        }))
        self.claude_platform = {
            "version": "2.3.4",
            "dist": {
                "tarball": "https://registry.npmjs.org/@anthropic-ai/claude-code-linux-x64/-/claude-test.tgz",
                "integrity": integrity,
            },
        }
        (self.root / "claude-platform.json").write_text(json.dumps(self.claude_platform))

    @staticmethod
    def write_executable(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)

    def write_platform(self):
        (self.root / "platform.json").write_text(json.dumps(self.platform))

    def run_desk(self, *args, input="", check=True):
        result = subprocess.run(
            [str(DESK), *args], env=self.env, input=input,
            capture_output=True, text=True, timeout=15,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def source(self, script, check=True):
        result = subprocess.run(
            ["bash", "-c", 'source "$DESK_SCRIPT"; ' + script],
            env=self.env, capture_output=True, text=True, timeout=15,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def save_selection(self, text):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "programs").write_text(text)

    def test_codex_only_install_and_repeat_keeps_other_programs_uninstalled(self):
        result = self.run_desk("install", "codex")
        self.assertTrue(self.codex.is_file())
        self.assertFalse((self.storage / "apps/vscode").exists())
        self.assertFalse((self.storage / "apps/brave").exists())
        self.assertEqual((self.state / "programs").read_text(), "codex\n")
        self.assertTrue((self.home / ".local/bin/codex").is_file())
        self.assertFalse((self.home / ".local/bin/code").exists())
        self.assertFalse((self.home / ".local/share/applications/code-native.desktop").exists())
        self.assertIn("sign in on first use", result.stdout)
        hook = (self.home / ".bashrc").read_text()
        self.assertIn("unalias codex", hook)
        self.assertNotIn("unalias code ", hook)
        self.run_desk("p")
        requests = (self.root / "requests").read_text()
        self.assertEqual(requests.count("codex-test.tgz"), 1)
        self.assertEqual((self.home / ".bashrc").read_text().count("# >>> desk >>>"), 1)

    def test_launch_preserves_arguments_input_exit_status_and_codex_home(self):
        self.run_desk("install", "codex")
        custom_home = str(self.home / "private codex")
        self.env.update(CODEX_HOME=custom_home, DESK_TEST_EXIT="17")
        wrapper = self.home / ".local/bin/codex"
        result = subprocess.run(
            [str(wrapper), "exec", "a prompt with spaces", "--", "literal"],
            env=self.env, input="piped input\n", capture_output=True, text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 17, result.stderr)
        launch = json.loads((self.root / "launch.json").read_text())
        cache = self.storage / "cache/codex"
        self.assertEqual(launch["args"], [
            "-c", "log_dir=" + json.dumps(str(cache / "log")),
            "exec", "a prompt with spaces", "--", "literal",
        ])
        self.assertEqual(launch["cache"], str(cache / "xdg"))
        self.assertEqual(launch["tmp"], str(cache / "tmp"))
        self.assertEqual(launch["home"], custom_home)
        self.assertEqual(launch["stdin"], "piped input\n")
        self.assertEqual((cache.stat().st_mode & 0o777), 0o700)
        self.assertEqual((Path(custom_home) / "tmp").resolve(), cache / "tmp")
        self.assertEqual((self.home / ".cache/codex-runtimes").resolve(), self.storage / "cache/codex-runtimes")
        self.assertFalse((self.state / "locks/codex.lock").exists())

    def test_corrupt_download_is_rejected_and_existing_install_is_preserved(self):
        self.codex.parent.mkdir(parents=True)
        self.write_executable(self.codex, "#!/bin/sh\necho old codex\n")
        (self.codex.parent.parent / ".installed-version").write_text("0.9.0\n")
        before = self.codex.read_bytes()
        self.platform["dist"]["integrity"] = "sha512-" + base64.b64encode(bytes(64)).decode()
        self.write_platform()
        result = self.run_desk("install", "codex", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertEqual(self.codex.read_bytes(), before)
        self.assertFalse((self.state / "initialized").exists())
        self.assertFalse(list(self.storage.glob(".desk-codex.*")))

    def test_offline_existing_codex_remains_usable_but_fresh_install_fails(self):
        (self.root / "offline").touch()
        self.assertNotEqual(self.run_desk("install", "codex", check=False).returncode, 0)
        self.write_executable(self.codex, "#!/bin/sh\necho existing codex\n")
        result = self.run_desk("p")
        self.assertIn("keeping the installed version", result.stderr)

    def test_selection_validation_cannot_execute_shell_and_preserves_saved_choice(self):
        self.save_selection("codex\n")
        bad_choices = ["unknown", "none,codex", "$(touch hacked)", "; touch hacked"]
        for choice in bad_choices:
            with self.subTest(choice=choice):
                result = self.run_desk("install", choice, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertEqual((self.state / "programs").read_text(), "codex\n")
        self.assertFalse((self.root / "requests").exists())

    def test_none_installs_nothing_and_status_distinguishes_selection(self):
        self.run_desk("install", "none")
        self.assertEqual((self.state / "programs").read_text(), "none\n")
        self.assertFalse((self.root / "requests").exists())
        result = self.run_desk("st")
        self.assertIn("Selected  none", result.stdout)
        self.assertIn("Codex CLI", result.stdout)
        self.assertIn("not installed", result.stdout)

    def test_background_updates_only_the_saved_selection(self):
        self.save_selection("code\ncodex\n")
        self.source('''
prepare_core() { :; }
prepare_vscode_unlocked() { echo code >> "$DESK_FIXTURE/prepared"; }
prepare_brave_unlocked() { echo brave >> "$DESK_FIXTURE/prepared"; }
prepare_codex_unlocked() { echo codex >> "$DESK_FIXTURE/prepared"; }
main _auto
''')
        self.assertEqual((self.root / "prepared").read_text(), "code\ncodex\n")

    def test_aliases_are_normalized_and_only_selected_installers_execute(self):
        self.source('''
prepare_vscode_unlocked() { echo code >> "$DESK_FIXTURE/prepared"; }
prepare_brave_unlocked() { echo brave >> "$DESK_FIXTURE/prepared"; }
prepare_codex_unlocked() { echo codex >> "$DESK_FIXTURE/prepared"; }
main install ai,c code
''')
        self.assertEqual((self.state / "programs").read_text(), "code\ncodex\n")
        self.assertEqual((self.root / "prepared").read_text(), "code\ncodex\n")

    def test_upgraded_noninteractive_installation_keeps_original_defaults(self):
        self.state.mkdir(parents=True)
        (self.state / "initialized").touch()
        self.source('''
prepare_vscode_unlocked() { echo code >> "$DESK_FIXTURE/prepared"; }
prepare_brave_unlocked() { echo brave >> "$DESK_FIXTURE/prepared"; }
prepare_codex_unlocked() { echo codex >> "$DESK_FIXTURE/prepared"; }
main p
''')
        self.assertEqual((self.state / "programs").read_text(), "code\nbrave\n")
        self.assertEqual((self.root / "prepared").read_text(), "code\nbrave\n")

    def test_explicit_open_starts_only_requested_programs(self):
        self.save_selection("code\n")
        self.write_executable(self.storage / "apps/brave/brave", "#!/bin/sh\nexit 0\n")
        self.write_executable(self.codex, "#!/bin/sh\nexit 0\n")
        self.source('''
open_app() { printf '%s\\n' "$1" >> "$DESK_FIXTURE/opened"; }
main open brave codex
''')
        self.assertEqual((self.root / "opened").read_text(), "brave\ncodex\n")
        self.assertEqual((self.state / "programs").read_text(), "code\n")
        self.assertEqual((self.state / "open-programs").read_text(), "brave\ncodex\n")
        self.assertFalse((self.root / "requests").exists())

    def test_noninteractive_chooser_requires_explicit_programs(self):
        result = self.run_desk("install", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.state / "programs").exists())

    def test_bootstrap_fix_defers_wrappers_until_user_chooses(self):
        self.run_desk("fix")
        self.assertIn("command desk _shell", (self.home / ".bashrc").read_text())
        for program in ("code", "brave", "codex"):
            self.assertFalse((self.home / ".local/bin" / program).exists())
        self.run_desk("install", "codex")
        self.assertTrue((self.home / ".local/bin/codex").exists())
        self.assertFalse((self.home / ".local/bin/code").exists())

    def test_existing_codex_scratch_directory_is_preserved(self):
        self.run_desk("install", "codex")
        scratch = self.home / ".codex/tmp"
        scratch.mkdir(parents=True)
        (scratch / "existing-file").write_text("keep me")
        self.run_desk("codex")
        self.assertFalse(scratch.is_symlink())
        self.assertEqual((scratch / "existing-file").read_text(), "keep me")

    def test_clean_removes_codex_files_but_keeps_authentication_and_selection(self):
        self.run_desk("install", "codex")
        private = self.home / ".codex"
        private.mkdir()
        (private / "auth.json").write_text("existing credential fixture")
        cache = self.storage / "cache/codex"
        cache.mkdir(parents=True)
        (cache / "cache-file").touch()
        self.source("setup_runtime; clean_reset_unlocked")
        self.assertFalse(self.codex.exists())
        self.assertFalse(cache.exists())
        self.assertEqual((private / "auth.json").read_text(), "existing credential fixture")
        self.assertEqual((self.state / "programs").read_text(), "codex\n")

    def interact(self, command, answers, prompt=b"Space: toggle"):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
        before = termios.tcgetattr(slave)
        args = [] if command is None else ([command] if isinstance(command, str) else list(command))
        process = subprocess.Popen(
            [str(DESK), *args], stdin=slave, stdout=slave, stderr=slave,
            env=self.env, start_new_session=True,
            preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
        )
        os.close(slave)
        output = b""
        keys = b"".join(answers)
        sent = False
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    output += chunk
                    if not sent and prompt in output:
                        sent = True
                        os.write(master, keys)
            code = process.wait(timeout=2)
            self.assertEqual(termios.tcgetattr(master), before, "Terminal settings were not restored")
            return code, output
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            os.close(master)

    def test_checklist_uses_arrows_and_space(self):
        code, output = self.interact("install", [b"n\x1b[B\x1b[B \r"])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b"[x] Codex CLI", output)
        self.assertEqual((self.state / "programs").read_text(), "codex\n")

    def test_checklist_can_select_both_ai_tools(self):
        code, output = self.interact("install", [b"njjj \x1b[A \r"])
        self.assertEqual(code, 0, output.decode())
        self.assertEqual((self.state / "programs").read_text(), "codex\nclaude\n")
        self.assertTrue(self.codex.exists())
        self.assertTrue(self.claude.exists())
        self.assertFalse((self.storage / "apps/brave").exists())

    def test_checklist_preserves_saved_choices_when_enter_is_pressed(self):
        self.save_selection("claude\n")
        code, output = self.interact("install", [b"\r"])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b"[x] Claude Code", output)
        self.assertEqual((self.state / "programs").read_text(), "claude\n")

    def test_checklist_select_none_does_not_download_programs(self):
        code, output = self.interact("install", [b"n\r"])
        self.assertEqual(code, 0, output.decode())
        self.assertEqual((self.state / "programs").read_text(), "none\n")
        self.assertFalse((self.root / "requests").exists())

    def test_checklist_all_checks_every_program_before_cancel(self):
        code, output = self.interact("install", [b"aq"])
        self.assertEqual(code, 130, output.decode())
        for title in ("VS Code", "Brave", "Codex CLI", "Claude Code", "Android 11 Google Play"):
            self.assertIn(f"[x] {title}".encode(), output)
        self.assertFalse((self.state / "programs").exists())
        self.assertFalse((self.root / "requests").exists())

    def test_escape_and_ctrl_c_cancel_without_changing_selection(self):
        self.save_selection("claude\n")
        for key in (b"\x1b", b"\x03"):
            with self.subTest(key=key):
                code, output = self.interact("install", [key])
                # Bash may itself receive the terminal's SIGINT; both forms
                # report status 130 to the invoking interactive shell.
                self.assertIn(code, (130, -signal.SIGINT), output.decode())
                self.assertEqual((self.state / "programs").read_text(), "claude\n")
        self.assertFalse((self.root / "requests").exists())

    def test_first_shell_offers_selection_and_prepares_only_codex(self):
        code, output = self.interact("_shell", [b"njj \r"])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b"Choose your programs", output)
        self.assertIn(b"Workstation ready", output)
        self.assertEqual((self.state / "programs").read_text(), "codex\n")
        self.assertTrue((self.state / "initialized").exists())
        self.assertTrue(self.codex.exists())
        self.assertFalse((self.storage / "apps/brave").exists())
        self.assertFalse((self.state / "locks/first-run.lock").exists())

    def test_cancel_keeps_choice_and_does_not_download(self):
        self.save_selection("brave\n")
        code, output = self.interact("install", [b"q"])
        self.assertEqual(code, 130, output.decode())
        self.assertEqual((self.state / "programs").read_text(), "brave\n")
        self.assertFalse((self.root / "requests").exists())

    def test_clean_refuses_busy_codex_lock_and_releases_other_locks(self):
        self.save_selection("codex\n")
        lock = self.state / "locks/codex.lock"
        lock.mkdir(parents=True)
        (lock / "pid").write_text(str(os.getpid()))
        code, output = self.interact("clean", [b"y\n"], b"Continue? [y/N] ")
        self.assertEqual(code, 1, output.decode())
        self.assertIn(b"Another desk setup/update is still running", output)
        self.assertTrue(lock.exists())
        for name in ("first-run", "core", "code", "brave"):
            self.assertFalse((self.state / "locks" / (name + ".lock")).exists())

    def test_running_codex_postpones_update_without_downloading(self):
        self.write_executable(self.codex, "#!/bin/sh\nsleep 30\n")
        marker = self.codex.parent.parent / ".installed-version"
        marker.write_text("0.9.0\n")
        process = subprocess.Popen([str(self.codex)], start_new_session=True)
        try:
            result = self.run_desk("install", "codex")
            self.assertIn("exit Codex CLI", result.stderr)
            self.assertEqual(marker.read_text(), "0.9.0\n")
            self.assertNotIn("codex-test.tgz", (self.root / "requests").read_text())
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)

    def test_claude_install_and_repeat_use_only_verified_native_artifact(self):
        self.run_desk("install", "claude")
        self.assertTrue(self.claude.is_file())
        self.assertFalse(self.codex.exists())
        self.assertEqual((self.state / "programs").read_text(), "claude\n")
        self.assertTrue((self.home / ".local/bin/claude").exists())
        self.assertIn("unalias claude", (self.home / ".bashrc").read_text())
        self.run_desk("p")
        self.assertEqual((self.root / "requests").read_text().count("claude-test.tgz"), 1)
        status = self.run_desk("st")
        self.assertIn("Claude Code", status.stdout)
        self.assertIn("2.3.4", status.stdout)

    def test_claude_launch_preserves_arguments_input_exit_status_and_config(self):
        self.run_desk("install", "claude")
        config = str(self.home / "existing claude config")
        self.env.update(CLAUDE_CONFIG_DIR=config, DESK_TEST_EXIT="19")
        result = self.run_desk("claude", "--print", "prompt with spaces", input="hello\n", check=False)
        self.assertEqual(result.returncode, 19, result.stderr)
        launch = json.loads((self.root / "launch.json").read_text())
        cache = self.storage / "cache/claude"
        self.assertEqual(launch["args"], ["--print", "prompt with spaces"])
        self.assertEqual(launch["stdin"], "hello\n")
        self.assertEqual(launch["claude_config"], config)
        self.assertEqual(launch["cache"], str(cache / "xdg"))
        self.assertEqual(launch["tmp"], str(cache / "tmp"))
        self.assertEqual(launch["claude_tmp"], str(cache / "tmp"))
        self.assertEqual(launch["updates_disabled"], "1")
        self.assertEqual(cache.stat().st_mode & 0o777, 0o700)
        self.assertFalse((self.state / "locks/claude.lock").exists())

    def test_corrupt_claude_artifact_keeps_the_existing_installation(self):
        self.write_executable(self.claude, "#!/bin/sh\necho old claude\n")
        before = self.claude.read_bytes()
        self.claude_platform["dist"]["integrity"] = "sha512-" + base64.b64encode(bytes(64)).decode()
        (self.root / "claude-platform.json").write_text(json.dumps(self.claude_platform))
        result = self.run_desk("install", "claude", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertEqual(self.claude.read_bytes(), before)
        self.assertFalse((self.state / "initialized").exists())

    def test_claude_selection_drives_background_update_and_all_includes_claude(self):
        self.save_selection("claude\n")
        self.source('''
prepare_core() { :; }
prepare_claude_unlocked() { echo claude >> "$DESK_FIXTURE/prepared"; }
main _auto
normalize_programs all
printf '%s\\n' "${PROGRAMS[@]}" > "$DESK_FIXTURE/all-programs"
''')
        self.assertEqual((self.root / "prepared").read_text(), "claude\n")
        self.assertEqual((self.root / "all-programs").read_text(), "code\nbrave\ncodex\nclaude\nandroid\nflutter\nhermes\ncodex-desktop\nclaude-desktop\nhermes-desktop\nopenmausbot\nchatgpt\ncua\n")

    def test_clean_preserves_claude_account_data_and_cleans_its_cache(self):
        self.run_desk("install", "claude")
        config = self.home / ".claude"
        config.mkdir()
        (config / "settings.json").write_text("existing config fixture")
        cache = self.storage / "cache/claude"
        cache.mkdir(parents=True)
        (cache / "cache-file").touch()
        self.source("setup_runtime; clean_reset_unlocked")
        self.assertFalse(self.claude.exists())
        self.assertFalse(cache.exists())
        self.assertFalse((self.home / ".local/bin/claude").exists())
        self.assertEqual((config / "settings.json").read_text(), "existing config fixture")
        self.assertEqual((self.state / "programs").read_text(), "claude\n")

    def test_busy_claude_lock_blocks_reset_without_leaking_other_locks(self):
        self.save_selection("claude\n")
        lock = self.state / "locks/claude.lock"
        lock.mkdir(parents=True)
        (lock / "pid").write_text(str(os.getpid()))
        code, output = self.interact("clean", [b"y\n"], b"Continue? [y/N] ")
        self.assertEqual(code, 1, output.decode())
        self.assertTrue(lock.exists())
        for name in ("first-run", "core", "code", "brave", "codex"):
            self.assertFalse((self.state / "locks" / (name + ".lock")).exists())

    def test_renamed_native_claude_process_postpones_update_and_blocks_reset(self):
        self.claude.parent.mkdir(parents=True)
        shutil.copy2(shutil.which("sleep"), self.claude)
        process = subprocess.Popen(["friendly-process-title", "30"], executable=str(self.claude))
        try:
            result = self.run_desk("install", "claude")
            self.assertIn("exit Claude Code", result.stderr)
            self.assertNotIn("claude-test.tgz", (self.root / "requests").read_text())
            code, output = self.interact("clean", [b"y\n"], b"Continue? [y/N] ")
            self.assertEqual(code, 1, output.decode())
            self.assertIn(b"Claude Code is running", output)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def install_recording_desktop(self, program):
        relative = {"code": "vscode/bin/code", "brave": "brave/brave"}[program]
        self.write_executable(self.storage / "apps" / relative, f'''#!/usr/bin/env python3
import os
from pathlib import Path
with (Path(os.environ['DESK_FIXTURE']) / 'opened').open('a') as record:
    record.write({program!r} + '\\n')
''')

    def install_old_native(self, program, version="0.9.0"):
        binary = self.codex if program == "codex" else self.claude
        self.write_executable(binary, "#!/bin/sh\necho existing native fixture\n")
        root = binary.parent.parent if program == "codex" else binary.parent
        (root / ".installed-version").write_text(version + "\n")
        return root / ".installed-version"

    def test_plain_desk_on_fresh_machine_does_not_install_or_launch_anything(self):
        result = self.run_desk()
        self.assertIn("No managed programs installed", result.stdout)
        self.assertFalse((self.root / "requests").exists())
        self.assertFalse((self.state / "programs").exists())

    def test_plain_desk_shows_only_installed_programs_and_opens_checked_item(self):
        self.install_recording_desktop("brave")
        self.save_selection("claude\n")
        code, output = self.interact(None, [b" \r"])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b"Choose programs to open", output)
        self.assertIn(b"[x] Brave", output)
        self.assertNotIn(b"[ ] VS Code", output)
        self.assertNotIn(b"[ ] Claude Code", output)
        self.assertEqual((self.root / "opened").read_text(), "brave\n")
        self.assertEqual((self.state / "programs").read_text(), "claude\n")
        self.assertEqual((self.state / "open-programs").read_text(), "brave\n")
        self.assertFalse((self.root / "requests").exists())

    def test_open_choices_are_remembered_independently_of_install_choices(self):
        self.install_recording_desktop("brave")
        self.install_recording_desktop("code")
        self.save_selection("claude\n")
        (self.state / "open-programs").write_text("code\n")
        code, output = self.interact("open", [b"\r"])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b"[x] VS Code", output)
        self.assertIn(b"[ ] Brave", output)
        self.assertEqual((self.root / "opened").read_text(), "code\n")
        self.assertEqual((self.state / "programs").read_text(), "claude\n")

    def test_cancelling_launch_picker_opens_nothing_and_keeps_preferences(self):
        self.install_recording_desktop("brave")
        self.save_selection("none\n")
        (self.state / "open-programs").write_text("brave\n")
        code, output = self.interact(None, [b"q"])
        self.assertEqual(code, 130, output.decode())
        self.assertFalse((self.root / "opened").exists())
        self.assertEqual((self.state / "open-programs").read_text(), "brave\n")
        self.assertEqual((self.state / "programs").read_text(), "none\n")

    def test_open_validates_the_whole_request_before_starting_anything(self):
        self.install_recording_desktop("brave")
        result = self.run_desk("open", "brave", "code", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("not installed", result.stderr)
        self.assertFalse((self.root / "opened").exists())
        self.assertFalse((self.state / "open-programs").exists())
        self.assertFalse((self.root / "requests").exists())

    def test_open_does_not_check_for_updates_and_returns_single_ai_exit_status(self):
        self.run_desk("install", "codex")
        (self.codex.parent.parent / ".installed-version").write_text("0.9.0\n")
        before = (self.root / "requests").read_text()
        self.env["DESK_TEST_EXIT"] = "23"
        result = self.run_desk("open", "codex", input="hello\n", check=False)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual((self.root / "requests").read_text(), before)
        self.assertEqual(json.loads((self.root / "launch.json").read_text())["stdin"], "hello\n")

    def test_opening_both_ai_tools_without_a_graphical_terminal_fails_before_launch(self):
        self.run_desk("install", "codex", "claude")
        self.env.pop("DISPLAY", None)
        self.env.pop("WAYLAND_DISPLAY", None)
        result = self.run_desk("open", "all", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Opening multiple terminal tools needs", result.stderr)
        self.assertFalse((self.root / "launch.json").exists())
        self.assertFalse((self.state / "open-programs").exists())

    def test_two_ai_tools_are_launched_in_separate_terminal_windows(self):
        self.run_desk("install", "codex", "claude")
        terminal = self.root / "terminal with spaces/gnome-terminal"
        self.write_executable(terminal, '''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
root = Path(os.environ['DESK_FIXTURE'])
(root / ('terminal-' + sys.argv[-1] + '.json')).write_text(json.dumps(sys.argv[1:]))
''')
        self.env.update(TERMINAL=str(terminal), DISPLAY=":99")
        self.run_desk("open", "codex", "claude")
        for program in ("codex", "claude"):
            record = self.root / ("terminal-" + program + ".json")
            deadline = time.monotonic() + 3
            while not record.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(json.loads(record.read_text()), [
                "--", str(self.home / ".local/bin/desk"), "_open", program,
            ])
        self.assertFalse((self.root / "launch.json").exists())

    def test_noninteractive_plain_desk_requires_explicit_launch_choices(self):
        self.install_recording_desktop("brave")
        result = self.run_desk(check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("desk open", result.stderr)
        self.assertFalse((self.root / "opened").exists())

    def test_install_does_not_launch_installed_programs(self):
        self.run_desk("install", "codex", "claude")
        self.assertFalse((self.root / "launch.json").exists())
        self.assertFalse((self.state / "open-programs").exists())

    def test_update_checks_all_installed_programs_outside_the_install_selection(self):
        codex_marker = self.install_old_native("codex")
        claude_marker = self.install_old_native("claude")
        self.save_selection("none\n")
        (self.state / "open-programs").write_text("claude\n")
        self.run_desk("update")
        self.assertEqual(codex_marker.read_text(), "1.2.3\n")
        self.assertEqual(claude_marker.read_text(), "2.3.4\n")
        self.assertEqual((self.state / "programs").read_text(), "none\n")
        self.assertEqual((self.state / "open-programs").read_text(), "claude\n")
        self.assertFalse((self.root / "launch.json").exists())
        self.assertFalse((self.storage / "apps/vscode").exists())

    def test_update_can_target_one_program_without_changing_others(self):
        codex_marker = self.install_old_native("codex")
        claude_marker = self.install_old_native("claude")
        self.run_desk("update", "claude")
        self.assertEqual(codex_marker.read_text(), "0.9.0\n")
        self.assertEqual(claude_marker.read_text(), "2.3.4\n")
        self.assertNotIn("@openai", (self.root / "requests").read_text())

    def test_update_rejects_uninstalled_programs_without_downloading(self):
        self.install_old_native("claude")
        result = self.run_desk("update", "claude", "codex", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("not installed", result.stderr)
        self.assertFalse((self.root / "requests").exists())
        self.assertFalse(self.codex.exists())

    def test_update_on_a_fresh_machine_installs_nothing(self):
        result = self.run_desk("update")
        self.assertIn("No installed programs selected", result.stdout)
        self.assertFalse((self.root / "requests").exists())
        self.assertFalse((self.state / "programs").exists())

    def test_update_does_not_redownload_current_or_downgrade_newer_versions(self):
        self.install_old_native("codex", "1.2.3")
        claude_marker = self.install_old_native("claude", "99.0.0")
        self.run_desk("update", "all")
        requests = (self.root / "requests").read_text().splitlines()
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(url.endswith("/latest") for url in requests))
        self.assertEqual(claude_marker.read_text(), "99.0.0\n")

    def test_failed_update_preserves_old_program_and_continues_other_updates(self):
        codex_marker = self.install_old_native("codex")
        claude_marker = self.install_old_native("claude")
        self.platform["dist"]["integrity"] = "sha512-" + base64.b64encode(bytes(64)).decode()
        self.write_platform()
        result = self.run_desk("update", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(codex_marker.read_text(), "0.9.0\n")
        self.assertEqual(claude_marker.read_text(), "2.3.4\n")
        self.assertFalse((self.root / "launch.json").exists())

    def test_update_checks_desktop_binaries_without_importing_profiles(self):
        self.install_recording_desktop("code")
        self.install_recording_desktop("brave")
        self.source('''
install_vscode() { echo code >> "$DESK_FIXTURE/updated"; }
install_brave() { echo brave >> "$DESK_FIXTURE/updated"; }
import_data() { echo unexpected-import >> "$DESK_FIXTURE/updated"; return 1; }
main update
''')
        self.assertEqual((self.root / "updated").read_text(), "code\nbrave\n")
        self.assertFalse((self.root / "opened").exists())
        self.assertFalse((self.state / "programs").exists())

    def test_internal_terminal_launch_does_not_install_a_removed_program(self):
        result = self.run_desk("_open", "claude", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not installed", result.stderr)
        self.assertFalse((self.root / "requests").exists())

    def test_launch_picker_forgets_uninstalled_choices_without_installing_them(self):
        self.install_recording_desktop("brave")
        self.state.mkdir(parents=True)
        (self.state / "open-programs").write_text("claude\n")
        code, output = self.interact(None, [b"\r"])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b"[ ] Brave", output)
        self.assertEqual((self.state / "open-programs").read_text(), "none\n")
        self.assertFalse((self.root / "opened").exists())
        self.assertFalse((self.root / "requests").exists())


if __name__ == "__main__":
    unittest.main()
