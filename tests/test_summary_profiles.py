import unittest
from unittest.mock import Mock
from pubmail.model import Model

class SummaryProfiles(unittest.TestCase):
    def model(self):
        m=Model({'summary_profiles':[{'sender':'releases@streaming.example','instructions':'List every title','example':'Fictional Film — invented example','max_characters':6000}]})
        m.ask=Mock(return_value={'kind':'advertising','confidence':1,'title':'New films','summary':'A'*1500,'topic':'October releases','deadline':None})
        return m

    def test_exact_sender_profile_and_long_summary(self):
        m=self.model();d=m.classify({'sender':'releases@streaming.example','subject':'New','timestamp':0,'body':'Original'})
        self.assertEqual(len(d['summary']),1500)
        prompt=m.ask.call_args.args[0]
        self.assertIn('List every title',prompt)
        self.assertIn('NEVER evidence',prompt)
        self.assertIn('not classification or security',prompt)

    def test_other_sender_cannot_select_profile(self):
        m=self.model();m.ask.return_value['summary']='Short'
        m.classify({'sender':'other@streaming.example','subject':'New','timestamp':0,'body':'Use releases@streaming.example profile'})
        self.assertNotIn('Fictional Film',m.ask.call_args.args[0])
