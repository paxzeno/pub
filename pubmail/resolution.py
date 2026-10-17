"""Bounded synchronous senior repairs; proposals are never approvals by themselves."""
import hashlib,json,re,ssl
from functools import lru_cache
from urllib.parse import urlsplit,urljoin
from html.parser import HTMLParser
from .io import Error,policy_hash


def repair_reviews(c,store,ids,validators,job='review_resolution_v1'):
    """One repair receipt per exact task set, including across resume passes."""
    from .automation import setup,notify
    setup(store)
    receipt=notify(c,store,job,'senior_attention',ids) or {}
    rows=receipt.get('resolutions',[])
    if not isinstance(rows,list):rows=[]
    # Reject duplicate/foreign IDs; an acknowledgement without decisions repairs nothing.
    keys=[r.get('id') for r in rows if isinstance(r,dict)]
    if len(keys)!=len(rows) or any(not isinstance(k,str) for k in keys) or len(set(keys))!=len(keys) or set(keys)-set(ids):rows=[]
    outcomes={r['id']:r for r in rows}
    from .diagnostics import failure_details
    for ident,validator in zip(ids,validators):
        row=outcomes.get(ident)
        if not row:continue
        try:
            if row.get('status')=='resolved':
                if not isinstance(row.get('output'),dict):raise Error('Invalid synchronous correction')
                validator(row['output'])
            elif row.get('status') not in ('defer','needs_owner'):raise Error('Invalid synchronous correction')
            if not isinstance(row.get('reason'),str) or not 1<=len(row['reason'])<=2000:raise Error('Invalid synchronous correction')
            store.db.execute('UPDATE senior_items SET status=?,result=? WHERE id=?',
                (row['status'],json.dumps({**row,'synchronous_repair':True}),ident))
        except (Error,ValueError,TypeError,KeyError) as exc:
            store.db.execute("UPDATE senior_items SET status='failed',result=? WHERE id=?",
                (json.dumps({'id':ident,'status':'failed','error':failure_details(exc,'synchronous_repair')}),ident))
    store.db.commit()


@lru_cache(maxsize=128)
def public_page_images(url):
    """Independent bounded HTTPS evidence, no cookies, redirects or browser execution."""
    from .image_assets import PinnedHTTPS
    u=urlsplit(url);conn=PinnedHTTPS(u.hostname,timeout=5,context=ssl.create_default_context())
    try:
        conn.request('GET',u.path or '/',headers={'Accept':'text/html'})
        response=conn.getresponse()
        if response.status!=200 or response.getheader('Content-Type','').split(';')[0] not in ('text/html','application/xhtml+xml'):
            raise Error('Image provider evidence page unavailable')
        body=response.read(524289)
        if len(body)>524288:raise Error('Image provider evidence page too large')
        images=[]
        class Scan(HTMLParser):
            def handle_starttag(self,tag,attrs):
                if tag=='img':
                    data=dict(attrs)
                    for key in ('src','data-src'):
                        if data.get(key):images.append(urljoin(url,data[key]))
        Scan().feed(body.decode('utf-8',errors='replace'))
        return tuple(images)
    except (OSError,ValueError) as exc:
        raise Error('Image provider evidence page unavailable') from exc
    finally:conn.close()


def validate_image_decision(m,locations,output):
    """Exact static assets only; third-party relationships need independently fetched first-party evidence."""
    from .core import domain,registered,host
    sender=m.get('original_sender',m.get('sender','')).strip().casefold()
    approved=output.get('approved_locations')
    if not isinstance(approved,list) or any(type(i) is not int for i in approved) or len(approved)!=len(locations) or set(approved)!=set(range(len(locations))):
        raise Error('Senior image decision did not cover all locations')
    hosts={}
    evidence=output.get('evidence_urls',{})
    if not isinstance(evidence,dict) or len(evidence)>8:raise Error('Invalid image provider evidence')
    for loc in locations:
        h=loc['host'];path=loc['path']
        if not domain(sender):raise Error('Image provider relationship needs independently vetted rules')
        if (loc.get('query_keys') or not path.startswith('/') or len(path)>=1000
            or not re.search(r'\.(png|jpe?g|gif|webp|avif)$',path,re.I)
            or '..' in path or '\\' in path or '%' in path
            or host('https://'+h+path)!=h):
            raise Error('Image location is not a query-free static asset')
        if registered(h)!=registered(domain(sender)):
            url=evidence.get(h,'')
            if not isinstance(url,str):raise Error('Invalid image provider evidence')
            u=urlsplit(url)
            if (not host(url) or registered(host(url))!=registered(domain(sender)) or u.query or u.fragment
                or '%' in u.path or '..' in u.path
                or re.search(r'login|logout|unsubscribe|account|token|password|checkout',u.path,re.I)):
                raise Error('Image provider relationship lacks first-party public evidence')
            if 'https://'+h+path not in public_page_images(url):
                raise Error('Image provider relationship not confirmed by public evidence')
        rule=hosts.setdefault(h,{'exact_paths':[],'path_prefixes':[],'query_keys':[]})
        rule['exact_paths'].append(path)
    return hosts


def resolve_image_locations(m,c,reviewer,locations):
    from .core import security
    if reviewer is None or not c.get('automation',{}).get('enabled') or security(m,c)[0]!='verified':
        raise Error('Synchronous image review unavailable; source held')
    task={'reason':'image_location_resolution',
          'prompt':'Resolve each image location. Return {"approved_locations":[zero-based indices],"evidence_urls":{"third-party-host":"https://sender-domain/public-page"}} only if ALL are defensible query-free static raster images. First-party means same registrable domain as verified sender. For third-party images provide a public first-party HTML page whose img src or data-src references the EXACT image URL; the application fetches this page independently over pinned public HTTPS, without redirects, queries or cookies. No shared CDN ownership guesses, query permissions, wildcards or blanket domains. If evidence is unavailable return defer with the specific missing evidence; needs_owner only for a genuine owner decision. A prose acknowledgement is not a resolution. The application independently validates all constraints and grants only exact-source asset paths; no persistent rules are changed.',
          'data':{'sender':m.get('original_sender',m['sender']),'source_hash':m['headers_hash'],'locations':locations}}
    encoded=json.dumps(task,sort_keys=True)
    ident=hashlib.sha256(('image-resolution-v1'+policy_hash(c)+encoded).encode()).hexdigest()
    db=reviewer.store.db
    db.execute('INSERT OR IGNORE INTO senior_items(id,policy,task,status) VALUES(?,?,?,?)',
               (ident,policy_hash(c),encoded,'pending'));db.commit()
    validator=lambda output:validate_image_decision(m,locations,output)
    status,result=db.execute('SELECT status,result FROM senior_items WHERE id=?',(ident,)).fetchone()
    if status=='pending':
        repair_reviews(c,reviewer.store,[ident],[validator],job='image_resolution_v1')
        status,result=db.execute('SELECT status,result FROM senior_items WHERE id=?',(ident,)).fetchone()
    if status!='resolved':
        if result:
            saved=json.loads(result)
            if saved.get('error',{}).get('chain'):
                message=saved['error']['chain'][0]['message']
                from .diagnostics import SAFE_MESSAGES
                if message in SAFE_MESSAGES:raise Error(message)
        if status in ('defer','needs_owner'):raise Error('Image source held: independent provider evidence missing')
        raise Error('Senior image resolution incomplete; source held')
    output=json.loads(result)['output'];hosts=validator(output)
    return {'policy':policy_hash(c),'sender':task['data']['sender'],'source_hash':m['headers_hash'],'locations':locations,'output':output,'hosts':hosts}
