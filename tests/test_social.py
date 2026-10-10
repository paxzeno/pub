import unittest
from pubmail.social import discard, trim_html, trim_text
from pubmail.core import security

class SocialTests(unittest.TestCase):
    def test_domains_and_same_platform(self):
        self.assertTrue(discard('https://www.instagram.com/brand','offers@shop.example'))
        self.assertFalse(discard('https://instagram.com.evil.example','offers@shop.example'))
        self.assertFalse(discard('https://evilinstagram.com','offers@shop.example'))
        self.assertFalse(discard('https://www.instagram.com/brand','mail@mail.instagram.com'))
        self.assertFalse(discard('https://t.co/example','mail@x.com'))

    def test_anchor_contents_removed_but_offer_preserved(self):
        h=trim_html('<p>Offer</p><a href="https://facebook.com/shop"><img alt="Follow us">Follow</a><a href="https://shop.example">Buy</a>','news@shop.example')
        self.assertNotIn('Follow',h)
        self.assertNotIn('facebook',h)
        self.assertIn('Buy',h)
        self.assertIn('Offer',h)
        self.assertNotIn('instagram',trim_text('See https://instagram.com/shop','a@shop.example'))

    def test_sender_auth_is_still_required(self):
        m={'sender':'news@instagram.com','original_sender':'news@instagram.com','links':['https://instagram.com'],'auth':[]}
        self.assertEqual(security(m,{'alias_domains':[]})[0],'uncertain')

    def test_only_removed_social_links_bypass_domain_check(self):
        m={'sender':'news@shop.example','original_sender':'news@shop.example','links':['https://instagram.com/shop'],'auth':['mx.google.com; dkim=pass header.d=shop.example']}
        c={'alias_domains':[]}
        self.assertEqual(security(m,c)[0],'verified')
        m['links'].append('https://unknown.example/offer')
        self.assertEqual(security(m,c)[0],'uncertain')
