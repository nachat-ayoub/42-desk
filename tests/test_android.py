"""Exercise the embedded Android installer and launchers with offline SDK archives."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
import zipfile

import test_programs as helpers


class AndroidTests(unittest.TestCase):
    write_executable = staticmethod(helpers.ProgramTests.write_executable)
    write_platform = helpers.ProgramTests.write_platform
    run_desk = helpers.ProgramTests.run_desk
    source = helpers.ProgramTests.source
    save_selection = helpers.ProgramTests.save_selection

    def setUp(self):
        helpers.ProgramTests.setUp(self)
        self.android = self.storage / 'apps/android'
        self.image = self.android / 'sdk/system-images/android-30/google_apis_playstore/x86_64'
        self.avd = self.android / 'avd/Android_11_Play_Pixel9.avd'
        self.repo = 'https://dl.google.com/android/repository/'
        self.image_repo = self.repo + 'sys-img/google_apis_playstore/'
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
        emulator = '''#!/usr/bin/env python3
import json, os, pathlib, sys
if '-accel-check' in sys.argv:
    print('KVM denied' if os.environ.get('DESK_TEST_NO_KVM') else 'KVM usable')
    sys.exit(1 if os.environ.get('DESK_TEST_NO_KVM') else 0)
root = pathlib.Path(os.environ['DESK_FIXTURE'])
(root / 'android-launch.json').write_text(json.dumps({
    'args': sys.argv[1:],
    'environment': {key: os.environ.get(key) for key in (
        'ANDROID_HOME', 'ANDROID_AVD_HOME', 'ANDROID_USER_HOME',
        'ANDROID_EMULATOR_HOME', 'ANDROID_SDK_HOME', 'XDG_CONFIG_HOME',
        'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME', 'TMPDIR',
        'MESA_SHADER_CACHE_DIR', '__GL_SHADER_DISK_CACHE_PATH')}
}))
'''
        self.archives = {
            'emulator': self.make_zip('emulator.zip', {'emulator/emulator': emulator}),
            'platform-tools': self.make_zip('platform-tools.zip', {'platform-tools/adb': '#!/bin/sh\nexit 1\n'}),
            'image': self.make_zip('image.zip', {
                'x86_64/system.img': 'system', 'x86_64/userdata.img': 'userdata',
                'x86_64/ramdisk.img': 'ramdisk', 'x86_64/kernel-ranchu': 'kernel',
            }),
        }
        self.write_metadata()

    def make_zip(self, name, entries):
        target = self.root / name
        with zipfile.ZipFile(target, 'w') as archive:
            for path, text in entries.items():
                info = zipfile.ZipInfo(path)
                info.external_attr = 0o100755 << 16
                archive.writestr(info, text)
        return target

    def write_metadata(self, revision=1):
        def package(path, archive):
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            return f'''<remotePackage path="{path}"><revision><major>{revision}</major></revision>
<channelRef ref="channel-0"/><archives><archive><host-os>linux</host-os><complete>
<size>{archive.stat().st_size}</size><checksum type="sha256">{digest}</checksum>
<url>{archive.name}</url></complete></archive></archives></remotePackage>'''
        tools = self.root / 'repository.xml'
        tools.write_text('<repository>' + ''.join(package(key, self.archives[key])
                         for key in ('emulator', 'platform-tools')) + '</repository>')
        image = self.root / 'images.xml'
        image.write_text('<repository>' + package('system-images;android-30;google_apis_playstore;x86_64',
                         self.archives['image']) + '</repository>')
        urls = {self.repo + 'repository2-1.xml': str(tools),
                self.image_repo + 'sys-img2-1.xml': str(image)}
        for key, archive in self.archives.items():
            urls[(self.image_repo if key == 'image' else self.repo) + archive.name] = str(archive)
        (self.root / 'urls.json').write_text(json.dumps(urls))

    def install(self):
        return self.run_desk('install', 'android')

    def test_fresh_install_has_play_store_pixel9_display_and_no_home_sdk(self):
        result = self.install()
        self.assertIn('Android 11 Google Play', result.stdout)
        self.assertEqual((self.state / 'programs').read_text(), 'android\n')
        self.assertTrue((self.home / '.local/bin/android').is_file())
        self.assertTrue((self.home / '.local/share/applications/android-desk.desktop').is_file())
        self.assertIn('unalias android', (self.home / '.bashrc').read_text())
        config = (self.avd / 'config.ini').read_text()
        for line in ('PlayStore.enabled=true', 'hw.lcd.width=1080', 'hw.lcd.height=2424',
                     'hw.lcd.density=420', 'hw.ramSize=2048', 'tag.id=google_apis_playstore'):
            self.assertIn(line, config)
        self.assertFalse((self.home / '.android').exists())
        self.assertFalse((self.home / 'Android').exists())
        self.assertFalse(list((self.android / 'downloads').glob('*.zip')))
        self.assertFalse((self.root / 'android-launch.json').exists())

    def test_repeat_and_shell_startup_reuse_installed_device_without_network(self):
        self.install()
        (self.avd / 'user-app-data').write_text('keep my apps')
        (self.android / '.installed-version').unlink()
        requests = (self.root / 'requests').read_text()
        (self.root / 'offline').touch()
        self.run_desk('p')
        self.source('setup_runtime; shell_prepare_component android')
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertEqual((self.avd / 'user-app-data').read_text(), 'keep my apps')

    def test_existing_sdk_is_reused_when_only_play_image_is_missing(self):
        self.install()
        import shutil
        shutil.rmtree(self.image)
        (self.root / 'requests').unlink()
        self.run_desk('p')
        requests = (self.root / 'requests').read_text()
        self.assertNotIn('repository2-1.xml', requests)
        self.assertNotIn('/emulator.zip', requests)
        self.assertIn('/image.zip', requests)

    def test_corrupt_image_is_rejected_without_publishing_an_image_or_device(self):
        self.archives['image'].write_bytes(b'corrupt archive')
        result = self.run_desk('install', 'android', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertFalse((self.image / 'system.img').exists())
        self.assertFalse(self.avd.exists())

    def test_archive_cannot_escape_goinfre_staging_directory(self):
        self.make_zip('image.zip', {'../escaped': 'bad', 'x86_64/system.img': 'system'})
        self.write_metadata()
        result = self.run_desk('install', 'android', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsafe ZIP entry', result.stderr)
        self.assertFalse((self.android / 'tmp/escaped').exists())
        self.assertFalse(self.image.exists())

    def test_detached_launch_preserves_args_and_redirects_all_runtime_storage(self):
        self.install()
        requests = (self.root / 'requests').read_text()
        (self.root / 'offline').touch()
        self.run_desk('open', 'android')
        record = self.root / 'android-launch.json'
        deadline = time.monotonic() + 5
        while not record.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        launch = json.loads(record.read_text())
        self.assertEqual(launch['args'][:2], ['-avd', 'Android_11_Play_Pixel9'])
        self.assertIn('5584', launch['args'])
        self.assertIn('-no-snapshot', launch['args'])
        for key, value in launch['environment'].items():
            self.assertTrue(Path(value).is_relative_to(self.android), (key, value))
        self.assertEqual((self.root / 'requests').read_text(), requests)
        record.unlink()
        self.run_desk('android', '-no-window', '-dns-server', '1.1.1.1')
        deadline = time.monotonic() + 5
        while not record.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(json.loads(record.read_text())['args'][-3:], ['-no-window', '-dns-server', '1.1.1.1'])

    def test_kvm_failure_is_reported_before_detaching(self):
        self.install()
        self.env['DESK_TEST_NO_KVM'] = '1'
        result = self.run_desk('android', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('/dev/kvm', result.stderr)
        self.assertFalse((self.root / 'android-launch.json').exists())

    def test_explicit_update_checks_revisions_but_keeps_guest_data(self):
        self.install()
        (self.avd / 'userdata-qemu.img').write_text('guest apps')
        original = (self.avd / 'config.ini').read_bytes()
        self.write_metadata(revision=2)
        self.run_desk('update', 'android')
        marker = json.loads((self.image / '.goinfre-package.json').read_text())
        self.assertEqual(marker['revision'], [2, 0, 0])
        self.assertEqual((self.avd / 'userdata-qemu.img').read_text(), 'guest apps')
        self.assertEqual((self.avd / 'config.ini').read_bytes(), original)
        self.assertFalse((self.root / 'android-launch.json').exists())

    def test_updates_skip_a_running_shared_sdk_without_network(self):
        self.install()
        requests = (self.root / 'requests').read_text()
        result = self.source('android_running() { return 0; }; main update android')
        self.assertIn('Close all emulators', result.stderr)
        self.assertEqual((self.root / 'requests').read_text(), requests)

    def test_clean_preserves_google_account_and_device_storage(self):
        self.install()
        data = self.avd / 'userdata-qemu.img'
        data.write_text('Google account and apps')
        self.source('setup_runtime; clean_reset_unlocked')
        self.assertEqual(data.read_text(), 'Google account and apps')
        self.assertTrue((self.image / 'system.img').exists())
        self.assertFalse((self.home / '.local/bin/android').exists())
        self.assertFalse((self.home / '.local/share/applications/android-desk.desktop').exists())

    def test_android_selection_is_persisted_and_reported_without_launching(self):
        self.install()
        result = self.run_desk('st')
        self.assertIn('Android 11 Google Play', result.stdout)
        self.assertIn('API 30, Google Play', result.stdout)
        self.run_desk('install', 'none')
        self.assertTrue((self.avd / 'config.ini').exists())
        self.assertFalse((self.root / 'android-launch.json').exists())

    def test_local_bootstrap_installs_adjacent_script_without_network(self):
        (self.root / 'offline').touch()
        installer = helpers.DESK.parent / 'install.sh'
        result = subprocess.run([str(installer)], env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(helpers.DESK.read_text().split('VERSION="', 1)[1].split('"', 1)[0], (self.home / '.local/bin/desk').read_text())
        self.assertFalse((self.root / 'requests').exists())
        self.assertFalse(list((self.storage / 'cache/desk/tmp').iterdir()))


if __name__ == '__main__':
    unittest.main()
