"""Generate a fictional, shareable visual sample (no mail access)."""

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import yaml
from pubmail.digest import render, mime

root = Path(__file__).resolve().parents[1]
c = yaml.safe_load((root / "config.example.yaml").read_text())
items = []
for id, title, summary, deadline, sender in [
    (
        "demo1",
        "A weekend outdoors",
        "A compact hiking collection pairs lighter daypacks with weatherproof layers. The offer covers selected products, not the entire range.",
        "2026-10-12T23:59:00+01:00",
        "offers@outdoors.example",
    ),
    (
        "demo2",
        "A weekend outdoors",
        "A second update adds the full packing list and confirms which daypacks are included.",
        "2026-10-12T23:59:00+01:00",
        "news@outdoors.example",
    ),
    (
        "demo3",
        "A new world for your game table",
        "The publisher previews a cooperative exploration game, with details on player count and the upcoming campaign.",
        None,
        "news@games.example",
    ),
    (
        "demo4",
        "The autumn reading collection",
        "A seasonal collection of essays and fiction was discounted during a short early-access offer. That offer has now ended.",
        "2026-10-01T18:00:00+01:00",
        "books@reading.example",
    ),
]:
    m = {
        "id": id,
        "original_sender": sender,
        "timestamp": 1791532800,
        "unsubscribe": ["https://" + sender.split("@")[1] + "/unsubscribe"],
    }
    items.append(
        dict(
            id=id,
            title=title,
            summary=summary,
            topic=title,
            deadline=deadline,
            message=m,
            safe_urls=m["unsubscribe"],
        )
    )
flag = [
    dict(
        id="demo5",
        title="Account offer needing verification",
        summary="An unexpected offer claims an association with a known service. Sender identity could not be established.",
        message={
            "id": "demo5",
            "original_sender": "sender@unverified.example",
            "timestamp": 1791532800,
        },
        security_reason="Claimed identity and sending domain do not match",
    )
]
groups = [["demo1", "demo2"], ["demo3"], ["demo4"]]
h, t, _ = render(
    c,
    items,
    groups,
    flag,
    now=datetime(2026, 10, 10, 12, tzinfo=ZoneInfo("Europe/Lisbon")),
    inline=True,
)
out = root / "output"
out.mkdir(exist_ok=True)
(out / "sample.html").write_text(h)
(out / "sample.txt").write_text(t)
(out / "sample.eml").write_text(
    mime(c, items, groups, flag, "fictional-sample").as_string()
)
print(out / "sample.html")
