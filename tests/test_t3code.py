"""T3 Code verified releases, managed storage, and coding-agent discovery."""

import json
import os
import shutil
import subprocess

import test_ai_apps as apps


class T3CodeTests(apps.AppFixtures):
    repos = {'t3code': 'pingdotgg/t3code'}
    make_release = apps.DesktopAppTests.make_release

    def setUp(self):
        super().setUp()
        self.env.pop('T3CODE_HOME', None)
        self.env.pop('ELECTRON_RUN_AS_NODE', None)
        self.urls = {}
        self.write_executable(self.bin / 'ps', '#!/bin/sh\necho bash\n')
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
        self.make_release('t3code', 'v0.1.3')

    @property
    def base(self):
        return self.storage / 'apps/t3code'

    def install(self):
        return self.run_desk('install', 't3code')

    def test_install_verified_official_desktop_only_without_opening(self):
        self.install()
        self.assertEqual((self.state / 'programs').read_text(), 't3code\n')
        self.assertTrue((self.base / 'current/t3code').is_file())
        self.assertFalse((self.root / 't3code-launch.json').exists())
        self.assertFalse((self.storage / 'apps/codex').exists())
        self.assertFalse((self.storage / 'apps/claude').exists())
        self.assertFalse((self.base / 'downloads/application.AppImage').exists())
        receipt = json.loads((self.base / '.desk-release.json').read_text())
        self.assertEqual(receipt['repo'], 'pingdotgg/t3code')
        self.assertEqual(len(receipt['sha256']), 64)
        self.assertTrue((self.home / '.local/bin/t3code').is_file())
        entry = (self.home / '.local/share/applications/t3code-desk.desktop').read_text()
        self.assertIn('Official T3 Code', entry)
        self.assertIn('x-scheme-handler/t3code', entry)
        for source, target in ((self.home / '.t3', self.storage / 'data/t3code/home'),
                               (self.home / '.config/t3code-v2', self.storage / 'data/t3code/config/t3code-v2')):
            self.assertTrue(source.is_symlink())
            self.assertEqual(source.resolve(), target)
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)

    def test_checklist_and_alias_select_t3code_without_other_programs(self):
        code, output = self.interact('install', [b'n' + b'j' * 14 + b' \r'])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b'T3 Code (official desktop)', output)
        self.assertEqual((self.state / 'programs').read_text(), 't3code\n')
        self.run_desk('install', 't3-code')
        self.assertEqual((self.state / 'programs').read_text(), 't3code\n')

    def test_launch_native_app_with_agent_path_caches_and_url_handler_wrapper(self):
        self.install()
        self.env['CODEX_HOME'] = str(self.home / 'custom codex')
        self.env['CLAUDE_CONFIG_DIR'] = str(self.home / 'custom claude')
        self.write_executable(self.home / '.local/bin/codex', '#!/bin/sh\nexit 0\n')
        self.run_desk('t3-code', 't3code://callback?code=test', 'argument with spaces')
        record = self.read_record('t3code-launch.json')
        cache = self.storage / 'cache/t3code'
        self.assertEqual(record['args'], ['--disable-setuid-sandbox', '--disk-cache-dir=' + str(cache / 'chromium'),
                                          't3code://callback?code=test', 'argument with spaces'])
        self.assertNotIn('--no-sandbox', record['args'])
        self.assertEqual(record['env']['PATH'].split(os.pathsep)[0], str(self.home / '.local/bin'))
        for key, target in (('XDG_CACHE_HOME', 'xdg'), ('TMPDIR', 'tmp'), ('MESA_SHADER_CACHE_DIR', 'mesa'),
                            ('npm_config_cache', 'npm'), ('NODE_COMPILE_CACHE', 'node-compile')):
            self.assertEqual(record['env'][key], str(cache / target))
        self.assertEqual(record['env']['T3CODE_DISABLE_AUTO_UPDATE'], 'true')
        self.assertEqual(record['env']['T3CODE_DESKTOP_LAUNCHER_PATH'], str(self.home / '.local/bin/t3code'))
        self.assertEqual(record['env']['CODEX_HOME'], self.env['CODEX_HOME'])
        self.assertEqual(record['env']['CLAUDE_CONFIG_DIR'], self.env['CLAUDE_CONFIG_DIR'])
        self.assertIsNone(record['env']['CODEX_CLI_PATH'])

    def test_open_picker_status_and_background_maintenance_support_t3code(self):
        self.install()
        requests = (self.root / 'requests').read_text()
        (self.root / 'offline').touch()
        self.run_desk('open', 't3code')
        self.assertEqual((self.state / 'open-programs').read_text(), 't3code\n')
        self.assertIn('T3 Code', self.run_desk('st').stdout)
        self.source('setup_runtime; shell_prepare_component t3code')
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertIn('[GOINFRE]', self.run_desk('storage').stdout)

    def test_updates_switch_release_keep_previous_and_do_not_launch_or_downgrade(self):
        self.install()
        previous = (self.base / 'current').resolve()
        self.make_release('t3code', 'v0.1.4')
        self.run_desk('update', 't3code')
        self.assertEqual((self.base / '.installed-version').read_text(), 'v0.1.4\n')
        self.assertTrue(previous.is_dir())
        self.assertFalse((self.root / 't3code-launch.json').exists())
        self.assertEqual((self.state / 'programs').read_text(), 't3code\n')
        self.make_release('t3code', 'v0.1.3')
        self.run_desk('update', 't3code')
        self.assertEqual((self.base / '.installed-version').read_text(), 'v0.1.4\n')

    def test_bad_digest_missing_digest_foreign_url_and_extraction_preserve_current(self):
        self.install()
        current = (self.base / 'current').resolve()
        for options, message in (({}, 'checksum mismatch'), ({'missing_digest': True}, 'no unique matching'),
                                 ({'bad_host': True}, 'unexpected AppImage download URL'),
                                 ({'fail_extract': True}, 'non-zero exit status')):
            with self.subTest(options=options):
                artifact = self.make_release('t3code', 'v0.1.4', **options)
                if not options:
                    artifact.write_bytes(b'corrupt package')
                result = self.run_desk('update', 't3code', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual((self.base / 'current').resolve(), current)

    def test_incompatible_runtime_and_incomplete_package_do_not_activate(self):
        self.install()
        current = (self.base / 'current').resolve()
        for options, message in (({'fail_runtime': True}, 'runtime/SQLite is incompatible'),
                                 ({'incomplete': True}, 'missing its native app or resources')):
            self.make_release('t3code', 'v0.1.4', **options)
            result = self.run_desk('update', 't3code', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertEqual((self.base / 'current').resolve(), current)

    def test_doctor_is_read_only_and_missing_install_does_not_download(self):
        result = self.run_desk('t3code', '--doctor', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not installed', result.stdout)
        self.assertFalse((self.root / 'requests').exists())
        self.assertFalse((self.home / '.t3').exists())
        self.install()
        state = self.home / '.t3/userdata/statev2.sqlite'
        state.parent.mkdir()
        state.write_bytes(b'private database; do not open')
        requests = (self.root / 'requests').read_text()
        report = self.run_desk('t3code', '--doctor')
        self.assertIn('Runtime/SQLite (in memory)', report.stdout)
        self.assertNotIn('private database', report.stdout)
        self.assertEqual(state.read_bytes(), b'private database; do not open')
        self.assertFalse((self.root / 't3code-launch.json').exists())
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertEqual(self.run_desk('t3code', '--version').stdout, 'v0.1.3\n')
        self.assertEqual(self.run_desk('t3code', '--doctor', 'extra', check=False).returncode, 2)

    def test_existing_profiles_and_custom_home_are_preserved(self):
        state = self.home / '.t3/state.sqlite'
        state.parent.mkdir()
        state.write_bytes(b'existing chat data')
        profile = self.home / '.config/t3code-v2'
        profile.mkdir(parents=True)
        (profile / 'Local State').write_text('existing key material')
        self.install()
        self.assertFalse(state.parent.is_symlink())
        self.assertFalse(profile.is_symlink())
        self.assertEqual(state.read_bytes(), b'existing chat data')
        self.assertEqual((profile / 'Local State').read_text(), 'existing key material')
        custom = self.root / 'private t3'
        custom.mkdir()
        self.env['T3CODE_HOME'] = str(custom)
        self.run_desk('t3code')
        self.assertEqual(self.read_record('t3code-launch.json')['env']['T3CODE_HOME'], str(custom))
        self.assertEqual(state.read_bytes(), b'existing chat data')

    def test_explicit_home_leaves_default_path_uncreated_and_custom_links_untouched(self):
        self.env['T3CODE_HOME'] = str(self.root / 'private state')
        external = self.root / 'external profile'
        external.mkdir()
        source = self.home / '.config/t3code-v2'
        source.parent.mkdir(parents=True)
        source.symlink_to(external)
        self.install()
        self.assertFalse((self.home / '.t3').exists())
        self.assertEqual(source.resolve(), external)
        self.assertFalse((self.storage / 'data/t3code/home').exists())

    def test_recreates_missing_managed_target_but_refuses_broken_custom_link(self):
        self.install()
        home = self.home / '.t3'
        target = home.resolve()
        target.rmdir()
        self.run_desk('t3code')
        self.assertTrue(target.is_dir())
        self.assertEqual(home.resolve(), target)
        home.unlink()
        home.symlink_to(self.root / 'lost custom state')
        (self.root / 't3code-launch.json').unlink()
        result = self.run_desk('t3code', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Broken custom T3 Code link', result.stderr)
        self.assertFalse((self.root / 't3code-launch.json').exists())

    def test_active_native_process_blocks_update_and_clean(self):
        self.install()
        binary = self.base / 'current/renamed-app'
        shutil.copy2('/bin/sleep', binary)
        process = subprocess.Popen([str(binary), '60'], env=self.env)
        try:
            requests = (self.root / 'requests').read_text()
            result = self.run_desk('update', 't3code')
            self.assertIn('is running', result.stderr)
            self.assertEqual((self.root / 'requests').read_text(), requests)
            result = self.source('setup_runtime; native_apps_running', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('T3 Code is running', result.stderr)
            self.assertTrue(self.base.is_dir())
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_clean_keeps_chat_data_and_profiles_and_removes_owned_launchers(self):
        self.install()
        data = self.home / '.t3/statev2.sqlite'
        data.write_bytes(b'keep chat history')
        profile = self.home / '.config/t3code-v2/Local State'
        profile.write_text('keep profile')
        self.source('setup_runtime; clean_reset_unlocked')
        self.assertEqual(data.read_bytes(), b'keep chat history')
        self.assertEqual(profile.read_text(), 'keep profile')
        self.assertFalse(self.base.exists())
        self.assertFalse((self.home / '.local/bin/t3code').exists())
        self.assertFalse((self.home / '.local/share/applications/t3code-desk.desktop').exists())
