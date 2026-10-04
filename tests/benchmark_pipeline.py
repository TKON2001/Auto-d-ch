"""Compare grouping/layout against a trusted local source backup ZIP."""
import argparse
import time
import types
import zipfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_translator import Cue
from ocr_core import group_samples
from subtitle_layout import layout


def measure(function, *args):
    start = time.perf_counter()
    result = function(*args)
    return result, time.perf_counter() - start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.backup) as archive:
        old_ocr = types.ModuleType('old_ocr')
        old_layout = types.ModuleType('old_layout')
        exec(compile(archive.read('ocr_core.py'), 'backup/ocr_core.py', 'exec'), old_ocr.__dict__)
        exec(compile(archive.read('subtitle_layout.py'), 'backup/subtitle_layout.py', 'exec'), old_layout.__dict__)
    samples = [(i * .5, str(i), (20, 180, 180, 210), .95) for i in range(6000)]
    before, first = measure(old_ocr.group_samples, samples, 3000, Cue, .25)
    after, second = measure(group_samples, samples, 3000, Cue, .25)
    assert before == after, 'Grouping output changed'
    print(f'Grouping 6000 samples: {first:.4f}s -> {second:.4f}s ({first/second:.1f}x)')
    cues = [Cue(i, i + .8, 'text', (20, 180, 180, 210)) for i in range(1000)]
    arguments = (cues, ['Xin chao'] * len(cues), {'width': 320, 'height': 240}, 'Arial', 12, {})
    before, first = measure(old_layout.layout, *arguments)
    after, second = measure(layout, *arguments)
    assert before == after, 'Layout output changed'
    print(f'Layout 1000 cues: {first:.4f}s -> {second:.4f}s ({first/second:.1f}x)')


if __name__ == '__main__':
    main()
