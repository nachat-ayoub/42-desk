"""Verify that desktop diagnostics never open a GUI or alter original databases."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

import test_ai_apps


class CodexDesktopDoctorTests(test_ai_apps.AppFixtures):
    def setUp(self):
        super().setUp()
        self.base = self.storage / 'apps/codex-desktop'
        self.current = self.base / 'current'
        self.current.mkdir(parents=True)
        (self.base / '.installed-version').write_text('v26.820.60940\n')
        (self.base / '.desk-release.json').write_text('{}')
        self.write_executable(self.current / 'AppRun', '#!/bin/sh\ntouch "$DESK_FIXTURE/gui-opened"\n')
        modules = self.current / 'resources/app/.vite/build'
        modules.mkdir(parents=True)
        (modules / 'src-fixture.js').write_text('''
Object.defineProperty(exports,"Fr",{enumerable:!0,get:function(){return HA}})
Object.defineProperty(exports,"Ir",{enumerable:!0,get:function(){return UA}})
Object.defineProperty(exports,"Pr",{enumerable:!0,get:function(){return _ne}})
function HA(e){return(0,i.join)(_O(),`sqlite`,e)}
''')
        self.write_executable(self.current / 'codex-desktop.bin', '''#!/usr/bin/env python3
import json, os, pathlib, sqlite3, sys
assert sys.argv[1] == '-e'
assert os.environ['ELECTRON_RUN_AS_NODE'] == '1'
profile = pathlib.Path(os.environ['CODEX_HOME'])
assert profile.parent.name.startswith('.desk-sqlite-probe-')
db = profile / 'sqlite/codex.db'
root = pathlib.Path(os.environ['DESK_FIXTURE'])
with (root / 'probes.jsonl').open('a') as stream:
    stream.write(json.dumps({'profile': str(profile), 'existing': db.exists()}) + '\\n')
if not db.exists() and os.environ.get('DESK_TEST_FRESH_ERROR'):
    print(json.dumps({'ok': False, 'code': 'SQLITE_FULL', 'message': 'disk quota exceeded'}))
    sys.exit(1)
try:
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE IF NOT EXISTS diagnostic_migration (id INTEGER)')
    conn.commit()
    conn.close()
    conn = sqlite3.connect(db)
    result = conn.execute('PRAGMA quick_check').fetchall()
    conn.close()
    print(json.dumps({'ok': result == [('ok',)]}))
except sqlite3.Error as error:
    print(json.dumps({'ok': False, 'code': 'SQLITE_NOTADB', 'message': str(error)}))
    sys.exit(1)
''')
        self.codex_home = self.home / '.codex'
        self.database = self.codex_home / 'sqlite/codex.db'

    @staticmethod
    def create_database(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE secrets (value TEXT)')
            conn.execute('INSERT INTO secrets VALUES (?)', ('private conversation text',))

    def doctor(self, **kwargs):
        return self.run_desk('codex-desktop', '--doctor', **kwargs)

    def test_missing_database_is_reported_without_creating_it_or_opening_a_gui(self):
        result = self.doctor()
        self.assertIn(str(self.database) + ': missing', result.stdout)
        self.assertIn('Fresh database and reopen on the home filesystem', result.stdout)
        self.assertIn('"ok": true', result.stdout)
        self.assertFalse(self.database.exists())
        self.assertFalse((self.root / 'gui-opened').exists())
        self.assertFalse((self.root / 'requests').exists())
        self.assertFalse(list(self.home.glob('.desk-sqlite-probe-*')))

    def test_original_database_and_backups_are_unchanged_after_copy_migrations(self):
        self.create_database(self.database)
        backup = self.database.parent / 'db-backups/sqlite-1-0/codex.db'
        self.create_database(backup)
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (self.database, backup)}
        result = self.doctor()
        self.assertIn('Current database (disposable copy)', result.stdout)
        self.assertIn('Preserved backup (disposable copy)', result.stdout)
        self.assertNotIn('private conversation text', result.stdout)
        for path, digest in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertFalse(self.codex_home.is_symlink())
        self.assertFalse((self.storage / 'data/codex-desktop').exists())
        probes = [json.loads(line) for line in (self.root / 'probes.jsonl').read_text().splitlines()]
        self.assertEqual([probe['existing'] for probe in probes], [True, True, False])
        self.assertTrue(all(not Path(probe['profile']).exists() for probe in probes))

    def test_corrupt_database_error_is_visible_without_moving_the_original(self):
        self.database.parent.mkdir(parents=True)
        self.database.write_bytes(b'not a database')
        result = self.doctor(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SQLITE_NOTADB', result.stdout)
        self.assertEqual(self.database.read_bytes(), b'not a database')
        self.assertFalse((self.database.parent / 'db-backups').exists())

    def test_fresh_database_quota_failure_is_visible(self):
        self.env['DESK_TEST_FRESH_ERROR'] = '1'
        result = self.doctor(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('disk quota exceeded', result.stdout)
        self.assertFalse(self.database.exists())

    def test_database_path_that_is_a_directory_is_reported_and_preserved(self):
        self.database.mkdir(parents=True)
        (self.database / 'keep').write_text('existing data')
        result = self.doctor(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(self.database) + ': directory', result.stdout)
        self.assertEqual((self.database / 'keep').read_text(), 'existing data')

    def test_dangling_migration_link_is_reported_without_recreating_it(self):
        migrated = self.storage / 'data/codex-desktop/codex-home'
        self.codex_home.symlink_to(migrated, target_is_directory=True)
        result = self.doctor(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('symlink to ' + str(migrated), result.stdout)
        self.assertIn('Physical home: ' + str(migrated), result.stdout)
        self.assertTrue(self.codex_home.is_symlink())
        self.assertFalse(migrated.exists())

    def test_recent_logs_are_selected_by_modification_time(self):
        root = self.home / '.local/state/codex/logs'
        root.mkdir(parents=True)
        old = root / 'z-old.log'
        old.write_text('SQLITE old database error\n')
        os.utime(old, (1, 1))
        for number in range(4):
            recent = root / f'a-new-{number}.log'
            recent.write_text(f'SQLITE recent error {number}\n')
            os.utime(recent, (100 + number, 100 + number))
        result = self.doctor()
        self.assertIn('SQLITE recent error 3', result.stdout)
        self.assertNotIn('SQLITE old database error', result.stdout)

    def test_explicit_home_and_state_directory_are_respected(self):
        custom = self.root / 'custom Codex home'
        self.env['CODEX_HOME'] = str(custom)
        self.env['XDG_STATE_HOME'] = str(self.root / 'custom state')
        self.create_database(custom / 'sqlite/codex.db')
        logs = Path(self.env['XDG_STATE_HOME']) / 'codex/logs'
        logs.mkdir(parents=True)
        (logs / 'current.log').write_text('SQLITE custom directory\n')
        result = self.doctor()
        self.assertIn('CODEX_HOME: ' + str(custom), result.stdout)
        self.assertIn('SQLITE custom directory', result.stdout)
        self.assertFalse(self.database.exists())

    def test_running_desktop_blocks_snapshot_probes(self):
        executable = self.current / 'AppRun'
        executable.unlink()
        shutil.copy2(shutil.which('sleep'), executable)
        process = subprocess.Popen(['codex-gui', '30'], executable=str(executable))
        try:
            result = self.doctor(check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Quit Codex Desktop', result.stderr)
            self.assertFalse((self.root / 'probes.jsonl').exists())
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_unsupported_package_is_reported_without_running_it(self):
        (self.current / 'resources/app/.vite/build/src-fixture.js').unlink()
        result = self.doctor(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unavailable for this package layout', result.stdout)
        self.assertFalse((self.root / 'probes.jsonl').exists())

    def test_dangling_electron_profile_is_reported_without_recreating_it(self):
        self.create_database(self.database)
        profile = self.home / '.config/Codex'
        profile.parent.mkdir(parents=True, exist_ok=True)
        target = self.storage / 'data/codex-desktop/config/Codex'
        profile.symlink_to(target, target_is_directory=True)
        result = self.doctor(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(target), result.stdout)
        self.assertIn('cannot create its SingletonLock', result.stdout)
        self.assertFalse(target.exists())
        self.assertTrue(profile.is_symlink())

