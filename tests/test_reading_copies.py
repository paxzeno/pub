import json, unittest
import test_automation
from unittest.mock import Mock, patch
from test_automation import OUTPUT
from test_pubmail import FakeGmail, raw
from pubmail import digest, automation
from pubmail.core import normalize
from pubmail.io import Error

class ReadingCopies(unittest.TestCase):
 setUp = test_automation.Automation.setUp
 tearDown = test_automation.Automation.tearDown
 def test_reading_copy_escapes_source_and_preserves_actual_target(self):
  m=normalize(raw(body='<script>untrusted</script> Claim https://redirect.example/path?a=1&b=2'))
  entry=dict(id=m['id'],subject=m['subject'],reason='Uncertain',**digest.source_notice(m,self.c))
  with patch('pubmail.digest.run') as run, patch('pubmail.image_assets.assets') as fetch:
   h,t,images=digest.render(self.c,[],[],[],skipped=[entry])
  self.assertIn('&lt;script&gt;',h);self.assertNotIn('<script>',h)
  self.assertIn('https[:]//redirect[.]example/path?a=1&b=2',t)
  self.assertIn('Shop <offers [at] shop[.]example>',t)
  self.assertIn('unreviewed text excerpt',h+t)
  self.assertNotIn('href="https://redirect',h)
  self.assertEqual(images,{});run.assert_not_called();fetch.assert_not_called()
 def test_final_failure_exposes_original_not_failed_model_summary(self):
  self.m.classify=Mock(return_value=dict(OUTPUT,summary='Draft text'))
  p=digest.prepare(self.g,self.c,self.m,self.s)
  with patch.object(self.m.reviewer,'exchange',return_value={}),patch.object(self.m.reviewer,'last_ids',['missing'],create=True):
   p=automation.final_review(self.c,self.m,self.s,p['id'])
  self.assertEqual(p['ids'],[])
  t=(self.s.root/'digests'/(p['id']+'.txt')).read_text()
  self.assertIn('Discover our summer collection.',t);self.assertNotIn('Draft text',t)
  digest.finish_labels(self.g,self.c,self.s,p['id'],p);self.assertEqual(self.g.calls,[])
 def test_copy_uses_pre_vision_source_and_discloses_trimming(self):
  m=normalize(raw(body='Original sender text.'))
  m['reading_source']=dict(m);m['body']='MODEL INVENTION'
  self.c['limits']['body_characters']=8
  notice=digest.source_notice(m,self.c)
  self.assertEqual(notice['source_excerpt'],'Original');self.assertTrue(notice['source_trimmed'])
 def test_reading_copy_change_blocks_send(self):
  self.m.classify=Mock(side_effect=Error('failure'))
  p=digest.prepare(self.g,self.c,self.m,self.s)
  self.g.messages['a1']=raw(body='Changed')
  with patch('pubmail.digest.run') as smtp:
   with self.assertRaisesRegex(Error,'Reading-copy source changed'):
    digest.send(self.g,self.c,self.s,p['id'])
  smtp.assert_not_called()
 def test_normal_urls_are_exact_not_anchor_labels(self):
  self.m.classify=Mock(return_value=OUTPUT.copy())
  self.g=FakeGmail([raw(body='Offer https://shop.example/path?x=1&y=2')])
  p=digest.prepare(self.g,self.c,self.m,self.s)
  t=(self.s.root/'digests'/(p['id']+'.txt')).read_text()
  h=(self.s.root/'digests'/(p['id']+'.html')).read_text()
  self.assertIn('https://shop.example/path?x=1&y=2',t)
  self.assertIn('https://shop.example/path?x=1&amp;y=2',h)
