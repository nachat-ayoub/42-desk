"""Offline regression checks for verified self updates and video downloads."""

import hashlib
import json
from pathlib import Path

from test_ai_apps import AppFixtures


class UtilityTests(AppFixtures):
    def setUp(self):
        super().setUp()
        self.write_executable(self.bin / 'curl', '''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['DESK_FIXTURE'])
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith('https://'))
with (root / 'requests').open('a') as stream:
    stream.write(url + '\\n')
if (root / 'offline').exists():
    sys.exit(22)
name = 'new-desk' if url.endswith('/main/desk') else ('latest.html' if url.endswith('/releases/latest') else url.rsplit('/', 1)[-1])
pathlib.Path(args[args.index('-o') + 1]).write_bytes((root / name).read_bytes())
''')
        self.candidate = self.root / 'new-desk'
        self.candidate.write_text('#!/usr/bin/env bash\nVERSION="9.0.0"\necho updated\n')
        self.target = self.home / '.local/bin/desk'
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text('previous installed desk')
        self.video = self.root / 'yt-dlp'
        self.video.write_text('''import json, os, pathlib, sys
root = pathlib.Path(os.environ['DESK_FIXTURE'])
if '--version' in sys.argv:
    print('2026.10.14')
elif '--list-formats' in sys.argv:
    print('18 mp4 360p video+audio')
    print('22 mp4 720p video+audio')
else:
    (root / 'download.json').write_text(json.dumps({'args': sys.argv[1:], 'tmp': os.environ['TMPDIR']}))
    sys.exit(7 if (root / 'download-fails').exists() else 0)
''')
        (self.root / 'latest.html').write_text('<include-fragment src="/yt-dlp/yt-dlp/releases/expanded_assets/2026.10.14">')
        self.checksums = self.root / 'SHA2-256SUMS'
        self.checksums.write_text(hashlib.sha256(self.video.read_bytes()).hexdigest() + '  yt-dlp\n')

    def test_self_update_installs_newer_version_without_touching_checkout(self):
        before = Path(self.env['DESK_SCRIPT']).read_bytes()
        result = self.run_desk('update', 'self')
        self.assertIn('Updated 42-desk', result.stdout)
        self.assertEqual(self.target.read_bytes(), self.candidate.read_bytes())
        self.assertEqual(Path(self.env['DESK_SCRIPT']).read_bytes(), before)
        self.assertTrue(self.target.stat().st_mode & 0o100)

    def test_self_update_preserves_installation_on_invalid_download_or_network_failure(self):
        for content in ('VERSION="9.0.0"\nif\n', '#!/bin/bash\necho no-version\n'):
            self.candidate.write_text(content)
            result = self.run_desk('update', 'self', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.target.read_text(), 'previous installed desk')
        (self.root / 'offline').touch()
        self.assertNotEqual(self.run_desk('self-update', check=False).returncode, 0)
        self.assertEqual(self.target.read_text(), 'previous installed desk')

    def test_self_update_never_downgrades(self):
        self.candidate.write_text('#!/bin/bash\nVERSION="1.0.0"\n')
        self.run_desk('self-update')
        self.assertEqual(self.target.read_text(), 'previous installed desk')

    def test_video_download_verifies_tool_routes_storage_and_passes_arguments(self):
        url = 'https://www.youtube.com/watch?v=example&list=ignored'
        self.run_desk('yt', url, '22')
        record = json.loads((self.root / 'download.json').read_text())
        self.assertEqual(record['args'][-2:], ['--', url])
        self.assertIn('--ignore-config', record['args'])
        self.assertIn('--no-playlist', record['args'])
        self.assertEqual(record['args'][record['args'].index('--format') + 1], '22')
        self.assertEqual(record['args'][record['args'].index('--paths') + 1], str(self.storage / 'downloads/youtube'))
        self.assertEqual(record['tmp'], str(self.storage / 'cache/yt-dlp/tmp'))
        (self.root / 'offline').touch()
        self.run_desk('yt', url, '18')  # Installed tool is reused, no bootstrap request.

    def test_video_checksum_failure_never_executes_or_installs_download(self):
        self.checksums.write_text('0' * 64 + '  yt-dlp\n')
        result = self.run_desk('yt', 'https://youtu.be/example', '18', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum', result.stderr)
        self.assertFalse((self.storage / 'apps/yt-dlp/yt-dlp').exists())
        self.assertFalse((self.root / 'download.json').exists())

    def test_video_quality_prompt_downloads_selected_format_and_can_cancel(self):
        code, output = self.interact(['yt', 'https://youtu.be/example'], [b'22\n'], prompt=b'Quality/format ID')
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b'720p', output)
        record = json.loads((self.root / 'download.json').read_text())
        self.assertEqual(record['args'][record['args'].index('--format') + 1], '22')
        (self.root / 'download.json').unlink()
        code, output = self.interact(['yt', 'https://youtu.be/example'], [b'q\n'], prompt=b'Quality/format ID')
        self.assertEqual(code, 0, output.decode())
        self.assertFalse((self.root / 'download.json').exists())

    def test_video_noninteractive_requires_format_and_propagates_download_failure(self):
        result = self.run_desk('yt', 'https://youtu.be/example', check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn('360p', result.stdout)
        self.assertFalse((self.root / 'download.json').exists())
        (self.root / 'download-fails').touch()
        self.assertEqual(self.run_desk('yt', 'https://youtu.be/example', '18', check=False).returncode, 7)
