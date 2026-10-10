import unittest
from unittest.mock import patch
from test_pubmail import raw, conf
from pubmail.core import normalize, preclassify
from pubmail.model import Model
from pubmail.digest import render
from pubmail.text_input import bounded_message

class TextTrimming(unittest.TestCase):
    def test_full_source_protection_survives_trim(self):
        m=normalize(raw(body='sale '*100+'Your invoice is ready'),20)
        self.assertEqual(preclassify(m,conf('/tmp'))[0],'keep')

    def test_limit_boundary_unicode_and_original_unchanged(self):
        c=conf('/tmp');c['limits']['body_characters']=10
        m={'body':'é'*10}
        self.assertFalse(bounded_message(m,c)['text_trimmed'])
        m['body']+='x'
        self.assertEqual(bounded_message(m,c)['body'],'é'*10)
        self.assertEqual(len(m['body']),11)

    def test_model_gets_prefix_and_marks_result(self):
        c=conf('/tmp');c['limits']['body_characters']=30
        m=normalize(raw(body='Offer for you. '*20))
        output={'kind':'advertising','confidence':.99,'title':'Offer','summary':'Offer for you.','topic':'Offer','deadline':None}
        with patch.object(Model,'ask',return_value=output) as call:
            result=Model(c).classify(m,include_images=False)
        self.assertEqual(len(call.call_args.args[1]['body']),30)
        self.assertTrue(result['text_trimmed'])

    def test_notice_order_and_no_deadline_and_untrimmed(self):
        c=conf('/tmp');m=normalize(raw())
        item=dict(id=m['id'],message=m,title='Offer',summary='Discount.',safe_urls=[],text_trimmed=True)
        with patch('pubmail.thumbnail.screenshot',return_value=b'png'):
            for deadline in [None,'2020-01-01T10:00:00+00:00']:
                item['deadline']=deadline
                html,text,_=render(c,[item],[[m['id']]],[])
                self.assertEqual(html.count('long email, it was trimmed'),1)
                self.assertEqual(text.count('long email, it was trimmed'),1)
                if deadline:
                    self.assertLess(html.index('long email, it was trimmed'),html.index('EXPIRED'))
                    self.assertLess(text.index('long email, it was trimmed'),text.index('EXPIRED'))
            item['text_trimmed']=False
            html,text,_=render(c,[item],[[m['id']]],[])
            self.assertNotIn('long email, it was trimmed',html+text)
