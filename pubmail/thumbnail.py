"""Raster previews of original email content in an offline, script-free browser."""
from functools import lru_cache
from html import escape
from html.parser import HTMLParser


class Sanitizer(HTMLParser):
    tags = set('div span p br hr table tbody thead tfoot tr td th h1 h2 h3 h4 h5 h6 b strong i em u s ul ol li blockquote pre center font style'.split())
    attrs = set('style class id width height align valign cellpadding cellspacing border colspan rowspan bgcolor color face size'.split())
    blocked = set('script iframe object embed svg math noscript template'.split())

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.depth = 0
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        if tag in self.blocked:
            self.depth += 1
        if self.depth:
            return
        if tag == 'img':
            alt = dict(attrs).get('alt') or 'Image blocked'
            self.parts.append('<span style="display:inline-block;color:#666;font:12px Arial">[' + escape(alt[:150]) + ']</span>')
        elif tag in self.tags:
            safe = ''.join(' ' + k + '="' + escape(v or '', quote=True) + '"' for k, v in attrs if k in self.attrs)
            self.parts.append('<' + tag + safe + '>')
            if tag == 'style':
                self.in_style = True

    def handle_endtag(self, tag):
        if self.depth:
            if tag in self.blocked:
                self.depth -= 1
            return
        if tag in self.tags:
            self.parts.append('</' + tag + '>')
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data if self.in_style else escape(data))


def document(markup, body):
    parser = Sanitizer()
    parser.feed(markup[:200000])
    content = ''.join(parser.parts) if markup else '<pre style="white-space:pre-wrap;font:18px/1.6 Arial">' + escape(body[:24000]) + '</pre>'
    return ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src \'none\'; font-src \'none\'; script-src \'none\'; connect-src \'none\'; frame-src \'none\'; base-uri \'none\'; form-action \'none\'">'
            '</head><body style="margin:16px;background:white">' + content + '</body></html>')


@lru_cache(maxsize=32)
def screenshot(markup, body):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(java_script_enabled=False, offline=True,
                                          service_workers='block', viewport={'width': 640, 'height': 400})
            context.route('**/*', lambda route: route.abort())
            page = context.new_page()
            page.set_default_timeout(10000)
            page.set_content(document(markup, body), wait_until='domcontentloaded')
            return page.screenshot(type='png', animations='disabled', timeout=10000)
        finally:
            browser.close()
