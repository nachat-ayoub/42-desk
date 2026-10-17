"""Exercise Flutter's verified SDK install, updates, cache routing, and ADB integration."""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import unittest

import test_programs as helpers


class FlutterTests(unittest.TestCase):
    write_executable = staticmethod(helpers.ProgramTests.write_executable)
    write_platform = helpers.ProgramTests.write_platform
    run_desk = helpers.ProgramTests.run_desk
    source = helpers.ProgramTests.source
    save_selection = helpers.ProgramTests.save_selection
    interact = helpers.ProgramTests.interact

    def setUp(self):
        helpers.ProgramTests.setUp(self)
        self.flutter = self.storage / 'apps/flutter'
        self.sdk = self.flutter / 'sdk'
        for key in ('PUB_CACHE', 'GRADLE_USER_HOME', 'ANDROID_HOME', 'ANDROID_SDK_ROOT',
                    'ANDROID_ADB_SERVER_PORT', 'ADB_SERVER_PORT', 'ADB_SERVER_SOCKET'):
            self.env.pop(key, None)
        self.repo = 'https://storage.googleapis.com/flutter_infra_release/releases/'
        self.manifest_url = 'https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json'
        self.write_executable(self.bin / 'curl', '''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['DESK_FIXTURE'])
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith('https://'))
with (root / 'requests').open('a') as stream:
    stream.write(url + '\\n')
if (root / 'offline').exists():
    print('000', end='')
    sys.exit(7)
errors = root / 'download-errors.json'
error = json.loads(errors.read_text()).get(url) if errors.exists() else None
if error:
    pathlib.Path(args[args.index('-o') + 1]).write_bytes(b'incomplete download')
    print(error['status'], end='')
    sys.exit(error['exit'])
source = json.loads((root / 'urls.json').read_text()).get(url)
if source is None:
    sys.exit('Unexpected download: ' + url)
pathlib.Path(args[args.index('-o') + 1]).write_bytes(pathlib.Path(source).read_bytes())
if '--write-out' in args:
    print('200', end='')
''')
        self.make_release()

    def make_release(self, version='3.40.0', unsafe=False):
        source = self.root / ('sdk-source-' + version)
        source.mkdir()
        (source / '.gitignore').write_text('/bin/cache/\n')
        (source / 'README.md').write_text('SDK fixture ' + version)
        script = '''#!/usr/bin/env python3
import json, os, pathlib, sys
if sys.argv[1:] == ['--version', '--machine']:
    print(json.dumps({'frameworkVersion': 'VERSION'}))
    sys.exit(0)
root = pathlib.Path(os.environ['DESK_FIXTURE'])
(root / 'flutter-launch.json').write_text(json.dumps({
    'command': pathlib.Path(sys.argv[0]).name, 'args': sys.argv[1:],
    'input': sys.stdin.read(),
    'environment': {key: os.environ.get(key) for key in (
        'FLUTTER_ROOT', 'PUB_CACHE', 'GRADLE_USER_HOME', 'TMPDIR',
        'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'ANDROID_HOME', 'ANDROID_SDK_ROOT',
        'ANDROID_USER_HOME', 'ANDROID_AVD_HOME', 'ADB_SERVER_SOCKET', 'ANDROID_ADB_SERVER_PORT')}
}))
sys.exit(int(os.environ.get('DESK_TEST_EXIT', '0')))
'''.replace('VERSION', version)
        for path in ('bin/flutter', 'bin/dart', 'bin/cache/dart-sdk/bin/dart'):
            self.write_executable(source / path, script)
        for args in (
            ['init', '-q'], ['add', '.'],
            ['-c', 'user.name=Desk SDK Fixture', '-c', 'user.email=fixture@example.test',
             '-c', 'commit.gpgsign=false', 'commit', '-qm', version],
        ):
            subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True)
        revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        archive_name = 'stable/linux/flutter_linux_' + version + '-stable.tar.xz'
        archive = self.root / Path(archive_name).name
        with tarfile.open(archive, 'w:xz') as stream:
            stream.add(source, arcname='flutter')
            if unsafe:
                info = tarfile.TarInfo('../escaped')
                info.size = 4
                stream.addfile(info, io.BytesIO(b'bad!'))
        self.manifest = {
            'base_url': self.repo.rstrip('/'), 'current_release': {'stable': revision},
            'releases': [{'hash': revision, 'channel': 'stable', 'version': version,
                          'dart_sdk_arch': 'x64', 'archive': archive_name,
                          'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}],
        }
        self.archive = archive
        self.write_manifest()

    def write_manifest(self):
        manifest = self.root / 'flutter-releases.json'
        manifest.write_text(json.dumps(self.manifest))
        (self.root / 'urls.json').write_text(json.dumps({
            self.manifest_url: str(manifest),
            self.repo + self.manifest['releases'][0]['archive']: str(self.archive),
        }))

    def install(self):
        return self.run_desk('install', 'flutter')

    def test_downloads_manifest_and_archive_from_official_release_directory(self):
        self.install()
        self.assertEqual((self.root / 'requests').read_text().splitlines(), [
            'https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json',
            'https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.40.0-stable.tar.xz',
        ])

    def test_http_manifest_errors_report_status_and_url_without_network_access_advice(self):
        for status in (404, 403):
            with self.subTest(status=status):
                (self.root / 'download-errors.json').write_text(json.dumps({
                    self.manifest_url: {'status': status, 'exit': 22},
                }))
                result = self.run_desk('install', 'flutter', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('release manifest download failed', result.stderr)
                self.assertIn('HTTP ' + str(status), result.stderr)
                self.assertIn(self.manifest_url, result.stderr)
                self.assertNotIn('allow access', result.stderr)
                self.assertFalse(self.sdk.exists())
                self.assertFalse(list((self.flutter / 'downloads').glob('*.part')))

    def test_transport_failure_reports_curl_exit_and_failed_manifest_url(self):
        (self.root / 'offline').touch()
        result = self.run_desk('install', 'flutter', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('curl exit 7', result.stderr)
        self.assertIn(self.manifest_url, result.stderr)
        self.assertNotIn('HTTP 000', result.stderr)

    def test_archive_http_error_keeps_previous_sdk_and_cleans_partial_download(self):
        self.install()
        self.make_release('3.41.0')
        archive_url = self.repo + self.manifest['releases'][0]['archive']
        (self.root / 'download-errors.json').write_text(json.dumps({
            archive_url: {'status': 404, 'exit': 22},
        }))
        result = self.run_desk('update', 'flutter', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('HTTP 404', result.stderr)
        self.assertIn(archive_url, result.stderr)
        self.assertEqual((self.flutter / '.installed-version').read_text(), '3.40.0\n')
        self.assertFalse(list((self.flutter / 'downloads').glob('*.part')))

    def test_install_publishes_verified_sdk_and_both_commands_without_launching(self):
        self.install()
        self.assertTrue((self.sdk / 'bin/flutter').is_file())
        self.assertEqual((self.flutter / '.installed-version').read_text(), '3.40.0\n')
        self.assertEqual((self.state / 'programs').read_text(), 'flutter\n')
        for name in ('flutter', 'dart'):
            self.assertTrue((self.home / '.local/bin' / name).is_file())
        self.assertIn('FLUTTER_ROOT=', (self.home / '.bashrc').read_text())
        self.assertFalse((self.root / 'flutter-launch.json').exists())
        self.assertFalse(list((self.flutter / 'downloads').glob('*.tar.xz')))
        self.assertFalse((self.home / '.pub-cache').exists())
        self.assertFalse((self.home / '.gradle').exists())

    def test_repeat_setup_and_background_maintenance_do_not_contact_release_server(self):
        self.install()
        requests = (self.root / 'requests').read_text()
        (self.root / 'offline').touch()
        self.run_desk('p')
        self.source('setup_runtime; shell_prepare_component flutter')
        self.assertEqual((self.root / 'requests').read_text(), requests)

    def test_flutter_and_dart_preserve_args_stdin_exit_status_and_cache_locations(self):
        self.install()
        self.env['DESK_TEST_EXIT'] = '17'
        for name in ('flutter', 'dart'):
            result = subprocess.run([str(self.home / '.local/bin' / name), '--version'],
                                    env=self.env, input='input\n', text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 17, result.stderr)
            record = json.loads((self.root / 'flutter-launch.json').read_text())
            self.assertEqual(record['command'], name)
            self.assertEqual(record['args'], ['--version'])
            self.assertEqual(record['input'], 'input\n')
            env = record['environment']
            for key in ('PUB_CACHE', 'GRADLE_USER_HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME'):
                self.assertTrue(Path(env[key]).is_relative_to(self.flutter), (key, env[key]))
            self.assertEqual(env['FLUTTER_ROOT'], str(self.sdk))

    def test_flutter_reuses_managed_android_sdk_and_adb_port(self):
        self.install()
        android = self.storage / 'apps/android'
        self.write_executable(android / 'sdk/platform-tools/adb', '#!/bin/sh\nexit 0\n')
        self.run_desk('flutter', 'devices')
        env = json.loads((self.root / 'flutter-launch.json').read_text())['environment']
        self.assertEqual(env['ANDROID_HOME'], str(android / 'sdk'))
        self.assertEqual(env['ANDROID_SDK_ROOT'], str(android / 'sdk'))
        self.assertEqual(env['ANDROID_ADB_SERVER_PORT'], '5038')
        self.assertEqual(env['ADB_SERVER_SOCKET'], 'tcp:localhost:5038')
        self.assertEqual(env['ANDROID_AVD_HOME'], str(android / 'avd'))

    def test_explicit_external_android_sdk_and_cache_bindings_are_preserved(self):
        self.install()
        self.env.update(PUB_CACHE=str(self.root / 'my pub cache'),
                        GRADLE_USER_HOME=str(self.root / 'my gradle'),
                        ANDROID_HOME=str(self.root / 'external sdk'), ADB_SERVER_SOCKET='tcp:localhost:5037')
        self.run_desk('flutter', 'devices')
        env = json.loads((self.root / 'flutter-launch.json').read_text())['environment']
        for key in ('PUB_CACHE', 'GRADLE_USER_HOME', 'ANDROID_HOME', 'ADB_SERVER_SOCKET'):
            self.assertEqual(env[key], self.env[key])

    def test_launch_picker_runs_doctor_without_installing_or_updating(self):
        self.install()
        requests = (self.root / 'requests').read_text()
        self.run_desk('open', 'flutter')
        record = json.loads((self.root / 'flutter-launch.json').read_text())
        self.assertEqual(record['args'], ['doctor'])
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertEqual((self.state / 'open-programs').read_text(), 'flutter\n')

    def test_checkbox_can_select_flutter_without_installing_android(self):
        code, output = self.interact('install', [b'njjjjj \r'])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b'[x] Flutter SDK', output)
        self.assertEqual((self.state / 'programs').read_text(), 'flutter\n')
        self.assertFalse((self.storage / 'apps/android').exists())

    def test_update_replaces_sdk_and_preserves_pub_gradle_and_config(self):
        self.install()
        paths = [self.flutter / 'cache/pub/keep', self.flutter / 'cache/gradle/keep', self.flutter / 'config/keep']
        for path in paths:
            path.write_text('keep me')
        self.make_release('3.41.0')
        self.run_desk('update', 'flutter')
        self.assertEqual((self.flutter / '.installed-version').read_text(), '3.41.0\n')
        for path in paths:
            self.assertEqual(path.read_text(), 'keep me')
        self.assertFalse((self.root / 'flutter-launch.json').exists())

    def test_bad_archive_checksum_keeps_previous_sdk(self):
        self.install()
        self.make_release('3.41.0')
        self.archive.write_bytes(b'broken download')
        result = self.run_desk('update', 'flutter', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertEqual((self.flutter / '.installed-version').read_text(), '3.40.0\n')

    def test_archive_paths_cannot_escape_staging(self):
        self.make_release('3.41.0', unsafe=True)
        result = self.run_desk('install', 'flutter', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('outside the destination', result.stderr)
        self.assertFalse(self.sdk.exists())
        self.assertFalse((self.flutter / 'tmp/escaped').exists())

    def test_sdk_local_changes_are_not_overwritten_by_update(self):
        self.install()
        (self.sdk / 'README.md').write_text('my SDK changes')
        self.make_release('3.41.0')
        result = self.run_desk('update', 'flutter', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('local changes', result.stderr)
        self.assertEqual((self.sdk / 'README.md').read_text(), 'my SDK changes')

    def test_running_sdk_tools_postpone_updates_without_network(self):
        self.install()
        runtime = self.sdk / 'bin/cache/dart-sdk/bin/dart'
        runtime.unlink()
        shutil.copy2(shutil.which('sleep'), runtime)
        process = subprocess.Popen(['renamed-dart-process', '30'], executable=str(runtime))
        try:
            requests = (self.root / 'requests').read_text()
            result = self.run_desk('update', 'flutter')
            self.assertIn('Flutter/Dart tools are running', result.stderr)
            self.assertEqual((self.root / 'requests').read_text(), requests)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_offline_update_preserves_a_ready_sdk(self):
        self.install()
        (self.root / 'offline').touch()
        result = self.run_desk('update', 'flutter')
        self.assertIn('release server unavailable', result.stderr)
        self.assertIn('curl exit 7', result.stderr)
        self.assertIn(self.manifest_url, result.stderr)
        self.assertEqual((self.flutter / '.installed-version').read_text(), '3.40.0\n')

    def test_update_does_not_downgrade_a_newer_managed_sdk(self):
        self.make_release('9.0.0')
        self.install()
        self.make_release('3.41.0')
        self.run_desk('update', 'flutter')
        self.assertEqual((self.flutter / '.installed-version').read_text(), '9.0.0\n')

    def test_generated_shell_hook_handles_goinfre_paths_with_spaces(self):
        self.install()
        result = subprocess.run(['bash', '--noprofile', '--norc', '-c',
                                 'source "$HOME/.bashrc"; printf "%s\\n" "$FLUTTER_ROOT" "$PUB_CACHE" "$GRADLE_USER_HOME"'],
                                env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [str(self.sdk), str(self.flutter / 'cache/pub'),
                                                     str(self.flutter / 'cache/gradle')])

    def test_clean_removes_sdk_and_wrappers_but_preserves_cached_user_settings(self):
        self.install()
        settings = self.flutter / 'cache/gradle/gradle.properties'
        settings.write_text('my gradle settings')
        self.source('setup_runtime; clean_reset_unlocked')
        self.assertFalse(self.sdk.exists())
        self.assertFalse((self.home / '.local/bin/flutter').exists())
        self.assertFalse((self.home / '.local/bin/dart').exists())
        self.assertEqual(settings.read_text(), 'my gradle settings')

    def test_busy_flutter_lock_blocks_clean_and_releases_other_locks(self):
        self.save_selection('flutter\n')
        lock = self.state / 'locks/flutter.lock'
        lock.mkdir(parents=True)
        (lock / 'pid').write_text(str(os.getpid()))
        code, output = self.interact('clean', [b'y\n'], b'Continue? [y/N] ')
        self.assertEqual(code, 1, output.decode())
        self.assertTrue(lock.exists())
        for name in ('first-run', 'core', 'code', 'brave', 'codex', 'claude'):
            self.assertFalse((self.state / 'locks' / (name + '.lock')).exists())


if __name__ == '__main__':
    unittest.main()
