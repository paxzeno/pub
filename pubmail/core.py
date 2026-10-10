from __future__ import annotations
import base64, hashlib, ipaddress, json, re
from datetime import datetime, timedelta
from email.utils import parseaddr
from html.parser import HTMLParser
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from publicsuffix2 import get_sld
from .social import discard, trim_html, trim_text

PROTECTED = re.compile(
    r"\b(invoice|receipt|password|verification|security alert|sign.in|one.time|payment (?:due|failed|received)|order (?:confirmation|confirmed|shipped)|booking|reservation|boarding|refund|appointment|fatura|factura|recibo|palavra.passe|c[oó]digo de|pagamento|encomenda|reserva|consulta|reembolso)\b",
    re.I,
)
PROMO = re.compile(
    r"\b(sale|offers?|discount|newsletter|promo|off|desconto|ofertas?|promoç|novidades)\b",
    re.I,
)


class BodyParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.links = []
        self.image_alts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "img" and not self.hidden:
            alt = (dict(attrs).get("alt") or "").strip()
            if alt:
                self.image_alts.append(alt)
                self.text.append("\n[Image text: " + alt + "]\n")
        if tag == "a":
            v = dict(attrs).get("href", "")
            if v:
                self.links.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("p", "div", "br", "li"):
            self.text.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def domain(address):
    return (
        parseaddr(address)[1].rsplit("@", 1)[-1].lower().rstrip(".")
        if "@" in parseaddr(address)[1]
        else ""
    )


def host(url):
    try:
        p = urlsplit(url)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            return ""
        h = (p.hostname or "").lower().rstrip(".")
        if not h or "." not in h:
            return ""
        try:
            ipaddress.ip_address(h)
            return ""
        except ValueError:
            pass
        return h.encode("idna").decode()
    except (ValueError, UnicodeError):
        return ""


def registered(d):
    return get_sld(d, strict=True) or d


def safe_text(s):
    # Defang URLs and addresses even in text/plain: clients auto-link them.
    s = re.sub(r"https?://", "hxxps[:]//", str(s), flags=re.I)
    return re.sub(r"(?<=\w)\.(?=\w)", "[.]", s.replace("@", " [at] "))


def normalize(raw, body_limit=24000):
    hs = raw.get("payload", {}).get("headers", [])
    headers = {}
    for h in hs:
        headers.setdefault(h["name"].lower(), []).append(h.get("value", ""))

    def first(k):
        return headers.get(k, [""])[0]

    texts = []
    markup = []

    def walk(p):
        mime = p.get("mimeType", "")
        data = p.get("body", {}).get("data")
        if data and mime in ("text/plain", "text/html") and not p.get("filename"):
            s = base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
            (texts if mime == "text/plain" else markup).append(s)
        for part in p.get("parts", []):
            walk(part)

    walk(raw.get("payload", {}))
    sender = parseaddr(first("from"))[1].lower()
    original = parseaddr(first("x-original-from"))[1].lower() or sender
    markup = [trim_html(s, original) for s in markup]
    texts = [trim_text(s, original) for s in texts]
    parser = BodyParser()
    for s in markup:
        parser.feed(s)
    text = "".join(parser.text) if markup else "\n".join(texts)
    links = parser.links if markup else re.findall(r'https?://[^\s<>"\)]+', text)
    unsub = re.findall(r"<(https://[^>]+)>", first("list-unsubscribe"))
    sender = parseaddr(first("from"))[1].lower()
    original = sender
    # Only a hint. Security() must authenticate the forwarding route separately.
    if first("x-original-from"):
        original = parseaddr(first("x-original-from"))[1].lower() or sender
    return dict(
        id=raw["id"],
        thread_id=raw.get("threadId", ""),
        rfc_message_id=first("message-id").strip().strip("<>"),
        labels=raw.get("labelIds", []),
        timestamp=int(raw.get("internalDate", "0")) // 1000,
        sender=sender,
        original_sender=original,
        sender_display=parseaddr(first("from"))[0],
        subject=first("subject"),
        body=text[:body_limit],
        image_alts=list(dict.fromkeys(parser.image_alts)),
        original_html="\n".join(markup)[:200000],
        truncated=len(text) > body_limit,
        links=list(dict.fromkeys(links)),
        unsubscribe=unsub,
        auth=headers.get("authentication-results", []),
        list_id=first("list-id"),
        headers_hash=hashlib.sha256(
            json.dumps(raw.get("payload", {}), sort_keys=True).encode()
        ).hexdigest(),
    )


