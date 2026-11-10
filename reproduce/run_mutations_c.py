"""Run deliberate defects against focused tests; always restore source bytes."""
import hashlib,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent
src=root/'higress/plugins/wasm-rust/extensions/ai-data-masking/src'
mutations=[('restore-flag-activation', 'tool_config.rs', 'let raw = Raw::deserialize(deserializer)?;', 'let mut raw = Raw::deserialize(deserializer)?; raw.restore |= raw.restore_allowlist.is_array();', 'response_callback_respects_all_eight_tool_switch_combinations'), ('literal-decode', 'tool_arguments.rs', 'serde_json::from_str(&self.input[start..self.at]).map_err(|_| "invalid JSON string")?', 'self.input[start + 1..self.at - 1].to_string()', 'deny_checks_decoded_keys_and_values_before_rewriting'), ('strict-inner', 'tool_arguments.rs', 'let document = JsonStrings::parse(input)?;', 'let document = match JsonStrings::parse(input) { Ok(value) => value, Err(_) => return Ok(None) };', 'malformed_or_oversized_arguments_cannot_be_released'), ('strict-sse', 'tool_stream.rs', 'serde_json::from_slice(&data).map_err(|_| "invalid tool SSE JSON")?', 'match serde_json::from_slice(&data) { Ok(value) => value, Err(_) => continue }', 'streaming_callback_runs_without_legacy_openai_and_keeps_failure_state'), ('text-order', 'tool_stream.rs', 'actions.push(StreamAction::FlushChoice(key.0));\n            actions.push(StreamAction::Arguments(argument_frame(key, entry)));', 'actions.push(StreamAction::Arguments(argument_frame(key, entry)));\n            actions.push(StreamAction::FlushChoice(key.0));', 'terminal_tool_frame_flushes_checked_text_before_arguments_and_finish'), ('call-choice-isolation', 'tool_stream.rs', 'Ok((choice, CallIndex::Modern(index)))', 'Ok((0, CallIndex::Modern(index)))', 'stream_keys_calls_by_choice_normalized_index_and_legacy_scope'), ('single-mask', 'ai_data_masking.rs', 'owned.contains(&(value as *const Value as usize))', 'false && owned.contains(&(value as *const Value as usize))', 'tool_request_masks_once_with_raw_and_argument_jsonpath_rules'), ('http-end-boundary', 'tool_stream.rs', 'ensure_event_boundary(&mut raw);', 'let _ = &mut raw;', 'unterminated_usage_event_is_separated_from_http_end_tool_arguments')]
records=[]
out=root/'evidence/mutations-c';out.mkdir(exist_ok=True)
for label,filename,before,after,test in mutations:
    path=src/filename; original=path.read_bytes(); text=original.decode()
    if text.count(before)!=1: raise SystemExit(f'{label}: expected exactly one mutation site, got {text.count(before)}')
    mutant=text.replace(before,after).encode()
    record={'mutation':label,'file':filename,'test':test,'baseline_sha256':hashlib.sha256(original).hexdigest(),'mutant_sha256':hashlib.sha256(mutant).hexdigest()}
    path.write_bytes(mutant)
    try:
        result=subprocess.run([sys.executable,str(root/'run_native.py'),'mutation-c-'+label,'cargo','test','--locked','--offline',test,'--','--nocapture'],cwd=root,capture_output=True,text=True)
        (out/(label+'-runner.log')).write_text(result.stdout+result.stderr)
        actual=json.loads((root/'evidence'/('mutation-c-'+label+'-result.json')).read_text())
        log=(root/'evidence'/('mutation-c-'+label+'.log')).read_text()
        record.update(exit_code=actual['exit_code'],killed=actual['exit_code']==101 and 'test result: FAILED.' in log and 'could not compile' not in log)
    finally:
        if path.read_bytes()!=mutant: raise RuntimeError('Source changed concurrently; refusing to overwrite '+filename)
        path.write_bytes(original)
        record['restored_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(record)
        (out/'results.json').write_text(json.dumps(records,indent=2)+'\n')
    print(json.dumps(record),flush=True)
    if not record.get('killed'): raise SystemExit('Mutation not killed: '+label)
print('All eight follow-up mutants failed their focused tests; original source restored.',flush=True)
