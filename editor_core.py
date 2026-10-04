"""Validate and save editable subtitle projects; render only from original media."""
import json,math
from pathlib import Path
from types import SimpleNamespace
from subtitle_layout import layout
from storage import atomic_json

def validate_rows(rows,info):
    clean=[]
    for i,row in enumerate(rows):
        try:
            start=float(row['start']);end=float(row['end']);box=[int(v) for v in row['box']];vi=row['vi'];zh=row.get('zh','')
            if not math.isfinite(start) or not math.isfinite(end) or not 0<=start<end<=info['duration']+.1:raise ValueError('thời gian không hợp lệ')
            if len(box)!=4 or not 0<=box[0]<box[2]<=info['width'] or not 0<=box[1]<box[3]<=info['height']:raise ValueError('khung chữ không hợp lệ')
            if not isinstance(vi,str) or not vi.strip() or not isinstance(zh,str):raise ValueError('nội dung tiếng Việt rỗng')
            pos=row.get('position')
            if pos is not None:
                x,y=map(float,pos)
                if not math.isfinite(x) or not math.isfinite(y) or not 0<=x<=info['width'] or not 0<=y<=info['height']:raise ValueError('tọa độ ngoài video')
                pos=[x,y]
            clean.append({'start':start,'end':end,'box':box,'zh':zh,'vi':vi.strip(),'position':pos})
        except (KeyError,TypeError,ValueError,OverflowError) as exc:raise ValueError(f'Dòng {i+1}: {exc}') from exc
    if not clean:raise ValueError('Chưa có dòng phụ đề.')
    return sorted(clean,key=lambda r:(r['start'],r['box'][1],r['box'][0]))

def preview_items(rows,info,font,style):
    rows=validate_rows(rows,info);cues=[SimpleNamespace(start=r['start'],end=r['end'],box=r['box']) for r in rows];size=max(12,int(info['height']*float(style.get('size_ratio',.038))))
    placed=layout(cues,[r['vi'] for r in rows],info,font,size,style)
    return [(r['start'],r['end'],*(r['position'] or [x,y]),fontsize,text) for r,(x,y,fontsize,text,rect) in zip(rows,placed)]

def save_project(path,source,rows,info,font,style):
    source=Path(source).resolve()
    if not source.is_file():raise ValueError('Không tìm thấy video gốc.')
    from ocr_cache import source_key
    data={'source_sha256':source_key(source),'version':1,'source':str(source),'info':info,'font':font,'style':style,'rows':validate_rows(rows,info)}
    atomic_json(path,data);return data
