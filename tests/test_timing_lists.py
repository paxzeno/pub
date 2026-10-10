import unittest
from pubmail.timing import extract_offer_timing
from pubmail.digest import summary_blocks

class TimingLists(unittest.TestCase):
    def test_split_year_and_time_evidence(self):
        t=extract_offer_timing('Offer valid during promotional period of August 6–31, 2026.\nValid from Aug 6, 10am – Aug 31, 23:50 CEST only.')
        self.assertEqual(t['deadline'],'2026-08-31T23:50:00+02:00')

    def test_date_only_does_not_invent_time(self):
        t=extract_offer_timing('Offer valid August 6–31, 2026.')
        self.assertIsNone(t['deadline'])
        self.assertEqual(t['deadline_date'],'2026-08-31')
        self.assertEqual(extract_offer_timing('Offer valid August 6–31.'),{})
        self.assertEqual(extract_offer_timing('Offer valid February 6–31, 2026.'),{})

    def test_bullets_are_separate_blocks(self):
        b=summary_blocks('• First — Description\n• Second — No description supplied.')
        self.assertEqual(len(b),2)
        self.assertEqual(b[0]['title'],'First')
        self.assertEqual(b[1]['text'],'No description supplied.')
