"""Measure, wrap and place subtitles without clipping or stacking on each other."""
import os,math
from functools import lru_cache
from pathlib import Path
from PIL import ImageFont

@lru_cache(maxsize=128)
def load_font(name,size,bold=False,italic=False):
    candidates=[name,name+'.ttf']
    if os.name=='nt':
        folder=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts') as key:
                for i in range(winreg.QueryInfoKey(key)[1]):
                    title,value,_=winreg.EnumValue(key,i)
                    if title.lower().startswith(name.lower()) and ('bold' in title.lower())==bool(bold) and ('italic' in title.lower())==bool(italic):candidates.insert(0,str(folder/value))
        except OSError:pass
        candidates.extend([str(folder/'arial.ttf'),str(folder/'segoeui.ttf')])
    candidates+=['DejaVuSans.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for p in candidates:
        try:return ImageFont.truetype(p,size)
        except OSError:pass
    return ImageFont.load_default(size=size)

def wrap_text(text,font,width,spacing=0):
    def measure(s):return float(font.getlength(s))+max(0,len(s)-1)*spacing
    result=[]
    for paragraph in text.splitlines() or ['']:
        line=''
        for word in paragraph.split():
            trial=(line+' '+word).strip()
            if line and measure(trial)>width:result.append(line);line=''
            while measure(word)>width and len(word)>1:
                k=1
                while k<len(word) and measure(word[:k+1])<=width:k+=1
                if line:result.append(line);line=''
                result.append(word[:k]);word=word[k:]
            line=(line+' '+word).strip()
        if line:result.append(line)
    return result or [''],measure

def intersects(a,b,gap=3):return a[0]<b[2]+gap and b[0]<a[2]+gap and a[1]<b[3]+gap and b[1]<a[3]+gap

def layout(cues,translations,info,font_name,size,style):
    if len(cues)!=len(translations):raise ValueError('Số dòng dịch không khớp phụ đề.')
    w,h=info['width'],info['height'];margin=max(8,round(h*.018));gap=max(4,round(h*float(style.get('gap_ratio',.012))))
    active=[];output=[None]*len(cues)
    ordered=sorted(enumerate(cues),key=lambda item:item[1].start)
    source_active=[];cursor=0
    for index,c in ordered:
        vi=translations[index]
        active=[(end,box) for end,box in active if end>c.start]
        source_active=[other for other in source_active if other.end>c.start]
        while cursor<len(ordered) and ordered[cursor][1].start<c.end:
            other=ordered[cursor][1];cursor+=1
            if other.end>c.start:source_active.append(other)
        fontsize=size;maxwidth=w-2*margin
        font=load_font(font_name,fontsize,style.get('bold'),style.get('italic'))
        wrapped,measure=wrap_text(vi,font,min(maxwidth,w*.85),float(style.get('spacing',0)))
        # Keep long translations intact; fit into screen rather than discard words.
        while len(wrapped)*fontsize*1.3>h*.4 and fontsize>12:
            fontsize-=1;font=load_font(font_name,fontsize,style.get('bold'),style.get('italic'));wrapped,measure=wrap_text(vi,font,min(maxwidth,w*.85),float(style.get('spacing',0)))
        width=min(maxwidth,max(measure(line) for line in wrapped)+2*float(style.get('outline',2.2))+8)
        height=math.ceil(len(wrapped)*fontsize*1.3+2*float(style.get('outline',2.2))+4)
        cx=max(margin+width/2,min(w-margin-width/2,(c.box[0]+c.box[2])/2))
        bottom=c.box[1]-gap
        blockers=[box for end,box in active]+[other.box for other in source_active if other.start<c.end]
        rect=(cx-width/2,bottom-height,cx+width/2,bottom)
        for _ in range(len(blockers)+1):
            hits=[b for b in blockers if intersects(rect,b)]
            if not hits:break
            bottom=min(b[1] for b in hits)-gap;rect=(cx-width/2,bottom-height,cx+width/2,bottom)
        if rect[1]<margin:
            bottom=c.box[3]+gap+height;rect=(cx-width/2,bottom-height,cx+width/2,bottom)
            for _ in range(len(blockers)+1):
                hits=[b for b in blockers if intersects(rect,b)]
                if not hits:break
                bottom=max(b[3] for b in hits)+gap+height;rect=(cx-width/2,bottom-height,cx+width/2,bottom)
            if bottom>h-margin:
                # Crowded frames cannot guarantee non-overlap. Remain within image.
                bottom=h-margin;rect=(cx-width/2,max(margin,bottom-height),cx+width/2,bottom)
        active.append((c.end,rect));output[index]=(round(cx),round(bottom),fontsize,'\n'.join(wrapped),rect)
    return output
