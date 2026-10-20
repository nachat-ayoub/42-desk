"""Exercise community desktop artifacts and official Hermes staged installs offline."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import unittest
from urllib.parse import quote

import test_programs as helpers


class AppFixtures(unittest.TestCase):
    write_executable = staticmethod(helpers.ProgramTests.write_executable)
    write_platform = helpers.ProgramTests.write_platform
    run_desk = helpers.ProgramTests.run_desk
    source = helpers.ProgramTests.source
    save_selection = helpers.ProgramTests.save_selection
    interact = helpers.ProgramTests.interact

    def setUp(self):
        helpers.ProgramTests.setUp(self)
        self.env.pop('HERMES_HOME', None)

    def read_record(self, name):
        path = self.root / name
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                return json.loads(path.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                # Detached fixture processes create the file before writing its
                # contents. Wait for the complete record, not just its inode.
                time.sleep(0.02)
        return json.loads(path.read_text())


class DesktopAppTests(AppFixtures):
    repos = {'codex-desktop': 'cuongducle/codex-linux',
             'claude-desktop': 'aaddrick/claude-desktop-debian',
             'openmausbot': 'milind-soni/OpenMausBot'}

    def setUp(self):
        super().setUp()
        self.urls = {}
        self.write_executable(self.bin / 'curl', '''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['DESK_FIXTURE'])
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith('https://'))
with (root / 'requests').open('a') as stream:
    stream.write(url + '\\n')
if (root / 'offline').exists():
    sys.exit(22)
source = json.loads((root / 'urls.json').read_text()).get(url)
if source is None:
    sys.exit('Unexpected URL: ' + url)
pathlib.Path(args[args.index('-o') + 1]).write_bytes(pathlib.Path(source).read_bytes())
''')
        self.make_release('codex-desktop', 'v26.820.60940')
        self.make_release('claude-desktop', 'v3.3.11+claude2.42304.0')
        self.make_release('openmausbot', 'v0.1.116')

    def make_release(self, app, tag, missing_digest=False, bad_host=False, fail_extract=False):
        repo = self.repos[app]
        name = {'codex-desktop': 'codex-desktop-linux-x86_64.AppImage',
                'claude-desktop': 'claude-desktop-unofficial-2.42304.0-3.3.11-amd64.AppImage',
                'openmausbot': 'OpenMausBot-' + tag.lstrip('v') + '-x86_64.AppImage'}[app]
        artifact = self.root / (app + '-' + tag + '.AppImage')
        launcher = '''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['DESK_FIXTURE'])
(root / 'APP-launch.json').write_text(json.dumps({
    'args': sys.argv[1:], 'env': {name: os.environ.get(name) for name in (
        'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'TMPDIR', 'MESA_SHADER_CACHE_DIR', 'APPDIR', 'CLAUDE_FORCE_SANDBOX',
        'PATH', 'OMB_DATA_DIR', 'LD_LIBRARY_PATH')}
}))
'''.replace('APP-launch.json', app + '-launch.json')
        script = '''#!/bin/sh
[ "$1" = --appimage-extract ] || exit 2
python3 - <<'PY'
from pathlib import Path
root = Path('squashfs-root')
root.mkdir()
target = root / 'AppRun'
target.write_text(LAUNCHER)
target.chmod(0o755)
if APP_NAME == 'claude-desktop':
    record = root / 'record.py'
    record.write_text(LAUNCHER)
    record.chmod(0o755)
    target.write_text("""#!/bin/sh\nflags=\nbuild_electron_args() { [ "$1" != appimage ] || flags=--no-sandbox; }\nbuild_electron_args 'appimage'\nexec "$(dirname "$0")/record.py" $flags "$@"\n""")
if APP_NAME == 'openmausbot':
    native = root / 'openmausbot'
    native.write_text(LAUNCHER)
    native.chmod(0o755)
    (root / 'resources').mkdir()
    (root / 'resources/app.asar').write_text('packaged app')
    target.write_text("""#!/bin/sh\nexec "$(dirname "$0")/openmausbot" --no-sandbox "$@"\n""")
