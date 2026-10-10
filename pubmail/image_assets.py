"""Bounded, pinned-HTTPS image fetches; browser never visits source URLs."""
import base64, hashlib, http.client, ipaddress, json, re, socket, ssl
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl


def eligible(url, policy, attrs=None):
    from .core import host
    h = host(url)
    if not policy.get('enabled') or not h:
        return False
    u = urlsplit(url)
    rules = policy.get('hosts', {})
    rule = rules.get(h)
    if not rule or u.fragment or re.search(r'%(?!(?:20|28|29|7b|7d))', u.path, re.I) or '..' in u.path:
        return False
    if not any(u.path.startswith(p) for p in rule.get('path_prefixes', [])):
        return False
    if any(k not in rule.get('query_keys', []) for k, _ in parse_qsl(u.query, keep_blank_values=True)):
        return False
    for key in ('width', 'height'):
        value = (attrs or {}).get(key, '')
        if re.fullmatch(r'\d+', value) and int(value) < 8:
            return False
    return True


class PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('Nonpublic image address')
        sock = socket.create_connection((addresses[0][4][0], 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch(url, max_bytes=3_000_000):
    from PIL import Image
    u = urlsplit(url)
    conn = PinnedHTTPS(u.hostname, timeout=5, context=ssl.create_default_context())
    try:
        conn.request('GET', u.path + ('?' + u.query if u.query else ''), headers={'Accept':'image/png,image/jpeg,image/webp,image/gif'})
        response = conn.getresponse()
        if response.status != 200 or response.getheader('Content-Type','').split(';')[0] not in ('image/png','image/jpeg','image/webp','image/gif','image/avif'):
            raise ValueError('Not a supported image; redirects are not followed')
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError('Image too large')
        with Image.open(BytesIO(data)) as im:
            if min(im.size) < 8 or im.width * im.height > 16_000_000:
                raise ValueError('Pixel or excessive image dimensions')
            im.seek(0)
            im.thumbnail((1600,1600))
            output=BytesIO(); im.convert('RGB').save(output,format='PNG')
            return output.getvalue()
    finally:
        conn.close()


def assets(markup, c):
    from .io import private_write
    policy=c.get('image_loading', {})
    if not policy.get('enabled'):
        return {}
    from .core import host
    def tracker(url):
        h = host(url)
        return h in c.get('ignored_tracking_domains', []) or any(h.endswith('.'+suffix) for suffix in c.get('ignored_tracking_domain_suffixes', []))
    class Sources(HTMLParser):
        def __init__(self):super().__init__();self.urls=[]
        def handle_starttag(self,tag,attrs):
            d=dict(attrs);url=d.get('src','')
            if tag=='img' and not tracker(url) and eligible(url,policy,d) and url not in self.urls:self.urls.append(url)
    parser=Sources();parser.feed(markup[:200000]);out={}
    strict=c.get('vision',{}).get('enabled',False)
    from .io import Error
    from .io import ProcessingPending
    downloaded = 0
    root=Path(c['state_dir'])/'image-cache';root.mkdir(mode=0o700,exist_ok=True)
    for url in parser.urls:
        path=root/(hashlib.sha256(url.encode()).hexdigest()+'.json')
        if path.exists():
            cached=json.loads(path.read_text())
        else:
            if downloaded >= policy.get('downloads_per_pass', 16):
                raise ProcessingPending('Artwork download pass saved; rerun to resume remaining images')
            downloaded += 1
            try:cached={'data':base64.b64encode(fetch(url, max_bytes=policy.get("max_download_bytes",3_000_000))).decode()}
            except Exception:cached={'data':None}
            private_write(path,json.dumps(cached))
        if cached.get('data'):out[url]='data:image/png;base64,'+cached['data']
        elif strict:raise Error('Approved artwork unavailable; visual evidence incomplete')
    return out
