import os,json,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from unittest.mock import patch,Mock
from PySide6.QtCore import QTimer,QEventLoop
from PySide6.QtWidgets import QApplication
from editor_core import validate_rows,preview_items,save_project
from subtitle_editor import SubtitleEditor
from video_player import VideoPlayer
import video_translator as v

def wait(ms):
 loop=QEventLoop();QTimer.singleShot(ms,loop.quit);loop.exec()
class EditorTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'video.mp4';self.source.write_bytes(b'test-source')
  self.info={'width':1024,'height':576,'duration':3};self.rows=[{'start':0,'end':1,'zh':'你好','vi':'Xin chào','box':[100,400,400,430]}]
 def tearDown(self):self.tmp.cleanup()
 def test_manual_position_and_time_validation(self):
  row=dict(self.rows[0],position=[512,300]);items=preview_items([row],self.info,'Arial',{});self.assertEqual(items[0][2:4],(512.,300.))
  for bad in [{'start':2,'end':1},{'start':float('nan')},{'position':[5000,20]},{'vi':''}]:
   with self.assertRaises(ValueError):validate_rows([dict(row,**bad)],self.info)
 def test_save_and_edit_row(self):
  path=self.root/'rows.translations.json';path.write_text(json.dumps(self.rows))
  e=SubtitleEditor(lambda:None);e.load_translation(path,self.source,self.info,'Arial',{});e.table.item(0,3).setText('Chào bạn');e.table.item(0,4).setText('512');e.table.item(0,5).setText('300')
  changed=e.snapshot();self.assertEqual(changed[0]['vi'],'Chào bạn');self.assertEqual(changed[0]['position'],[512.,300.]);e.save()
  project=json.loads(e.project_path.read_text(encoding='utf-8'));self.assertEqual(project['rows'][0]['vi'],'Chào bạn');self.assertIn('source_sha256',project);e.close()
 def test_ass_manual_positions(self):
  path=self.root/'test.ass';v.create_ass([v.Cue(0,1,'你好',(100,400,400,430))],['Xin chào'],self.info,path,positions=[[512,300]])
  self.assertIn('\\pos(512,300)',path.read_text(encoding='utf-8-sig'))
 def test_export_avoids_ocr_and_api(self):
  with patch.object(v,'probe',return_value=dict(self.info,has_audio=True)),patch.object(v,'render') as render,patch.object(v,'translate',side_effect=AssertionError('API called')),patch.object(v,'extract_frames',side_effect=AssertionError('OCR called')):
   out=self.root/'edited.mp4';v.render_edited(self.source,out,self.rows,'Arial',{});render.assert_called_once();self.assertTrue(out.with_suffix('.project.json').is_file())
 def test_add_and_delete(self):
  path=self.root/'rows.translations.json';path.write_text(json.dumps(self.rows));e=SubtitleEditor(lambda:None);e.load_translation(path,self.source,self.info,'Arial',{});e.add_row();self.assertEqual(e.table.rowCount(),2);e.delete_rows();self.assertEqual(e.table.rowCount(),1);e.close()
 def test_processing_pause_button(self):
  from types import SimpleNamespace
  from pause_control import PauseController
  app,w=v.launch_gui(test_mode=True);control=PauseController(w.pause_state);w.worker=SimpleNamespace(isRunning=lambda:True,control=control)
  w.pause_button.setEnabled(True);w.pause_button.click();self.assertTrue(control.requested);self.assertEqual(w.pause_button.text(),'Tiếp tục')
  w.pause_button.click();self.assertFalse(control.requested);self.assertEqual(w.pause_button.text(),'Tạm dừng');w.worker=None;w.close()
 def test_finished_video_moves_to_step_4_editor(self):
  app,w=v.launch_gui(test_mode=True);out=self.root/'translated_vi.mp4'
  out.write_bytes(b'out');out.with_suffix('.translations.json').write_text(json.dumps(self.rows),encoding='utf-8')
  save_project(out.with_suffix('.project.json'),self.source,self.rows,self.info,'Arial',{})
  w.preview.load=Mock();w.preview.set_subtitles=Mock()
  w.done(str(out));wait(20)
  self.assertEqual(w.editor.table.rowCount(),1)
  self.assertEqual(w.source.text(),str(self.source.resolve()))
  self.assertIn('phần 4',w.status.text())
  w.preview.load.assert_called_with(str(self.source.resolve()))
  w.close()
class LoaderTests(unittest.TestCase):
 def test_one_reader_and_model_change(self):
  import ocr_loader,types,torch
  with tempfile.TemporaryDirectory() as d:
   model=Path(d)/'model.pth';model.write_bytes(b'a');ocr_loader._cache.clear()
   fake=types.SimpleNamespace(Reader=lambda *a,**k:object())
   with patch.dict('sys.modules',{'easyocr':fake}),patch.object(fake,'Reader',wraps=fake.Reader) as reader:
    a,_=ocr_loader.get_reader(d,False,lambda _:None);b,_=ocr_loader.get_reader(d,False,lambda _:None);self.assertIs(a,b);self.assertEqual(reader.call_count,1)
    model.write_bytes(b'new');c,_=ocr_loader.get_reader(d,False,lambda _:None);self.assertIsNot(a,c);self.assertEqual(reader.call_count,2)
   ocr_loader._cache.clear()
if __name__=='__main__':unittest.main()