PY
'''.replace('LAUNCHER', repr(launcher)).replace('APP_NAME', repr(app))
        if fail_extract:
            script = '#!/bin/sh\nexit 1\n'
        artifact.write_text(script)
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        prefix = '/' + ('other/project' if bad_host else repo) + '/releases/download/' + quote(tag, safe='')
        url = prefix + '/' + name
        page, listing = self.root / (app + '-latest.html'), self.root / (app + '-assets.html')
        page.write_text('<include-fragment src="/' + repo + '/releases/expanded_assets/' + quote(tag, safe='') + '"></include-fragment>')
        listing.write_text('<ul><li><a href="' + url + '">AppImage</a>' +
                           ('' if missing_digest else '<clipboard-copy value="sha256:' + digest + '"></clipboard-copy>') +
                           '</li><li><a href="' + url + '.zsync">zsync</a></li></ul>')
        if app == 'openmausbot':
            # Upstream also publishes an identical, unversioned alias. Choose
            # the exact version/architecture asset, not an ambiguous alias.
            listing.write_text(listing.read_text() + '<li><a href="' + prefix +
                               '/OpenMausBot.AppImage">Portable alias</a><clipboard-copy value="sha256:' +
                               digest + '"></clipboard-copy></li>')
        self.urls['https://github.com/' + repo + '/releases/latest'] = str(page)
        self.urls['https://github.com/' + repo + '/releases/expanded_assets/' + quote(tag, safe='')] = str(listing)
        self.urls['https://github.com' + url] = str(artifact)
        (self.root / 'urls.json').write_text(json.dumps(self.urls))
        return artifact

    def install(self, app='codex-desktop'):
        return self.run_desk('install', app)

    def test_install_appimage_apps_creates_wrappers_and_menu_entries_without_opening(self):
        self.run_desk('install', *self.repos)
        for app in self.repos:
            self.assertTrue((self.storage / 'apps' / app / 'current/AppRun').is_file())
            self.assertTrue((self.home / '.local/bin' / app).is_file())
            entry = (self.home / '.local/share/applications' / (app + '-desk.desktop')).read_text()
            self.assertIn('OpenMausBot' if app == 'openmausbot' else 'community', entry)
            if app == 'openmausbot':
                self.assertNotIn('Community', entry)
            self.assertFalse((self.root / (app + '-launch.json')).exists())
            self.assertFalse((self.storage / 'apps' / app / 'downloads/application.AppImage').exists())

    def test_install_checklist_can_choose_only_the_two_desktop_apps(self):
        code, output = self.interact('install', [b'n' + b'j' * 7 + b' j \r'])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b'Codex Desktop (community Linux port)', output)
        self.assertEqual((self.state / 'programs').read_text(), 'codex-desktop\nclaude-desktop\n')
        self.assertFalse((self.storage / 'apps/hermes').exists())

    def test_codex_desktop_migrates_profile_and_shared_data_and_reuses_links(self):
        self.write_executable(self.bin / 'ps', '#!/bin/sh\necho bash\n')
        profile = self.home / '.config/Codex'
        profile.mkdir(parents=True)
        (profile / 'history').write_text('desktop history')
        shared = self.home / '.codex'
        shared.mkdir()
        (shared / 'auth.json').write_text('fixture account')
        self.install('codex-desktop')
        root = self.storage / 'data/codex-desktop'
        self.assertTrue(profile.is_symlink())
        self.assertEqual((root / 'config/Codex/history').read_text(), 'desktop history')
        self.assertTrue(shared.is_symlink())
        self.assertEqual((root / 'codex-home/auth.json').read_text(), 'fixture account')
        self.run_desk('codex-desktop')
        record = self.read_record('codex-desktop-launch.json')
        self.assertEqual(record['env']['XDG_CACHE_HOME'], str(self.storage / 'cache/codex-desktop/xdg'))
        self.assertNotIn('--no-sandbox', record['args'])
        self.source('setup_runtime; clean_reset_unlocked')
        self.assertEqual((shared / 'auth.json').read_text(), 'fixture account')
        self.assertEqual((profile / 'history').read_text(), 'desktop history')

    def test_codex_data_migration_refuses_running_sessions_and_conflicts(self):
        self.write_executable(self.bin / 'ps', '#!/bin/sh\necho codex\n')
        profile = self.home / '.config/Codex'
        profile.mkdir(parents=True)
        (profile / 'history').write_text('preserve')
        result = self.source('setup_runtime; prepare_codex_desktop_storage', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Close Codex', result.stderr)
        self.assertFalse(profile.is_symlink())
        self.assertEqual((profile / 'history').read_text(), 'preserve')
        self.write_executable(self.bin / 'ps', '#!/bin/sh\necho bash\n')
        target = self.storage / 'data/codex-desktop/config/Codex'
        target.mkdir(parents=True)
        (target / 'history').write_text('other history')
        result = self.source('setup_runtime; prepare_codex_desktop_storage', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((profile / 'history').read_text(), 'preserve')
        self.assertEqual((target / 'history').read_text(), 'other history')

    def test_codex_data_migration_respects_custom_codex_home_and_symlinks(self):
        custom = self.root / 'custom codex data'
        custom.mkdir()
        (custom / 'auth.json').write_text('custom account')
        self.env['CODEX_HOME'] = str(custom)
        shared = self.home / '.codex'
        shared.symlink_to(custom, target_is_directory=True)
        self.install('codex-desktop')
        self.assertEqual(shared.resolve(), custom)
        self.assertFalse((self.storage / 'data/codex-desktop/codex-home').exists())
        self.assertEqual((custom / 'auth.json').read_text(), 'custom account')

    def test_launch_uses_goinfre_cache_and_preserves_normal_profile_and_arguments(self):
        self.install('claude-desktop')
        profile = self.home / '.config/Claude/history'
        profile.parent.mkdir(parents=True)
        profile.write_text('keep conversations')
        self.run_desk('claude-desktop', '--', 'argument with spaces')
        record = self.read_record('claude-desktop-launch.json')
        cache = self.storage / 'cache/claude-desktop'
        self.assertEqual(record['args'], ['--disable-setuid-sandbox', '--disk-cache-dir=' + str(cache / 'chromium'), '--', 'argument with spaces'])
        self.assertNotIn('--no-sandbox', record['args'])
        self.assertEqual(record['env']['XDG_CONFIG_HOME'], str(self.home / '.config'))
        self.assertEqual(record['env']['TMPDIR'], str(cache / 'tmp'))
        self.assertEqual(record['env']['APPDIR'], str(self.storage / 'apps/claude-desktop/current'))
        self.assertEqual(record['env']['CLAUDE_FORCE_SANDBOX'], '1')
        self.assertEqual(profile.read_text(), 'keep conversations')

    def test_open_launches_both_desktops_without_needing_a_terminal_emulator(self):
        self.run_desk('install', 'codex-desktop', 'claude-desktop')
        self.run_desk('open', 'codex-desktop', 'claude-desktop')
        for app in ('codex-desktop', 'claude-desktop'):
            self.read_record(app + '-launch.json')
        self.assertEqual((self.state / 'open-programs').read_text(), 'codex-desktop\nclaude-desktop\n')

    def test_repeat_and_background_maintenance_reuse_installed_apps_offline(self):
        self.install()
        requests = (self.root / 'requests').read_text()
        (self.root / 'offline').touch()
        self.run_desk('p')
        self.source('setup_runtime; shell_prepare_component codex-desktop')
        self.assertEqual((self.root / 'requests').read_text(), requests)

    def test_update_changes_release_and_keeps_program_choices(self):
        self.install()
        self.make_release('codex-desktop', 'v26.900.10000')
        self.run_desk('update', 'codex-desktop')
        self.assertEqual((self.storage / 'apps/codex-desktop/.installed-version').read_text(), 'v26.900.10000\n')
        self.assertEqual((self.state / 'programs').read_text(), 'codex-desktop\n')
        self.assertFalse((self.root / 'codex-desktop-launch.json').exists())

    def test_corrupt_download_and_failed_extraction_keep_previous_release(self):
        self.install()
        current = self.storage / 'apps/codex-desktop/current'
        before = current.resolve()
        artifact = self.make_release('codex-desktop', 'v26.900.10000')
        artifact.write_bytes(b'corrupt download')
        result = self.run_desk('update', 'codex-desktop', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertEqual(current.resolve(), before)
        self.make_release('codex-desktop', 'v26.900.10000', fail_extract=True)
        result = self.run_desk('update', 'codex-desktop', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(current.resolve(), before)

    def test_missing_digest_is_rejected_before_downloading_appimage(self):
        self.make_release('codex-desktop', 'v26.900.10000', missing_digest=True)
        result = self.run_desk('install', 'codex-desktop', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256 digest', result.stderr)
        self.assertNotIn('.AppImage', (self.root / 'requests').read_text())

    def test_asset_from_another_project_is_rejected(self):
        self.make_release('codex-desktop', 'v26.900.10000', bad_host=True)
        result = self.run_desk('install', 'codex-desktop', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unexpected AppImage download URL', result.stderr)

    def test_offline_update_keeps_app_and_does_not_downgrade(self):
        self.install()
        self.make_release('codex-desktop', 'v26.100.10000')
        self.run_desk('update', 'codex-desktop')
        (self.root / 'offline').touch()
        result = self.run_desk('update', 'codex-desktop')
        self.assertIn('keeping the installed desktop app', result.stderr)
        self.assertEqual((self.storage / 'apps/codex-desktop/.installed-version').read_text(), 'v26.820.60940\n')

    def test_clean_preserves_desktop_profiles(self):
        self.run_desk('install', *self.repos)
        profiles = [self.home / '.config/Codex/account', self.home / '.config/Claude/account',
                    self.home / '.openmausbot/config.json', self.home / '.config/openmausbot/credentials.bin']
        for path in profiles:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('keep user account')
        self.source('setup_runtime; clean_reset_unlocked')
        for app in self.repos:
            self.assertFalse((self.storage / 'apps' / app).exists())
            self.assertFalse((self.home / '.local/bin' / app).exists())
            self.assertFalse((self.home / '.local/share/applications' / (app + '-desk.desktop')).exists())
        for path in profiles:
            self.assertEqual(path.read_text(), 'keep user account')

    def test_running_desktop_postpones_updates_before_network_access(self):
        self.install()
        executable = self.storage / 'apps/codex-desktop/current/AppRun'
        executable.unlink()
        shutil.copy2(shutil.which('sleep'), executable)
        process = subprocess.Popen(['renamed-desktop', '30'], executable=str(executable))
        try:
            requests = (self.root / 'requests').read_text()
            result = self.run_desk('update', 'codex-desktop')
            self.assertIn('is running', result.stderr)
            self.assertEqual((self.root / 'requests').read_text(), requests)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_busy_desktop_lock_blocks_clean_and_releases_other_locks(self):
        self.save_selection('codex-desktop\n')
        lock = self.state / 'locks/claude-desktop.lock'
        lock.mkdir(parents=True)
        (lock / 'pid').write_text(str(os.getpid()))
        code, output = self.interact('clean', [b'y\n'], b'Continue? [y/N] ')
        self.assertEqual(code, 1, output.decode())
        self.assertTrue(lock.exists())
        for name in ('first-run', 'core', 'code', 'brave', 'codex', 'claude', 'flutter', 'hermes', 'codex-desktop'):
            self.assertFalse((self.state / 'locks' / (name + '.lock')).exists())

    def test_openmausbot_checklist_choice_installs_only_the_app(self):
        code, output = self.interact('install', [b'n' + b'j' * 10 + b' \r'])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b'OpenMausBot', output)
        self.assertEqual((self.state / 'programs').read_text(), 'openmausbot\n')
        self.assertTrue((self.storage / 'apps/openmausbot/current/AppRun').is_file())
        self.assertFalse((self.storage / 'apps/codex').exists())
        self.assertFalse((self.storage / 'apps/claude').exists())
        self.assertFalse((self.root / 'openmausbot-launch.json').exists())

    def test_openmausbot_open_uses_cache_and_exposes_agent_wrappers_preserving_data_override(self):
        self.install('openmausbot')
        custom = self.root / 'my bot data'
        custom.mkdir()
        (custom / 'config.json').write_text('saved bots')
        self.env['OMB_DATA_DIR'] = str(custom)
        profile = self.home / '.config/openmausbot'
        existing = profile / 'GPUCache'
        existing.mkdir(parents=True)
        (existing / 'existing-cache').write_text('keep existing directory')
        self.run_desk('openmausbot', '--', 'argument with spaces')
        record = self.read_record('openmausbot-launch.json')
        cache = self.storage / 'cache/openmausbot'
        self.assertEqual(record['args'], ['--disable-setuid-sandbox', '--disk-cache-dir=' + str(cache / 'chromium'), '--', 'argument with spaces'])
        self.assertEqual(record['env']['PATH'].split(os.pathsep)[0], str(self.home / '.local/bin'))
        self.assertEqual(record['env']['OMB_DATA_DIR'], str(custom))
        self.assertEqual(record['env']['XDG_CONFIG_HOME'], str(self.home / '.config'))
        self.assertEqual(record['env']['APPDIR'], str(self.storage / 'apps/openmausbot/current'))
        for name in ('TMPDIR', 'XDG_CACHE_HOME', 'MESA_SHADER_CACHE_DIR'):
            self.assertTrue(Path(record['env'][name]).is_relative_to(cache), record)
        self.assertEqual(record['env']['LD_LIBRARY_PATH'].split(os.pathsep)[0], str(self.storage / 'apps/openmausbot/current/usr/lib'))
        for directory in ('Code Cache', 'server-compile-cache'):
            self.assertTrue((profile / directory).is_symlink())
            self.assertEqual((profile / directory).resolve(), cache / 'profile' / directory)
        self.assertFalse(existing.is_symlink())
        self.assertEqual((existing / 'existing-cache').read_text(), 'keep existing directory')
        self.assertEqual((custom / 'config.json').read_text(), 'saved bots')

    def test_openmausbot_recreates_cache_targets_after_clean(self):
        self.install('openmausbot')
        self.run_desk('openmausbot')
        self.read_record('openmausbot-launch.json')
        profile = self.home / '.config/openmausbot'
        (profile / 'credentials.bin').write_text('saved account')
        self.source('setup_runtime; clean_reset_unlocked')
        self.assertFalse((profile / 'server-compile-cache').exists())
        self.assertTrue((profile / 'server-compile-cache').is_symlink())
        self.install('openmausbot')
        self.run_desk('openmausbot')
        self.assertTrue((profile / 'server-compile-cache').is_dir())
        self.assertEqual((profile / 'credentials.bin').read_text(), 'saved account')

    def test_openmausbot_open_picker_and_maintenance_work_offline(self):
        self.install('openmausbot')
        requests = (self.root / 'requests').read_text()
        (self.root / 'offline').touch()
        self.run_desk('p')
        self.source('setup_runtime; shell_prepare_component openmausbot')
        self.run_desk('open', 'openmausbot')
        self.read_record('openmausbot-launch.json')
        self.assertEqual((self.state / 'open-programs').read_text(), 'openmausbot\n')
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertRegex(self.run_desk('st').stdout, r'OpenMausBot\s+yes\s+installed\s+v0.1.116')

    def test_openmausbot_update_failure_preserves_app_then_valid_update_succeeds(self):
        self.install('openmausbot')
        current = self.storage / 'apps/openmausbot/current'
        old = current.resolve()
        artifact = self.make_release('openmausbot', 'v0.1.117')
        artifact.write_bytes(b'corrupt download')
        result = self.run_desk('update', 'openmausbot', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertEqual(current.resolve(), old)
        self.make_release('openmausbot', 'v0.1.117')
        self.run_desk('update', 'openmausbot')
        self.assertNotEqual(current.resolve(), old)
        self.assertTrue(old.is_dir())
        self.assertEqual((self.state / 'programs').read_text(), 'openmausbot\n')
        self.assertEqual((self.storage / 'apps/openmausbot/.installed-version').read_text(), 'v0.1.117\n')
        self.assertFalse((self.root / 'openmausbot-launch.json').exists())

    def test_openmausbot_arm64_is_rejected_without_a_download(self):
        self.write_executable(self.bin / 'uname', '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo aarch64;; esac\n')
        result = self.run_desk('install', 'openmausbot', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('x86_64 only', result.stderr)
        self.assertFalse((self.root / 'requests').exists())

    def test_openmausbot_running_blocks_updates_and_cleanup(self):
        self.install('openmausbot')
        executable = self.storage / 'apps/openmausbot/current/AppRun'
        executable.unlink()
        shutil.copy2(shutil.which('sleep'), executable)
        process = subprocess.Popen(['bot-desktop', '30'], executable=str(executable))
        try:
            requests = (self.root / 'requests').read_text()
            result = self.run_desk('update', 'openmausbot')
            self.assertIn('is running', result.stderr)
            self.assertEqual((self.root / 'requests').read_text(), requests)
            result = self.source('setup_runtime; native_apps_running', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('OpenMausBot is running', result.stderr)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_openmausbot_lock_blocks_clean_and_releases_other_locks(self):
        self.save_selection('openmausbot\n')
        lock = self.state / 'locks/openmausbot.lock'
        lock.mkdir(parents=True)
        (lock / 'pid').write_text(str(os.getpid()))
        code, output = self.interact('clean', [b'y\n'], b'Continue? [y/N] ')
        self.assertEqual(code, 1, output.decode())
        self.assertTrue(lock.exists())
        for name in ('first-run', 'core', 'code', 'brave', 'codex', 'claude', 'flutter',
                     'hermes', 'codex-desktop', 'claude-desktop'):
            self.assertFalse((self.state / 'locks' / (name + '.lock')).exists())


class HermesTests(AppFixtures):
    def setUp(self):
        super().setUp()
        self.repo = self.root / 'upstream-hermes'
        self.repo.mkdir()
        self.real_git = shutil.which('git')
        self.git('init', '-q')
        (self.repo / '.gitignore').write_text('.hermes/\napps/desktop/release/\n')
        (self.repo / 'hermes_cli').mkdir()
        (self.repo / 'hermes_cli/main.py').write_text('# official source fixture\n')
        (self.repo / 'uv.lock').write_text('version = 1\n')
        (self.repo / 'pm').mkdir()
        (self.repo / 'pm/lock.json').write_text('{}')
        (self.repo / 'scripts').mkdir()
        (self.repo / 'scripts/install.sh').write_text('''#!/bin/bash
