import unittest
from PySide6.QtWidgets import QPushButton
from video_translator import launch_gui
class InlineTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app,cls.window=launch_gui(test_mode=True);cls.window.show();cls.app.processEvents()
 @classmethod
 def tearDownClass(cls):cls.window.close();cls.app.processEvents()
 def test_embedded_in_source_no_dialog(self):
  w=self.window;self.assertFalse(w.batch.isWindow());self.assertIn(w.batch_toggle,w.batch.parent().findChildren(QPushButton));self.assertFalse(any(b.text()=='Tải Excel' for b in w.findChildren(QPushButton)));w.batch_toggle.setChecked(True);self.app.processEvents();self.assertTrue(w.batch.isVisible());w.batch_toggle.setChecked(False);self.assertFalse(w.batch.isVisible())
 def test_busy_blocks_other_jobs(self):
  w=self.window;w.batch_running(True);self.assertFalse(w.start.isEnabled());self.assertFalse(w.download.isEnabled());w.batch_running(False);self.assertTrue(w.start.isEnabled());self.assertTrue(w.download.isEnabled())
if __name__=='__main__':unittest.main()
