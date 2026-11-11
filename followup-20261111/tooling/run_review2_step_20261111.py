import hashlib,json,subprocess,sys,time
from pathlib import Path
lab=Path(__file__).resolve().parent;src=lab/'higress/verification/ai-data-masking-tool-arguments';aux=lab/'review2-supplemental-suite-20261111';review=lab/'review-20261111'
name=sys.argv[1];record={'name':name,'source_revision':'9efa167c17346817ad7487e752ede06d20276b72','steps':[]}
receipt=review/('parallel-'+name+'.json')
def run(label,cmd):
 row={'label':label,'command':list(map(str,cmd)),'started':time.time(),'state':'running'};record['steps'].append(row);receipt.write_text(json.dumps(record,indent=2)+'\n')
 with (review/('parallel-'+label+'.log')).open('w') as log:r=subprocess.run(row['command'],stdout=log,stderr=subprocess.STDOUT)
 row.update(exit_code=r.returncode,state='passed' if r.returncode==0 else 'failed',elapsed_seconds=time.time()-row['started']);receipt.write_text(json.dumps(record,indent=2)+'\n');assert r.returncode==0,label
base=lab/'wasm/review2-upstream-rust180-20261111.wasm';candidate=lab/'wasm/review2-candidate-rust180-20261111.wasm';source='9efa167c17346817ad7487e752ede06d20276b72'
assert hashlib.sha256(candidate.read_bytes()).hexdigest()=='59b25818e30da43aa32b071e34ce22e4ccfccdfebac94cb86da7bc08c878af6b'
if name=='host-failure':
 run('build-fault-probe',[sys.executable,'-B',lab/'build_fault_probe_review2_20261111.py','--repo',lab/'higress','--revision',source,'--output',lab/'fault-probe-review2-build-20261111'])
 candidate=lab/'fault-probe-review2-build-20261111/fault-probe.wasm';source+=' + recorded intentional diagnostic patch'
script={'legacy':aux/'verify_legacy_rules.py','disabled':aux/'verify_disabled_large.py','limits':src/'verify_limits.py','configuration':src/'verify_configuration.py','host-failure':src/'verify_host_failure.py'}[name]
output=lab/(name+'-review2-20261111-a')
run(name,[sys.executable,'-B',script,'--baseline-wasm',base,'--candidate-wasm',candidate,'--baseline-source','1fef633553462434ccafad94a6ef35d2b367450f','--candidate-source',source,'--output',output,'--resource-prefix','h5213-r2-'+name])
run(name+'-integrity',[sys.executable,'-B',src/'check_results.py',output])
record['state']='passed';receipt.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)