set -eu
stage= dir= desktop=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --stage) stage=$2; shift ;;
    --dir) dir=$2; shift ;;
    --include-desktop) desktop=1 ;;
    --non-interactive|--skip-browser|--skip-computer-use) ;;
    *) exit 2 ;;
  esac
  shift
done
python3 - "$stage" "$dir" "$desktop" <<'PY'
import json, os, pathlib, sys
root = pathlib.Path(os.environ['DESK_FIXTURE'])
with (root / 'hermes-stages').open('a') as stream:
    stream.write(json.dumps({'stage': sys.argv[1], 'source': sys.argv[2],
        'home': os.environ['HERMES_HOME'], 'runtime': os.environ['HERMES_RUNTIME_DIR'],
        'desktop': sys.argv[3] == '1'}) + '\\n')
if os.environ.get('DESK_TEST_FAIL_STAGE') == sys.argv[1]:
    sys.exit(1)
if sys.argv[1] == 'products':
    source = pathlib.Path(sys.argv[2])
    executable = source / '.hermes/bin/hermes'
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text((source / 'fixture-cli').read_text())
    executable.chmod(0o755)
    if sys.argv[3] == '1' and not os.environ.get('DESK_TEST_SKIP_DESKTOP'):
        unpacked = source / 'apps/desktop/release/linux-unpacked'
        (unpacked / 'resources').mkdir(parents=True, exist_ok=True)
        (unpacked / 'resources/app.asar').write_text('packaged desktop fixture')
        desktop = unpacked / 'hermes'
        desktop.write_text((source / 'fixture-desktop').read_text())
        desktop.chmod(0o755)
