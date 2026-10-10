import base64,unittest
from unittest.mock import Mock
from pubmail.core import normalize,security
from pubmail.model import Model

class ExtractionExceptions(unittest.TestCase):
    def test_html_alt_and_links_win_over_broken_alternative(self):
        enc=lambda x:base64.urlsafe_b64encode(x.encode()).decode()
        m=normalize({'id':'a','payload':{'headers':[{'name':'From','value':'news@shop.example'}],'parts':[
            {'mimeType':'text/plain','body':{'data':enc('https://ma=\r\nngled.example')}},
            {'mimeType':'text/html','body':{'data':enc('<p>New titles</p><img alt="Film One"><a href="https://shop.example">More</a>')}}]}})
        self.assertIn('Film One',m['body'])
        self.assertEqual(m['image_alts'],['Film One'])
        self.assertEqual(m['links'],['https://shop.example'])

    def test_scoped_omissions_not_returned_as_safe_urls(self):
        m={'sender':'news@shop.example','original_sender':'news@shop.example','auth':['mx.google.com; dkim=pass header.d=shop.example'],'links':['http://shop.example','mailto:help@shop.example','https://shop.example']}
        ex={'sender':m['sender'],'relay_domain':'','reason':'Operator review','omit_http_domains':['shop.example'],'omit_mailto':True}
        c={'security_exceptions':[ex]}
        self.assertEqual(security(m,c)[2],['https://shop.example'])
        m['links'].append('http://evil.example')
        self.assertEqual(security(m,c)[0],'uncertain')
        m['auth']=[]
        self.assertEqual(security(m,c)[0],'uncertain')

    def test_complete_titles_required(self):
        m=Model({'summary_profiles':[{'sender':'news@shop.example','format':'title_list'}]})
        result={'kind':'advertising','confidence':1,'title':'New','summary':'Short','topic':'Films','deadline':None}
        m.ask=Mock(side_effect=[result,{'items':[{'title':'Film One','description':None}]}])
        from pubmail.io import Error
        with self.assertRaises(Error):
            m.classify({'sender':'news@shop.example','subject':'New','timestamp':0,'body':'Film One Film Two','image_alts':['Film One','Film Two']})

    def test_operator_vouched_relay_still_requires_authentication(self):
        m={'sender':'alias@privaterelay.appleid.com','original_sender':'alias@privaterelay.appleid.com','auth':['mx.google.com; dkim=pass header.d=privaterelay.appleid.com'],'links':['https://click.shop.example']}
        ex={'sender':m['sender'],'relay_domain':'privaterelay.appleid.com','original_domain':'shop.example','link_domains':['click.shop.example'],'reason':'Explicit operator review'}
        c={'alias_domains':['privaterelay.appleid.com'],'security_exceptions':[ex]}
        self.assertEqual(security(m,c)[0],'uncertain')
        ex['operator_verified_original']=True
        self.assertEqual(security(m,c)[0],'verified')
        self.assertIn('operator-vouched',security(m,c)[1])
        m['auth']=[]
        self.assertEqual(security(m,c)[0],'uncertain')

    def test_forwarder_original_header_requires_gmail_arc(self):
        def message(arc='pass', origin='shop.example', extra=None):
            headers=[{'name':'From','value':'alias@relay.example'},
                     {'name':'X-SimpleLogin-Original-From','value':'Shop <news@shop.example>'},
                     {'name':'Authentication-Results','value':f'mx.google.com; dkim=pass header.d=relay.example; arc={arc} (i=1 dkim=pass dkdomain={origin} dmarc=pass fromdomain={origin})'}]
            if extra: headers.append(extra)
            return normalize({'id':'x','payload':{'headers':headers}})
        c={'alias_domains':['relay.example']}
        good=message();self.assertEqual(good['original_sender'],'news@shop.example')
        self.assertEqual(security(good,c)[0],'verified')
        for bad in [message('fail'),message(origin='evil.example'),message(extra={'name':'X-Original-From','value':'other@shop.example'}),message(extra={'name':'X-SimpleLogin-Original-From','value':'news@shop.example'})]:
            self.assertEqual(security(bad,c)[0],'uncertain')
        forged=message();forged['auth']=['attacker.example; arc=pass (dmarc=pass fromdomain=shop.example)',good['auth'][0]]
        self.assertEqual(security(forged,c)[0],'uncertain')
        badroute=message();badroute['auth']=['mx.google.com; dkim=fail header.d=relay.example; arc=pass (dmarc=pass fromdomain=shop.example)']
        self.assertEqual(security(badroute,c)[0],'uncertain')
        direct=message();direct['sender']='news@another.example'
        self.assertEqual(security(direct,c)[0],'uncertain')
        good['links']=['https://shop.example.evil.example']
        self.assertEqual(security(good,c)[0],'uncertain')
