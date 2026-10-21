"""Compare unmodified main and fixed WASM in a pinned official Envoy runtime.
Synthetic upstream only. No credentials, real model calls, or executed tools.
"""
import hashlib,json,pathlib,subprocess,time
ROOT=pathlib.Path(__file__).resolve().parent
EVIDENCE=ROOT/'runtime-evidence-review'
EVIDENCE.mkdir(exist_ok=True)
GATEWAY='higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299'
PYTHON='higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/wasm-rust-builder@sha256:31758209b0ab11bb81db4c07789d1b93072c46f63ecb10f1ee88863baf659d90'
CONFIG={'deny_openai':True,'deny_raw':False,'system_deny':False,'replace_roles':[{'regex':'DEMO_SECRET','type':'replace','restore':True,'value':'MASKED_TOKEN'}]}
NETWORK='higress-masking-review2-runtime-20261021'
FIXTURE=NETWORK+'-fixture'
CONTAINERS=[]
RESULTS=[]

def run(args):
    return subprocess.check_output(args, stderr=subprocess.STDOUT, text=True).strip()

def config(enabled):
    filters = []
    if enabled:
        filters.append({'name': 'envoy.filters.http.wasm', 'typed_config': {
            '@type': 'type.googleapis.com/envoy.extensions.filters.http.wasm.v3.Wasm',
            'config': {'name': 'ai-data-masking', 'fail_open': False,
                       'configuration': {'@type': 'type.googleapis.com/google.protobuf.StringValue',
                                         'value': json.dumps(CONFIG)},
                       'vm_config': {'runtime': 'envoy.wasm.runtime.v8',
                                     'code': {'local': {'filename': '/lab/official-2.0.3.wasm'}}}}}})
    filters.append({'name': 'envoy.filters.http.router', 'typed_config': {
        '@type': 'type.googleapis.com/envoy.extensions.filters.http.router.v3.Router'}})
    return {'static_resources': {
        'listeners': [{'name': 'lab', 'address': {'socket_address': {'address': '0.0.0.0', 'port_value': 10000}},
                       'filter_chains': [{'filters': [{'name': 'envoy.filters.network.http_connection_manager',
                           'typed_config': {'@type': 'type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager',
                               'stat_prefix': 'lab', 'route_config': {'name': 'lab', 'virtual_hosts': [
                                   {'name': 'all', 'domains': ['*'], 'routes': [
                                       {'match': {'prefix': '/'}, 'route': {'cluster': 'fixture'}}]}]},
                               'http_filters': filters}}]}]}],
        'clusters': [{'name': 'fixture', 'type': 'STRICT_DNS', 'connect_timeout': '2s',
                      'load_assignment': {'cluster_name': 'fixture', 'endpoints': [{'lb_endpoints': [
                          {'endpoint': {'address': {'socket_address': {'address': FIXTURE, 'port_value': 18080}}}}]}]}}]},
        'admin': {'access_log_path': '/tmp/admin.log', 'address': {'socket_address': {'address': '127.0.0.1', 'port_value': 15000}}}}

