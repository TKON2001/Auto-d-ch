#!/usr/bin/env python3
"""Translate burned-in Chinese subtitles while preserving source audio."""
from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from urllib.parse import urlsplit, parse_qs
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from components import find_binary, data_dir, model_dir, use_local_ffmpeg, use_local_models, bundled_ffmpeg_dir, install as install_components

VIDEO_EXTS = {'.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v'}


def resource_path(name: str) -> Path:
    """Resolve bundled resources for source and PyInstaller builds."""
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return root / name

from translation_core import DEFAULT_MODEL, MODELS, DEFAULT_INSTRUCTION, translate_context
from ocr_core import scan, group_samples, DEFAULT_REGION, validate_translation_input, scan_settings
from subtitle_layout import layout
from render_core import render_video
from ocr_cache import source_key, load_cache, save_cache


@dataclass
class Cue:
    start: float
    end: float
    text: str
    box: tuple[int, int, int, int]


def run(cmd: list[str], *, capture=True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, encoding='utf-8', errors='replace', stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None,
                          creationflags=0x08000000 if os.name=="nt" else 0)


def ffmpeg_path() -> str:
    p = find_binary('ffmpeg')
    if not p: raise RuntimeError('FFmpeg thiếu hoặc không chạy được. Bấm Kiểm tra / sửa thành phần hoặc chọn bộ FFmpeg hợp lệ trong Cài đặt.')
    return p


def probe(path: Path) -> dict:
    p = find_binary('ffprobe')
    if not p: raise RuntimeError('Không tìm thấy ffprobe (thường đi kèm FFmpeg).')
    raw=run([p,'-v','error','-show_streams','-show_format','-of','json',str(path)]).stdout
    if not raw: raise RuntimeError('FFprobe không trả thông tin video. Kiểm tra ffprobe.exe và tệp nguồn.')
    try: data=json.loads(raw)
    except (ValueError,TypeError) as exc: raise RuntimeError('FFprobe trả thông tin video không hợp lệ.') from exc
    if not isinstance(data,dict) or not isinstance(data.get('streams'),list) or not isinstance(data.get('format'),dict): raise RuntimeError('FFprobe trả cấu trúc video không hợp lệ.')
    v=next((s for s in data['streams'] if s.get('codec_type')=='video'),None)
    if not v: raise RuntimeError('Tệp không có luồng video hợp lệ.')
    dur=float(data['format'].get('duration') or v.get('duration') or 0)
    return {'width':int(v['width']),'height':int(v['height']),'duration':dur,'has_audio':any(s.get('codec_type')=='audio' for s in data['streams'])}


def obtain_source(value: str, work: Path, log: Callable[[str],None], cookie_file=None) -> Path:
    p=Path(value).expanduser()
    if p.is_file(): return p.resolve()
    if not re.match(r'^https?://',value,re.I): raise RuntimeError(f'Không tìm thấy video: {value}')
    from yt_dlp import YoutubeDL
    log('Đang tải video…')
    template=str(work/'source.%(ext)s')
    parsed=urlsplit(value)
    if parsed.hostname in ('www.douyin.com','douyin.com'):
        modal=parse_qs(parsed.query).get('modal_id',[''])[0]
        if modal.isdigit(): value='https://www.douyin.com/video/'+modal
    options={'noplaylist':True,'format':'bv*+ba/b','merge_output_format':'mp4','outtmpl':template,'ffmpeg_location':str(Path(ffmpeg_path()).parent),'no_color':True}
    if cookie_file:
        cookies=Path(cookie_file).expanduser()
        if not cookies.is_file(): raise RuntimeError('Không tìm thấy file cookies đã chọn.')
        with cookies.open(encoding='utf-8-sig') as handle: header=handle.readline().strip()
        if header not in ('# Netscape HTTP Cookie File','# HTTP Cookie File'):
            raise RuntimeError('Cookies phải là file .txt định dạng Netscape, không phải JSON.')
        # Work on a temporary copy: yt-dlp may update the cookie jar on exit.
        copied=work/'cookies.txt'; shutil.copyfile(cookies,copied)
        options['cookiefile']=str(copied)
    try:
        with YoutubeDL(options) as downloader: downloader.download([value])
    except Exception as exc:
        clean=re.sub(r'\x1b\[[0-9;]*m','',str(exc))
        if 'fresh cookies' in clean.lower():
            raise RuntimeError('Douyin yêu cầu cookies mới. Mở video trên trình duyệt, xuất cookies của douyin.com dạng Netscape .txt rồi chọn ở mục Cookies. Nếu vẫn lỗi, xuất lại cookies mới hoặc chọn video có sẵn trên máy.') from None
        raise RuntimeError(clean) from None
    matches=[x for x in work.glob('source.*') if x.suffix.lower() in VIDEO_EXTS]
    if not matches: raise RuntimeError('yt-dlp không tạo được tệp video hỗ trợ.')
    return matches[0]


def extract_frames(video, info, region, fps, work, log, gpu=False, fast=True, checkpoint=None):
    return scan(video,info,model_dir(),log,gpu,checkpoint=checkpoint,fps=fps,region=region)


def cluster(samples,duration,min_gap=.45,sample_step=.125):
    return group_samples(samples,duration,Cue,sample_step=sample_step)


def translate(cues,api_key,model,log,instruction=None,glossary='',checkpoint=None,cache_path=None):
    return translate_context(cues,api_key,model,log,instruction,glossary,checkpoint=checkpoint,cache_path=cache_path)


