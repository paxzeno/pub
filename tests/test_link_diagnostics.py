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
        for link in ['www.shop.example.evil.example','shop-example.com','user@shop.example','shop.example:443','//shop.example','shop.example\\@evil.example']:
            m=normalize(raw());m['links']=[link]
            self.assertEqual(security(m,conf('/tmp'))[0],'uncertain',link)

    def test_explicit_single_offer_cutoff_is_retained(self):
        from pubmail.timing import extract_offer_timing
        self.assertEqual(extract_offer_timing('Offer ends September 13, 2026.')['deadline_date'],'2026-09-13')
        self.assertEqual(extract_offer_timing('Offer ends September 13.'),{})

    @patch('pubmail.thumbnail.screenshot',return_value=b'png')
    def test_cids_bound_to_message_source_and_bytes(self,shot):
        from pubmail.digest import mime
        m=normalize(raw());c=conf('/tmp')
        item={'id':m['id'],'message':m,'title':'Offer','summary':'Offer','deadline':None}
        first=mime(c,[item],[[m['id']]],[],'first')
        second=mime(c,[item],[[m['id']]],[],'second')
        def image_parts(msg):return [p for p in msg.walk() if p.get_content_maintype()=='image']
        a=image_parts(first)[0];b=image_parts(second)[0]
        self.assertNotEqual(a['Content-ID'],b['Content-ID'])
        self.assertNotEqual(a.get_filename(),b.get_filename())
        html=next(p.get_content() for p in second.walk() if p.get_content_type()=='text/html')
        self.assertIn('cid:'+b['Content-ID'].strip('<>'),html)
        shot.return_value=b'different png'
        changed=image_parts(mime(c,[item],[[m['id']]],[],'second'))[0]
        self.assertNotEqual(b['Content-ID'],changed['Content-ID'])
        m['id']='new-source';item['id']='new-source'
        changed_source=image_parts(mime(c,[item],[['new-source']],[],'second'))[0]
        self.assertNotEqual(changed['Content-ID'],changed_source['Content-ID'])

    @patch('pubmail.thumbnail.screenshot',return_value=b'png')
    def test_serialized_inline_ids_are_literal_ascii_msg_ids(self,shot):
        import re
        from email import policy
        from email.parser import BytesParser
        from pubmail.digest import mime
        m=normalize(raw());c=conf('/tmp')
        item={'id':m['id'],'message':m,'title':'Offer','summary':'Offer','deadline':None}
        for fmt in ('html','multipart'):
            c['newsletter']['format']=fmt
            wire=mime(c,[item],[[m['id']]],[],'fictional-message').as_bytes()
            headers=re.findall(rb'^Content-ID:([^\r\n]*(?:\r\n[ \t][^\r\n]*)*)',wire,re.M)
            self.assertEqual(len(headers),1)
            self.assertRegex(headers[0],rb'^ <image-[a-f0-9]{32}@pubmail>$')
            self.assertLess(len(b'Content-ID:'+headers[0]),78)
            parsed=BytesParser(policy=policy.default).parsebytes(wire)
            html=parsed.get_body(preferencelist=('html',)).get_content()
            img=next(p for p in parsed.walk() if p.get_content_type()=='image/png')
            self.assertIn('cid:'+str(img['Content-ID']).strip('<>'),html)
            self.assertEqual(img.get_content_disposition(),'inline')
            self.assertEqual(img.get_payload(decode=True),b'png')

    @patch('pubmail.thumbnail.screenshot',return_value=b'png')
    def test_source_date_follows_from_in_configured_timezone(self,_):
        c=conf('/tmp');c['timezone']='Europe/Lisbon'
        m=normalize(raw());m['timestamp']=1787526000
        item={'id':m['id'],'message':m,'title':'Offer','summary':'Offer','deadline':None,'security_reason':'Review'}
        h,t,_=render(c,[item],[[m['id']]],[])
        self.assertIn('From: Shop &lt;'+m['original_sender']+'&gt;<br>Date: 2026-08-24 00:00:00',h)
        self.assertIn('From: Shop <'+m['original_sender']+'>\nDate: 2026-08-24 00:00:00',t)
        h,t,_=render(c,[],[],[item])
        self.assertIn('Date: 2026-08-24 00:00:00',h)
        self.assertIn('\nDate: 2026-08-24 00:00:00',t)

    def test_same_brand_http_omitted_not_upgraded(self):
        c=conf('/tmp')
        for url in ['http://shop.example/sale','http://www.shop.example:80/sale']:
            m=normalize(raw());m['links']=[url,'https://shop.example/safe']
            status,reason,safe=security(m,c)
            self.assertEqual(status,'verified')
            self.assertNotIn(url,safe)
            self.assertNotIn(url.replace('http:','https:'),safe)
            self.assertIn('omitted 1',reason)
        c['link_policy']={'omit_same_brand_http':False}
        self.assertEqual(security(m,c)[0],'uncertain')

    def test_service_omissions_scoped_to_authenticated_origin(self):
        c=conf('/tmp');c['link_policy']={'omitted_service_hosts':{'shop.example':['links.mailer.example']}}
        m=normalize(raw());m['links']=['https://links.mailer.example/secret','https://shop.example/sale']
        status,_,safe=security(m,c)
        self.assertEqual(status,'verified')
        self.assertNotIn(m['links'][0],safe)
        m['auth']=[]
        self.assertEqual(security(m,c)[0],'uncertain')
        m=normalize(raw());m['links']=['https://links.mailer.example/path']
        c['link_policy']['omitted_service_hosts']={'different.example':['links.mailer.example']}
        self.assertEqual(security(m,c)[0],'uncertain')

    def test_omission_does_not_hide_deceptive_links(self):
        c=conf('/tmp');c['link_policy']={'omitted_service_hosts':{'shop.example':['links.mailer.example']}}
        for url in ['http://shop.example.evil.example','http://shop-example.com',
                    'http://user@shop.example','http://shop.example:443','http://shop.example:8080',
                    'http://shop.example\\@evil.example','http://shop.example/\nfoo',
                    'https://links.mailer.example.evil.example/x','https://links.mailer.example:444/x',
                    'https://user@links.mailer.example/x','https://links.mailer.example\\@evil.example',
                    'https://unknown.example/x','javascript:alert(1)']:
            m=normalize(raw());m['links']=[url]
            self.assertNotEqual(security(m,c)[0],'verified',url)

    def test_invalid_service_config_rejected(self):
        import tempfile,yaml
        from pathlib import Path
        from pubmail.io import load_config,Error
        with tempfile.TemporaryDirectory() as tmp:
            c=conf(tmp)
            for hosts in [{'shop.example':['*.mailer.example']},{'shop.example':['https://mailer.example']},
                          {'shop.example':['mailer..example']}, {'shop.example':'mailer.example'}]:
                c['link_policy']={'omitted_service_hosts':hosts}
                p=Path(tmp)/'config.yaml';p.write_text(yaml.safe_dump(c))
                with self.assertRaises(Error):load_config(p)

    def test_fragment_only_omitted_not_external_relative_paths(self):
        c=conf('/tmp');m=normalize(raw());m['links']=['#top','#footer']
        self.assertEqual(security(m,c)[0],'verified')
        for url in ['/login','#x\\@evil.example','//evil.example/path']:
            m['links']=[url]
            if url.startswith('#'):
                self.assertNotIn(url,security(m,c)[2])
            else:
                self.assertEqual(security(m,c)[0],'uncertain')
