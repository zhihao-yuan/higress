import hashlib,json,os,subprocess,sys,time
from pathlib import Path
lab=Path(__file__).resolve().parent
repo=lab/'higress'
source=repo/'verification/ai-data-masking-tool-arguments'
aux=lab/'review2-supplemental-suite-20261111'
review=lab/'review-20261111'
revision='9efa167c17346817ad7487e752ede06d20276b72'
upstream='1fef633553462434ccafad94a6ef35d2b367450f'
state={'source_revision':revision,'baseline_revision':upstream,'model_budget_approved':{'health':1,'formal':14,'formal_max_tokens':256},'steps':[]}
def save():
 p=review/'verification-state.json';q=p.with_suffix('.next');q.write_text(json.dumps(state,indent=2)+'\n');q.replace(p)
def run(name,cmd):
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==revision
 record={'name':name,'command':list(map(str,cmd)),'state':'running','started':time.time()};state['steps'].append(record);save();print('START '+name,flush=True)
 with (review/(name+'.log')).open('w') as out:r=subprocess.run(record['command'],stdout=out,stderr=subprocess.STDOUT)
 record.update(state='passed' if r.returncode==0 else 'failed',exit_code=r.returncode,elapsed_seconds=time.time()-record['started']);save();print(json.dumps(record),flush=True)
 assert r.returncode==0,name+' failed; retained log, no automatic retry'
prereqs=[lab/'evidence/review2-native-stable-20261111-result.json',lab/'build-review2-upstream-rust180-20261111/manifest.json',lab/'build-review2-candidate-rust180-20261111/manifest.json']
state['state']='waiting-for-native-and-builds';save()
start=time.time()
while not all(p.exists() for p in prereqs):
 for p in prereqs:
  if p.exists():assert json.loads(p.read_text())['exit_code']==0, str(p)+' failed'
 assert time.time()-start<3600,'prerequisites did not complete within one hour'
 time.sleep(5)
for p in prereqs:
 v=json.loads(p.read_text());assert v['exit_code']==0
 if 'source_stable_during_run' in v:assert v['source_stable_during_run']
 for name,digest in v.get('source_files_sha256',{}).items():
  path=name if '/' in name else 'plugins/wasm-rust/extensions/ai-data-masking/src/'+name
  expected_revision=upstream if 'upstream' in p.parent.name else revision
  actual=subprocess.check_output(['git','show',expected_revision+':'+path],cwd=repo)
  assert hashlib.sha256(actual).hexdigest()==digest,(p,path)
base=lab/'wasm/review2-upstream-rust180-20261111.wasm'
candidate=lab/'wasm/review2-candidate-rust180-20261111.wasm'
for name,path in [('upstream',base),('candidate',candidate)]:
 v=json.loads((lab/('build-review2-'+name+'-rust180-20261111')/'manifest.json').read_text());assert hashlib.sha256(path.read_bytes()).hexdigest()==v['wasm_sha256']
state['state']='running-full-verification';save()
def suite(name,script,extra=(),baseline=base,baseline_revision=upstream,wasm=candidate,candidate_revision=revision):
 output=lab/(name+'-review2-20261111-a')
 cmd=[sys.executable,'-B',script,'--baseline-wasm',baseline,'--candidate-wasm',wasm,'--baseline-source',baseline_revision,'--candidate-source',candidate_revision,'--output',output,'--resource-prefix','h5213-r2-'+name,*extra]
 run(name,cmd);run(name+'-integrity',[sys.executable,'-B',source/'check_results.py',output])
suite('unparsed',source/'verify_unparsed.py',baseline=lab/'wasm/merged-20261109.wasm',baseline_revision='8ee506a2a727cb7793bc909fc74e53c204df6218')
suite('red-green',source/'verify_red_green.py')
suite('runtime',source/'verify_runtime.py')
suite('content',source/'verify_content_merge.py')
suite('flags',aux/'verify_flags.py',extra=('--system-word-file',repo/'plugins/wasm-rust/extensions/ai-data-masking/res/sensitive_word_dict.txt'))
suite('legacy',aux/'verify_legacy_rules.py')
suite('disabled',aux/'verify_disabled_large.py')
suite('limits',source/'verify_limits.py')
suite('configuration',source/'verify_configuration.py')
run('build-fault-probe',[sys.executable,'-B',lab/'build_fault_probe_review2_20261111.py','--repo',repo,'--revision',revision,'--output',lab/'fault-probe-review2-build-20261111'])
suite('host-failure',source/'verify_host_failure.py',wasm=lab/'fault-probe-review2-build-20261111/fault-probe.wasm',candidate_revision=revision+' + recorded intentional diagnostic patch')
# Capacity measurements start only after all compiler jobs have completed.
p=lab/'evidence/review2-native182-bounded-20261111-result.json'
start=time.time()
while not p.exists():
 assert time.time()-start<3600
 time.sleep(5)
v=json.loads(p.read_text());assert v['exit_code']==0 and v['source_stable_during_run'] and v['source_revision']==revision
for path,digest in v['source_files_sha256'].items():
 assert hashlib.sha256(subprocess.check_output(['git','show',revision+':'+path],cwd=repo)).hexdigest()==digest
suite('capacity',source/'verify_capacity.py')
# Only the approved final round reaches the real model; no retries or budget expansion.
suite('live',source/'verify_live.py')
state['state']='all-runtime-suites-passed';save()
print('ALL SUITES PASSED',flush=True)
