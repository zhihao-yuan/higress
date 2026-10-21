"""Validate saved evidence without Docker, a model, or credentials."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def read(name):
    return json.loads((ROOT / name).read_text())

revisions = read('source-revisions.json')
assert revisions['main_rust_tree'] == revisions['initial_main_rust_tree']
assert revisions['fixed'] == 'f16adbc79a943da2622ec99e8084ee5500ca5c51'
for name, expected in read('tested-source.json').items():
    path = ROOT / 'source-snapshot' / name
    actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    assert actual == expected, name
for name in ['fixed.wasm', 'runtime/fixed.wasm']:
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == revisions['fixed_wasm_sha256'], name
checks = read('checks.json')
assert len(checks) == 5 and all(item['exit_code'] == 0 for item in checks)
for name in ['native-final.log', 'make-test-final.log']:
    assert '30 passed; 0 failed' in (ROOT / name).read_text(), name

rows = read('runtime/runtime-evidence-review/results.json')
assert len(rows) == 552
fixed = [row for row in rows if row['variant'] == 'fixed']
assert len(fixed) == 138
for row in fixed:
    for key in ['tools_definitions_preserved', 'mask_active', 'tool_deltas_equal', 'text_equal',
                'finish_equal', 'done_equal', 'metadata_equal', 'errors_equal', 'usage_equal']:
        assert row[key], (row['case'], key)
assert sum(row['variant'] == 'pre_review' and row['scenario'] == 'same_choice_barrier'
           and not row['text_equal'] for row in rows) == 8
for row in rows:
    path = ROOT / 'runtime/runtime-evidence-review' / (row['case'] + '.body')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row['body_sha256'], row['case']

denials = read('runtime/deny-evidence/results.json')
assert len(denials) == 48
fixed_denials = [row for row in denials if row['variant'] == 'fixed']
assert len(fixed_denials) == 16
assert all(row['deny_check_matched'] and not row['forbidden_in_client'] for row in fixed_denials)
assert sum(row['variant'] == 'pre_review' and row['scenario'] == 'deny_across_barrier'
           and row['forbidden_in_client'] for row in denials) == 8
for row in denials:
    path = ROOT / 'runtime/deny-evidence' / (row['case'] + '.body')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row['body_sha256'], row['case']

live = read('live/results.json')
assert len(live) == 14
assert sum(row['variant'] == 'fixed' for row in live) == 4
assert all(row['real_model_request'] for row in live)
for row in live:
    path = ROOT / 'live/responses' / (row['case'] + '.body')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row['body_sha256'], row['case']
for label in ['fixed-tools-1', 'fixed-tools-2']:
    assert (ROOT / 'live/responses' / (label + '.body')).read_bytes() == (
        ROOT / 'live/responses' / (label + '.upstream.body')).read_bytes()
for name in ['cleanup.json', 'runtime/runtime-evidence-review/cleanup.json',
             'runtime/deny-evidence/cleanup.json', 'live/cleanup.json']:
    assert not any(read(name).values()), name
print('Verified: 30 native tests, 552 runtime requests, 48 deny requests, 14 fresh model requests, and cleanup.')
