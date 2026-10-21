"""Exercise signed official-package selection, rootless extraction, and launch."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from test_ai_apps import AppFixtures


@unittest.skipUnless(shutil.which('dpkg-deb'), 'Official Linux package tests require dpkg-deb')
class OfficialChatGPTTests(AppFixtures):
    root_url = 'https://persistent.oaistatic.com/codex-app-prod/linux'
    fingerprint = '3BFA0E4AE8B8CC16A2D9BA684A3B4A566C4660E4'

    def setUp(self):
        super().setUp()
        self.base = self.storage / 'apps/chatgpt'
        self.write_executable(self.bin / 'ps', '#!/bin/sh\necho bash\n')
        self.write_executable(self.bin / 'curl', '''#!/usr/bin/env python3
import json, os, pathlib, sys
root=pathlib.Path(os.environ['DESK_FIXTURE']); args=sys.argv[1:]
url=next(arg for arg in args if arg.startswith('https://'))
assert '--proto' in args and '--proto-redir' in args and '--tlsv1.2' in args
with (root/'requests').open('a') as stream:stream.write(url+'\\n')
if (root/'offline').exists():sys.exit(22)
source=json.loads((root/'urls.json').read_text()).get(url)
if source is None:sys.exit('Unexpected official URL: '+url)
pathlib.Path(args[args.index('-o')+1]).write_bytes(pathlib.Path(source).read_bytes())
''')
        self.write_executable(self.bin / 'gpg', '''#!/usr/bin/env python3
import os, pathlib, sys
root=pathlib.Path(os.environ['DESK_FIXTURE']); args=sys.argv[1:]
home=pathlib.Path(args[args.index('--homedir')+1])
assert home.name=='gnupg' and home.stat().st_mode & 0o777==0o700
assert '--no-auto-key-retrieve' in args and '--no-auto-key-import' in args and '--no-autostart' in args
with (root/'gpg-operations').open('a') as stream:stream.write(' '.join(args)+'\\n')
if '--show-keys' in args:
 print('pub::::::::::')
 print('fpr:::::::::'+('0'*40 if (root/'bad-key').exists() else 'FINGERPRINT')+':')
elif '--import' in args:pass
elif '--decrypt' in args:
 if (root/'bad-signature').exists():sys.exit(2)
 pathlib.Path(args[args.index('--output')+1]).write_bytes((root/'Release').read_bytes())
else:sys.exit('Unexpected GPG invocation')
'''.replace('FINGERPRINT', self.fingerprint))
        self.write_executable(self.bin / 'ldd', '''#!/usr/bin/env python3
import os, pathlib
root=pathlib.Path(os.environ['DESK_FIXTURE'])
print('librequired.so => not found' if (root/'missing-library').exists() else 'libc.so.6 => /lib/libc.so.6')
''')
        self.make_release('26.1016.51333')

    def make_release(self, version, arch='amd64', bad_url=False):
        payload = self.root / ('package-' + version + '-' + arch)
        control = payload / 'DEBIAN'
        control.mkdir(parents=True, exist_ok=True)
        control.chmod(0o755)
        (control / 'control').write_text(f'Package: chatgpt\nVersion: {version}\nArchitecture: {arch}\nMaintainer: OpenAI <support@openai.com>\nDescription: Official fixture\nInstalled-Size: 32\n')
        (control / 'control').chmod(0o644)
        self.write_executable(control / 'postinst', '#!/bin/sh\ntouch "$DESK_FIXTURE/maintainer-ran"\n')
        content = payload / 'usr/lib/chatgpt'
        self.write_executable(content / 'ChatGPT', '''#!/usr/bin/env python3
import json, os, pathlib, sys
if sys.argv[1:]==['--version']:
 print('APP_VERSION');sys.exit(0)
root=pathlib.Path(os.environ['DESK_FIXTURE'])
(root/'official-launch.json').write_text(json.dumps({'args':sys.argv[1:],'env':{key:os.environ.get(key) for key in ('XDG_CACHE_HOME','TMPDIR','CODEX_CLI_PATH','MESA_SHADER_CACHE_DIR')}}))
'''.replace('APP_VERSION', version))
        self.write_executable(content / 'codex-launcher', '#!/bin/sh\nexec "$(dirname "$(readlink -f "$0")")/ChatGPT" "$@"\n')
        self.write_executable(content / 'resources/codex', '#!/bin/sh\necho codex-cli official-fixture\n')
        (content / 'resources/app.asar').write_bytes(b'unmodified official application content')
        archive = self.root / ('chatgpt-' + version + '-' + arch + '.deb')
        result = subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(payload), str(archive)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        filename = f'pool/main/c/chatgpt/chatgpt_{version}_{arch}.deb'
        packages = self.root / 'Packages'
        packages.write_text(f'Package: chatgpt\nVersion: {version}\nArchitecture: {arch}\nFilename: '+ ('https://other.test/app.deb' if bad_url else filename) + f'\nSize: {archive.stat().st_size}\nSHA256: {hashlib.sha256(archive.read_bytes()).hexdigest()}\nInstalled-Size: 32\n\n')
        (self.root / 'Release').write_text('SHA256:\n '+hashlib.sha256(packages.read_bytes()).hexdigest()+f' {packages.stat().st_size} main/binary-{arch}/Packages\n')
        (self.root / 'InRelease').write_text('signed fixture; verified by GPG adapter')
        (self.root / 'key.gpg').write_text('official public key fixture')
        urls = {self.root_url+'/deb/dists/stable/InRelease': str(self.root/'InRelease'),
                self.root_url+'/deb/dists/stable/main/binary-'+arch+'/Packages': str(packages),
                self.root_url+'/arch/26.1016.51333/repository-signing-key.gpg': str(self.root/'key.gpg'),
                self.root_url+'/deb/'+filename: str(archive)}
        (self.root / 'urls.json').write_text(json.dumps(urls))
        return archive, content

    def install(self, **kwargs):
        return self.run_desk('install', 'chatgpt', **kwargs)

    def test_install_verifies_chain_extracts_without_scripts_and_keeps_vendor_files(self):
        archive, source = self.make_release('26.1016.51333')
        originals = {name: (source / name).read_bytes() for name in ('ChatGPT','resources/app.asar','resources/codex')}
        self.install()
        current = self.base / 'current'
        self.assertTrue(current.is_symlink())
        for name, content in originals.items():
            self.assertEqual((current / name).read_bytes(), content)
        self.assertEqual(os.readlink(current / 'AppRun'), 'codex-launcher')
        self.assertTrue((self.home / '.local/bin/chatgpt').is_file())
        entry = (self.home / '.local/share/applications/chatgpt-desk.desktop').read_text()
        self.assertIn('ChatGPT Desktop (official)', entry)
        self.assertNotIn('Community', entry)
        receipt = json.loads((self.base / '.desk-release.json').read_text())
        self.assertEqual(receipt['provider'], 'OpenAI')
        self.assertEqual(receipt['signing_fingerprint'], self.fingerprint)
        self.assertEqual(receipt['sha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertFalse((self.root / 'maintainer-ran').exists())
        self.assertFalse((self.root / 'official-launch.json').exists())
        self.assertFalse((self.base / 'current/resources/app').exists())
        self.assertFalse(list(self.base.glob('official-*')))
        requests = (self.root / 'requests').read_text()
        self.assertNotIn('github.com', requests)
        self.assertIn('repository-signing-key.gpg', requests)

    def test_new_checkbox_entry_and_alias_install_only_official_app(self):
        code, output = self.interact('install', [b'n' + b'j'*11 + b' \r'])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b'ChatGPT Desktop (official, includes Codex)', output)
        self.assertEqual((self.state / 'programs').read_text(), 'chatgpt\n')
        self.assertFalse((self.storage / 'apps/codex-desktop').exists())
        self.run_desk('install', 'chatgpt-desktop')
        self.assertEqual((self.state / 'programs').read_text(), 'chatgpt\n')

    def test_launch_uses_bundled_backend_cache_and_remembers_official_open_choice(self):
        self.install()
        self.run_desk('open', 'chatgpt')
        record = self.read_record('official-launch.json')
        self.assertEqual(record['env']['CODEX_CLI_PATH'], str(self.base / 'current/resources/codex'))
        self.assertEqual(record['env']['XDG_CACHE_HOME'], str(self.storage / 'cache/chatgpt/xdg'))
        self.assertNotIn('--no-sandbox', record['args'])
        self.assertEqual((self.state / 'open-programs').read_text(), 'chatgpt\n')
        self.assertEqual(self.run_desk('chatgpt', '--version').stdout.strip(), '26.1016.51333')
        self.assertIn('ChatGPT Desktop (official)', self.run_desk('st').stdout)

    def test_update_is_explicit_preserves_old_release_and_reuses_healthy_install_offline(self):
        self.install()
        old = (self.base / 'current').resolve()
        requests = (self.root / 'requests').read_text()
        (self.root / 'offline').touch()
        self.install()
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertIn('keeping the installed', self.run_desk('update', 'chatgpt').stderr)
        (self.root / 'offline').unlink()
        self.make_release('26.1020.12345')
        self.run_desk('update', 'chatgpt')
        self.assertNotEqual((self.base / 'current').resolve(), old)
        self.assertTrue(old.is_dir())
        self.assertEqual((self.state / 'programs').read_text(), 'chatgpt\n')
        self.assertFalse((self.root / 'official-launch.json').exists())

    def test_signature_or_key_failure_keeps_installed_release(self):
        self.install()
        old = (self.base / 'current').resolve()
        self.make_release('26.1020.12345')
        for name in ('bad-key', 'bad-signature'):
            with self.subTest(name=name):
                (self.root / name).touch()
                result = self.run_desk('update', 'chatgpt', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.base / 'current').resolve(), old)
                self.assertFalse(list(self.base.glob('official-*')))
                (self.root / name).unlink()

    def test_index_or_artifact_checksum_failure_keeps_original(self):
        self.install()
        old = (self.base / 'current').resolve()
        for target in ('Packages', 'archive'):
            with self.subTest(target=target):
                archive, _ = self.make_release('26.1020.12345')
                path = self.root / 'Packages' if target == 'Packages' else archive
                path.write_bytes(path.read_bytes() + b'tampered')
                result = self.run_desk('update', 'chatgpt', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('checksum mismatch', result.stderr)
                self.assertEqual((self.base / 'current').resolve(), old)

    def test_unsafe_package_url_and_missing_libraries_are_rejected(self):
        self.make_release('26.1016.51333', bad_url=True)
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unexpected official package URL', result.stderr)
        self.make_release('26.1016.51333')
        (self.root / 'missing-library').touch()
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('librequired.so', result.stderr)
        self.assertFalse((self.base / 'current').exists())

    def test_arm64_selects_signed_arm64_package(self):
        self.write_executable(self.bin / 'uname', '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo aarch64;; esac\n')
        self.make_release('26.1016.51333', arch='arm64')
        self.install()
        receipt = json.loads((self.base / '.desk-release.json').read_text())
        self.assertEqual(receipt['architecture'], 'arm64')
        self.assertIn('_arm64.deb', receipt['url'])

    def test_running_app_blocks_update_and_other_profile_runtime(self):
        self.install()
        executable = self.base / 'current/ChatGPT'
        executable.unlink()
        shutil.copy2(shutil.which('sleep'), executable)
        process = subprocess.Popen([str(executable), '30'])
        try:
            requests = (self.root / 'requests').read_text()
            self.run_desk('update', 'chatgpt')
            self.assertEqual((self.root / 'requests').read_text(), requests)
            result = self.run_desk('codex-desktop', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('share your profile', result.stderr)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_old_community_app_cannot_receive_official_launch_by_singleton_handoff(self):
        self.install()
        executable = self.storage / 'apps/codex-desktop/current/running-gui'
        executable.parent.mkdir(parents=True)
        shutil.copy2(shutil.which('sleep'), executable)
        process = subprocess.Popen([str(executable), '30'])
        try:
            result = self.run_desk('chatgpt', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('community Codex Desktop', result.stderr)
            self.assertFalse((self.root / 'official-launch.json').exists())
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_doctor_never_opens_gui_or_changes_profile_and_clean_preserves_data(self):
        self.install()
        profile = self.home / '.config/Codex/history'
        account = self.home / '.codex/auth.json'
        profile.write_bytes(b'keep profile')
        account.write_bytes(b'keep auth')
        result = self.run_desk('chatgpt', '--doctor')
        self.assertIn('provider: OpenAI', result.stdout)
        self.assertIn('No GUI was opened', result.stdout)
        self.assertFalse((self.root / 'official-launch.json').exists())
        self.assertEqual(profile.read_bytes(), b'keep profile')
        self.assertEqual(account.read_bytes(), b'keep auth')
        self.source('setup_runtime; clean_reset_unlocked')
        self.assertFalse(self.base.exists())
        self.assertFalse((self.home / '.local/bin/chatgpt').exists())
        self.assertEqual(profile.read_bytes(), b'keep profile')
        self.assertEqual(account.read_bytes(), b'keep auth')
