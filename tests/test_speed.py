import unittest,tempfile,json,types
from pathlib import Path
from translation_core import translate_context
from video_translator import Cue
class SpeedTests(unittest.TestCase):
 def test_cache_resume_and_invalidation(self):
  calls=[];fail=[True]
  def create(**kw):
   data=json.loads(kw['input']);calls.append(data)
   if len(calls)==2 and fail[0]:raise RuntimeError('network')
   return types.SimpleNamespace(status='completed',output_text=json.dumps({'lines':[{'id':r['id'],'vi':'Dịch '+str(r['id'])} for r in data['translate']]}))
  client=types.SimpleNamespace(responses=types.SimpleNamespace(create=create))
  cues=[Cue(i,i+1,'你好',(0,0,50,10)) for i in range(60)]
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'cache.json';kwargs=dict(client=client,cache_path=path)
   with self.assertRaises(RuntimeError):translate_context(cues,'SECRET','gpt-6.1-sol',lambda _:None,**kwargs)
   self.assertNotIn('SECRET',path.read_text())
   fail[0]=False;calls.clear()
   out=translate_context(cues,'SECRET','gpt-6.1-sol',lambda _:None,**kwargs)
   self.assertEqual(len(calls),1);self.assertEqual(len(calls[0]['translate']),12);self.assertEqual(out[-1],'Dịch 59')
   calls.clear();translate_context(cues,'SECRET','gpt-6.1-sol',lambda _:None,**kwargs);self.assertEqual(calls,[])
   translate_context(cues,'SECRET','gpt-6.1-sol',lambda _:None,glossary='new',**kwargs);self.assertEqual(len(calls),2)
 def test_invalid_cache_ignored(self):
  def create(**kw):return types.SimpleNamespace(status='completed',output_text='{"lines":[{"id":0,"vi":"Chào"}]}')
  client=types.SimpleNamespace(responses=types.SimpleNamespace(create=create))
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'cache.json';path.write_text('{broken')
   self.assertEqual(translate_context([Cue(0,1,'你',(0,0,10,10))],'','gpt-6.1-sol',lambda _:None,client=client,cache_path=path),['Chào'])
class OCRSpeedTests(unittest.TestCase):
 def test_default_scan_finds_top_and_bottom_text(self):
  import cv2,numpy as np
  from ocr_core import scan
  shapes=[];crops=[]
  class Reader:
   def detect(self,frame,**kw):
    shapes.append(frame.shape[:2]);return ([[[5,75,5,20],[85,155,80,95]]],[[]])
   def recognize(self,crop,**kw):
    crops.append(crop.shape);return [([[0,0],[70,0],[70,15],[0,15]],'你好',.95)]
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'test.avi';writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),8,(160,100))
   for i in range(8):writer.write(np.full((100,160,3),70,dtype=np.uint8))
   writer.release()
   rows,_=scan(path,{'duration':1},Path(d),lambda _:None,reader=Reader())
  self.assertTrue(shapes);self.assertTrue(all(shape==(100,160) for shape in shapes))
  self.assertTrue(crops);self.assertTrue(all(shape==(15,70) for shape in crops))
  self.assertTrue(any(box[1]==5 for _,_,box,_ in rows));self.assertTrue(any(box[1]==80 for _,_,box,_ in rows))
 def test_stable_cache_still_reads_changed_pixels(self):
  import cv2,numpy as np
  from ocr_core import scan
  class Reader:
   count=0
   def detect(self,frame,**kw):return ([[[5,155,5,35]]],[[]])
   def recognize(self,crop,**kw):
    self.count+=1
    return [([[0,0],[150,0],[150,30],[0,30]],'你好' if crop.mean()<110 else '再见',.95)]
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'test.avi';writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),8,(160,48))
   for i in range(16):writer.write(np.full((48,160,3),70 if i<8 else 150,dtype=np.uint8))
   writer.release();reader=Reader()
   rows,_=scan(path,{'duration':2},Path(d),lambda _:None,reader=reader,region=(0,1),fps=4)
   self.assertLess(reader.count,8);self.assertTrue(any(t>=1 and text=='再见' for t,text,_,_ in rows))
 def test_gpu_batch_preserves_two_boxes(self):
  import cv2,numpy as np
  from ocr_core import scan
  class Reader:
   batches=0
   def detect(self,frame,**kw):return ([[[5,75,5,20],[85,155,25,40]]],[[]])
   def recognize(self,crop,**kw):
    boxes=kw.get('horizontal_list')
    if boxes:
     self.batches+=1
     return [([[x1,y1],[x2,y1],[x2,y2],[x1,y2]],'你好',.95) for x1,x2,y1,y2 in boxes]
    return [([[0,0],[70,0],[70,15],[0,15]],'你好',.95)]
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'test.avi';writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),8,(160,48))
   for i in range(8):writer.write(np.full((48,160,3),70,dtype=np.uint8))
   writer.release();reader=Reader();rows,_=scan(path,{'duration':1},Path(d),lambda _:None,reader=reader,gpu=True,region=(0,1),fps=4)
   # Four sampled frames per second, with two text boxes per frame.
   self.assertEqual(reader.batches,1);self.assertEqual(len(rows),8)
