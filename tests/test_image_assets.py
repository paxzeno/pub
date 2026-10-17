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

    def test_encoded_spaces_not_encoded_traversal(self):
        policy={'enabled':True,'hosts':{'cdn.example.com':{'path_prefixes':['/images/'],'query_keys':[]}}}
        self.assertTrue(eligible('https://cdn.example.com/images/Product%20Hero.png',policy))
        self.assertTrue(eligible('https://cdn.example.com/images/%7Babc%7D_Hero%2836%29.png',policy))
        for path in ['%2e%2e/secret.png','%2520secret.png','%2fsecret.png','%20../secret.png','../secret.png']:
            self.assertFalse(eligible('https://cdn.example.com/images/'+path,policy))

    def test_small_vision_input_is_padded_without_losing_pixels(self):
        from pubmail.vision import model_image
        from PIL import Image
        from io import BytesIO
        import base64
        b=BytesIO();Image.new('RGB',(108,25),'red').save(b,format='PNG')
        result=Image.open(BytesIO(base64.b64decode(model_image(base64.b64encode(b.getvalue()).decode()))))
        self.assertEqual(result.size,(108,64))
        self.assertEqual(result.getpixel((0,0)),(255,0,0))
        self.assertEqual(result.getpixel((0,63)),(255,255,255))

    def test_sender_bound_folder_and_new_filenames(self):
        from pubmail.image_assets import source_config
        c={'image_loading':{'enabled':True,'hosts':{},'sender_hosts':{'sender@brand.example':{'cdn.example.com':{'path_prefixes':['/brand/images/'],'query_keys':[]}}}}}
        m={'original_sender':'sender@brand.example'}
        with patch('pubmail.core.security',return_value=('verified','',[])):
            p=source_config(m,c)['image_loading']
        self.assertTrue(eligible('https://cdn.example.com/brand/images/new/2027.png',p))
        for url in ['https://cdn.example.com/other/x.png','https://cdn.example.com/brand/images/../x.png','https://cdn.example.com/brand/images/x.png?token=abc']:
            self.assertFalse(eligible(url,p))
        self.assertFalse(eligible('https://cdn.example.com/brand/images/x.png',source_config({'original_sender':'other@brand.example'},c)['image_loading']))
        with patch('pubmail.core.security',return_value=('uncertain','',[])):
            self.assertEqual(source_config(m,c)['image_loading']['hosts'],{})

    def test_rejected_locations_exclude_trackers_and_query_values(self):
        from pubmail.image_assets import missing_locations
        c={'image_loading':{'enabled':True,'hosts':{}},'ignored_tracking_domains':['track.example.com']}
        out=missing_locations('<img src="https://new.example.com/image.png?token=secret"><img src="https://track.example.com/pixel"><img width="1" src="https://other.example.com/pixel">',c)
        self.assertEqual(len(out),1);self.assertEqual(out[0]['reason'],'unknown_host')
        self.assertNotIn('secret',str(out));self.assertEqual(out[0]['query_keys'],['token'])

    def test_timestamp_query_is_explicit_and_bounded(self):
        p={'enabled':True,'hosts':{'cdn.example.com':{'path_prefixes':['/brand/'],'allow_timestamp_query':True}}}
        self.assertTrue(eligible('https://cdn.example.com/brand/a.png?1772639916',p))
        for query in ['token=secret','1772639916&token=secret','123','a1772639916']:
            self.assertFalse(eligible('https://cdn.example.com/brand/a.png?'+query,p))
