import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from test_pubmail import conf
from pubmail.io import Store, LockBusy, Gmail, GmailAuthRequired, Error, run
from pubmail import scheduling as s, automation as a
from pubmail.oauth import recovery_url

URL='https://accounts.google.com/o/oauth2/auth?state=test&client_id=example&redirect_uri=http%3A%2F%2Flocalhost'

class Recovery(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.c=conf(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_friday_hold_dst_and_boundaries(self):
  for month,day,utc_start in [(10,23,9),(10,30,10)]:
   for hour in range(24):
    self.assertEqual(s.hourly_held(self.c,datetime(2026,month,day,hour,tzinfo=timezone.utc)),utc_start<=hour<=utc_start+2)
  self.assertFalse(s.hourly_held(self.c,datetime(2026,10,29,11,tzinfo=timezone.utc)))
 def test_request_survives_contention_and_completed_job(self):
  store=Store(self.c)
  try:
   a.setup(store);a.save(store,'weekly','complete',{'digest':'old'})
   s.queue_weekly(self.c)
   with self.assertRaises(LockBusy):Store(self.c)
   self.assertEqual(len(list(Path(self.tmp.name).glob('weekly-request-*'))),1)
   s.accept_weekly(self.c,store)
   state,body=store.db.execute('select state,body from automation_jobs').fetchone()
   self.assertEqual(state,'pending');self.assertNotIn('digest',json.loads(body))
   a.save(store,'weekly','complete',json.loads(body))
   s.queue_weekly(self.c);s.accept_weekly(self.c,store)
   self.assertEqual(store.db.execute('select state from automation_jobs').fetchone()[0],'complete')
  finally:store.close()
 def test_existing_blocked_job_not_overwritten(self):
  store=Store(self.c)
  try:
   a.setup(store);a.save(store,'weekly','blocked',{'digest':'ambiguous'})
   s.queue_weekly(self.c);s.accept_weekly(self.c,store)
   self.assertEqual(store.db.execute('select state from automation_jobs').fetchone()[0],'blocked')
   self.assertTrue(list(Path(self.tmp.name).glob('weekly-request-*')))
  finally:store.close()
 def test_auth_error_is_structured_not_arbitrary_stderr(self):
  with patch('pubmail.io.subprocess.run',return_value=subprocess.CompletedProcess([],4,'{"error":{"class":"auth_required"}}','private')):
   with self.assertRaises(GmailAuthRequired):run(['gog'])
  with patch('pubmail.io.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','invalid_grant private')):
   with self.assertRaises(Error) as cm:run(['gog'])
   self.assertNotIsInstance(cm.exception,GmailAuthRequired);self.assertNotIn('private',str(cm.exception))
 def test_recovery_url_cached_private_and_scoped(self):
  with patch('pubmail.oauth.run',return_value=json.dumps({'auth_url':URL})) as cmd:
   self.assertEqual(recovery_url(self.c,{}),URL);self.assertEqual(recovery_url(self.c,{}),URL)
   self.assertEqual(cmd.call_count,1)
   self.assertIn('https://www.googleapis.com/auth/gmail.modify',cmd.call_args.args[0])
   self.assertNotIn('full',cmd.call_args.args[0])
  self.assertEqual((Path(self.tmp.name)/'oauth-recovery.json').stat().st_mode & 0o777,0o600)
 def test_untrusted_auth_url_rejected(self):
  with patch('pubmail.oauth.run',return_value='{"auth_url":"https://evil.example/auth"}'):
   with self.assertRaises(Error):recovery_url(self.c,{})
 def test_gmail_emits_recovery_but_never_retries_request(self):
  c=dict(self.c);c.pop('keyring_password_command',None)
  with patch('pubmail.io.run',side_effect=GmailAuthRequired('auth')) as cmd,patch('pubmail.oauth.recovery_url',return_value=URL),patch('sys.stderr') as err:
   with self.assertRaises(GmailAuthRequired):Gmail(c).labels()
   self.assertEqual(cmd.call_count,1);self.assertIn(URL,str(err.write.call_args_list))
