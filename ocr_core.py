"""Full-frame detection plus intermediate line reading, with conservative pixel cache."""
import re,time,math
from difflib import SequenceMatcher
from statistics import median
CHINESE=re.compile(r'[\u3400-\u9fff]')
DEFAULT_REGION=(0.0,1.0)

def scan_settings(fps=1.5, region=DEFAULT_REGION):
    fps=float(fps)
    top,bottom=map(float,region)
    if not math.isfinite(fps) or fps<=0:
        raise ValueError('FPS OCR phải là số dương hữu hạn.')
    if not 0<=top<bottom<=1:
        raise ValueError('Vùng OCR phải thỏa 0 ≤ trên < dưới ≤ 1.')
    return max(.25,1.0/max(1.0,fps)),(top,bottom)

def validate_translation_input(cues,duration):
    if not cues or not any(CHINESE.search(c.text) for c in cues):
        raise RuntimeError('OCR không có chữ Trung hợp lệ; chưa gọi API dịch.')
    if duration>=60 and len(cues)<=2 and sum(c.end-c.start for c in cues)<1:
        raise RuntimeError('OCR chỉ nhận được vài chữ thoáng qua trong video dài; đã dừng trước khi gọi API dịch. Hãy kiểm tra dữ liệu OCR và quét lại.')
def same_lane(a,b):
    overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))
    return abs((a[1]+a[3])-(b[1]+b[3])) < max(12,min(a[3]-a[1],b[3]-b[1])) and overlap/max(1,min(a[2]-a[0],b[2]-b[0]))>.6

def group_samples(samples,duration,cue_type,sample_step=.125):
    groups=[];active=[];window=max(.28,sample_step*1.5)
    for t,txt,box,conf in sorted(samples,key=lambda v:v[0]):
        norm=re.sub(r'\s+','',txt); match=None
        active=[g for g in active if t-g['last']<=window]
        for g in reversed(active):
            if not same_lane(box,g['boxes'][-1]): continue
            # Never merge changed numbers or short, different sentences.
            close=norm==g['norm'] or (len(norm)>=10 and len(g['norm'])==len(norm) and re.findall(r'\d+',norm)==re.findall(r'\d+',g['norm']) and SequenceMatcher(None,norm,g['norm']).ratio()>=.94)
            if close: match=g;break
        if match:
            match['last']=t;match['boxes'].append(box);match['texts'].append((conf,txt))
        else:
            group={'norm':norm,'first':t,'last':t,'boxes':[box],'texts':[(conf,txt)]}
            groups.append(group);active.append(group)
    cues=[]
    for g in groups:
        box=tuple(round(median(b[i] for b in g['boxes'])) for i in range(4))
        cues.append(cue_type(max(0,g['first']-sample_step/2),min(duration,g['last']+sample_step/2),max(g['texts'])[1],box))
    cues.sort(key=lambda c:(c.start,c.box[1],c.box[0]))
    for i,c in enumerate(cues):
        for j in range(i+1,len(cues)):
            nxt=cues[j]
            if nxt.start>=c.end:break
            if same_lane(c.box,nxt.box) and nxt.start>c.start:c.end=min(c.end,nxt.start)
    return [c for c in cues if c.end>c.start]

def vertical_regions(crop):
    """Split upright vertical lettering by ink projections, without rotating glyphs."""
    import cv2,numpy as np
    ink=(crop>190).astype('uint8')
    if ink.mean()>.4:return []
    def runs(mask):
        values=[];start=None
        for i,on in enumerate(list(mask)+[False]):
            if on and start is None:start=i
            if not on and start is not None:values.append((start,i));start=None
        return values
    # Bridge small inter-stroke gaps inside a glyph, not gaps between columns.
    cols=cv2.dilate((ink.sum(axis=0)>2).astype('uint8')[None,:],np.ones((1,5),np.uint8))[0]>0
    result=[]
    for xa,xb in runs(cols):
        if xb-xa<6:continue
        rows=cv2.dilate((ink[:,xa:xb].sum(axis=1)>2).astype('uint8')[:,None],np.ones((3,1),np.uint8))[:,0]>0
        chars=[(max(0,xa-2),max(0,ya-2),min(crop.shape[1],xb+2),min(crop.shape[0],yb+2)) for ya,yb in runs(rows) if yb-ya>=6]
        if len(chars)>=2:result.append(chars)
    return result


