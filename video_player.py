"""Real playback, seeking and live subtitle preview on original video."""
from pathlib import Path
from PySide6.QtCore import Qt,QUrl,QRectF,Signal
from PySide6.QtGui import QPainter,QPainterPath,QColor,QPen,QFont,QFontMetricsF,QImage
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QSlider,QLabel
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput,QVideoSink

def clock(ms):
    seconds=max(0,int(ms)//1000);m,s=divmod(seconds,60);return f'{m:02d}:{s:02d}'
class Canvas(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.image=QImage();self.items=[];self.info={};self.style={};self.font_name='Arial';self.time=0.;self.message='Chọn video để bắt đầu';self.setMinimumHeight(220)
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#0b0c0d'))
        if self.image.isNull():p.setPen(QColor('#a6adaf'));p.drawText(self.rect(),Qt.AlignCenter,self.message);return
        iw,ih=self.image.width(),self.image.height();ratio=min(self.width()/iw,self.height()/ih);x=(self.width()-iw*ratio)/2;y=(self.height()-ih*ratio)/2
        p.drawImage(QRectF(x,y,iw*ratio,ih*ratio),self.image)
        if not self.info:return
        sx=iw*ratio/self.info['width'];sy=ih*ratio/self.info['height'];p.translate(x,y);p.scale(sx,sy);p.setRenderHint(QPainter.Antialiasing)
        for start,end,cx,bottom,size,text in self.items:
            if not start<=self.time<end:continue
            font=QFont(self.font_name);font.setPixelSize(size);font.setBold(bool(self.style.get('bold')));font.setItalic(bool(self.style.get('italic')));font.setLetterSpacing(QFont.AbsoluteSpacing,float(self.style.get('spacing',0)))
            metrics=QFontMetricsF(font);lines=text.split('\n');lineheight=metrics.height();baseline=bottom-metrics.descent()-(len(lines)-1)*lineheight
            path=QPainterPath()
            for line in lines:path.addText(cx-metrics.horizontalAdvance(line)/2,baseline,font,line);baseline+=lineheight
            shadow=float(self.style.get('shadow',0))
            if shadow:p.save();p.translate(shadow,shadow);p.fillPath(path,QColor('#000000'));p.restore()
            pen=QPen(QColor(self.style.get('outline_color','#000000')));pen.setWidthF(float(self.style.get('outline',2.2))*2);pen.setJoinStyle(Qt.RoundJoin)
            if pen.widthF()>0:p.strokePath(path,pen)
            p.fillPath(path,QColor(self.style.get('color','#FFFFFF')))
class VideoPlayer(QWidget):
    position_changed=Signal(int);error=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.path=None;self.pending_seek=None;self.first_frame=False;self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.audio.setVolume(.8);self.player.setAudioOutput(self.audio);self.sink=QVideoSink(self);self.player.setVideoSink(self.sink)
        box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0);self.canvas=Canvas();box.addWidget(self.canvas,1)
        row=QHBoxLayout();self.play_button=QPushButton('Phát');self.stop_button=QPushButton('Dừng');self.slider=QSlider(Qt.Horizontal);self.slider.setRange(0,0);self.time_label=QLabel('00:00 / 00:00')
        for widget in [self.play_button,self.stop_button,self.slider,self.time_label]:row.addWidget(widget)
        box.addLayout(row);self.message=QLabel('');self.message.setWordWrap(True);box.addWidget(self.message)
        self.play_button.clicked.connect(self.toggle);self.stop_button.clicked.connect(self.stop);self.slider.sliderMoved.connect(self.player.setPosition);self.slider.sliderReleased.connect(lambda:self.player.setPosition(self.slider.value()))
        self.player.mediaStatusChanged.connect(self.media_ready);self.player.durationChanged.connect(lambda ms:self.slider.setRange(0,ms));self.player.positionChanged.connect(self.on_position);self.player.playbackStateChanged.connect(lambda state:self.play_button.setText('Tạm dừng' if state==QMediaPlayer.PlayingState else 'Phát'))
        self.sink.videoFrameChanged.connect(self.frame_changed);self.player.errorOccurred.connect(self.on_error)
    def frame_changed(self,frame):
        image=frame.toImage()
        if not image.isNull():
            self.canvas.image=image;self.canvas.update()
            if self.first_frame:self.first_frame=False;self.player.pause();self.audio.setMuted(False)
    def media_ready(self,status):
        if status==QMediaPlayer.LoadedMedia:
            if self.pending_seek is not None:self.player.setPosition(self.pending_seek);self.pending_seek=None
            if self.first_frame:self.audio.setMuted(True);self.player.play()
    def on_position(self,ms):
        if not self.slider.isSliderDown():self.slider.setValue(ms)
        self.time_label.setText(clock(ms)+' / '+clock(self.player.duration()));self.canvas.time=ms/1000;self.canvas.update();self.position_changed.emit(ms)
    def on_error(self,*args):
        self.message.setText('Không phát được video: '+self.player.errorString());self.error.emit(self.message.text())
    def load(self,path):
        path=Path(path).resolve()
        if self.path==path:return
        self.player.stop();self.path=path;self.pending_seek=None;self.first_frame=True;self.canvas.image=QImage();self.canvas.items=[];self.message.clear();self.player.setSource(QUrl.fromLocalFile(str(path)))
    def play(self):
        self.first_frame=False;self.audio.setMuted(False);self.player.play()
    def stop(self):
        self.first_frame=False;self.pending_seek=None;self.player.pause();self.player.setPosition(0)
    def toggle(self):
        self.first_frame=False;self.audio.setMuted(False)
        if self.player.playbackState()==QMediaPlayer.PlayingState:self.player.pause()
        else:self.player.play()
    def seek(self,seconds):
        ms=round(seconds*1000)
        if self.player.mediaStatus() in (QMediaPlayer.LoadingMedia,QMediaPlayer.NoMedia):self.pending_seek=ms
        else:
            if self.player.playbackState()==QMediaPlayer.StoppedState:
                self.player.setSource(QUrl());self.pending_seek=ms;self.first_frame=True;self.player.setSource(QUrl.fromLocalFile(str(self.path)))
            else:self.player.setPosition(ms);self.player.pause()
    def set_subtitles(self,items,info,font,style):self.canvas.items=items;self.canvas.info=info;self.canvas.font_name=font;self.canvas.style=dict(style);self.canvas.update()
    def clear(self):self.canvas.image=QImage();self.canvas.update()
    def setText(self,text):self.canvas.message=text;self.canvas.update()
    def shutdown(self):self.first_frame=False;self.player.stop();self.player.setSource(QUrl());self.path=None