def security(m, c):
    # Discard configured HTTPS tracking destinations, never treat them as safe links.
    ignored = set(c.get("ignored_tracking_domains", []))
    links = [u for u in m.get("links", []) + m.get("unsubscribe", []) if host(u) not in ignored]
    sender = m["sender"]
    sd = domain(sender)
    original = m["original_sender"]
    od = domain(original)
    relay = sd if sd in c.get("alias_domains", []) else ""
    # Only the first Gmail authentication result is used; never trust a later
    # sender-injected Authentication-Results header. Missing evidence fails closed.
    auth = (m.get("auth") or [""])[0]
    if not re.match(r"^\s*mx\.google\.com\s*;", auth, re.I):
        return "uncertain", "No trusted Gmail authentication result", []
    aligned = False
    for part in auth.split(";")[1:]:
        if re.search(r"\bdmarc=pass\b", part):
            hit = re.search(r"header\.from=([^\s;]+)", part)
            if hit and registered(hit[1].strip('"')) == registered(sd):
                aligned = True
        if re.search(r"\bdkim=pass\b", part):
            hit = re.search(r"header\.(?:d|i)=([^\s;]+)", part)
            if hit and registered(
                hit[1].strip('"').lstrip("@").rsplit("@", 1)[-1]
            ) == registered(sd):
                aligned = True
    if not aligned:
        return (
            "uncertain",
            "Original/forwarding sender authentication not established",
            [],
        )
    ex = next(
        (
            x
            for x in c.get("security_exceptions", [])
            if x.get("sender") == original
            and x.get("relay_domain", "") == relay
            and x.get("reason")
        ),
        None,
    )
    if relay and not ex:
        return (
            "uncertain",
            f"Forwarding route {relay} authenticated; original sender {original} needs attribution. Link hosts: {', '.join(sorted({host(u) for u in links if host(u) and not discard(u, original)})) or 'none'}. Forwarding itself is not a link mismatch.",
            [],
        )
    if relay:
        expected = (ex or {}).get("original_domain", od if original != sender else "")
        if not expected:
            return "uncertain", "Original domain missing from relay exception", []
        # Gmail-validated ARC can preserve original domain authentication across
        # a rewriting relay. Alias local-parts are never decoded as identity proof.
        arc = next(
            (part for part in auth.split(";") if re.search(r"\barc=pass\b", part)), ""
        )
        origins = re.findall(r"fromdomain=([^\s;)]+)", arc)
        if not ex.get("operator_verified_original", False) and (
            not expected
            or not re.search(r"\bdmarc=pass\b", arc)
            or not any(registered(x) == registered(expected) for x in origins)
        ):
            return (
                "uncertain",
                "Relay authenticated but original domain lacks matching ARC evidence",
                [],
            )
        od = expected
    if not relay and original != sender:
        return "uncertain", "Unverified original-sender header", []
    for brand, domains in c.get("brands", {}).items():
        if (
            re.search(
                r"\b" + re.escape(brand) + r"\b", m.get("sender_display", ""), re.I
            )
            and registered(od) not in domains
        ):
            return "suspicious", "Display-name brand and sender domain disagree", []
    allowed = set(ex.get("link_domains", []) if ex else [])
    safe = []
    for url in links:
        if discard(url, original):
            continue
        h = host(url)
        if not h:
            try:
                parsed = urlsplit(url)
                port = parsed.port
            except ValueError:
                return "uncertain", "Malformed URL", []
            # Scoped omissions: never returned as renderable/unsubscribe URLs.
            if ex and parsed.scheme == "mailto" and ex.get("omit_mailto"):
                continue
            if ex and parsed.scheme == "http" and parsed.hostname in ex.get("omit_http_domains", []) and not parsed.username and not parsed.password and port in (None, 80):
                continue
            return "uncertain", "Link is non-HTTPS, malformed, or uses an unsupported scheme; not a sender-authentication failure", []
        if registered(h) != registered(od) and h not in allowed:
            return (
                "uncertain",
                f"Sender domain: {od}; authenticated route: {relay or sd}; differing link hosts: {', '.join(sorted({host(u) for u in links if host(u) and not discard(u, original) and registered(host(u)) != registered(od) and host(u) not in allowed}))}. Expected sender domain or configured exact service hosts: {', '.join(sorted({od} | allowed))}. These are link-host differences, not evidence that forwarding failed.",
                [],
            )
        safe.append(url)
    reason = "Authenticated relay; operator-vouched original sender and permitted HTTPS domains" if relay and ex.get("operator_verified_original") else "Aligned sender and permitted HTTPS link domains"
    return "verified", reason, safe


def preclassify(m, c):
    w = c.get("whitelist", {})
    if (
        m["sender"] in w.get("addresses", [])
        or m["original_sender"] in w.get("addresses", [])
        or domain(m["sender"]) in w.get("domains", [])
    ):
        return "keep", "Whitelist"
    if m.get("truncated"):
        return "keep", "Body exceeds review limit"
    if PROTECTED.search(m["subject"] + "\n" + m["body"]):
        return "keep", "Protected transactional/security content"
    for r in c.get("advertising", []):
        if r.get("sender") == m["original_sender"] and re.search(
            r["subject_regex"], m["subject"]
        ):
            return "advertising", "Explicit sender and subject rule"
    if (
        m.get("list_id")
        or m.get("unsubscribe")
        or "CATEGORY_PROMOTIONS" in m["labels"]
        or PROMO.search(m["subject"])
    ):
        return "candidate", "Needs content classification"
    return "keep", "No promotional evidence"


def week_bounds(timestamp, tz):
    d = datetime.fromtimestamp(timestamp, ZoneInfo(tz))
    start = d.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=d.weekday()
    )
    return int(start.timestamp()), int((start + timedelta(days=7)).timestamp())


def topic_key(title):
    s = re.sub(r"\s+", " ", title.casefold()).strip()
    return s or "untitled"
