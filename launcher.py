"""First-run setup GUI using Python's built-in Tkinter (no pip libraries required)."""
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess, sys, threading, queue, os, shutil, ctypes
from pathlib import Path
root=Path(__file__).resolve().parent
venv=root/'.runtime'
python=venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
flags=0x08000000 if os.name=='nt' else 0
messages=queue.Queue()
app=tk.Tk(); app.title('Frame — Cài đặt và khởi chạy'); app.geometry('690x430'); app.configure(bg='#101112')
label=tk.Label(app,text='Frame Video Translator',bg='#101112',fg='#f3f4f4',font=('Segoe UI',23)); label.pack(pady=22)
tk.Label(app,text='Tải thư viện vào môi trường riêng, sau đó mở ứng dụng.',bg='#101112',fg='#a6adaf').pack()
logs=tk.Text(app,bg='#1b1e20',fg='#a7e5d3',height=13,relief='flat'); logs.pack(fill='both',expand=True,padx=22,pady=16)
busy=False

# Windows MAX_PATH is 260. PySide6/torch files under the venv add ~100–130 characters.
# 60 was a false-positive cutoff (this project folder is already ~69).
MAX_VENV_CHARS=120
FILE_ATTRIBUTE_REPARSE_POINT=0x400

def command(args):
    process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=flags)
    for line in process.stdout: messages.put(line.rstrip())
    if process.wait(): raise RuntimeError('Cài đặt thất bại. Xem nhật ký phía trên và thử lại.')

def is_reparse(path):
    if os.name!='nt':
        return path.is_symlink()
    try:
        attrs=ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return attrs!=-1 and bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return path.is_symlink()

def junction(link, target):
    target.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink() or is_reparse(link):
        try:
            if link.resolve()==target.resolve():
                return
        except OSError:
            pass
        raise RuntimeError('Thư mục .runtime đã tồn tại ở đường dẫn dài. Đổi tên hoặc xóa .runtime rồi chạy lại START_WINDOWS.bat. Không sao chép .runtime từ máy khác.')
    result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(target)],capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=flags)
    if result.returncode:
        detail=(result.stderr or result.stdout or 'mklink thất bại').strip()
        raise RuntimeError('Không tạo được đường dẫn ngắn cho Qt: '+detail)

def prepare_venv():
    if os.name!='nt':
        return venv
    n=len(str(venv.resolve()))
    if n<=MAX_VENV_CHARS:
        return venv
    local=os.environ.get('LOCALAPPDATA') or os.environ.get('TEMP') or r'C:\Users\Public'
    short=Path(local)/'Frame'/'runtime'
    if len(str(short.resolve() if short.exists() else short))>MAX_VENV_CHARS:
        for candidate in (Path(r'C:\Frame\runtime'), Path(r'D:\Frame\runtime')):
            if len(str(candidate))<=MAX_VENV_CHARS:
                short=candidate
                break
    messages.put(f'Đường dẫn dự án dài ({n} ký tự). Cài thư viện vào {short}')
    junction(venv, short)
    return venv

def setup():
    global busy
    if busy: return
    busy=True; button.config(state='disabled')
    def work():
        try:
            prepare_venv()
            valid=False
            if python.exists():
                try:
                    check=subprocess.run([str(python),'-c','import sys; print(sys.base_prefix)'],capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=flags)
                    valid=check.returncode==0 and Path(check.stdout.strip()).is_dir()
                except OSError: pass
            if not valid:
                if venv.exists() and not is_reparse(venv):
                    messages.put('Môi trường cũ không còn hợp lệ; tạo lại trên máy này…')
                    shutil.rmtree(venv)
                elif venv.exists() and is_reparse(venv):
                    messages.put('Môi trường cũ không còn hợp lệ; tạo lại trên máy này…')
                    try:
                        real=venv.resolve()
                    except OSError:
                        real=None
                    venv.rmdir()
                    if real and real.exists():
                        shutil.rmtree(real, ignore_errors=True)
                    prepare_venv()
            if not valid:
                messages.put('Tạo môi trường Python riêng…'); command([sys.executable,'-m','venv',str(venv)])
            try:
                subprocess.run([str(python),'-c','from importlib.util import find_spec; from importlib.metadata import version; assert all(find_spec(x) is not None for x in ("PySide6","easyocr","cv2","openai","psutil","openpyxl","yt_dlp")); assert int(version("openai").split(".")[0])>=2'],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=flags)
                ready=True
            except subprocess.CalledProcessError: ready=False
            if not ready: command([str(python),'-m','pip','install','--upgrade','pip'])
            if not ready: command([str(python),'-m','pip','install','-r',str(root/'requirements.txt')])
            subprocess.Popen([str(python),str(root/'video_translator.py')],cwd=root,creationflags=flags)
            messages.put('__DONE__')
        except Exception as e: messages.put('__ERROR__'+str(e))
    threading.Thread(target=work,daemon=True).start()
button=tk.Button(app,text='Tải thành phần và mở ứng dụng',command=setup,bg='#a7e5d3',fg='#101112',font=('Segoe UI',12),relief='flat'); button.pack(pady=(0,18))
def poll():
    global busy
    while not messages.empty():
        msg=messages.get()
        if msg=='__DONE__': busy=False; button.config(state='normal'); logs.insert('end','Đã mở ứng dụng. FFmpeg và model OCR đã kèm bộ cài. Bấm Thêm video để bắt đầu.\n')
        elif msg.startswith('__ERROR__'): busy=False; button.config(state='normal'); messagebox.showerror('Cài đặt thất bại',msg[9:])
        else: logs.insert('end',msg+'\n'); logs.see('end')
    app.after(150,poll)
def close():
    if busy: messagebox.showinfo('Đang cài đặt','Chờ cài đặt hoàn tất trước khi đóng.')
    else: app.destroy()
app.protocol('WM_DELETE_WINDOW',close); poll(); app.mainloop()
