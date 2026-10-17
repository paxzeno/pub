"""Bounded, pinned-HTTPS image fetches; browser never visits source URLs."""
import base64, hashlib, http.client, ipaddress, json, re, socket, ssl, subprocess, os, time, uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, unquote


def eligible(url, policy, attrs=None):
    from .core import host
    h = host(url)
    if not policy.get('enabled') or not h:
        return False
    u = urlsplit(url)
    if policy.get('mode') == 'public_https':
        if u.fragment or len(url)>4096 or any(ord(ch)<32 for ch in url):return False
        if re.search(r'(?:^|[/_.-])(pixel|tracking|beacon|unsubscribe|logout|delete)(?:[/_.?-]|$)',unquote(unquote(u.path)),re.I):return False
        return not any(re.fullmatch(r'\d+', (attrs or {}).get(k,'')) and int((attrs or {})[k])<8 for k in ('width','height'))
    rules = policy.get('hosts', {})
    rule = rules.get(h)
    if not rule or u.fragment or re.search(r'%(?!(?:20|28|29|7b|7d))', u.path, re.I) or '..' in u.path or '\\' in u.path:
        return False
    if u.path not in rule.get('exact_paths',[]) and not any(u.path.startswith(p) for p in rule.get('path_prefixes', [])):
        return False
    timestamp_query=rule.get('allow_timestamp_query',False) and re.fullmatch(r'[0-9]{10}',u.query)
    if not timestamp_query and any(k not in rule.get('query_keys', []) for k, _ in parse_qsl(u.query, keep_blank_values=True)):
        return False
    for key in ('width', 'height'):
        value = (attrs or {}).get(key, '')
        if re.fullmatch(r'\d+', value) and int(value) < 8:
            return False
    return True


class PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global or ipaddress.ip_address(a[4][0]).is_multicast for a in addresses):
            raise ValueError('Nonpublic image address')
        sock = socket.create_connection((addresses[0][4][0], 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def decode_isolated(data):
    """OS namespaces: no network, home, mail state or credentials; read-only runtime only."""
    name='pubmail-decode-'+uuid.uuid4().hex
    argv=['docker','run','--name',name,'--rm','-i','--network=none','--read-only',
          '--cap-drop=ALL','--security-opt=no-new-privileges',
          '--memory=512m','--memory-swap=512m','--pids-limit=16',
          '--user=65534:65534','--log-driver=none','pubmail-image-decoder:1']
    try:
        result=subprocess.run(argv,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              env={'PATH':'/usr/bin:/bin'},timeout=20)
    except subprocess.TimeoutExpired:
        subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                       env={'PATH':'/usr/bin:/bin'},timeout=5)
        raise ValueError('Isolated image decoding timed out')
    if result.returncode or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Isolated image decoding failed')
    return result.stdout


def fetch(url, max_bytes=3_000_000):
    from .core import host
    if not host(url):raise ValueError('Invalid public HTTPS image URL')
    u = urlsplit(url)
    conn = PinnedHTTPS(u.hostname, timeout=5, context=ssl.create_default_context())
    try:
        conn.request('GET', (u.path or '/') + ('?' + u.query if u.query else ''), headers={'Accept':'image/*'})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError('Image unavailable; redirects are not followed')
        # MIME and filename are hints, not proof: decoder checks the actual bytes.
        chunks=[];size=0;deadline=time.monotonic()+10
        while size<=max_bytes:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ValueError('Image download timed out')
            if conn.sock:conn.sock.settimeout(min(5,remaining))
            part=response.read1(min(65536,max_bytes+1-size))
            if not part:break
            chunks.append(part);size+=len(part)
        if size > max_bytes:raise ValueError('Image too large')
        data=b''.join(chunks)
        return decode_isolated(data)
    finally:
        conn.close()


def source_config(m, c):
    """Sender-specific scopes require existing source authentication, never display-name trust."""
    from .core import security
    policy=c.get('image_loading',{})
    if policy.get('mode')=='public_https':
        return {**c,'image_loading':{**policy,'enabled':bool(policy.get('enabled') and security(m,c)[0]=='verified')}}
    sender=m.get('original_sender',m.get('sender','')).strip().casefold()
    scopes=policy.get('sender_hosts',{})
    hosts=dict(scopes.get(sender,policy.get('hosts',{})))
    if sender in scopes and security(m,c)[0]!='verified':hosts={}
    from .io import policy_hash
    proof=m.get('_image_resolution')
    if proof and proof.get('policy')==policy_hash(c) and proof.get('sender')==sender and proof.get('source_hash')==m.get('headers_hash') and security(m,c)[0]=='verified':
        from .resolution import validate_image_decision
        for h,rule in validate_image_decision(m,proof['locations'],proof['output']).items():
            existing=hosts.get(h,{})
            hosts[h]={**existing,'exact_paths':list(set(existing.get('exact_paths',[])+rule['exact_paths']))}
    return {**c,'image_loading':{**policy,'hosts':hosts}}


def missing_locations(markup, c):
    """Metadata only; never fetch rejected URLs or retain query values."""
    from .core import host
    policy=c.get('image_loading',{})
    if not policy.get('enabled'):return []
    result=[]
    class Scan(HTMLParser):
        def handle_starttag(self,tag,attrs):
            if tag!='img':return
            attrs=dict(attrs);url=attrs.get('src','');h=host(url)
            if not h:return
            if h in c.get('ignored_tracking_domains',[]) or any(h.endswith('.'+x) for x in c.get('ignored_tracking_domain_suffixes',[])):return
            if any(re.fullmatch(r'\d+',attrs.get(k,'')) and int(attrs[k])<8 for k in ('width','height')):return
            if eligible(url,policy,attrs):return
            u=urlsplit(url);rule=policy.get('hosts',{}).get(h)
            reason='unknown_host' if not rule else 'path_or_query_not_permitted'
            entry={'host':h,'path':u.path[:1000],'query_keys':sorted({k for k,v in parse_qsl(u.query,keep_blank_values=True)}),'reason':reason}
            if entry not in result and len(result)<32:result.append(entry)
    Scan().feed(markup[:200000])
    return result


def assets(markup, c, *, cache_only=False):
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
    strict=c.get('vision',{}).get('enabled',False) and policy.get('mode')!='public_https'
    from .io import Error
    from .io import ProcessingPending
    downloaded = 0
    root=Path(c['state_dir'])/'image-cache';root.mkdir(mode=0o700,exist_ok=True)
    for url in parser.urls:
        path=root/(hashlib.sha256(url.encode()).hexdigest()+'.json')
        cached=json.loads(path.read_text()) if path.exists() else {}
        if not cached.get('data') and not cache_only and (not cached.get('at') or time.time()-cached['at']>3600):
            if downloaded >= policy.get('downloads_per_pass', 16):
                raise ProcessingPending('Artwork download pass saved; rerun to resume remaining images')
            downloaded += 1
            try:cached={'data':base64.b64encode(fetch(url, max_bytes=policy.get("max_download_bytes",3_000_000))).decode()}
            except Exception:cached={'data':None,'at':time.time(),'error':'Image fetch or decode failed'}
            private_write(path,json.dumps(cached))
        if cached.get('data'):out[url]='data:image/png;base64,'+cached['data']
        elif strict:raise Error('Approved artwork unavailable; visual evidence incomplete')
    return out
