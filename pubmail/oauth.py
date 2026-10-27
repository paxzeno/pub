"""Private gog-owned OAuth handshake; never construct an unbound consent URL."""
import json
import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .io import Error, private_write, run


def recovery_url(c, env):
    path = Path(c['state_dir']) / 'oauth-recovery.json'
    try:
        cached = json.loads(path.read_text())
        if cached['expires'] > time.time() and cached['account'] == c['account'] and cached['client'] == c['client']:
            return checked_url(cached['url'])
    except (OSError, ValueError, KeyError, TypeError, Error):
        pass
    # Current gog no longer has gmail-scope=modify. Request readonly plus the
    # required modify scope explicitly, never the full-mail/delete scope.
    output = run(['gog', '--client', c['client'], '--json', '--no-input',
                  'auth', 'add', c['account'], '--services', 'gmail',
                  '--gmail-scope', 'readonly', '--extra-scopes',
                  'https://www.googleapis.com/auth/gmail.modify',
                  '--remote', '--step', '1', '--timeout', '1h'], env=env)
    try:
        data = json.loads(output)
        url = checked_url(data.get('auth_url') or data.get('url') or data.get('authorization_url'))
    except (ValueError, AttributeError, TypeError):
        raise Error('OAuth recovery response invalid') from None
    private_write(path, json.dumps({'url': url, 'account': c['account'],
                                   'client': c['client'], 'expires': time.time() + 3000}))
    return url


def checked_url(url):
    if not isinstance(url, str) or any(ch.isspace() for ch in url):
        raise Error('OAuth recovery URL invalid')
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc != 'accounts.google.com' or not p.path.endswith('/auth'):
        raise Error('OAuth recovery URL invalid')
    q = parse_qs(p.query)
    if not all(q.get(k) for k in ('state', 'client_id', 'redirect_uri')):
        raise Error('OAuth recovery URL missing handshake state')
    return url
