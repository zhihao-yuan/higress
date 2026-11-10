"""Retain the interrupted attempt, restore source, and rerun only mutation 20."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys

lab = Path(__file__).resolve().parent
repo = lab / 'higress'
out = lab / 'evidence/mutations-head-7d9223a6-20261110'
records = json.loads((out / 'results.json').read_text())
assert len(records) == 19 and all(row['killed'] for row in records)
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
assert revision == '7d9223a61c1dd88a827945d8aabc8afc70e119ce'
relative = 'plugins/wasm-rust/extensions/ai-data-masking/src/ai_data_masking.rs'
path = repo / relative
original = subprocess.check_output(['git', 'show', revision + ':' + relative], cwd=repo)
before = b'Some(size) => size > config.tool_arguments.limits.max_unparsed_bytes,'
after = b'Some(_size) => false,'
assert original.count(before) == 1
mutant = original.replace(before, after, 1)
assert path.read_bytes() == mutant
label = 'current-mutation-probe-ceiling-20261110'
assert not (lab / 'evidence' / (label + '-result.json')).exists()
interrupted = lab / 'evidence/interrupted-probe-ceiling-20261110'
interrupted.mkdir(exist_ok=False)
for suffix in ('.log', '-source.diff', '-source'):
    source = lab / 'evidence' / (label + suffix)
    shutil.move(str(source), interrupted / source.name)
(interrupted / 'attempt.json').write_text(json.dumps({
    'source_revision': revision, 'mutation': 'probe-ceiling',
    'status': 'interrupted-before-result', 'exit_code': None,
    'reason': 'The conversation turn was interrupted before a test result was recorded.',
    'counted_as_killed': False, 'followup_label': label}, indent=2) + '\n')
path.write_bytes(original)
assert subprocess.check_output(['git', 'diff', '--name-only'], cwd=repo) == b''

record = {'source_revision': revision, 'mutation': 'probe-ceiling', 'file': 'ai_data_masking.rs',
          'test': 'undecided_response_prefix_is_bounded_and_failure_stays_closed',
          'baseline_sha256': hashlib.sha256(original).hexdigest(),
          'mutant_sha256': hashlib.sha256(mutant).hexdigest(),
          'interrupted_attempt_retained': 'ci/interrupted-probe-ceiling-20261110'}
path.write_bytes(mutant)
try:
    diff = subprocess.check_output(['git', 'diff', '--', relative], cwd=repo)
    assert (out / 'probe-ceiling.diff').read_bytes() == diff
    record['diff_sha256'] = hashlib.sha256(diff).hexdigest()
    result = subprocess.run([sys.executable, str(lab / 'run_native.py'), label, 'sh', '-ec',
                             'cd /src/extensions/ai-data-masking; CARGO_TARGET_DIR=/src/target/p2-final cargo test --locked --offline ' + record['test']],
                            cwd=repo, capture_output=True, text=True)
    (out / 'probe-ceiling-runner.log').write_text(result.stdout + result.stderr)
    log = (lab / 'evidence' / (label + '.log')).read_text()
    record.update(exit_code=result.returncode,
                  killed=result.returncode == 101 and 'test result: FAILED' in log and 'panicked at' in log and 'could not compile' not in log)
finally:
    assert path.read_bytes() == mutant, 'Source changed concurrently'
    path.write_bytes(original)
    record['restored_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    records.append(record)
    (out / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
assert record['killed'], record
assert subprocess.check_output(['git', 'diff', '--name-only'], cwd=repo) == b''
(out / 'summary.json').write_text(json.dumps({'source_revision': revision, 'killed': 20,
                                             'survived': 0, 'source_restored': True}, indent=2) + '\n')
print(json.dumps(record), flush=True)
