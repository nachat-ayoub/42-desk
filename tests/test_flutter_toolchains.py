"""Verify explicit target preparation, interactive licences, and runtime bindings."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time
import unittest
import zipfile

import test_flutter as flutter_helpers


class FlutterToolchainTests(unittest.TestCase):
    write_executable = staticmethod(flutter_helpers.FlutterTests.write_executable)
    write_platform = flutter_helpers.FlutterTests.write_platform
    run_desk = flutter_helpers.FlutterTests.run_desk
    source = flutter_helpers.FlutterTests.source
    save_selection = flutter_helpers.FlutterTests.save_selection
    interact = flutter_helpers.FlutterTests.interact
    make_release = flutter_helpers.FlutterTests.make_release
    write_manifest = flutter_helpers.FlutterTests.write_manifest
    install = flutter_helpers.FlutterTests.install

    def setUp(self):
        flutter_helpers.FlutterTests.setUp(self)
        self.install()
        self.android = self.storage / 'apps/android'
        self.jdk = self.root / 'system jdk'
        self.write_executable(self.jdk / 'bin/java', '#!/bin/sh\necho \'openjdk version "21.0.1"\' >&2\n')
        self.write_executable(self.jdk / 'bin/javac', '#!/bin/sh\nexit 0\n')
        self.env['JAVA_HOME'] = str(self.jdk)
        self.sdk_repo = 'https://dl.google.com/android/repository/'
        self.manager_script = '''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['DESK_FIXTURE'])
sdk = pathlib.Path(os.environ['ANDROID_HOME'])
args = sys.argv[1:]
record = {'args': args, 'JAVA_HOME': os.environ.get('JAVA_HOME'),
          'ANDROID_USER_HOME': os.environ.get('ANDROID_USER_HOME'),
          'TMPDIR': os.environ.get('TMPDIR')}
if '--licenses' in args:
    record['input'] = sys.stdin.read()
    if 'y' not in record['input']:
        (root / 'licences-pending').touch()
with (root / 'sdkmanager-calls').open('a') as stream:
    stream.write(json.dumps(record) + '\\n')
if '--install' in args and not (root / 'licences-pending').exists():
    for arg in args[args.index('--install') + 1:]:
        if arg.startswith('platforms;'):
            file = sdk / arg.replace(';', '/') / 'android.jar'
        elif arg.startswith('build-tools;'):
            file = sdk / arg.replace(';', '/') / 'aapt'
        else:
            file = sdk / 'platform-tools/adb'
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('fixture')
        file.chmod(0o755)
'''
        self.cmdline_zip = self.root / 'commandlinetools.zip'
        self.write_cmdline_zip()
        self.write_sdk_metadata()
        for name in ('clang++', 'cmake', 'eglinfo'):
            self.write_executable(self.bin / name, '#!/bin/sh\nexit 0\n')
        self.write_executable(self.bin / 'pkg-config', '#!/bin/sh\n[ -z "$DESK_TEST_MISSING_GTK" ]\n')
        self.ninja = self.flutter / 'tools/ninja/bin/ninja'
        self.write_ninja_fixture()

    def add_url(self, url, path):
        file = self.root / 'urls.json'
        urls = json.loads(file.read_text())
        urls[url] = str(path)
        file.write_text(json.dumps(urls))

    def write_cmdline_zip(self, unsafe=False):
        with zipfile.ZipFile(self.cmdline_zip, 'w') as archive:
            for name, data in {
                'cmdline-tools/bin/sdkmanager': self.manager_script,
                'cmdline-tools/source.properties': 'Pkg.Revision=19.0',
                **({'../escape': 'bad'} if unsafe else {}),
            }.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = 0o100755 << 16
                archive.writestr(info, data)

    def write_sdk_metadata(self):
        metadata = self.root / 'sdk-repository.xml'
        metadata.write_text('''<repository><remotePackage path="cmdline-tools;19.0">
<revision><major>19</major></revision><channelRef ref="channel-0"/>
<archives><archive><host-os>linux</host-os><complete><size>SIZE</size>
<checksum type="sha256">SHA</checksum><url>commandlinetools.zip</url>
</complete></archive></archives></remotePackage></repository>'''
                            .replace('SIZE', str(self.cmdline_zip.stat().st_size))
                            .replace('SHA', hashlib.sha256(self.cmdline_zip.read_bytes()).hexdigest()))
        self.add_url(self.sdk_repo + 'repository2-1.xml', metadata)
        self.add_url(self.sdk_repo + 'commandlinetools.zip', self.cmdline_zip)

    def write_ninja_fixture(self, unsafe=False):
        wheel = self.root / 'ninja.whl'
        with zipfile.ZipFile(wheel, 'w') as archive:
            info = zipfile.ZipInfo('ninja-1.13.2.data/scripts/ninja')
            info.external_attr = 0o100755 << 16
            archive.writestr(info, '#!/bin/sh\necho 1.13.2\n')
            if unsafe:
                archive.writestr('../escape', 'bad')
        metadata = self.root / 'ninja.json'
        metadata.write_text(json.dumps({'urls': [{
            'filename': 'ninja-1.13.2-py3-none-manylinux2014_x86_64.whl',
            'url': 'https://files.pythonhosted.org/fixtures/ninja.whl',
            'digests': {'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest()},
        }]}))
        self.add_url('https://pypi.org/pypi/ninja/json', metadata)
        self.add_url('https://files.pythonhosted.org/fixtures/ninja.whl', wheel)
        self.ninja_archive = wheel

    def calls(self):
        return [json.loads(line) for line in (self.root / 'sdkmanager-calls').read_text().splitlines()]

    def test_android_installs_only_build_dependencies_and_preserves_selection(self):
        self.run_desk('flutter-setup', 'android', input='y\n')
        self.assertEqual((self.state / 'programs').read_text(), 'flutter\n')
        self.assertFalse((self.android / 'sdk/emulator').exists())
        self.assertFalse((self.android / 'sdk/system-images').exists())
        self.assertTrue((self.android / 'sdk/platforms/android-36/android.jar').is_file())
        self.assertTrue((self.android / 'sdk/build-tools/36.0.0/aapt').is_file())
        self.assertIn('export FLUTTER_ROOT=', (self.home / '.bashrc').read_text())
        calls = self.calls()
        self.assertEqual(calls[0]['input'], 'y\n')
        self.assertEqual(calls[1]['args'], [
            '--sdk_root=' + str(self.android / 'sdk'), '--install',
            'platforms;android-36', 'build-tools;36.0.0', 'platform-tools'])
        self.assertEqual(calls[0]['JAVA_HOME'], str(self.jdk))
        self.assertEqual(calls[0]['ANDROID_USER_HOME'], str(self.android / 'state/.android'))
        self.assertTrue(Path(calls[0]['TMPDIR']).is_relative_to(self.flutter))
        self.assertFalse((self.home / '.android').exists())

    def test_all_prepares_each_target_without_changing_saved_program_choices(self):
        self.write_executable(self.storage / 'apps/brave/brave', '#!/bin/sh\nexit 0\n')
        self.write_executable(self.ninja, '#!/bin/sh\nexit 0\n')
        self.run_desk('flutter-setup', 'all', input='y\n')
        self.assertEqual((self.state / 'programs').read_text(), 'flutter\n')
        self.assertIn('export ANDROID_HOME=', (self.home / '.bashrc').read_text())
        self.assertIn('export CHROME_EXECUTABLE=', (self.home / '.bashrc').read_text())
        self.assertTrue((self.android / 'sdk/platforms/android-36/android.jar').exists())

    def test_target_checklist_can_choose_web_without_installing_android(self):
        self.write_executable(self.storage / 'apps/brave/brave', '#!/bin/sh\nexit 0\n')
        code, output = self.interact('flutter-setup', [b'nj \r'])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b'Web (Brave / Chrome)', output)
        self.assertFalse((self.android / 'sdk').exists())
        self.assertEqual((self.state / 'programs').read_text(), 'flutter\n')

    def test_android_reuses_existing_adb_and_emulator_data(self):
        adb = self.android / 'sdk/platform-tools/adb'
        self.write_executable(adb, '#!/bin/sh\nexit 0\n')
        data = self.android / 'avd/device-data'
        data.parent.mkdir(parents=True)
        data.write_text('keep')
        self.run_desk('flutter-setup', 'android', input='y\n')
        self.assertNotIn('platform-tools', self.calls()[1]['args'])
        self.assertEqual(data.read_text(), 'keep')
        self.assertEqual(adb.read_text(), '#!/bin/sh\nexit 0\n')

    def test_android_repeat_needs_no_network_or_licence_input(self):
        self.run_desk('flutter-setup', 'android', input='y\n')
        requests = (self.root / 'requests').read_text()
        calls = self.calls()
        (self.root / 'offline').touch()
        self.run_desk('flutter-setup', 'android')
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertEqual(self.calls(), calls)

    def test_declining_licences_does_not_claim_a_ready_toolchain(self):
        result = self.run_desk('flutter-setup', 'android', input='n\n', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('licence prompts', result.stderr)
        self.assertEqual(self.calls()[0]['input'], 'n\n')
        self.assertFalse((self.android / 'sdk/platforms').exists())

    def test_external_sdk_is_not_modified(self):
        self.env['ANDROID_HOME'] = str(self.root / 'external-sdk')
        result = self.run_desk('flutter-setup', 'android', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('external Android SDK', result.stderr)
        self.assertFalse((self.root / 'external-sdk').exists())
        self.assertFalse((self.android / 'sdk').exists())

    def test_external_sdk_root_also_supplies_android_home_for_builds(self):
        external = self.root / 'external sdk'
        self.env['ANDROID_SDK_ROOT'] = str(external)
        self.run_desk('flutter', 'run')
        env = json.loads((self.root / 'flutter-launch.json').read_text())['environment']
        self.assertEqual(env['ANDROID_HOME'], str(external))
        self.assertEqual(env['ANDROID_SDK_ROOT'], str(external))

    def test_vscode_inherits_flutter_sdk_and_caches_without_changing_its_profile(self):
        self.write_executable(self.android / 'sdk/platform-tools/adb', '#!/bin/sh\nexit 0\n')
        self.write_executable(self.storage / 'apps/vscode/bin/code', '''#!/usr/bin/env python3
import json, os, pathlib, sys
record = {'args': sys.argv[1:], 'env': {name: os.environ.get(name) for name in (
    'ANDROID_HOME', 'ANDROID_SDK_ROOT', 'ADB_SERVER_SOCKET', 'FLUTTER_ROOT',
    'PUB_CACHE', 'GRADLE_USER_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'TMPDIR')}}
(pathlib.Path(os.environ['DESK_FIXTURE']) / 'vscode-launch.json').write_text(json.dumps(record))
''')
        self.run_desk('code', 'project with spaces')
        record = self.root / 'vscode-launch.json'
        deadline = time.monotonic() + 5
        while not record.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        launch = json.loads(record.read_text())
        env = launch['env']
        self.assertEqual(env['ANDROID_HOME'], str(self.android / 'sdk'))
        self.assertEqual(env['ANDROID_SDK_ROOT'], str(self.android / 'sdk'))
        self.assertEqual(env['ADB_SERVER_SOCKET'], 'tcp:localhost:5038')
        self.assertEqual(env['FLUTTER_ROOT'], str(self.sdk))
        self.assertEqual(env['PUB_CACHE'], str(self.flutter / 'cache/pub'))
        self.assertEqual(env['GRADLE_USER_HOME'], str(self.flutter / 'cache/gradle'))
        self.assertEqual(env['XDG_CONFIG_HOME'], self.env['XDG_CONFIG_HOME'])
        self.assertEqual(env['TMPDIR'], str(self.storage / 'cache/vscode/tmp'))
        self.assertEqual(env['XDG_CACHE_HOME'], str(self.storage / 'cache/vscode/xdg'))
        self.assertEqual(launch['args'][-1], 'project with spaces')

    def test_shell_hook_exposes_emulator_sdk_even_without_cmdline_tools(self):
        self.write_executable(self.android / 'sdk/platform-tools/adb', '#!/bin/sh\nexit 0\n')
        self.source('setup_runtime; write_shell_hook')
        result = subprocess.run(['bash', '--noprofile', '--norc', '-c',
                                 'source "$HOME/.bashrc"; printf "%s\\n" "$ANDROID_HOME" "$ANDROID_SDK_ROOT" "$ADB_SERVER_SOCKET"'],
                                env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [str(self.android / 'sdk'), str(self.android / 'sdk'),
                                                     'tcp:localhost:5038'])

    def test_env_command_supplies_sdk_discovery_to_a_project_script(self):
        self.write_executable(self.android / 'sdk/platform-tools/adb', '#!/bin/sh\nexit 0\n')
        requests = (self.root / 'requests').read_text()
        result = subprocess.run(['bash', '-c', '''set -euo pipefail
desk_env=$("$DESK_SCRIPT" env flutter)
eval "$desk_env"
sdk_dir=""
for candidate in "${ANDROID_HOME:-}" "${ANDROID_SDK_ROOT:-}" "$HOME/Android/Sdk"; do
  if [[ -n "$candidate" && -x "$candidate/platform-tools/adb" ]]; then sdk_dir="$candidate"; break; fi
done
printf '%s\\n' "$sdk_dir" "$ADB_SERVER_SOCKET" "$PUB_CACHE" "$GRADLE_USER_HOME" "$TMPDIR"
'''], env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [str(self.android / 'sdk'), 'tcp:localhost:5038',
                                                     str(self.flutter / 'cache/pub'), str(self.flutter / 'cache/gradle'),
                                                     str(self.flutter / 'tmp')])
        self.assertEqual((self.root / 'requests').read_text(), requests)

    def test_env_command_quotes_shell_characters_in_external_sdk_paths(self):
        external = self.root / 'external; $(touch SHELL_INJECTION) sdk'
        self.env['ANDROID_SDK_ROOT'] = str(external)
        result = subprocess.run(['bash', '-c', '''set -euo pipefail
desk_env=$("$DESK_SCRIPT" env flutter)
eval "$desk_env"
printf '%s\\n' "$ANDROID_HOME" "$ANDROID_SDK_ROOT"
'''], cwd=self.root, env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [str(external), str(external)])
        self.assertFalse((self.root / 'SHELL_INJECTION').exists())

    def test_bad_cmdline_archive_is_rejected_without_modifying_the_sdk(self):
        self.cmdline_zip.write_bytes(b'bad')
        result = self.run_desk('flutter-setup', 'android', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertFalse((self.android / 'sdk/cmdline-tools/latest').exists())

    def test_brave_is_used_directly_for_flutter_web_and_explicit_override_is_preserved(self):
        brave = self.storage / 'apps/brave/brave'
        self.write_executable(brave, '#!/bin/sh\nexit 0\n')
        self.run_desk('flutter-setup', 'web')
        self.run_desk('flutter', 'doctor')
        env = json.loads((self.root / 'flutter-launch.json').read_text())['environment']
        self.assertEqual(env['CHROME_EXECUTABLE'], str(brave))
        self.assertNotEqual(env['CHROME_EXECUTABLE'], str(self.home / '.local/bin/brave'))
        custom = self.root / 'custom chrome'
        self.write_executable(custom, '#!/bin/sh\nexit 0\n')
        self.env['CHROME_EXECUTABLE'] = str(custom)
        self.run_desk('flutter', 'doctor')
        env = json.loads((self.root / 'flutter-launch.json').read_text())['environment']
        self.assertEqual(env['CHROME_EXECUTABLE'], str(custom))

    def test_linux_installs_verified_ninja_and_exposes_it_to_flutter(self):
        self.source('setup_runtime; install_flutter_tool ninja')
        self.assertTrue(os.access(self.ninja, os.X_OK))
        self.run_desk('flutter-setup', 'linux')
        self.run_desk('flutter', 'doctor')
        env = json.loads((self.root / 'flutter-launch.json').read_text())['environment']
        self.assertIn(str(self.ninja.parent), env['PATH'].split(os.pathsep))
        self.assertIn(str(self.ninja.parent), (self.home / '.bashrc').read_text().replace('\\ ', ' '))

    def test_linux_reports_system_libraries_that_need_admin_access(self):
        self.write_executable(self.ninja, '#!/bin/sh\nexit 0\n')
        self.env['DESK_TEST_MISSING_GTK'] = '1'
        result = self.run_desk('flutter-setup', 'linux', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('libgtk-3-dev', result.stderr)

    def test_ninja_checksum_and_zip_traversal_are_rejected(self):
        self.ninja_archive.write_bytes(b'bad')
        result = self.source('setup_runtime; install_flutter_tool ninja', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.write_ninja_fixture(unsafe=True)
        result = self.source('setup_runtime; install_flutter_tool ninja', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsafe Ninja ZIP', result.stderr)
        self.assertFalse((self.flutter / 'tools/ninja').exists())
        self.assertFalse((self.flutter / 'tmp/escape').exists())

    def test_invalid_target_prevents_all_dependency_work(self):
        requests = (self.root / 'requests').read_text()
        result = self.run_desk('flutter-setup', 'android', 'unknown', check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertFalse((self.android / 'sdk').exists())

    def test_explicit_invalid_java_home_is_preserved_and_explained(self):
        self.env['JAVA_HOME'] = str(self.root / 'invalid-jdk')
        result = self.run_desk('flutter-setup', 'android', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('JAVA_HOME must point', result.stderr)
        self.assertFalse((self.flutter / 'tools/jdk').exists())

    def test_portable_jdk_is_verified_and_used_by_future_flutter_commands(self):
        archive = self.root / 'jdk.tar.gz'
        with tarfile.open(archive, 'w:gz') as stream:
            for name in ('java', 'javac'):
                data = b'#!/bin/sh\necho \'openjdk version "21.0.1"\' >&2\n'
                info = tarfile.TarInfo('jdk-21/bin/' + name)
                info.size, info.mode = len(data), 0o755
                stream.addfile(info, io.BytesIO(data))
        metadata = self.root / 'jdk.json'
        metadata.write_text(json.dumps([{'binary': {'package': {
            'link': 'https://github.com/adoptium/temurin21-binaries/releases/download/fixture/jdk.tar.gz',
            'checksum': hashlib.sha256(archive.read_bytes()).hexdigest(),
        }}}]))
        self.add_url('https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=x64&heap_size=normal&image_type=jdk&jvm_impl=hotspot&os=linux&vendor=eclipse', metadata)
        self.add_url('https://github.com/adoptium/temurin21-binaries/releases/download/fixture/jdk.tar.gz', archive)
        self.env.pop('JAVA_HOME')
        self.write_executable(self.bin / 'java', '#!/bin/sh\necho \'openjdk version "11.0.1"\' >&2\n')
        self.write_executable(self.bin / 'javac', '#!/bin/sh\nexit 0\n')
        self.run_desk('flutter-setup', 'android', input='y\n')
        self.run_desk('flutter', 'doctor')
        env = json.loads((self.root / 'flutter-launch.json').read_text())['environment']
        self.assertEqual(env['JAVA_HOME'], str(self.flutter / 'tools/jdk'))


if __name__ == '__main__':
    unittest.main()
