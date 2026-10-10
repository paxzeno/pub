from __future__ import annotations
import argparse, json, os
from datetime import datetime
from zoneinfo import ZoneInfo
from .io import Error, Gmail, Store, load_config
from .reviewer import EscalatingModel
from . import workflow, digest


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description="Conservative promotional-mail triage; dry-run first."
    )
    parser.add_argument("--config", default="~/.config/pub/config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("review-status")
    sub.add_parser("review-test")
    sub.add_parser("init-labels")
    sub.add_parser("oldest-week")
    sub.add_parser("hourly")
    sub.add_parser("weekly")
    p = sub.add_parser("digest-preview")
    p.add_argument("--plan", help="Preview proposed plan without sending or labelling")
    p = sub.add_parser("plan")
    p.add_argument("--week", help="Monday YYYY-MM-DD; default oldest eligible week")
    p = sub.add_parser("apply")
    p.add_argument("id")
    p.add_argument("--sha256", required=True)
    p = sub.add_parser("undo")
    p.add_argument("id")
    p = sub.add_parser("digest-send")
    p.add_argument("id")
    p = sub.add_parser("reconcile")
    p.add_argument("id")
    p.add_argument("--confirmed-sent", action="store_true", required=True)
    p.add_argument("--evidence", required=True)
    args = parser.parse_args()
    store = None
    try:
        c = load_config(args.config)
        if args.command == "review-test":
            from .reviewer import smoke_test
            print(json.dumps(smoke_test(c)))
            return
        store = Store(c)
        gmail = Gmail(c)
        model = EscalatingModel(c, store)
        if args.command in ("hourly", "weekly"):
            key = "hourly_enabled" if args.command == "hourly" else "digest_enabled"
            if not c["rollout"].get(key):
                print(json.dumps({"status": "paused", "job": args.command}))
                return
        if args.command == "review-status":
            out = model.reviewer.status()
        elif args.command == "check":
            d = gmail.call("auth", "list")
            matches = [
                a
                for a in d.get("accounts", [])
                if a.get("email") == c["account"] and not a.get("error")
            ]
            if not matches:
                raise Error("Configured Gmail authorization unavailable")
            gmail.labels()
            out = {"gmail_access": True, "account": c["account"]}
        elif args.command == "init-labels":
            out = gmail.labels(create=True)
        elif args.command == "oldest-week":
            out = {"bounds": workflow.oldest_week(gmail, c)}
        elif args.command in ("plan", "hourly"):
            bounds = None
            if args.command == "plan" and args.week:
                d = datetime.fromisoformat(args.week).replace(
                    tzinfo=ZoneInfo(c["timezone"])
                )
                if d.weekday() != 0:
                    raise Error("Week must start on Monday")
                from .core import week_bounds

                bounds = week_bounds(d.timestamp(), c["timezone"])
            result = workflow.plan(
                gmail, c, model, store, week=bounds, hourly=args.command == "hourly"
            )
            if not result:
                out = {"status": "no_unread_inbox_mail"}
            else:
                p, sha = result
                out = {
                    "plan": p["id"],
                    "sha256": sha,
                    "bounds": p["bounds"],
                    "truncated": p["truncated"],
                    "counts": {
                        a: sum(d["action"] == a for d in p["decisions"])
                        for a in ("keep", "archive", "review")
                    },
                }
                if args.command == "hourly":
                    out["result"] = workflow.apply(gmail, c, store, p["id"], sha)
                    if not any(d.get("retry") for d in p["decisions"]):
                        store.db.execute(
                            "INSERT OR REPLACE INTO meta VALUES('hourly_after',?)",
                            (str(p["hourly_cutoff"]),),
                        )
                        store.db.commit()
        elif args.command == "apply":
            out = workflow.apply(gmail, c, store, args.id, args.sha256)
        elif args.command == "undo":
            out = workflow.undo(gmail, c, store, args.id)
        elif args.command == "digest-preview" and args.plan:
            out = digest.preview_plan(c, model, store, args.plan)
        elif args.command in ("digest-preview", "weekly"):
            # Any interrupted send blocks generation/sending until reconciled.
            if store.db.execute(
                "SELECT 1 FROM deliveries WHERE status IN ('sending','ambiguous','sent')"
            ).fetchone():
                raise Error("Unresolved prior delivery: reconcile first")
            p = digest.prepare(gmail, c, model, store)
            out = (
                {"digest": p["id"], "messages": len(p["ids"])}
                if p
                else {"status": "empty"}
            )
            if p and args.command == "weekly":
                out = digest.send(gmail, c, store, p["id"])
        elif args.command == "digest-send":
            out = digest.send(gmail, c, store, args.id)
        else:
            row = store.db.execute(
                "SELECT status,body FROM deliveries WHERE id=?", (args.id,)
            ).fetchone()
            if not row or row[0] not in ("sending", "ambiguous", "sent"):
                raise Error("No ambiguous/sent delivery to reconcile")
            p = json.loads(row[1])
            p["reconciliation_evidence"] = args.evidence
            store.delivery(args.id, "sent", p)
            digest.finish_labels(gmail, c, store, args.id, p)
            out = {"reconciled": args.id}
        print(json.dumps(out, ensure_ascii=False))
    except Error as e:
        parser.exit(1, f"pubmail: {e}\n")
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    main()
