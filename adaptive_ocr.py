"""Cheap region tracking and new bright-text proposals between full OCR scans."""
def unchanged(a,b,np):
    if a.shape!=b.shape:return False
    delta=np.abs(a.astype('int16')-b.astype('int16'))
    return float(delta.mean())<1 and float((delta>12).mean())<.005

def track_regions(previous,current,boxes,cv,np):
    if previous is None:return boxes,False
    h,w=current.shape;tracked=[];unstable=False
    for x1,y1,x2,y2 in boxes:
        template=previous[y1:y2,x1:x2]
        if not template.size or template.std()<2:
            tracked.append((x1,y1,x2,y2));continue
        xa=max(0,x1-16);ya=max(0,y1-16);xb=min(w,x2+16);yb=min(h,y2+16)
        area=current[ya:yb,xa:xb]
        if area.shape[0]<template.shape[0] or area.shape[1]<template.shape[1]:unstable=True;tracked.append((x1,y1,x2,y2));continue
        scores=cv.matchTemplate(area,template,cv.TM_CCOEFF_NORMED)
        _,confidence,_,position=cv.minMaxLoc(scores)
        if confidence<.9:unstable=True;tracked.append((x1,y1,x2,y2));continue
        x=xa+position[0];y=ya+position[1];tracked.append((x,y,x+template.shape[1],y+template.shape[0]))
    return tracked,unstable

def new_text(previous,current,boxes,cv,np):
    # This is only an early trigger. Periodic full scans remain mandatory,
    # including dark, coloured and single-character text missed here.
    if previous is None:return True
    scale=min(1.,512/current.shape[1]);size=(max(1,int(current.shape[1]*scale)),max(1,int(current.shape[0]*scale)))
    now=cv.resize(current,size);old=cv.resize(previous,size)
    changed=((now>190)&(np.abs(now.astype('int16')-old.astype('int16'))>25)).astype('uint8')
    for x1,y1,x2,y2 in boxes:
        xa=max(0,int(x1*scale)-3);ya=max(0,int(y1*scale)-3);xb=min(size[0],int(x2*scale)+4);yb=min(size[1],int(y2*scale)+4)
        changed[ya:yb,xa:xb]=0
    count,_,stats,_=cv.connectedComponentsWithStats(changed,8)
    for x,y,w,h,area in stats[1:]:
        if 3<=h<=48 and 2<=w<=96 and area>=8 and .1<=w/max(h,1)<=12:return True
    return False
