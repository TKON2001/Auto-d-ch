import unittest,tempfile,types
from pathlib import Path
import cv2,numpy as np
from adaptive_ocr import unchanged,track_regions,new_text
from ocr_core import scan
class AdaptiveTests(unittest.TestCase):
 def test_reference_pixels_detect_small_change(self):
  a=np.zeros((32,128),np.uint8);b=a.copy();b[10:15,10:15]=255
  self.assertFalse(unchanged(a,b,np));self.assertTrue(unchanged(a,a,np))
 def test_tracking_moves_region(self):
  rng=np.random.default_rng(3);a=np.zeros((100,200),np.uint8);b=a.copy();a[20:40,20:60]=rng.integers(0,255,(20,40),dtype=np.uint8);b[23:43,26:66]=a[20:40,20:60]
  boxes,unstable=track_regions(a,b,[(20,20,60,40)],cv2,np)
  self.assertFalse(unstable);self.assertEqual(boxes,[(26,23,66,43)])
 def test_new_text_outside_old_region(self):
  a=np.zeros((100,200),np.uint8);b=a.copy();b[60:75,150:160]=255
  self.assertTrue(new_text(a,b,[(0,0,60,30)],cv2,np));self.assertFalse(new_text(a,b,[(145,55,165,80)],cv2,np))
 def test_scan_reduces_detections_and_finds_new_region(self):
  class Reader:
   detects=0;reads=0
   def detect(self,frame,**kw):
    self.detects+=1;boxes=[[5,75,5,25]]
    if frame[45:60,100:120].mean()>50:boxes.append([95,145,40,65])
    return ([boxes],[[]])
   def recognize(self,crop,**kw):
    self.reads+=1
    return [([[0,0],[70,0],[70,20],[0,20]],'你好' if crop.shape[0]==20 else '新字',.95)]
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'sample.avi';writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),8,(160,80))
   for i in range(32):
    frame=np.zeros((80,160,3),np.uint8);frame[8:20,10:20]=255
    if i>=12:frame[45:60,100:110]=255
    writer.write(frame)
   writer.release();reader=Reader();logs=[]
   # Synthetic boxes use full-frame coordinates, not the default subtitle ROI.
   samples,_=scan(path,{'duration':4},Path(d),logs.append,reader=reader,region=(0,1),fps=4)
   self.assertLess(reader.detects,12);self.assertTrue(any(text=='新字' and t<=1.75 for t,text,_,_ in samples));self.assertTrue(any('lượt dò toàn khung' in s for s in logs))
   print(f'ADAPTIVE synthetic: {reader.detects} detects over 4s (old cadence about 16), {reader.reads} recognitions')
