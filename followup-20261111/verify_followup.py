"""Offline checks for the 2026-11-11 follow-up. Never starts Docker or a model."""
import gzip,hashlib,importlib.util,json,re,subprocess,sys,tarfile,tempfile
from pathlib import Path
sys.dont_write_bytecode=True
root=Path(__file__).resolve().parent
revision='9efa167c17346817ad7487e752ede06d20276b72'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):
 path=Path(path)
 return path.read_bytes() if path.exists() else gzip.decompress(Path(str(path)+'.gz').read_bytes())
def js(path):return json.loads(read(path))
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value);return value
listed={}
for line in (root/'SHA256SUMS').read_text().splitlines():
 digest,path=line.split('  ',1);assert sha((root/path).read_bytes())==digest,path;listed[path]=digest
assert set(listed)=={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p!=root/'SHA256SUMS'}
source=root/'source/plugins/wasm-rust/extensions/ai-data-masking'
for label in ('candidate','upstream'):
 build=root/'builds'/label;v=js(build/'manifest.json');raw=gzip.decompress((build/'source.tar.gz').read_bytes())
 assert sha(raw)==v['archive_sha256']
 assert sha((build/'module.wasm').read_bytes())==v['wasm_sha256']
 with tempfile.TemporaryDirectory() as folder:
  import io
  with tarfile.open(fileobj=io.BytesIO(raw)) as archive:archive.extractall(folder,filter='data')
  sdk=Path(folder)/'plugins/wasm-rust';plugin=sdk/'extensions/ai-data-masking'
  assert v['effective_lock_sha256']==sha((plugin/'Cargo.lock').read_bytes())
  assert v['sdk_root_lock_sha256']==sha((sdk/'Cargo.lock').read_bytes())
  assert v['effective_lock_path']=='plugins/wasm-rust/extensions/ai-data-masking/Cargo.lock'
  for name,digest in v['source_files_sha256'].items():assert sha((plugin/'src'/name).read_bytes())==digest
for label in ('review2-native-stable-20261111','review2-native182-bounded-20261111','review2-native182-locked-20261111'):
 native=root/'native'/label;v=js(native/(label+'-result.json'));log=(native/(label+'.log')).read_text()
 assert v['exit_code']==0 and v['source_stable_during_run']
 assert 'test result: ok. 93 passed; 0 failed' in log
 for path,digest in v['source_files_sha256'].items():assert sha((root/'source'/path).read_bytes())==digest
 for path,digest in v['locks_sha256'].items():assert sha((root/'source'/path).read_bytes())==digest
assert 'rustc 1.82.0' in (root/'native/review2-native182-bounded-20261111/review2-native182-bounded-20261111.log').read_text()
for row in js(root/'lock-provenance-corrections.json')['corrections']:
 v=js(root.parent/row['published_manifest'])
 assert v['lock_sha256']==row['effective_lock_sha256']==sha((source/'Cargo.lock').read_bytes())
 assert v['sdk_root_lock_sha256']==row['original_lock_sha256_field']
 assert sha((root.parent/row['published_manifest']).read_bytes())==row['corrected_manifest_sha256']
mutations=js(root/'mutations/summary.json');rows=js(root/'mutations/results.json')
assert mutations['mutants']==mutations['killed']==len(rows)==6 and mutations['source_restored'] and mutations['candidate_wasm_unchanged']
for row in rows:
 assert row['killed'] and row['exit_code']==101 and row['restored_sha256']==row['baseline_sha256']
 assert sha((source/'src'/row['file']).read_bytes())==row['baseline_sha256']
 label=row['native_label'];directory=root/'mutations/native'/label
 result=js(directory/(label+'-result.json'));log=(directory/(label+'.log')).read_text()
 assert result['exit_code']==101 and result['source_stable_during_run']
 assert 'panicked at' in log and 'test result: FAILED.' in log and 'could not compile' not in log
 assert sha((directory/(label+'-source')/row['file']).read_bytes())==row['mutant_sha256']
 assert sha((root/'mutations'/(row['mutation']+'.diff')).read_bytes())==row['diff_sha256']
