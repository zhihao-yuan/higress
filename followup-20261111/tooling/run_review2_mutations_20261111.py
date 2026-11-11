import difflib,hashlib,json,os,signal,subprocess,sys,threading,time
from pathlib import Path
lab=Path(__file__).resolve().parent;repo=lab/'higress';out=lab/'evidence/mutations-review2-20261111';out.mkdir(exist_ok=False)
revision='9efa167c17346817ad7487e752ede06d20276b72';src=repo/'plugins/wasm-rust/extensions/ai-data-masking/src'
originals={p:p.read_bytes() for p in src.glob('*.rs')};rows=[];paused=[];stop=threading.Event();success=False

def controllers():
 result=[]
 for line in subprocess.check_output(['ps','-Ao','pid,command'],text=True).splitlines()[1:]:
  parts=line.split(None,1)
  if len(parts)==2 and parts[1].split()[-2:]==['-B','run_review2_verification_20261111.py']:result.append(int(parts[0]))
 return result

def pause():
 for pid in controllers():
  if pid not in paused:os.kill(pid,signal.SIGSTOP);paused.append(pid)

def guard():
 while not stop.wait(1):
  try:
   state=json.load(open(lab/'review-20261111/verification-state.json'))
   if state['steps'] and state['steps'][-1]['name'] in ('build-fault-probe','host-failure','host-failure-integrity','capacity','capacity-integrity','live'):pause()
  except (FileNotFoundError,json.JSONDecodeError,ProcessLookupError):pass
thread=threading.Thread(target=guard,daemon=True);thread.start()

def replace_once(text,before,after):
 assert text.count(before)==1,(before,text.count(before));return text.replace(before,after,1)

def precopy(text):
 start=text.index('    pub(super) fn push_with_raw_deny(');where=text.index('        let mut actions = Vec::new();',start)
 return text[:where]+'''        if let Some(window) = raw_deny.as_deref_mut() {
            window.push(data, end, config, log)?;
        }
'''+text[where:]
mutations=[
 ('raw-before-framing','tool_stream.rs','raw_deny_sees_only_bounded_frames_and_matches_whole_body_checks',precopy),
 ('raw-check-skipped','tool_stream.rs','raw_deny_sees_only_bounded_frames_and_matches_whole_body_checks',lambda s:replace_once(s,'                window.push(&raw, false, config, log)?;','                let _ = window;')),
 ('raw-capacity-retained','tool_raw.rs','raw_deny_batched_frames_do_not_retain_the_callback_allocation',lambda s:replace_once(s,'''        if self.bytes.capacity() > config.tool_arguments.limits.max_unparsed_bytes {
            self.bytes.shrink_to_fit();
        }''','')),
 ('json-sse-ceiling','ai_data_masking.rs','recognized_json_errors_do_not_use_the_unparsed_sse_limit',lambda s:replace_once(s,'if tools.response_stream.is_none() && exceeds_unparsed_limit {','if exceeds_unparsed_limit {')),
 ('decoder-capacity-ceiling','tool_stream.rs','sse_allocation_stays_within_the_frame_limit',lambda s:replace_once(s,'.min(limit)','')),
 ('default-129-calls','tool_config.rs','default_response_call_count_accepts_127_and_128_but_rejects_129',lambda s:replace_once(s,'max_calls: 128,','max_calls: 129,')),
]
try:
 prerequisite=lab/'evidence/review2-native182-bounded-20261111-result.json';start=time.time()
 while not prerequisite.exists():
  assert time.time()-start<3600;time.sleep(5)
 assert json.load(open(prerequisite))['exit_code']==0
 for name,filename,test,mutate in mutations:
  p=src/filename;before=originals[p];after=mutate(before.decode()).encode();label='review2-mut-'+name+'-20261111'
  diff=''.join(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='a/'+filename,tofile='b/'+filename))
  (out/(name+'.diff')).write_text(diff);p.write_bytes(after)
  try:
   command=[sys.executable,str(lab/'run_native.py'),label,'sh','-ec',f'cd /src/extensions/ai-data-masking; export CARGO_TARGET_DIR=/src/target/ci-rust180-20261110 CARGO_BUILD_JOBS=2; cargo +1.80.0 test --locked --offline {test} -- --test-threads=1']
   with (out/(name+'-runner.log')).open('w') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
   result=json.load(open(lab/'evidence'/(label+'-result.json')));log=(lab/'evidence'/(label+'.log')).read_text()
   killed=r.returncode==101 and result['exit_code']==101 and result['source_stable_during_run'] and 'panicked at' in log and 'test result: FAILED.' in log and 'could not compile' not in log
   row={'source_revision':revision,'mutation':name,'file':filename,'test':test,'baseline_sha256':hashlib.sha256(before).hexdigest(),'mutant_sha256':hashlib.sha256(after).hexdigest(),'diff_sha256':hashlib.sha256(diff.encode()).hexdigest(),'native_label':label,'exit_code':r.returncode,'killed':killed,'elapsed_seconds':result['elapsed_seconds']}
   rows.append(row);assert killed,row
  finally:
   p.write_bytes(before)
   if rows:rows[-1]['restored_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
   (out/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
  print(json.dumps(rows[-1]),flush=True)
 assert all(p.read_bytes()==raw for p,raw in originals.items())
 assert subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)==''
 (out/'summary.json').write_text(json.dumps({'source_revision':revision,'mutants':len(rows),'killed':sum(r['killed'] for r in rows),'source_restored':True,'candidate_wasm_unchanged':hashlib.sha256((lab/'wasm/review2-candidate-rust180-20261111.wasm').read_bytes()).hexdigest()=='59b25818e30da43aa32b071e34ce22e4ccfccdfebac94cb86da7bc08c878af6b'},indent=2)+'\n');success=True
finally:
 for p,raw in originals.items():p.write_bytes(raw)
 stop.set();thread.join()
 if success:
  for pid in paused:
   try:os.kill(pid,signal.SIGCONT)
   except ProcessLookupError:pass
 else:pause()