def parse(raw, stream):
    events = []; done = 0
    if stream:
        for line in raw.splitlines():
            if line.startswith('data:'):
                if line[5:].strip() == '[DONE]': done += 1
                else: events.append(json.loads(line[5:]))
    else: events = [json.loads(raw)]
    texts = {}; reasonings = {}; tools = []; tools_by_choice = {}; finishes = {}
    opaque = {'top': [], 'choice': [], 'delta': [], 'non_data': []}
    if stream:
        opaque['non_data'] = [line for line in raw.splitlines() if line and not line.startswith('data:')]
    for event in events:
        for key, value in event.items():
            if key not in ['id', 'object', 'created', 'model', 'system_fingerprint', 'choices', 'usage']:
                opaque['top'].append([key, value])
        for choice in event.get('choices', []):
            index = str(choice.get('index', 0))
            if choice.get('finish_reason'): finishes.setdefault(index, []).append(choice['finish_reason'])
            for key, value in choice.items():
                if key not in ['index', 'delta', 'message', 'finish_reason'] and not (key in ['logprobs', 'token_ids'] and value is None):
                    opaque['choice'].append([index, key, value])
            delta = choice.get('delta', choice.get('message', {})) or {}
            for key, value in delta.items():
                if key not in ['content', 'reasoning_content', 'tool_calls']:
                    opaque['delta'].append([index, key, value])
            if delta.get('content'): texts[index] = texts.get(index, '') + delta['content']
            if delta.get('reasoning_content'): reasonings[index] = reasonings.get(index, '') + delta['reasoning_content']
            if delta.get('tool_calls'):
                tools.extend(delta['tool_calls'])
                tools_by_choice.setdefault(index, []).extend(delta['tool_calls'])
    # Object member order is not part of JSON semantics. Preserve value order
    # for repeated fields while comparing different keys independently.
    for group in ['top', 'choice', 'delta']:
        opaque[group].sort(key=lambda item: json.dumps(item[:1] if group == 'top' else item[:2]))
    return {'events': len(events), 'texts': texts, 'reasonings': reasonings, 'tools': tools,
            'tools_by_choice': tools_by_choice, 'finishes': finishes, 'done': done, 'opaque': opaque,
            'errors': [event['error'] for event in events if event.get('error')],
            'usage': [event['usage'] for event in events if event.get('usage')]}


