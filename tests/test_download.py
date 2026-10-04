import tempfile, unittest, sys, types
from unittest.mock import MagicMock
try:
    import yt_dlp
except ImportError:
    sys.modules["yt_dlp"]=types.SimpleNamespace(YoutubeDL=MagicMock())
from pathlib import Path
from unittest.mock import patch
import video_translator as v
class DownloadTests(unittest.TestCase):
    def test_cookie_and_normalize(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cookie=root/'original.txt'; cookie.write_text('# Netscape HTTP Cookie File\n')
            work=root/'work'; work.mkdir()
            with patch('yt_dlp.YoutubeDL') as dl, patch.object(v,'ffmpeg_path',return_value='/bin/ffmpeg'):
                dl.return_value.__enter__.return_value.download.side_effect=lambda urls:(work/'source.mp4').write_bytes(b'video')
                v.obtain_source('https://www.douyin.com/jingxuan/car?modal_id=123',work,lambda _:None,cookie)
                self.assertEqual(dl.return_value.__enter__.return_value.download.call_args.args[0],['https://www.douyin.com/video/123'])
                self.assertEqual(dl.call_args.args[0]['cookiefile'],str(work/'cookies.txt'))
                self.assertEqual(cookie.read_text(),'# Netscape HTTP Cookie File\n')
    def test_cookie_error(self):
        with tempfile.TemporaryDirectory() as td, patch('yt_dlp.YoutubeDL') as dl, patch.object(v,'ffmpeg_path',return_value='/bin/ffmpeg'):
            dl.return_value.__enter__.return_value.download.side_effect=Exception('Fresh cookies (not necessarily logged in) are needed')
            with self.assertRaisesRegex(RuntimeError,'Douyin yêu cầu cookies mới'):
                v.obtain_source('https://www.douyin.com/video/123',Path(td),lambda _:None)
    def test_local_without_cookies(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'video.mp4'; p.touch()
            self.assertEqual(v.obtain_source(str(p),Path(td),lambda _:None,'missing'),p.resolve())
if __name__=='__main__': unittest.main()
