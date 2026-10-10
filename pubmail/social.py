"""Remove unused social links; never treat lookalike domains as social hosts."""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

PLATFORMS = (
    ('facebook.com', 'fb.com'), ('instagram.com',), ('linkedin.com',),
    ('youtube.com', 'youtu.be'), ('tiktok.com',), ('twitter.com', 'x.com', 't.co'),
    ('pinterest.com', 'pin.it'), ('threads.net', 'threads.com'),
    ('reddit.com', 'redd.it'), ('snapchat.com',), ('bsky.app',),
)


def belongs(host, domains):
    return any(host == d or host.endswith('.' + d) for d in domains)


def discard(url, sender):
    try:
        host = (urlsplit(url).hostname or '').lower().rstrip('.')
    except ValueError:
        return False  # Let security reject malformed URLs, never silently exempt them.
    origin = sender.rsplit('@', 1)[-1].lower().rstrip('.')
    return any(belongs(host, group) and not belongs(origin, group) for group in PLATFORMS)


def trim_text(text, sender):
    return re.sub(r'https?://[^\s<>"\)]+', lambda m: '' if discard(m[0], sender) else m[0], text)


class TrimHTML(HTMLParser):
    def __init__(self, sender):
        super().__init__(convert_charrefs=False)
        self.sender, self.parts, self.skip = sender, [], 0

    def handle_starttag(self, tag, attrs):
        if tag == 'a' and (self.skip or discard(dict(attrs).get('href', ''), self.sender)):
            self.skip += 1
        if not self.skip:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.skip:
            if tag == 'a':
                self.skip -= 1
        else:
            self.parts.append('</' + tag + '>')

    def handle_startendtag(self, tag, attrs):
        if not self.skip:
            self.parts.append(self.get_starttag_text())

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(trim_text(data, self.sender))

    def handle_entityref(self, name):
        if not self.skip:
            self.parts.append('&' + name + ';')

    def handle_charref(self, name):
        if not self.skip:
            self.parts.append('&#' + name + ';')


def trim_html(markup, sender):
    p = TrimHTML(sender)
    p.feed(markup)
    return ''.join(p.parts)
