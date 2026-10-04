"""Progress reporting and hardware encode preflight with CPU fallback."""
import subprocess,tempfile,time,os
from pathlib import Path
from functools import lru_cache
from resource_limits import cpu_threads,background_flags

@lru_cache(maxsize=4)
def nvenc_available(ffmpeg):
    flags=background_flags()
    try:
        return subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=size=64x64:rate=1','-frames:v','1','-c:v','h264_nvenc','-f','null','-'],capture_output=True,timeout=15,creationflags=flags).returncode==0
    except (OSError,subprocess.TimeoutExpired):return False


def render_video(ffmpeg,source,output,filter_text,has_audio,duration,log,controller=None):
    check=controller.check if controller else (lambda:None);check()
    flags=background_flags()
    encoder=['-c:v','libx264','-preset','veryfast','-crf','19']
    if nvenc_available(ffmpeg):encoder=['-c:v','h264_nvenc','-preset','p4','-cq','19','-b:v','0']
    log(f'Chế độ nhẹ CPU: {cpu_threads()} luồng xuất, 1 luồng lọc phụ đề')
    tmp=None
    try:
        fd,name=tempfile.mkstemp(prefix=output.stem+'_render_',suffix='.mp4',dir=output.parent);os.close(fd);tmp=Path(name)
        for attempt in range(2):
            check()
            log('Xuất video bằng '+('NVIDIA NVENC' if 'h264_nvenc' in encoder else 'CPU x264'))
            cmd=[ffmpeg,'-y','-v','warning','-threads',str(cpu_threads()),'-filter_threads','1','-i',str(source),'-vf',filter_text]+encoder+['-threads',str(cpu_threads())]
            cmd+=['-map','0:v:0','-map','0:a?','-c:a','copy'] if has_audio else ['-map','0:v:0','-an']
            cmd+=['-movflags','+faststart','-pix_fmt','yuv420p','-progress','pipe:1','-nostats',str(tmp)]
            with tempfile.TemporaryFile() as err:
                proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=err,text=True,encoding='utf-8',errors='replace',creationflags=flags)
                last=-10.;started=time.monotonic()
                try:
                    if controller:controller.register(proc)
                    for line in proc.stdout:
                        key,sep,value=line.strip().partition('=')
                        if key=='out_time_us' and sep:
                            try:t=int(value)/1000000
                            except ValueError:continue
                            now=time.monotonic()
                            if now-last>=2:
                                percent=min(99,max(0,int(t/max(duration,.01)*100)))
                                log(f'Đang xuất video: {percent}% • {now-started:.0f}s');last=now
                    code=proc.wait()
                finally:
                    if controller:controller.unregister(proc)
                    proc.stdout.close()
                    if proc.poll() is None:proc.kill();proc.wait()
                if code==0:check();os.replace(tmp,output);log('Đang xuất video: 100%');return
                err.seek(0);message=err.read().decode('utf-8','replace')[-1500:]
            if 'h264_nvenc' in encoder:
                log('NVENC không xuất được video này, chuyển sang CPU…');encoder=['-c:v','libx264','-preset','veryfast','-crf','19'];continue
            raise RuntimeError('FFmpeg lỗi: '+message)
        raise RuntimeError('Không xuất được video.')
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)
