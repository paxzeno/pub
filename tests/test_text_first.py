import unittest,tempfile,base64
from unittest.mock import patch
from pathlib import Path
from pubmail.image_assets import eligible,assets,fetch
from pubmail.vision import enrich
class TextFirst(unittest.TestCase):
 def test_public_urls_not_filename_trust(self):
  p={'enabled':True,'mode':'public_https'}
  for u in ['https://cdn.example.com/art/webp','https://cdn.example.com/img?w=600','https://new.example.org/x.png']:
   self.assertTrue(eligible(u,p))
  for u in ['http://cdn.example.com/x','https://localhost/x','https://127.0.0.1/x','https://u:p@cdn.example.com/x','https://cdn.example.com:444/x','https://cdn.example.com/unsubscribe?token=x','https://cdn.example.com/pixel.gif']:
   self.assertFalse(eligible(u,p))
  self.assertFalse(eligible('https://cdn.example.com/img',p,{'width':'1'}))
 def test_text_only_never_downloads_or_investigates(self):
  m={'body':'A complete textual offer.','sender':'offers@example.com','original_html':'<img src="https://cdn.example.com/hero">'}
  c={'vision':{'enabled':True},'image_loading':{'mode':'public_https'}}
  with patch('pubmail.core.security',return_value=('verified','',[])),patch('pubmail.vision.text_sufficient',return_value=True),patch('pubmail.image_assets.assets') as a,patch('pubmail.resolution.resolve_image_locations') as r:
   out=enrich(m,c);self.assertTrue(out['_vision_enriched']);self.assertIn('not inspected',out['coverage_notice']);a.assert_not_called();r.assert_not_called()
 def test_failed_decorative_asset_does_not_discard_good_image(self):
  with tempfile.TemporaryDirectory() as root:
   c={'state_dir':root,'vision':{'enabled':True},'image_loading':{'enabled':True,'mode':'public_https'}}
   with patch('pubmail.image_assets.fetch',side_effect=[ValueError('bad'),b'good']):
    out=assets('<img src="https://cdn.example.com/bad"><img src="https://cdn.example.com/good">',c)
   self.assertEqual(len(out),1)
   with patch('pubmail.image_assets.fetch') as f:
    assets('<img src="https://cdn.example.com/new">',c,cache_only=True);f.assert_not_called()
 def test_text_decision_requires_literal_evidence(self):
  from pubmail.vision import text_sufficient
  with tempfile.TemporaryDirectory() as root,patch('pubmail.model.Model.ask',return_value={'sufficient':True,'evidence':['This invented excerpt is not present.']}):
   self.assertFalse(text_sufficient({'body':'Only footer','subject':'News'},{'state_dir':root,'model':{}}))
 def test_redirect_never_decoded(self):
  with patch('pubmail.image_assets.PinnedHTTPS') as cls,patch('pubmail.image_assets.decode_isolated') as d:
   cls.return_value.getresponse.return_value.status=302
   with self.assertRaises(ValueError):fetch('https://cdn.example.com/img')
   d.assert_not_called()

 def test_dns_mixed_public_private_and_multicast_rejected(self):
  from pubmail.image_assets import PinnedHTTPS
  for ips in [('8.8.8.8','169.254.169.254'),('224.0.0.1',),('::1',),('fc00::1',)]:
   with patch('socket.getaddrinfo',return_value=[(2,1,6,'',(ip,443)) for ip in ips]),patch('socket.create_connection') as connect:
    with self.assertRaises(ValueError):PinnedHTTPS('cdn.example.com').connect()
    connect.assert_not_called()
 def test_extensionless_and_generic_mime_use_actual_bytes(self):
  with patch('pubmail.image_assets.PinnedHTTPS') as cls,patch('pubmail.image_assets.decode_isolated',return_value=b'png') as decoder:
   response=cls.return_value.getresponse.return_value;response.status=200;response.read1.side_effect=[b'actual image',b'']
   self.assertEqual(fetch('https://cdn.example.com/webp'),b'png');decoder.assert_called_once_with(b'actual image')
 def test_unreadable_image_does_not_erase_other_evidence(self):
  from pubmail.io import Error
  from pubmail.model import Model
  with tempfile.TemporaryDirectory() as root:
   m={'id':'fictional','body':'Original text','sender':'offers@example.com','original_html':'<img src="https://cdn.example.com/a">'}
   c={'state_dir':root,'vision':{'enabled':True},'image_loading':{'enabled':True,'mode':'public_https'},'model':{}}
   data='data:image/png;base64,'+base64.b64encode(b'fictional').decode()
   with patch('pubmail.core.security',return_value=('verified','',[])),patch('pubmail.vision.text_sufficient',side_effect=[False,True]),patch('pubmail.image_assets.assets',return_value={'a':data}),patch('pubmail.vision.model_image',side_effect=lambda b:b),patch.object(Model,'ask',side_effect=Error('Unreadable')):
    out=enrich(m,c);self.assertEqual(out['visual_evidence'],[]);self.assertIn('unavailable artwork',out['coverage_notice'])
 def test_no_useful_combined_evidence_stays_held(self):
  from pubmail.io import Error
  from pubmail.model import Model
  with tempfile.TemporaryDirectory() as root:
   m={'id':'fictional','body':'Footer','sender':'offers@example.com','original_html':'<img src="https://cdn.example.com/a">'}
   c={'state_dir':root,'vision':{'enabled':True},'image_loading':{'enabled':True,'mode':'public_https'},'model':{}}
   data='data:image/png;base64,'+base64.b64encode(b'fictional').decode()
   with patch('pubmail.core.security',return_value=('verified','',[])),patch('pubmail.vision.text_sufficient',return_value=False),patch('pubmail.image_assets.assets',return_value={'a':data}),patch('pubmail.vision.model_image',side_effect=lambda b:b),patch.object(Model,'ask',return_value={'text':'','titles':[],'readable':True}):
    with self.assertRaisesRegex(Error,'do not support'):enrich(m,c)
 def test_grounded_paragraph_survives_short_heading_and_whitespace(self):
  from pubmail.vision import text_sufficient
  body='This offer includes free shipping on eligible orders over fifty euros.\n\nMore details below.'
  with tempfile.TemporaryDirectory() as root,patch('pubmail.model.Model.ask',return_value={'sufficient':True,'evidence':['Offer','This offer includes free shipping on eligible orders over fifty euros. More details below.']}):
   self.assertTrue(text_sufficient({'body':body,'subject':'News'},{'state_dir':root,'model':{}}))
