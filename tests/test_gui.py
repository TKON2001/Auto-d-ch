import os,tempfile,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QDialog,QLineEdit,QDialogButtonBox
import components,video_translator
class Checks(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
  self.mock=patch.object(components,'data_dir',return_value=self.root);self.mock.start()
  self.app,self.win=video_translator.launch_gui(test_mode=True)
 def tearDown(self): self.win.close();self.mock.stop();self.tmp.cleanup()
 def test_local_models_file_and_persistence(self):
  for n in ('craft_mlt_25k.pth','zh_sim_g2.pth'): (self.root/n).write_bytes(b'test')
  self.assertEqual(components.use_local_models(self.root/'zh_sim_g2.pth'),self.root)
  self.assertEqual(components.model_dir(),self.root)
 def test_model_missing(self):
  with self.assertRaisesRegex(RuntimeError,'Thiếu model'): components.use_local_models(self.root)
 def test_ffmpeg_root_and_file(self):
  platform=patch.object(components,'is_windows',return_value=False);platform.start();self.addCleanup(platform.stop)
  b=self.root/'bin';b.mkdir()
  for n in ('ffmpeg','ffprobe'): (b/n).write_bytes(b'test')
  with patch.object(components.subprocess,'run',side_effect=lambda cmd,**kw:__import__('types').SimpleNamespace(stdout=(Path(cmd[0]).stem+' version test').encode())):
   self.assertEqual(components.use_local_ffmpeg(self.root),b)
   self.assertEqual(components.use_local_ffmpeg(b/'ffmpeg'),b)
  self.assertEqual(components.find_binary('ffmpeg'),str(b/'ffmpeg'))
 def test_dialog_pasted_path(self):
  for n in ('craft_mlt_25k.pth','zh_sim_g2.pth'): (self.root/n).write_bytes(b'test')
  def apply():
   dlg=QApplication.activeModalWidget();self.assertIsInstance(dlg,QDialog)
   dlg.findChild(QLineEdit).setText(str(self.root))
   dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
  QTimer.singleShot(30,apply);self.win.pick_local_models()
  self.assertEqual(components.model_dir(),self.root)
 def test_dialog_from_settings(self):
  def nested():
   settings=QApplication.activeModalWidget()
   QTimer.singleShot(30,lambda: QApplication.activeModalWidget().reject())
   self.win.pick_local_models()
   self.assertIs(QApplication.activeModalWidget(),settings)
   settings.reject()
  QTimer.singleShot(30,nested);self.win.open_settings()
 def test_video_output_and_api(self):
  with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',return_value=(str(self.root/'测试.mp4'),'')),patch.object(video_translator,'probe',return_value={'width':1920,'height':1080,'duration':1}): self.win.pick_file()
  self.assertTrue(self.win.source.text().endswith('测试.mp4'))
  with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(self.root/'out'),'')):self.win.pick_output()
  self.assertTrue(self.win.out.text().endswith('out.mp4'))
  self.win.api.setText('dummy');self.assertEqual(self.win.api.text(),'dummy')
if __name__=='__main__': unittest.main()
