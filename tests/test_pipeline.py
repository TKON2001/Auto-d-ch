import unittest,json,tempfile,types
from pathlib import Path
from unittest.mock import patch
import video_translator as v
from translation_core import parse_lines,translate_context
from subtitle_layout import layout
class PipelineTests(unittest.TestCase):
 def test_repeated_sentence_keeps_context(self):
  calls=[]
  def create(**kw):
   p=json.loads(kw['input']);calls.append(p)
   return types.SimpleNamespace(status='completed',output_text=json.dumps({'lines':[{'id':x['id'],'vi':'Dịch '+str(x['id'])} for x in p['translate']]}))
  client=types.SimpleNamespace(responses=types.SimpleNamespace(create=create))
  cues=[v.Cue(i,i+.5,'你好',(10,100,150,120)) for i in range(26)]
  out=translate_context(cues,'','gpt-6.1-sol',lambda _:None,client=client,batch_size=24)
  self.assertEqual(out[0],'Dịch 0');self.assertEqual(out[25],'Dịch 25');self.assertTrue(calls[0]['context_only']);self.assertTrue(calls[1]['previous_translations'])
 def test_missing_translation_retried(self):
  count=[0]
  def create(**kw):
   count[0]+=1;p=json.loads(kw['input']);ids=p['translate'][:1] if count[0]==1 else p['translate']
   return types.SimpleNamespace(status='completed',output_text=json.dumps({'lines':[{'id':x['id'],'vi':'Xin chào'} for x in ids]}))
  c=types.SimpleNamespace(responses=types.SimpleNamespace(create=create))
  out=translate_context([v.Cue(0,1,'你',(0,0,10,10)),v.Cue(1,2,'好',(0,0,10,10))],'','gpt-6.1-sol',lambda _:None,client=c)
  self.assertEqual(count[0],2);self.assertEqual(len(out),2)
 def test_invalid_json_and_duplicate_id(self):
  for content in [None,'null','{"lines":[{"id":0,"vi":"a"},{"id":0,"vi":"b"}]}','{"lines":[{"id":0,"vi":""}]}']:
   with self.assertRaises((ValueError,TypeError)):parse_lines(content,{0})
 def test_timing_changed_short_text(self):
  box=(100,300,300,325)
  cues=v.cluster([(0,'不行',box,.9),(.125,'不行',box,.9),(.25,'可以',box,.9),(.375,'可以',box,.9)],1)
  self.assertEqual(len(cues),2);self.assertLessEqual(cues[0].end,cues[1].start)
 def test_multiple_regions_not_merged(self):
  cues=v.cluster([(0,'你好',(0,20,50,40),.8),(0,'你好',(300,300,400,320),.8)],1)
  self.assertEqual(len(cues),2)
 def test_timing_at_default_ocr_fps(self):
  box=(100,900,300,930);step=1/1.5
  cues=v.cluster([(0,'你好',box,.9),(step,'你好',box,.9),(2*step,'再见',box,.9)],2,sample_step=step)
  self.assertEqual(len(cues),2)
  self.assertAlmostEqual(cues[0].end,1)
  self.assertAlmostEqual(cues[1].start,1)
  self.assertGreater(cues[1].end-cues[1].start,.6)
 def test_long_and_edge_layout(self):
  cues=[v.Cue(0,2,'一',(1,400,100,430)),v.Cue(0,2,'二',(1,350,100,380))]
  output=layout(cues,['Một câu rất dài '*15,'Một dòng khác'],{'width':1024,'height':576},'Arial',24,{})
  self.assertIn('\n',output[0][3])
  for _,_,_,_,box in output:self.assertGreaterEqual(box[0],0);self.assertLessEqual(box[2],1024);self.assertGreaterEqual(box[1],0);self.assertLessEqual(box[3],576)
 def test_no_silent_ass_truncation(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(RuntimeError):v.create_ass([v.Cue(0,1,'你',(1,1,10,10))],[],{'height':576,'width':1024},Path(d)/'x.ass')
 def test_probe_utf8_and_empty_result(self):
  with patch.object(v,'find_binary',return_value='ffprobe'),patch.object(v,'run',return_value=types.SimpleNamespace(stdout=None)):
   with self.assertRaisesRegex(RuntimeError,'FFprobe'):v.probe(Path('x.mp4'))
 def test_cache_identity_and_source_change(self):
  from ocr_cache import load_cache,save_cache,source_key
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'gốc⭐.mp4';source.write_bytes(b'video-one');out=root/'out.mp4'
   info={'width':1024,'height':576,'duration':3};cues=[v.Cue(0,1,'你好',(10,20,100,40))];key=source_key(source)
   save_cache(out,key,info,cues)
   self.assertEqual(load_cache(out,key,info,v.Cue)[0].text,'你好')
   source.write_bytes(b'video-two');self.assertIsNone(load_cache(out,source_key(source),info,v.Cue))
 def test_vertical_projection(self):
  import numpy as np
  from ocr_core import vertical_regions
  crop=np.zeros((100,25),dtype=np.uint8)
  crop[8:25,5:20]=255;crop[40:57,5:20]=255;crop[73:90,5:20]=255
  regions=vertical_regions(crop);self.assertEqual(len(regions),1);self.assertEqual(len(regions[0]),3)
if __name__=='__main__':unittest.main()
