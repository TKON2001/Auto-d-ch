"""Exercise actual FFmpeg encoding; OCR and translation are offline fixtures."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import video_translator as app


class RenderIntegration(unittest.TestCase):
    def test_real_video_audio_and_project(self):
        ffmpeg = app.find_binary('ffmpeg')
        if not ffmpeg or not app.find_binary('ffprobe'):
            self.skipTest('FFmpeg is not installed')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mp4'
            output = Path(directory) / 'translated.mp4'
            app.run([ffmpeg, '-y', '-v', 'error', '-f', 'lavfi', '-i',
                     'color=c=black:size=320x240:rate=10:duration=1',
                     '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                     '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                     '-shortest', str(source)])
            samples = [(0, '你好', (40, 180, 160, 200), .95),
                       (.5, '你好', (40, 180, 160, 200), .95)]
            with patch.object(app, 'extract_frames', return_value=(samples, 1)), \
                    patch.object(app, 'translate', return_value=['Xin chào']), \
                    patch('render_core.nvenc_available', return_value=False):
                result = app.process(str(source), output, 'offline-fixture', log=lambda _: None)
            info = app.probe(result)
            self.assertEqual((info['width'], info['height']), (320, 240))
            self.assertTrue(info['has_audio'])
            self.assertGreaterEqual(info['duration'], .9)
            self.assertTrue(output.with_suffix('.project.json').is_file())
            self.assertEqual(list(Path(directory).glob('*_render_*.mp4')), [])
