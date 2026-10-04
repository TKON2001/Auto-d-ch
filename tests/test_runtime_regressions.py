"""Failure recovery and temporal grouping tests; no API or OCR model calls."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ocr_cache import load_cache, save_cache
from ocr_core import group_samples, scan_settings
from pause_control import PauseController
from storage import atomic_json
from translation_core import translate_context
from video_translator import Cue


class RuntimeRegressions(unittest.TestCase):
    def test_cache_settings_and_interrupted_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.mp4'
            info = dict(width=320, height=200, duration=3)
            cues = [Cue(0, 1, '你好', (0, 10, 100, 30))]
            save_cache(output, 'source', info, cues, fps=2, region=(.2, .8))
            self.assertIsNotNone(load_cache(output, 'source', info, Cue, 2, (.2, .8)))
            self.assertIsNone(load_cache(output, 'source', info, Cue, 4, (.2, .8)))
            self.assertIsNone(load_cache(output, 'source', info, Cue, 2, (0, 1)))
            data = json.loads(output.with_suffix('.ocr.json').read_text(encoding='utf-8'))
            data[0]['zh'] = '再见'
            atomic_json(output.with_suffix('.ocr.json'), data)
            self.assertIsNone(load_cache(output, 'source', info, Cue, 2, (.2, .8)))

    def test_atomic_failure_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project.json'
            atomic_json(path, {'version': 1})
            with patch('storage.os.replace', side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError):
                    atomic_json(path, {'version': 2})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'version': 1})
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_pause_is_idempotent_for_owned_process(self):
        process = Mock()
        control = PauseController()
        control._children[42] = process
        control.pause()
        control.pause()
        control.resume()
        control.resume()
        process.suspend.assert_called_once()
        process.resume.assert_called_once()

    def test_expired_group_cannot_absorb_later_same_text(self):
        box = (0, 10, 100, 30)
        rows = [(0, '你好', box, .9), (.25, '你好', box, .9),
                (10, '你好', box, .9), (10.25, '你好', box, .9)]
        cues = group_samples(rows, 11, Cue, .25)
        self.assertEqual(len(cues), 2)
        self.assertLess(cues[0].end, cues[1].start)

    def test_invalid_scan_parameters_rejected(self):
        for fps, region in [(0, (0, 1)), (float('nan'), (0, 1)),
                            (2, (.8, .2)), (2, (-.1, 1)), (2, (0, float('inf')))]:
            with self.subTest(fps=fps, region=region), self.assertRaises(ValueError):
                scan_settings(fps, region)

    def test_wrong_json_cache_type_is_ignored(self):
        create = Mock(return_value=SimpleNamespace(status='completed',
                      output_text='{"lines":[{"id":0,"vi":"OK"}]}'))
        client = SimpleNamespace(responses=SimpleNamespace(create=create))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            path.write_text('[]', encoding='utf-8')
            result = translate_context([Cue(0, 1, '你好', (0, 0, 10, 10))], '',
                                       'gpt-6.1-sol', lambda _: None,
                                       client=client, cache_path=path)
            self.assertEqual(result, ['OK'])


if __name__ == '__main__':
    unittest.main()
