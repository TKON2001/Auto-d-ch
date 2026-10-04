"""Cooperative OCR/API pause and native suspension of owned encoder processes."""
import threading,os,signal
class PosixChild:
    def __init__(self,pid):self.pid=pid
    def suspend(self):os.kill(self.pid,signal.SIGSTOP)
    def resume(self):os.kill(self.pid,signal.SIGCONT)
class PauseController:
    def __init__(self,on_state=lambda _:None):
        self._condition=threading.Condition();self.requested=False;self._children={};self._suspended=set();self.on_state=on_state
    def pause(self):
        with self._condition:
            if self.requested:return
            self.requested=True;paused=False
            for pid,process in list(self._children.items()):
                try:process.suspend();self._suspended.add(pid);paused=True
                except Exception as exc:self.on_state('pause_error:'+str(exc))
            self.on_state('paused' if paused else 'pausing')
    def resume(self):
        with self._condition:
            self.requested=False
            for pid in list(self._suspended):
                try:self._children[pid].resume();self._suspended.discard(pid)
                except Exception as exc:self.on_state('pause_error:'+str(exc))
            self._condition.notify_all();self.on_state('running')
    def check(self):
        with self._condition:
            if self.requested:self.on_state('paused')
            while self.requested:self._condition.wait()
    def register(self,proc):
        with self._condition:
            if proc.pid in self._children:return
            if os.name=='nt':
                import psutil
                process=psutil.Process(proc.pid)
            else:process=PosixChild(proc.pid)
            self._children[proc.pid]=process
            if self.requested:
                process.suspend();self._suspended.add(proc.pid);self.on_state('paused')
    def unregister(self,proc):
        with self._condition:
            process=self._children.pop(proc.pid,None)
            if process and proc.pid in self._suspended:
                try:process.resume()
                except Exception:pass
            self._suspended.discard(proc.pid)
