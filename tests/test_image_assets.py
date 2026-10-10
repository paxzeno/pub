import unittest
from unittest.mock import patch
from pubmail.image_assets import eligible, PinnedHTTPS
from pubmail.thumbnail import document

class ImageAssets(unittest.TestCase):
    def test_scoped_urls_and_pixels(self):
        policy={'enabled':True,'hosts':{'cdn.example.com':{'path_prefixes':['/images/'],'query_keys':['w']}}}
        self.assertTrue(eligible('https://cdn.example.com/images/a.png?w=600',policy))
        for url in ['https://cdn.example.com.evil.example/images/a.png','http://cdn.example.com/images/a.png','https://cdn.example.com/pixel','https://cdn.example.com/images/a.png?recipient=x','https://user@cdn.example.com/images/a.png']:
            self.assertFalse(eligible(url,policy))
        self.assertFalse(eligible('https://cdn.example.com/images/a.png',policy,{'width':'1'}))
        self.assertFalse(eligible('https://cdn.example.com/images/a.png',{}))

    def test_private_dns_blocked_before_connect(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]), patch('socket.create_connection') as connect:
            with self.assertRaises(ValueError):PinnedHTTPS('cdn.example.com').connect()
            connect.assert_not_called()

    def test_only_prefetched_image_enters_document(self):
        h=document('<img src="https://cdn.example.com/images/a.png"><img src="https://evil.example/pixel">','',{'https://cdn.example.com/images/a.png':'data:image/png;base64,AAAA'})
        self.assertEqual(h.count('<img'),1)
        self.assertNotIn('https://',h)
        self.assertIn('data:image/png',h)

    def test_header_unsubscribe_separate_from_tracker_exclusion(self):
        from pubmail.core import unsubscribe_control
        c={'unsubscribe_controls':{'manage.example.com':['/subscriptions/unsubscribe']}}
        url='https://manage.example.com/subscriptions/unsubscribe?token=example'
        m={'unsubscribe':[url]}
        with patch('pubmail.core.security',return_value=('verified','',[])):
            self.assertEqual(unsubscribe_control(m,c),url)
            self.assertIsNone(unsubscribe_control({'unsubscribe':[],'links':[url]},c))
            self.assertIsNone(unsubscribe_control({'unsubscribe':[url.replace('/subscriptions/unsubscribe','/click')]},c))
            self.assertIsNone(unsubscribe_control({'unsubscribe':[url.replace('manage.example.com','manage.example.com.evil.example')]},c))
        with patch('pubmail.core.security',return_value=('uncertain','',[])):
            self.assertIsNone(unsubscribe_control(m,c))
