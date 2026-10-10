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
    def test_tracking_excluded_not_allowed(self):
        m=normalize(raw(body='https://ctrk.klclick.com/path?recipient=secret'))
        c=conf('/tmp');c['ignored_tracking_domains']=['ctrk.klclick.com']
        sec,reason,urls=security(m,c)
        self.assertEqual(sec,'verified')
        self.assertFalse(any('klclick' in u for u in urls))
        m['links'].append('https://ctrk.klclick.com.evil.example/path')
        self.assertEqual(security(m,c)[0],'uncertain')
    def test_ignored_host_does_not_skip_sender_auth(self):
        m=normalize(raw(body='https://ctrk.klclick.com/path'))
        m['auth']=[]
        c=conf('/tmp');c['ignored_tracking_domains']=['ctrk.klclick.com']
        self.assertEqual(security(m,c)[0],'uncertain')
    def test_documented_tracking_suffix_boundary(self):
        c=conf('/tmp');c['ignored_tracking_domain_suffixes']=['ct.sendgrid.net','awstrack.me']
        for url in ('https://u123.ct.sendgrid.net/ls/click?secret=1','https://r.us-east-1.awstrack.me/x'):
            m=normalize(raw(body=url));sec,_,safe=security(m,c)
            self.assertEqual(sec,'verified');self.assertNotIn(url,safe)
        for url in ('https://ct.sendgrid.net.evil.example/x','https://evilct.sendgrid.net/x','https://ct.sendgrid.net/x','https://user@u123.ct.sendgrid.net/x','https://u123.ct.sendgrid.net:444/x'):
            self.assertEqual(security(normalize(raw(body=url)),c)[0],'uncertain')

    def test_contact_and_matching_bare_links_are_omitted(self):
        m=normalize(raw());m['links']=['mailto:help@shop.example','www.shop.example','shop.example/support','https://shop.example/sale']
        self.assertEqual(security(m,conf('/tmp'))[0],'verified')
        self.assertEqual(security(m,conf('/tmp'))[2],['https://shop.example/sale','https://shop.example/unsubscribe'])
        m['auth']=[]
        self.assertEqual(security(m,conf('/tmp'))[0],'uncertain')
    def test_bare_lookalikes_and_ambiguous_forms_still_flag(self):
        for link in ['www.shop.example.evil.example','shop-example.com','user@shop.example','shop.example:443','//shop.example','shop.example\\@evil.example','http://shop.example']:
            m=normalize(raw());m['links']=[link]
            self.assertEqual(security(m,conf('/tmp'))[0],'uncertain',link)

    def test_explicit_single_offer_cutoff_is_retained(self):
        from pubmail.timing import extract_offer_timing
        self.assertEqual(extract_offer_timing('Offer ends September 13, 2026.')['deadline_date'],'2026-09-13')
        self.assertEqual(extract_offer_timing('Offer ends September 13.'),{})
