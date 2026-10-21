"""Check the guarded renderer repair and execute its transport-aware tool routing."""

import hashlib
import json
import os
import shutil
import subprocess
import unittest

from test_ai_apps import AppFixtures, CHAT_RENDERER


class CodexDesktopChatTests(AppFixtures):
    def setUp(self):
        super().setUp()
        self.base = self.storage / 'apps/codex-desktop'
        self.current = self.base / 'current'
        self.renderer = self.current / 'resources/app/webview/assets/app-initial-fixture.js'
        self.renderer.parent.mkdir(parents=True)
        self.renderer.write_text(CHAT_RENDERER)
        (self.base / '.installed-version').write_text('v26.820.60940\n')
        self.backup = self.renderer.with_name(self.renderer.name + '.desk-original')
        self.profile = self.home / '.codex'
        self.profile.mkdir()
        (self.profile / 'config.toml').write_text('[mcp_servers.custom]\ncommand="custom-server"\n')
        (self.profile / 'auth.json').write_bytes(b'private credentials')

    def prepare(self, **kwargs):
        return self.source('setup_runtime; prepare_codex_desktop_chat', **kwargs)

    def test_patch_keeps_original_renderer_and_user_data_and_is_idempotent(self):
        before = self.renderer.read_bytes()
        originals = {path: path.read_bytes() for path in self.profile.iterdir()}
        result = self.prepare()
        self.assertIn('Prepared Codex Desktop chat compatibility', result.stdout)
        self.assertEqual(self.backup.read_bytes(), before)
        receipt = json.loads((self.base / '.desk-chat-compat.json').read_text())
        self.assertEqual(receipt['original_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(receipt['patched_sha256'], hashlib.sha256(self.renderer.read_bytes()).hexdigest())
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse((self.root / 'requests').exists())
        modified = self.renderer.stat().st_mtime_ns
        self.prepare()
        self.assertEqual(self.renderer.stat().st_mtime_ns, modified)
        self.assertFalse(list(self.renderer.parent.glob('.desk-chat-*')))

    def test_unknown_newer_release_is_not_rewritten(self):
        (self.base / '.installed-version').write_text('v26.900.10000\n')
        self.prepare()
        self.assertEqual(self.renderer.read_text(), CHAT_RENDERER)
        self.assertFalse(self.backup.exists())

    def test_changed_layout_or_duplicate_target_is_rejected_without_modification(self):
        for source in ('unknown renderer', CHAT_RENDERER + CHAT_RENDERER):
            with self.subTest(source=source[:25]):
                self.renderer.write_text(source)
                result = self.prepare(check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.renderer.read_text(), source)
                self.assertFalse(self.backup.exists())

    def test_unrecognized_existing_backup_is_kept(self):
        self.backup.write_text('user backup')
        result = self.prepare(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.backup.read_text(), 'user backup')
        self.assertEqual(self.renderer.read_text(), CHAT_RENDERER)

    def test_running_gui_blocks_renderer_repair(self):
        executable = self.current / 'running-gui'
        shutil.copy2(shutil.which('sleep'), executable)
        process = subprocess.Popen([str(executable), '30'])
        try:
            result = self.prepare(check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Quit Codex Desktop', result.stderr)
            self.assertEqual(self.renderer.read_text(), CHAT_RENDERER)
            self.assertFalse(self.backup.exists())
        finally:
            process.terminate()
            process.wait(timeout=5)

    @unittest.skipUnless(shutil.which('node'), 'Node is needed to execute renderer routing tests')
    def test_renderer_falls_back_only_when_local_app_transport_is_absent(self):
        self.prepare()
        script = '''
const assert=require('node:assert/strict');
const {prepare}=require(process.argv[1]);
const tools=[{type:'function',name:'read_thread'},{type:'function',name:'create_thread'}];
async function run(server,host='local',skip=false,error=false){
  const calls=[];
  const context={params:{hostId:host,requestClient:{sendRequest:async(method,params)=>{
    calls.push({method,params}); if(error)throw Error('existing configuration error');
    return{config:{mcp_servers:{codex_app:server}}};
  }}},requestDynamicToolsForThreadStart:async()=>tools};
  const result=await prepare.call(context,{config:{'features.existing':true},cwd:'/project'},{skipDynamicTools:skip},'/fallback');
  return{result,calls};
}
(async()=>{
  for(const server of [undefined,{}, {enabled:false}, {enabled_tools:['read_thread']}]){
    const {result,calls}=await run(server);
    assert.equal(result.config['mcp_servers.codex_app.enabled_tools'],undefined);
    assert.deepEqual(result.dynamicTools,[{type:'function',name:'read_thread'}]);
    assert.equal(result.config['features.existing'],true);
    assert.deepEqual(calls,[{method:'config/read',params:{includeLayers:false,cwd:'/project'}}]);
  }
  for(const server of [{command:'/real/server'}, {url:'https://example.test/mcp'}]){
    const {result}=await run(server);
    assert.deepEqual(result.config['mcp_servers.codex_app.enabled_tools'],['read_thread','create_thread']);
    assert.deepEqual(result.dynamicTools,[]);
  }
  const remote=await run(undefined,'remote-host');
  assert.deepEqual(remote.calls,[]);
  assert.deepEqual(remote.result.dynamicTools,[{type:'function',name:'read_thread'}]);
  const skipped=await run(undefined,'local',true);
  assert.equal(skipped.result.dynamicTools,undefined);
  assert.equal(skipped.result.config['mcp_servers.codex_app.enabled_tools'],undefined);
  await assert.rejects(run(undefined,'local',false,true),/existing configuration error/);
  console.log('transport routing verified');
})().catch(error=>{console.error(error);process.exitCode=1});
'''
        result = subprocess.run([shutil.which('node'), '-e', script, str(self.renderer)],
                                capture_output=True, text=True, timeout=15, env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('transport routing verified', result.stdout)
