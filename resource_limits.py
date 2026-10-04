"""CPU budget tuned for OCR throughput without starving the desktop."""
import os

def cpu_threads():
    count=max(1, os.cpu_count() or 1)
    return max(1, min(8, count // 2))

def configure_cv(cv):
    cv.setNumThreads(max(1, min(4, os.cpu_count() or 1)))
    try:cv.ocl.setUseOpenCL(False)
    except AttributeError:pass

def background_flags():
    # Applies to FFmpeg only, not the GUI or unrelated programs.
    return 0x08000000 | 0x00004000 if os.name=='nt' else 0
