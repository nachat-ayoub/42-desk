"""Shared-home lease diagnostics and explicit recovery without bot-data loss."""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import unittest
import uuid

from test_ai_apps import AppFixtures


class OpenMausBotLeaseTests(AppFixtures):
    def setUp(self):
        super().setUp()
        self.env.pop('OMB_DATA_DIR', None)
        self.data = self.home / '.openmausbot'
        self.parent = self.data / 'openmausbot-server.lease'
        self.child = self.data / '.openmausbot-server-child/openmausbot-server.lease'
        self.boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()

    def record(self, **changes):
        record = dict(version=1, pid=2147483647, host='another-school-machine.example',
                      token=str(uuid.uuid4()), createdAt=time.time() * 1000,
                      boot=str(uuid.uuid4()), uptime=123456)
        record.update(changes)
        return record

    def write_lease(self, path, record=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        contents = json.dumps(record or self.record()).encode() + b'\n'
        path.write_bytes(contents)
        path.chmod(0o600)
        return contents

    def repair(self, check=True):
        return self.run_desk('openmausbot', '--repair-lease', '--closed-everywhere', check=check)

    def backups(self):
        return list(self.data.rglob('.desk-lease-backup-*/openmausbot-server.lease'))

    def test_doctor_identifies_foreign_child_without_printing_token_or_changing_data(self):
        record = self.record(secret='must not print this')
        original = self.write_lease(self.child, record)
        result = self.run_desk('openmausbot', '--doctor')
        self.assertIn('another-school-machine.example', result.stdout)
        self.assertIn('remote liveness cannot be checked', result.stdout)
        self.assertNotIn(record['token'], result.stdout + result.stderr)
        self.assertNotIn('must not print this', result.stdout + result.stderr)
        self.assertEqual(self.child.read_bytes(), original)
        self.assertFalse(self.backups())
        self.assertFalse((self.root / 'requests').exists())
        self.assertFalse((self.root / 'openmausbot-launch.json').exists())

    def test_repair_requires_explicit_closed_everywhere_assertion_and_rejects_extra_args(self):
        original = self.write_lease(self.child)
        for args in (('--repair-lease',), ('--repair-lease', '--force'),
                     ('--repair-lease', '--closed-everywhere', 'extra'), ('--doctor', 'extra')):
            with self.subTest(args=args):
                result = self.run_desk('openmausbot', *args, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.child.read_bytes(), original)
                self.assertFalse(self.backups())
        self.assertFalse((self.root / 'requests').exists())

    def test_repair_archives_both_foreign_leases_and_preserves_all_other_files(self):
        parent = self.write_lease(self.parent)
        child = self.write_lease(self.child)
        files = {'config.json': b'private account settings', 'messages.db': b'chat data',
                 'messages.db-wal': b'uncheckpointed messages', 'messages.db-shm': b'database state',
                 '.openmausbot-server-child/keep': b'keep other runtime files',
                 'openmausbot-server.lease.reap-history': b'keep recovery history'}
        for name, contents in files.items():
            (self.data / name).write_bytes(contents)
        result = self.repair()
        self.assertIn('Archived lease:', result.stdout)
        self.assertFalse(self.parent.exists())
        self.assertFalse(self.child.exists())
        backups = self.backups()
        self.assertEqual(len(backups), 2)
        self.assertCountEqual([p.read_bytes() for p in backups], [parent, child])
        for backup in backups:
            self.assertEqual(backup.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        for name, contents in files.items():
            self.assertEqual((self.data / name).read_bytes(), contents)
        self.assertFalse((self.root / 'openmausbot-launch.json').exists())
        self.assertFalse((self.root / 'requests').exists())

    def test_no_lease_and_repeat_repair_are_harmless(self):
        self.run_desk('openmausbot', '--doctor')
        self.assertFalse(self.data.exists())
        self.repair()
        self.assertFalse(self.data.exists())
        self.write_lease(self.child)
        self.repair()
        first = self.backups()
        self.repair()
        self.assertEqual(self.backups(), first)

    def test_live_local_pid_blocks_all_archiving_even_with_closed_everywhere_flag(self):
        parent = self.write_lease(self.parent, self.record(host=socket.gethostname(), pid=os.getpid(), boot=self.boot))
        child = self.write_lease(self.child)
        result = self.repair(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('still alive', result.stderr)
        self.assertEqual(self.parent.read_bytes(), parent)
        self.assertEqual(self.child.read_bytes(), child)
        self.assertFalse(self.backups())

    def test_matching_boot_protects_owner_after_hostname_change(self):
        original = self.write_lease(self.child, self.record(pid=os.getpid(), boot=self.boot))
        self.assertNotEqual(self.repair(check=False).returncode, 0)
        self.assertEqual(self.child.read_bytes(), original)

    def test_foreign_pid_is_not_mistaken_for_an_unrelated_live_local_pid(self):
        self.write_lease(self.child, self.record(pid=os.getpid()))
        self.repair()
        self.assertFalse(self.child.exists())

    def test_previous_boot_and_dead_local_pids_can_be_archived(self):
        self.write_lease(self.parent, self.record(host=socket.gethostname(), pid=os.getpid()))
        self.write_lease(self.child, self.record(host=socket.gethostname(), boot=self.boot))
        self.repair()
        self.assertEqual(len(self.backups()), 2)

    def test_legacy_bootless_record_uses_uptime_only_to_prove_previous_boot(self):
        record = self.record(host=socket.gethostname(), pid=os.getpid(), uptime=10**15)
        record.pop('boot')
        self.write_lease(self.child, record)
        self.repair()
        self.assertFalse(self.child.exists())

    def test_recent_timestamp_does_not_stop_confirmed_foreign_recovery_or_imply_liveness(self):
        self.write_lease(self.child, self.record(createdAt=(time.time() + 86400) * 1000))
        self.repair()
        self.assertFalse(self.child.exists())

    def test_invalid_or_future_lease_formats_prevent_every_change(self):
        original = self.write_lease(self.parent)
        for payload in (b'not json', b'[]', b'{}', json.dumps(self.record(version=2)).encode(),
                        json.dumps(self.record(pid=True)).encode(), json.dumps(self.record(token='invalid')).encode()):
            with self.subTest(payload=payload):
                self.child.parent.mkdir(exist_ok=True)
                self.child.write_bytes(payload)
                self.assertNotEqual(self.repair(check=False).returncode, 0)
                self.assertEqual(self.child.read_bytes(), payload)
                self.assertEqual(self.parent.read_bytes(), original)
                self.assertFalse(self.backups())

    def test_symbolic_lease_files_and_child_directories_are_not_followed(self):
        external = self.root / 'other-lease'
        contents = self.write_lease(external)
        self.child.parent.mkdir(parents=True)
        self.child.symlink_to(external)
        self.assertNotEqual(self.repair(check=False).returncode, 0)
        self.assertEqual(external.read_bytes(), contents)
        self.child.unlink()
        self.child.parent.rmdir()
        self.child.parent.symlink_to(self.root)
        self.assertNotEqual(self.repair(check=False).returncode, 0)
        self.assertEqual(external.read_bytes(), contents)

    def test_custom_data_dir_is_respected_and_default_data_is_untouched(self):
        default = self.write_lease(self.child)
        custom = self.root / 'custom bot data'
        target = custom / '.openmausbot-server-child/openmausbot-server.lease'
        self.write_lease(target)
        self.env['OMB_DATA_DIR'] = str(custom)
        self.repair()
        self.assertFalse(target.exists())
        self.assertEqual(self.child.read_bytes(), default)
        self.assertFalse(self.backups())

    def test_running_managed_app_with_renamed_process_title_blocks_recovery(self):
        original = self.write_lease(self.child)
        binary = self.storage / 'apps/openmausbot/current/openmausbot'
        binary.parent.mkdir(parents=True)
        shutil.copy2(shutil.which('sleep'), binary)
        process = subprocess.Popen(['renamed-server-title', '30'], executable=str(binary))
        try:
            result = self.repair(check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Quit OpenMausBot', result.stderr)
            self.assertEqual(self.child.read_bytes(), original)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_a_lease_replaced_at_rename_is_restored_and_not_discarded(self):
        self.write_lease(self.child)
        replacement = self.record(host=socket.gethostname(), pid=os.getpid(), boot=self.boot)
        (self.root / 'replacement.json').write_text(json.dumps(replacement))
        self.write_executable(self.bin / 'python3', f'''#!{sys.executable}
import json,os,pathlib,sys
args=sys.argv[1:]
if args[:2]==['-', 'repair']:
 original=os.rename
 def race(source,destination,*a,**kw):
  root=pathlib.Path(os.environ['DESK_FIXTURE'])
  if str(source).endswith('openmausbot-server.lease'):
   p=pathlib.Path(source);changed=p.with_suffix('.replacement')
   changed.write_bytes((root/'replacement.json').read_bytes())
   original(changed,p)
  return original(source,destination,*a,**kw)
 os.rename=race
 sys.argv=args
 exec(compile(sys.stdin.read(),'<lease>','exec'))
else:os.execv({sys.executable!r},[{sys.executable!r},*args])
''')
        result = self.repair(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('changed while being archived', result.stderr)
        self.assertEqual(json.loads(self.child.read_text()), replacement)