PY
''')
        (self.repo / 'fixture-desktop').write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['DESK_FIXTURE'])
(root / 'hermes-desktop-launch.json').write_text(json.dumps({
    'args': sys.argv[1:], 'env': {name: os.environ.get(name) for name in (
        'HERMES_HOME', 'HERMES_DESKTOP_HERMES', 'HERMES_INSTALL_ROOT', 'XDG_CONFIG_HOME',
        'XDG_CACHE_HOME', 'TMPDIR', 'ELECTRON_CACHE', 'ELECTRON_BUILDER_CACHE',
        'MESA_SHADER_CACHE_DIR', '__GL_SHADER_DISK_CACHE_PATH')}
}))
''')
        (self.repo / 'fixture-cli').write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
if sys.argv[1:] == ['--help']:
    print('Hermes help')
    sys.exit(0)
root = pathlib.Path(os.environ['DESK_FIXTURE'])
(root / 'hermes-launch.json').write_text(json.dumps({
    'args': sys.argv[1:], 'input': sys.stdin.read(),
    'env': {name: os.environ.get(name) for name in ('HERMES_HOME', 'HERMES_RUNTIME_DIR',
        'UV_CACHE_DIR', 'UV_PYTHON_INSTALL_DIR', 'PIP_CACHE_DIR', 'TMPDIR', 'XDG_CACHE_HOME')}
}))
sys.exit(int(os.environ.get('DESK_TEST_EXIT', '0')))
''')
        self.make_release('0.1.0')
        self.write_executable(self.bin / 'git', '''#!/usr/bin/env python3
