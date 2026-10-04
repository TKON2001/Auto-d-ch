import unittest,json,tempfile,types
from pathlib import Path
from unittest.mock import patch
from translation_core import translate_context,recover_lines,TranslationIncomplete
class RecoveryTests(unittest.TestCase):
 def test_sparse_ocr_stops_before_api_and_render(self):
  import video_translator as v
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.mp4';source.write_bytes(b'video');out=Path(d)/'out.mp4'
   cues=[v.Cue(133.293,133.458,'人^',(846,767,906,797))]
   with patch.object(v,'ffmpeg_path',return_value='ffmpeg'),patch.object(v,'obtain_source',return_value=source),patch.object(v,'probe',return_value={'width':1920,'height':1080,'duration':260,'has_audio':True}),patch.object(v,'load_cache',return_value=cues),patch.object(v,'translate') as translate,patch.object(v,'render') as render:
    with self.assertRaisesRegex(RuntimeError,'trước khi gọi API'):v.process(str(source),out,'test',log=lambda _:None)
   translate.assert_not_called();render.assert_not_called();self.assertFalse(out.exists())
 def test_salvage_split_and_resume(self):
  cues=[types.SimpleNamespace(text='你好',start=i,end=i+1) for i in range(4)];calls=[]
  def create(**kw):
   ids=[r['id'] for r in json.loads(kw['input'])['translate']];calls.append(ids)
   rows=[{'id':0,'vi':'good'},{'id':99,'vi':'wrong'},{'id':1,'vi':''}] if len(calls)==1 else ([{'id':ids[0],'vi':'ok'}] if len(ids)==1 else [])
   return types.SimpleNamespace(status='completed',output_text=json.dumps({'lines':rows}))
  c=types.SimpleNamespace(responses=types.SimpleNamespace(create=create))
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'cache.json';out=translate_context(cues,'','gpt-6.1-sol',lambda _:None,client=c,cache_path=path)
   self.assertEqual(out,['good','ok','ok','ok']);self.assertTrue(all(0 not in ids for ids in calls[1:]));calls.clear()
   self.assertEqual(translate_context(cues,'','gpt-6.1-sol',lambda _:None,client=c,cache_path=path),out);self.assertEqual(calls,[])
 def test_conflicting_duplicates(self):
  rows=[{'id':0,'vi':'a'},{'id':0,'vi':'b'},{'id':1,'vi':'ok'},{'id':2,'vi':''}]
  self.assertEqual(recover_lines(json.dumps({'lines':rows}),{0,1,2}),{1:'ok'})
 def test_partial_video_not_success(self):
  import video_translator as v
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.mp4';source.write_bytes(b'video');out=Path(d)/'out.mp4';cues=[v.Cue(0,1,'你好',(0,0,50,20))]
   def render(source,output,*args):output.write_bytes(b'mp4')
   with patch.object(v,'obtain_source',return_value=source),patch.object(v,'probe',return_value={'width':160,'height':100,'duration':1,'has_audio':False}),patch.object(v,'load_cache',return_value=cues),patch.object(v,'translate',side_effect=TranslationIncomplete([''])),patch.object(v,'render',side_effect=render):
    with self.assertRaisesRegex(RuntimeError,'Video tạm'):v.process(str(source),out,'test',log=lambda _:None)
   self.assertTrue((Path(d)/'out_partial.mp4').exists());self.assertFalse(out.exists());self.assertIn('[Chưa dịch]',(Path(d)/'out_partial.translations.json').read_text(encoding='utf-8'))
 def test_persistent_failure_saves_good_lines(self):
  cues=[types.SimpleNamespace(text='你好',start=i,end=i+1) for i in range(2)]
  def create(**kw):return types.SimpleNamespace(status='completed',output_text='{"lines":[{"id":0,"vi":"ok"}]}')
  c=types.SimpleNamespace(responses=types.SimpleNamespace(create=create))
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'cache.json'
   with self.assertRaises(TranslationIncomplete):translate_context(cues,'','gpt-6.1-sol',lambda _:None,client=c,cache_path=path)
   self.assertEqual(json.loads(path.read_text())['lines'],['ok',''])
 def test_invalid_api_key_message(self):
  cues=[types.SimpleNamespace(text='你好',start=0,end=1)]
  class InvalidKeyError(RuntimeError):
   status_code=401
   body={'error':{'message':'Your API key has been invalidated.','code':'token_invalidated'}}
  def create(**kw):
   raise InvalidKeyError('Error code: 401 - {"error": {"message": "Your API key has been invalidated."}}')
  c=types.SimpleNamespace(responses=types.SimpleNamespace(create=create))
  with self.assertRaisesRegex(RuntimeError,'API key OpenAI.*vô hiệu|vô hiệu hóa|API key.*hết hạn'):
   translate_context(cues,'BAD','gpt-6.1-sol',lambda _:None,client=c)
 def test_rate_limit_waits_and_retries(self):
  cues=[types.SimpleNamespace(text='ä½ å¥½',start=0,end=1)]
  calls=[];waits=[];logs=[]
  class RateLimitError(RuntimeError):
   status_code=429
  def create(**kw):
   calls.append(kw)
   if len(calls)==1:raise RateLimitError('rate limit')
   return types.SimpleNamespace(status='completed',output_text='{"lines":[{"id":0,"vi":"ok"}]}')
  c=types.SimpleNamespace(responses=types.SimpleNamespace(create=create))
  out=translate_context(cues,'','gpt-6.1-sol',logs.append,client=c,retry_sleep=waits.append)
  self.assertEqual(out,['ok'])
  self.assertEqual(len(calls),2)
  self.assertEqual(waits,[15])
  self.assertTrue(any('429' in line for line in logs))