alternate=js(root/'builds/rust182/manifest.json')
assert alternate['source_revision']==revision and alternate['runtime_tested'] is False
assert sha((root/'builds/rust182/module.wasm').read_bytes())==alternate['wasm_sha256']
ci=js(root/'ci-checks.json');assert ci and all(row['state'] in ('SUCCESS','SKIPPED','NEUTRAL') for row in ci),ci
red=root/'native/review2-red-fixed-harness-20261111'
assert js(red/'review2-red-fixed-harness-20261111-result.json')['exit_code']==101
red_log=(red/'review2-red-fixed-harness-20261111.log').read_text()
assert 'raw deny allocated 2200 bytes for a 22 byte frame limit' in red_log
assert '2 failed' in red_log and 'could not compile' not in red_log
expected_attempts={'review2-red-20261111':101,'review2-green-focused-20261111':130,'review2-native-final-20261111':101,'review2-native182-make-20261111':255}
for label,exit_code in expected_attempts.items():
 directory=root/'attempts/native'/label;record=js(directory/(label+'-result.json'));assert record['exit_code']==exit_code
 for path,digest in record['source_files_sha256'].items():assert sha((directory/(label+'-source')/Path(path).name).read_bytes())==digest
 assert sha((directory/(label+'-source.diff')).read_bytes())==record['source_diff_sha256']
runs={re.sub(r'-review2-20261111-[ab]$', '', p.name):p for p in (root/'runs').iterdir() if p.is_dir()}
expected={'unparsed','red-green','runtime','content','flags','legacy','disabled','limits','defaults','configuration','host-failure','capacity','live'}
assert set(runs)==expected
candidate_sha=js(root/'builds/candidate/manifest.json')['wasm_sha256']
for name,run in runs.items():
 subprocess.run([sys.executable,'-B',str(runs['unparsed']/'source/check_results.py'),str(run)],check=True)
 manifest=js(run/'manifest.json')
 if name!='host-failure':assert manifest['candidate_wasm_sha256']==candidate_sha
rt=module('followup_runtime',runs['runtime']/'source/verify_runtime.py')
rows=js(runs['runtime']/'results.json');assert len(rows)==1568
for row in rows:
 run=runs['runtime'];case=row['case'];base=run/'cases'
 up=base/(case+'.upstream-request');wire=base/(case+'.upstream-response')
 rt.check(row['variant'],row['scenario'],row['stream'],rt.configurations()[row['variant']],
          js(base/(case+'.request.json')),up.read_bytes() if up.exists() else None,
          wire.read_bytes() if wire.exists() else b'',read(base/(case+'.body')))
rows=js(runs['unparsed']/'results.json');assert len(rows)==160
for row in rows:
 case=row['case'];base=runs['unparsed']/'cases';original=read(base/(case+'.upstream-response'));body=read(base/(case+'.body'))
 if 'candidate-' in case and not any(t in case for t in ('json-error','batched','unterminated-1030-','unterminated-1031-')):
  assert body==b'' and rt.parse(body,True)['done']==0,case
 elif not row['expected_baseline_failure']:
  assert body in (original,original+b'\n\n'),case
 else:assert body,'Baseline did not forward the rejected wire input'
rows=js(runs['defaults']/'results.json');assert len(rows)==192
for row in rows:
 base=runs['defaults']/'cases';case=row['case'];body=read(base/(case+'.body'))
 if row['expected']=='response-denied':
  if row['stream']:assert not rt.parse(body,True)['arguments'] and rt.parse(body,True)['done']==0
  else:assert '已被屏蔽' in body.decode()
 elif row['expected']=='request-denied':assert not row['upstream_received'] and '已被屏蔽' in body.decode()
 else:
  actual=rt.parse(body,row['stream']);spec=js(base/(case+'.fixture.json'))
  expected_arguments={('0','modern',str(c.get('index',i))):c['arguments'] for i,c in enumerate(spec.get('calls',[]))}
  if case.startswith('default-restored-output-'):
   original=js(base/(case+'.request'))['messages'][0]['content'];expected_arguments={('0','modern','0'):'{"email":"'+original+'"}'}
  assert actual['arguments']==expected_arguments,case
