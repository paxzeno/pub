import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from test_pubmail import conf,raw,FakeGmail
from pubmail.io import Store,Error
from pubmail.reviewer import EscalatingModel
from pubmail import automation,digest,vision
from pubmail.resolution import validate_image_decision,resolve_image_locations
from pubmail.image_assets import source_config,eligible

GOOD={'kind':'advertising','confidence':1,'title':'Offer','summary':'Summer collection.','topic':'Offer','deadline':None,'deadline_evidence':None}
class SynchronousResolution(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.c=conf(self.tmp.name)
  self.c['automation'].update(enabled=True,senior_notify_argv=['fixture'],owner_notify_argv=['fixture'])
  self.c['agent_chain']['enabled']=True;self.c['agent_chain']['batching']['enforce_limits']=False
  self.c['agent_chain']['connections']['senior_openclaw']['processing']='local'
  self.s=Store(self.c);self.model=EscalatingModel(self.c,self.s);automation.setup(self.s)
  self.m={'id':'a1','sender':'offers@shop.example.com','headers_hash':'hash','body':'Offer',
          'original_html':'<img src="https://images.example.com/news/a.png">'}
  self.locations=[{'host':'images.example.com','path':'/news/a.png','query_keys':[],'reason':'unknown_host'}]
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def receipt(self,output):
  def respond(*args,**kw):
   req=json.loads(kw['input']);event=json.loads(Path(req['event_file']).read_text())
   return json.dumps({'event_id':req['event_id'],'status':'acknowledged','review_ids':event['review_ids'],
    'report':'Evidence inspected','resolutions':[{'id':i,'status':'resolved','output':output,'reason':'Verified exact evidence'} for i in event['review_ids']]})
  return respond
 def test_image_resolved_revalidated_and_extracted_in_same_call(self):
  self.c['vision']['enabled']=True;self.c['image_loading']['enabled']=True
  self.c['image_loading']['hosts']={}
  with patch('pubmail.core.security',return_value=('verified','',[])),patch('pubmail.automation.run',side_effect=self.receipt({'approved_locations':[0]})),patch('pubmail.image_assets.assets',return_value={'x':'data:image/png;base64,YWJj'}) as assets,patch('pubmail.vision.model_image',side_effect=lambda x:x),patch('pubmail.model.Model.ask',return_value={'text':'Offer','titles':[],'readable':True}):
   result=vision.enrich(self.m,self.c,self.model.reviewer)
   self.assertTrue(result['_vision_enriched']);self.assertEqual(result['visual_evidence'][0]['text'],'Offer')
   scoped=source_config(result,self.c)
   self.assertTrue(eligible('https://images.example.com/news/a.png',scoped['image_loading']))
   self.assertFalse(eligible('https://images.example.com/news/a.png.evil',scoped['image_loading']))
   self.assertFalse(eligible('https://images.example.com/news/b.png',scoped['image_loading']))
  self.assertEqual(self.c['image_loading']['hosts'],{})
  self.assertEqual(self.s.db.execute('SELECT status FROM senior_items').fetchone()[0],'resolved')
 def test_third_party_requires_independent_exact_reference(self):
  locations=[{**self.locations[0],'host':'cdn.other.example'}]
  with self.assertRaises(Error):validate_image_decision(self.m,locations,{'approved_locations':[0]})
  proposal={'approved_locations':[0],'evidence_urls':{'cdn.other.example':'https://www.example.com/news'}}
  with patch('pubmail.resolution.public_page_images',return_value=('https://cdn.other.example/news/a.png',)):
   self.assertIn('cdn.other.example',validate_image_decision(self.m,locations,proposal))
  with patch('pubmail.resolution.public_page_images',return_value=('https://cdn.other.example/other.png',)):
   with self.assertRaises(Error):validate_image_decision(self.m,locations,proposal)
 def test_query_or_wrong_source_proposal_rejected(self):
  with self.assertRaises(Error):validate_image_decision(self.m,[{**self.locations[0],'query_keys':['recipient']}],{'approved_locations':[0]})
  other={**self.m,'sender':'offers@unrelated.example'}
  with self.assertRaises(Error):validate_image_decision(other,self.locations,{'approved_locations':[0]})
 def test_ack_without_decision_does_not_resolve_or_loop(self):
  with patch('pubmail.core.security',return_value=('verified','',[])),patch('pubmail.automation.run',return_value='{}') as run:
   for _ in range(2):
    with self.assertRaises(Error):resolve_image_locations(self.m,self.c,self.model.reviewer,self.locations)
   self.assertEqual(run.call_count,1)
  self.assertNotEqual(self.s.db.execute('SELECT status FROM senior_items').fetchone()[0],'resolved')
 def test_final_review_repair_included_without_another_run(self):
  g=FakeGmail([raw()]);self.model.classify=Mock(return_value=GOOD.copy())
  preview=digest.prepare(g,self.c,self.model,self.s)
  def invalid(*args,**kw):
   request=json.loads(kw['input'])
   return json.dumps({'version':1,'results':[{'id':i['id'],'status':'resolved','reason':'initial','output':{**GOOD,'kind':'keep'}} for i in request['items']]})
  with patch('pubmail.reviewer.run',side_effect=invalid),patch('pubmail.automation.run',side_effect=self.receipt(GOOD)):
   reviewed=automation.final_review(self.c,self.model,self.s,preview['id'])
  self.assertEqual(reviewed['ids'],['a1']);self.assertFalse(reviewed['skipped'])
  self.assertEqual(self.s.db.execute('SELECT status FROM senior_items').fetchone()[0],'resolved')
 def test_evidence_fetch_is_bounded_and_does_not_follow_redirects(self):
  from pubmail.resolution import public_page_images
  public_page_images.cache_clear()
  response=Mock();response.status=302;response.getheader.return_value='text/html'
  conn=Mock();conn.getresponse.return_value=response
  with patch('pubmail.image_assets.PinnedHTTPS',return_value=conn):
   with self.assertRaises(Error):public_page_images('https://www.example.com/evidence')
  response.read.assert_not_called();conn.close.assert_called_once()
  args,kw=conn.request.call_args
  self.assertEqual(args,('GET','/evidence'));self.assertEqual(kw['headers'],{'Accept':'text/html'})
 def test_evidence_fetch_rejects_oversized_body(self):
  from pubmail.resolution import public_page_images
  public_page_images.cache_clear()
  response=Mock();response.status=200;response.getheader.return_value='text/html';response.read.return_value=b'x'*524289
  conn=Mock();conn.getresponse.return_value=response
  with patch('pubmail.image_assets.PinnedHTTPS',return_value=conn):
   with self.assertRaises(Error):public_page_images('https://www.example.com/evidence')
  response.read.assert_called_once_with(524289);conn.close.assert_called_once()
 def test_private_or_tokenized_evidence_not_requested(self):
  locations=[{**self.locations[0],'host':'cdn.other.example'}]
  for url in ['https://127.0.0.1/a','https://www.example.com/a?token=x','https://www.example.com/unsubscribe','https://www.example.com.evil.example/a']:
   with patch('pubmail.resolution.public_page_images') as fetch:
    with self.assertRaises(Error):validate_image_decision(self.m,locations,{'approved_locations':[0],'evidence_urls':{'cdn.other.example':url}})
    fetch.assert_not_called()
