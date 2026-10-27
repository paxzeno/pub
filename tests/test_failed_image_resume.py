import base64,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from pubmail.io import Error,ProcessingPending
from pubmail.model import Model
from pubmail.vision import enrich,retry_failed_images

class FailedImageResume(unittest.TestCase):
 def test_failed_images_do_not_starve_later_images_and_retry_is_explicit(self):
  with tempfile.TemporaryDirectory() as root:
   c={'state_dir':root,'vision':{'enabled':True,'images_per_pass':1},'image_loading':{'mode':'public_https'},'model':{}}
   images={str(i):'data:image/png;base64,'+base64.b64encode(str(i).encode()).decode() for i in range(3)}
   m={'body':'Original','original_html':'<img>'}
   def sufficient(message,config):return bool(message.get('_vision_enriched'))
   with patch('pubmail.core.security',return_value=('verified','',[])),patch('pubmail.vision.text_sufficient',side_effect=sufficient),patch('pubmail.image_assets.assets',return_value=images),patch('pubmail.vision.model_image',side_effect=lambda b:b),patch.object(Model,'ask',side_effect=Error('private provider detail')) as ask:
    for n in range(2):
     with self.assertRaises(ProcessingPending):enrich(m,c)
    out=enrich(m,c);self.assertEqual(ask.call_count,6);self.assertEqual(len(out['unavailable_images']),3)
    self.assertEqual(out['visual_evidence'],[]);self.assertIn('3 image(s)',out['coverage_notice'])
    enrich(m,c);self.assertEqual(ask.call_count,6)
    files=list((Path(root)/'vision-cache/failures').glob('*.json'))
    self.assertNotIn('private provider detail',files[0].read_text());self.assertEqual(files[0].stat().st_mode & 0o777,0o600)
    self.assertEqual(retry_failed_images(c,files[0].stem)['retryable_images'],1)
    enrich(m,c);self.assertEqual(ask.call_count,8)
    self.assertEqual(len(list((Path(root)/'vision-cache/failure-history').glob('*/*.json'))),1)
    with self.assertRaises(Error):retry_failed_images(c,'../../escape')
 def test_missing_content_still_fails_closed(self):
  with tempfile.TemporaryDirectory() as root:
   c={'state_dir':root,'vision':{'enabled':True},'image_loading':{'mode':'public_https'},'model':{}}
   image='data:image/png;base64,'+base64.b64encode(b'bad').decode()
   with patch('pubmail.core.security',return_value=('verified','',[])),patch('pubmail.vision.text_sufficient',return_value=False),patch('pubmail.image_assets.assets',return_value={'a':image}),patch('pubmail.vision.model_image',side_effect=lambda b:b),patch.object(Model,'ask',side_effect=Error('bad')) as ask:
    for n in range(2):
     with self.assertRaisesRegex(Error,'useful summary'):enrich({'body':'','original_html':'<img>'},c)
    self.assertEqual(ask.call_count,2)
