"""Exercise missing managed profiles without resetting existing data or links."""

import os
from pathlib import Path
import signal
import time

from test_ai_apps import AppFixtures


class CodexDesktopStorageTests(AppFixtures):
    def setUp(self):
        super().setUp()
        self.write_executable(self.bin / 'ps', '#!/bin/sh\necho bash\n')
        self.data = self.storage / 'data/codex-desktop'
        self.profile = self.home / '.config/Codex'
        self.target = self.data / 'config/Codex'
        self.profile.parent.mkdir(parents=True)

    def prepare(self, **kwargs):
        return self.source('setup_runtime; prepare_codex_desktop_storage', **kwargs)

    def test_missing_managed_targets_are_recreated_preserving_links_and_existing_data(self):
        pairs = [(self.profile, self.target),
                 (self.home / '.codex', self.data / 'codex-home'),
                 (self.home / '.local/share/codex', self.data / 'share/codex')]
        for source, target in pairs:
            source.parent.mkdir(parents=True, exist_ok=True)
            source.symlink_to(target, target_is_directory=True)
        keep = self.data / 'config/codex/history'
        keep.parent.mkdir(parents=True)
        keep.write_bytes(b'existing profile history')
        (self.home / '.config/codex').symlink_to(keep.parent, target_is_directory=True)
        original_links = {source: os.readlink(source) for source, _ in pairs}
        result = self.prepare()
        self.assertIn('Recreated missing desk-managed directory', result.stdout)
        self.assertIn('Missing directories are empty', result.stderr)
        for source, target in pairs:
            self.assertTrue(target.is_dir())
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertEqual(os.readlink(source), original_links[source])
        self.assertEqual(keep.read_bytes(), b'existing profile history')
        again = self.prepare()
        self.assertNotIn('Recreated', again.stdout)
        self.assertNotIn('Missing directories', again.stderr)

    def test_broken_custom_link_is_preserved_and_blocks_other_migrations(self):
        external = self.root / 'missing custom profile'
        self.profile.symlink_to(external, target_is_directory=True)
        home = self.home / '.codex'
        home.mkdir()
        (home / 'auth.json').write_bytes(b'existing credentials')
        result = self.prepare(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Restore the target or correct the link', result.stderr)
        self.assertEqual(os.readlink(self.profile), str(external))
        self.assertFalse(external.exists())
        self.assertFalse(home.is_symlink())
        self.assertEqual((home / 'auth.json').read_bytes(), b'existing credentials')
        self.assertFalse(self.data.exists())

    def test_target_file_is_never_replaced_by_directory(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'user file')
        self.profile.symlink_to(self.target)
        result = self.prepare(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.target.read_bytes(), b'user file')
        self.assertEqual(os.readlink(self.profile), str(self.target))

    def test_conflicts_are_checked_before_recreating_missing_targets(self):
        self.profile.symlink_to(self.target, target_is_directory=True)
        other = self.home / '.config/codex'
        other.mkdir()
        destination = self.data / 'config/codex'
        destination.mkdir(parents=True)
        (other / 'history').write_bytes(b'original')
        result = self.prepare(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.target.exists())
        self.assertEqual((other / 'history').read_bytes(), b'original')

    def test_running_codex_blocks_missing_directory_recreation(self):
        self.profile.symlink_to(self.target, target_is_directory=True)
        self.write_executable(self.bin / 'ps', '#!/bin/sh\necho codex\n')
        result = self.prepare(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Close Codex CLI and Codex Desktop', result.stderr)
        self.assertFalse(self.target.exists())
        self.assertTrue(self.profile.is_symlink())


class DesktopStartupTests(AppFixtures):
    def test_missing_executable_is_reported(self):
        result = self.source('setup_runtime; start_logged_desktop "Test app" "$STATE_DIR/test.log" "$DESK_FIXTURE/missing"', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('could not start', result.stderr)

    def test_long_running_app_detaches_and_keeps_writing_log(self):
        executable = self.bin / 'desktop-fixture'
        self.write_executable(executable, '''#!/usr/bin/env python3
import os, pathlib, time
root = pathlib.Path(os.environ['DESK_FIXTURE'])
(root / 'pid').write_text(str(os.getpid()))
(root / 'session').write_text(str(os.getsid(0)))
print('started', flush=True)
time.sleep(30)
''')
        process_id = None
        try:
            started = time.monotonic()
            self.source('setup_runtime; start_logged_desktop "Test app" "$STATE_DIR/test.log" "$DESK_FIXTURE/bin/desktop-fixture"')
            self.assertLess(time.monotonic() - started, 8)
            process_id = int((self.root / 'pid').read_text())
            os.kill(process_id, 0)
            self.assertEqual(int((self.root / 'session').read_text()), process_id)
            self.assertEqual((self.state / 'test.log').read_text(), 'started\n')
        finally:
            if process_id is None and (self.root / 'pid').exists():
                process_id = int((self.root / 'pid').read_text())
            if process_id is not None:
                try:
                    os.kill(process_id, signal.SIGTERM)
                except ProcessLookupError:
                    pass
