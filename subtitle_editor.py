"""Inline editor for subtitle text, timing and position."""
import json,copy
from pathlib import Path
from PySide6.QtCore import Qt,Signal,QSignalBlocker
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QTableWidget,QTableWidgetItem,QPushButton,QLabel,QPlainTextEdit,QFileDialog,QMessageBox,QHeaderView
from editor_core import validate_rows,save_project
class SubtitleEditor(QWidget):
    preview_requested=Signal(object,object,str,object,str)
    seek_requested=Signal(float)
    export_requested=Signal(object)
    def __init__(self,style_callback,parent=None):
        super().__init__(parent);self.source=None;self.info={};self.rows=[];self.font='Arial';self.style={};self.project_path=None;self.modified=False;self.loading=False
        box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0);title=QLabel('04  CHỈNH PHỤ ĐỀ & XUẤT LẠI');box.addWidget(title)
        self.note=QLabel('Sau khi dịch, chỉnh từng câu, thời gian và vị trí tại đây. X/Y để trống sẽ tự căn.');self.note.setWordWrap(True);box.addWidget(self.note)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['Bắt đầu (s)','Kết thúc (s)','Tiếng Trung','Tiếng Việt','X Việt','Y Việt']);self.table.setMinimumHeight(220);self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch);self.table.setColumnWidth(2,190);self.table.setColumnWidth(0,110);self.table.setColumnWidth(1,110);self.table.setColumnWidth(4,85);self.table.setColumnWidth(5,85);box.addWidget(self.table)
        self.text=QPlainTextEdit();self.text.setPlaceholderText('Chọn một dòng để sửa bản dịch.');self.text.setMaximumHeight(90);box.addWidget(self.text)
        row=QHBoxLayout();self.open_button=QPushButton('Mở dự án…');self.save_button=QPushButton('Lưu dự án');self.add_button=QPushButton('Thêm dòng');self.delete_button=QPushButton('Xóa dòng');self.style_button=QPushButton('Font / màu / viền…');self.preview_button=QPushButton('Xem bản chỉnh');self.export_button=QPushButton('Xuất video đã chỉnh…')
        for b in [self.open_button,self.save_button,self.add_button,self.delete_button,self.style_button,self.preview_button,self.export_button]:row.addWidget(b)
        box.addLayout(row)
        self.open_button.clicked.connect(self.open_project);self.save_button.clicked.connect(self.save);self.add_button.clicked.connect(self.add_row);self.delete_button.clicked.connect(self.delete_rows);self.style_button.clicked.connect(style_callback);self.preview_button.clicked.connect(self.preview);self.export_button.clicked.connect(self.export)
        self.table.itemSelectionChanged.connect(self.select_row);self.table.itemChanged.connect(self.changed);self.text.textChanged.connect(self.text_changed);self.set_ready(False)
    def set_ready(self,ready):
        for b in [self.save_button,self.add_button,self.delete_button,self.preview_button,self.export_button]:b.setEnabled(ready)
        self.table.setEnabled(ready);self.text.setEnabled(ready)
    def fill(self):
        self.loading=True;self.table.setRowCount(len(self.rows))
        for i,r in enumerate(self.rows):
            values=[f"{r['start']:.3f}",f"{r['end']:.3f}",r.get('zh',''),r['vi']]+([str(v) for v in r['position']] if r.get('position') else ['',''])
            for j,value in enumerate(values):self.table.setItem(i,j,QTableWidgetItem(value))
        self.loading=False;self.set_ready(True)
        if self.rows:self.table.selectRow(0)
    def load_translation(self,path,source,info,font,style):
        rows=json.loads(Path(path).read_text(encoding='utf-8'));self.rows=validate_rows(rows,info);self.source=Path(source).resolve();self.info=dict(info);self.font=font;self.style=dict(style);self.project_path=Path(path).with_name(Path(path).name.removesuffix('.translations.json')+'.project.json');self.modified=False;self.fill()
        self.note.setText(f'{len(rows)} dòng • X/Y là tọa độ chữ Việt theo pixel video gốc; để trống để tự căn.')
    def snapshot(self):
        rows=[]
        for i in range(self.table.rowCount()):
            r=copy.deepcopy(self.rows[i]);r.update(start=self.table.item(i,0).text(),end=self.table.item(i,1).text(),zh=self.table.item(i,2).text(),vi=self.table.item(i,3).text())
            x=self.table.item(i,4).text().strip();y=self.table.item(i,5).text().strip()
            if bool(x)!=bool(y):raise ValueError(f'Dòng {i+1}: nhập cả X và Y hoặc để trống cả hai.')
            r['position']=[x,y] if x else None;rows.append(r)
        return validate_rows(rows,self.info)
    def select_row(self):
        if self.loading:return
        i=self.table.currentRow()
        if i<0:return
        with QSignalBlocker(self.text):self.text.setPlainText(self.table.item(i,3).text())
        try:self.seek_requested.emit(float(self.table.item(i,0).text()))
        except ValueError:pass
    def text_changed(self):
        i=self.table.currentRow()
        if i>=0:self.table.item(i,3).setText(self.text.toPlainText())
    def changed(self,item):
        if self.loading:return
        self.modified=True
        if item.column()==3 and item.row()==self.table.currentRow():
            with QSignalBlocker(self.text):self.text.setPlainText(item.text())
    def set_style(self,font,style):self.font=font;self.style=dict(style);self.modified=True
    def preview(self):
        try:self.preview_requested.emit(self.snapshot(),self.info,self.font,self.style,str(self.source))
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,'Dòng cần sửa',str(exc))
    def save(self):
        try:
            rows=self.snapshot();path=self.project_path
            if path is None:
                chosen,_=QFileDialog.getSaveFileName(self,'Lưu dự án phụ đề','','JSON (*.json)')
                if not chosen:return
                path=Path(chosen)
            save_project(path,self.source,rows,self.info,self.font,self.style);self.project_path=path;self.modified=False;self.note.setText('Đã lưu dự án: '+str(path))
        except (ValueError,OSError,TypeError) as exc:QMessageBox.warning(self,'Không lưu được dự án',str(exc))
    def open_project(self):
        if self.modified and QMessageBox.question(self,'Thay dự án','Có thay dự án đang có chỉnh sửa chưa lưu không?')!=QMessageBox.Yes:return
        p,_=QFileDialog.getOpenFileName(self,'Mở dự án phụ đề','','JSON (*.json)')
        if not p:return
        try:
            data=json.loads(Path(p).read_text(encoding='utf-8'))
            if isinstance(data,list):
                selected,_=QFileDialog.getOpenFileName(self,'Chọn video gốc cho bản dịch V15','','Video (*.mp4 *.mkv *.mov *.webm *.avi)')
                if not selected:return
                from video_translator import probe
                source=Path(selected);info=probe(source)
                meta=Path(str(p).replace('.translations.json','.ocr.meta.json'))
                if meta!=Path(p) and meta.is_file():
                    from ocr_cache import source_key
                    if json.loads(meta.read_text(encoding='utf-8')).get('source_sha256')!=source_key(source):raise ValueError('Video được chọn khác video gốc của bản dịch.')
                self.rows=validate_rows(data,info);self.source=source.resolve();self.info=info;self.project_path=Path(str(p).replace('.translations.json','.project.json'));self.modified=False;self.fill();self.preview();return
            if data.get('version')!=1:raise ValueError('Định dạng dự án không được hỗ trợ.')
            source=Path(data['source'])
            if not source.is_file():
                selected,_=QFileDialog.getOpenFileName(self,'Chọn lại video gốc','','Video (*.mp4 *.mkv *.mov *.webm *.avi)')
                if not selected:return
                source=Path(selected)
            from video_translator import probe
            info=probe(source)
            from ocr_cache import source_key
            if data.get('source_sha256') and data['source_sha256']!=source_key(source):raise ValueError('Video được chọn khác video gốc của dự án.')
            self.rows=validate_rows(data['rows'],info);self.source=source.resolve();self.info=info;self.font=data.get('font','Arial');self.style=data.get('style',{});self.project_path=Path(p);self.modified=False;self.fill();self.preview()
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:QMessageBox.warning(self,'Không mở được dự án',str(exc))
    def add_row(self):
        try:self.rows=self.snapshot()
        except ValueError as exc:QMessageBox.warning(self,'Dòng cần sửa',str(exc));return
        i=self.table.currentRow();start=self.rows[i]['end'] if i>=0 else 0;start=min(start,max(0,self.info['duration']-.1));end=min(self.info['duration'],start+1)
        w,h=self.info['width'],self.info['height'];self.rows.append({'start':start,'end':end,'zh':'','vi':'Nhập bản dịch','box':[int(w*.25),int(h*.8),int(w*.75),int(h*.9)],'position':None});self.fill();self.table.selectRow(len(self.rows)-1);self.modified=True
    def delete_rows(self):
        selected=sorted({item.row() for item in self.table.selectedItems()},reverse=True)
        for i in selected:self.table.removeRow(i);self.rows.pop(i)
        self.modified=True
    def export(self):
        try:
            rows=self.snapshot()
            if not self.source or not self.source.is_file():raise ValueError('Cần chọn đúng video gốc để xuất lại.')
            p,_=QFileDialog.getSaveFileName(self,'Xuất video đã chỉnh',str(self.source.with_name(self.source.stem+'_edited.mp4')),'MP4 (*.mp4)')
            if not p:return
            output=Path(p).with_suffix('.mp4').resolve()
            if output==self.source:raise ValueError('Tệp đầu ra không được trùng video gốc.')
            self.export_requested.emit({'source':self.source,'output':output,'rows':rows,'font':self.font,'style':self.style})
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,'Chưa thể xuất',str(exc))
