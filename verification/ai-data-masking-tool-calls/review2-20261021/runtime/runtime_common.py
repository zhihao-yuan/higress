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

