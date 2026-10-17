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
 def ack(self,*args,**kw):
  d=json.loads(kw['input']);event=json.loads(Path(d['event_file']).read_text())
  return json.dumps({'event_id':d['event_id'],'status':'acknowledged','review_ids':event['review_ids'],'report':'Inspected fixture; remains pending.'})
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
  with patch('pubmail.digest.prepare',side_effect=Error('private detail')) as prep,patch('pubmail.automation.run',side_effect=self.ack) as notify:
   a.run_weekly(self.g,self.c,self.m,self.s);a.run_weekly(self.g,self.c,self.m,self.s,start=False)
   self.assertEqual(prep.call_count,1);self.assertEqual(notify.call_count,1)
   self.assertNotIn('private detail',str(notify.call_args))
 def test_queued_without_acknowledgement_is_failure(self):
  with patch('pubmail.automation.run',return_value='{"queued":"yes"}'):
   a.notify(self.c,self.s,'weekly','senior_attention',['x'])
  status,body=self.s.db.execute('SELECT status,body FROM automation_events').fetchone()
  self.assertEqual(status,'failed');self.assertNotIn('handoff_receipt',json.loads(body))
 def test_acknowledgement_keeps_review_pending(self):
  with patch('pubmail.automation.run',side_effect=self.ack) as call:
   a.notify(self.c,self.s,'weekly','senior_attention',['x'])
   a.notify(self.c,self.s,'weekly','senior_attention',['x'])
  status,body=self.s.db.execute('SELECT status,body FROM automation_events').fetchone()
  self.assertEqual(status,'acknowledged');self.assertEqual(call.call_count,1)
  self.assertEqual(json.loads(body)['handoff_receipt']['review_ids'],['x'])
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
  with patch('pubmail.digest.prepare') as prep,patch('pubmail.automation.run',side_effect=self.ack):
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
 def test_imported_correction_revalidated_in_next_issue(self):
  p=digest.prepare(self.g,self.c,self.m,self.s)
  with patch('pubmail.reviewer.run',return_value='{}'):
   held=a.final_review(self.c,self.m,self.s,p['id'])
  self.assertEqual(held['ids'],[])
  ident=self.m.reviewer.last_ids[0]
  f=self.s.root/'repair.json';f.write_text(json.dumps({'output':OUTPUT,'reason':'manually checked'}));a.resolve(self.s,ident,f)
  p=digest.prepare(self.g,self.c,self.m,self.s)
  with patch('pubmail.reviewer.run') as senior:
   reviewed=a.final_review(self.c,self.m,self.s,p['id']);senior.assert_not_called()
  self.assertEqual(reviewed['ids'],['a1'])
 def test_invalid_import_never_includes_source(self):
  p=digest.prepare(self.g,self.c,self.m,self.s)
  with patch('pubmail.reviewer.run',return_value='{}'):
   a.final_review(self.c,self.m,self.s,p['id'])
  ident=self.m.reviewer.last_ids[0];f=self.s.root/'repair.json';f.write_text(json.dumps({'output':{'bad':1},'reason':'invalid'}));a.resolve(self.s,ident,f)
  p=digest.prepare(self.g,self.c,self.m,self.s)
  held=a.final_review(self.c,self.m,self.s,p['id'])
  self.assertEqual(held['ids'],[]);self.assertEqual(self.g.calls,[])
  self.assertEqual(self.s.db.execute('SELECT status FROM senior_items WHERE id=?',(ident,)).fetchone()[0],'failed')
  f.write_text(json.dumps({'output':OUTPUT,'reason':'corrected'}));a.resolve(self.s,ident,f)
  p=digest.prepare(self.g,self.c,self.m,self.s)
  self.assertEqual(a.final_review(self.c,self.m,self.s,p['id'])['ids'],['a1'])
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
  with patch('pubmail.automation.run',side_effect=self.ack),patch('pubmail.digest.prepare') as prep:
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
 def test_failure_chain_persisted_and_returned_on_resume(self):
  def fail(*args):
   try:raise Error('No approved artwork available for visual extraction')
   except Error as cause:
    error=Error('Digest summarization failed; nothing sent or marked');error.source_id='abcdef1234'
    raise error from cause
  with patch('pubmail.digest.prepare',side_effect=fail) as prep,patch('pubmail.automation.run',side_effect=self.ack) as notify,self.assertLogs('pubmail.automation',level='ERROR') as logs:
   result=a.run_weekly(self.g,self.c,self.m,self.s)
   resumed=a.run_weekly(self.g,self.c,self.m,self.s,start=False)
  self.assertEqual(result,resumed);self.assertEqual(prep.call_count,1);self.assertEqual(notify.call_count,1)
  error=result['error'];self.assertEqual(error['stage'],'prepare');self.assertEqual(error['source_id'],'abcdef1234')
  self.assertEqual(error['chain'][1]['message'],'No approved artwork available for visual extraction')
  self.assertTrue(error['chain'][1]['frames']);self.assertIn('No approved artwork',str(logs.output))
  self.assertEqual(a.job_errors(self.s)['weekly'],error)
  event=json.loads(self.s.db.execute("SELECT body FROM automation_events WHERE status='acknowledged'").fetchone()[0])
  self.assertEqual(event['error'],error)
 def test_unexpected_exception_blocks_without_leaking_payload(self):
  secret='Bearer secret-token https://private.example/path?token=secret mail body'
  with patch('pubmail.digest.prepare',side_effect=ValueError(secret)),patch('pubmail.automation.run',side_effect=self.ack),self.assertLogs('pubmail.automation',level='ERROR') as logs:
   result=a.run_weekly(self.g,self.c,self.m,self.s)
  self.assertEqual(result['status'],'blocked');self.assertEqual(result['error']['chain'][0]['type'],'ValueError')
  self.assertNotIn(secret,json.dumps(result)+str(logs.output)+str(list(self.s.db.execute('SELECT body FROM automation_events'))))
 def test_final_review_and_delivery_failure_stages(self):
  for stage in ('final_review','delivery'):
   self.s.db.execute('DELETE FROM automation_jobs');self.s.db.commit()
   with patch('pubmail.digest.prepare',return_value={'id':'fixture'}),patch('pubmail.automation.final_review',side_effect=Error('Final content review incomplete') if stage=='final_review' else None),patch('pubmail.digest.send',side_effect=Error('Final review missing or stale; sending blocked')) as send,patch('pubmail.automation.run',side_effect=self.ack),self.assertLogs('pubmail.automation',level='ERROR'):
    result=a.run_weekly(self.g,self.c,self.m,self.s)
   self.assertEqual(result['error']['stage'],stage)
   if stage=='final_review':send.assert_not_called()
 def test_legacy_blocked_job_is_explicit_and_not_retried(self):
  a.save(self.s,'weekly','blocked',{})
  with patch('pubmail.digest.prepare') as prep:
   result=a.run_weekly(self.g,self.c,self.m,self.s,start=False)
  self.assertIn('Legacy',result['error']['message']);prep.assert_not_called()
 def test_notification_error_is_private_persisted_and_not_resent(self):
  with patch('pubmail.automation.run',side_effect=Error('credential=topsecret')) as notify,self.assertLogs('pubmail.automation',level='ERROR') as logs:
   a.notify(self.c,self.s,'weekly','needs_owner',['x']);a.notify(self.c,self.s,'weekly','needs_owner',['x'])
  status,body=self.s.db.execute('SELECT status,body FROM automation_events').fetchone()
  self.assertEqual(status,'failed');self.assertEqual(json.loads(body)['notification_error']['stage'],'notification')
  self.assertNotIn('topsecret',body+str(logs.output));self.assertEqual(notify.call_count,1)
 def test_failed_source_is_reported_but_never_labelled(self):
  self.g=FakeGmail([raw(id='a1'),raw(id='b2',subject='Failed source')])
  self.m.classify=Mock(side_effect=[OUTPUT.copy(),Error('No approved artwork available for visual extraction')])
  p=digest.prepare(self.g,self.c,self.m,self.s)
  self.assertEqual(p['ids'],['a1']);self.assertEqual(p['skipped'][0]['id'],'b2')
  self.assertEqual(self.g.calls,[])
  with patch('pubmail.reviewer.run',side_effect=self.reply):
   reviewed=a.final_review(self.c,self.m,self.s,p['id'])
  for ext in ('html','txt','eml'):
   text=(self.s.root/'digests'/(p['id']+'.'+ext)).read_text()
   self.assertIn('processing failed',text.lower());self.assertIn('Failed source',text)
  digest.finish_labels(self.g,self.c,self.s,p['id'],reviewed)
  self.assertEqual([x[0] for x in self.g.calls],['a1'])
  self.assertEqual(self.g.messages['b2']['labelIds'],['INBOX','UNREAD'])
  self.m.classify=Mock(return_value=OUTPUT.copy())
  next_issue=digest.prepare(self.g,self.c,self.m,self.s)
  self.assertEqual(next_issue['ids'],['b2'])
 def test_all_sources_failed_builds_notice_only_digest(self):
  self.m.classify=Mock(side_effect=Error('No approved artwork available for visual extraction'))
  p=digest.prepare(self.g,self.c,self.m,self.s)
  self.assertEqual(p['ids'],[]);self.assertEqual(len(p['skipped']),1)
  with patch('pubmail.reviewer.run',side_effect=self.reply):
   a.final_review(self.c,self.m,self.s,p['id'])
  digest.finish_labels(self.g,self.c,self.s,p['id'],p)
  self.assertEqual(self.g.calls,[])
 def test_skipped_identity_only_for_verified_sources(self):
  source={'id':'abc123','sender':'shop@example.com','original_sender':'shop@example.com',
          'thread_id':'thread123','rfc_message_id':'message@example.com'}
  verified={'id':source['id'],'subject':'Offer','reason':'Review incomplete',
            **digest.skipped_identity(source,True)}
  h,t,_=digest.render(self.c,[],[],[],skipped=[verified])
  self.assertIn('From: shop@example.com',h);self.assertIn('From: shop@example.com',t)
  self.assertIn('Open original email',h);self.assertIn('rfc822msgid%3Amessage%40example.com',h)
  self.assertEqual(digest.skipped_identity(source,False),{})
  for entry in [dict(verified,security='review'),{'id':'abc123','subject':'Legacy','reason':'Incomplete'}]:
   h,t,_=digest.render(self.c,[],[],[],skipped=[entry])
   self.assertNotIn('Open original email',h+t);self.assertNotIn('shop@example.com',h+t)
  h,_,_=digest.render(self.c,[],[],[],skipped=[dict(verified,sender='<script>bad</script>')])
  self.assertNotIn('<script>',h);self.assertIn('&lt;script&gt;',h)
 def test_skipped_notice_does_not_include_private_exception_text(self):
  self.m.classify=Mock(side_effect=Error('credential=secret'))
  p=digest.prepare(self.g,self.c,self.m,self.s)
  self.assertNotIn('credential=secret',json.dumps(p))
 def test_failed_final_review_excludes_only_rejected_source(self):
  self.g=FakeGmail([raw(id='a1'),raw(id='b2',subject='Review failed')])
  self.m.classify=Mock(return_value=OUTPUT.copy())
  p=digest.prepare(self.g,self.c,self.m,self.s)
  def partial(*args,**kw):
   q=json.loads(kw['input'])
   return json.dumps({'version':1,'results':[{'id':t['id'],'status':'needs_owner','reason':'cannot verify'} if n==1 else {'id':t['id'],'status':'resolved','reason':'verified','output':OUTPUT.copy()} for n,t in enumerate(q['items'])]})
  with patch('pubmail.reviewer.run',side_effect=partial):
   reviewed=a.final_review(self.c,self.m,self.s,p['id'])
  self.assertEqual(reviewed['ids'],['a1']);self.assertEqual(reviewed['skipped'][0]['id'],'b2')
  self.assertEqual(set(reviewed['final_review']['sources']),{'a1'})
  digest.finish_labels(self.g,self.c,self.s,p['id'],reviewed)
  self.assertEqual([x[0] for x in self.g.calls],['a1'])
 def test_failed_source_fetch_does_not_block_other_source(self):
  self.g=FakeGmail([raw(id='a1'),raw(id='b2')]);original=self.g.raw
  self.g.raw=lambda ident: (_ for _ in ()).throw(Error('unavailable')) if ident=='b2' else original(ident)
  self.m.classify=Mock(return_value=OUTPUT.copy())
  p=digest.prepare(self.g,self.c,self.m,self.s)
  self.assertEqual(p['ids'],['a1']);self.assertEqual(p['skipped'][0]['id'],'b2')
 def test_image_location_research_is_durable_and_deduplicated(self):
  from pubmail.reviewer import queue_image_location_review
  m={'original_sender':'offers@shop.example'};locations=[{'host':'cdn.example.com','path':'/brand/a.png','query_keys':[],'reason':'unknown_host'}]
  with patch('pubmail.automation.run',side_effect=self.ack) as notify:
   ident=queue_image_location_review(m,self.c,self.s,locations)
   self.assertEqual(ident,queue_image_location_review(m,self.c,self.s,locations))
   self.c['automation']['notify_timeout_seconds']=179
   self.assertEqual(ident,queue_image_location_review(m,self.c,self.s,locations))
  self.assertEqual(notify.call_count,1)
  state,attempts,task=self.s.db.execute('SELECT status,attempts,task FROM senior_items WHERE id=?',(ident,)).fetchone()
  self.assertEqual((state,attempts),('pending',0));self.assertEqual(json.loads(task)['reason'],'image_location_investigation')
