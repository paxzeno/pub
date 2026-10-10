from __future__ import annotations
import base64, hashlib, json, uuid
from datetime import datetime, date
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate
from zoneinfo import ZoneInfo
from jinja2 import Environment, PackageLoader, select_autoescape
from .core import normalize, security, safe_text
from .io import Error, ProcessingPending, private_write, run


def summary_blocks(summary):
    """Email-safe list structure; no dependence on CSS whitespace preservation."""
    import re
    lines = [s.strip() for s in summary.splitlines() if s.strip()]
    blocks = []
    for line in lines:
        match = re.match(r"^(?:[•*-]|\d+[.)])\s+(.+)$", line)
        if match:
            title, sep, detail = match[1].partition(" — ")
            blocks.append({"bullet": True, "title": title if sep else "", "text": detail if sep else title})
        else:
            blocks.append({"bullet": False, "title": "", "text": line})
    return blocks


def render(c, items, groups, flagged, now=None, inline=False):
    now = now or datetime.now(ZoneInfo(c["timezone"]))
    lookup = {i["id"]: i for i in items}
    # Topic groups determine ordering, not visual card boundaries. Each verified
    # original sender gets one card; keep every source as a separate entry.
    flat = [mid for group in groups for mid in group]
    if sorted(flat) != sorted(lookup) or len(lookup) != len(items):
        raise Error("Rendering groups omitted, invented or repeated messages")
    sender_groups = {}
    for mid in flat:
        sender = lookup[mid]["message"].get("original_sender", "").strip().casefold()
        sender_groups.setdefault(sender or mid, []).append(mid)
    groups = list(sender_groups.values())
    cards = []
    images = {}
    text = [c["newsletter"]["subject"], now.strftime("%d %B %Y"), ""]
    for n, g in enumerate(groups):
        entries = []
        title = lookup[g[0]]["message"]["original_sender"] if len(g) > 1 else lookup[g[0]]["title"]
        text += ["## " + title, ""]
        for mid in g:
            i = lookup[mid]
            m = i["message"]
            deadline = i.get("deadline")
            expired = False
            display = ""
            if deadline:
                dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                expired = dt < now
                display = dt.astimezone(ZoneInfo(c["timezone"])).strftime(
                    "%d %b %Y, %H:%M %Z"
                )
            if not deadline and i.get("deadline_date"):
                day = date.fromisoformat(i["deadline_date"])
                expired = day < now.astimezone(ZoneInfo(c["timezone"])).date()
                display = day.strftime("%d %b %Y") + " (time not supplied)"
                deadline = i["deadline_date"]
            from .timing import extract_event_timing
            event = extract_event_timing(m.get("body", ""), m.get("subject", ""))
            event_display = ""
            event_status = ""
            if event:
                first, last = date.fromisoformat(event["start"]), date.fromisoformat(event["end"])
                today = now.astimezone(ZoneInfo(c["timezone"])).date()
                event_status = "ENDED" if last < today else "UPCOMING" if first > today else "ONGOING"
                event_display = first.strftime("%d %b %Y") + " – " + last.strftime("%d %b %Y") + " (times not supplied)"
            relative_notice = ""
            if not deadline and not event:
                import re
                match = re.search(r"(?:s[oó]\s+)?este fim[ -]de[ -]semana|this weekend|today only|s[oó] hoje", m.get('subject','')+' '+m.get('body',''), re.I)
                if match:
                    received = datetime.fromtimestamp(m['timestamp'], ZoneInfo(c['timezone'])).strftime('%d %b %Y')
                    relative_notice = '“'+match[0]+'” — source email '+received+'; exact cutoff not supplied.'
            if not deadline and not event and not relative_notice:
                from .timing import unresolved_timing_notice
                relative_notice = unresolved_timing_notice(m.get('body',''), m.get('subject',''))
            unsub = next(
                (u for u in m.get("unsubscribe", []) if u in i.get("safe_urls", [])),
                None,
            )
            if not unsub:
                from .core import unsubscribe_control
                unsub = unsubscribe_control(m, c)
            # This is our Gmail link, not a link supplied in the email.
            from urllib.parse import quote
            rfc_id = m.get("rfc_message_id", "")
            if rfc_id and not any(ch.isspace() for ch in rfc_id):
                original = "https://mail.google.com/mail/u/?authuser=" + quote(c["account"], safe="") + "#search/" + quote("rfc822msgid:" + rfc_id, safe="")
            else:
                original = "https://mail.google.com/mail/u/?authuser=" + quote(c["account"], safe="") + "#all/" + quote(m.get("thread_id") or m["id"], safe="")
            entries.append(
                dict(
                    title=i["title"],
                    summary=i["summary"],
                    summary_blocks=summary_blocks(i["summary"]),
                    deadline=deadline,
                    expired=expired,
                    deadline_display=display,
                    event_status=event_status,
                    event_display=event_display,
                    relative_notice=relative_notice,
                    sender=m["original_sender"],
                    original_url=original,
                    unsubscribe=unsub,
                )
            )
            if len(g) > 1:
                text += ["### " + i["title"]]
            text += [i["summary"]]
            if relative_notice:
                text += ["TIME-SENSITIVE: " + relative_notice]
            if event:
                text += ["EVENT " + event_status + ": " + event_display]
            if deadline:
                text += [("EXPIRED" if expired else "DEADLINE") + ": " + display]
            text += ["From: " + m["original_sender"], "Original: " + original]
            if unsub:
                text += ["Unsubscribe: " + unsub]
            text += [""]
        from .thumbnail import screenshot

        original = lookup[g[0]]["message"]
        from .image_assets import assets
        image_entries = tuple(assets(original.get("original_html", ""), c).items())
        data = screenshot(original.get("original_html", ""), original.get("body", ""), image_entries)
        cid = f"topic-{n}@pubmail"
        images[cid] = data
        thumbnail = (
            ("data:image/png;base64," + base64.b64encode(data).decode())
            if inline
            else "cid:" + cid
        )
        cards.append(
            dict(title=title, items=entries, sources=len(entries), thumbnail=thumbnail)
        )
    suspicious = []
    if flagged:
        text += ["## SET ASIDE FOR YOUR REVIEW (no active links)", ""]
    for i in flagged:
        m = i["message"]
        f = dict(
            title=safe_text(i["title"]),
            summary=safe_text(i["summary"]),
            sender=safe_text(m["original_sender"]),
            received=datetime.fromtimestamp(
                m["timestamp"], ZoneInfo(c["timezone"])
            ).isoformat(),
            reason=safe_text(i["security_reason"]),
            id=m["id"],
        )
        suspicious.append(f)
        text += [
            f["title"],
            f["summary"],
            "Sender: " + f["sender"],
            "Received: " + f["received"],
            "Reason: " + f["reason"],
            "Original Gmail message ID: " + f["id"],
            "",
        ]
    env = Environment(
        loader=PackageLoader("pubmail", "templates"),
        autoescape=select_autoescape(["html"]),
    )
    html = env.get_template("newsletter.html").render(
        title=c["newsletter"]["subject"],
        date=now.strftime("%d %B %Y"),
        count=len(items) + len(flagged),
        cards=cards,
        suspicious=suspicious,
    )
    return html, "\n".join(text), images