rows=js(runs['limits']/'results.json');assert len(rows)==520
borders=[r for r in rows if r['case'].startswith('default-count-')];assert len(borders)==96
observed=set()
for row in borders:
 count=len(js(runs['limits']/'cases'/(row['case']+'.fixture.json'))['calls']);observed.add(count)
 assert row['expected']==('pass' if count<=128 else 'response-denied')
assert observed=={127,128,129}
cp=runs['capacity'];groups=js(cp/'results.json');assert len(groups)==36 and sum(g['formal_requests'] for g in groups)==1152
for group in groups:
 rows=js(cp/(group['group']+'.results.json'));samples=js(cp/(group['group']+'.samples.json'))
 assert len(rows)==32 and group['passed']==32 and group['failed']==0
 warmups=js(cp/(group['group']+'.warmups.json'));assert len(warmups)==4 and all(r['passed'] for r in warmups)
 rss=[int(line.split()[1])*1024 for sample in samples for line in sample['raw'].splitlines() if line.startswith('VmRSS:')]
 assert max(rss)==group['sampled_peak_rss_bytes']
 for field,quantiles in group['latency'].items():
  values=sorted(r[field] for r in rows if field in r);assert quantiles['n']==len(values) and quantiles['p95_nearest_rank']==values[(95*len(values)+99)//100-1]
 for row in rows:
  case=row['case'];spec=js(cp/'cases'/(case+'.fixture.json'));actual=rt.parse(read(cp/'cases'/(case+'.body')),True)
  expected_arguments={('0','modern',str(c.get('index',i))):c['arguments'] for i,c in enumerate(spec['calls'])}
  if group['variant']=='candidate-on':expected_arguments={k:v.replace('MASKED_TOKEN','DEMO_SECRET') for k,v in expected_arguments.items()}
  assert actual['arguments']==expected_arguments and actual['names']=={k:'lookup' for k in expected_arguments}
  assert actual['done']==1 and actual['finish']==[(0,'tool_calls')] and actual['usage']==[{'total_tokens':20}]
  assert actual['text']=={('0','content'):'checking DEMO_SECRET'}
live=runs['live'];v=js(live/'summary.json');ledger=js(live/'ledger.json')
assert v['formal_cases']==v['covered']==14 and v['uncovered']==0 and v['tools_executed']==0
assert len(ledger)==15 and sum(r['category']=='health' for r in ledger)==1
assert all(r['state']=='returned' and r['http_status']=='200' for r in ledger)
assert all(r['max_tokens']<=256 for r in ledger if r['category']=='formal')
with tempfile.TemporaryDirectory() as folder:
 subprocess.run([sys.executable,'-B',str(live/'source/reanalyze_live.py'),'--input',str(live),'--output',str(Path(folder)/'analysis')],check=True)
 v=js(Path(folder)/'analysis/summary.json');assert v['covered']==14 and v['model_calls_new']==0
assert js(root/'builds/fault-probe/manifest.json')['diagnostic_only']
assert js(runs['host-failure']/'summary.json')['candidate_runtime_crash_claim'] is False
failed=root/'attempts/capacity/capacity-review2-20261111-a'
subprocess.run([sys.executable,'-B',str(failed/'source/check_results.py'),str(failed),'--allow-recorded-failure'],check=True)
control=root/'attempts/capacity/capacity-clock-control-review2-20261111-a'
subprocess.run([sys.executable,'-B',str(control/'source/check_results.py'),str(control)],check=True)
assert len(js(control/'results.json'))==1 and js(control/'results.json')[0]['passed']==32
assert js(root/'attempts/capacity/capacity-power-diagnostic.json')['lid_closed'] is False
assert 'Clamshell Sleep' in str(js(root/'attempts/capacity/capacity-power-diagnostic.json'))
print('Follow-up verified: source/locks, 93-test native runs, final gateway assertions, 1152 capacity responses, and 14 real-model cases. New model calls: 0.')
