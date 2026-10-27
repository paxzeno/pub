from __future__ import annotations
import argparse, json, os
from datetime import datetime
from zoneinfo import ZoneInfo
from .io import Error, LockBusy, ProcessingPending, Gmail, Store, load_config
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
    sub.add_parser("auth-recover")
    image_retry=sub.add_parser("image-retry");image_retry.add_argument("key",help="64-character failure cache key, or all")
    sub.add_parser("review-status")
    sub.add_parser("review-test")
    sub.add_parser("automation-test")
    sub.add_parser("init-labels")
    sub.add_parser("oldest-week")
    sub.add_parser("hourly")
    sub.add_parser("weekly")
    sub.add_parser("resume")
    sub.add_parser("automation-status")
    a=sub.add_parser("automation-retry");a.add_argument("job",choices=['weekly'])
    a=sub.add_parser("review-resolve");a.add_argument("id");a.add_argument("--file",required=True)
    p = sub.add_parser("digest-preview")
    p.add_argument("--plan", help="Preview proposed plan without sending or labelling")
    p = sub.add_parser("plan")
    p.add_argument("--week", help="Monday YYYY-MM-DD; default oldest eligible week")
    p = sub.add_parser("apply")
    p.add_argument("id")
    p.add_argument("--sha256", required=True)
    p = sub.add_parser("undo")
    p.add_argument("id")
    p = sub.add_parser("digest-review")
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
        if args.command == 'automation-test':
            from .automation import smoke_test
            print(json.dumps(smoke_test(c)));return
        if args.command == "review-test":
            from .reviewer import smoke_test
            print(json.dumps(smoke_test(c)))
            return
        from .scheduling import hourly_held, queue_weekly, accept_weekly
        if args.command == 'hourly' and hourly_held(c):
            print(json.dumps({'status': 'held', 'reason': 'Friday 10:00–12:59 local weekly window'}))
            return
        if args.command == 'weekly' and c['rollout'].get('digest_enabled') and c.get('automation', {}).get('enabled'):
            queue_weekly(c)
        store = Store(c)
        gmail = Gmail(c)
        model = EscalatingModel(c, store)
        if args.command in ("hourly", "weekly"):
            key = "hourly_enabled" if args.command == "hourly" else "digest_enabled"
            if not c["rollout"].get(key):
                print(json.dumps({"status": "paused", "job": args.command}))
                return
        if args.command in ('weekly','resume') and c.get('automation',{}).get('enabled'):
            from .automation import run_weekly
            if c['rollout'].get('digest_enabled'):
                accept_weekly(c, store)
            result=run_weekly(gmail,c,model,store,start=False)
            print(json.dumps(result))
            if result.get('status')=='blocked':parser.exit(1,'pubmail: workflow blocked; inspect automation-status\n')
            return
        if args.command in ('automation-status','automation-retry','review-resolve','resume'):
            from . import automation
            automation.setup(store)
            if args.command=='automation-status':
                out={'queued_weekly': sorted(p.name for p in store.root.glob('weekly-request-*')),
                     'jobs':dict(store.db.execute('SELECT name,state FROM automation_jobs')),
                     'job_errors':automation.job_errors(store),
                     'notification_errors':{i:json.loads(b)['notification_error'] for i,b in store.db.execute("SELECT id,body FROM automation_events WHERE status='failed'") if 'notification_error' in json.loads(b)},
                     'review_errors':{i:json.loads(r)['error'] for i,r in store.db.execute("SELECT id,result FROM senior_items WHERE status='failed' AND result IS NOT NULL") if 'error' in json.loads(r)},
                     'handoffs':{i:{'status':s,'review_ids':json.loads(b).get('review_ids',[]),'acknowledged':bool(json.loads(b).get('handoff_receipt'))} for i,s,b in store.db.execute('SELECT id,status,body FROM automation_events')},
                     'notifications':dict(store.db.execute('SELECT status,count(*) FROM automation_events GROUP BY status')),
                     'reviews':model.reviewer.status()}
            elif args.command=='automation-retry':out=automation.retry(c,store,args.job)
            elif args.command=='review-resolve':out=automation.resolve(store,args.id,args.file)
            else:out={'status':'paused'}
            print(json.dumps(out));return
        if args.command == 'image-retry':
            from .vision import retry_failed_images
            print(json.dumps(retry_failed_images(c,args.key)))
            return
        if args.command == 'auth-recover':
            from .oauth import recovery_url
            from .io import run
            env = os.environ.copy()
            if c.get('keyring_password_command'):
                env['GOG_KEYRING_PASSWORD'] = run(c['keyring_password_command']).rstrip('\r\n')
            print(recovery_url(c, env))
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
                    if c.get('automation',{}).get('enabled'):
                        from .automation import setup,surface_reviews
                        setup(store);surface_reviews(c,store,'hourly')
                        if any(d['action']=='review' for d in p['decisions']):
                            from .automation import notify
                            notify(c,store,'hourly','security_review',[p['id']])
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
        elif args.command == "digest-review":
            from .automation import final_review
            p=final_review(c,model,store,args.id)
            out={"reviewed":p["id"],"mime_sha256":p["mime_sha256"]}
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
    except LockBusy as e:
        parser.exit(75, f"pubmail: {e}\n")
    except ProcessingPending as e:
        parser.exit(75, f"pubmail: pending image work: {e}\n")
    except Error as e:
        if store and c.get('automation',{}).get('enabled') and args.command in ('hourly','weekly','resume'):
            from .automation import setup,notify
            setup(store);notify(c,store,args.command,'workflow_blocked')
        parser.exit(1, f"pubmail: {e}\n")
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    main()
