"""One retained Reader per process; no concurrent duplicate model initialization."""
from pathlib import Path
import threading,time
_lock=threading.Lock();_cache={}
def get_reader(model_path,gpu=False,log=print):
    started=time.monotonic();done=threading.Event()
    def heartbeat():
        while not done.wait(3):log(f'Đang chuẩn bị OCR… {time.monotonic()-started:.0f}s')
    threading.Thread(target=heartbeat,daemon=True).start()
    try:
        log('Kiểm tra thư viện và thiết bị OCR…')
        import torch
        gpu=bool(gpu and torch.cuda.is_available())
        from resource_limits import cpu_threads
        torch.set_num_threads(cpu_threads())
        try:torch.set_num_interop_threads(1)
        except RuntimeError:pass
        log(f'Giới hạn OCR: {cpu_threads()} luồng CPU; giữ tài nguyên cho ứng dụng khác')
        path=Path(model_path).resolve()
        key=(str(path),gpu,tuple((f.name,f.stat().st_size,f.stat().st_mtime_ns) for f in sorted(path.glob('*.pth'))))
        with _lock:
            if key in _cache:
                log('Dùng lại model OCR đã nạp trong phiên');return _cache[key],gpu
            log('Nạp bộ dò chữ và nhận dạng EasyOCR từ máy…')
            import easyocr
            reader=easyocr.Reader(['ch_sim','en'],gpu=gpu,model_storage_directory=str(path),download_enabled=False,verbose=False)
            _cache.clear();_cache[key]=reader
        log(f'OCR sẵn sàng sau {time.monotonic()-started:.1f}s');return reader,gpu
    finally:done.set()
