# Copyright (c) 2026 Alibaba Group Holding Ltd.
# SPDX-License-Identifier: Apache-2.0

"""Verify saved bytes, assertions, mutation failures and the same-request live capture."""
import hashlib
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'reproduce'))
from check_results import check
from verify_red_green import assert_scope
from verify_limits import keymap
from verify_runtime import parse


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


listed = set()
for line in (root / 'SHA256SUMS').read_text().splitlines():
    expected, relative = line.split('  ', 1)
    path = (root / relative).resolve()
    path.relative_to(root)
    assert sha(path) == expected, relative
    assert relative not in listed, relative
    listed.add(relative)
actual = {str(path.relative_to(root)) for path in root.rglob('*') if path.is_file()
          and '.git' not in path.relative_to(root).parts and path != root / 'SHA256SUMS'}
assert actual == listed, 'Unlisted or missing files'
print(json.dumps({'package_files_verified': len(listed)}))

for parent in (root / 'runs', root / 'history/synthetic'):
    for run in sorted(parent.iterdir()):
        if run.is_dir():
            print(json.dumps(check(run, False)))
for name in ('history/red-green', 'history/live'):
    print(json.dumps(check(root / name, False)))

for name in ('red-green-p2-final-20261109-a', 'red-green-ci-rust180-20261110-a'):
    red_green = root / 'runs' / name
    for row in json.loads((red_green / 'results.json').read_text()):
        case = row['case']
        path = red_green / 'cases'
        upstream_path = path / (case + '.upstream-request')
        upstream = json.loads(upstream_path.read_bytes()) if upstream_path.exists() else None
        body = (path / (case + '.body')).read_bytes()
        assert row['curl_exit'] == 0 and row['status'] == '200'
        if row['expected_red']:
            assert upstream is not None
            try:
                assert_scope(row['scope'], row, body, upstream, row['stream'])
            except AssertionError:
                pass
            else:
                raise AssertionError('Baseline unexpectedly satisfies the new scope')
        else:
            assert_scope(row['scope'], row, body, upstream, row['stream'])
    print(name + ': eight baseline failures and eight candidate scope assertions rechecked')

for name in ('unparsed-final-20261109-a', 'unparsed-ci-rust180-20261110-a'):
    unparsed = root / 'runs' / name
    for row in json.loads((unparsed / 'results.json').read_text()):
        case = row['case']
        wire = (unparsed / 'cases' / (case + '.upstream-response')).read_bytes()
        body = (unparsed / 'cases' / (case + '.body')).read_bytes()
        over = len(wire) > row['max_unparsed_bytes'] and '-batched-' not in case
        assert row['upstream_received'] and row['curl_exit'] == 0 and row['status'] == '200'
        if over and case.startswith('candidate-'):
            assert body == b'', case
        else:
            assert body in (wire, wire + b'\n\n'), case
    print(name + ': 72 raw framing outcomes rechecked against saved upstream bytes')

for record_path in sorted(root.rglob('*-result.json')):
    if record_path.relative_to(root).parts[0] == 'followup-20261111':
        continue  # Current native successes and retained attempts have an explicit checker below.
    record = json.loads(record_path.read_text())
    if 'source_files_sha256' not in record:
        continue
    label = record_path.name.removesuffix('-result.json')
    snapshot = record_path.parent / (label + '-source')
    for relative, expected in record['source_files_sha256'].items():
        assert sha(snapshot / Path(relative).name) == expected, (label, relative)
    assert sha(record_path.parent / (label + '-source.diff')) == record['source_diff_sha256']
    expected_exit = 101 if label.endswith('-red') or label.startswith('current-mutation-') else 0
    assert record['exit_code'] == expected_exit, label
    if expected_exit == 101:
        log = (record_path.parent / (label + '.log')).read_text()
        assert 'test result: FAILED' in log and 'panicked at' in log and 'could not compile' not in log, label

for name, source in (('current', 'source'), ('head-7d9223a6', 'source-head')):
    mutation = root / 'mutations' / name
    records = json.loads((mutation / 'results.json').read_text())
    assert len(records) == 20
    for row in records:
        assert row['killed'] and row['exit_code'] == 101
        assert sha(mutation / (row['mutation'] + '.diff')) == row['diff_sha256']
        baseline = root / source / 'plugins/wasm-rust/extensions/ai-data-masking/src' / row['file']
        assert sha(baseline) == row['baseline_sha256'] == row['restored_sha256']
    print(name + ': 20 assertion-killed mutations and restored source checked')

builds = [root / 'builds' / name for name in ('ci-rust180-20261110', 'ci-rust180-merged-20261110')]
for build in builds:
    manifest = json.loads((build / 'manifest.json').read_text())
    assert manifest['exit_code'] == 0
    assert sha(build / 'module.wasm') == manifest['wasm_sha256']
    for relative, expected in manifest['source_files_sha256'].items():
        assert sha(root / 'source-head' / relative) == expected, relative
