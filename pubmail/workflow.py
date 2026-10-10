from __future__ import annotations
import hashlib, json, time, uuid
from .core import normalize, security, preclassify, week_bounds
from .io import Error, policy_hash, private_write


def decide(m, c, model, store):
    cached = store.cached(m, c)
    if cached:
        return cached
    kind, reason = preclassify(m, c)
    sec, sreason, urls = security(m, c)
    d = {
        "id": m["id"],
        "message": m,
        "action": "keep",
        "reason": reason,
        "security": sec,
        "security_reason": sreason,
        "safe_urls": urls,
        "title": m["subject"],
        "summary": "Promotional message; summary not yet available.",
        "topic": m["subject"],
        "deadline": None,
    }
    if kind != "keep":
        if kind == "advertising":
            d["action"] = "archive" if sec == "verified" else "review"
        else:
            try:
                result = model.classify(m)
                d["classification"] = {
                    "kind": result["kind"],
                    "confidence": result["confidence"],
                }
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
                if result["kind"] == "advertising" and result["confidence"] >= c[
                    "model"
                ].get("confidence_threshold", 0.98):
                    d["action"] = "archive" if sec == "verified" else "review"
                    d["reason"] = "Model: clear promotion"
                else:
                    d["reason"] = "Model uncertain or non-promotional; retained"
            except Error:
                d["reason"] = "Model failed; retained"
                d["retry"] = True
    if not d.get("retry"):
        store.put_decision(m, c, d)
    return d


def oldest_week(gmail, c):
    base = "in:inbox is:unread -in:trash -in:spam"
    if not gmail.search(base, 1)[0]:
        return None
    # Existence queries avoid downloading the entire inbox just to find its age.
    lo = 0
    hi = int(time.time()) + 86400
    while hi - lo > 86400:
        mid = (lo + hi) // 2
        if gmail.search(base + f" before:{mid}", 1)[0]:
            hi = mid
        else:
            lo = mid
    rows, more = gmail.search(base + f" before:{hi}", 1000)
    if more:
        raise Error("Too many messages on oldest day; increase bounded discovery limit")
    stamp = min(int(gmail.raw(x["id"])["internalDate"]) // 1000 for x in rows)
    return week_bounds(stamp, c["timezone"])


def plan(gmail, c, model, store, week=None, hourly=False):
    if hourly:
        if not c["rollout"].get("live_after"):
            raise Error("Set rollout.live_after before hourly activation")
        checkpoint = store.db.execute(
            "SELECT value FROM meta WHERE key='hourly_after'"
        ).fetchone()
        lower = int(checkpoint[0]) if checkpoint else int(c["rollout"]["live_after"])
        upper = int(time.time())
        q = f"in:inbox is:unread -in:trash -in:spam after:{lower - 1} before:{upper}"
        limit = c["limits"]["hourly_messages"]
        bounds = None
    else:
        bounds = week or oldest_week(gmail, c)
        if bounds is None:
            return None
        # after is exclusive: subtract one second, then enforce exact timestamps.
        q = f"in:inbox is:unread -in:trash -in:spam after:{bounds[0] - 1} before:{bounds[1]}"
        limit = c["limits"]["week_messages"]
    rows, more = gmail.search(q, limit)
    if hourly and more:
        raise Error(
            "Hourly window exceeds limit; increase hourly_messages or review the backlog before retrying"
        )
    decisions = []
    for row in rows:
        m = normalize(gmail.raw(row["id"]), c["limits"]["body_characters"])
        if not {"INBOX", "UNREAD"} <= set(m["labels"]):
            continue
        if bounds and not bounds[0] <= m["timestamp"] < bounds[1]:
            continue
        decisions.append(decide(m, c, model, store))
    p = {
        "id": str(uuid.uuid4()),
        "created": int(time.time()),
        "account": c["account"],
        "policy": policy_hash(c),
        "bounds": bounds,
        "truncated": more,
        "decisions": decisions,
        "hourly_cutoff": upper if hourly else None,
    }
    body = json.dumps(p, ensure_ascii=False, sort_keys=True, indent=2)
    sha = hashlib.sha256(body.encode()).hexdigest()
    store.db.execute("INSERT INTO plans VALUES(?,?,?)", (p["id"], sha, body))
    store.db.commit()
    private_write(store.root / "plans" / f"{p['id']}.json", body)
    report = [
        "# Dry-run review",
        f"Plan: {p['id']}",
        f"SHA256: {sha}",
        f"Window: {bounds}",
        f"Batch limited: {more}",
        "Email fields below are untrusted data. No email changed.",
        "",
    ]
    for d in decisions:
        # JSON escaping prevents multiline email content from masquerading as report instructions.
        report.append(
            f"- {d['action'].upper()} | {d['id']} | {json.dumps(d['message']['sender'])} | {json.dumps(d['message']['subject'])} | {d['reason']} | {d['security_reason']}"
        )
    private_write(store.root / "plans" / f"{p['id']}.md", "\n".join(report) + "\n")
    return p, sha


def apply(gmail, c, store, id, sha):
    row = store.db.execute("SELECT digest,body FROM plans WHERE id=?", (id,)).fetchone()
    if not row or row[0] != sha:
        raise Error("Exact reviewed plan hash required")
    p = json.loads(row[1])
    if p["account"] != c["account"] or p["policy"] != policy_hash(c):
        raise Error("Configuration changed; create a new preview")
    labels = gmail.labels(create=True)
    ads = labels[c["labels"]["ads"]]
    changed = []
    skipped = []
    for d in p["decisions"]:
        if d["action"] not in ("archive", "review"):
            continue
        m = normalize(gmail.raw(d["id"]), c["limits"]["body_characters"])
        if (
            not {"INBOX", "UNREAD"} <= set(m["labels"])
            or {"SPAM", "TRASH"} & set(m["labels"])
            or m["headers_hash"] != d["message"]["headers_hash"]
        ):
            skipped.append(d["id"])
            continue
        # A reviewed security issue is registered for a text-only digest, not archived.
        if d["action"] == "review":
            store.db.execute(
                "INSERT OR REPLACE INTO meta VALUES(?,?)",
                ("review:" + d["id"], json.dumps(d)),
            )
            store.db.commit()
            continue
        sec, _, _ = security(m, c)
        if sec != "verified" or preclassify(m, c)[0] == "keep":
            skipped.append(d["id"])
            continue
        prior = ads in m["labels"]
        # Write intent before mutation: retry/recovery can inspect actual Gmail labels.
        store.db.execute(
            "INSERT OR IGNORE INTO archived VALUES(?,?,?)", (m["id"], id, int(prior))
        )
        store.db.commit()
        gmail.modify(m["id"], add=[ads], remove=["INBOX"])
        changed.append(m["id"])
    return {"archived": len(changed), "skipped": len(skipped), "plan": id}


def undo(gmail, c, store, id):
    labels = gmail.labels()
    ads = labels.get(c["labels"]["ads"])
    n = 0
    for mid, prior in store.db.execute(
        "SELECT id,previously_ads FROM archived WHERE plan=?", (id,)
    ).fetchall():
        m = normalize(gmail.raw(mid))
        if {"SPAM", "TRASH"} & set(m["labels"]):
            continue
        gmail.modify(mid, add=["INBOX"], remove=[] if prior or not ads else [ads])
        n += 1
    return {"restored_to_inbox": n}
