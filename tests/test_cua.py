"""Cua release integrity, Codex registration, cache routing and clean MCP stdio."""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import unittest

from test_ai_apps import AppFixtures


class CuaTests(AppFixtures):
    release_root = 'https://github.com/trycua/cua/releases'

    def setUp(self):
        super().setUp()
        for key in list(self.env):
            if key.startswith('CUA_'):
                self.env.pop(key)
        self.env.pop('CODEX_CLI_PATH', None)
        self.base = self.storage / 'apps/cua'
        self.home_codex = self.home / '.codex'
        self.home_codex.mkdir()
        self.config = self.home_codex / 'config.toml'
        self.config.write_text('# keep my settings\nmodel = "test-model"\n[mcp_servers.other]\ncommand = "other-server"\n')
        self.original_config = self.config.read_bytes()
        self.write_executable(self.codex, '''#!/usr/bin/env python3
import json, os, pathlib, sys
root=pathlib.Path(os.environ['DESK_FIXTURE']);args=sys.argv[1:]
state=root/'mcp-state.json'
servers=json.loads(state.read_text()) if state.exists() else []
with (root/'codex-commands').open('a') as log:log.write(json.dumps(args)+'\\n')
config=pathlib.Path(os.environ['CODEX_HOME'])/'config.toml'
if args==['mcp','list','--json']:
 if (root/'invalid-config').exists():sys.exit('invalid configuration fixture')
 print(json.dumps(servers))
elif args[:2]==['mcp','add']:
 if (root/'add-fails').exists():sys.exit(2)
 command=args[args.index('--')+1:]
 env_arg=args[args.index('--env')+1];key,value=env_arg.split('=',1)
 entry={'name':'cua-driver','enabled':True,'transport':{'type':'stdio','command':command[0],'args':command[1:],'env':{key:value}}}
 servers.append(entry);state.write_text(json.dumps(servers))
 config.write_text(config.read_text()+'\\n[mcp_servers.cua-driver]\\ncommand = '+json.dumps(command[0])+'\\n')
elif args==['mcp','remove','cua-driver']:
 state.write_text(json.dumps([s for s in servers if s['name']!='cua-driver']))
 config.write_text(config.read_text().split('\\n[mcp_servers.cua-driver]')[0])
else:sys.exit('unexpected Codex command: '+str(args))
''')
        (self.codex.parent.parent / '.installed-version').write_text('1.2.3\n')
        self.write_executable(self.bin / 'curl', '''#!/usr/bin/env python3
import json, os, pathlib, sys
root=pathlib.Path(os.environ['DESK_FIXTURE']);args=sys.argv[1:]
assert '--proto' in args and '--proto-redir' in args and '--tlsv1.2' in args
url=next(a for a in args if a.startswith('https://'))
with (root/'requests').open('a') as log:log.write(url+'\\n')
if (root/'offline').exists():sys.exit(22)
source=json.loads((root/'urls.json').read_text()).get(url)
if source is None:sys.exit('Unexpected URL: '+url)
pathlib.Path(args[args.index('-o')+1]).write_bytes(pathlib.Path(source).read_bytes())
''')
        self.write_executable(self.bin / 'ldd', '''#!/usr/bin/env python3
import os,pathlib
print('libX11.so.6 => not found' if (pathlib.Path(os.environ['DESK_FIXTURE'])/'missing-library').exists() else 'libX11.so.6 => /lib/libX11.so.6')
''')
        self.write_executable(self.bin / 'cosign', '''#!/usr/bin/env python3
import os,pathlib,sys
root=pathlib.Path(os.environ['DESK_FIXTURE']);args=sys.argv[1:]
assert '--certificate-identity' in args and '--certificate-oidc-issuer' in args
assert 'cd-rust-cua-driver.yml@refs/tags/cua-driver-rs-v' in args[args.index('--certificate-identity')+1]
with (root/'signatures-checked').open('a') as stream:stream.write('checked\\n')
sys.exit(1 if (root/'bad-signature').exists() else 0)
''')
        self.urls = {}
        self.make_release('0.38.0')

    def make_tar(self, path, entries):
        with tarfile.open(path, 'w:gz') as archive:
            for name, data, mode in entries:
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), mode
                archive.addfile(info, io.BytesIO(data))

    def make_release(self, version, arch='x86_64', unsafe=False, missing_skill=False):
        tag = 'cua-driver-rs-v' + version
        name = f'cua-driver-rs-{version}-linux-{arch}-binary.tar.gz'
        skills = tag + '-skills.tar.gz'
        content = '''#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:];root=pathlib.Path(os.environ['DESK_FIXTURE'])
if args==['--version']:print('cua-driver VERSION');sys.exit(0)
if args==['mcp']:
 for line in sys.stdin:
  request=json.loads(line)
  if 'id' in request:
   print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'serverInfo':{'name':'cua-driver','version':'VERSION'}}}),flush=True)
 sys.exit(0)
(root/'driver-launch.json').write_text(json.dumps({'args':args,'env':{k:os.environ.get(k) for k in (
 'XDG_CACHE_HOME','TMPDIR','CUA_DRIVER_RS_HOME','CUA_DRIVER_HOME','CUA_DRIVER_TELEMETRY_HOME',
 'CUA_DRIVER_RS_UPDATE_CHECK','DISPLAY','WAYLAND_DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','XDG_CONFIG_HOME')}}))
'''.replace('VERSION', version).encode()
        archive = self.root / name
        entries = [('cua-driver', content, 0o755), ('cua-cursor-theme', b'cursor', 0o755)]
        if unsafe:
            entries.append(('../escaped', b'unsafe', 0o644))
        self.make_tar(archive, entries)
        skill_archive = self.root / skills
        entries = [(tag + '-skills/SKILL.md', b'official skill fixture', 0o644)]
        if not missing_skill:
            entries.append((tag + '-skills/LINUX.md', b'Linux guide', 0o644))
        self.make_tar(skill_archive, entries)
        sums = self.root / ('sums-' + version)
        sums.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in (archive, skill_archive)))
        page = self.root / ('page-' + version)
        page.write_text('<a href="/trycua/cua/releases/tag/'+tag+'">release</a>'
                        '<a href="/trycua/cua/releases/tag/cua-driver-rs-v0.28.3">withdrawn</a>'
                        '<a href="/trycua/cua/releases/tag/nightly-cua-driver-rs-v99.0.0">nightly</a>')
        bundle = self.root / 'signature.json'
        bundle.write_text('{"mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json"}')
        url = self.release_root + '/download/' + tag + '/'
        self.urls[self.release_root + '?q=cua-driver-rs-v&expanded=true'] = str(page)
        self.urls[url + 'SHA256SUMS'] = str(sums)
        for path in (archive, skill_archive):
            self.urls[url + path.name] = str(path)
            self.urls[url + path.name + '.sigstore.json'] = str(bundle)
        (self.root / 'urls.json').write_text(json.dumps(self.urls))
        return archive

    def install(self):
        return self.run_desk('install', 'cua')

    def test_install_registers_stdio_with_codex_preserves_other_settings_and_backs_up(self):
        self.install()
        self.assertTrue((self.base / 'current/cua-driver').is_file())
        self.assertFalse((self.root / 'driver-launch.json').exists())
        self.assertEqual((self.state / 'programs').read_text(), 'cua\n')
        self.assertFalse((self.storage / 'apps/brave').exists())
        self.assertTrue(self.config.read_bytes().startswith(self.original_config))
        entry = json.loads((self.root / 'mcp-state.json').read_text())[0]
        self.assertEqual(entry['transport']['command'], str(self.home / '.local/bin/desk'))
        self.assertEqual(entry['transport']['args'], ['cua', 'mcp'])
        self.assertEqual(entry['transport']['env'], {'GOINFRE': str(self.storage)})
        forwarded = json.loads(next(line.split('=', 1)[1] for line in self.config.read_text().splitlines()
                                    if line.startswith('env_vars =')))
        for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR', 'XAUTHORITY'):
            self.assertIn(name, forwarded)
        self.assertNotIn('OPENAI_API_KEY', forwarded)
        backups = list((self.storage / 'data/cua/config-backups').glob('*.toml'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original_config)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.home / '.agents/skills/cua-driver').resolve(), (self.base / 'current/skills/cua-driver').resolve())
        self.assertTrue((self.home / '.local/bin/cua-driver').is_file())
        self.assertEqual((self.root / 'signatures-checked').read_text().splitlines(), ['checked', 'checked'])

    def test_checkbox_alias_and_status_include_cua(self):
        code, output = self.interact('install', [b'n' + b'\x1b[B' * 12 + b' \r'])
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b'Cua Driver', output)
        self.assertEqual((self.state / 'programs').read_text(), 'cua\n')
        self.run_desk('install', 'cua-driver')
        self.assertIn('Cua Driver', self.run_desk('st').stdout)

    def test_shell_hook_manages_driver_alias_without_changing_the_cua_sdk_command(self):
        self.install()
        hook = (self.home / '.bashrc').read_text()
        self.assertIn('unalias cua-driver ', hook)
        self.assertNotIn('unalias cua ', hook)
        self.assertNotIn('unset -f cua ', hook)
        self.assertIn('/cua-driver', self.run_desk('st').stdout)

    def test_repeat_install_and_background_startup_do_not_download_or_duplicate_config(self):
        self.install()
        original = self.config.read_bytes()
        requests = (self.root / 'requests').read_text()
        (self.root / 'offline').touch()
        self.install()
        self.source('setup_runtime; shell_prepare_component cua')
        self.assertEqual((self.root / 'requests').read_text(), requests)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(len(list((self.storage / 'data/cua/config-backups').glob('*'))), 1)

    def test_native_launch_routes_state_and_cache_and_keeps_graphical_session_environment(self):
        self.install()
        self.env.update(DISPLAY=':9', WAYLAND_DISPLAY='wayland-test', XDG_RUNTIME_DIR='/run/user/test', DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/test/bus')
        self.run_desk('cua', 'doctor')
        record = self.read_record('driver-launch.json')
        self.assertEqual(record['args'], ['doctor'])
        for key in ('XDG_CACHE_HOME', 'TMPDIR', 'CUA_DRIVER_RS_HOME', 'CUA_DRIVER_HOME', 'CUA_DRIVER_TELEMETRY_HOME'):
            self.assertTrue(Path(record['env'][key]).is_relative_to(self.storage), key)
        self.assertEqual(record['env']['CUA_DRIVER_RS_UPDATE_CHECK'], '0')
        for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_CONFIG_HOME'):
            self.assertEqual(record['env'][key], self.env[key])
        self.assertEqual((self.home / '.cua-driver').resolve(), self.storage / 'data/cua/driver')
        self.run_desk('cua')
        self.assertEqual(self.read_record('driver-launch.json')['args'], ['doctor'])

    def test_mcp_stdout_contains_only_json_rpc_and_missing_install_never_downloads(self):
        request = json.dumps({'jsonrpc':'2.0', 'id':1, 'method':'initialize', 'params':{}}) + '\n'
        missing = self.run_desk('cua', 'mcp', input=request, check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(missing.stdout, '')
        self.assertFalse((self.root / 'requests').exists())
        self.install()
        answer = self.run_desk('cua', 'mcp', input=request)
        self.assertEqual(json.loads(answer.stdout)['result']['serverInfo']['name'], 'cua-driver')
        self.assertEqual(len(answer.stdout.splitlines()), 1)

    def test_update_activates_new_release_and_keeps_old_release_and_codex_preferences(self):
        self.install()
        old = (self.base / 'current').resolve()
        config = self.config.read_bytes()
        self.make_release('0.39.0')
        self.run_desk('update', 'cua')
        self.assertEqual((self.base / '.installed-version').read_text(), '0.39.0\n')
        self.assertNotEqual((self.base / 'current').resolve(), old)
        self.assertTrue(old.is_dir())
        self.assertEqual(self.config.read_bytes(), config)
        self.assertEqual((self.home / '.agents/skills/cua-driver').resolve(), (self.base / 'current/skills/cua-driver').resolve())
        self.assertFalse((self.root / 'driver-launch.json').exists())

    def test_offline_update_keeps_working_release(self):
        self.install()
        (self.root / 'offline').touch()
        self.assertIn('keeping the installed', self.run_desk('update', 'cua').stderr)
        self.assertTrue((self.base / 'current/cua-driver').is_file())

    def test_corrupt_or_unsigned_updates_never_replace_working_release(self):
        self.install()
        old = (self.base / 'current').resolve()
        archive = self.make_release('0.39.0')
        original = archive.read_bytes()
        archive.write_bytes(original + b'corrupt')
        result = self.run_desk('update', 'cua', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertEqual((self.base / 'current').resolve(), old)
        archive.write_bytes(original)
        (self.root / 'bad-signature').touch()
        self.assertNotEqual(self.run_desk('update', 'cua', check=False).returncode, 0)
        self.assertEqual((self.base / 'current').resolve(), old)
        self.assertFalse((self.base / 'releases/0.39.0-linux-x86_64').exists())

    def test_unsafe_archive_missing_guides_and_missing_libraries_are_rejected(self):
        for variant in ('unsafe', 'missing_skill', 'missing-library'):
            with self.subTest(variant=variant):
                self.make_release('0.38.0', unsafe=variant=='unsafe', missing_skill=variant=='missing_skill')
                if variant=='missing-library':
                    (self.root / 'missing-library').touch()
                result = self.run_desk('install', 'cua', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.base / 'current').exists())
        self.assertFalse((self.base / 'escaped').exists())
        self.assertEqual(self.config.read_bytes(), self.original_config)

    def test_custom_codex_home_is_used_without_touching_default_home(self):
        custom = self.root / 'custom codex home'
        custom.mkdir()
        (custom / 'config.toml').write_bytes(self.original_config)
        self.env['CODEX_HOME'] = str(custom)
        self.install()
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertIn('mcp_servers.cua-driver', (custom / 'config.toml').read_text())

    def test_existing_official_desktop_backend_is_reused_without_installing_terminal_codex(self):
        bundled = self.storage / 'apps/chatgpt/current/resources/codex'
        bundled.parent.mkdir(parents=True)
        self.codex.rename(bundled)
        self.install()
        self.assertFalse(self.codex.exists())
        self.assertTrue((self.root / 'mcp-state.json').exists())

    def test_existing_codex_on_path_is_reused(self):
        self.codex.rename(self.bin / 'codex')
        self.install()
        self.assertFalse(self.codex.exists())
        self.assertTrue((self.root / 'mcp-state.json').exists())

    def test_missing_codex_is_installed_as_a_dependency_only_when_needed(self):
        template = self.root / 'dependency-codex'
        self.codex.rename(template)
        self.source('''setup_runtime
cua_codex_binary() {
 [ -x "$APPS/codex/bin/codex" ] || return 1
 printf '%s\\n' "$APPS/codex/bin/codex"
}
prepare_codex_unlocked() {
 mkdir -p "$APPS/codex/bin"
 cp "$DESK_FIXTURE/dependency-codex" "$APPS/codex/bin/codex"
 echo dependency > "$DESK_FIXTURE/dependency-installed"
}
main install cua
''')
        self.assertTrue((self.root / 'dependency-installed').is_file())
        self.assertTrue((self.root / 'mcp-state.json').exists())

    def test_explicit_driver_home_and_existing_default_state_are_preserved(self):
        existing = self.home / '.cua-driver'
        existing.mkdir()
        (existing / 'settings.json').write_text('my original settings')
        custom = self.root / 'custom driver state'
        self.env['CUA_DRIVER_RS_HOME'] = str(custom)
        self.install()
        self.run_desk('cua', 'doctor')
        self.assertEqual(self.read_record('driver-launch.json')['env']['CUA_DRIVER_RS_HOME'], str(custom))
        self.assertFalse(existing.is_symlink())
        self.assertEqual((existing / 'settings.json').read_text(), 'my original settings')

    def test_existing_user_server_and_skill_are_left_unchanged(self):
        custom = {'name':'cua-driver','enabled':False,'transport':{'command':'/custom/cua-driver','args':['mcp']}}
        (self.root / 'mcp-state.json').write_text(json.dumps([custom]))
        skill = self.home / '.agents/skills/cua-driver'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('my skill')
        result = self.install()
        self.assertIn('Keeping your existing cua-driver MCP', result.stderr)
        self.assertEqual(json.loads((self.root / 'mcp-state.json').read_text()), [custom])
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual((skill / 'SKILL.md').read_text(), 'my skill')

    def test_invalid_codex_config_is_not_modified_and_setup_can_be_retried(self):
        (self.root / 'invalid-config').touch()
        result = self.run_desk('install', 'cua', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no configuration was changed', result.stderr)
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertFalse((self.root / 'mcp-state.json').exists())
        (self.root / 'invalid-config').unlink()
        self.run_desk('cua', 'setup')
        self.assertEqual(len(json.loads((self.root / 'mcp-state.json').read_text())), 1)

    def test_arm64_release_selection(self):
        self.write_platform_for_arm64()
        self.make_release('0.38.0', arch='arm64')
        self.install()
        receipt = json.loads((self.base / 'current/.desk-release.json').read_text())
        self.assertEqual(receipt['arch'], 'arm64')

    def write_platform_for_arm64(self):
        self.write_executable(self.bin / 'uname', '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo aarch64;; esac\n')

    def test_clean_removes_only_owned_registration_and_preserves_driver_state_and_backups(self):
        self.install()
        state = self.storage / 'data/cua/driver'
        (state / 'settings.json').write_text('keep')
        self.source('setup_runtime; clean_reset_unlocked')
        self.assertFalse(self.base.exists())
        self.assertFalse((self.storage / 'cache/cua').exists())
        self.assertFalse((self.home / '.local/bin/cua-driver').exists())
        self.assertFalse((self.home / '.agents/skills/cua-driver').exists())
        self.assertEqual(json.loads((self.root / 'mcp-state.json').read_text()), [])
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual((state / 'settings.json').read_text(), 'keep')
        self.assertTrue(list((self.storage / 'data/cua/config-backups').glob('*.toml')))

    def test_running_native_driver_postpones_updates_and_blocks_clean(self):
        self.install()
        binary = self.base / 'current/cua-driver'
        shutil.copy2(shutil.which('sleep'), binary)
        process = subprocess.Popen(['renamed-driver-title', '30'], executable=str(binary))
        try:
            requests = (self.root / 'requests').read_text()
            result = self.run_desk('update', 'cua')
            self.assertIn('Cua Driver is running', result.stderr)
            self.assertEqual((self.root / 'requests').read_text(), requests)
            result = self.source('setup_runtime; native_apps_running', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Cua Driver is running', result.stderr)
        finally:
            process.terminate();process.wait(timeout=5)
