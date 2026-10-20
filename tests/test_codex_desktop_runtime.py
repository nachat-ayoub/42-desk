"""Exercise verified native compatibility repair without accessing user data."""

import hashlib
import io
import json
import shutil
import subprocess
import tarfile

from test_ai_apps import AppFixtures


class CodexDesktopRuntimeTests(AppFixtures):
    def setUp(self):
        super().setUp()
        self.base = self.storage / 'apps/codex-desktop'
        self.current = self.base / 'current'
        self.package = self.current / 'resources/app/node_modules/better-sqlite3'
        self.native = self.package / 'build/Release/better_sqlite3.node'
        self.native.parent.mkdir(parents=True)
        self.native.write_bytes(b'incompatible community module')
        (self.package / 'package.json').write_text('{"version":"12.9.0"}')
        (self.base / '.desk-release.json').write_text('{}')
        self.write_executable(self.current / 'AppRun', '#!/bin/sh\ntouch "$DESK_FIXTURE/gui-opened"\n')
        self.write_executable(self.current / 'codex-desktop.bin', '''#!/usr/bin/env python3
import json, os, pathlib, sys
assert os.environ['ELECTRON_RUN_AS_NODE'] == '1'
assert sys.argv[1] == '-e'
assert "':memory:'" in sys.argv[2]
package = pathlib.Path(sys.argv[3])
candidate = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else package / 'build/Release/better_sqlite3.node'
healthy = candidate.read_bytes() == b'compatible upstream module'
message = os.environ.get('DESK_NATIVE_ERROR', "libm.so.6: version `GLIBC_2.38' not found")
print(json.dumps({'ok': healthy, 'abi': '143', 'arch': os.environ.get('DESK_NATIVE_ARCH', 'x64'),
                  'code': 'ERR_DLOPEN_FAILED', 'message': message}))
sys.exit(0 if healthy else 1)
''')
        self.archive = self.root / 'upstream.tar.gz'
        self.make_archive()
        self.listing = self.root / 'assets.html'
        self.asset_url = 'https://github.com/WiseLibs/better-sqlite3/releases/download/v12.9.0/better-sqlite3-v12.9.0-electron-v143-linux-x64.tar.gz'
        self.make_listing()
        self.write_executable(self.bin / 'curl', '''#!/usr/bin/env python3
import os, pathlib, sys
root = pathlib.Path(os.environ['DESK_FIXTURE'])
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith('https://'))
assert '--proto' in args and '--proto-redir' in args and '--tlsv1.2' in args
with (root / 'requests').open('a') as stream:
    stream.write(url + '\\n')
if (root / 'offline').exists(): sys.exit(22)
assert url.startswith('https://github.com/WiseLibs/better-sqlite3/releases/')
source = root / ('assets.html' if '/expanded_assets/' in url else 'upstream.tar.gz')
pathlib.Path(args[args.index('-o') + 1]).write_bytes(source.read_bytes())
''')
        self.userdata = self.home / '.codex/sqlite/codex.db'
        self.userdata.parent.mkdir(parents=True)
        self.userdata.write_bytes(b'preserve existing database even if damaged')
        self.backup = self.userdata.parent / 'db-backups/sqlite-1-0/codex.db'
        self.backup.parent.mkdir(parents=True)
        self.backup.write_bytes(b'preserve prior recovery backup')

    def make_archive(self, name='build/Release/better_sqlite3.node', data=b'compatible upstream module', symlink=False):
        with tarfile.open(self.archive, 'w:gz') as archive:
            entry = tarfile.TarInfo(name)
            if symlink:
                entry.type = tarfile.SYMTYPE
                entry.linkname = '/etc/passwd'
                archive.addfile(entry)
            else:
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))

    def make_listing(self, url=None, digest=True):
        value = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.listing.write_text('<li><a href="' + (url or self.asset_url) + '">native module</a>' +
                                (f'<clipboard-copy value="sha256:{value}"></clipboard-copy>' if digest else '') + '</li>')

    def repair(self, **kwargs):
        return self.run_desk('codex-desktop', '--repair-runtime', **kwargs)

    def test_repair_preserves_original_and_all_user_data_without_launch_or_migration(self):
        before = {path: path.read_bytes() for path in (self.native, self.userdata, self.backup)}
        result = self.repair()
        self.assertIn('Compatible SQLite runtime installed', result.stdout)
        self.assertEqual(self.native.read_bytes(), b'compatible upstream module')
        original = self.native.with_name(self.native.name + '.desk-original')
        self.assertEqual(original.read_bytes(), before[self.native])
        for path in (self.userdata, self.backup):
            self.assertEqual(path.read_bytes(), before[path])
        self.assertFalse((self.home / '.codex').is_symlink())
        self.assertFalse((self.root / 'gui-opened').exists())
        self.assertFalse((self.storage / 'data/codex-desktop').exists())
        self.assertEqual(list((self.storage / 'cache/codex-desktop').iterdir()), [])
        receipt = json.loads(self.native.with_name(self.native.name + '.desk-runtime.json').read_text())
        self.assertEqual(receipt['abi'], '143')
        self.assertEqual(receipt['url'], self.asset_url)
        requests = (self.root / 'requests').read_text()
        (self.root / 'offline').touch()
        self.repair()
        self.assertEqual((self.root / 'requests').read_text(), requests)

    def test_bad_checksum_keeps_original(self):
        self.archive.write_bytes(b'tampered release archive')
        result = self.repair(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertEqual(self.native.read_bytes(), b'incompatible community module')

    def test_missing_digest_or_wrong_release_is_rejected(self):
        for options in ({'digest': False}, {'url': self.asset_url.replace('v143', 'v145')},
                        {'url': self.asset_url.replace('WiseLibs', 'untrusted')}):
            with self.subTest(options=options):
                self.make_listing(**options)
                result = self.repair(check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('No unique matching', result.stderr)
                self.assertEqual(self.native.read_bytes(), b'incompatible community module')

    def test_incompatible_upstream_module_is_not_installed(self):
        self.make_archive(data=b'also incompatible module')
        self.make_listing()
        result = self.repair(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('incompatible too', result.stderr)
        self.assertEqual(self.native.read_bytes(), b'incompatible community module')

    def test_symlink_or_traversal_archive_is_not_extracted(self):
        for options in ({'symlink': True}, {'name': '../../outside'}):
            with self.subTest(options=options):
                self.make_archive(**options)
                self.make_listing()
                result = self.repair(check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Unsupported SQLite archive', result.stderr)
                self.assertEqual(self.native.read_bytes(), b'incompatible community module')

    def test_unrelated_loader_error_is_reported_without_downloads(self):
        self.env['DESK_NATIVE_ERROR'] = 'Module did not self-register'
        result = self.repair(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Module did not self-register', result.stderr)
        self.assertFalse((self.root / 'requests').exists())

    def test_running_gui_blocks_replacement_and_network_access(self):
        process_path = self.current / 'running-gui'
        shutil.copy2(shutil.which('sleep'), process_path)
        process = subprocess.Popen([str(process_path), '30'])
        try:
            result = self.repair(check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Quit Codex Desktop', result.stderr)
            self.assertFalse((self.root / 'requests').exists())
            self.assertEqual(self.native.read_bytes(), b'incompatible community module')
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_install_and_launch_check_runtime_before_data_migration(self):
        (self.root / 'offline').touch()
        for arguments in (('install', 'codex-desktop'), ('codex-desktop',)):
            with self.subTest(arguments=arguments):
                result = self.run_desk(*arguments, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.home / '.codex').is_symlink())
                self.assertFalse((self.root / 'gui-opened').exists())
                self.assertEqual(self.userdata.read_bytes(), b'preserve existing database even if damaged')

    def test_extra_arguments_are_rejected_without_downloads(self):
        result = self.run_desk('codex-desktop', '--repair-runtime', 'extra', check=False)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / 'requests').exists())