import os, pathlib, sys
real_git = REAL_GIT
root = pathlib.Path(os.environ['DESK_FIXTURE'])
args = sys.argv[1:]
official = 'https://github.com/NousResearch/hermes-agent.git'
if official in args:
    with (root / 'git-requests').open('a') as stream:
        stream.write(' '.join(args) + '\\n')
    if (root / 'offline').exists():
        sys.exit(128)
    args = [str(root / 'upstream-hermes') if arg == official else arg for arg in args]
os.execv(real_git, [real_git, *args])
'''.replace('REAL_GIT', repr(self.real_git)))
        self.base = self.storage / 'apps/hermes'

    def git(self, *args):
        return subprocess.run([self.real_git, '-C', str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def make_release(self, version):
        (self.repo / 'version').write_text(version)
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', version)
        self.git('-c', 'tag.gpgsign=false', 'tag', 'v' + version)

    def install(self):
        return self.run_desk('install', 'hermes')

    def test_install_uses_only_official_release_and_noninteractive_stages(self):
        self.install()
        self.assertEqual((self.state / 'programs').read_text(), 'hermes\n')
        self.assertTrue((self.home / '.local/bin/hermes').is_file())
        self.assertFalse((self.root / 'hermes-launch.json').exists())
        stages = [json.loads(line) for line in (self.root / 'hermes-stages').read_text().splitlines()]
        self.assertEqual([stage['stage'] for stage in stages], ['venv', 'python-deps', 'config', 'products', 'complete'])
        self.assertTrue(all(stage['runtime'] == str(self.storage / 'cache/hermes/runtime') for stage in stages))
        self.assertIn('https://github.com/NousResearch/hermes-agent.git', (self.root / 'git-requests').read_text())
        for directory in ('installs', 'tools', 'cache', 'image_cache', 'audio_cache'):
            self.assertTrue((self.home / '.hermes' / directory).resolve().is_relative_to(self.storage))

    def test_launch_preserves_arguments_stdin_exit_status_and_config_override(self):
        self.install()
        self.env['HERMES_HOME'] = str(self.root / 'custom hermes home')
        self.env['DESK_TEST_EXIT'] = '17'
        result = self.run_desk('hermes', 'chat', '--query', 'a prompt with spaces', input='stdin\n', check=False)
        self.assertEqual(result.returncode, 17)
        record = self.read_record('hermes-launch.json')
        self.assertEqual(record['args'], ['chat', '--query', 'a prompt with spaces'])
        self.assertEqual(record['input'], 'stdin\n')
        self.assertEqual(record['env']['HERMES_HOME'], self.env['HERMES_HOME'])
        for key, value in record['env'].items():
            if key != 'HERMES_HOME':
                self.assertTrue(Path(value).is_relative_to(self.storage / 'cache/hermes'), (key, value))

    def test_repeat_and_shell_maintenance_are_offline_once_ready(self):
        self.install()
        requests = (self.root / 'git-requests').read_text()
        stages = (self.root / 'hermes-stages').read_text()
        (self.root / 'offline').touch()
        self.run_desk('p')
        self.source('setup_runtime; shell_prepare_component hermes')
        self.assertEqual((self.root / 'git-requests').read_text(), requests)
        self.assertEqual((self.root / 'hermes-stages').read_text(), stages)

    def test_update_stages_new_release_before_switching_and_preserves_user_state(self):
        self.install()
        config = self.home / '.hermes/config.yaml'
        config.write_text('existing user settings')
        old = (self.base / 'current').resolve()
        self.make_release('0.2.0')
        self.run_desk('update', 'hermes')
        self.assertNotEqual((self.base / 'current').resolve(), old)
        self.assertTrue(old.is_dir())
        self.assertEqual(config.read_text(), 'existing user settings')
        self.assertEqual((self.base / '.installed-version').read_text(), '0.2.0\n')
        self.assertEqual((self.state / 'programs').read_text(), 'hermes\n')

    def test_failed_update_keeps_previous_working_release(self):
        self.install()
        before = (self.base / 'current').resolve()
        self.make_release('0.2.0')
        self.env['DESK_TEST_FAIL_STAGE'] = 'products'
        result = self.run_desk('update', 'hermes', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.base / 'current').resolve(), before)
        self.assertEqual((self.base / '.installed-version').read_text(), '0.1.0\n')
        self.env.pop('DESK_TEST_FAIL_STAGE')
        self.run_desk('update', 'hermes')
        self.assertEqual((self.base / '.installed-version').read_text(), '0.2.0\n')

    def test_local_source_changes_are_not_overwritten(self):
        self.install()
        source = self.base / 'current/source/version'
        source.write_text('my changes')
        self.make_release('0.2.0')
        result = self.run_desk('update', 'hermes', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('local source changes', result.stderr)
        self.assertEqual(source.read_text(), 'my changes')

    def test_update_keeps_a_newer_version_and_offline_existing_install(self):
        self.make_release('0.2.0')
        self.install()
        self.git('tag', '-d', 'v0.2.0')
        self.run_desk('update', 'hermes')
        (self.root / 'offline').touch()
        result = self.run_desk('update', 'hermes')
        self.assertIn('keeping the installed agent', result.stderr)
        self.assertEqual((self.base / '.installed-version').read_text(), '0.2.0\n')

    def test_running_hermes_postpones_update_without_contacting_git(self):
        self.install()
        executable = self.base / 'current/source/.hermes/bin/hermes'
        executable.unlink()
        shutil.copy2(shutil.which('sleep'), executable)
        process = subprocess.Popen(['renamed-agent', '30'], executable=str(executable))
        try:
            requests = (self.root / 'git-requests').read_text()
            result = self.run_desk('update', 'hermes')
            self.assertIn('is running', result.stderr)
            self.assertEqual((self.root / 'git-requests').read_text(), requests)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_clean_keeps_credentials_and_can_recreate_goinfre_cache_links(self):
        self.install()
        config = self.home / '.hermes/.env'
        config.write_text('existing account settings')
        self.source('setup_runtime; clean_reset_unlocked')
        self.assertFalse(self.base.exists())
        self.assertFalse((self.home / '.local/bin/hermes').exists())
        self.assertEqual(config.read_text(), 'existing account settings')
        self.install()
        self.assertTrue((self.home / '.hermes/installs').is_dir())
        self.assertEqual(config.read_text(), 'existing account settings')

    def test_direct_hermes_update_uses_desks_update_flow(self):
        self.install()
        self.make_release('0.2.0')
        self.run_desk('hermes', 'update')
        self.assertEqual((self.base / '.installed-version').read_text(), '0.2.0\n')
        self.assertFalse((self.root / 'hermes-launch.json').exists())

    def test_desktop_install_builds_gui_without_opening_and_creates_menu_and_wrapper(self):
        self.run_desk('install', 'hermes-desktop')
        self.assertTrue((self.base / 'current/desktop').is_file())
        self.assertTrue((self.home / '.local/bin/hermes-desktop').is_file())
        entry = (self.home / '.local/share/applications/hermes-desktop-desk.desktop').read_text()
        self.assertIn('Name=Hermes Desktop\n', entry)
        self.assertIn('hermes-desktop %U', entry)
        stages = [json.loads(line) for line in (self.root / 'hermes-stages').read_text().splitlines()]
        self.assertEqual([stage['stage'] for stage in stages], ['venv', 'python-deps', 'config', 'products', 'complete'])
        self.assertTrue(all(stage['desktop'] for stage in stages))
        self.assertFalse((self.root / 'hermes-launch.json').exists())
        self.assertFalse((self.root / 'hermes-desktop-launch.json').exists())
        self.assertEqual((self.state / 'programs').read_text(), 'hermes-desktop\n')
        result = self.run_desk('st')
        self.assertRegex(result.stdout, r'Hermes Desktop\s+yes\s+installed\s+0.1.0')

    def test_checklist_selects_only_hermes_desktop(self):
        code, output = self.interact('install', [b'n' + b'j' * 9 + b' \r'])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b'Hermes Desktop (official)', output)
        self.assertIn(b'Hermes Agent (CLI)', output)
        self.assertEqual((self.state / 'programs').read_text(), 'hermes-desktop\n')

    def test_desktop_launch_uses_managed_backend_and_goinfre_cache_preserving_profile(self):
        self.run_desk('install', 'hermes-desktop')
        profile = self.home / '.config/Hermes/connections.json'
        profile.parent.mkdir(parents=True)
        profile.write_text('saved desktop connections')
        self.env['HERMES_HOME'] = str(self.root / 'custom Hermes home')
        self.run_desk('hermes-desktop', '--local', 'argument with spaces')
        record = self.read_record('hermes-desktop-launch.json')
        cache = self.storage / 'cache/hermes'
        self.assertEqual(record['args'], ['--disable-setuid-sandbox', '--disk-cache-dir=' + str(cache / 'chromium'), '--local', 'argument with spaces'])
        self.assertEqual(record['env']['HERMES_DESKTOP_HERMES'], str(self.base / 'current/source/.hermes/bin/hermes'))
        self.assertEqual(record['env']['HERMES_INSTALL_ROOT'], str(self.base / 'current/source'))
        self.assertEqual(record['env']['HERMES_HOME'], self.env['HERMES_HOME'])
        self.assertEqual(record['env']['XDG_CONFIG_HOME'], str(self.home / '.config'))
        for key in ('TMPDIR', 'XDG_CACHE_HOME', 'ELECTRON_CACHE', 'ELECTRON_BUILDER_CACHE',
                    'MESA_SHADER_CACHE_DIR', '__GL_SHADER_DISK_CACHE_PATH'):
            self.assertTrue(Path(record['env'][key]).is_relative_to(cache), (key, record))
        self.assertEqual(profile.read_text(), 'saved desktop connections')

    def test_open_desktop_does_not_require_a_terminal_or_network(self):
        self.run_desk('install', 'hermes-desktop')
        requests = (self.root / 'git-requests').read_text()
        stages = (self.root / 'hermes-stages').read_text()
        (self.root / 'offline').touch()
        self.run_desk('p')
        self.source('setup_runtime; shell_prepare_component hermes-desktop')
        self.run_desk('open', 'hermes-desktop')
        self.read_record('hermes-desktop-launch.json')
        self.assertEqual((self.state / 'open-programs').read_text(), 'hermes-desktop\n')
        self.assertEqual((self.root / 'git-requests').read_text(), requests)
        self.assertEqual((self.root / 'hermes-stages').read_text(), stages)

    def test_can_add_desktop_to_an_existing_cli_at_the_same_version(self):
        self.install()
        current = (self.base / 'current').resolve()
        self.run_desk('install', 'hermes-desktop')
        self.assertEqual((self.base / 'current').resolve(), current)
        self.source('setup_runtime; hermes_ready; hermes_desktop_ready')
        self.assertTrue((self.base / 'current/.desk-desktop-ready').is_file())

    def test_adding_desktop_offline_cannot_mistake_cli_for_ready_desktop(self):
        self.install()
        (self.root / 'offline').touch()
        result = self.run_desk('install', 'hermes-desktop', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / 'current/desktop').exists())
        self.source('setup_runtime; hermes_ready')

    def test_cli_update_preserves_the_installed_desktop(self):
        self.run_desk('install', 'hermes-desktop')
        self.make_release('0.2.0')
        self.run_desk('update', 'hermes')
        self.source('setup_runtime; hermes_ready; hermes_desktop_ready')
        self.assertEqual((self.base / '.installed-version').read_text(), '0.2.0\n')
        self.assertEqual((self.state / 'programs').read_text(), 'hermes-desktop\n')
        self.assertFalse((self.root / 'hermes-desktop-launch.json').exists())

    def test_missing_gui_after_successful_products_stage_keeps_previous_desktop(self):
        self.run_desk('install', 'hermes-desktop')
        current = (self.base / 'current').resolve()
        self.make_release('0.2.0')
        self.env['DESK_TEST_SKIP_DESKTOP'] = '1'
        result = self.run_desk('update', 'hermes-desktop', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Desktop build is incomplete', result.stderr)
        self.assertEqual((self.base / 'current').resolve(), current)
        self.assertEqual((self.base / '.installed-version').read_text(), '0.1.0\n')
        self.env.pop('DESK_TEST_SKIP_DESKTOP')
        self.run_desk('update', 'hermes-desktop')
        self.source('setup_runtime; hermes_desktop_ready')
        self.assertEqual((self.base / '.installed-version').read_text(), '0.2.0\n')

    def test_running_desktop_postpones_cli_update_and_blocks_cleanup(self):
        self.run_desk('install', 'hermes-desktop')
        executable = (self.base / 'current/desktop').resolve()
        executable.unlink()
        shutil.copy2(shutil.which('sleep'), executable)
        process = subprocess.Popen(['hermes-gui', '30'], executable=str(executable))
        try:
            requests = (self.root / 'git-requests').read_text()
            result = self.run_desk('update', 'hermes')
            self.assertIn('is running', result.stderr)
            self.assertEqual((self.root / 'git-requests').read_text(), requests)
            result = self.source('setup_runtime; native_apps_running', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Hermes is running', result.stderr)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_clean_removes_desktop_launcher_and_keeps_user_data(self):
        self.run_desk('install', 'hermes-desktop')
        config = self.home / '.hermes/config.yaml'
        config.write_text('account settings')
        profile = self.home / '.config/Hermes/connections.json'
        profile.parent.mkdir(parents=True)
        profile.write_text('desktop connections')
        self.source('setup_runtime; clean_reset_unlocked')
        self.assertFalse(self.base.exists())
        self.assertFalse((self.home / '.local/bin/hermes-desktop').exists())
        self.assertFalse((self.home / '.local/share/applications/hermes-desktop-desk.desktop').exists())
        self.assertEqual(config.read_text(), 'account settings')
        self.assertEqual(profile.read_text(), 'desktop connections')


if __name__ == '__main__':
    unittest.main()
