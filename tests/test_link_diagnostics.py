import unittest
from unittest.mock import patch
from test_pubmail import raw, conf
from pubmail.core import normalize, security
from pubmail.digest import render

class LinkDiagnostics(unittest.TestCase):
    def test_all_hosts_not_tracking_paths(self):
        m=normalize(raw(body='https://one.example/a?secret=123 https://two.example/b'))
        sec,reason,_=security(m,conf('/tmp'))
        self.assertEqual(sec,'uncertain')
        self.assertIn('one.example',reason); self.assertIn('two.example',reason)
        self.assertNotIn('secret',reason)
    @patch('pubmail.thumbnail.screenshot',return_value=b'png')
    def test_exact_search_link_and_inline_bullet(self,_):
        r=raw();r['payload']['headers'].append({'name':'Message-ID','value':'<message+1@example.com>'})
        m=normalize(r);c=conf('/tmp')
        d={'id':m['id'],'message':m,'title':'Title','summary':'• Title — Detail','deadline':None}
        html,txt,_=render(c,[d],[[m['id']]],[])
        self.assertIn('#search/rfc822msgid%3Amessage%2B1%40example.com',html)
        self.assertIn('<strong>&#8226;&nbsp;Title</strong>',html)
        self.assertNotIn('#all/a1',html)
