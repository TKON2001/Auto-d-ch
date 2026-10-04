"""Install optional runtime components into a writable per-user directory."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

def data_dir():
    root=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'FrameVideoTranslator'
    root.mkdir(parents=True,exist_ok=True)
    return root

def is_windows():return os.name=='nt'

FFMPEG_URL='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
FFMPEG_FALLBACK_URL='https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'
_validation_cache={}

def pe_payload_end(stream, size):
    """Return the last byte covered by PE section raw data, or None if not a PE."""
    head=stream.read(64)
    if len(head)<64 or head[:2]!=b'MZ':
        return None
    offset=int.from_bytes(head[60:64],'little')
    if offset<64 or offset>size-6:
        raise RuntimeError('header EXE bị hỏng.')
    stream.seek(offset)
    header=stream.read(24)
    if len(header)<24 or header[:4]!=b'PE\0\0':
        raise RuntimeError('thiếu header PE Windows.')
    nsections=int.from_bytes(header[6:8],'little')
    opt_size=int.from_bytes(header[20:22],'little')
    stream.seek(offset+24+opt_size)
    end=0
    for _ in range(nsections):
        section=stream.read(40)
        if len(section)<40:
            raise RuntimeError('bảng section PE bị cắt.')
        raw_size=int.from_bytes(section[16:20],'little')
        raw_ptr=int.from_bytes(section[20:24],'little')
        if raw_size:
            end=max(end, raw_ptr+raw_size)
    return end

def bundled_ffmpeg_dir():
    roots=[Path(__file__).resolve().parent/'ffmpeg']
    if getattr(sys,'frozen',False):roots.insert(0,Path(sys.executable).parent/'ffmpeg')
    suffix='.exe' if is_windows() else ''
    for root in roots:
        if (root/('ffmpeg'+suffix)).is_file() and (root/('ffprobe'+suffix)).is_file():
            return root
    return roots[0]

def unblock_windows_file(path):
    try: os.remove(str(path)+':Zone.Identifier')
    except OSError: pass

def oserror_hint(path, exc):
    code=getattr(exc,'winerror',None)
    if code==5:
        detail='Windows từ chối truy cập (WinError 5). Kiểm tra quyền tệp và Windows Security; không tắt antivirus.'
    elif code==193:
        detail='Windows không nạp được EXE (WinError 193). Tệp có thể bị cắt, sai kiến trúc, hoặc Windows Security đang quét. Hãy bấm Dùng FFmpeg kèm theo hoặc Kiểm tra / sửa thành phần.'
    elif code==225:
        detail='Windows Security đang chặn tệp (WinError 225). Chờ quét xong hoặc khôi phục ffmpeg.exe trong Bảo vệ chống virus, rồi thử lại.'
    else:
        detail=str(exc) or exc.__class__.__name__
        if code is not None: detail=f'WinError {code}: {detail}'
    return f'Không chạy được {path}: {detail}'

def validate_pe(path):
    path=Path(path)
    if not path.is_file():raise RuntimeError(f'Thiếu tệp: {path}')
    if not is_windows():return
    stat=path.stat()
    with path.open('rb') as stream:
        try:
            needed=pe_payload_end(stream, stat.st_size)
        except RuntimeError as exc:
            raise RuntimeError(f'{path.name}: {exc}') from exc
        if needed is None:
            raise RuntimeError(f'{path.name} không phải chương trình Windows hợp lệ (có thể tải nhầm HTML/ZIP hoặc tệp hỏng).')
        if needed>stat.st_size:
            raise RuntimeError(f'{path.name} bị cắt cụt ({stat.st_size} byte, cần {needed} byte). Bấm Kiểm tra / sửa thành phần để tải lại, hoặc chọn ZIP Gyan.dev đã giải nén đủ.')

def check_version(path):
    kwargs=dict(stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,stdin=subprocess.DEVNULL)
    if is_windows():
        kwargs['creationflags']=0x08000000
        kwargs['cwd']=str(Path(path).parent)
    def once():
        completed=subprocess.run([str(path),'-version'],check=True,**kwargs)
        output=(getattr(completed,'stdout',None) or b'')+(getattr(completed,'stderr',None) or b'')
        if isinstance(output,str):output=output.encode()
        marker=path.stem.lower().encode()+b' version'
        if marker not in output.lower()[:400] and not output.lower().lstrip().startswith(marker):
            raise RuntimeError(f'{path.name} không trả đúng thông tin phiên bản.')
    try:
        once()
    except OSError:
        try: once()
        except OSError as exc: raise exc
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:
        raise RuntimeError(f'Kiểm tra {path} thất bại: {exc}') from exc

def copy_to_user_bin(path):
    dest_dir=data_dir()/'bin'
    dest_dir.mkdir(parents=True,exist_ok=True)
    dest=dest_dir/path.name
    if dest.resolve()!=path.resolve():
        shutil.copy2(path,dest)
    unblock_windows_file(dest)
    try: dest.chmod(0o755)
    except OSError: pass
    return dest

def validate_binary(path):
    path=Path(path)
    if not path.is_file():raise RuntimeError(f'Thiếu tệp: {path}')
    stat=path.stat();key=(str(path.resolve()),stat.st_size,stat.st_mtime_ns,os.name)
    if key in _validation_cache:return _validation_cache[key]
    validate_pe(path)
    unblock_windows_file(path)
    try:
        check_version(path)
        _validation_cache[key]=path
        return path
    except OSError as exc:
        dest=copy_to_user_bin(path)
        if dest.resolve()!=path.resolve():
            try:
                validate_pe(dest); check_version(dest)
                _validation_cache[key]=dest
                return dest
            except (RuntimeError,OSError):
                pass
        raise RuntimeError(oserror_hint(path,exc)) from exc

def binary_candidates(name):
    filename=name+('.exe' if is_windows() else '')
    roots=[Path(local_settings().get('bin',str(data_dir()/'bin'))),data_dir()/'bin',bundled_ffmpeg_dir()]
    if getattr(sys,'frozen',False):roots.insert(0,Path(sys.executable).parent/'ffmpeg')
    candidates=[root/filename for root in roots]
    system=shutil.which(name)
    if system:candidates.append(Path(system))
    return list(dict.fromkeys(candidates))

def find_binary(name):
    for path in binary_candidates(name):
        try:return str(validate_binary(path))
        except (RuntimeError,OSError):continue
    return None

def download_archive(url,destination,log):
    import time
    request=urllib.request.Request(url,headers={'User-Agent':'FrameVideoTranslator/19','Accept-Encoding':'identity'})
    log('Kết nối tải FFmpeg…')
    try:
        with urllib.request.urlopen(request,timeout=30) as response,destination.open('wb') as out:
            if 'text/html' in response.headers.get('Content-Type','').lower():raise RuntimeError('Máy chủ trả trang HTML thay vì ZIP.')
            raw=response.headers.get('Content-Length','0')
            total=int(raw) if raw.isdigit() else 0;done=0;last=0.
            while True:
                chunk=response.read(256*1024)
                if not chunk:break
                out.write(chunk);done+=len(chunk);now=time.monotonic()
                if now-last>=1:
                    value=f'{done*100/total:.1f}%' if total else f'{done/1048576:.1f} MB (không có tổng dung lượng)'
                    log(f'Tải FFmpeg: {value} • {done/1048576:.1f} MB');last=now
            if total and done!=total:raise RuntimeError(f'Tải chưa đủ: {done}/{total} byte.')
            if not done:raise RuntimeError('Máy chủ trả tệp rỗng.')
        if not zipfile.is_zipfile(destination):raise RuntimeError('Tệp tải về không phải ZIP hợp lệ.')
        log(f'Tải FFmpeg hoàn tất: {done/1048576:.1f} MB')
    except (OSError,ValueError) as exc:raise RuntimeError(f'Tải FFmpeg thất bại: {exc}. Có thể chọn FFmpeg có sẵn trong Cài đặt.') from exc

def activate_archive(archive,log=print):
    # Publish one versioned folder only after both tools validate. Never
    # overwrite an active executable or change configuration half way through.
    root=data_dir()/'bin-versions';root.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='ffmpeg-',dir=root));activated=False
    try:
        with zipfile.ZipFile(archive) as z:
            members={}
            for name in ('ffmpeg.exe','ffprobe.exe'):
                matches=[i for i in z.infolist() if i.filename.endswith('/bin/'+name) and not i.is_dir()]
                if len(matches)!=1:raise RuntimeError(f'ZIP thiếu/trùng {name}.')
                info=matches[0]
                if info.file_size<64 or info.file_size>512*1024*1024:raise RuntimeError(f'Dung lượng {name} bất thường.')
                members[name]=info
            for name,info in members.items():
                log('Giải nén và kiểm tra '+name+'…')
                with z.open(info) as source,(stage/name).open('wb') as target:shutil.copyfileobj(source,target,256*1024)
                (stage/name).chmod(0o755)
                validate_binary(stage/name)
            for member in z.infolist():
                base=Path(member.filename).name
                if not member.is_dir() and base.upper().startswith(('LICENSE','COPYING','README')) and member.file_size<=1024*1024:(stage/base).write_bytes(z.read(member))
        save_local('bin',stage);activated=True
        log('Đã chọn bộ FFmpeg đã kiểm tra: '+str(stage))
        return stage
    except (OSError,zipfile.BadZipFile) as exc:raise RuntimeError(f'Không cài được FFmpeg: {exc}') from exc
    finally:
        if not activated:shutil.rmtree(stage,ignore_errors=True)

def install(log=print):
    _validation_cache.clear()  # Re-check permissions/security on explicit repair.
    healthy={name:find_binary(name) for name in ('ffmpeg','ffprobe')}
    if not all(healthy.values()):
        for name in healthy:
            if not healthy[name]:
                for path in binary_candidates(name):
                    if path.is_file():
                        try:validate_binary(path)
                        except (RuntimeError,OSError) as exc:log(str(exc))
        if not is_windows():raise RuntimeError('Tự tải FFmpeg hỗ trợ Windows x64. Trên Linux/macOS hãy cài FFmpeg bằng trình quản lý gói.')
        import platform
        if platform.machine().lower() not in ('amd64','x86_64'):raise RuntimeError('Gói tải tự động dành cho Windows x64; hãy chọn bộ FFmpeg phù hợp máy trong Cài đặt.')
        with tempfile.TemporaryDirectory() as td:
            archive=Path(td)/'ffmpeg.zip'
            last=None
            for url in (FFMPEG_URL, FFMPEG_FALLBACK_URL):
                try:
                    log('Tải FFmpeg từ '+url)
                    download_archive(url,archive,log);activate_archive(archive,log);last=None;break
                except RuntimeError as exc:
                    last=exc; log('Không dùng được nguồn này: '+str(exc))
            if last: raise last
    else:log('FFmpeg và FFprobe đã chạy được; bỏ qua tải lại.')
    for name in ('ffmpeg','ffprobe'):
        path=find_binary(name)
        if not path:raise RuntimeError(f'{name} chưa sẵn sàng. Kiểm tra Windows Security/quyền tệp rồi thử lại.')
        log(name+': '+path)
    folder=model_dir()
    if verify_bundled_models(folder):
        log('Model OCR đã đủ và đúng checksum; bỏ qua tải/nạp model.')
    else:
        log('Kiểm tra/tải model OCR tiếng Trung…')
        import easyocr
        easyocr.Reader(['ch_sim','en'],gpu=False,model_storage_directory=str(folder),verbose=False)
    log('Đã sẵn sàng: FFmpeg, FFprobe và model OCR tiếng Trung.')

def verify_bundled_models(folder):
    import json,hashlib
    manifest=Path(__file__).resolve().parent/'component_hashes.json'
    try:expected=json.loads(manifest.read_text(encoding='utf-8'))['models']
    except (OSError,ValueError,KeyError):return False
    for name in ('craft_mlt_25k.pth','zh_sim_g2.pth'):
        path=Path(folder)/name
        if not path.is_file():return False
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        if digest.hexdigest()!=expected.get(name):return False
    return True


def local_settings():
    import json
    try: return json.loads((data_dir()/'local_components.json').read_text(encoding='utf-8'))
    except (OSError,ValueError): return {}


def save_local(kind, folder):
    import json
    config=local_settings(); config[kind]=str(Path(folder).resolve())
    target=data_dir()/'local_components.json'
    fd,name=tempfile.mkstemp(prefix='components-',suffix='.json',dir=target.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(config,stream)
        os.replace(name,target)
    finally:Path(name).unlink(missing_ok=True)


def model_dir():
    configured=local_settings().get('models')
    if configured and all((Path(configured)/n).is_file() for n in ('craft_mlt_25k.pth','zh_sim_g2.pth')): return Path(configured)
    bundled=Path(getattr(__import__('sys'),'_MEIPASS',Path(__file__).resolve().parent))/'models'
    if all((bundled/n).is_file() for n in ('craft_mlt_25k.pth','zh_sim_g2.pth')): return bundled
    return Path(local_settings().get('models',str(data_dir()/'models')))


def use_local_ffmpeg(folder):
    folder=Path(os.path.expandvars(str(folder).strip().strip('"'))).expanduser()
    if folder.is_file(): folder=folder.parent
    suffix='.exe' if is_windows() else ''
    if not (folder/('ffmpeg'+suffix)).is_file() and (folder/'bin').is_dir(): folder=folder/'bin'
    originals=[]
    for name in ('ffmpeg','ffprobe'):
        binary=folder/(name+suffix)
        if not binary.is_file(): raise RuntimeError(f'Thư mục phải chứa cả ffmpeg{suffix} và ffprobe{suffix}.')
        originals.append(binary)
    working=[]
    for binary in originals:
        working.append(Path(validate_binary(binary)))
    chosen=working[0].parent
    if any(item.parent.resolve()!=chosen.resolve() for item in working):
        chosen=data_dir()/'bin'
        for binary in originals:
            copy_to_user_bin(binary)
        working=[Path(validate_binary(chosen/(item.name))) for item in originals]
        chosen=working[0].parent
    save_local('bin',chosen)
    return chosen


def use_local_models(folder):
    folder=Path(os.path.expandvars(str(folder).strip().strip('"'))).expanduser()
    if folder.is_file(): folder=folder.parent
    required=('craft_mlt_25k.pth','zh_sim_g2.pth')
    missing=[name for name in required if not (folder/name).is_file()]
    if missing: raise RuntimeError('Thiếu model: '+', '.join(missing))
    save_local('models',folder)
    return folder