def mime(c, items, groups, flagged, id):
    h, t, images = render(c, items, groups, flagged)
    n = c["newsletter"]
    msg = EmailMessage(policy=SMTP)
    msg["From"] = n["sender"]
    msg["To"] = n["recipient"]
    msg["Subject"] = n["subject"]
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = f"<pub-{id}@{n['sender'].split('@')[-1]}>"
    fmt = n["format"]
    if fmt == "text":
        msg.set_content(t)
    elif fmt == "html":
        msg.set_content(h, subtype="html")
    else:
        msg.set_content(t)
        msg.add_alternative(h, subtype="html")
    if fmt != "text":
        part = msg if fmt == "html" else msg.get_payload()[-1]
        for cid, data in images.items():
            part.add_related(
                data,
                maintype="image",
                subtype="png",
                cid=f"<{cid}>",
                filename="topic.png",
                disposition="inline",
            )
    return msg


def prepare(gmail, c, model, store):
    labels = gmail.labels()
    ads = labels.get(c["labels"]["ads"])
    done = labels.get(c["labels"]["newsletter"])
    items = []
    flagged = []
    if ads:
        rows, more = gmail.search(
            f"label:{c['labels']['ads']} -label:{c['labels']['newsletter']} -in:spam -in:trash",
            c["limits"]["digest_messages"],
        )
        if more:
            raise Error(
                "Digest exceeds configured bound; create reviewed catch-up volumes first"
            )
    else:
        rows = []
    ids = {r["id"] for r in rows}
    for key, body in store.db.execute(
        "SELECT key,value FROM meta WHERE key LIKE 'review:%'"
    ):
        id = key.removeprefix("review:")
        if id not in ids:
            rows.append({"id": id})
            ids.add(id)
    if len(rows) > c["limits"]["digest_messages"]:
        raise Error("Too many digest messages")
    delivered = set()
    for (body,) in store.db.execute(
        "SELECT body FROM deliveries WHERE status IN ('sent','complete')"
    ):
        delivered.update(json.loads(body)["ids"])
    for row in rows:
        if row["id"] in delivered:
            continue
        m = normalize(gmail.raw(row["id"]), c["limits"]["body_characters"])
        if done and done in m["labels"] or {"SPAM", "TRASH"} & set(m["labels"]):
            continue
        sec, reason, urls = security(m, c)
        d = store.cached(m, c) or {
            "title": m["subject"],
            "summary": "Message awaiting review.",
            "topic": m["subject"],
            "deadline": None,
        }
        try:
            result = model.classify(m)
            d.update(
                {
                    k: result.get(k)
                    for k in (
                        "title",
                        "summary",
                        "topic",
                        "deadline",
                        "deadline_evidence",
                        "deadline_date",
                    )
                }
            )
        except ProcessingPending:
            raise
        except Error:
            # No false "digested" marking when summarization failed.
            raise Error("Digest summarization failed; nothing sent or marked")
        d.update(
            id=m["id"], message=m, security=sec, security_reason=reason, safe_urls=urls
        )
        (items if sec == "verified" else flagged).append(d)
    if not items and not flagged:
        return None
    # Sender grouping is deterministic in render; no semantic-model call needed.
    groups = [[i["id"]] for i in items]
    id = str(uuid.uuid4())
    p = {
        "id": id,
        "items": items,
        "groups": groups,
        "flagged": flagged,
        "ids": [i["id"] for i in items + flagged],
    }
    h, t, _ = render(c, items, groups, flagged, inline=True)
    private_write(store.root / "digests" / f"{id}.html", h)
    private_write(store.root / "digests" / f"{id}.txt", t)
    private_write(
        store.root / "digests" / f"{id}.eml",
        mime(c, items, groups, flagged, id).as_string(),
    )
    p["mime_sha256"] = hashlib.sha256(
        (store.root / "digests" / f"{id}.eml").read_bytes()
    ).hexdigest()
    p["config_hash"] = hashlib.sha256(
        json.dumps(c, sort_keys=True).encode()
    ).hexdigest()
    store.delivery(id, "preview", p)
    return p


