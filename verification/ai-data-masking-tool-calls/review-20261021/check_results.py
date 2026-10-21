"""Verify saved results and module fingerprints without HTTP requests."""
import collections
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
runtime = ROOT / 'runtime-evidence-review'
rows = json.loads((runtime / 'results.json').read_text())
assert len(rows) == 366
assert collections.Counter(row['variant'] for row in rows) == {'bypass': 122, 'baseline': 122, 'fixed': 122}
fields = ['tools_definitions_preserved', 'mask_active', 'tool_deltas_equal', 'text_equal',
          'finish_equal', 'done_equal', 'errors_equal', 'usage_equal', 'metadata_equal']
for row in rows:
    body = (runtime / (row['case'] + '.body')).read_bytes()
    assert hashlib.sha256(body).hexdigest() == row['body_sha256']
    if row['variant'] == 'bypass':
        assert body == (runtime / (row['case'] + '.upstream-response')).read_bytes()
    if row['variant'] == 'fixed':
        assert all(row[field] for field in fields), row
    request = json.loads((runtime / (row['case'] + '.upstream-request.json')).read_text())
    definitions = {tool['function']['name']: tool['function'] for tool in request['tools']}
    raw = (runtime / (row['case'] + '.upstream-response')).read_text()
    if row['stream']:
        events = [json.loads(line[5:]) for line in raw.splitlines()
                  if line.startswith('data:') and line[5:].strip() != '[DONE]']
    else:
        events = [json.loads(raw)]
    calls = collections.defaultdict(lambda: {'name': '', 'arguments': ''})
    for event in events:
        for choice in event.get('choices', []):
            delta = choice.get('delta', choice.get('message', {})) or {}
            for call in delta.get('tool_calls', []):
                item = calls[(choice.get('index', 0), call.get('index', 0))]
                function = call.get('function', {})
                item['name'] += function.get('name', '')
                item['arguments'] += function.get('arguments', '')
    for call in calls.values():
        assert call['name'] in definitions
        arguments = json.loads(call['arguments'])
        assert isinstance(arguments, dict)
        assert set(definitions[call['name']]['parameters'].get('required', [])) <= arguments.keys()
live = json.loads((ROOT / 'live/results.json').read_text())
assert len(live) == 14
assert sum(row['variant'] == 'fixed' for row in live) == 4
for row in live:
    body = (ROOT / 'live/responses' / (row['case'] + '.body')).read_bytes()
    assert hashlib.sha256(body).hexdigest() == row['body_sha256']
    if row['variant'] == 'fixed' and row['kind'] == 'tools':
        assert row['upstream_tool_deltas'] == row['downstream_tool_deltas'] > 0
        assert row['valid_downstream_calls'] >= 1
        assert row['downstream_finish'] == ['tool_calls'] and row['downstream_done'] == 1
for name, digest in json.loads((ROOT / 'tested-source-hashes.json').read_text())['wasm'].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
assert json.loads((runtime / 'summary.json').read_text())['status'] == 'passed'
assert json.loads((ROOT / 'live/summary.json').read_text())['status'] == 'passed'
for path in [runtime / 'cleanup.json', ROOT / 'live/cleanup.json']:
    assert not any(json.loads(path.read_text()).values())
print(json.dumps({'synthetic_requests_checked': len(rows), 'live_requests_checked': len(live),
                  'wasm_hashes_valid': True, 'status': 'passed'}, indent=2))
