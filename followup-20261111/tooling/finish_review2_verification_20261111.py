import hashlib,json,subprocess,sys,time
from pathlib import Path
lab=Path(__file__).resolve().parent;review=lab/'review-20261111';src=lab/'higress/verification/ai-data-masking-tool-arguments';rev='9efa167c17346817ad7487e752ede06d20276b72'
state={'source_revision':rev,'state':'waiting-for-independent-functional-checks','steps':[]}
def save():
 p=review/'completion-state.json';q=p.with_suffix('.next');q.write_text(json.dumps(state,indent=2)+'\n');q.replace(p)
def value(path):
 try:return json.loads(path.read_text())
 except (FileNotFoundError,json.JSONDecodeError):return None
def ready():
 old=value(review/'verification-state.json')
 if not old:return False
 for n in ('unparsed','red-green','runtime','content','flags'):
  for name in (n,n+'-integrity'):
   rows=[r for r in old['steps'] if r['name']==name]
   if not rows or rows[-1]['state']=='running':return False
   assert rows[-1]['state']=='passed',rows[-1]
 collision=[r for r in old['steps'] if r['name']=='legacy' and r['state']=='failed']
 if not collision:return False
 assert 'FileExistsError' in (review/'legacy.log').read_text(), 'Unexpected controller failure'
 for name in ('legacy','disabled','limits','configuration','host-failure'):
  v=value(review/('parallel-'+name+'.json'))
  if not v:return False
  assert not any(r.get('state')=='failed' for r in v['steps']),v
  if v.get('state')!='passed':return False
 native=value(lab/'evidence/review2-native182-bounded-20261111-result.json')
 if not native:return False
 assert native['exit_code']==0 and native['source_stable_during_run']
 mutations=value(lab/'evidence/mutations-review2-20261111/summary.json')
 detail=value(lab/'evidence/mutations-review2-20261111/results.json')
 if detail:assert all(r['killed'] for r in detail)
 if not mutations:return False
 assert mutations['mutants']==mutations['killed']==6 and mutations['source_restored'] and mutations['candidate_wasm_unchanged']
 defaults=value(lab/'defaults-review2-20261111-a/summary.json');integrity=value(review/'defaults-integrity.json')
 if not defaults or not integrity:return False
 assert defaults['passed']==192 and defaults['failed']==0 and integrity['status']=='integrity checked'
 return True
save();start=time.time()
while not ready():
 assert time.time()-start<5400,'Functional prerequisites still incomplete after 90 minutes'
 time.sleep(2)
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=lab/'higress',text=True).strip()==rev
assert subprocess.check_output(['git','status','--porcelain'],cwd=lab/'higress',text=True)==''
(review/'original-controller-state.json').write_bytes((review/'verification-state.json').read_bytes())
notes=value(review/'attempt-notes.json');notes['controller-functional-parallel-transition']='Remaining independent functional suites were run concurrently in isolated Docker networks. The original sequential controller later refused the existing legacy output directory, without starting another gateway or repeating that suite. Original status/log and each parallel worker exit receipt are retained. Capacity and live verification run only after every functional/native/mutation job completes.';(review/'attempt-notes.json').write_text(json.dumps(notes,indent=2)+'\n')
# Reject a measurement taken while any owned compiler process remains active.
check=['docker','exec','higress5213-builder','python3','-c','import pathlib; names=[]\nfor p in pathlib.Path("/proc").glob("[0-9]*"):\n try:\n  n=(p/"comm").read_text().strip()\n  if n in ("cargo","rustc","clippy-driver"):names.append(n)\n except FileNotFoundError:pass\nassert not names,names']
assert subprocess.run(check).returncode==0
state['state']='running-isolated-capacity-and-live';save()
def run(name,cmd):
 row={'name':name,'command':list(map(str,cmd)),'state':'running','started':time.time()};state['steps'].append(row);save()
 with (review/('final-'+name+'.log')).open('w') as log:r=subprocess.run(row['command'],stdout=log,stderr=subprocess.STDOUT)
 row.update(exit_code=r.returncode,state='passed' if r.returncode==0 else 'failed',elapsed_seconds=time.time()-row['started']);save();assert r.returncode==0,row
for name in ('capacity','live'):
 output=lab/(name+'-review2-20261111-a');assert not output.exists(),'Refuse to overwrite or retry '+name
 run(name,[sys.executable,'-B',src/('verify_'+name+'.py'),'--baseline-wasm',lab/'wasm/review2-upstream-rust180-20261111.wasm','--candidate-wasm',lab/'wasm/review2-candidate-rust180-20261111.wasm','--baseline-source','1fef633553462434ccafad94a6ef35d2b367450f','--candidate-source',rev,'--output',output,'--resource-prefix','h5213-r2-'+name])
 run(name+'-integrity',[sys.executable,'-B',src/'check_results.py',output])
v=value(lab/'live-review2-20261111-a/summary.json');assert v['formal_cases']==v['covered']==14 and v['uncovered']==0 and v['real_model_generations_dispatched']==15 and v['health_calls']==1
state['state']='all-verification-completed';save();print(json.dumps(state),flush=True)
