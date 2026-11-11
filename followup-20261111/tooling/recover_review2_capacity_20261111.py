import hashlib,json,subprocess,sys,time
from pathlib import Path
lab=Path(__file__).resolve().parent;review=lab/'review-20261111';source=lab/'higress/verification/ai-data-masking-tool-arguments';rev='9efa167c17346817ad7487e752ede06d20276b72'
old=json.load(open(review/'completion-state.json'));assert old['steps'][-1]['state']=='failed' and old['steps'][-1]['name']=='capacity'
(review/'capacity-first-completion-state.json').write_text(json.dumps(old,indent=2)+'\n')
assert json.load(open(review/'capacity-power-diagnostic.json'))['lid_closed'] is False
assert json.load(open(review/'capacity-power-diagnostic.json'))['current_power_assertions']['PreventUserIdleSystemSleep']==1
assert hashlib.sha256((lab/'wasm/review2-candidate-rust180-20261111.wasm').read_bytes()).hexdigest()=='59b25818e30da43aa32b071e34ce22e4ccfccdfebac94cb86da7bc08c878af6b'
assert subprocess.check_output(['git','status','--porcelain'],cwd=lab/'higress',text=True)==''
state={'source_revision':rev,'state':'rerunning-capacity-with-system-awake','cause':'A documented clamshell sleep interrupted the first capacity run. Original data preserved; no code, timeout or quota change.','steps':[]}
def save():
 p=review/'completion-state.json';q=p.with_suffix('.next');q.write_text(json.dumps(state,indent=2)+'\n');q.replace(p)
def run(name,cmd):
 row={'name':name,'command':list(map(str,cmd)),'state':'running','started':time.time()};state['steps'].append(row);save()
 with (review/('final-'+name+'.log')).open('w') as log:r=subprocess.run(row['command'],stdout=log,stderr=subprocess.STDOUT)
 row.update(state='passed' if r.returncode==0 else 'failed',exit_code=r.returncode,elapsed_seconds=time.time()-row['started']);save();assert r.returncode==0,row
common=['--baseline-wasm',lab/'wasm/review2-upstream-rust180-20261111.wasm','--candidate-wasm',lab/'wasm/review2-candidate-rust180-20261111.wasm','--baseline-source','1fef633553462434ccafad94a6ef35d2b367450f','--candidate-source',rev]
for name,output,extra in [('capacity-clock-control',lab/'capacity-clock-control-review2-20261111-a',['--only-group','near-total-c1-candidate-off']),('capacity',lab/'capacity-review2-20261111-b',[]),('live',lab/'live-review2-20261111-a',[])]:
 assert not output.exists(),'Never overwrite an attempt or automatically retry a model call'
 script='verify_live.py' if name=='live' else 'verify_capacity.py'
 run(name,[sys.executable,'-B',source/script,*common,'--output',output,'--resource-prefix','h5213-r2-'+name+'-b',*extra])
 run(name+'-integrity',[sys.executable,'-B',source/'check_results.py',output])
v=json.load(open(lab/'live-review2-20261111-a/summary.json'));assert v['formal_cases']==v['covered']==14 and v['uncovered']==0 and v['real_model_generations_dispatched']==15 and v['health_calls']==1
state['state']='all-verification-completed';save();print(json.dumps(state),flush=True)
