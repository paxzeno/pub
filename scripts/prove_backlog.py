"""Read-only mailbox snapshot + isolated preparation/review. Never sends or modifies mail."""
import sys,os,json,sqlite3,copy,shutil,time,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pubmail.io import load_config,Gmail,Store,private_write,ProcessingPending
from pubmail.reviewer import EscalatingModel
from pubmail import digest,automation
os.umask(0o077)
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config',default='~/.config/pub/config.yaml')
parser.add_argument('--delivery-id',required=True)
parser.add_argument('--out',required=True)
args=parser.parse_args()
c=load_config(args.config);live=Path(c['state_dir'])
root=Path(args.out).expanduser().resolve()
if root==live.resolve():raise ValueError('Proof must use separate state')
root.mkdir(mode=0o700,parents=True,exist_ok=True)
snapshot=root/'snapshot.json'
if not snapshot.exists():
 db=sqlite3.connect('file:'+str(live/'state.sqlite3')+'?mode=ro',uri=True)
 old=json.loads(db.execute("select body from deliveries where id=?",(args.delivery_id,)).fetchone()[0])
 g=Gmail(c);raw={i['id']:g.raw(i['id']) for i in old['skipped']}
 private_write(snapshot,json.dumps({'raw':raw,'labels':g.labels()}))
 for name in ('image-cache','vision-cache'):
  if (live/name).exists():shutil.copytree(live/name,root/name,dirs_exist_ok=True)
data=json.loads(snapshot.read_text())
class Snapshot:
 def labels(self,*a):return data['labels']
 def search(self,*a):return ([{'id':i} for i in data['raw']],False)
 def raw(self,ident):return data['raw'][ident]
 def modify(self,*a,**k):raise AssertionError('Mailbox mutation forbidden in proof')
def no_send(*a,**k):raise AssertionError('SMTP forbidden in proof')
digest.send=no_send
c=copy.deepcopy(c);c['state_dir']=str(root);c['image_loading']['mode']='public_https'
# Production config untouched until the proof passes.
private_write(root/'proof-config.json',json.dumps(c))
store=Store(c);model=EscalatingModel(c,store)
ident_file=root/'digest-id'
for step in range(60):
 try:
  if ident_file.exists():ident=ident_file.read_text().strip()
  else:
   prepared=digest.prepare(Snapshot(),c,model,store)
   if not prepared:raise RuntimeError('No prepared digest')
   ident=prepared['id'];private_write(ident_file,ident)
   print(json.dumps({'stage':'prepared','id':ident}),flush=True)
  automation.final_review(c,model,store,ident)
  b=json.loads(store.db.execute('select body from deliveries where id=?',(ident,)).fetchone()[0])
  result={'id':ident,'included':len(b['ids']),'skipped':len(b.get('skipped',[])),
          'titles':[i['title'] for i in b['items']],
          'skips':[{'id':i['id'],'subject':i['subject'],'reason':i['reason']} for i in b.get('skipped',[])],
          'smtp_calls':0,'mailbox_mutations':0}
  private_write(root/'result.json',json.dumps(result,indent=2));print(json.dumps(result),flush=True);break
 except ProcessingPending as e:
  print(json.dumps({'stage':'pending','pass':step,'message':str(e)}),flush=True)
else:raise RuntimeError('Proof bounded passes exhausted')
