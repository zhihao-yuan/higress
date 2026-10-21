"""Exercise actual deny checks around protocol barriers in pinned Envoy/WASM."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

import runtime_common as common

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'deny-evidence'
EVIDENCE.mkdir(exist_ok=True)
NETWORK = 'higress-masking-review2-deny-20261021'
FIXTURE = NETWORK + '-fixture'
common.NETWORK = NETWORK
common.FIXTURE = FIXTURE
common.CONFIG['deny_words'] = ['FORBIDDEN']
run = common.run
containers = []
results = []

def log_count(name):
    return run(['docker', 'logs', name]).count('custom deny word FORBIDDEN matched')

try:
    run(['docker', 'network', 'create', NETWORK])
    containers.append(FIXTURE)
    run(['docker', 'run', '-d', '--platform', 'linux/amd64', '--name', FIXTURE,
         '--network', NETWORK, '-v', str(ROOT) + ':/lab:ro', '-v', str(EVIDENCE) + ':/evidence',
         '--entrypoint', 'python3', common.PYTHON, '/lab/fixture.py'])
    for mode, module in [('bypass', None), ('pre_review', 'pre-review.wasm'), ('fixed', 'fixed.wasm')]:
        name = NETWORK + '-' + mode
        config = common.config(module is not None)
        hcm = config['static_resources']['listeners'][0]['filter_chains'][0]['filters'][0]['typed_config']
        hcm['access_log'] = [{'name': 'envoy.access_loggers.file', 'typed_config': {
            '@type': 'type.googleapis.com/envoy.extensions.access_loggers.file.v3.FileAccessLog',
            'path': '/dev/stdout', 'log_format': {'json_format': {
                'case': '%REQ(X-TEST-CASE)%', 'status': '%RESPONSE_CODE%', 'bytes': '%BYTES_SENT%'}}}}]
        if module:
            hcm['http_filters'][0]['typed_config']['config']['vm_config']['code']['local']['filename'] = '/lab/' + module
        file = ROOT / ('deny-' + mode + '.json')
        file.write_text(json.dumps(config, indent=2))
        containers.append(name)
        run(['docker', 'run', '-d', '--platform', 'linux/amd64', '--name', name,
             '--network', NETWORK, '-v', str(ROOT) + ':/lab:ro', '-p', '127.0.0.1::10000',
             '--entrypoint', '/usr/local/bin/envoy', common.GATEWAY,
             '-c', '/lab/' + file.name, '--concurrency', '1', '--log-level', 'info'])
        port = run(['docker', 'port', name, '10000/tcp']).split(':')[-1]
        for _ in range(100):
            ready = subprocess.run(['docker', 'exec', name, 'curl', '-sf', 'http://127.0.0.1:15000/ready'], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(.2)
        else:
            raise RuntimeError('Envoy not ready: ' + name)
        for scenario in ['deny_across_barrier', 'deny_before_prefix']:
            for delivery in ['single', 'frames', 'fragment17', 'prefix1']:
                for repeat in [1, 2]:
                    case = '-'.join([mode, scenario, delivery, str(repeat)])
                    request = {'model': 'public-fixture', 'stream': True,
                        'messages': [{'role': 'user', 'content': 'For DEMO_SECRET find demo info'}],
                        'tools': [{'type': 'function', 'function': {'name': 'read', 'parameters': {
                            'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}}],
                        'tool_choice': 'auto', 'parallel_tool_calls': True}
                    req = EVIDENCE / (case + '.request.json')
                    req.write_text(json.dumps(request, indent=2))
                    before = log_count(name)
                    outcome = subprocess.run(['curl', '-sS', '-N', '--connect-timeout', '3', '--max-time', '40',
                        'http://127.0.0.1:' + port + '/v1/chat/completions', '-H', 'Content-Type: application/json',
                        '-H', 'X-Test-Case: ' + case, '-H', 'X-Test-Scenario: ' + scenario,
                        '-H', 'X-Test-Delivery: ' + delivery, '--data-binary', '@' + str(req),
                        '-D', str(EVIDENCE / (case + '.headers')), '-o', str(EVIDENCE / (case + '.body')),
                        '-w', '%{http_code}'], capture_output=True, text=True)
                    assert outcome.returncode == 0 and outcome.stdout == '200', (case, outcome.stdout, outcome.stderr)
                    upstream = json.loads((EVIDENCE / (case + '.upstream-request.json')).read_text())
                    raw = (EVIDENCE / (case + '.body')).read_text()
                    expected = (EVIDENCE / (case + '.upstream-response')).read_text()
                    actual_text = ''.join(common.parse(raw, True)['texts'].values())
                    expected_text = ''.join(common.parse(expected, True)['texts'].values())
                    result = {'case': case, 'variant': mode, 'scenario': scenario,
                        'delivery': delivery, 'repeat': repeat, 'deny_check_matched': log_count(name) > before,
                        'forbidden_in_upstream': 'FORBIDDEN' in expected_text,
                        'forbidden_in_client': 'FORBIDDEN' in actual_text,
                        'tools_definitions_preserved': all(upstream[key] == request[key] for key in ['tools', 'tool_choice', 'parallel_tool_calls']),
                        'mask_active': upstream['messages'][0]['content'] == request['messages'][0]['content'].replace('DEMO_SECRET', 'MASKED_TOKEN') if module else upstream == request,
                        'body_sha256': hashlib.sha256(raw.encode()).hexdigest()}
                    results.append(result)
                    (EVIDENCE / 'results.json').write_text(json.dumps(results, indent=2))
                    print(json.dumps(result), flush=True)
                    assert result['forbidden_in_upstream'] and result['tools_definitions_preserved'] and result['mask_active'], result
                    if mode == 'bypass':
                        assert raw == expected and result['forbidden_in_client'], result
                    if mode == 'fixed':
                        assert result['deny_check_matched'] and not result['forbidden_in_client'], result
        stats = run(['docker', 'exec', name, 'curl', '-sf', 'http://127.0.0.1:15000/stats?filter=wasm'])
        (EVIDENCE / (mode + '.stats.txt')).write_text(stats)
        for line in stats.splitlines():
            if any(key in line for key in ['crash_total', 'worker_fail_open_skip_total', 'worker_uninitialized']):
                assert line.rsplit(': ', 1)[1] == '0', line
        (EVIDENCE / (mode + '.envoy.log')).write_text(run(['docker', 'logs', name]))
        run(['docker', 'rm', '-f', name])
        containers.remove(name)
    broken = [row for row in results if row['variant'] == 'pre_review' and row['scenario'] == 'deny_across_barrier' and row['forbidden_in_client']]
    assert broken, 'Pre-review module did not reproduce denial gap'
    summary = {'requests': len(results), 'fixed_cases': sum(row['variant'] == 'fixed' for row in results),
        'pre_review_same_choice_denial_bypasses': len(broken), 'status': 'passed',
        'tools_executed': False, 'real_model_calls': 0,
        'note': 'Checks actual deny-word log and absence of the forbidden text; synthetic denial termination is outside this PR.'}
    (EVIDENCE / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
finally:
    for name in containers:
        (EVIDENCE / (name + '.envoy.log')).write_text(run(['docker', 'logs', name]))
        run(['docker', 'rm', '-f', name])
    run(['docker', 'network', 'rm', NETWORK])
    cleanup = {'containers_remaining': run(['docker', 'ps', '-aq', '--filter', 'name=' + NETWORK]),
        'network_remaining': run(['docker', 'network', 'ls', '-q', '--filter', 'name=' + NETWORK])}
    (EVIDENCE / 'cleanup.json').write_text(json.dumps(cleanup, indent=2))
    assert not any(cleanup.values()), cleanup
