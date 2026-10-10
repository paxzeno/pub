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

    def test_event_range_subject_year_and_ambiguity(self):
        from pubmail.timing import extract_event_timing as extract
        body='Backing the tournament since 2019. Find us at\nExample Arena, City\nAug 20-23'
        t=extract(body, 'Tournament 2026: visit our booth')
        self.assertEqual((t['start'],t['end']),('2026-08-20','2026-08-23'))
        self.assertIn('Tournament 2026',t['evidence'])
        self.assertIsNone(extract(body, 'Tournament'))
        self.assertIsNone(extract(body, 'Tournament 2025 or 2026'))
        self.assertIsNone(extract('Event Feb 20-31, 2026'))
        self.assertIsNone(extract('Event Aug 20-23, 2026. Event Sep 20-23, 2026.'))
        self.assertIsNone(extract('Offer valid Aug 20-23, 2026.'))
