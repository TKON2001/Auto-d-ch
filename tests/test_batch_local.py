import tempfile,unittest,json,threading,time
from pathlib import Path
from unittest.mock import Mock
from batch_core import BatchQueue,digest,open_video_project,copy_local_video,local_source
from pause_control import PauseController
class LocalTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'Video tiếng Trung.mp4';self.source.write_bytes(b'local video');self.file=self.root/'list.csv';self.file.write_text(f'STT,Link,Tên\n2,{self.root / "missing.mp4"},Missing\n1,"{self.source}",Local\n',encoding='utf-8-sig')
 def tearDown(self):self.temp.cleanup()
 def info(self,p):return {'duration':2,'width':320,'height':240,'has_audio':True}
 def test_copy_no_network_and_resume_change(self):
  q=BatchQueue(self.file,self.root/'out');network=Mock(side_effect=AssertionError('Network not allowed'));q.run(PauseController(),downloader=network,probe=self.info);network.assert_not_called();self.assertEqual([j['status'] for j in q.jobs],['completed','failed']);self.assertIn('Không tìm thấy',q.jobs[1]['error']);self.assertEqual((q.root/q.jobs[0]['video']).read_bytes(),self.source.read_bytes())
  restored=open_video_project(q.root/q.jobs[0]['project'],self.root/'imported');self.assertEqual(digest(restored),digest(self.source))
  self.source.write_bytes(b'changed source');q=BatchQueue(self.file,self.root/'out');q.run(PauseController(),downloader=network,probe=self.info);self.assertEqual((q.root/q.jobs[0]['video']).read_bytes(),b'changed source');network.assert_not_called()
 def test_relative_quoted_and_uri(self):
  self.assertEqual(local_source('"Video tiếng Trung.mp4"',self.file),str(self.source));self.assertEqual(local_source(self.source.as_uri(),self.file),str(self.source))
 def test_pause_copy(self):
  folder=self.root/'copy';folder.mkdir();control=PauseController();control.pause();done=[]
  t=threading.Thread(target=lambda:done.append(copy_local_video({'local_path':str(self.source)},folder,control,lambda _:None)));t.start();time.sleep(.05);self.assertFalse(done);control.resume();t.join(2);self.assertFalse(t.is_alive());self.assertEqual(done[0].read_bytes(),self.source.read_bytes())
if __name__=='__main__':unittest.main()
