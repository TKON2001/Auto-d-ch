import unittest,threading,time,subprocess,sys,os
from pause_control import PauseController
class PauseTests(unittest.TestCase):
 def test_checkpoint_waits_and_resumes(self):
  states=[];control=PauseController(states.append);control.pause();done=threading.Event();thread=threading.Thread(target=lambda:(control.check(),done.set()));thread.start()
  self.assertFalse(done.wait(.1));self.assertIn('paused',states);control.resume();self.assertTrue(done.wait(1));thread.join()
 def test_owned_process_suspend_and_resume(self):
  import psutil
  process=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'])
  control=PauseController()
  try:
   control.register(process);control.pause()
   if os.name=='nt':self.assertEqual(psutil.Process(process.pid).status(),psutil.STATUS_STOPPED)
   else:self.assertTrue(os.WIFSTOPPED(os.waitpid(process.pid,os.WUNTRACED)[1]))
   control.resume()
   if os.name!='nt':self.assertTrue(os.WIFCONTINUED(os.waitpid(process.pid,os.WCONTINUED)[1]))
  finally:control.unregister(process);process.terminate();process.wait(timeout=3)
if __name__=='__main__':unittest.main()
