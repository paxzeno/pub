import base64,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from pubmail.vision import enrich,validate
from pubmail.io import Error
from pubmail.model import Model
class Vision(unittest.TestCase):
    def test_evidence_cache_and_title_validation(self):
        with tempfile.TemporaryDirectory() as root:
            c={'vision':{'enabled':True},'state_dir':root,'model':{'name':'vision-example'}}
            m={'body':'Original text','original_html':'<img src="x">'}
            data='data:image/png;base64,'+base64.b64encode(b'fictional-image').decode()
            with patch('pubmail.core.security',return_value=('verified','',[])),patch('pubmail.image_assets.assets',return_value={'x':data}),patch.object(Model,'ask',return_value={'text':'Example Film','titles':['Example Film'],'readable':True}) as ask:
                out=enrich(m,c)
                self.assertEqual(out['visual_titles'],['Example Film'])
                self.assertIn('Example Film',out['body'])
                self.assertEqual(m['body'],'Original text')
                self.assertEqual(ask.call_args.kwargs['images'],[data.split(',')[1]])
                enrich(m,c);self.assertEqual(ask.call_count,1)
            with self.assertRaises(Error):validate({'text':'Example Film','titles':['Invented Film'],'readable':True})
            with self.assertRaises(Error):validate({'text':'','titles':[],'readable':False})

    def test_unverified_never_loads_images(self):
        with patch('pubmail.core.security',return_value=('uncertain','',[])),patch('pubmail.image_assets.assets') as assets:
            m={'body':'source'}
            self.assertEqual(enrich(m,{'vision':{'enabled':True}}),m)
            assets.assert_not_called()

    def test_actual_multimodal_payload_native_and_compatible(self):
        for endpoint,native in [('http://127.0.0.1:11434/api/chat',True),('http://127.0.0.1:11434/v1/chat/completions',False)]:
            from unittest.mock import MagicMock
            response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'message':{'content':'{}'},'choices':[{'message':{'content':'{}'}}]}).encode()
            with patch('urllib.request.urlopen',return_value=response) as request:
                Model({'model':{'endpoint':endpoint,'name':'vision-example'}}).ask('Task',{'source':'data'},images=['AAAA'])
                msg=json.loads(request.call_args.args[0].data)['messages'][1]
                if native:self.assertEqual(msg['images'],['AAAA'])
                else:self.assertEqual(msg['content'][1]['image_url']['url'],'data:image/png;base64,AAAA')

    def test_unverified_description_is_disclosed_not_invented(self):
        from unittest.mock import Mock
        c={'summary_profiles':[{'sender':'offers@example.com','format':'title_list','max_characters':1000}]}
        m={'sender':'offers@example.com','original_sender':'offers@example.com','subject':'New','body':'Example Film','timestamp':0,'image_alts':['Example Film']}
        model=Model(c)
        model.ask=Mock(side_effect=[{'kind':'advertising','confidence':1,'title':'Films','summary':'Films','topic':'Films','deadline':None},{'items':[{'title':'Example Film','description':'An invented plot.'}]}])
        summary=model.classify(m)['summary']
        self.assertIn('Description not verified from source.',summary)
        self.assertNotIn('invented plot',summary)

    def test_triage_does_not_invoke_vision(self):
        from unittest.mock import Mock
        model=Model({'vision':{'enabled':True}})
        model.ask=Mock(return_value={'kind':'keep','confidence':1,'title':'Notice','summary':'Notice','topic':'Notice','deadline':None})
        m={'subject':'Notice','sender':'sender@example.com','timestamp':0,'body':'Notice'}
        with patch('pubmail.vision.enrich') as extraction:
            self.assertEqual(model.classify(m,include_images=False)['kind'],'keep')
            extraction.assert_not_called()
