"""Rebuild a fictional newsletter with the production renderer; never access mail.

Run: .venv/bin/python examples/preview.py --publish-docs
All dates, senders, source emails and offers below are invented fixtures.
"""

import argparse
from datetime import datetime
from html import escape
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo
import yaml
from pubmail.digest import render, mime

ROOT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo('Europe/Lisbon')
NOW = datetime(2026, 10, 11, 11, 0, tzinfo=ZONE)


def source_panel(brand, title, detail, accent, background):
    """Fictional original-email HTML, rasterised by the normal offline renderer."""
    return f'''<div style="background:{background};color:#fff;padding:30px 32px;font-family:Arial;min-height:310px;box-sizing:border-box">
    <p style="font-size:14px;letter-spacing:4px;margin:0 0 22px;color:{accent}">{escape(brand.upper())}</p>
    <div style="width:56px;height:5px;background:{accent};margin-bottom:20px"></div>
    <h1 style="font-size:44px;line-height:1.05;letter-spacing:-1px;margin:0 0 20px;max-width:490px">{escape(title)}</h1>
    <p style="font-size:19px;line-height:1.5;margin:0;max-width:490px">{escape(detail)}</p>
    <p style="font-size:11px;margin-top:26px;color:{accent}">FICTIONAL EMAIL · PUBLIC DESIGN SAMPLE</p></div>'''


def fixture(mid, sender, title, summary, received, panel, **extra):
    message = dict(id=mid, original_sender=sender, subject=title,
                   body=extra.pop('source_body', summary), original_html=panel,
                   timestamp=int(datetime.fromisoformat(received).replace(tzinfo=ZONE).timestamp()),
                   rfc_message_id=f'{mid}@example.com',
                   unsubscribe=[f'https://{sender.split("@")[1]}/unsubscribe'])
    return dict(id=mid, title=title, summary=summary, topic=title, message=message,
                safe_urls=message['unsubscribe'], deadline=None, **extra)


def build():
    c = yaml.safe_load((ROOT / 'config.example.yaml').read_text())
    items = [
        fixture('sample-trail-offer', 'hello@trail.example', 'Pack lighter. Stay out longer.',
                'Selected daypacks are 20% off with TRAIL20 on orders of €60 or more. Waterproof jackets are excluded. The offer ends on 12 October 2026; no cutoff time is supplied.',
                '2026-10-08T09:14:22', source_panel('Trail Supply', 'A little further.\nA little lighter.', '20% off selected daypacks · code TRAIL20', '#d8eba4', '#263c32'),
                deadline_date='2026-10-12'),
        fixture('sample-trail-guide', 'hello@trail.example', 'A morning outside, without the overpacking',
                '• Start small — A short local route can be enough for a reset.\n• Pack the essentials — Water, an extra layer and a charged phone.\n• Leave room — This guide is separate from the daypack promotion above.',
                '2026-10-09T17:08:16', source_panel('Trail Supply', 'Make room for the outside.', 'Three ideas for your next quiet morning.', '#d8eba4', '#263c32')),
        fixture('sample-screen', 'news@screen.example', 'Three new stories for your weekend',
                '• The Glass Harbour — A coastal mystery; available 10 October.\n• Orbit Nine — A documentary following an observatory crew; available now.\n• The Last Orchard — Title supplied by the artwork. Description not verified from source.',
                '2026-10-09T18:32:05', source_panel('Screen Club', 'New worlds.\nOne weekend.', 'The Glass Harbour · Orbit Nine · The Last Orchard', '#ffd6b4', '#462d3f')),
        fixture('sample-reading', 'offers@reading.example', 'The introductory reading offer has ended',
                'The introduction was €1.99 per month for three months, then €10.99 per month until cancelled. New members only. The signup offer ended on 9 October 2026. This summary covers only the retained text prefix.',
                '2026-10-07T12:45:30', source_panel('Reading Room', 'Your next chapter.', 'Three months at €1.99/month. Then €10.99/month.', '#ffe3a3', '#453b27'),
                deadline_date='2026-10-09', text_trimmed=True),
        fixture('sample-makers', 'events@makers.example', 'Meet the makers this October',
                'A two-day design fair includes hands-on workshops and independent makers. The event runs 17–18 October 2026. Workshop places require separate registration; opening times were not supplied.',
                '2026-10-10T10:05:42', source_panel('Makers Weekend', 'Ideas worth\ngetting out for.', '17–18 October 2026 · Workshops & independent design', '#b8e0f2', '#243f50'),
                source_body='Join our design festival October 17–18, 2026. Workshop registration is separate. Opening times not supplied.'),
    ]
    flagged = [dict(id='sample-review', title='An offer with unverified sender attribution',
                    summary='This fictional message claims to represent a familiar shop. Its sender could not be verified, so it stays in the inbox without artwork or active links.',
                    message=dict(id='sample-review', original_sender='offers@unverified.example', body='',
                                 timestamp=int(datetime(2026,10,10,15,20,0,tzinfo=ZONE).timestamp())),
                    security_reason='Claimed sender identity is not supported by authentication evidence.')]
    # Different topics from the exact same sender still produce one visual section.
    groups = [[item['id']] for item in items]
    h, t, images = render(c, items, groups, flagged, now=NOW, inline=True)
    assert len(images) == 4
    assert h.count('Read original email') == 5
    assert h.count('Date: ') == 6
    assert h.count('>Unsubscribe</a>') == 5
    for marker in ('long email, it was trimmed', 'EXPIRED', 'EVENT UPCOMING', 'REVIEW DESK'):
        assert marker in h, marker
    h = '\n'.join(line.rstrip() for line in h.splitlines()) + '\n'
    out = ROOT / 'output'
    out.mkdir(exist_ok=True)
    (out / 'sample.html').write_text(h)
    (out / 'sample.txt').write_text(t)
    (out / 'sample.eml').write_text(mime(c, items, groups, flagged, 'fictional-sample').as_string())
    return out


def publish(out):
    from playwright.sync_api import sync_playwright
    docs = ROOT / 'docs'
    for name in ('sample.html', 'sample.txt'):
        shutil.copyfile(out / name, docs / name)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for name, width, height in [('desktop', 1040, 900), ('mobile', 390, 844)]:
                context = browser.new_context(viewport=dict(width=width,height=height),
                                              java_script_enabled=False, offline=True,
                                              service_workers='block', device_scale_factor=1)
                context.route('**/*', lambda route: route.abort())
                page = context.new_page()
                page.set_content((out / 'sample.html').read_text(), wait_until='load')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), name
                assert page.locator('img').count() == 4
                assert page.locator('img').evaluate_all('(imgs) => imgs.every(i => i.complete && i.naturalWidth > 0)')
                page.screenshot(path=str(docs / f'sample-{name}-{NOW:%Y-%m-%d}.png'), full_page=True, animations='disabled')
                context.close()
        finally:
            browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish-docs', action='store_true', help='Update public HTML/text and desktop/mobile screenshots')
    args = parser.parse_args()
    out = build()
    if args.publish_docs:
        publish(out)
    print('Fictional sample: 6 emails, 4 sender thumbnails, 5 original links and unsubscribe controls; no mailbox access.')
    print(ROOT / 'docs/sample.html' if args.publish_docs else out / 'sample.html')
