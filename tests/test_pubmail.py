import base64, copy, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
import yaml
from pubmail.core import normalize, security, preclassify, week_bounds
from pubmail.io import Error, Store
from pubmail import workflow, digest
from pubmail.model import Model

ROOT = Path(__file__).resolve().parents[1]


def raw(
    id="a1", body="Discover our summer collection.", subject="Summer sale", labels=None
):
    return {
        "id": id,
        "threadId": "thread",
        "internalDate": "1782730800000",
        "labelIds": labels or ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Shop <offers@shop.example>"},
                {"name": "Subject", "value": subject},
                {
                    "name": "Authentication-Results",
                    "value": "mx.google.com; dkim=pass header.d=shop.example; dmarc=pass header.from=shop.example",
                },
                {
                    "name": "List-Unsubscribe",
                    "value": "<https://shop.example/unsubscribe>",
                },
            ],
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
        },
    }


def conf(path):
    c = yaml.safe_load((ROOT / "config.example.yaml").read_text())
    c["state_dir"] = path
    c["advertising"] = [{"sender": "offers@shop.example", "subject_regex": "sale"}]
    c["security_exceptions"] = []
    return c


class FakeGmail:
    def __init__(self, rs):
        self.messages = {r["id"]: r for r in rs}
        self.calls = []
        self.names = {"ads": "L1", "ads/newsletter": "L2"}

    def raw(self, id):
        return copy.deepcopy(self.messages[id])

    def search(self, q, limit=200):
        return ([{"id": k} for k in self.messages][:limit], False)

    def labels(self, create=False):
        return self.names

    def modify(self, id, add=(), remove=()):
        self.calls.append((id, list(add), list(remove)))
        m = self.messages[id]
        m["labelIds"] = list((set(m["labelIds"]) | set(add)) - set(remove))


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = conf(self.tmp.name)
        self.store = Store(self.c)
        self.g = FakeGmail([raw()])
        self.model = Mock()
        self.model.groups.side_effect = lambda items: [[i["id"]] for i in items]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def plan(self):
        return workflow.plan(
            self.g,
            self.c,
            self.model,
            self.store,
            week=week_bounds(1782730800, "Europe/Lisbon"),
        )

    def test_alias_requires_matching_original_arc(self):
        m = normalize(raw())
        self.c["alias_domains"] = ["shop.example"]
        self.c["security_exceptions"] = [
            {
                "sender": "offers@shop.example",
                "relay_domain": "shop.example",
                "original_domain": "merchant.example",
                "link_domains": ["shop.example"],
                "reason": "Verified sender mapping",
            }
        ]
        self.assertEqual(security(m, self.c)[0], "uncertain")
        m["auth"][0] += "; arc=pass (i=1 dmarc=pass fromdomain=merchant.example)"
        self.assertEqual(security(m, self.c)[0], "verified")
        m["auth"][0] = m["auth"][0].replace("i=1 dmarc=pass", "i=1 dmarc=fail")
        self.assertEqual(security(m, self.c)[0], "uncertain")

    def test_plan_newsletter_preview_cannot_be_sent(self):
        p, h = self.plan()
        self.model.classify.return_value = dict(title='Updated source summary', summary='Current offer details', topic='Sale', deadline=None)
        result = digest.preview_plan(self.c, self.model, self.store, p["id"])
        self.assertIn('Current offer details', Path(result['preview']).read_text())
        self.assertFalse(result["sendable"])
        self.assertEqual(self.g.calls, [])
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM deliveries").fetchone()[0], 0
        )

    def test_empty_gmail_header_value(self):
        r = raw()
        r["payload"]["headers"].append({"name": "X-Empty"})
        self.assertEqual(normalize(r)["sender"], "offers@shop.example")

    def test_no_candidates_no_model(self):
        self.g.messages = {}
        p, h = self.plan()
        self.assertEqual(p["decisions"], [])
        self.model.classify.assert_not_called()

    def test_truncated_hourly_window_fails_closed(self):
        self.c["rollout"]["live_after"] = 1700000000
        self.g.search = lambda *args: ([{"id": "a1"}], True)
        with self.assertRaises(Error):
            workflow.plan(self.g, self.c, self.model, self.store, hourly=True)
        self.assertEqual(self.g.calls, [])

    def test_defang_keeps_sentence_punctuation(self):
        from pubmail.core import safe_text

        s = safe_text("A sentence. See www.example.com or a@example.com.")
        self.assertIn("sentence.", s)
        self.assertNotIn("example.com", s)

    def test_whitelist_wins(self):
        self.c["whitelist"]["addresses"] = ["offers@shop.example"]
        self.assertEqual(preclassify(normalize(raw()), self.c)[0], "keep")

    def test_transactional_wins(self):
        self.assertEqual(
            preclassify(normalize(raw(body="Your invoice is ready.")), self.c)[0],
            "keep",
        )

    def test_large_body_trimmed_not_rejected(self):
        self.assertEqual(
            preclassify(normalize(raw(body="a" * 100), 20), self.c)[0], "advertising"
        )

    def test_unknown_not_candidate(self):
        m = normalize(raw(subject="Hello"))
        m["unsubscribe"] = []
        self.assertEqual(preclassify(m, self.c)[0], "keep")

    def test_auth_spoof_later_ignored(self):
        m = normalize(raw())
        m["auth"] = [
            "attacker.example; dmarc=pass header.from=shop.example",
            m["auth"][0],
        ]
        self.assertEqual(security(m, self.c)[0], "uncertain")

    def test_authenticated_sender(self):
        self.assertEqual(security(normalize(raw()), self.c)[0], "verified")

    def test_link_mismatch(self):
        m = normalize(raw())
        m["links"] = ["https://shop.example.evil.test/"]
        self.assertEqual(security(m, self.c)[0], "uncertain")

    def test_unsafe_schemes(self):
        for url in [
            "http://unrelated.example/",
            "javascript:alert(1)",
            "https://127.0.0.1/",
            "https://shop.example@evil.example/",
        ]:
            m = normalize(raw())
            m["links"] = [url]
            self.assertNotEqual(security(m, self.c)[0], "verified")

    def test_brand_impersonation(self):
        m = normalize(raw())
        m["sender_display"] = "PayPal support"
        self.assertEqual(security(m, self.c)[0], "suspicious")

    def test_scoped_link_exception(self):
        m = normalize(raw())
        m["links"] = ["https://tracking.example/offer"]
        self.c["security_exceptions"] = [
            {
                "sender": "offers@shop.example",
                "link_domains": ["tracking.example"],
                "reason": "Manually verified",
            }
        ]
        self.assertEqual(security(m, self.c)[0], "verified")
        m["original_sender"] = "other@shop.example"
        self.assertNotEqual(security(m, self.c)[0], "verified")

    def test_relay_not_blanket_trust(self):
        m = normalize(raw())
        self.c["alias_domains"] = ["shop.example"]
        self.assertEqual(security(m, self.c)[0], "uncertain")

    def test_dry_run_no_mutation(self):
        p, h = self.plan()
        self.assertEqual(self.g.calls, [])
        self.assertEqual(p["decisions"][0]["action"], "archive")
        self.model.classify.assert_not_called()

    def test_hash_required(self):
        p, h = self.plan()
        with self.assertRaises(Error):
            workflow.apply(self.g, self.c, self.store, p["id"], "wrong")

    def test_read_since_preview_skipped(self):
        p, h = self.plan()
        self.g.messages["a1"]["labelIds"].remove("UNREAD")
        self.assertEqual(
            workflow.apply(self.g, self.c, self.store, p["id"], h)["archived"], 0
        )

    def test_policy_change_invalidates(self):
        p, h = self.plan()
        self.c["whitelist"]["addresses"].append("offers@shop.example")
        with self.assertRaises(Error):
            workflow.apply(self.g, self.c, self.store, p["id"], h)

    def test_changed_body_skipped(self):
        p, h = self.plan()
        self.g.messages["a1"]["payload"]["body"]["data"] = "eA=="
        self.assertEqual(
            workflow.apply(self.g, self.c, self.store, p["id"], h)["archived"], 0
        )

    def test_apply_preserves_unread_and_idempotent(self):
        p, h = self.plan()
        workflow.apply(self.g, self.c, self.store, p["id"], h)
        workflow.apply(self.g, self.c, self.store, p["id"], h)
        self.assertEqual(len(self.g.calls), 1)
        self.assertIn("UNREAD", self.g.messages["a1"]["labelIds"])
        self.assertNotIn("INBOX", self.g.messages["a1"]["labelIds"])

    def test_undo(self):
        p, h = self.plan()
        workflow.apply(self.g, self.c, self.store, p["id"], h)
        workflow.undo(self.g, self.c, self.store, p["id"])
        self.assertIn("INBOX", self.g.messages["a1"]["labelIds"])
        self.assertIn("UNREAD", self.g.messages["a1"]["labelIds"])

    def test_suspicious_retained_review_queue(self):
        self.g.messages["a1"] = raw(body="Go https://unrelated.example/ now")
        p, h = self.plan()
        self.assertEqual(p["decisions"][0]["action"], "review")
        workflow.apply(self.g, self.c, self.store, p["id"], h)
        self.assertEqual(self.g.calls, [])
        self.assertTrue(
            self.store.db.execute("SELECT 1 FROM meta WHERE key='review:a1'").fetchone()
        )

    def test_model_failure_keeps_and_retries(self):
        self.c["advertising"] = []
        self.model.classify.side_effect = Error("bad")
        p, h = self.plan()
        self.assertEqual(p["decisions"][0]["action"], "keep")
        self.assertTrue(p["decisions"][0]["retry"])

    def test_dst_week_is_calendar_week(self):
        ts = datetime(2026, 3, 25, tzinfo=timezone.utc).timestamp()
        a, b = week_bounds(ts, "Europe/Lisbon")
        self.assertEqual(b - a, 167 * 3600)

    def test_template_copies_match(self):
        self.assertEqual(
            (ROOT / "templates/newsletter.html").read_bytes(),
            (ROOT / "pubmail/templates/newsletter.html").read_bytes(),
        )

    def items(self):
        m = normalize(raw())
        return [
            {
                "id": "a1",
                "title": "<script>bad</script>",
                "summary": "A summer collection.",
                "topic": "Summer collection",
                "deadline": "2020-01-01T10:00:00+00:00",
                "message": m,
                "safe_urls": m["unsubscribe"],
                "security_reason": "Review https://evil.example",
            }
        ]

    def test_render_autoescaped_and_expired(self):
        h, t, imgs = digest.render(self.c, self.items(), [["a1"]], [])
        self.assertNotIn("<script>bad", h)
        self.assertIn("&lt;script&gt;", h)
        self.assertIn("EXPIRED", h)
        self.assertIn("EXPIRED", t)

    def test_event_badge_survives_cached_summary(self):
        items = self.items()
        items[0]['deadline'] = None
        items[0]['message'].update(body='Find us at Example Arena, Aug 20-23', subject='Tournament 2026')
        for day, status in [(19, 'UPCOMING'), (22, 'ONGOING'), (24, 'ENDED')]:
            h, t, _ = digest.render(self.c, items, [['a1']], [], now=datetime(2026,8,day,tzinfo=timezone.utc))
            self.assertIn('EVENT ' + status, h)
            self.assertIn('EVENT ' + status, t)
            self.assertIn('20 Aug 2026', t)
            self.assertIn('23 Aug 2026', t)
            self.assertNotIn('EXPIRED', t)

    def test_sender_card_keeps_different_topics_and_links(self):
        first = self.items()[0]
        second = copy.deepcopy(first)
        second.update(id='a2', title='Different campaign', summary='Separate details', topic='Another topic')
        second['message'].update(id='a2', thread_id='thread-two')
        third = copy.deepcopy(first)
        third.update(id='a3', title='Other sender')
        third['message'].update(id='a3', original_sender='another@shop.example')
        with patch('pubmail.thumbnail.screenshot', return_value=b'png') as screenshot:
            h, t, images = digest.render(self.c, [first,second,third], [['a1'],['a3'],['a2']], [])
        self.assertEqual(len(images), 2)
        self.assertEqual(screenshot.call_count, 2)
        self.assertIn('Different campaign', h)
        self.assertIn('Separate details', t)
        self.assertIn('thread-two', h)
        self.assertEqual(h.count('Read original email'), 3)
        self.assertLess(h.index('Separate details'), h.index('Other sender'))
        with self.assertRaises(Error):
            digest.render(self.c, [first,second], [['a1']], [])

    def test_relative_urgency_is_visible_without_invented_deadline(self):
        items=self.items();items[0]['deadline']=None
        items[0]['message'].update(subject='Só este fim de semana',body='Sale')
        h,t,_=digest.render(self.c,items,[['a1']],[])
        self.assertIn('TIME-SENSITIVE',h)
        self.assertIn('exact cutoff not supplied',t)
        self.assertNotIn('EXPIRED',t)

    def test_suspicious_no_links(self):
        h, t, imgs = digest.render(self.c, [], [], self.items())
        self.assertNotIn("href=", h)
        self.assertNotIn("https://", t)
        self.assertNotIn("<img", h)

    def test_multipart_equivalence(self):
        msg = digest.mime(self.c, self.items(), [["a1"]], [], "test")
        self.assertEqual(msg.get_content_type(), "multipart/alternative")
        self.assertIn(
            "A summer collection.",
            msg.get_body(preferencelist=("plain",)).get_content(),
        )
        self.assertIn(
            "A summer collection.", msg.get_body(preferencelist=("html",)).get_content()
        )
        self.assertTrue(any(p.get_content_type() == "image/png" for p in msg.walk()))

    def test_invalid_group_cannot_drop_mail(self):
        model = Model(self.c)
        model.ask = Mock(return_value={"groups": [["a1"]]})
        with self.assertRaises(Error):
            model.groups(
                [dict(id=i, title="x", topic="x", summary="x") for i in ["a1", "a2"]]
            )

    def test_deadline_requires_source_evidence(self):
        model = Model(self.c)
        model.ask = Mock(
            return_value=dict(
                kind="advertising",
                confidence=1,
                title="x",
                summary="x",
                topic="x",
                deadline="2026-10-10T10:00:00Z",
                deadline_evidence="not in original",
            )
        )
        self.assertIsNone(model.classify(normalize(raw()))["deadline"])

    def test_digest_send_ambiguity_blocks_retry(self):
        self.model.classify.return_value = dict(
            title="Collection",
            summary="Summer collection.",
            topic="Summer collection",
            deadline=None,
        )
        self.g.messages["a1"]["labelIds"] = ["L1", "UNREAD"]
        p = digest.prepare(self.g, self.c, self.model, self.store)
        self.assertEqual(self.g.calls, [])
        with patch("pubmail.digest.run", side_effect=Error("timeout")) as run:
            with self.assertRaises(Error):
                digest.send(self.g, self.c, self.store, p["id"])
            with self.assertRaises(Error):
                digest.send(self.g, self.c, self.store, p["id"])
            self.assertEqual(run.call_count, 1)
        self.assertEqual(self.g.calls, [])

    def test_delivered_ledger_prevents_repeat_when_label_removed(self):
        self.g.messages["a1"]["labelIds"] = ["L1"]
        self.store.delivery("old", "complete", {"ids": ["a1"]})
        self.assertIsNone(digest.prepare(self.g, self.c, self.model, self.store))
        self.model.classify.assert_not_called()

    def test_digest_labels_only_after_send(self):
        self.model.classify.return_value = dict(
            title="Collection",
            summary="Summer collection.",
            topic="Summer collection",
            deadline=None,
        )
        self.g.messages["a1"]["labelIds"] = ["L1"]  # read mail remains eligible
        p = digest.prepare(self.g, self.c, self.model, self.store)
        with patch("pubmail.digest.run", return_value="ok") as run:
            digest.send(self.g, self.c, self.store, p["id"])
            digest.send(self.g, self.c, self.store, p["id"])
            self.assertEqual(run.call_count, 1)
        self.assertIn("L2", self.g.messages["a1"]["labelIds"])
        self.assertNotIn("L1", self.g.messages["a1"]["labelIds"])
        self.assertNotIn("UNREAD", self.g.messages["a1"]["labelIds"])

    def test_partial_delivered_label_transition_recovers_without_resend(self):
        self.g = FakeGmail([raw('a1', labels=['L1', 'UNREAD', 'IMPORTANT']),
                            raw('a2', labels=['L1', 'INBOX', 'STARRED'])])
        p = {'ids': ['a1', 'a2']}
        self.store.delivery('accepted', 'sent', p)
        modify = self.g.modify
        def fail_second(mid, **kwargs):
            if mid == 'a2':
                raise Error('label service unavailable')
            return modify(mid, **kwargs)
        with patch.object(self.g, 'modify', side_effect=fail_second):
            with self.assertRaises(Error):
                digest.send(self.g, self.c, self.store, 'accepted')
        self.assertEqual(set(self.g.messages['a1']['labelIds']), {'L2', 'UNREAD', 'IMPORTANT'})
        self.assertEqual(set(self.g.messages['a2']['labelIds']), {'L1', 'INBOX', 'STARRED'})
        self.assertEqual(self.store.db.execute("SELECT status FROM deliveries WHERE id='accepted'").fetchone()[0], 'sent')
        with patch('pubmail.digest.run') as smtp:
            digest.send(self.g, self.c, self.store, 'accepted')
            digest.send(self.g, self.c, self.store, 'accepted')
            smtp.assert_not_called()
        self.assertEqual(set(self.g.messages['a2']['labelIds']), {'L2', 'INBOX', 'STARRED'})

    def test_digest_cutover_excludes_old_ads_and_review_without_mutation(self):
        self.c['rollout']['live_after'] = 1782730801
        self.g.messages['a1']['labelIds'] = ['L1', 'UNREAD']
        self.store.db.execute("INSERT INTO meta VALUES(?,?)", ('review:a1', '{}'))
        self.store.db.commit()
        self.assertIsNone(digest.prepare(self.g, self.c, self.model, self.store))
        self.model.classify.assert_not_called()
        self.assertEqual(self.g.calls, [])
        self.assertIsNotNone(self.store.db.execute("SELECT value FROM meta WHERE key='review:a1'").fetchone())

    def test_digest_cutover_includes_exact_boundary(self):
        self.c['rollout']['live_after'] = 1782730800
        self.g.messages['a1']['labelIds'] = ['L1', 'UNREAD']
        self.model.classify.return_value = dict(title='Collection', summary='Summer collection.', topic='Summer', deadline=None)
        self.assertEqual(digest.prepare(self.g, self.c, self.model, self.store)['ids'], ['a1'])


if __name__ == "__main__":
    unittest.main()
