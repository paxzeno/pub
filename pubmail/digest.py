from __future__ import annotations
import base64, hashlib, json, struct, uuid, zlib
from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate
from zoneinfo import ZoneInfo
from jinja2 import Environment, PackageLoader, select_autoescape
from .core import normalize, security, safe_text
from .io import Error, private_write, run


def tile(index):
    # Tiny geometric topic thumbnail. Generated locally, no remote assets/tracking.
    palette = [(34, 86, 72), (66, 96, 131), (147, 101, 55), (105, 81, 119)]
    bg = palette[index % len(palette)]

    def chunk(t, data):
        return (
            struct.pack("!I", len(data))
            + t
            + data
            + struct.pack("!I", zlib.crc32(t + data) & 0xFFFFFFFF)
        )

    rows = []
    for y in range(64):
        row = bytearray()
        for x in range(64):
            stripe = 18 <= x < 46 and (18 <= y < 22 or 29 <= y < 33 or 40 <= y < 44)
            row.extend((236, 235, 219) if stripe else bg)
        rows.append(b"\0" + row)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 64, 64, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def render(c, items, groups, flagged, now=None, inline=False):
    now = now or datetime.now(ZoneInfo(c["timezone"]))
    lookup = {i["id"]: i for i in items}
    cards = []
    images = {}
    text = [c["newsletter"]["subject"], now.strftime("%d %B %Y"), ""]
    for n, g in enumerate(groups):
        entries = []
        title = lookup[g[0]]["title"]
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
            unsub = next(
                (u for u in m.get("unsubscribe", []) if u in i.get("safe_urls", [])),
                None,
            )
            # This is our Gmail link, not a link supplied in the email.
            original = (
                "https://mail.google.com/mail/u/?authuser="
                + c["account"]
                + "#all/"
                + m["id"]
            )
            entries.append(
                dict(
                    summary=i["summary"],
                    deadline=deadline,
                    expired=expired,
                    deadline_display=display,
                    sender=m["original_sender"],
                    original_url=original,
                    unsubscribe=unsub,
                )
            )
            text += [i["summary"]]
            if deadline:
                text += [("EXPIRED" if expired else "DEADLINE") + ": " + display]
            text += ["From: " + m["original_sender"], "Original: " + original]
            if unsub:
                text += ["Unsubscribe: " + unsub]
            text += [""]
        data = tile(n)
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
                    )
                }
            )
        except Error:
            # No false "digested" marking when summarization failed.
            raise Error("Digest summarization failed; nothing sent or marked")
        d.update(
            id=m["id"], message=m, security=sec, security_reason=reason, safe_urls=urls
        )
        (items if sec == "verified" else flagged).append(d)
    if not items and not flagged:
        return None
    # Bounded grouping; fallback is safe singletons, never omission.
    try:
        groups = model.groups(items)
    except Error:
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
    items = [d for d in p["decisions"] if d["action"] == "archive"]
    flagged = [d for d in p["decisions"] if d["action"] == "review"]
    try:
        groups = model.groups(items)
    except Error:
        groups = [[i["id"]] for i in items]
    h, t, _ = render(c, items, groups, flagged, inline=True)
    prefix = store.root / "plans" / (plan_id + "-newsletter")
    private_write(str(prefix) + ".html", h)
    private_write(str(prefix) + ".txt", t)
    return {"plan": plan_id, "preview": str(prefix) + ".html", "sendable": False}
