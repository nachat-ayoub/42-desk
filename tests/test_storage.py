"""Verify storage reporting, cache relocation, and preservation of existing data."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from test_ai_apps import AppFixtures
from test_programs import DESK


class StorageTests(AppFixtures):
    def setUp(self):
        super().setUp()
        self.write_executable(self.bin / 'ps', '#!/bin/sh\necho bash\n')
        self.runtime = self.home / '.cache/codex-runtimes'
        self.destination = self.storage / 'cache/codex-runtimes'

    def populate(self, path, name='keep', content=b'preserve existing bytes'):
        path.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(content)
        return path / name

    def test_report_is_read_only_shows_physical_paths_and_distinguishes_other_data(self):
        self.populate(self.runtime)
        self.populate(self.home / '.nvm')
        self.populate(self.home / '.data/mariadb', content=b'database contents must not be printed')
        self.populate(self.home / '.var/app/com.visualstudio.code/data/vscode/extensions')
        result = self.run_desk('storage')
        self.assertIn('[HOME]', result.stdout)
        self.assertIn('Node installation, not managed by desk', result.stdout)
        self.assertIn('MariaDB database, not managed by desk', result.stdout)
        self.assertIn('com.visualstudio.code/data/vscode/extensions', result.stdout)
        self.assertNotIn('database contents must not be printed', result.stdout)
        self.assertFalse(self.storage.exists())
        self.assertFalse(self.state.exists())
        self.storage.mkdir()
        self.populate(self.destination)
        import shutil
        shutil.rmtree(self.runtime)
        self.runtime.symlink_to(self.destination)
        result = self.run_desk('storage')
        self.assertIn('[GOINFRE]', result.stdout)
        self.assertIn('physical: ' + str(self.destination), result.stdout)
        self.assertFalse(self.state.exists())

    def test_home_fallback_is_reported_as_session_storage(self):
        self.env['GOINFRE'] = str(self.home / '.local/opt')
        self.populate(self.home / '.local/opt/cache')
        result = self.run_desk('storage')
        self.assertIn('still use session storage', result.stdout)
        self.assertNotIn('[GOINFRE]', result.stdout)

    def test_migration_preserves_caches_extensions_permissions_and_persistent_data(self):
        runtime_file = self.populate(self.runtime, 'node')
        runtime_file.chmod(0o755)
        flatpak = self.home / '.var/app/com.visualstudio.code/data/vscode/extensions'
        native = self.home / '.vscode/extensions'
        self.populate(flatpak, 'claude')
        self.populate(native, 'extension')
        self.populate(self.home / '.config/Code/GPUCache')
        self.populate(self.home / '.config/BraveSoftware/Brave-Browser/Default/Cache')
        for directory in ('.nvm', '.data/mariadb', '.codex', '.claude'):
            self.populate(self.home / directory)
        result = self.run_desk('storage', 'migrate')
        self.assertIn('Storage migration complete', result.stdout)
        for path in (self.runtime, flatpak, native, self.home / '.config/Code/GPUCache',
                     self.home / '.config/BraveSoftware/Brave-Browser/Default/Cache'):
            self.assertTrue(path.is_symlink(), path)
            self.assertTrue(path.resolve().is_relative_to(self.storage), path)
        self.assertEqual(runtime_file.read_bytes(), b'preserve existing bytes')
        self.assertEqual(runtime_file.stat().st_mode & 0o777, 0o755)
        self.assertEqual((flatpak / 'claude').read_bytes(), b'preserve existing bytes')
        for directory in ('.nvm', '.data/mariadb', '.codex', '.claude'):
            self.assertFalse((self.home / directory).is_symlink())
            self.assertEqual((self.home / directory / 'keep').read_bytes(), b'preserve existing bytes')
        self.run_desk('storage', 'migrate')
        self.assertEqual(runtime_file.read_bytes(), b'preserve existing bytes')

    def test_conflict_is_detected_before_any_files_move(self):
        self.populate(self.runtime)
        self.populate(self.home / '.vscode/extensions')
        self.populate(self.storage / 'data/vscode/extensions', content=b'other extension')
        result = self.run_desk('storage', 'migrate', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Destination already contains data', result.stderr)
        self.assertFalse(self.runtime.is_symlink())
        self.assertFalse(self.destination.exists())
        self.assertEqual((self.home / '.vscode/extensions/keep').read_bytes(), b'preserve existing bytes')

    def test_running_apps_prevent_all_pending_moves(self):
        self.populate(self.runtime)
        self.populate(self.home / '.vscode/extensions')
        for name in ('codex', 'ChatGPT', 'code', 'code-insiders'):
            with self.subTest(name=name):
                self.write_executable(self.bin / 'ps', '#!/bin/sh\necho ' + name + '\n')
                result = self.run_desk('storage', 'migrate', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Quit Codex/ChatGPT', result.stderr)
                self.assertFalse(self.runtime.is_symlink())
                self.assertFalse(self.destination.exists())

    def test_custom_links_and_external_parent_directories_are_preserved(self):
        external = self.root / 'custom-cache'
        self.populate(external)
        self.runtime.parent.mkdir(parents=True)
        self.runtime.symlink_to(external)
        parent = self.root / 'external-profile'
        self.populate(parent / 'GPUCache')
        config = self.home / '.config'
        config.mkdir()
        (config / 'Code').symlink_to(parent)
        result = self.run_desk('storage', 'migrate')
        self.assertIn('Keeping custom link', result.stderr)
        self.assertIn('Keeping externally stored path', result.stderr)
        self.assertEqual(self.runtime.resolve(), external)
        self.assertFalse((parent / 'GPUCache').is_symlink())

    def test_prepare_links_new_paths_and_preserves_existing_live_directories(self):
        self.source('setup_runtime; storage_paths prepare codex')
        self.assertTrue(self.runtime.is_symlink())
        self.assertEqual(self.runtime.resolve(), self.destination)
        self.destination.rmdir()
        self.source('setup_runtime; storage_paths prepare codex')
        self.assertTrue(self.runtime.is_dir())
        self.runtime.unlink()
        self.populate(self.runtime)
        self.write_executable(self.bin / 'ps', '#!/bin/sh\necho codex\n')
        self.source('setup_runtime; storage_paths prepare codex')
        self.assertFalse(self.runtime.is_symlink())
        self.assertEqual((self.runtime / 'keep').read_bytes(), b'preserve existing bytes')

    def test_empty_destination_can_be_replaced_without_merging(self):
        self.populate(self.runtime)
        self.destination.mkdir(parents=True)
        self.run_desk('storage', 'migrate')
        self.assertTrue(self.runtime.is_symlink())
        self.assertEqual((self.destination / 'keep').read_bytes(), b'preserve existing bytes')

    def test_native_editor_and_browser_launch_route_new_caches_and_extensions(self):
        for key in ('npm_config_cache', 'PIP_CACHE_DIR', 'UV_CACHE_DIR'):
            self.env.pop(key, None)
        for app, executable in (('code', 'vscode/bin/code'), ('brave', 'brave/brave')):
            with self.subTest(app=app):
                self.write_executable(self.storage / 'apps' / executable, '''#!/usr/bin/env python3
import json, os, pathlib, sys
pathlib.Path(os.environ['DESK_FIXTURE'], 'native-launch.json').write_text(json.dumps({
 'args':sys.argv[1:], 'env':{key:os.environ.get(key) for key in
 ('XDG_CACHE_HOME','TMPDIR','TMP','TEMP','MESA_SHADER_CACHE_DIR','__GL_SHADER_DISK_CACHE_PATH',
  'npm_config_cache','PIP_CACHE_DIR','UV_CACHE_DIR')}}))
''')
                (self.root / 'native-launch.json').unlink(missing_ok=True)
                self.run_desk('_open', app)
                record = self.read_record('native-launch.json')
                cache = self.storage / 'cache' / ('vscode' if app == 'code' else 'brave')
                for key, value in record['env'].items():
                    self.assertTrue(Path(value).is_relative_to(cache), (key, value))
                if app == 'code':
                    self.assertEqual((self.home / '.vscode/extensions').resolve(), self.storage / 'data/vscode/extensions')
                    self.assertTrue((self.home / '.config/Code/GPUCache').resolve().is_relative_to(cache))
                else:
                    self.assertIn('--disk-cache-dir=' + str(cache / 'chromium'), record['args'])

    def test_explicit_package_cache_overrides_survive_native_launch_environment(self):
        for key in ('npm_config_cache', 'PIP_CACHE_DIR', 'UV_CACHE_DIR'):
            self.env[key] = str(self.root / key)
        result = self.source('setup_runtime; launch_cache_environment vscode; '
                             'python3 -c \'import json,os;print(json.dumps({k:os.environ[k] for k in '
                             '("npm_config_cache","PIP_CACHE_DIR","UV_CACHE_DIR")}))\'')
        values = json.loads(result.stdout)
        for key, value in values.items():
            self.assertEqual(value, self.env[key])

    def cross_filesystem_storage(self):
        temporary = tempfile.TemporaryDirectory(prefix='.desk-storage-test-', dir=DESK.parent)
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name)
        if target.stat().st_dev == self.home.stat().st_dev:
            self.skipTest('Cross-filesystem relocation needs separate workspace/tmp mounts')
        self.storage = target
        self.env['GOINFRE'] = str(target)
        self.destination = target / 'cache/codex-runtimes'

    def test_cross_filesystem_copy_keeps_executables_and_relative_links(self):
        self.cross_filesystem_storage()
        original = self.populate(self.runtime, 'node')
        original.chmod(0o755)
        (self.runtime / 'alias').symlink_to('node')
        self.run_desk('storage', 'migrate')
        self.assertTrue(self.runtime.is_symlink())
        self.assertEqual((self.runtime / 'alias').read_bytes(), b'preserve existing bytes')
        self.assertTrue((self.destination / 'alias').is_symlink())
        self.assertTrue(os.access(self.destination / 'node', os.X_OK))
        self.assertFalse(list(self.runtime.parent.glob('*.desk-storage-*')))

    def test_cross_filesystem_copy_failure_leaves_original_complete(self):
        self.cross_filesystem_storage()
        self.populate(self.runtime)
        # Simulate a full destination disk after a partial copy, using the real
        # migration code and real cross-filesystem source rename failure.
        self.write_executable(self.bin / 'python3', f'''#!{sys.executable}
import os, shutil, sys
args=sys.argv[1:]
if len(args)>1 and args[:2]==['-', 'migrate']:
 def fail_copy(source, target, **kwargs):
  os.mkdir(target)
  open(os.path.join(target, 'partial'), 'w').write('incomplete')
  raise OSError('simulated disk full')
 shutil.copytree=fail_copy
 sys.argv=args
 exec(compile(sys.stdin.read(), '<storage>', 'exec'))
else:
 os.execv({sys.executable!r}, [{sys.executable!r}, *args])
''')
        result = self.run_desk('storage', 'migrate', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('simulated disk full', result.stderr)
        self.assertFalse(self.runtime.is_symlink())
        self.assertEqual((self.runtime / 'keep').read_bytes(), b'preserve existing bytes')
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.destination.parent.glob('.desk-storage-*')))

    def test_invalid_arguments_do_not_create_directories(self):
        for args in (('storage', 'delete'), ('storage', 'migrate', 'everything')):
            result = self.run_desk(*args, check=False)
            self.assertEqual(result.returncode, 2)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.storage.exists())