def finish_labels(gmail, c, store, id, p):
    done = gmail.labels(create=True)[c["labels"]["newsletter"]]
    for mid in p["ids"]:
        gmail.modify(mid, add=[done])
        store.db.execute("DELETE FROM meta WHERE key=?", ("review:" + mid,))
        store.db.commit()
    store.delivery(id, "complete", p)


def send(gmail, c, store, id):
    unresolved = store.db.execute(
        "SELECT id FROM deliveries WHERE status IN ('sending','ambiguous','sent') AND id<>?",
        (id,),
    ).fetchall()
    if unresolved:
        raise Error("Resolve prior delivery before any new send")
    row = store.db.execute(
        "SELECT status,body FROM deliveries WHERE id=?", (id,)
    ).fetchone()
    if not row:
        raise Error("Unknown digest preview")
    status, body = row
    p = json.loads(body)
    if status == "complete":
        return {"already_complete": id}
    if status == "sent":
        finish_labels(gmail, c, store, id, p)
        return {"label_recovery_complete": id}
    if status != "preview":
        raise Error(
            "Delivery ambiguous; inspect Sent before explicit reconciliation. Never auto-retry."
        )
    if (
        p["config_hash"]
        != hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()
    ):
        raise Error("Configuration changed; regenerate preview")
    done = gmail.labels().get(c["labels"]["newsletter"])
    for i in p["items"] + p["flagged"]:
        m = normalize(gmail.raw(i["id"]), c["limits"]["body_characters"])
        if (
            (done and done in m["labels"])
            or {"SPAM", "TRASH"} & set(m["labels"])
            or m["headers_hash"] != i["message"]["headers_hash"]
        ):
            raise Error("Digest source changed or already included; regenerate preview")
    file = store.root / "digests" / f"{id}.eml"
    if hashlib.sha256(file.read_bytes()).hexdigest() != p["mime_sha256"]:
        raise Error("Preview MIME changed; regenerate")
    store.delivery(id, "sending", p)
    try:
        n = c["newsletter"]
        run(
            [
                "himalaya",
                "message",
                "send",
                "--account",
                n["himalaya_account"],
                "--save",
                n["sent_mailbox"],
                "--json",
            ],
            input=file.read_text(),
            timeout=120,
        )
    except Error:
        store.delivery(id, "ambiguous", p)
        raise Error(
            "Possible SMTP acceptance; stopped. Check Sent and reconcile; do not resend automatically."
        )
    store.delivery(id, "sent", p)
    finish_labels(gmail, c, store, id, p)
    return {"sent": id, "messages": len(p["ids"])}


