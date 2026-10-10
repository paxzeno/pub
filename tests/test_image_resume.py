import base64,tempfile,unittest
from unittest.mock import patch
from pubmail.io import ProcessingPending
from pubmail.vision import enrich
from pubmail.model import Model
from pubmail.image_assets import assets
class Resume(unittest.TestCase):
    @patch('pubmail.vision.model_image',side_effect=lambda b:b)
    def test_thirteen_images_resume_without_reprocessing(self,_padding):
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
    @patch('pubmail.vision.model_image',side_effect=lambda b:b)
    def test_time_budget(self,_padding):
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

    def test_incomplete_timing_is_not_silently_lost(self):
        from pubmail.timing import unresolved_timing_notice
        notice=unresolved_timing_notice('LIVE SESSION AUGUST 26 • 9AM PT / 12PM ET')
        self.assertIn('AUGUST 26',notice)
        self.assertIn('9AM PT / 12PM ET',notice)
        self.assertIn('not verified',notice)
        self.assertNotIn('2026',notice)
        self.assertIn('exact cutoff not supplied',unresolved_timing_notice('Your summer savings won’t last long'))

    def test_single_webinar_date_has_explicit_year(self):
        from pubmail.timing import extract_event_timing
        event=extract_event_timing('Webinar Date & Time Wednesday, August 26, 2026 9am PT / 12pm ET')
        self.assertEqual(event['start'],'2026-08-26')
        self.assertEqual(event['end'],'2026-08-26')
        self.assertIsNone(extract_event_timing('Webinar August 26. Copyright 2026'))