def ass_time(seconds: float) -> str:
    cs=max(0,round(seconds*100)); h,cs=divmod(cs,360000); m,cs=divmod(cs,6000); s,cs=divmod(cs,100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def ass_escape(s: str) -> str:
    return s.replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')


def create_ass(cues: list[Cue], translations: list[str], info: dict, dest: Path, font='Arial', font_ratio=.038, subtitle_style=None, positions=None):
    style=subtitle_style or {}
    h=info['height']; size=max(12,int(h*float(style.get('size_ratio',font_ratio)))); margin=max(12,int(h*.025))
    font=re.sub(r'[,\r\n]','',font)
    def color(value):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',value): raise ValueError('Màu chữ phải có dạng #RRGGBB')
        return '&H00'+value[5:7]+value[3:5]+value[1:3]
    primary=color(style.get('color','#FFFFFF')); outline_color=color(style.get('outline_color','#000000'))
    bold=-1 if style.get('bold',False) else 0; italic=-1 if style.get('italic',False) else 0
    outline=max(0,min(10,float(style.get('outline',2.2)))); shadow=max(0,min(10,float(style.get('shadow',0))))
    spacing=max(-2,min(20,float(style.get('spacing',0)))); gap=max(0,int(h*float(style.get('gap_ratio',.012))))
    lines=['[Script Info]','ScriptType: v4.00+','WrapStyle: 2',f'PlayResX: {info["width"]}',f'PlayResY: {h}','ScaledBorderAndShadow: yes','',
           '[V4+ Styles]','Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
           f'Style: Vietnamese,{font},{size},{primary},&H000000FF,{outline_color},&H80000000,{bold},{italic},0,0,100,100,{spacing},0,1,{outline},{shadow},2,{margin},{margin},{margin},1','',
           '[Events]','Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    if len(cues)!=len(translations) or any(not isinstance(v,str) or not v.strip() for v in translations):
        raise RuntimeError('Số dòng dịch không khớp OCR hoặc có dòng rỗng; dừng xuất để tránh mất phụ đề.')
    placed=layout(cues,translations,info,font,size,style)
    for i,(cue,(x,y,fontsize,vi,rect)) in enumerate(zip(cues,placed)):
        if positions and positions[i] is not None: x,y=map(round,positions[i])
        tags=f'{{\\an2\\pos({x},{y})\\fs{fontsize}}}'
        lines.append(f'Dialogue: 1,{ass_time(cue.start)},{ass_time(cue.end)},Vietnamese,,0,0,0,,{tags}{ass_escape(vi)}')
    dest.write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')


def ff_filter_path(path: Path) -> str:
    return str(path.resolve()).replace('\\','/').replace(':','\\:').replace("'","\\'")


def render(source,output,assfile,has_audio,log,duration=None,controller=None):
    if duration is None: duration=probe(source)['duration']
    render_video(ffmpeg_path(),source,output,f"subtitles='{ff_filter_path(assfile)}'",has_audio,duration,log,controller)


def process(source_value: str, output: Path, api_key: str, model=DEFAULT_MODEL, fps=1.5, region=DEFAULT_REGION, font='Arial', font_ratio=.038, gpu=False, log=print, cookie_file=None, fast=True, subtitle_style=None, instruction=None, glossary="", force_ocr=False,controller=None):
    check=controller.check if controller else (lambda:None);check()
    sample_step,region=scan_settings(fps,region)
    if not api_key: raise RuntimeError('Thiếu OPENAI_API_KEY. Nhập khóa trong ứng dụng hoặc cấu hình biến môi trường.')
    ffmpeg_path()  # Validate before OCR/API work.
    output=output.expanduser().resolve()
    if output.suffix.lower() not in VIDEO_EXTS: output=output.with_suffix('.mp4')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='vietsub_') as td:
        work=Path(td); source=obtain_source(source_value,work,log,cookie_file); info=probe(source)
        if output==source.resolve(): raise RuntimeError('Tệp đầu ra không được trùng tệp nguồn.')
        log(f'Video {info["width"]}×{info["height"]}, dài {info["duration"]:.1f}s')
        key=source_key(source,check)
        cues=None if force_ocr else load_cache(output,key,info,Cue,fps,region)
        if cues: log(f'Dùng lại {len(cues)} dòng OCR đã lưu đúng video; bỏ qua bước quét')
        else:
            samples,duration=extract_frames(source,info,region,fps,work,log,gpu,fast,check)
            cues=cluster(samples,duration,sample_step=sample_step)
            if not cues: raise RuntimeError('Không nhận diện được chữ Trung. Chữ có thể quá nhỏ, mờ hoặc cách điệu.')
            save_cache(output,key,info,cues,fps,region)
            log('Đã lưu dữ liệu OCR: '+str(output.with_suffix('.ocr.json')))
        log(f'Đã gom thành {len(cues)} dòng phụ đề')
        validate_translation_input(cues,info['duration'])
        stage_started=__import__('time').monotonic()
        from translation_core import TranslationIncomplete
        incomplete=None
        try:translations=translate(cues,api_key,model,log,instruction,glossary,check,output.with_suffix('.translation_cache.json'))
        except TranslationIncomplete as exc:
            incomplete=exc
            translations=[v if v else '[Chưa dịch] '+c.text for c,v in zip(cues,exc.result)]
            output=output.with_name(output.stem+'_partial.mp4')
            log(f'Còn {len(exc.missing)} dòng lỗi; xuất video tạm có đánh dấu [Chưa dịch]: {output}')
        log(f"Thời gian dịch API/cache: {__import__('time').monotonic()-stage_started:.1f}s")
        output.with_suffix('.translations.json').write_text(json.dumps([{'start':c.start,'end':c.end,'zh':c.text,'vi':v,'box':c.box} for c,v in zip(cues,translations)],ensure_ascii=False,indent=2),encoding='utf-8')
        assfile=output.with_suffix('.ass'); create_ass(cues,translations,info,assfile,font,font_ratio,subtitle_style)
        stage_started=__import__('time').monotonic()
        render(source,output,assfile,info['has_audio'],log,info['duration'],controller)
        log(f"Thời gian xuất video: {__import__('time').monotonic()-stage_started:.1f}s")
        from editor_core import save_project
        save_project(output.with_suffix('.project.json'),source,[{'start':c.start,'end':c.end,'zh':c.text,'vi':v,'box':c.box} for c,v in zip(cues,translations)],info,font,subtitle_style or {})
    if incomplete is not None:raise RuntimeError(f'Còn {len(incomplete.missing)} dòng chưa dịch. Video tạm: {output}. Chạy lại cùng đầu ra ban đầu để tiếp tục từ cache.')
    return output


def render_edited(source,output,rows,font,style,log=print,controller=None):
    from editor_core import validate_rows,save_project
    if controller:controller.check()
    source=Path(source).resolve();output=Path(output).resolve()
    if source==output:raise ValueError('Đầu ra không được trùng video gốc.')
    info=probe(source);rows=validate_rows(rows,info);output.parent.mkdir(parents=True,exist_ok=True)
    cues=[Cue(r['start'],r['end'],r['zh'],tuple(r['box'])) for r in rows]
    ass=output.with_suffix('.ass');create_ass(cues,[r['vi'] for r in rows],info,ass,font,subtitle_style=style,positions=[r['position'] for r in rows])
    output.with_suffix('.translations.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    save_project(output.with_suffix('.project.json'),source,rows,info,font,style)
    render(source,output,ass,info['has_audio'],log,info['duration'],controller);return output


def cli():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',nargs='?',help='Đường dẫn video hoặc URL; bỏ trống để mở giao diện')
    parser.add_argument('-o','--output',default='translated_vi.mp4')
    parser.add_argument('--model',default=DEFAULT_MODEL); parser.add_argument('--ocr-fps',type=float,default=1.5)
    parser.add_argument('--region-top',type=float,default=DEFAULT_REGION[0]); parser.add_argument('--region-bottom',type=float,default=DEFAULT_REGION[1])
    parser.add_argument('--font',default='Arial'); parser.add_argument('--font-ratio',type=float,default=.038)
    parser.add_argument('--gpu',action='store_true',help='Dùng CUDA GPU cho EasyOCR (cần cài PyTorch CUDA phù hợp)')
    parser.add_argument('--cookies',help='File cookies Netscape .txt cho trang yêu cầu phiên trình duyệt')
    args=parser.parse_args()
    if not args.source: return launch_gui()
    try:
        out=process(args.source,Path(args.output),os.getenv('OPENAI_API_KEY',''),args.model,args.ocr_fps,(args.region_top,args.region_bottom),args.font,args.font_ratio,args.gpu,cookie_file=args.cookies)
        print(f'Hoàn tất: {out}')
    except Exception as e: print(f'Lỗi: {e}',file=sys.stderr); return 1
    return 0


def launch_gui(test_mode=False):
    try:
        from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
        from PySide6.QtGui import QDesktopServices, QImage, QPixmap, QFont
        from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,
            QLabel,QLineEdit,QPushButton,QFileDialog,QComboBox,QDoubleSpinBox,QProgressBar,QPlainTextEdit,
            QFrame,QCheckBox,QMessageBox,QDialog,QDialogButtonBox,QScrollArea,QFontComboBox,QColorDialog)
    except ImportError: print('Cài giao diện: pip install PySide6'); return 2
    class Worker(QThread):
        log_signal=Signal(str); finished_signal=Signal(str); error_signal=Signal(str);state_signal=Signal(str)
        def __init__(self, values):
            super().__init__();self.values=dict(values)
            from pause_control import PauseController
            self.control=PauseController(self.state_signal.emit);self.values["controller"]=self.control
        def run(self):
            try:
                result=process(**self.values,log=self.log_signal.emit); self.finished_signal.emit(str(result))
            except Exception as e: self.error_signal.emit(str(e))
    class ExcelWorker(Worker):
        batch_finished=Signal(dict);item_started=Signal(dict);item_progress=Signal(dict)
        def __init__(self,values,queue):super().__init__(values);self.queue=queue
        def run(self):
            try:
                from batch_translation import translate_queue
                result=translate_queue(self.queue,self.values,self.control,process,self.item_progress.emit,self.log_signal.emit,self.item_started.emit);self.batch_finished.emit(result)
            except Exception as exc:self.error_signal.emit(str(exc))
    class ExportWorker(Worker):
        def run(self):
            try:self.finished_signal.emit(str(render_edited(**self.values,log=self.log_signal.emit)))
            except Exception as exc:self.error_signal.emit(str(exc))
    class WarmupWorker(QThread):
        log_signal=Signal(str); error_signal=Signal(str)
        def __init__(self,gpu):super().__init__();self.gpu=gpu
        def run(self):
            try:
                from ocr_loader import get_reader
                get_reader(model_dir(),self.gpu,self.log_signal.emit)
            except Exception as exc:self.error_signal.emit(str(exc))
    class ComponentWorker(QThread):
        log_signal=Signal(str); done_signal=Signal(); error_signal=Signal(str)
        def run(self):
            try:
                install_components(self.log_signal.emit); self.done_signal.emit()
            except Exception as e: self.error_signal.emit(str(e))
    class App(QMainWindow):
        def __init__(self):
            super().__init__(); self.setWindowTitle('Frame — Video Translator • V19 Components Fix'); self.resize(1280,900); self.setMinimumSize(1000,650); self.setAcceptDrops(True); self.worker=None; self.warmup=None; self.subtitle_style={}; self.instruction=DEFAULT_INSTRUCTION; self.glossary=''; self.saved_model=DEFAULT_MODEL
            try:
                config=json.loads((data_dir()/'translation_settings.json').read_text(encoding='utf-8'))
                self.instruction=config.get('instruction') or DEFAULT_INSTRUCTION; self.glossary=config.get('glossary',''); self.saved_model=config.get('model',DEFAULT_MODEL)
            except (OSError,ValueError,AttributeError): pass
            try: self.subtitle_style=json.loads((data_dir()/"subtitle_style.json").read_text(encoding="utf-8"))
            except (OSError,ValueError): pass
            self.setStyleSheet('''QMainWindow,QWidget{background:#101112;color:#f3f4f4;font-family:Inter,"Segoe UI",sans-serif;font-size:14px} QFrame#panel{background:#1b1e20;border:1px solid #303638;border-radius:10px} QLabel,QCheckBox{background:transparent;border:0} QCheckBox::indicator{width:15px;height:15px;border:1px solid #727a7d;border-radius:3px;background:#151718} QCheckBox::indicator:checked{background:#a7e5d3;border:1px solid #a7e5d3} QLabel#muted{color:#a6adaf} QLabel#eyebrow{color:#a7e5d3;font-size:11px;font-weight:700;letter-spacing:1px} QLineEdit,QComboBox,QDoubleSpinBox{background:#151718;border:1px solid #303638;border-radius:6px;padding:10px;color:#f3f4f4;min-height:20px} QLineEdit:focus,QComboBox:focus,QDoubleSpinBox:focus{border:1px solid #a7e5d3} QPushButton{background:#222628;border:1px solid #363d3f;border-radius:6px;padding:10px 14px;color:#f3f4f4} QPushButton:hover{background:#2c3234} QPushButton#primary{background:#a7e5d3;color:#101112;border:0;font-weight:700;padding:12px 18px} QPushButton#primary:hover{background:#c0f0e2} QPushButton:disabled{color:#727a7d;background:#1b1e20} QPlainTextEdit{background:#151718;border:1px solid #303638;border-radius:6px;color:#a6adaf;padding:8px} QProgressBar{background:#151718;border:0;border-radius:4px;height:8px;text-align:center} QProgressBar::chunk{background:#a7e5d3;border-radius:4px}QTableWidget{background:#15191c;alternate-background-color:#1d2529;color:#f3f4f4;gridline-color:#3c484f;border:1px solid #3c484f;selection-background-color:#30576d;selection-color:#ffffff} QHeaderView::section{background:#28343c;color:#ffffff;border:0;border-right:1px solid #46545d;border-bottom:1px solid #46545d;padding:8px 6px;font-weight:600} QTableCornerButton::section{background:#28343c;border:1px solid #46545d} QTableWidget::item{padding:4px} QTableWidget::item:selected{background:#30576d;color:#ffffff} QScrollBar:horizontal{background:#171e23;height:14px;margin:0} QScrollBar:vertical{background:#171e23;width:14px;margin:0} QScrollBar::handle:horizontal,QScrollBar::handle:vertical{background:#647982;border-radius:5px;min-width:28px;min-height:28px} QScrollBar::add-line,QScrollBar::sub-line{width:0;height:0} QScrollBar::add-page,QScrollBar::sub-page{background:#171e23}''')
            root=QWidget(); self.setCentralWidget(root); outer=QHBoxLayout(root); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
            nav=QFrame(); nav.setFixedWidth(160); nav.setStyleSheet('background:#151718;border-right:1px solid #303638'); nv=QVBoxLayout(nav); nv.setContentsMargins(14,20,14,20); logo=QLabel('F'); logo.setAlignment(Qt.AlignCenter); logo.setFixedSize(44,44); logo.setStyleSheet('background:#a7e5d3;color:#101112;border-radius:8px;font-size:22px;font-weight:800'); nv.addWidget(logo); nv.addSpacing(22)
            for text, callback in [('Video',self.pick_file),('Mở kết quả',self.open_result),('Thành phần',self.open_components),('Cài đặt',self.open_settings)]:
                b=QPushButton(text); b.setToolTip(text); b.clicked.connect(callback); nv.addWidget(b)
            nv.addStretch(); nv.addWidget(QLabel('Frame • v19 Fix',objectName='muted')); outer.addWidget(nav)
            main=QWidget(); self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.NoFrame); self.scroll.setWidget(main); outer.addWidget(self.scroll,1); ml=QVBoxLayout(main); ml.setContentsMargins(30,24,30,24); ml.setSpacing(18)
            top=QHBoxLayout(); title=QVBoxLayout(); eyebrow=QLabel('FRAME / VIETSUB STUDIO',objectName='eyebrow'); title.addWidget(eyebrow); h=QLabel('Video Trung → Phụ đề Việt'); h.setStyleSheet('font-size:27px;font-weight:600'); title.addWidget(h); top.addLayout(title); top.addStretch(); self.api=QLineEdit(os.getenv('OPENAI_API_KEY','')); self.api.setPlaceholderText('OpenAI API key'); self.api.setEchoMode(QLineEdit.Password); self.api.setMinimumWidth(230); apibox=QVBoxLayout(); apibox.addWidget(QLabel('OpenAI API key',objectName='muted')); apirow=QHBoxLayout(); apirow.addWidget(self.api); reveal=QPushButton('Hiện'); reveal.setCheckable(True); reveal.toggled.connect(lambda checked: (self.api.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password),reveal.setText('Ẩn' if checked else 'Hiện'))); apirow.addWidget(reveal); apibox.addLayout(apirow); top.addLayout(apibox); ml.addLayout(top)
            content=QHBoxLayout(); content.setSpacing(18); ml.addLayout(content,1)
            left=QVBoxLayout(); left.setSpacing(14); content.addLayout(left,5)
            source_panel=self.panel('01  THÊM VIDEO'); source_panel.layout().addWidget(QLabel('Chọn file hoặc kéo thả video vào cửa sổ này',objectName='muted')); row=QHBoxLayout(); self.source=QLineEdit(); self.source.setPlaceholderText('Đường dẫn video trên máy'); row.addWidget(self.source,1); browse=QPushButton('Thêm video'); browse.clicked.connect(self.pick_file); row.addWidget(browse); source_panel.layout().addLayout(row)
            from batch_gui import BatchPanel
            self.batch_toggle=QPushButton('Nhập danh sách Excel');self.batch_toggle.setCheckable(True);source_panel.layout().addWidget(self.batch_toggle)
            self.batch=BatchPanel(source_panel);self.batch.hide();source_panel.layout().addWidget(self.batch)
            self.batch_toggle.toggled.connect(self.batch.setVisible);self.batch.video_selected.connect(self.select_batch_video);self.batch.running_changed.connect(self.batch_running);self.batch.queue_ready.connect(self.excel_ready);self.batch.use_list.toggled.connect(self.excel_mode);self.source.textEdited.connect(lambda _:self.batch.use_list.setChecked(False))
            left.addWidget(source_panel)
            out_panel=self.panel('02  TỆP ĐẦU RA'); out_panel.layout().addWidget(QLabel('Video mới, giữ nguyên âm thanh gốc',objectName='muted')); outrow=QHBoxLayout(); self.out=QLineEdit(str(Path.home()/'Videos'/'translated_vi.mp4')); outrow.addWidget(self.out,1); outbrowse=QPushButton('Lưu tại…');self.output_browse=outbrowse; outbrowse.clicked.connect(self.pick_output); outrow.addWidget(outbrowse); out_panel.layout().addLayout(outrow); left.addWidget(out_panel)
            settings=self.panel('03  THIẾT LẬP DỊCH'); grid=QGridLayout(); settings.layout().addLayout(grid); grid.addWidget(QLabel('Model dịch'),0,0); self.model=QComboBox(); self.model.addItems(MODELS); self.model.setEditable(True); self.model.setCurrentText(self.saved_model); grid.addWidget(self.model,0,1); grid.addWidget(QLabel('OCR tự động • toàn khung hình'),1,0,1,2); grid.addWidget(QLabel('Font phụ đề'),3,0); self.font=QFontComboBox(); self.font.setCurrentFont(QFont(self.subtitle_style.get('font','Arial'))); grid.addWidget(self.font,3,1); customize=QPushButton('Cấu hình chữ phụ đề…'); customize.clicked.connect(self.open_subtitle_style); grid.addWidget(customize,4,0,1,2); left.addWidget(settings)
            self.gpu=QCheckBox('Tự dùng GPU NVIDIA nếu CUDA khả dụng'); self.gpu.setChecked(True); left.addWidget(self.gpu); self.force_ocr=QCheckBox('Quét OCR lại (bỏ dữ liệu đã lưu)'); left.addWidget(self.force_ocr); left.addStretch()
            right=QVBoxLayout(); right.setSpacing(14); right.setAlignment(Qt.AlignTop); content.addLayout(right,6)
            from video_player import VideoPlayer
            from subtitle_editor import SubtitleEditor
            preview=self.panel('TRÌNH PHÁT VIDEO'); self.preview=VideoPlayer(self); self.preview.setMinimumHeight(300); self.preview.setMaximumHeight(380); preview.layout().addWidget(self.preview)
            self.filemeta=QLabel('Thông tin video sẽ hiển thị tại đây',objectName='muted');self.filemeta.setWordWrap(True);preview.layout().addWidget(self.filemeta)
            switch=QHBoxLayout();original=QPushButton('Video gốc');original.clicked.connect(self.play_original);result=QPushButton('Video đã xuất');result.clicked.connect(self.open_result);switch.addWidget(original);switch.addWidget(result);preview.layout().addLayout(switch);right.addWidget(preview,3)
            status=self.panel('TIẾN TRÌNH'); sv=QVBoxLayout(); status.layout().addLayout(sv); self.status=QLabel('Sẵn sàng'); self.status.setStyleSheet('font-size:17px;font-weight:600'); sv.addWidget(self.status); self.stage=QLabel('Chọn video  →  Đọc chữ  →  Dịch  →  Xuất video',objectName='muted'); sv.addWidget(self.stage); self.progress=QProgressBar(); self.progress.setRange(0,0); self.progress.hide(); sv.addWidget(self.progress); self.logs=QPlainTextEdit(); self.logs.setReadOnly(True); self.logs.setMaximumBlockCount(300); self.logs.setPlaceholderText('Nhật ký xử lý sẽ hiện tại đây'); self.logs.setMinimumHeight(125); sv.addWidget(self.logs); right.addWidget(status,2)
            self.editor_panel=self.panel('04  BIÊN TẬP PHỤ ĐỀ SAU KHI DỊCH');self.editor=SubtitleEditor(self.open_subtitle_style,self);self.editor_panel.layout().addWidget(self.editor);ml.addWidget(self.editor_panel)
            self.editor.preview_requested.connect(self.preview_edited);self.editor.seek_requested.connect(self.seek_editor);self.editor.export_requested.connect(self.export_editor)
            self.preview.error.connect(self.on_log)
            localrow=QHBoxLayout(); bundledbutton=QPushButton('Dùng FFmpeg kèm theo'); bundledbutton.clicked.connect(self.use_bundled_ffmpeg); localrow.addWidget(bundledbutton); ffbutton=QPushButton('Chọn FFmpeg trên máy'); ffbutton.clicked.connect(self.pick_local_ffmpeg); localrow.addWidget(ffbutton); modelbutton=QPushButton('Chọn thư mục model OCR'); modelbutton.clicked.connect(self.pick_local_models); localrow.addWidget(modelbutton); warmbutton=QPushButton('Nạp OCR trước');warmbutton.clicked.connect(self.warm_ocr); localrow.addWidget(warmbutton);localrow.addStretch(); ml.addLayout(localrow)
            actions=QHBoxLayout(); actions.addWidget(QLabel('Giữ chữ Trung • Giữ âm thanh gốc',objectName='muted')); actions.addStretch(); self.download=QPushButton('Kiểm tra / sửa thành phần'); self.download.setToolTip('Kiểm tra công cụ và sửa thành phần thiếu/hỏng. Nút tạm khóa khi đang xử lý video.'); self.download.clicked.connect(self.download_components); actions.addWidget(self.download); self.start=QPushButton('Bắt đầu dịch'); self.start.setObjectName('primary'); self.start.clicked.connect(self.start_job); actions.addWidget(self.start);self.pause_button=QPushButton('Tạm dừng');self.pause_button.setEnabled(False);self.pause_button.clicked.connect(self.toggle_processing_pause);actions.addWidget(self.pause_button); ml.insertLayout(2,actions)
        def excel_ready(self,queue):
            for job in queue.jobs:
                candidate=queue.root/job.get('video','') if job.get('video') else Path(job.get('local_path') or '')
                if candidate.is_file():self.load_video(str(candidate));break
            self.batch.use_list.setChecked(True);self.excel_mode(True)
            if queue.jobs:self.out.setText(str(queue.root/queue.jobs[0]['folder']/'translated_vi.mp4'))
            self.out.setToolTip('Danh sách Excel: mỗi video lưu translated_vi.mp4 trong thư mục dự án riêng.')
            self.status.setText(f'Đã nạp {len(queue.jobs)} video • Bấm Bắt đầu dịch để xử lý theo STT')
        def excel_mode(self,active):
            self.source.setReadOnly(active);self.out.setReadOnly(active);self.output_browse.setEnabled(not active)
            if hasattr(self,'start'):self.start.setText(f'Bắt đầu dịch ({len(self.batch.queue.jobs)} video)' if active and self.batch.queue else 'Bắt đầu dịch')
        def excel_item_started(self,item):
            path=item['source']
            self.source.setText(path);self.out.setText(str(Path(path).parent/'translated_vi.mp4'));self.filemeta.setText(f'Video {item["index"]}/{item["total"]}: {item["name"]}');self.preview.load(path)
        def excel_done(self,result):
            if result['last_output']:self.done(result['last_output'])
            else:
                self.batch.setEnabled(True);self.pause_button.setEnabled(False);self.progress.hide();self.start.setEnabled(True);self.download.setEnabled(True);self.editor.open_button.setEnabled(True)
            self.status.setText(f'Đã dịch {result["success"]}/{result["total"]} video • Lỗi {result["failed"]}')
            self.logs.appendPlainText('Dự án: '+result['root'])
        def start_excel_job(self):
            self.batch.load_queue()
            if self.batch.queue is None:return
            if not self.api.text().strip():QMessageBox.warning(self,'Thiếu API key','Nhập OpenAI API key để dịch danh sách.');return
            if self.editor.modified and QMessageBox.question(self,'Chỉnh sửa chưa lưu','Bắt đầu danh sách và bỏ chỉnh sửa chưa lưu?',QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
            values={'force_ocr':self.force_ocr.isChecked(),'fast':False,'api_key':self.api.text().strip(),'model':self.model.currentText().strip(),'instruction':self.instruction,'glossary':self.glossary,'fps':1.5,'region':DEFAULT_REGION,'font':self.font.currentFont().family(),'subtitle_style':dict(self.subtitle_style),'gpu':self.gpu.isChecked()}
            self.batch.queue.cookies=self.batch.cookies.text().strip() or None
            self.preview.player.pause();self.editor.set_ready(False);self.editor.open_button.setEnabled(False);self.start.setEnabled(False);self.download.setEnabled(False);self.batch.setEnabled(False);self.progress.show();self.logs.clear()
            self.worker=ExcelWorker(values,self.batch.queue);self.worker.item_progress.connect(self.batch.update_row);self.worker.item_started.connect(self.excel_item_started);self.worker.log_signal.connect(self.on_log);self.worker.state_signal.connect(self.pause_state);self.worker.batch_finished.connect(self.excel_done);self.worker.error_signal.connect(self.fail);self.pause_button.setEnabled(True);self.pause_button.setText('Tạm dừng');self.worker.start()
        def select_batch_video(self,path):
            self.load_video(path)
            if self.source.text()==path:self.batch_toggle.setChecked(False)
        def batch_running(self,busy):
            self.start.setEnabled(not busy);self.download.setEnabled(not busy);self.editor.open_button.setEnabled(not busy);self.editor.set_ready(not busy and bool(self.editor.rows))
        def open_subtitle_style(self):
            dialog=QDialog(self); dialog.setWindowTitle('Cấu hình phụ đề tiếng Việt'); dialog.setMinimumWidth(560)
            layout=QVBoxLayout(dialog); grid=QGridLayout(); layout.addLayout(grid)
            fonts=QFontComboBox(); fonts.setCurrentFont(self.font.currentFont()); grid.addWidget(QLabel('Font đã cài trên máy'),0,0); grid.addWidget(fonts,0,1)
            controls={}
            for row,(key,label,minimum,maximum,value) in enumerate([
                ('size_ratio','Cỡ chữ (% chiều cao video)',1,10,3.8),('outline','Độ dày viền (px)',0,10,2.2),
                ('shadow','Bóng chữ (px)',0,10,0),('spacing','Giãn ký tự (px)',-2,20,0),
                ('gap_ratio','Khoảng cách trên dòng Trung (%)',0,10,1.2)],1):
                spin=QDoubleSpinBox(); spin.setRange(minimum,maximum); spin.setSingleStep(.2)
                existing=self.subtitle_style.get(key,value/100 if key.endswith('ratio') else value)
                spin.setValue(existing*100 if key.endswith('ratio') else existing); controls[key]=spin
                grid.addWidget(QLabel(label),row,0); grid.addWidget(spin,row,1)
            colors={key:self.subtitle_style.get(key,default) for key,default in [('color','#FFFFFF'),('outline_color','#000000')]}
            for row,(key,label) in enumerate([('color','Màu chữ'),('outline_color','Màu viền')],6):
                button=QPushButton(colors[key]); grid.addWidget(QLabel(label),row,0); grid.addWidget(button,row,1)
                def choose(checked=False,k=key,b=button):
                    chosen=QColorDialog.getColor(parent=dialog,title='Chọn màu')
                    if chosen.isValid(): colors[k]=chosen.name(); b.setText(colors[k]); update_preview()
                button.clicked.connect(choose)
            bold=QCheckBox('In đậm'); bold.setChecked(self.subtitle_style.get('bold',False))
            italic=QCheckBox('In nghiêng'); italic.setChecked(self.subtitle_style.get('italic',False))
            row=QHBoxLayout(); row.addWidget(bold); row.addWidget(italic); layout.addLayout(row)
            sample=QLabel('Tiếng Việt: Đường phố, tuổi trẻ và những chuyến đi'); sample.setWordWrap(True); sample.setMinimumHeight(100); layout.addWidget(sample)
            layout.addWidget(QLabel('Mẫu thể hiện font, màu và kiểu chữ. Cỡ chữ xuất tính theo chiều cao video.'))
            def update_preview(*args):
                f=fonts.currentFont(); f.setPointSize(22); f.setBold(bold.isChecked()); f.setItalic(italic.isChecked()); sample.setFont(f)
                sample.setStyleSheet('color:'+colors['color']+';background:#20272b;padding:16px;border-radius:8px')
            fonts.currentFontChanged.connect(update_preview); bold.toggled.connect(update_preview); italic.toggled.connect(update_preview); update_preview()
            buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
            if dialog.exec()==QDialog.Accepted:
                self.font.setCurrentFont(fonts.currentFont())
                self.subtitle_style={k:spin.value()/100 if k.endswith('ratio') else spin.value() for k,spin in controls.items()}
                self.subtitle_style.update(colors); self.subtitle_style.update(bold=bold.isChecked(),italic=italic.isChecked(),font=fonts.currentFont().family())
                try:
                    data_dir().mkdir(parents=True,exist_ok=True); (data_dir()/'subtitle_style.json').write_text(json.dumps(self.subtitle_style,ensure_ascii=False),encoding='utf-8')
                except OSError: self.on_log('Cấu hình chữ chỉ áp dụng phiên này vì không ghi được thiết lập.')
                self.editor.set_style(self.font.currentFont().family(),self.subtitle_style)
                if self.editor.source:self.editor.preview()
        def open_result(self):
            p=Path(self.out.text()).expanduser()
            if p.is_file(): self.preview.load(p);self.preview.set_subtitles([],{},'Arial',{});self.preview.play()
            else: QMessageBox.information(self,'Chưa có kết quả','Hãy dịch video trước. Tệp kết quả sẽ xuất tại đường dẫn đầu ra.')
        def open_components(self):
            dialog=QDialog(self); dialog.setWindowTitle('Thành phần — FFmpeg & OCR'); dialog.setMinimumWidth(680)
            layout=QVBoxLayout(dialog)
            title=QLabel('FFmpeg & ffprobe cho Windows'); title.setStyleSheet('font-size:22px;font-weight:600'); layout.addWidget(title)
            guide=QLabel('Ứng dụng đã kèm ffmpeg.exe và ffprobe.exe trong thư mục ffmpeg. Bấm Dùng FFmpeg kèm theo. Chỉ tải ZIP nếu bản kèm theo bị hỏng.'); guide.setWordWrap(True); layout.addWidget(guide)
            links=QLabel('<a style="color:#a7e5d3" href="https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip">Tải ZIP dự phòng: ffmpeg.exe + ffprobe.exe</a><br><br><a style="color:#a7e5d3" href="https://www.gyan.dev/ffmpeg/builds/">Trang tải Gyan.dev</a>'); links.setOpenExternalLinks(True); layout.addWidget(links)
            copy=QPushButton('Sao chép link tải ZIP'); copy.clicked.connect(lambda: QApplication.clipboard().setText('https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip')); layout.addWidget(copy)
            bundled=QPushButton('Dùng FFmpeg kèm theo ứng dụng'); layout.addWidget(bundled)
            choose=QPushButton('Chọn file FFmpeg hoặc thư mục đã giải nén'); choose.clicked.connect(self.pick_local_ffmpeg); layout.addWidget(choose)
            details=QLabel(''); details.setWordWrap(True); layout.addWidget(details)
            def refresh():
                details.setText('FFmpeg: '+str(find_binary('ffmpeg') or 'Chưa chọn')+'\nffprobe: '+str(find_binary('ffprobe') or 'Chưa chọn')+'\nModel OCR: '+str(model_dir()))
            refresh()
            bundled.clicked.connect(lambda: (self.use_bundled_ffmpeg(), refresh()))
            check=QPushButton('Cập nhật trạng thái'); check.clicked.connect(refresh); layout.addWidget(check)
            models=QPushButton('Chọn model OCR có sẵn'); models.clicked.connect(self.pick_local_models); layout.addWidget(models)
            openfolder=QPushButton('Mở thư mục thành phần'); openfolder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))); layout.addWidget(openfolder)
            close=QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(dialog.reject); layout.addWidget(close); dialog.exec()
        def open_settings(self):
            dialog=QDialog(self); dialog.setWindowTitle('Cài đặt'); dialog.setMinimumWidth(430); layout=QVBoxLayout(dialog)
            layout.addWidget(QLabel('API key ở góc trên bên phải. Nhấn Hiện/Ẩn để xem hoặc che khóa. Khóa chỉ giữ trong phiên chạy.'))
            layout.addWidget(QLabel('Thành phần cục bộ'))
            ff=QPushButton('Chọn FFmpeg trên máy'); ff.clicked.connect(self.pick_local_ffmpeg); layout.addWidget(ff)
            models=QPushButton('Chọn thư mục model OCR'); models.clicked.connect(self.pick_local_models); layout.addWidget(models)
            layout.addWidget(QLabel('Model dịch'))
            combo=QComboBox(); combo.setEditable(True); combo.addItems([self.model.itemText(i) for i in range(self.model.count())]); combo.setCurrentText(self.model.currentText()); layout.addWidget(combo)
            layout.addWidget(QLabel('Instruction cho phiên dịch (không lưu API key)'))
            instructions=QPlainTextEdit(self.instruction); instructions.setMinimumHeight(190); layout.addWidget(instructions)
            reset=QPushButton('Khôi phục instruction chuẩn'); reset.clicked.connect(lambda: instructions.setPlainText(DEFAULT_INSTRUCTION)); layout.addWidget(reset)
            layout.addWidget(QLabel('Thuật ngữ / tên riêng (mỗi dòng: tiếng Trung = tiếng Việt)'))
            glossary=QPlainTextEdit(self.glossary); glossary.setMaximumHeight(100); layout.addWidget(glossary)
            buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
            if dialog.exec()==QDialog.Accepted:
                self.model.setCurrentText(combo.currentText().strip()); self.instruction=instructions.toPlainText().strip() or DEFAULT_INSTRUCTION; self.glossary=glossary.toPlainText().strip()
                try:
                    data_dir().mkdir(parents=True,exist_ok=True)
                    (data_dir()/'translation_settings.json').write_text(json.dumps({'model':self.model.currentText(),'instruction':self.instruction,'glossary':self.glossary},ensure_ascii=False,indent=2),encoding='utf-8')
                except OSError as exc: QMessageBox.warning(self,'Không lưu được cài đặt',str(exc))
        def panel(self,label):
            f=QFrame(); f.setObjectName('panel'); lay=QVBoxLayout(f); lay.setContentsMargins(16,14,16,16); lay.setSpacing(10); l=QLabel(label); l.setStyleSheet('color:#a6adaf;font-size:11px;font-weight:700;letter-spacing:1px'); lay.addWidget(l); return f
        def pick_file(self):
            p,_=QFileDialog.getOpenFileName(self,'Chọn video','','Video (*.mp4 *.mkv *.mov *.webm *.avi *.m4v)',options=QFileDialog.DontUseNativeDialog)
            if p:self.batch.use_list.setChecked(False);self.load_video(p)
        def dragEnterEvent(self,event):
            if event.mimeData().hasUrls() and any(u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in VIDEO_EXTS for u in event.mimeData().urls()): event.acceptProposedAction()
        def dropEvent(self,event):
            if self.worker and self.worker.isRunning(): return
            for u in event.mimeData().urls():
                if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in VIDEO_EXTS:
                    self.load_video(u.toLocalFile()); event.acceptProposedAction(); break
        def load_video(self,p):
            if self.editor.modified and QMessageBox.question(self,'Thay video','Có thay video khi dự án còn chỉnh sửa chưa lưu không?')!=QMessageBox.Yes:return
            self.source.setText(p);self.source.setCursorPosition(0);self.source.setToolTip(p);self.filemeta.setText(Path(p).name)
            self.editor.set_ready(False);self.editor.source=None;self.editor.rows=[];self.editor.table.setRowCount(0);self.editor.modified=False
            self.preview.load(p)
            try:
                info=probe(Path(p));self.filemeta.setText(f'{Path(p).name}\n{info["width"]} × {info["height"]} • {info["duration"]:.1f} giây')
            except Exception as exc:self.on_log('Không đọc được thông tin video: '+str(exc))
            self.out.setText(str(Path(p).with_name(Path(p).stem+'_vi.mp4')));self.status.setText('Video đã sẵn sàng')
        def play_original(self):
            if Path(self.source.text()).is_file():self.preview.load(self.source.text());self.preview.set_subtitles([],{},'Arial',{});self.preview.play()
        def preview_edited(self,rows,info,font,style,source):
            from editor_core import preview_items
            self.subtitle_style=dict(style);self.font.setCurrentFont(QFont(font))
            try:
                self.preview.load(source);self.preview.set_subtitles(preview_items(rows,info,font,style),info,font,style)
            except Exception as exc:QMessageBox.warning(self,'Không xem được bản chỉnh',str(exc))
        def seek_editor(self,seconds):
            if self.editor.source:self.editor.preview();self.preview.seek(seconds)
        def export_editor(self,values):
            if self.worker and self.worker.isRunning():QMessageBox.information(self,'Đang xử lý','Chờ tác vụ hiện tại hoàn tất.');return
            self.preview.shutdown();self.start.setEnabled(False);self.download.setEnabled(False);self.editor.set_ready(False);self.editor.open_button.setEnabled(False);self.out.setText(str(values['output']));self.progress.show();self.logs.clear()
            self.worker=ExportWorker(values);self.pause_button.setEnabled(True);self.pause_button.setText("Tạm dừng");self.worker.state_signal.connect(self.pause_state);self.worker.log_signal.connect(self.on_log);self.worker.finished_signal.connect(self.done);self.worker.error_signal.connect(self.fail);self.batch.setEnabled(False);self.worker.start()
        def warm_ocr(self):
            if self.warmup and self.warmup.isRunning():return
            self.warmup=WarmupWorker(self.gpu.isChecked());self.warmup.log_signal.connect(self.on_log);self.warmup.error_signal.connect(self.on_log);self.warmup.start()
        def pick_output(self):
            p,_=QFileDialog.getSaveFileName(self,'Lưu video đã dịch',self.out.text(),'MP4 (*.mp4)')
            if p: self.out.setText(p if Path(p).suffix else p+'.mp4')
        def select_component(self,kind):
            # Parent to the currently active modal dialog, not its blocked main window.
            parent=QApplication.activeModalWidget() or self
            dialog=QDialog(parent); dialog.setWindowTitle('Chọn FFmpeg' if kind=='bin' else 'Chọn model OCR'); dialog.setMinimumWidth(640)
            layout=QVBoxLayout(dialog)
            layout.addWidget(QLabel('Chọn thư mục gốc FFmpeg, thư mục bin, hoặc file ffmpeg.exe.' if kind=='bin' else 'Chọn thư mục model, hoặc một file .pth trong thư mục model.'))
            path=QLineEdit(); path.setPlaceholderText('Dán đường dẫn trên máy tại đây'); layout.addWidget(path)
            bundled=bundled_ffmpeg_dir()
            start=str(bundled if kind=='bin' and bundled.is_dir() else Path.home())
            if kind=='bin' and bundled.is_dir(): path.setText(str(bundled))
            row=QHBoxLayout(); folderbutton=QPushButton('Chọn thư mục…'); filebutton=QPushButton('Chọn file…'); row.addWidget(folderbutton); row.addWidget(filebutton); layout.addLayout(row)
            if kind=='bin':
                bundledbutton=QPushButton('Dùng FFmpeg kèm theo ứng dụng'); layout.addWidget(bundledbutton)
            error=QLabel(''); error.setWordWrap(True); error.setMinimumHeight(72); error.setStyleSheet('color:#e28b8b'); layout.addWidget(error)
            def browse_folder():
                chosen=QFileDialog.getExistingDirectory(dialog,'Chọn thư mục',path.text().strip() or start,QFileDialog.ShowDirsOnly|QFileDialog.DontUseNativeDialog)
                if chosen: path.setText(chosen)
            def browse_file():
                chosen,_=QFileDialog.getOpenFileName(dialog,'Chọn file',path.text().strip() or start,'FFmpeg (*.exe);;Tất cả (*)' if kind=='bin' else 'Model OCR (*.pth);;Tất cả (*)',options=QFileDialog.DontUseNativeDialog)
                if chosen: path.setText(chosen)
            folderbutton.clicked.connect(browse_folder); filebutton.clicked.connect(browse_file)
            buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); layout.addWidget(buttons)
            def apply(target=None):
                try:
                    chosen=(target if target is not None else path.text()).strip()
                    if not chosen: raise RuntimeError('Hãy chọn file/thư mục hoặc dán đường dẫn.')
                    path.setText(chosen)
                    selected=(use_local_ffmpeg if kind=='bin' else use_local_models)(chosen)
                    self.on_log('Đã chọn '+('FFmpeg: ' if kind=='bin' else 'model OCR: ')+str(selected)); dialog.accept()
                except Exception as e: error.setText(str(e))
            if kind=='bin': bundledbutton.clicked.connect(lambda: apply(str(bundled)))
            buttons.accepted.connect(lambda: apply()); buttons.rejected.connect(dialog.reject); dialog.exec()
        def pick_local_ffmpeg(self): self.select_component('bin')
        def pick_local_models(self): self.select_component('models')
        def use_bundled_ffmpeg(self, silent=False):
            try:
                selected=use_local_ffmpeg(bundled_ffmpeg_dir())
                self.on_log('Đã dùng FFmpeg kèm theo: '+str(selected))
            except Exception as e:
                self.on_log('Chưa dùng được FFmpeg kèm theo: '+str(e))
                if not silent:
                    QMessageBox.warning(QApplication.activeModalWidget() or self,'Không chạy được FFmpeg',str(e))
        def download_components(self):
            if self.worker and self.worker.isRunning():return
            self.start.setEnabled(False); self.download.setEnabled(False); self.progress.show(); self.logs.clear()
            self.worker=ComponentWorker(); self.worker.log_signal.connect(self.on_log); self.worker.done_signal.connect(self.components_done); self.worker.error_signal.connect(self.fail); self.batch.setEnabled(False);self.worker.start()
        def components_done(self):
            self.batch.setEnabled(True)
            self.progress.hide(); self.start.setEnabled(True); self.download.setEnabled(True); self.status.setText('Thành phần đã sẵn sàng')
        def closeEvent(self,event):
            if (self.batch.worker and self.batch.worker.isRunning()) or (self.worker and self.worker.isRunning()) or (self.warmup and self.warmup.isRunning()):
                QMessageBox.information(self,'Đang xử lý','Chờ tác vụ hoàn tất trước khi đóng ứng dụng.'); event.ignore()
            elif self.editor.modified:
                answer=QMessageBox.question(self,'Chỉnh sửa chưa lưu','Đóng và bỏ các chỉnh sửa chưa lưu?',QMessageBox.Yes|QMessageBox.No)
                if answer==QMessageBox.Yes:self.preview.shutdown();event.accept()
                else:event.ignore()
            else:self.preview.shutdown();event.accept()
        def start_job(self):
            if self.worker and self.worker.isRunning():return
            if self.batch.queue is None and Path(self.batch.excel.text()).is_file():self.batch.load_queue()
            if self.batch.queue and self.batch.use_list.isChecked():self.start_excel_job();return
            src=self.source.text().strip().strip('"'); key=self.api.text().strip()
            if not src: QMessageBox.warning(self,'Thiếu video','Bấm Thêm video để chọn file trên máy.'); return
            if not Path(src).expanduser().is_file(): QMessageBox.warning(self,'Video không hợp lệ','Hãy chọn video đã tải về máy. Giao diện này không nhận link website.'); return
            if Path(src).suffix.lower() not in VIDEO_EXTS: QMessageBox.warning(self,'Định dạng không hỗ trợ','Chọn MP4, MKV, MOV, WEBM, AVI hoặc M4V.'); return
            if not key: QMessageBox.warning(self,'Thiếu API key','Nhập OpenAI API key để dịch phụ đề.'); return
            self.preview.player.pause();self.editor.set_ready(False);self.editor.open_button.setEnabled(False);self.start.setEnabled(False); self.download.setEnabled(False); self.progress.show(); self.status.setText('Đang khởi chạy…'); self.logs.clear()
            vals={'force_ocr':self.force_ocr.isChecked(),'fast':False,'source_value':src,'output':Path(self.out.text().strip() or 'translated_vi.mp4'),'api_key':key,'model':self.model.currentText().strip(),'instruction':self.instruction,'glossary':self.glossary,'fps':1.5,'region':DEFAULT_REGION,'font':self.font.currentFont().family(),'subtitle_style':dict(self.subtitle_style),'gpu':self.gpu.isChecked()}
            self.worker=Worker(vals);self.pause_button.setEnabled(True);self.pause_button.setText("Tạm dừng");self.worker.state_signal.connect(self.pause_state); self.worker.log_signal.connect(self.on_log); self.worker.finished_signal.connect(self.done); self.worker.error_signal.connect(self.fail); self.batch.setEnabled(False);self.worker.start()
        def toggle_processing_pause(self):
            if not self.worker or not self.worker.isRunning() or not hasattr(self.worker,'control'):return
            if self.worker.control.requested:self.worker.control.resume()
            else:self.worker.control.pause()
        def pause_state(self,state):
            self.pause_button.setText('Tiếp tục' if state!='running' else 'Tạm dừng')
            if state=='paused':self.status.setText('Đã tạm dừng • giữ phần đã xử lý');self.stage.setText('Nhấn Tiếp tục để tiếp tục tác vụ')
            elif state=='pausing':self.status.setText('Đang chờ lượt OCR / yêu cầu API hiện tại hoàn tất để tạm dừng…')
            elif state=='running':self.status.setText('Đang tiếp tục xử lý…')
            else:self.logs.appendPlainText('Chưa tạm dừng được tiến trình: '+state)
        def on_log(self,msg):
            self.logs.appendPlainText(msg)
            if self.worker and hasattr(self.worker,'control') and self.worker.control.requested:return
            self.status.setText(msg[:100])
            match=re.search(r'(?:quét phụ đề|xuất video): (\d+)%',msg)
            if match:
                self.progress.setRange(0,100); self.progress.setValue(int(match.group(1))); self.stage.setText('Đang xuất video • % của bước xuất' if 'xuất video:' in msg else 'Đang đọc chữ • % của bước OCR')
            else:
                self.progress.setRange(0,0)
                if 'dịch' in msg.lower(): self.stage.setText('Đang dịch phụ đề sang tiếng Việt')
                elif 'xuất' in msg.lower() or 'render' in msg.lower(): self.stage.setText('Đang xuất video')

        def show_editor_section(self):
            self.editor_panel.setFocus(Qt.OtherFocusReason)
            QTimer.singleShot(0,lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))
        def load_result_for_editing(self,path):
            output=Path(path)
            project=json.loads(output.with_suffix('.project.json').read_text(encoding='utf-8'));source=project['source']
            self.editor.load_translation(output.with_suffix('.translations.json'),source,project['info'],project['font'],project['style'])
            self.editor.project_path=output.with_suffix('.project.json');self.source.setText(source);self.source.setToolTip(source)
            self.filemeta.setText(f'Video đã dịch: {output}\nNguồn chỉnh sửa: {source}')
            self.editor.preview()
            self.show_editor_section()

        def done(self,path):
            self.batch.setEnabled(True)
            self.pause_button.setEnabled(False);self.pause_button.setText("Tạm dừng")
            self.progress.hide();self.start.setEnabled(True);self.download.setEnabled(True);self.editor.open_button.setEnabled(True);self.status.setText('Hoàn tất • đã chuyển sang phần 4 để chỉnh sửa');self.stage.setText('Bản dịch đã nằm ở phần 4. Sửa câu, thời gian, vị trí rồi xuất lại nếu cần.');self.logs.appendPlainText('Đã lưu: '+path)
            try:
                self.load_result_for_editing(path)
            except Exception as exc:
                self.logs.appendPlainText('Không nạp được dữ liệu chỉnh sửa: '+str(exc))
                self.preview.load(path);self.preview.set_subtitles([],{},'Arial',{})
        def fail(self,msg):
            self.batch.setEnabled(True)
            self.pause_button.setEnabled(False);self.pause_button.setText("Tạm dừng")
            self.editor.open_button.setEnabled(True);self.editor.set_ready(bool(self.editor.rows));self.progress.hide(); self.start.setEnabled(True); self.download.setEnabled(True); self.status.setText('Có lỗi cần xử lý'); self.logs.appendPlainText('LỖI: '+msg); QMessageBox.critical(self,'Không thể xử lý video',msg)
    app=QApplication.instance() or QApplication(sys.argv); win=App()
    if test_mode: return app,win
    if not (find_binary('ffmpeg') and find_binary('ffprobe')):
        win.use_bundled_ffmpeg(silent=True)
    win.show(); return app.exec()

if __name__=='__main__': raise SystemExit(cli())
