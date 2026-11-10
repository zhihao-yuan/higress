from pathlib import Path
import ast,hashlib,json,subprocess,sys
lab=Path(__file__).resolve().parent
repo=lab/'higress'
mutations=[]
for script,selection in [('run_mutations_b.py',slice(0,10)),('run_mutations_c.py',slice(None))]:
 for node in ast.parse((lab/script).read_text()).body:
  if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='mutations' for t in node.targets):
   mutations.extend(ast.literal_eval(node.value)[selection])
mutations += [
 ('frame-ceiling','tool_stream.rs','config.tool_arguments.limits.max_unparsed_bytes,','usize::MAX,','unclosed_sse_frames_obey_the_unparsed_buffer_limit'),
 ('probe-ceiling','ai_data_masking.rs','.is_none_or(|size| size > config.tool_arguments.limits.max_unparsed_bytes)','.is_none_or(|_size| false)','undecided_response_prefix_is_bounded_and_failure_stays_closed')]
output=lab/'evidence/mutations-current-20261109';output.mkdir(exist_ok=False)
files={name:(repo/'plugins/wasm-rust/extensions/ai-data-masking/src'/name) for _,name,_,_,_ in mutations}
original={name:path.read_bytes() for name,path in files.items()}
source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
records=[]
for label,file,before,after,test in mutations:
 text=original[file].decode();assert text.count(before)==1,(label,text.count(before))
 mutant=text.replace(before,after,1).encode();path=files[file]
 record={'source_revision':source,'mutation':label,'file':file,'test':test,
  'baseline_sha256':hashlib.sha256(original[file]).hexdigest(),'mutant_sha256':hashlib.sha256(mutant).hexdigest()}
 path.write_bytes(mutant)
 try:
  diff=subprocess.check_output(['git','diff','--',str(path.relative_to(repo))],cwd=repo)
  (output/(label+'.diff')).write_bytes(diff)
  record['diff_sha256']=hashlib.sha256(diff).hexdigest()
  run_label='current-mutation-'+label+'-20261109'
  result=subprocess.run([sys.executable,str(lab/'run_native.py'),run_label,'sh','-ec',
   'cd /src/extensions/ai-data-masking; CARGO_TARGET_DIR=/src/target/p2-final cargo test --locked --offline '+test],cwd=repo,capture_output=True,text=True)
  (output/(label+'-runner.log')).write_text(result.stdout+result.stderr)
  log=(lab/'evidence'/(run_label+'.log')).read_text()
  record.update(exit_code=result.returncode,killed=result.returncode==101 and 'test result: FAILED' in log and 'panicked at' in log and 'could not compile' not in log)
 finally:
  if path.read_bytes()!=mutant:raise RuntimeError('Concurrent source change: '+file)
  path.write_bytes(original[file]);record['restored_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
  records.append(record);(output/'results.json').write_text(json.dumps(records,indent=2)+'\n')
 print(json.dumps(record),flush=True)
 assert record['killed'],label
for file,path in files.items():assert path.read_bytes()==original[file]
(output/'summary.json').write_text(json.dumps({'source_revision':source,'killed':len(records),'survived':0,'source_restored':True},indent=2)+'\n')
