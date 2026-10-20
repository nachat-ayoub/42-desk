"""Offline regression checks for verified self updates and video downloads."""

import hashlib
import json
import subprocess
import io
import zipfile
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
name = 'new-desk' if url.endswith('/main/desk') else ('ffmpeg.json' if url.endswith('/imageio-ffmpeg/json') else ('latest.html' if url.endswith('/releases/latest') else url.rsplit('/', 1)[-1]))
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
elif '--dump-single-json' in sys.argv:
    (root / 'metadata-args.json').write_text(json.dumps(sys.argv[1:]))
    if (root / 'metadata-fails').exists():
        print('fixture extraction failure', file=sys.stderr)
        sys.exit(4)
    print((root / 'metadata.json').read_text())
else:
    (root / 'download.json').write_text(json.dumps({'args': sys.argv[1:], 'tmp': os.environ['TMPDIR']}))
    sys.exit(7 if (root / 'download-fails').exists() else 0)
''')
        formats = [
            {'height': 360, 'vcodec': 'h264', 'acodec': 'aac'},
            {'height': 480, 'vcodec': 'h264', 'acodec': 'none'},
            {'height': 720, 'vcodec': 'h264', 'acodec': 'aac'},
            {'height': 720, 'vcodec': 'vp9', 'acodec': 'none'},
            {'height': 1080, 'vcodec': 'vp9', 'acodec': 'none'},
            {'height': 2160, 'vcodec': 'vp9', 'acodec': 'none'},
            {'height': 27, 'vcodec': 'none', 'acodec': 'none'},
            {'height': None, 'vcodec': 'none', 'acodec': 'aac'},
        ]
        (self.root / 'metadata.json').write_text(json.dumps({'title': 'Example video', 'formats': formats}))
        wheel = io.BytesIO()
        with zipfile.ZipFile(wheel, 'w') as archive:
            archive.writestr('imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2', '#!/bin/sh\nexit 0\n')
        (self.root / 'ffmpeg.whl').write_bytes(wheel.getvalue())
        self.ffmpeg_metadata = {'urls': [{
            'filename': 'imageio_ffmpeg-0.6.0-py3-none-manylinux2014_x86_64.whl',
            'url': 'https://files.pythonhosted.org/ffmpeg.whl',
            'digests': {'sha256': hashlib.sha256(wheel.getvalue()).hexdigest()},
        }]}
        (self.root / 'ffmpeg.json').write_text(json.dumps(self.ffmpeg_metadata))
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
        self.run_desk('yt', url, '720p')
        record = json.loads((self.root / 'download.json').read_text())
        self.assertEqual(record['args'][-2:], ['--', url])
        self.assertIn('--ignore-config', record['args'])
        self.assertIn('--no-playlist', record['args'])
        self.assertEqual(record['args'][record['args'].index('--format') + 1], 'b[height=720]/bv[height=720]+ba')
        self.assertEqual(record['args'][record['args'].index('--paths') + 1], str(self.storage / 'downloads/youtube'))
        self.assertEqual(record['tmp'], str(self.storage / 'cache/yt-dlp/tmp'))
        (self.root / 'offline').touch()
        self.run_desk('yt', url, '360p')  # Installed tool is reused, no bootstrap request.

    def test_video_checksum_failure_never_executes_or_installs_download(self):
        self.checksums.write_text('0' * 64 + '  yt-dlp\n')
        result = self.run_desk('yt', 'https://youtu.be/example', '360p', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum', result.stderr)
        self.assertFalse((self.storage / 'apps/yt-dlp/yt-dlp').exists())
        self.assertFalse((self.root / 'download.json').exists())

    def test_video_quality_prompt_downloads_selected_format_and_can_cancel(self):
        code, output = self.interact(['yt', 'https://youtu.be/example'], [b'3\n'], prompt=b'Choose quality')
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b'720p', output)
        record = json.loads((self.root / 'download.json').read_text())
        self.assertEqual(record['args'][record['args'].index('--format') + 1], 'b[height=720]/bv[height=720]+ba')
        (self.root / 'download.json').unlink()
        code, output = self.interact(['yt', 'https://youtu.be/example'], [b'q\n'], prompt=b'Choose quality')
        self.assertEqual(code, 0, output.decode())
        self.assertFalse((self.root / 'download.json').exists())

    def test_video_noninteractive_requires_quality_and_propagates_download_failure(self):
        result = self.run_desk('yt', 'https://youtu.be/example', check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn('360p', result.stdout)
        self.assertFalse((self.root / 'download.json').exists())
        (self.root / 'download-fails').touch()
        self.assertEqual(self.run_desk('yt', 'https://youtu.be/example', '360p', check=False).returncode, 7)

    def test_quality_menu_has_unique_resolutions_without_stream_details(self):
        result = self.run_desk('yt', 'https://youtu.be/example', check=False)
        self.assertEqual(result.returncode, 2)
        for quality in ('360p', '480p', '720p', '1080p'):
            self.assertEqual(result.stdout.count(quality), 1)
        self.assertNotIn('27p', result.stdout)
        self.assertNotIn('video only', result.stdout)
        self.assertNotIn('FORMAT_ID', result.stdout)
        self.assertIn('Example video', result.stdout)
        self.assertEqual(json.loads((self.root / 'metadata-args.json').read_text())[-2:], ['--', 'https://youtu.be/example'])

    def test_default_quality_and_invalid_interactive_choice(self):
        code, output = self.interact(['yt', 'https://youtu.be/example'], [b'wrong\n\n'], prompt=b'Choose quality')
        self.assertEqual(code, 0, output.decode())
        self.assertIn(b'Choose an available quality', output)
        record = json.loads((self.root / 'download.json').read_text())
        self.assertIn('b[height=720]/bv[height=720]+ba', record['args'])

    def install_portable_ffmpeg(self, tool):
        # Exercise the embedded installer with PATH discovery mocked so a
        # system ffmpeg cannot bypass the download/integrity checks.
        script = Path(self.env['DESK_SCRIPT']).read_text().split("3<<'VIDEO_DOWNLOAD'\n", 1)[1].split('\nVIDEO_DOWNLOAD', 1)[0]
        script = script.split('\ntry:\n    sys.exit(main())', 1)[0]
        return subprocess.run(['python3', '-c', script + "\nshutil.which = lambda name: None\nprint(portable_ffmpeg(Path(sys.argv[1])))", str(tool)], env=self.env, capture_output=True, text=True)

    def test_ffmpeg_checksum_failure_preserves_existing_files(self):
        self.source('setup_runtime; install_ytdlp_unlocked')
        tool = self.storage / 'apps/yt-dlp/yt-dlp'
        self.ffmpeg_metadata['urls'][0]['digests']['sha256'] = '0' * 64
        (self.root / 'ffmpeg.json').write_text(json.dumps(self.ffmpeg_metadata))
        result = self.install_portable_ffmpeg(tool)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum verification failed', result.stderr)
        self.assertFalse((tool.parent / 'ffmpeg').exists())
        self.assertFalse((tool.parent / 'ffmpeg.whl').exists())

    def test_1080p_installs_verified_portable_ffmpeg_and_merges_audio(self):
        # Do not depend on the host already having ffmpeg installed.
        self.source('setup_runtime; install_ytdlp_unlocked')
        tool = self.storage / 'apps/yt-dlp/yt-dlp'
        result = self.install_portable_ffmpeg(tool)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((tool.parent / 'ffmpeg').is_file())
        self.assertTrue((tool.parent / 'ffmpeg.whl').is_file())
        self.run_desk('yt', 'https://youtu.be/example', '1080p')
        record = json.loads((self.root / 'download.json').read_text())
        self.assertIn('--ffmpeg-location', record['args'])
        self.assertIn('b[height=1080]/bv[height=1080]+ba', record['args'])

    def test_unavailable_quality_and_metadata_failure_do_not_download(self):
        result = self.run_desk('yt', 'https://youtu.be/example', '4320p', check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn('available quality', result.stderr)
        self.assertFalse((self.root / 'download.json').exists())
        (self.root / 'metadata-fails').touch()
        result = self.run_desk('yt', 'https://youtu.be/example', '720p', check=False)
        self.assertEqual(result.returncode, 4)
        self.assertIn('Could not read this video', result.stderr)
        self.assertNotIn('fixture extraction failure', result.stderr)
        self.assertIn('fixture extraction failure', (self.storage / 'cache/yt-dlp/last-check.log').read_text())

    def test_all_downloads_finish_as_mp4_including_2160p_and_combined_streams(self):
        for quality in ('720p', '2160p'):
            with self.subTest(quality=quality):
                self.run_desk('yt', 'https://youtu.be/example', quality)
                args = json.loads((self.root / 'download.json').read_text())['args']
                self.assertEqual(args[args.index('--output') + 1],
                                 f'%(title).180B [%(id)s] [{quality}].%(ext)s')
                self.assertEqual(args[args.index('--recode-video') + 1], 'mp4')
                self.assertEqual(args[args.index('--merge-output-format') + 1], 'mkv')
                self.assertIn('--ffmpeg-location', args)
                options = args[args.index('--postprocessor-args') + 1]
                self.assertIn('VideoConvertor+ffmpeg_o:', options)
                self.assertIn('-c:v libx264', options)
                self.assertIn('-c:a aac', options)
                self.assertNotIn('--keep-video', args)
