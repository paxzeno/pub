"""Optional BYO adapter: JSON stdin/stdout <-> OpenClaw gateway CLI."""
import argparse, json, os, sys, tempfile
from pathlib import Path
from .io import Error, run


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--executable',default='openclaw')
    p.add_argument('--agent',default='main')
    p.add_argument('--session-prefix',default='pub-review')
    p.add_argument('--timeout',type=int,default=150)
    args=p.parse_args()
    os.umask(0o077)
    packet=json.load(sys.stdin)
    # New per-batch session prevents source instructions persisting across batches.
    session=f"agent:{args.agent}:{args.session_prefix}-{packet['batch_id']}"
    with tempfile.TemporaryDirectory(prefix='pub-review-') as d:
        f=Path(d)/'request.json';f.write_text(json.dumps(packet));f.chmod(0o600)
        raw=run([args.executable,'agent','--agent',args.agent,'--session-key',session,
                 '--message-file',str(f),'--timeout',str(args.timeout),'--json'],
                timeout=args.timeout+10)
    envelope=json.loads(raw)
    payload=envelope.get('result',envelope)
    parts=payload.get('payloads',[])
    text='\n'.join(x['text'] for x in parts if isinstance(x.get('text'),str)).strip()
    if text.startswith('```'):
        lines=text.splitlines(); text='\n'.join(lines[1:-1])
    result=json.loads(text)
    if result.get('version')!=1 or not isinstance(result.get('results'),list):
        raise Error('Invalid OpenClaw reviewer response')
    print(json.dumps(result))

if __name__=='__main__':
    try: main()
    except Exception:
        print('OpenClaw reviewer adapter failed; details suppressed for privacy',file=sys.stderr)
        raise SystemExit(1)
