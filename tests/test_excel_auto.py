import unittest,tempfile,time
from pathlib import Path
from unittest.mock import patch
from video_translator import launch_gui
class AutoExcelTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.video=self.root/'movie.mp4';self.video.write_bytes(b'test video');self.csv=self.root/'list.csv';self.csv.write_text(f'STT,Link,Tên\n1,{self.video},One\n2,{self.video},Two\n',encoding='utf-8-sig');self.app,self.win=launch_gui(test_mode=True);self.win.batch.dest.setText(str(self.root/'out'))
 def tearDown(self):self.win.close();self.app.processEvents();self.tmp.cleanup()
 def info(self,*_):return {'duration':1,'width':320,'height':240,'has_audio':False}
 def test_choose_file_auto_loads_no_manual_select(self):
  with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',return_value=(str(self.csv),'')),patch('video_translator.probe',side_effect=self.info):self.win.batch.pick_excel()
  self.assertEqual(self.win.source.text(),str(self.video));self.assertEqual(self.win.batch.table.rowCount(),2);self.assertTrue(self.win.batch.use_list.isChecked());self.assertIn('2 video',self.win.start.text());self.assertTrue(self.win.source.isReadOnly())
  self.win.batch.table.selectRow(0);self.win.batch.queue.jobs[0].update(status='completed',video=str(self.video));self.win.batch.select_video();self.assertTrue(self.win.batch.use_list.isChecked())
 def test_choose_then_main_start_runs_all_without_import_click(self):
  seen=[]
  def process(source_value,output,**_):seen.append(source_value);Path(output).write_bytes(b'rendered');return output
  with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',return_value=(str(self.csv),'')),patch('video_translator.probe',side_effect=self.info),patch('video_translator.process',side_effect=process):
   self.win.batch.pick_excel();self.win.api.setText('TEST_ONLY');self.win.start_job();limit=time.monotonic()+3
   while self.win.worker.isRunning() and time.monotonic()<limit:self.app.processEvents();time.sleep(.01)
   self.app.processEvents();self.assertFalse(self.win.worker.isRunning());self.assertEqual(len(seen),2);self.assertIn('Đã dịch 2/2',self.win.status.text())
if __name__=='__main__':unittest.main()
