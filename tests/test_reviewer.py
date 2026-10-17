import copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import yaml
from pubmail.io import Store, Error
from pubmail.reviewer import ReviewQueue, validate_config, EscalatingModel, review_decisions

class ReviewerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.c=yaml.safe_load(Path('config.example.yaml').read_text())
        self.c['state_dir']=self.tmp.name
        self.c['agent_chain']['enabled']=True
        conn=self.c['agent_chain']['connections']['senior_openclaw']
        conn.update(processing='local',argv=['example-reviewer'])
        self.store=Store(self.c);self.q=ReviewQueue(self.c,self.store)
        self.task={'reason':'model_failure','prompt':'test','data':{'body':'untrusted'}}
    def tearDown(self): self.store.close();self.tmp.cleanup()
    def response(self,*args,**kwargs):
        req=json.loads(kwargs['input'])
        return json.dumps({'version':1,'results':[{'id':i['id'],'status':'resolved','output':{'ok':True},'reason':'reviewed'} for i in req['items']]})
    def test_validation_failure_isolated_and_recorded(self):
        def reject(o):raise Error('Final review omitted source title')
        with patch('pubmail.reviewer.run',side_effect=self.response):
            out=self.q.exchange([self.task,dict(self.task,reason='other')],[reject,lambda o:None])
        self.assertEqual(out,{1:{'ok':True}})
        rows=self.store.db.execute("SELECT status,result FROM senior_items").fetchall()
        self.assertEqual(sorted(s for s,r in rows),['failed','resolved'])
        error=json.loads(next(r for s,r in rows if s=='failed'))['error']
        self.assertEqual(error['stage'],'review_validation')
        self.assertEqual(error['chain'][0]['message'],'Final review omitted source title')
    def test_transport_failure_diagnostic_private_and_not_retried(self):
        with patch('pubmail.reviewer.run',side_effect=Error('SECRET')) as call:
            self.q.exchange([self.task],[lambda o:None])
            self.q.exchange([self.task],[lambda o:None])
        self.assertEqual(call.call_count,1)
        result=self.store.db.execute('SELECT result FROM senior_items').fetchone()[0]
        self.assertNotIn('SECRET',result)
        self.assertEqual(json.loads(result)['error']['stage'],'review_transport_or_contract')
    def test_batch_and_dedup(self):
        with patch('pubmail.reviewer.run',side_effect=self.response) as call:
            tasks=[self.task,dict(self.task,reason='low_confidence')]
            self.assertEqual(len(self.q.exchange(tasks,[lambda o:None]*2)),2)
            self.assertEqual(len(self.q.exchange(tasks,[lambda o:None]*2)),2)
            self.assertEqual(call.call_count,1)
    def test_invalid_output_never_resolves_or_retries(self):
        with patch('pubmail.reviewer.run',return_value='{}') as call:
            self.assertEqual(self.q.exchange([self.task],[lambda o:None]),{})
            self.assertEqual(self.q.exchange([self.task],[lambda o:None]),{})
            self.assertEqual(call.call_count,1)
            self.assertEqual(self.q.status(),{'failed':1})
    def test_timeout_fail_closed(self):
        with patch('pubmail.reviewer.run',side_effect=Error('timeout')):
            self.assertEqual(self.q.exchange([self.task],[lambda o:None]),{})
    def test_validation_failure_rejects(self):
        def reject(o): raise Error('bad schema')
        with patch('pubmail.reviewer.run',side_effect=self.response):
            self.assertEqual(self.q.exchange([self.task],[reject]),{})
    def test_empty_no_wake_and_throttle(self):
        with patch('pubmail.reviewer.run',side_effect=self.response) as call:
            self.q.exchange([],[]);self.assertEqual(call.call_count,0)
            self.q.exchange([self.task],[lambda o:None])
            self.q.exchange([dict(self.task,reason='new')],[lambda o:None])
            self.assertEqual(call.call_count,1)
            self.assertEqual(self.q.status(),{'pending':1,'resolved':1})
    def test_no_shell_and_data_on_stdin(self):
        with patch('pubmail.reviewer.run',side_effect=self.response) as call:
            self.q.exchange([self.task],[lambda o:None])
            self.assertEqual(call.call_args.args[0],['example-reviewer'])
            self.assertNotIn('untrusted',str(call.call_args.args))
    def test_remote_opt_in(self):
        self.c['agent_chain']['connections']['senior_openclaw']['processing']='remote'
        with self.assertRaises(Error):validate_config(self.c)
        self.c['agent_chain']['review_packet']['allow_remote_processing']=True
        validate_config(self.c)
    def test_model_failure_round_trip(self):
        from pubmail.model import Model
        model=EscalatingModel(self.c,self.store)
        result={'kind':'keep','confidence':1,'title':'Account notice','summary':'Account changed.','topic':'Account','deadline':None,'deadline_evidence':None}
        def reply(*a,**kw):
            req=json.loads(kw['input'])
            return json.dumps({'version':1,'results':[{'id':i['id'],'status':'resolved','output':result,'reason':'transactional'} for i in req['items']]})
        m={'id':'test','subject':'Account notice','sender':'service@example.com','timestamp':1,'body':'Account changed.','headers_hash':'abc'}
        with patch.object(model.local,'classify',side_effect=Error('offline')),patch('pubmail.reviewer.run',side_effect=reply):
            self.assertEqual(model.classify(m)['kind'],'keep')
    def test_inflight_recovery_does_not_repeat(self):
        self.store.db.execute("INSERT INTO senior_items VALUES('x','p','{}','running',NULL,1)")
        self.store.db.commit()
        q=ReviewQueue(self.c,self.store)
        self.assertEqual(q.status(),{'ambiguous':1})
    def test_wrong_ids_rejected(self):
        with patch('pubmail.reviewer.run',return_value=json.dumps({'version':1,'results':[{'id':'invented','status':'resolved','output':{},'reason':'x'}]})):
            self.assertEqual(self.q.exchange([self.task],[lambda o:None]),{})
    def test_owner_queue_never_resolves(self):
        def reply(*a,**kw):
            req=json.loads(kw['input'])
            return json.dumps({'version':1,'results':[{'id':i['id'],'status':'needs_owner','reason':'Preference needed'} for i in req['items']]})
        with patch('pubmail.reviewer.run',side_effect=reply):
            self.assertEqual(self.q.exchange([self.task],[lambda o:None]),{})
            self.assertEqual(self.q.status(),{'needs_owner':1})
    def test_oversized_trimmed_and_sent(self):
        with patch('pubmail.reviewer.run', side_effect=self.response) as call:
            task=dict(self.task,data={'body':'x'*7000})
            self.assertEqual(self.q.exchange([task],[lambda o:None]),{0:{'ok':True}})
            data=json.loads(call.call_args.kwargs['input'])['items'][0]['data']
            self.assertEqual(len(data['body']),6000)
            self.assertTrue(data['text_trimmed'])
    def test_batch_respects_security_and_protected_content(self):
        model=EscalatingModel(self.c,self.store)
        m={'id':'test','subject':'Receipt','sender':'billing@example.com','timestamp':1,'body':'Receipt received.','headers_hash':'abc'}
        d={'id':'test','message':m,'action':'keep','reason':'Model failed; retained','retry':True,'security':'unverified','security_reason':'unverified'}
        out={'kind':'advertising','confidence':1,'title':'Offer','summary':'Receipt received.','topic':'Receipt','deadline':None,'deadline_evidence':None}
        def reply(*a,**kw):
            req=json.loads(kw['input'])
            return json.dumps({'version':1,'results':[{'id':i['id'],'status':'resolved','output':out,'reason':'x'} for i in req['items']]})
        with patch('pubmail.reviewer.run',side_effect=reply),patch('pubmail.core.security',return_value=('verified','ok',[])),patch('pubmail.core.preclassify',return_value=('keep','protected')):
            review_decisions([d],self.c,model,self.store)
        self.assertEqual(d['action'],'keep')
    def test_cooldown_bounds(self):
        for value in (0, 60, 720):
            self.c['agent_chain']['batching']['min_interval_minutes']=value
            validate_config(self.c)
        for value in (-1, 721, 1440, True, 0.5, '60'):
            self.c['agent_chain']['batching']['min_interval_minutes']=value
            with self.assertRaises(Error): validate_config(self.c)
    def test_zero_cooldown_dispatches_distinct_batches(self):
        self.c['agent_chain']['batching']['min_interval_minutes']=0
        with patch('pubmail.reviewer.run',side_effect=self.response) as call:
            self.q.exchange([self.task],[lambda o:None])
            self.q.exchange([dict(self.task,reason='different')],[lambda o:None])
            self.assertEqual(call.call_count,2)
    def test_zero_cooldown_keeps_daily_budget(self):
        self.c['agent_chain']['batching'].update(min_interval_minutes=0,max_batches_per_day=1)
        with patch('pubmail.reviewer.run',side_effect=self.response) as call:
            self.q.exchange([self.task],[lambda o:None])
            self.q.exchange([dict(self.task,reason='different')],[lambda o:None])
            self.assertEqual(call.call_count,1)

    def test_calibration_bypasses_quotas_preserves_dedup(self):
        self.c['agent_chain']['batching'].update(min_interval_minutes=720,max_batches_per_day=1)
        with patch('pubmail.reviewer.run',side_effect=self.response) as call:
            self.q.exchange([self.task],[lambda o:None])
            other=dict(self.task,reason='other')
            self.q.exchange([other],[lambda o:None])
            self.assertEqual(call.call_count,1)
            self.c['agent_chain']['batching']['enforce_limits']=False
            self.q.exchange([self.task,other],[lambda o:None]*2)
            self.assertEqual(call.call_count,2)
            self.c['agent_chain']['batching']['enforce_limits']=True
            self.q.exchange([dict(self.task,reason='third')],[lambda o:None])
            self.assertEqual(call.call_count,2)

    def test_calibration_toggle_does_not_retry_failed_attempt(self):
        with patch('pubmail.reviewer.run',return_value='{}') as call:
            self.q.exchange([self.task],[lambda o:None])
            self.c['agent_chain']['batching']['enforce_limits']=False
            self.q.exchange([self.task],[lambda o:None])
            self.assertEqual(call.call_count,1)

    def test_enforcement_switch_boolean_only(self):
        self.c['agent_chain']['batching']['enforce_limits']='false'
        with self.assertRaises(Error): validate_config(self.c)