def scan(video,info,model_path,log,gpu=False,reader=None,limit=None,checkpoint=None,fps=1.5,region=DEFAULT_REGION):
    check=checkpoint or (lambda:None);check()
    sample_step,region=scan_settings(fps,region)
    import cv2,numpy as np
    from adaptive_ocr import unchanged,track_regions,new_text
    if reader is None:
        from ocr_loader import get_reader
        reader,gpu=get_reader(model_path,gpu,log)
    check()
    from resource_limits import configure_cv
    configure_cv(cv2)
    cap=cv2.VideoCapture()
    opened=False
    if hasattr(cv2,'CAP_PROP_N_THREADS'):
        try:opened=cap.open(str(video),cv2.CAP_FFMPEG,[cv2.CAP_PROP_N_THREADS,1])
        except cv2.error:opened=False
    if not opened:cap.open(str(video))
    if not cap.isOpened():raise RuntimeError('Không mở được video để quét OCR.')
    sf=cap.get(cv2.CAP_PROP_FPS) or 25;n=cap.get(cv2.CAP_PROP_FRAME_COUNT);duration=info['duration'] or n/sf
    top_ratio,bottom_ratio=region
    log(f'OCR thích ứng: theo dõi vùng chữ, đọc khi đổi; dò toàn khung định kỳ • {"CUDA" if gpu else "CPU"} • fps={fps:.1f} vùng={top_ratio:.2f}-{bottom_ratio:.2f}')
    samples=[];boxes=[];cache=[];vertical_cache=[];prev=None;i=0;last_detect=-1.;next_sample=0.;last_log=-10.;hits=0;reads=0;started=time.monotonic();previous_gray=None;detected_gray=None;detections=0
    skipped_frames=0;previous_shape=None
    try:
        while True:
            check()
            if not cap.grab():break
            t=i/sf;i+=1
            if limit is not None and t>limit:break
            if t+1e-8<next_sample:continue
            next_sample+=sample_step
            ok,frame=cap.retrieve()
            if not ok or frame is None or frame.size==0:
                skipped_frames+=1
                continue
            # Use decoded dimensions (metadata may be stale/rotated). Never reuse
            # text-box coordinates as ROI bounds: y1 below belongs to a box.
            height=frame.shape[0]
            roi_top=max(0,min(height-1,int(height*top_ratio)))
            roi_bottom=max(roi_top+1,min(height,int(height*bottom_ratio)))
            frame_shape=frame.shape
            frame=frame[roi_top:roi_bottom]
            if frame.size==0:
                skipped_frames+=1
                continue
            if frame_shape!=previous_shape:
                boxes=[];cache=[];vertical_cache=[];prev=None
                previous_gray=None;detected_gray=None;last_detect=-1.
                previous_shape=frame_shape
            gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY);thumb=cv2.resize(gray,(64,36))
            scene=prev is not None and np.abs(thumb.astype(float)-prev.astype(float)).mean()>24
            prev=thumb
            boxes,unstable=track_regions(previous_gray,gray,boxes,cv2,np)
            novelty=new_text(detected_gray,gray,boxes,cv2,np)
            interval=.5 if gpu else .75
            due=t-last_detect>=interval
            early=t-last_detect>=.24 and (unstable or novelty)
            if due or early or scene or last_detect<0:
                horizontal,free=reader.detect(frame,canvas_size=2560,text_threshold=.6,low_text=.3,link_threshold=.3,mag_ratio=1.)
                boxes=[]
                for x1,x2,y1_box,y2 in horizontal[0]:boxes.append((max(0,int(x1)),max(0,int(y1_box)),min(gray.shape[1],int(x2)),min(gray.shape[0],int(y2))))
                for poly in free[0]:boxes.append((max(0,int(min(p[0] for p in poly))),max(0,int(min(p[1] for p in poly))),min(gray.shape[1],int(max(p[0] for p in poly))),min(gray.shape[0],int(max(p[1] for p in poly)))))
                last_detect=t;detected_gray=gray.copy();detections+=1
                if scene:cache=[];vertical_cache=[]
            newcache=[];new_vertical_cache=[]
            batched={}
            if gpu:
                pending=[]
                for box in boxes:
                    x1,y1,x2,y2=box;crop=gray[y1:y2,x1:x2]
                    if not crop.size or crop.shape[0]>crop.shape[1]*1.5:continue
                    tiny=cv2.resize(crop,(128,32))
                    cached=any(conf>=.65 and t-read_t<2.0 and same_lane(box,oldbox) and unchanged(tiny,pixels,np) for oldbox,pixels,txt,conf,read_t in cache)
                    if not cached:pending.append(box)
                if len(pending)>1:
                    check()
                    got=reader.recognize(gray,horizontal_list=[[b[0],b[2],b[1],b[3]] for b in pending],free_list=[],detail=1,paragraph=False,batch_size=min(16,len(pending)),workers=0)
                    if len(got)==len(pending):
                        for box in pending:
                            candidates=[r for r in got if same_lane(box,(min(pt[0] for pt in r[0]),min(pt[1] for pt in r[0]),max(pt[0] for pt in r[0]),max(pt[1] for pt in r[0])))]
                            if len(candidates)==1:batched[box]=candidates
            for box in boxes:
                check()
                x1,y1,x2,y2=box;crop=gray[y1:y2,x1:x2]
                if crop.size==0:continue
                tiny=cv2.resize(crop,(128,32));reused=None
                for oldbox,pixels,txt,conf,read_t in cache:
                    if conf>=.65 and t-read_t<2.0 and same_lane(box,oldbox) and unchanged(tiny,pixels,np):
                        tiny=pixels
                        reused=(txt,conf,read_t);break
                if reused:txt,conf,read_t=reused;hits+=1
                else:
                    vertical=vertical_regions(crop) if crop.shape[0]>crop.shape[1]*1.5 else []
                    if vertical:
                        reused_vertical=None
                        for oldbox,pixels,entries,read_t in vertical_cache:
                            if t-read_t<.5 and same_lane(box,oldbox) and unchanged(tiny,pixels,np):
                                reused_vertical=(entries,read_t);break
                        if reused_vertical: entries,vertical_t=reused_vertical
                        else:
                            entries=[];vertical_t=t
                            for chars in vertical:
                                letters=[];scores=[]
                                for xa,ya,xb,yb in chars:
                                    char=crop[ya:yb,xa:xb]
                                    got=reader.recognize(char,detail=1,workers=0)
                                    if got and (CHINESE.search(got[0][1]) or re.fullmatch(r'[A-Z0-9]+',got[0][1])):letters.append(got[0][1]);scores.append(float(got[0][2]))
                                if letters:
                                    vbox=(x1+min(c[0] for c in chars),y1+min(c[1] for c in chars),x1+max(c[2] for c in chars),y1+max(c[3] for c in chars))
                                    entries.append((''.join(letters),vbox,sum(scores)/len(scores)))
                        new_vertical_cache.append((box,tiny,entries,vertical_t))
                        samples.extend((t,txt,(vbox[0],vbox[1]+roi_top,vbox[2],vbox[3]+roi_top),confidence) for txt,vbox,confidence in entries if confidence>=.05)
                    results=batched.get(box)
                    if results is None:results=reader.recognize(crop,detail=1,paragraph=False,batch_size=8 if gpu else 1,workers=0,rotation_info=[90,270] if crop.shape[0]>crop.shape[1]*1.5 and not vertical else None)
                    reads+=1;read_t=t
                    if not results:continue
                    txt=' '.join(v[1] for v in results).strip();conf=min(float(v[2]) for v in results)
                    if conf<.5 and CHINESE.search(txt):
                        larger=cv2.threshold(crop,180,255,cv2.THRESH_BINARY_INV)[1]
                        larger=cv2.resize(larger,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
                        retry=reader.recognize(larger,detail=1,paragraph=False,decoder='beamsearch',beamWidth=5,workers=0)
                        if retry and min(float(v[2]) for v in retry)>conf:txt=' '.join(v[1] for v in retry).strip();conf=min(float(v[2]) for v in retry)
                newcache.append((box,tiny,txt,conf,read_t))
                # Tracking/cache boxes stay ROI-local; downstream rendering uses
                # coordinates in the original decoded frame.
                if conf>=.05 and CHINESE.search(txt):samples.append((t,txt,(x1,y1+roi_top,x2,y2+roi_top),conf))
            cache=newcache;vertical_cache=new_vertical_cache;previous_gray=gray.copy()
            if t-last_log>=5:
                log(f'Đang quét phụ đề: {min(99,int(t/max(duration,.01)*100))}%');last_log=t
    finally:cap.release()
    if skipped_frames:log(f'OCR bỏ qua {skipped_frames} khung hình rỗng hoặc không giải mã được.')
    log(f'OCR hoàn tất: {detections} lượt dò toàn khung, {reads} lượt đọc, {hits} lượt dùng lại vùng chữ không đổi, {time.monotonic()-started:.1f}s')
    return samples,duration
