"""Separate Android tablet profile, shared SDK, and game/runtime diagnostics."""

import json
from pathlib import Path
import time
import unittest

import test_android as android_helpers
import test_programs as helpers


class AndroidTabletTests(unittest.TestCase):
    write_executable = staticmethod(helpers.ProgramTests.write_executable)
    write_platform = helpers.ProgramTests.write_platform
    run_desk = helpers.ProgramTests.run_desk
    source = helpers.ProgramTests.source
    save_selection = helpers.ProgramTests.save_selection
    interact = helpers.ProgramTests.interact
    make_zip = android_helpers.AndroidTests.make_zip
    write_metadata = android_helpers.AndroidTests.write_metadata

    def setUp(self):
        android_helpers.AndroidTests.setUp(self)
        self.tablet = self.android / 'avd/Android_11_Play_Tablet.avd'

    def install(self):
        return self.run_desk('install', 'android-tablet')

    def read_launch(self):
        record = self.root / 'android-launch.json'
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                return json.loads(record.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.02)
        return json.loads(record.read_text())

    def fake_running_device(self, name='Android_11_Play_Tablet'):
        self.write_executable(self.android / 'sdk/platform-tools/adb', '''#!/usr/bin/env python3
import sys
args=sys.argv[1:]
if args[-1:] == ['get-state']:print('device')
elif args[-3:] == ['emu','avd','name']:print(AVD_NAME);print('OK')
elif 'getprop' in args:
 values={'ro.build.version.release':'11','ro.build.version.sdk':'30',
         'ro.product.cpu.abilist':'x86_64,arm64-v8a,x86,armeabi-v7a',
         'ro.dalvik.vm.native.bridge':'libndk_translation.so','ro.hardware.egl':'emulation'}
 print(values.get(args[-1],''))
elif args[-3:]==['pm','list','features']:
 print('feature:android.hardware.vulkan.level=1')
 print('feature:android.hardware.vulkan.version=4198400')
elif args[-3:-1]==['pm','path']:print('package:/system/app/'+args[-1]+'/base.apk')
else:sys.exit(1)
'''.replace('AVD_NAME', repr(name)))

    def test_tablet_installs_google_play_with_ipad_like_display_and_game_settings(self):
        self.install()
        config = (self.tablet / 'config.ini').read_text()
        for setting in ('hw.lcd.width=1640', 'hw.lcd.height=2360', 'hw.lcd.density=320',
                        'PlayStore.enabled=true', 'target=android-30', 'tag.id=google_apis_playstore',
                        'hw.ramSize=2048', 'hw.cpu.ncore=2', 'vm.heapSize=512',
                        'disk.dataPartition.size=16G', 'hw.gpu.enabled=yes', 'hw.gpu.mode=auto',
                        'hw.audioOutput=yes', 'hw.touchScreen=multi-touch', 'hw.accelerometer=yes'):
            self.assertIn(setting, config)
        self.assertFalse(self.avd.exists())
        self.assertFalse((self.android / '.installed-version').exists())
        self.assertTrue((self.android / '.installed-version-tablet').is_file())
        self.assertTrue((self.home / '.local/bin/android-tablet').is_file())
        self.assertTrue((self.home / '.local/share/applications/android-tablet-desk.desktop').is_file())
        self.assertFalse((self.home / '.local/bin/android').exists())
        self.assertFalse((self.root / 'android-launch.json').exists())
        self.assertEqual((self.state / 'programs').read_text(), 'android-tablet\n')
        self.assertFalse((self.home / '.android').exists())
        self.assertFalse((self.home / 'Android').exists())

    def test_checkbox_can_select_only_tablet_and_aliases_normalize(self):
        status, output = self.interact('install', [b'n' + b'\x1b[B' * 13 + b' \r'])
        self.assertEqual(status, 0, output.decode())
        self.assertIn(b'Google Play Tablet', output)
        self.assertEqual((self.state / 'programs').read_text(), 'android-tablet\n')
        self.run_desk('install', 'tablet')
        self.assertIn('Android 11 Google Play Tablet', self.run_desk('st').stdout)

    def test_adding_tablet_reuses_phone_sdk_offline_without_changing_phone_data(self):
        self.run_desk('install', 'android')
        phone_config = (self.avd / 'config.ini').read_bytes()
        phone_ini = (self.android / 'avd/Android_11_Play_Pixel9.ini').read_bytes()
        (self.avd / 'userdata-qemu.img').write_text('phone games and Google account')
        requests = (self.root / 'requests').read_text()
        (self.root / 'offline').touch()
        self.install()
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertEqual((self.avd / 'config.ini').read_bytes(), phone_config)
        self.assertEqual((self.android / 'avd/Android_11_Play_Pixel9.ini').read_bytes(), phone_ini)
        self.assertEqual((self.avd / 'userdata-qemu.img').read_text(), 'phone games and Google account')
        self.assertTrue((self.tablet / 'config.ini').is_file())

    def test_adding_phone_after_tablet_does_not_download_another_system_image(self):
        self.install()
        requests = (self.root / 'requests').read_text()
        original = (self.tablet / 'config.ini').read_bytes()
        (self.root / 'offline').touch()
        self.run_desk('install', 'android', 'android-tablet')
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertEqual((self.tablet / 'config.ini').read_bytes(), original)
        self.assertTrue((self.avd / 'config.ini').is_file())
        self.assertEqual(requests.count('/image.zip'), 1)

    def test_tablet_can_be_created_with_complete_shared_sdk_while_phone_is_running(self):
        self.run_desk('install', 'android')
        (self.root / 'offline').touch()
        self.source('android_running() { return 0; }; main install android-tablet')
        self.assertTrue((self.tablet / 'config.ini').is_file())

    def test_repeat_and_background_maintenance_keep_existing_games_offline(self):
        self.install()
        (self.tablet / 'userdata-qemu.img').write_text('tablet games')
        config = (self.tablet / 'config.ini').read_bytes()
        requests = (self.root / 'requests').read_text()
        (self.root / 'offline').touch()
        self.run_desk('p')
        self.source('setup_runtime; shell_prepare_component android-tablet')
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertEqual((self.tablet / 'config.ini').read_bytes(), config)
        self.assertEqual((self.tablet / 'userdata-qemu.img').read_text(), 'tablet games')

    def test_gaming_launch_keeps_audio_and_vulkan_available_and_uses_its_own_port(self):
        self.install()
        self.run_desk('open', 'android-tablet')
        launch = self.read_launch()
        self.assertEqual(launch['args'][:2], ['-avd', 'Android_11_Play_Tablet'])
        self.assertIn('5586', launch['args'])
        self.assertNotIn('5584', launch['args'])
        self.assertNotIn('-no-audio', launch['args'])
        self.assertNotIn('-Vulkan', launch['args'])
        self.assertIn('-accel', launch['args'])
        self.assertIn('-no-snapshot', launch['args'])
        for key, value in launch['environment'].items():
            self.assertTrue(Path(value).is_relative_to(self.android), (key, value))
        self.assertEqual((self.state / 'open-programs').read_text(), 'android-tablet\n')

    def test_phone_and_tablet_launch_together_with_different_devices_and_ports(self):
        self.run_desk('install', 'android', 'android-tablet')
        self.write_executable(self.android / 'sdk/emulator/emulator', '''#!/usr/bin/env python3
import json,os,pathlib,sys
if '-accel-check' in sys.argv:sys.exit(0)
with pathlib.Path(os.environ['DESK_FIXTURE'],'launches').open('a') as stream:
 stream.write(json.dumps(sys.argv[1:])+'\\n')
''')
        self.run_desk('open', 'android', 'android-tablet')
        path = self.root / 'launches'
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            lines = path.read_text().splitlines() if path.exists() else []
            if len(lines) == 2:
                break
            time.sleep(0.02)
        launches = [json.loads(line) for line in lines]
        self.assertEqual(len(launches), 2)
        by_name = {args[1]: args for args in launches}
        phone = by_name['Android_11_Play_Pixel9']
        tablet = by_name['Android_11_Play_Tablet']
        self.assertEqual(phone[phone.index('-port') + 1], '5584')
        self.assertEqual(tablet[tablet.index('-port') + 1], '5586')
        self.assertIn('-no-audio', phone)
        self.assertNotIn('-no-audio', tablet)

    def test_tablet_memory_cpu_graphics_overrides_and_arguments_are_forwarded(self):
        self.install()
        self.env.update(DESK_ANDROID_TABLET_MEMORY='4096', DESK_ANDROID_TABLET_CORES='4', DESK_ANDROID_TABLET_GPU='host')
        self.run_desk('android-tablet', '-no-window')
        args = self.read_launch()['args']
        self.assertEqual(args[args.index('-memory') + 1], '4096')
        self.assertEqual(args[args.index('-cores') + 1], '4')
        self.assertEqual(args[args.index('-gpu') + 1], 'host')
        self.assertEqual(args[-1], '-no-window')

    def test_invalid_game_resource_settings_fail_before_launching_or_downloading(self):
        for key, value in (('DESK_ANDROID_TABLET_MEMORY', '1024'), ('DESK_ANDROID_TABLET_MEMORY', '8193'),
                           ('DESK_ANDROID_TABLET_MEMORY', 'abc'), ('DESK_ANDROID_TABLET_CORES', '9'),
                           ('DESK_ANDROID_TABLET_CORES', '-1')):
            with self.subTest(key=key, value=value):
                self.env.pop('DESK_ANDROID_TABLET_MEMORY', None)
                self.env.pop('DESK_ANDROID_TABLET_CORES', None)
                self.env[key] = value
                result = self.run_desk('android-tablet', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(key, result.stderr)
                self.assertFalse((self.root / 'requests').exists())
                self.assertFalse((self.root / 'android-launch.json').exists())

    def test_existing_tablet_is_detected_and_reserved_port_collision_is_refused(self):
        self.install()
        self.fake_running_device()
        self.assertIn('already running', self.run_desk('android-tablet').stdout)
        self.assertFalse((self.root / 'android-launch.json').exists())
        self.fake_running_device('Different_AVD')
        result = self.run_desk('android-tablet', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Port 5586 belongs', result.stderr)
        self.assertFalse((self.root / 'android-launch.json').exists())

    def test_game_doctor_reads_android_abi_play_services_and_gpu_without_changing_data(self):
        self.install()
        self.fake_running_device()
        (self.tablet / 'userdata-qemu.img').write_text('keep game progress')
        result = self.run_desk('android-tablet', '--doctor')
        for value in ('Android: 11', 'API level: 30', 'arm64-v8a', 'libndk_translation.so',
                      'Google Play Store: installed', 'Google Play services: installed', 'vulkan', 'emulator-5586'):
            self.assertIn(value, result.stdout)
        self.assertEqual((self.tablet / 'userdata-qemu.img').read_text(), 'keep game progress')
        self.assertFalse((self.root / 'android-launch.json').exists())

    def test_missing_device_doctor_never_installs_and_kvm_failure_blocks_launch(self):
        result = self.run_desk('android-tablet', '--doctor', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'requests').exists())
        self.install()
        self.env['DESK_TEST_NO_KVM'] = '1'
        result = self.run_desk('android-tablet', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('/dev/kvm', result.stderr)
        self.assertFalse((self.root / 'android-launch.json').exists())

    def test_early_graphics_failure_is_reported_instead_of_silent_launch_success(self):
        self.install()
        self.write_executable(self.android / 'sdk/emulator/emulator', '''#!/bin/sh
[ "$1" != -accel-check ] || exit 0
echo 'Cannot initialize host GPU' >&2
exit 7
''')
        result = self.run_desk('android-tablet', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('exited during startup', result.stderr)
        self.assertIn('Cannot initialize host GPU', result.stderr)
        self.assertIn('Cannot initialize host GPU', (self.android / 'logs/launch-tablet.log').read_text())

    def test_updating_shared_image_preserves_both_devices_and_running_emulators_postpone_it(self):
        self.run_desk('install', 'android', 'android-tablet')
        originals = {}
        for device in (self.avd, self.tablet):
            originals[device] = (device / 'config.ini').read_bytes()
            (device / 'userdata-qemu.img').write_text(device.name)
        self.write_metadata(revision=2)
        self.run_desk('update', 'android-tablet')
        marker = json.loads((self.image / '.goinfre-package.json').read_text())
        self.assertEqual(marker['revision'], [2, 0, 0])
        for device, config in originals.items():
            self.assertEqual((device / 'config.ini').read_bytes(), config)
            self.assertEqual((device / 'userdata-qemu.img').read_text(), device.name)
        requests = (self.root / 'requests').read_text()
        result = self.source('android_running() { return 0; }; main update android-tablet')
        self.assertIn('Close all emulators', result.stderr)
        self.assertEqual((self.root / 'requests').read_text(), requests)

    def test_clean_preserves_both_avds_game_progress_and_shared_image(self):
        self.run_desk('install', 'android', 'android-tablet')
        for device in (self.avd, self.tablet):
            (device / 'userdata-qemu.img').write_text('keep ' + device.name)
        self.source('setup_runtime; clean_reset_unlocked')
        for device in (self.avd, self.tablet):
            self.assertEqual((device / 'userdata-qemu.img').read_text(), 'keep ' + device.name)
        for name in ('android', 'android-tablet'):
            self.assertFalse((self.home / '.local/bin' / name).exists())
            self.assertFalse((self.home / '.local/share/applications' / (name + '-desk.desktop')).exists())
        self.assertTrue((self.image / 'system.img').is_file())