try:
    run(['docker', 'network', 'create', NETWORK])
    CONTAINERS.append(FIXTURE)
    run(['docker', 'run', '-d', '--name', FIXTURE, '--network', NETWORK,
         '-v', str(ROOT) + ':/lab:ro', '-v', str(EVIDENCE) + ':/evidence',
         '--entrypoint', 'python3', PYTHON, '/lab/fixture.py'])
    for mode, module in [('bypass', None), ('baseline', 'baseline.wasm'), ('pre_review', 'pre-review.wasm'), ('fixed', 'fixed.wasm')]:
        cn = NETWORK + '-' + mode
        cfg = config(module is not None)
        cfg['static_resources']['listeners'][0]['filter_chains'][0]['filters'][0]['typed_config']['access_log'] = [{
            'name': 'envoy.access_loggers.file', 'typed_config': {
                '@type': 'type.googleapis.com/envoy.extensions.access_loggers.file.v3.FileAccessLog',
                'path': '/dev/stdout', 'log_format': {'json_format': {
                    'case': '%REQ(X-TEST-CASE)%', 'status': '%RESPONSE_CODE%',
                    'bytes': '%BYTES_SENT%', 'flags': '%RESPONSE_FLAGS%', 'duration_ms': '%DURATION%'}}}}]
        if module:
            cfg['static_resources']['listeners'][0]['filter_chains'][0]['filters'][0]['typed_config']['http_filters'][0]['typed_config']['config']['vm_config']['code']['local']['filename'] = '/lab/' + module
        (ROOT / (mode + '.json')).write_text(json.dumps(cfg, indent=2))
        CONTAINERS.append(cn)
        run(['docker', 'run', '-d', '--name', cn, '--network', NETWORK,
             '-v', str(ROOT) + ':/lab:ro', '-p', '127.0.0.1::10000',
             '--entrypoint', '/usr/local/bin/envoy', GATEWAY,
             '-c', '/lab/' + mode + '.json', '--concurrency', '1', '--log-level', 'info'])
        port = run(['docker', 'port', cn, '10000/tcp']).split(':')[-1]
        (EVIDENCE / (mode + '.port.txt')).write_text(port)
        for _ in range(100):
            p = subprocess.run(['docker', 'exec', cn, 'curl', '-sf', 'http://127.0.0.1:15000/ready'], capture_output=True)
            if p.returncode == 0:
                break
            time.sleep(.2)
        else:
            raise RuntimeError('Envoy not ready: ' + cn)
        (EVIDENCE / (mode + '.envoy-version.txt')).write_text(run(['docker', 'exec', cn, '/usr/local/bin/envoy', '--version']))
        scenarios = ['tools_only', 'text_then_tools', 'two_tools', 'plain_text', 'long_tools',
                     'mixed_tools', 'terminal_null', 'terminal_missing', 'error', 'unterminated_text',
                     'multi_choice', 'metadata', 'finish_only', 'missing_done', 'error_after_finish',
                     'same_choice_barrier', 'same_choice_prefix']
        cases = [(s, d, True) for s in scenarios for d in ['single', 'frames', 'fragment17', 'prefix1']]
        cases.append(('nonstream_tools', 'single', False))
        for repeat in [1, 2]:
            for scenario, delivery, stream in cases:
                ident = mode + '-' + scenario + '-' + delivery + '-' + str(repeat)
                request = {'model': 'public-fixture', 'messages': [{'role': 'user', 'content': 'For DEMO_SECRET find demo info'}],
                           'stream': stream, 'tools': [{'type': 'function', 'function': {'name': 'read',
                           'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}}],
                           'tool_choice': 'auto', 'parallel_tool_calls': True}
                request['tools'].append({'type': 'function', 'function': {'name': 'search',
                    'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}}})
                if scenario == 'long_tools':
                    request['tools'][0]['function'] = {'name': 'write', 'parameters': {
                        'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}},
                        'required': ['path', 'content']}}
                req = EVIDENCE / (ident + '.request.json')
                req.write_text(json.dumps(request, indent=2))
                p = subprocess.run(['curl', '-sS', '-N', '--connect-timeout', '3', '--max-time', '40',
                                    'http://127.0.0.1:' + port + '/v1/chat/completions',
                                    '-H', 'Content-Type: application/json', '-H', 'X-Test-Case: ' + ident,
                                    '-H', 'X-Test-Scenario: ' + scenario, '-H', 'X-Test-Delivery: ' + delivery,
                                    '--data-binary', '@' + str(req), '-D', str(EVIDENCE / (ident + '.headers')),
                                    '-o', str(EVIDENCE / (ident + '.body')), '-w', '%{http_code}'], capture_output=True, text=True)
                assert p.returncode == 0 and p.stdout == '200', (ident, p.stdout, p.stderr)
                upstream = json.loads((EVIDENCE / (ident + '.upstream-request.json')).read_text())
                expected_raw = (EVIDENCE / (ident + '.upstream-response')).read_text()
                raw = (EVIDENCE / (ident + '.body')).read_text()
                expected, actual = parse(expected_raw, stream), parse(raw, stream)
                tools_ok = all(upstream[k] == request[k] for k in ['tools', 'tool_choice', 'parallel_tool_calls'])
                mask_ok = upstream['messages'][0]['content'] == request['messages'][0]['content'].replace('DEMO_SECRET', 'MASKED_TOKEN') if module else upstream == request
                expected_texts = {key: value.replace('MASKED_TOKEN', 'DEMO_SECRET') for key, value in expected['texts'].items()} if module else expected['texts']
                expected_reasonings = {key: value.replace('MASKED_TOKEN', 'DEMO_SECRET') for key, value in expected['reasonings'].items()} if module else expected['reasonings']
                text_ok = actual['texts'] == expected_texts and actual['reasonings'] == expected_reasonings
                expected_done = 1 if mode in ['fixed', 'pre_review'] and scenario == 'missing_done' else expected['done']
                result = {'case': ident, 'variant': mode, 'scenario': scenario, 'delivery': delivery, 'repeat': repeat,
                          'http': p.stdout, 'stream': stream, 'tools_definitions_preserved': tools_ok, 'mask_active': mask_ok,
                          'tool_deltas_equal': actual['tools_by_choice'] == expected['tools_by_choice'],
                          'upstream_tool_deltas': len(expected['tools']), 'downstream_tool_deltas': len(actual['tools']),
                          'text_equal': text_ok, 'finish_equal': actual['finishes'] == expected['finishes'],
                          'done_equal': actual['done'] == expected_done, 'metadata_equal': actual['opaque'] == expected['opaque'], 'errors_equal': actual['errors'] == expected['errors'],
                          'usage_equal': actual['usage'] == expected['usage'],
                          'upstream_finish': expected['finishes'], 'downstream_finish': actual['finishes'],
                          'upstream_done': expected['done'], 'downstream_done': actual['done'],
                          'body_sha256': hashlib.sha256(raw.encode()).hexdigest()}
                RESULTS.append(result)
                (EVIDENCE / 'results.json').write_text(json.dumps(RESULTS, indent=2))
                print(json.dumps(result), flush=True)
                assert tools_ok and mask_ok, result
                if mode == 'bypass':
                    assert raw == expected_raw, result
                if mode == 'fixed' or not stream:
                    assert all(result[k] for k in ['tool_deltas_equal', 'text_equal', 'finish_equal', 'done_equal', 'errors_equal', 'usage_equal', 'metadata_equal']), result
        stats = run(['docker', 'exec', cn, 'curl', '-sf', 'http://127.0.0.1:15000/stats?filter=wasm'])
        (EVIDENCE / (mode + '.stats.txt')).write_text(stats)
        for line in stats.splitlines():
            if any(k in line for k in ['crash_total', 'worker_fail_open_skip_total', 'worker_uninitialized']):
                assert line.rsplit(': ', 1)[1] == '0', line
        (EVIDENCE / (mode + '.config-dump.json')).write_text(run(['docker', 'exec', cn, 'curl', '-sf', 'http://127.0.0.1:15000/config_dump']))
        (EVIDENCE / (mode + '.envoy.log')).write_text(run(['docker', 'logs', cn]))
        run(['docker', 'rm', '-f', cn])
        CONTAINERS.remove(cn)
    broken = [r for r in RESULTS if r['variant'] == 'baseline' and r['upstream_tool_deltas'] and r['stream'] and not r['tool_deltas_equal']]
    assert broken, 'Baseline did not reproduce tool loss'
    summary = {'requests': len(RESULTS), 'baseline_tool_loss_cases': len(broken),
               'pre_review_same_choice_text_failures': sum(r['variant'] == 'pre_review' and r['scenario'] == 'same_choice_barrier' and not r['text_equal'] for r in RESULTS),
               'fixed_cases': sum(r['variant'] == 'fixed' for r in RESULTS),
               'pre_review_wasm_sha256': hashlib.sha256((ROOT / 'pre-review.wasm').read_bytes()).hexdigest(),
               'baseline_wasm_sha256': hashlib.sha256((ROOT / 'baseline.wasm').read_bytes()).hexdigest(),
               'fixed_wasm_sha256': hashlib.sha256((ROOT / 'fixed.wasm').read_bytes()).hexdigest(),
               'real_model_calls': 0, 'tools_executed': False, 'status': 'passed'}
    (EVIDENCE / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
finally:
    for cn in CONTAINERS:
        try:
            (EVIDENCE / (cn + '.envoy.log')).write_text(run(['docker', 'logs', cn]))
            run(['docker', 'rm', '-f', cn])
        except Exception as exc:
            print('cleanup error', cn, str(exc), flush=True)
    run(['docker', 'network', 'rm', NETWORK])
    cleanup = {'containers_remaining': run(['docker', 'ps', '-aq', '--filter', 'name=' + NETWORK]),
               'network_remaining': run(['docker', 'network', 'ls', '-q', '--filter', 'name=' + NETWORK])}
    (EVIDENCE / 'cleanup.json').write_text(json.dumps(cleanup, indent=2))
    assert not any(cleanup.values()), cleanup
