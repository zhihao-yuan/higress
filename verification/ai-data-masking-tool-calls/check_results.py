"""Check saved evidence without making HTTP or model requests."""
import collections
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent


def check_tools(request, raw, stream):
    definitions = {tool['function']['name']: tool['function'] for tool in request['tools']}
    events = []
    if stream:
        for line in raw.splitlines():
            if line.startswith('data:') and line[5:].strip() != '[DONE]':
                events.append(json.loads(line[5:]))
    else:
        events.append(json.loads(raw))
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
        assert call['name'] in definitions, call['name']
        arguments = json.loads(call['arguments'])
        assert isinstance(arguments, dict)
        assert set(definitions[call['name']]['parameters'].get('required', [])) <= arguments.keys()


directory = ROOT / 'runtime-evidence-final'
rows = json.loads((directory / 'results.json').read_text())
assert len(rows) == 246
assert collections.Counter(row['variant'] for row in rows) == {'bypass': 82, 'baseline': 82, 'fixed': 82}
for row in rows:
    ident = row['case']
    request = json.loads((directory / (ident + '.upstream-request.json')).read_text())
    upstream = (directory / (ident + '.upstream-response')).read_text()
    check_tools(request, upstream, row['stream'])
    body = (directory / (ident + '.body')).read_bytes()
    assert hashlib.sha256(body).hexdigest() == row['body_sha256']
    if row['variant'] == 'bypass':
        assert body == upstream.encode()
    if row['variant'] == 'fixed':
        assert all(row[key] for key in ['tool_deltas_equal', 'text_equal', 'finish_equal',
                                      'done_equal', 'errors_equal', 'usage_equal'])
        check_tools(request, body.decode(), row['stream'])
live = json.loads((ROOT / 'live/results.json').read_text())
assert len(live) == 14
assert sum(row['variant'] == 'fixed' for row in live) == 4
for row in live:
    body = (ROOT / 'live/responses' / (row['case'] + '.body')).read_bytes()
    assert hashlib.sha256(body).hexdigest() == row['body_sha256']
    if row['variant'] == 'fixed' and row['kind'] == 'tools':
        assert row['downstream_tool_deltas'] == row['upstream_tool_deltas'] == 3
        assert row['valid_downstream_calls'] == 1
        assert row['downstream_finish'] == ['tool_calls']
        assert row['downstream_done'] == 1
for name, digest in json.loads((ROOT / 'tested-source-hashes.json').read_text())['wasm'].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
for file in [directory / 'cleanup.json', ROOT / 'live/cleanup.json']:
    assert not any(json.loads(file.read_text()).values())
print(json.dumps({'saved_synthetic_requests_checked': len(rows), 'saved_live_requests_checked': len(live),
                  'declared_tool_names_and_required_parameters_valid': True, 'wasm_hashes_valid': True,
                  'status': 'passed'}, indent=2))
