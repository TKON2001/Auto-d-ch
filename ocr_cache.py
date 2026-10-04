"""Validated source fingerprint so translation/style retries can skip OCR."""
import hashlib,json
from pathlib import Path
from storage import atomic_json
from ocr_core import scan_settings
POLICY='v19.4-settings-and-integrity'
def source_key(source,checkpoint=None):
    check=checkpoint or (lambda:None)
    h=hashlib.sha256()
    with source.open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):check();h.update(chunk)
    return h.hexdigest()
def metadata(key,info,fps,region):
    step,region=scan_settings(fps,region)
    return {'source_sha256':key,'policy':POLICY,'width':info['width'],'height':info['height'],'duration':info['duration'],'sample_step':step,'region':list(region)}

def cue_digest(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')).hexdigest()

def load_cache(output,key,info,cue_type,fps=1.5,region=(0.,1.)):
    try:
        meta=json.loads(output.with_suffix('.ocr.meta.json').read_text(encoding='utf-8'))
        data=json.loads(output.with_suffix('.ocr.json').read_text(encoding='utf-8'))
        if not isinstance(data,list) or meta!=dict(metadata(key,info,fps,region),cues_sha256=cue_digest(data)):return None
        cues=[]
        for row in data:
            a=float(row['start']);b=float(row['end']);box=tuple(int(x) for x in row['box']);txt=row['zh']
            if not isinstance(txt,str) or not txt.strip() or not 0<=a<b<=info['duration']+.1 or len(box)!=4 or not 0<=box[0]<box[2]<=info['width'] or not 0<=box[1]<box[3]<=info['height']:return None
            cues.append(cue_type(a,b,txt,box))
        return sorted(cues,key=lambda c:(c.start,c.box[1])) or None
    except (OSError,ValueError,TypeError,KeyError,OverflowError):return None

def save_cache(output,key,info,cues,fps=1.5,region=(0.,1.)):
    data=[{'start':c.start,'end':c.end,'zh':c.text,'box':list(c.box)} for c in cues]
    meta=dict(metadata(key,info,fps,region),cues_sha256=cue_digest(data))
    # Interrupted pairs are rejected by the digest, even when old metadata remains.
    atomic_json(output.with_suffix('.ocr.json'),data)
    atomic_json(output.with_suffix('.ocr.meta.json'),meta)
