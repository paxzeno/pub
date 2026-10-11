import base64,copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from test_pubmail import conf,raw,FakeGmail
from pubmail.io import Store,Error,ProcessingPending
from pubmail.reviewer import EscalatingModel,review_decisions
from pubmail import automation as a,digest,workflow

OUTPUT={'kind':'advertising','confidence':1,'title':'Offer','summary':'Summer collection.','topic':'Offer','deadline':None,'deadline_evidence':None}
class Automation(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.c=conf(self.tmp.name)
  self.c['automation'].update(enabled=True,senior_notify_argv=['notify-senior'],owner_notify_argv=['notify-owner'])
  self.c['agent_chain']['enabled']=True;self.c['agent_chain']['batching']['enforce_limits']=False
  self.c['agent_chain']['connections']['senior_openclaw'].update(argv=['reviewer'],processing='local')
  self.c['rollout']['digest_enabled']=True
  self.s=Store(self.c);self.m=EscalatingModel(self.c,self.s);a.setup(self.s)
  self.g=FakeGmail([raw()]);self.m.local.classify=Mock(return_value=OUTPUT.copy())
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def reply(self,*args,**kw):
  q=json.loads(kw['input']);return json.dumps({'version':1,'results':[{'id':i['id'],'status':'resolved','reason':'source verified','output':OUTPUT.copy()} for i in q['items']]})
 def test_pending_then_resume_only_active_job(self):
  with patch('pubmail.digest.prepare',side_effect=[ProcessingPending('more'),None]) as prep:
   self.assertEqual(a.run_weekly(self.g,self.c,self.m,self.s)['status'],'pending')
   self.assertEqual(a.run_weekly(self.g,self.c,self.m,self.s,start=False)['status'],'empty')
   self.assertEqual(a.run_weekly(self.g,self.c,self.m,self.s,start=False)['status'],'idle')
   self.assertEqual(prep.call_count,2)
 def test_resume_idle_and_paused_never_reads_mail(self):
  with patch('pubmail.digest.prepare') as prep:
   self.assertEqual(a.run_weekly(self.g,self.c,self.m,self.s,start=False)['status'],'idle')
   self.c['rollout']['digest_enabled']=False
   self.assertEqual(a.run_weekly(self.g,self.c,self.m,self.s)['status'],'paused');prep.assert_not_called()
 def test_real_failure_blocks_and_notifies_once(self):
  with patch('pubmail.digest.prepare',side_effect=Error('private detail')) as prep,patch('pubmail.automation.run',return_value='{}') as notify:
   a.run_weekly(self.g,self.c,self.m,self.s);a.run_weekly(self.g,self.c,self.m,self.s,start=False)
   self.assertEqual(prep.call_count,1);self.assertEqual(notify.call_count,1)
   self.assertNotIn('private detail',str(notify.call_args))
 def test_notification_routing_failure_and_dedup(self):
  with patch('pubmail.automation.run',side_effect=Error('down')) as n:
   a.notify(self.c,self.s,'weekly','needs_owner',['x']);a.notify(self.c,self.s,'weekly','needs_owner',['x'])
   self.assertEqual(n.call_args.args[0],['notify-owner']);self.assertEqual(n.call_count,1)
   self.assertEqual(self.s.db.execute('SELECT status FROM automation_events').fetchone()[0],'failed')
 def test_notification_crash_becomes_ambiguous(self):
  self.s.db.execute("INSERT INTO automation_events VALUES('x','sending','{}')");a.setup(self.s)
  self.assertEqual(self.s.db.execute('SELECT status FROM automation_events').fetchone()[0],'ambiguous')
 def test_ambiguous_send_never_retried(self):
  self.s.delivery('x','ambiguous',{'ids':[]})
  with patch('pubmail.digest.prepare') as prep,patch('pubmail.automation.run',return_value='{}'):
   self.assertEqual(a.run_weekly(self.g,self.c,self.m,self.s)['status'],'blocked');prep.assert_not_called()
   with self.assertRaises(Error):a.retry(self.c,self.s,'weekly')
 def test_send_requires_final_receipt_and_stale_mime_blocks(self):
  p=digest.prepare(self.g,self.c,self.m,self.s)
  with patch('pubmail.digest.run') as smtp:
   with self.assertRaisesRegex(Error,'Final review'):digest.send(self.g,self.c,self.s,p['id'])
   smtp.assert_not_called()
  with patch('pubmail.reviewer.run',side_effect=self.reply):p=a.final_review(self.c,self.m,self.s,p['id'])
  file=self.s.root/'digests'/(p['id']+'.eml');file.write_text(file.read_text()+'changed')
  with patch('pubmail.digest.run') as smtp:
   with self.assertRaises(Error):digest.send(self.g,self.c,self.s,p['id'])
   smtp.assert_not_called()
 def test_end_to_end_review_send_once_then_label_recovery(self):
  with patch('pubmail.reviewer.run',side_effect=self.reply) as senior,patch('pubmail.digest.run',return_value='{}') as smtp:
   result=a.run_weekly(self.g,self.c,self.m,self.s)
   self.assertIn('sent',result);self.assertEqual(smtp.call_count,1);self.assertEqual(senior.call_count,1)
   self.assertIn('L2',self.g.messages['a1']['labelIds']);self.assertIn('UNREAD',self.g.messages['a1']['labelIds'])
   a.run_weekly(self.g,self.c,self.m,self.s,start=False);self.assertEqual(smtp.call_count,1)
 def test_sent_recovery_has_no_smtp(self):
  p=digest.prepare(self.g,self.c,self.m,self.s);self.s.delivery(p['id'],'sent',p)
  a.save(self.s,'weekly','ready',{'policy':a.policy_hash(self.c),'digest':p['id']})
  with patch('pubmail.digest.run') as smtp:
   a.run_weekly(self.g,self.c,self.m,self.s,start=False);smtp.assert_not_called()
 def test_final_batches_resume_without_repeating(self):
  self.g=FakeGmail([raw('a1'),raw('a2')]);self.c['agent_chain']['batching']['max_messages']=1
  with patch('pubmail.reviewer.run',side_effect=self.reply) as senior,patch('pubmail.digest.run',return_value='{}') as smtp:
   self.assertEqual(a.run_weekly(self.g,self.c,self.m,self.s)['status'],'pending');smtp.assert_not_called()
   self.assertIn('sent',a.run_weekly(self.g,self.c,self.m,self.s,start=False));self.assertEqual(senior.call_count,2)
 def test_imported_correction_revalidated_and_resumes(self):
  p=digest.prepare(self.g,self.c,self.m,self.s)
  with patch('pubmail.reviewer.run',return_value='{}'),patch('pubmail.automation.run',return_value='{}'):
   with self.assertRaises(Error):a.final_review(self.c,self.m,self.s,p['id'])
  ident=self.m.reviewer.last_ids[0];a.save(self.s,'weekly','blocked',{'policy':a.policy_hash(self.c),'digest':p['id']})
  f=self.s.root/'repair.json';f.write_text(json.dumps({'output':OUTPUT,'reason':'manually checked'}));a.resolve(self.s,ident,f)
  with patch('pubmail.reviewer.run') as senior,patch('pubmail.digest.run',return_value='{}'):
   self.assertIn('sent',a.run_weekly(self.g,self.c,self.m,self.s,start=False));senior.assert_not_called()
 def test_invalid_import_never_sends(self):
  p=digest.prepare(self.g,self.c,self.m,self.s)
  with patch('pubmail.reviewer.run',return_value='{}'):
   with self.assertRaises(Error):a.final_review(self.c,self.m,self.s,p['id'])
  ident=self.m.reviewer.last_ids[0];f=self.s.root/'repair.json';f.write_text(json.dumps({'output':{'bad':1},'reason':'invalid'}));a.resolve(self.s,ident,f)
  with self.assertRaises(Error):a.final_review(self.c,self.m,self.s,p['id'])
  self.assertEqual(self.s.db.execute('SELECT status FROM senior_items WHERE id=?',(ident,)).fetchone()[0],'failed')
  f.write_text(json.dumps({'output':OUTPUT,'reason':'corrected'}));a.resolve(self.s,ident,f)
  a.final_review(self.c,self.m,self.s,p['id'])
 def test_image_failure_senior_reads_bound_file_then_cache(self):
  from pubmail.vision import enrich
  from pubmail.model import Model
  c=self.c;c['vision']['enabled']=True
  data='data:image/png;base64,'+base64.b64encode(b'fictional').decode()
  def reply(*args,**kw):
   q=json.loads(kw['input']);t=q['items'][0];self.assertEqual(Path(t['image_files'][0]).read_bytes(),b'fictional')
   return json.dumps({'version':1,'results':[{'id':t['id'],'status':'resolved','reason':'inspected','output':{'text':'10% OFF','titles':[],'readable':True}}]})
  with patch('pubmail.core.security',return_value=('verified','',[])),patch('pubmail.image_assets.assets',return_value={'x':data}),patch('pubmail.vision.model_image',side_effect=lambda b:b),patch.object(Model,'ask',side_effect=Error('invalid')),patch('pubmail.reviewer.run',side_effect=reply) as senior:
   m={'id':'a','body':'offer','original_html':'<img>'};self.assertIn('10% OFF',enrich(m,c,self.m.reviewer)['body']);enrich(m,c,self.m.reviewer);self.assertEqual(senior.call_count,1)
 def test_protected_override_requires_exact_review_whitelist_wins(self):
  from pubmail.core import normalize
  m=normalize(raw(body='Generic encomenda instructions for sale.'))
  d=workflow.decide(m,self.c,self.m,self.s)
  out=dict(OUTPUT,protected_disposition='promotional_only',protected_evidence='Generic encomenda instructions for sale.')
  def reply(*args,**kw):
   q=json.loads(kw['input']);return json.dumps({'version':1,'results':[{'id':t['id'],'status':'resolved','reason':'generic terms only','output':out} for t in q['items']]})
  with patch('pubmail.reviewer.run',side_effect=reply):review_decisions([d],self.c,self.m,self.s)
  self.assertEqual(d['action'],'archive');self.assertIn('protected_review',d)
  from pubmail.reviewer import protected_approval
  self.assertTrue(protected_approval(d,m,self.c,self.s));m['headers_hash']='changed';self.assertFalse(protected_approval(d,m,self.c,self.s))
 def test_config_requires_senior_and_notification_routes(self):
  a.validate_config(self.c);self.c['automation']['senior_notify_argv']=[]
  with self.assertRaises(Error):a.validate_config(self.c)
 def test_completed_receipt_does_not_wake_again(self):
  p=digest.prepare(self.g,self.c,self.m,self.s)
  with patch('pubmail.reviewer.run',side_effect=self.reply) as call:
   a.final_review(self.c,self.m,self.s,p['id']);a.final_review(self.c,self.m,self.s,p['id']);self.assertEqual(call.call_count,1)
 def test_changed_policy_blocks_existing_job(self):
  a.save(self.s,'weekly','pending',{'policy':'old'})
  with patch('pubmail.automation.run',return_value='{}'),patch('pubmail.digest.prepare') as prep:
   self.assertEqual(a.run_weekly(self.g,self.c,self.m,self.s,start=False)['status'],'blocked');prep.assert_not_called()
 def test_whitelist_not_overridden(self):
  from pubmail.core import normalize
  self.c['whitelist']={'addresses':['offers@shop.example'],'domains':[]}
  m=normalize(raw(body='Generic encomenda instructions for sale.'));d=workflow.decide(m,self.c,self.m,self.s)
  with patch('pubmail.reviewer.run') as senior:
   review_decisions([d],self.c,self.m,self.s);senior.assert_not_called()
  self.assertEqual(d['action'],'keep')
 def test_truncated_protected_source_never_overridden(self):
  from pubmail.core import normalize
  m=normalize(raw(body='Generic encomenda instructions for sale.'));m['truncated']=True;d=workflow.decide(m,self.c,self.m,self.s)
  def reply(*args,**kw):
   q=json.loads(kw['input']);return json.dumps({'version':1,'results':[{'id':t['id'],'status':'resolved','reason':'terms','output':dict(OUTPUT,protected_disposition='promotional_only',protected_evidence=m['body'])} for t in q['items']]})
  with patch('pubmail.reviewer.run',side_effect=reply):review_decisions([d],self.c,self.m,self.s)
  self.assertEqual(d['action'],'keep')
 def test_final_title_description_cannot_borrow_another_image(self):
  self.c['summary_profiles']=[{'sender':'offers@shop.example','format':'title_list','max_characters':1200}]
  from pubmail.core import normalize
  m=normalize(raw(body='Film One. Other card description.'));m.update(visual_titles=['Film One'],visual_evidence=[{'text':'Film One','titles':['Film One']}])
  with self.assertRaises(Error):a.validate_final(self.c,dict(OUTPUT,summary='• Film One — Other card description.'),m,self.m.local)
  self.assertIn('not verified',a.validate_final(self.c,dict(OUTPUT,summary='• Film One — Description not verified from source.'),m,self.m.local)['summary'])
