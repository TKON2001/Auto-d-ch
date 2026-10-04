import unittest,tempfile,zipfile,types,io
from pathlib import Path
from unittest.mock import patch
import components as c

def pe():
 data=bytearray(100);data[:2]=b'MZ';data[60:64]=(64).to_bytes(4,'little');data[64:68]=b'PE\0\0';return bytes(data)
def archive(path):
 with zipfile.ZipFile(path,'w') as z:
  for n in ['ffmpeg.exe','ffprobe.exe']:z.writestr('release/bin/'+n,pe())
class ComponentTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.p=patch.object(c,'data_dir',return_value=self.root);self.p.start();c._validation_cache.clear()
 def tearDown(self):self.p.stop();self.t.cleanup()
 def test_bad_html_and_winerror(self):
  f=self.root/'ffmpeg.exe';f.write_bytes(b'<html>wrong</html>')
  with patch.object(c,'is_windows',return_value=True):
   with self.assertRaisesRegex(RuntimeError,'Windows hợp lệ'):c.validate_binary(f)
  f.write_bytes(pe());err=OSError('denied');err.winerror=5
  with patch.object(c.subprocess,'run',side_effect=err):
   with self.assertRaisesRegex(RuntimeError,'Windows từ chối'):c.validate_binary(f)
 def test_winerror_193_copies_to_user_bin(self):
  src=self.root/'bundle';src.mkdir()
  for n in ('ffmpeg.exe','ffprobe.exe'):(src/n).write_bytes(pe())
  err=OSError('bad exe');err.winerror=193
  def run(cmd,**kw):
   p=Path(cmd[0])
   if p.parent==src: raise err
   return types.SimpleNamespace(stdout=(p.stem+' version 1').encode(),stderr=b'')
  with patch.object(c,'is_windows',return_value=True),patch.object(c.subprocess,'run',side_effect=run):
   folder=c.use_local_ffmpeg(src)
  self.assertEqual(folder,self.root/'bin')
  self.assertTrue((self.root/'bin'/'ffmpeg.exe').exists())
 def test_truncated_pe_is_rejected(self):
  f=self.root/'ffmpeg.exe'
  data=bytearray(200);data[:2]=b'MZ';data[60:64]=(64).to_bytes(4,'little');data[64:68]=b'PE\0\0'
  data[70:72]=(1).to_bytes(2,'little')  # one section
  data[84:86]=(0).to_bytes(2,'little')  # optional header size
  data[64+24+16:64+24+20]=(80).to_bytes(4,'little')  # SizeOfRawData
  data[64+24+20:64+24+24]=(150).to_bytes(4,'little')  # PointerToRawData
  f.write_bytes(data)
  with patch.object(c,'is_windows',return_value=True):
   with self.assertRaisesRegex(RuntimeError,'cắt cụt'):c.validate_binary(f)
 def test_version_must_match(self):
  f=self.root/'ffmpeg';f.write_bytes(b'exe')
  with patch.object(c,'is_windows',return_value=False),patch.object(c.subprocess,'run',return_value=types.SimpleNamespace(stdout=b'not ffmpeg')):
   with self.assertRaisesRegex(RuntimeError,'phiên bản'):c.validate_binary(f)
 def test_find_skips_bad_override(self):
  a=self.root/'bad';b=self.root/'healthy';a.write_bytes(b'bad');b.write_bytes(b'good')
  with patch.object(c,'binary_candidates',return_value=[a,b]),patch.object(c,'validate_binary',side_effect=[RuntimeError('bad'),b]):self.assertEqual(c.find_binary('ffmpeg'),str(b))
 def test_failed_install_preserves_config(self):
  c.save_local('bin',self.root/'old');before=c.local_settings();z=self.root/'x.zip';archive(z)
  with patch.object(c,'validate_binary',side_effect=[None,RuntimeError('ffprobe bad')]):
   with self.assertRaisesRegex(RuntimeError,'ffprobe bad'):c.activate_archive(z,lambda _:None)
  self.assertEqual(c.local_settings(),before);self.assertEqual(list((self.root/'bin-versions').iterdir()),[])
 def test_success_activates_both(self):
  z=self.root/'x.zip';archive(z)
  def run(cmd,**kw):return types.SimpleNamespace(stdout=(Path(cmd[0]).stem+' version 9.0').encode())
  with patch.object(c,'is_windows',return_value=True),patch.object(c.subprocess,'run',side_effect=run):folder=c.activate_archive(z,lambda _:None)
  self.assertEqual(c.local_settings()['bin'],str(folder));self.assertTrue((folder/'ffprobe.exe').exists())
 def test_unknown_size_and_html(self):
  z=self.root/'x.zip';archive(z);payload=z.read_bytes();logs=[]
  class Response(io.BytesIO):headers={}
  with patch.object(c.urllib.request,'urlopen',return_value=Response(payload)):c.download_archive('https://example.test',self.root/'download.zip',logs.append)
  self.assertTrue(any('không có tổng' in x for x in logs))
  response=Response(b'html');response.headers={'Content-Type':'text/html'}
  with patch.object(c.urllib.request,'urlopen',return_value=response):
   with self.assertRaisesRegex(RuntimeError,'HTML'):c.download_archive('https://example.test',self.root/'bad.zip',lambda _:None)
 def test_install_skips_model_initialization(self):
  with patch.object(c,'find_binary',return_value='/usr/bin/ffmpeg'),patch.object(c,'verify_bundled_models',return_value=True),patch.object(c,'download_archive') as download:
   c.install(lambda _:None);download.assert_not_called()
 def test_truncated_download(self):
  class Response(io.BytesIO):headers={'Content-Length':'100'}
  with patch.object(c.urllib.request,'urlopen',return_value=Response(b'123')):
   with self.assertRaisesRegex(RuntimeError,'Tải chưa đủ'):c.download_archive('https://example.test',self.root/'bad.zip',lambda _:None)
