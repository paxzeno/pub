import base64,tempfile,unittest
from unittest.mock import patch
from pubmail.io import ProcessingPending
from pubmail.vision import enrich
from pubmail.model import Model
from pubmail.image_assets import assets
class Resume(unittest.TestCase):
    def test_thirteen_images_resume_without_reprocessing(self):
        with tempfile.TemporaryDirectory() as root:
            c={'vision':{'enabled':True,'images_per_pass':4},'state_dir':root,'model':{}}
            m={'body':'Original','original_html':'<img>'}
            images={str(i):'data:image/png;base64,'+base64.b64encode(str(i).encode()).decode() for i in range(13)}
            with patch('pubmail.core.security',return_value=('verified','',[])),patch('pubmail.image_assets.assets',return_value=images),patch.object(Model,'ask',return_value={'text':'Text','titles':[],'readable':True}) as ask:
                for expected in (4,8,12):
                    with self.assertRaises(ProcessingPending):enrich(m,c)
                    self.assertEqual(ask.call_count,expected)
                    self.assertNotIn('_vision_enriched',m)
                self.assertEqual(len(enrich(m,c)['visual_evidence']),13)
                enrich(m,c);self.assertEqual(ask.call_count,13)
    def test_time_budget(self):
        with tempfile.TemporaryDirectory() as root:
            c={'vision':{'enabled':True,'pass_seconds':1},'state_dir':root,'model':{}}
            images={str(i):'data:image/png;base64,'+base64.b64encode(str(i).encode()).decode() for i in range(2)}
            with patch('pubmail.core.security',return_value=('verified','',[])),patch('pubmail.image_assets.assets',return_value=images),patch.object(Model,'ask',return_value={'text':'Text','titles':[],'readable':True}) as ask,patch('pubmail.vision.time.monotonic',side_effect=[0,0,2]):
                with self.assertRaises(ProcessingPending):enrich({'body':'Text','original_html':'<img>'},c)
                self.assertEqual(ask.call_count,1)
    def test_download_resume(self):
        with tempfile.TemporaryDirectory() as root:
            c={'state_dir':root,'vision':{'enabled':True},'image_loading':{'enabled':True,'downloads_per_pass':5,'hosts':{'cdn.example.com':{'path_prefixes':['/images/']}}}}
            markup=''.join(f'<img src="https://cdn.example.com/images/{i}.png">' for i in range(13))
            with patch('pubmail.image_assets.fetch',return_value=b'image') as fetch:
                for count in (5,10):
                    with self.assertRaises(ProcessingPending):assets(markup,c)
                    self.assertEqual(fetch.call_count,count)
                self.assertEqual(len(assets(markup,c)),13)
                assets(markup,c);self.assertEqual(fetch.call_count,13)
    def test_pending_never_escalates(self):
        from pubmail.reviewer import EscalatingModel
        from unittest.mock import Mock
        model=object.__new__(EscalatingModel);model.c={};model.local=Mock();model.reviewer=Mock()
        with patch('pubmail.vision.enrich',side_effect=ProcessingPending('saved')):
            with self.assertRaises(ProcessingPending):model.classify({})
        model.reviewer.exchange.assert_not_called()