def preview_plan(c, model, store, plan_id):
    """Visual rehearsal of proposed changes. Not a sendable delivery record."""
    row = store.db.execute("SELECT body FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        raise Error("Unknown plan")
    p = json.loads(row[0])
    candidates = [dict(d) for d in p['decisions'] if d['action'] in ('archive','review')]
    items = [d for d in candidates if security(d['message'],c)[0] == 'verified']
    from .vision import enrich
    pending = []
    for item in items:
        try:
            item['message'] = enrich(item['message'], c)
        except ProcessingPending as exc:
            pending.append(str(exc))
    if pending:
        raise ProcessingPending('; '.join(pending))
    for item in items:
        result = model.classify(item['message'])
        item.update({key: result.get(key) for key in (
            'title', 'summary', 'topic', 'deadline', 'deadline_date', 'deadline_evidence')})
        sec, reason, urls = security(item['message'], c)
        if sec != 'verified':
            raise Error('Preview source security changed; generate a fresh plan')
        item.update(security=sec, security_reason=reason, safe_urls=urls)
    flagged = [d for d in candidates if security(d['message'],c)[0] != 'verified']
    for item in flagged:
        sec, reason, urls = security(item['message'],c)
        item.update(security=sec, security_reason=reason, safe_urls=urls)
    groups = [[i["id"]] for i in items]
    h, t, _ = render(c, items, groups, flagged, inline=True)
    prefix = store.root / "plans" / (plan_id + "-newsletter")
    private_write(str(prefix) + ".html", h)
    private_write(str(prefix) + ".txt", t)
    private_write(str(prefix) + ".json", json.dumps({'items':items,'groups':groups,'flagged':flagged}))
    return {"plan": plan_id, "preview": str(prefix) + ".html", "sendable": False}