assert sha(builds[0] / 'module.wasm') == sha(builds[1] / 'module.wasm')
assert sha(builds[1] / 'module.wasm') == sha(root / 'runs/unparsed-ci-rust180-20261110-a/candidate.wasm')
assert sha(builds[1] / 'module.wasm') == sha(root / 'runs/red-green-ci-rust180-20261110-a/candidate.wasm')
ci = json.loads((root / 'ci/ci-github-green-20261110.json').read_text())
assert ci['source_revision'] == '7d9223a61c1dd88a827945d8aabc8afc70e119ce'
assert len(ci['workflow_runs']) == 5
assert all(row['status'] == 'completed' and row['conclusion'] == 'success' for row in ci['workflow_runs'])
print('Current Rust source, rebuilt/runtime module identity and saved five-workflow CI result checked')

native_label = 'head-7d9223a6-native-20261110'
native_record = root / 'native' / native_label / (native_label + '-result.json')
native_manifest = json.loads((root / 'builds' / native_label / 'manifest.json').read_text())
assert json.loads(native_record.read_text())['exit_code'] == 0
native_log = (native_record.parent / (native_label + '.log')).read_text()
assert native_log.count('88 passed; 0 failed') == 2, 'Native and Makefile checks must both be present'
assert 'rustc 1.82.0' in native_log
assert native_manifest['source_revision'] == ci['source_revision']
assert native_manifest['git_diff_check_exit_code'] == 0
assert sha(root / 'builds' / native_label / 'module.wasm') == native_manifest['wasm_sha256']
for relative, expected in native_manifest['source_files_sha256'].items():
    assert sha(root / 'source-head' / relative) == expected, relative
print('Archived 7d9223a Rust 1.82 tests, lint, build and restored-source Makefile test checked')

profile = root / 'runs/capacity-options-head-7d9223a6-20261110-a'


def payload(path):
    return path.read_bytes() if path.exists() else gzip.decompress(Path(str(path) + '.gz').read_bytes())


assert sha(profile / 'candidate.wasm') == sha(builds[1] / 'module.wasm')
assert sha(profile / 'candidate.wasm') == sha(profile / 'baseline.wasm')
groups = json.loads((profile / 'results.json').read_text())
assert len(groups) == 4 and sum(group['formal_requests'] for group in groups) == 128
for group in groups:
    name = group['group']
    rows = json.loads((profile / (name + '.results.json')).read_text())
    samples = json.loads((profile / (name + '.samples.json')).read_text())
    assert group['concurrency'] == 32 and group['passed'] == 32 and group['failed'] == 0
    assert len(rows) == 32
    warmups = json.loads((profile / (name + '.warmups.json')).read_text())
    assert len(warmups) == 4 and all(row['passed'] for row in warmups)
    rss = [int(line.split()[1]) * 1024 for sample in samples for line in sample['raw'].splitlines()
           if line.startswith('VmRSS:')]
    assert max(rss) == group['sampled_peak_rss_bytes']
    for field, values in group['latency'].items():
        observations = sorted(row[field] for row in rows if field in row)
        assert values['n'] == len(observations)
        assert values['p95_nearest_rank'] == observations[(95 * len(observations) + 99) // 100 - 1]
    for row in rows:
        case = row['case']
        body = payload(profile / 'cases' / (case + '.body'))
        fixture = json.loads(payload(profile / 'cases' / (case + '.fixture.json')))
        actual = parse(body, True)
        expected = keymap(fixture)
        if group['variant'] == 'candidate-on':
            expected = {key: value.replace('MASKED_TOKEN', 'DEMO_SECRET') for key, value in expected.items()}
        assert actual['arguments'] == expected
        assert actual['names'] == {key: 'lookup' for key in expected}
        assert actual['finish'] == [(0, 'tool_calls')] and actual['done'] == 1
        assert actual['usage'] == [{'total_tokens': 20}]
        assert actual['text'] == {('0', 'content'): 'checking DEMO_SECRET'}
print('Archived 7d9223a capacity subset: 128 complete responses, sample RSS and P95 rechecked')

with tempfile.TemporaryDirectory(prefix='masking-live-offline-') as directory:
    subprocess.run([sys.executable, '-B', str(root / 'reproduce/reanalyze_live.py'),
                    '--input', str(root / 'history/live'), '--output', str(Path(directory) / 'analysis')], check=True)
    result = json.loads((Path(directory) / 'analysis/summary.json').read_text())
    assert result['covered'] == 14 and result['model_calls_new'] == 0
assert {str(path.relative_to(root)) for path in root.rglob('*') if path.is_file()
        and '.git' not in path.relative_to(root).parts and path != root / 'SHA256SUMS'} == listed
subprocess.run([sys.executable, '-B', str(root / 'followup-20261111/verify_followup.py')], check=True)
print('Offline package verification passed')
