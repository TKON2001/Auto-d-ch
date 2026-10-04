"""Regression tests for cropped OCR; no models, network or GPU required."""
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from ocr_core import scan


class FakeCapture:
    def __init__(self, frames):
        self.frames = frames
        self.index = -1
        self.released = False

    def open(self, *args):
        return True

    def isOpened(self):
        return True

    def get(self, prop):
        return {
            cv2.CAP_PROP_FPS: 2,
            cv2.CAP_PROP_FRAME_COUNT: len(self.frames),
            cv2.CAP_PROP_FRAME_HEIGHT: 200,
        }.get(prop, 0)

    def grab(self):
        self.index += 1
        return self.index < len(self.frames)

    def retrieve(self):
        return self.frames[self.index]

    def release(self):
        self.released = True


class FakeReader:
    def __init__(self):
        self.detected_shapes = []
        self.recognized_shapes = []
        self.batches = 0

    def detect(self, frame, **kwargs):
        self.detected_shapes.append(frame.shape)
        return ([[[5, 75, 5, 25], [85, 155, 30, 50]]], [[]])

    def recognize(self, crop, **kwargs):
        assert crop.size, 'Empty image passed to OCR'
        self.recognized_shapes.append(crop.shape)
        boxes = kwargs.get('horizontal_list')
        if boxes:
            self.batches += 1
        else:
            boxes = [[0, crop.shape[1], 0, crop.shape[0]]]
        return [([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], '你好', .95)
                for x1, x2, y1, y2 in boxes]


class OCRScanTests(unittest.TestCase):
    def run_scan(self, frames=None, reader=None, gpu=False, info=None):
        if frames is None:
            frames = [(True, np.full((200, 320, 3), 70, np.uint8)) for _ in range(4)]
        capture = FakeCapture(frames)
        reader = reader or FakeReader()
        logs = []
        with patch('cv2.VideoCapture', return_value=capture):
            rows, duration = scan('fake.mp4', info or {'duration': 2, 'height': 200},
                                  Path('.'), logs.append, reader=reader, gpu=gpu, fps=2,
                                  region=(.52,.82))
        self.assertTrue(capture.released)
        return rows, reader, logs

    def test_roi_survives_recognition_on_cpu_and_gpu(self):
        for gpu in (False, True):
            with self.subTest(gpu=gpu):
                rows, reader, _ = self.run_scan(gpu=gpu)
                self.assertEqual(len(rows), 8)
                self.assertEqual({t for t, _, _, _ in rows}, {0, .5, 1, 1.5})
                self.assertTrue(all(shape == (60, 320, 3) for shape in reader.detected_shapes))
                self.assertEqual({box for _, _, box, _ in rows},
                                 {(5, 109, 75, 129), (85, 134, 155, 154)})
                if gpu:
                    self.assertGreater(reader.batches, 0)

    def test_same_reader_can_scan_multiple_videos(self):
        reader = FakeReader()
        first, _, _ = self.run_scan(reader=reader)
        second, _, _ = self.run_scan(reader=reader)
        self.assertEqual(first, second)
        self.assertEqual(len(second), 8)

    def test_empty_decoded_frames_are_skipped(self):
        frames = [(False, None), (True, None),
                  (True, np.empty((0, 320, 3), np.uint8)),
                  (True, np.empty((200, 0, 3), np.uint8)),
                  (True, np.full((200, 320, 3), 70, np.uint8))]
        rows, _, logs = self.run_scan(frames=frames)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(t == 2 for t, _, _, _ in rows))
        self.assertTrue(any('4' in line and 'khung hình' in line for line in logs))

    def test_roi_uses_decoded_height_not_stale_metadata(self):
        rows, reader, _ = self.run_scan(info={'duration': 2, 'height': 1080})
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(shape[0] == 60 for shape in reader.detected_shapes))

    def test_resolution_change_resets_tracking(self):
        frames = [(True, np.full((h, w, 3), 70, np.uint8))
                  for h, w in [(200, 320), (400, 640), (200, 320)]]
        rows, reader, _ = self.run_scan(frames=frames)
        self.assertEqual(len(rows), 6)
        self.assertEqual(reader.detected_shapes, [(60, 320, 3), (120, 640, 3), (60, 320, 3)])
        self.assertIn((.5, '你好', (5, 213, 75, 233), .95), rows)

    def test_reader_errors_still_propagate_and_release_capture(self):
        reader = FakeReader()
        capture = FakeCapture([(True, np.zeros((200, 320, 3), np.uint8))])
        with patch('cv2.VideoCapture', return_value=capture), \
                patch.object(reader, 'detect', side_effect=RuntimeError('model failure')):
            with self.assertRaisesRegex(RuntimeError, 'model failure'):
                scan('fake.mp4', {'duration': 1}, Path('.'), lambda _: None, reader=reader)
        self.assertTrue(capture.released)

    def test_vertical_text_coordinates_include_roi_offset(self):
        reader = FakeReader()
        frames = [(True, np.full((200, 320, 3), 70, np.uint8))]
        chars = [[(1, 2, 9, 10), (1, 12, 9, 20)]]
        with patch.object(reader, 'detect', return_value=([[[5, 15, 5, 45]]], [[]])), \
                patch('ocr_core.vertical_regions', return_value=chars):
            rows, _, _ = self.run_scan(frames=frames, reader=reader)
        self.assertIn((0, '你好你好', (6, 111, 14, 129), .95), rows)


if __name__ == '__main__':
    unittest.main()
