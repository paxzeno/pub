import copy,tempfile,unittest
from test_pubmail import conf,raw
from pubmail.core import normalize,preclassify,security

class MarketingRules(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.c=conf(self.tmp.name)
  self.c['advertising']=[{'sender':'offers@shop.example','subject_regex':'(?i)sale','promotional_phrases':['Repeat your last order confirmation example.']}]
 def tearDown(self):self.tmp.cleanup()
 def message(self,body):return normalize(raw(body=body))
 def test_reviewed_literal_only(self):
  m=self.message('Sale. Repeat your last order confirmation example.')
  self.assertEqual(preclassify(m,self.c)[0],'advertising')
  m=self.message('Sale. Repeat your last order confirmation example. Your payment failed.')
  self.assertEqual(preclassify(m,self.c)[0],'keep')
 def test_subject_sender_truncation_whitelist_still_protected(self):
  m=self.message('Repeat your last order confirmation example.')
  for key,value in [('subject','Sale invoice'),('original_sender','other@shop.example'),('truncated',True)]:
   changed=dict(m,**{key:value});self.assertEqual(preclassify(changed,self.c)[0],'keep')
  self.c['whitelist']={'addresses':['offers@shop.example']}
  self.assertEqual(preclassify(m,self.c)[0],'keep')
 def test_malformed_omission_never_yields_clickable_link(self):
  m=self.message('Sale');m['links']=['https://shop.example/path?campaign=bad value']
  self.assertEqual(security(m,self.c)[0],'uncertain')
  self.c.setdefault('link_policy',{})['omitted_malformed_hosts']={'offers@shop.example':['shop.example']}
  result=security(m,self.c);self.assertEqual(result[0],'verified');self.assertNotIn(m['links'][0],result[2])
  for url in ['https://attacker.example/path?x=a b','https://user@shop.example/path?x=a b','https://shop.example:444/path?x=a b','https://shop.example\\@evil.example/a b']:
   m['links']=[url];self.assertNotEqual(security(m,self.c)[0],'verified')
 def test_omission_does_not_cross_sender_or_auth(self):
  self.c.setdefault('link_policy',{})['omitted_malformed_hosts']={'other@shop.example':['shop.example']}
  m=self.message('Sale');m['links']=['https://shop.example/path?x=a b']
  self.assertEqual(security(m,self.c)[0],'uncertain')
  self.c['link_policy']['omitted_malformed_hosts']['offers@shop.example']=['shop.example'];m['auth']=[]
  self.assertNotEqual(security(m,self.c)[0],'verified')
