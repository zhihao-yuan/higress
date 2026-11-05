"""Original/fixed Wasm on official Envoy; deterministic SSE fixture, NOT a model.
Client-observed first chunks order the two responses without timing sleeps.
"""
import concurrent.futures
import hashlib
import http.client
import json
import pathlib
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent
IMAGE = 'higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299'
TEMPLATE = ROOT / 'envoy-template.json'
CASES = {}
CONTAINERS = []

def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True, text=True, timeout=60).stdout.strip()

def event(kind, **fields):
    return ('data: ' + json.dumps(dict(type=kind, **fields), separators=(',', ':')) + '\n\n').encode()

def events(role):
    a = role == 'a'
    start = event('message_start', message=dict(id='msg_'+role, role='assistant', content=[], model='fixture-model', usage=dict(input_tokens=10 if a else 200, output_tokens=0, service_tier='standard' if a else 'priority')))
    if a:
        middle = [event('content_block_delta', index=0, delta=dict(type='text_delta', text='answer a'))]
    else:
        middle = [event('content_block_start', index=0, content_block=dict(type='tool_use', id='call_b', name='weather', input={})), event('content_block_delta', index=0, delta=dict(type='input_json_delta', partial_json='{"city":"Beijing"}'))]
    return [start, *middle, event('message_delta', delta=dict(stop_reason='end_turn' if a else 'tool_use'), usage=dict(output_tokens=3 if a else 5)), event('message_stop')]

class Fixture(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass
    def do_POST(self):
        label = self.headers['x-observation-id']
        case_name, role = label.rsplit('-', 1)
        case = CASES[case_name]
        if self.headers.get('Transfer-Encoding','').lower()=='chunked':
            parts=[]
            while True:
                size=int(self.rfile.readline().split(b';',1)[0],16)
                if size==0:
                    while self.rfile.readline() not in (b'\r\n',b'\n',b''):
                        pass
                    break
                parts.append(self.rfile.read(size))
                assert self.rfile.read(2)==b'\r\n'
            body=b''.join(parts)
        else:
            body = self.rfile.read(int(self.headers.get('Content-Length','0')))
        folder = ROOT / 'gateway' / case_name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (role+'.upstream.request.json')).write_bytes(body)
        frames = events(role)
        (folder / (role+'.upstream.sse')).write_bytes(b''.join(frames))
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Transfer-Encoding', 'chunked')
        self.end_headers()
        def send(frame):
            self.wfile.write(('%x\r\n' % len(frame)).encode()+frame+b'\r\n')
            self.wfile.flush()
        try:
            send(frames[0])
            if case['parallel']:
                wait_for = case['b_started'] if role == 'a' else case['a_done']
                if not wait_for.wait(20):
                    raise TimeoutError('client-observed interleaving handshake timed out: '+label)
            for frame in frames[1:]:
                send(frame)
            self.wfile.write(b'0\r\n\r\n')
            self.wfile.flush()
        except Exception as exc:
            case['errors'].append(str(exc))
            self.close_connection = True

def request(port, case_name, role):
    case = CASES[case_name]
    if role == 'b' and not case['a_started'].wait(20):
        raise TimeoutError('A did not emit its first client chunk')
    body = dict(model='fixture-model', messages=[dict(role='user', content='fixture '+role)], stream=True)
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=25)
    conn.request('POST', '/v1/chat/completions', json.dumps(body), {'Content-Type':'application/json', 'x-observation-id':case_name+'-'+role})
    response = conn.getresponse()
    raw = bytearray()
    line = bytearray()
    chunks = []
    try:
        while True:
            char = response.read(1)
            if not char:
                break
            raw.extend(char)
            line.extend(char)
            if char != b'\n':
                continue
            data = bytes(line).strip()
            line.clear()
            if data.startswith(b'data:') and data != b'data: [DONE]':
                chunks.append(json.loads(data[5:].strip()))
                case[role+'_started'].set()
    finally:
        conn.close()
        case[role+'_done'].set()
    folder = ROOT / 'gateway' / case_name
    folder.mkdir(parents=True,exist_ok=True)
    (folder/(role+'.client.sse')).write_bytes(raw)
    (folder/(role+'.client.request.json')).write_text(json.dumps(body,indent=2)+'\n')
    (folder/(role+'.client.headers.json')).write_text(json.dumps(dict(status=response.status,headers=response.getheaders()),indent=2)+'\n')
    assert response.status==200 and chunks, (case_name,response.status,bytes(raw).decode(errors='replace'))
    ids = sorted({c.get('id') for c in chunks})
    tiers = sorted({c.get('service_tier') for c in chunks})
    usage = [c['usage'] for c in chunks if c.get('usage')][-1]
    expected = dict(prompt_tokens=10 if role=='a' else 200, completion_tokens=3 if role=='a' else 5, total_tokens=13 if role=='a' else 205)
    text = ''.join(str(choice.get('delta',{}).get('content') or '') for c in chunks for choice in c.get('choices',[]))
    calls = [call for c in chunks for choice in c.get('choices',[]) for call in choice.get('delta',{}).get('tool_calls',[])]
    arguments = ''.join(call.get('function',{}).get('arguments','') for call in calls)
    payload_ok = text=='answer a' if role=='a' else arguments=='{"city":"Beijing"}' and any(c.get('id')=='call_b' and c.get('function',{}).get('name')=='weather' for c in calls)
    return dict(case=case_name,role=role,status=response.status,ids=ids,service_tiers=tiers,usage=usage,expected_usage=expected,payload_preserved=payload_ok,correct=response.status==200 and ids==['msg_'+role] and tiers==['standard' if role=='a' else 'priority'] and usage==expected and payload_ok)

def create_gateway(label, upstream_port):
    folder = ROOT / 'gateway' / label
    folder.mkdir(parents=True,exist_ok=True)
    cfg = json.loads(TEMPLATE.read_text())
    hcm = cfg['static_resources']['listeners'][0]['filter_chains'][0]['filters'][0]['typed_config']
    hcm['http_filters'] = [f for f in hcm['http_filters'] if f['name']!='envoy.filters.http.tap']
    wasm = hcm['http_filters'][0]['typed_config']['config']
    wasm['vm_config']['code']['local']['filename']='/lab/plugin.wasm'
    wasm['configuration']['value']=json.dumps(dict(provider=dict(type='claude',apiTokens=['fixture-placeholder'],modelMapping={'*':'fixture-model'})))
    cfg['static_resources']['clusters'][0]['load_assignment']['endpoints'][0]['lb_endpoints'][0]['endpoint']['address']['socket_address']['port_value']=upstream_port
    cfg['admin']['address']['socket_address']['address']='0.0.0.0'
    (folder/'envoy.json').write_text(json.dumps(cfg,indent=2)+'\n')
    shutil.copyfile(ROOT/(label+'.wasm'),folder/'plugin.wasm')
    name='claude-isolation-'+label+'-'+str(time.time_ns())
    docker('run','-d','--name',name,'-p','127.0.0.1::10000','-p','127.0.0.1::15000','-v',str(folder)+':/lab:ro','--entrypoint','/usr/local/bin/envoy',IMAGE,'-c','/lab/envoy.json','--concurrency','1','--log-level','warning')
    CONTAINERS.append(name)
    port=int(docker('port',name,'10000/tcp').rsplit(':',1)[1])
    admin=int(docker('port',name,'15000/tcp').rsplit(':',1)[1])
    for _ in range(100):
        try:
            c=http.client.HTTPConnection('127.0.0.1',admin,timeout=1);c.request('GET','/ready');r=c.getresponse();r.read();c.close()
            if r.status==200:
                return name,port,admin,folder
        except OSError:
            pass
        time.sleep(.1)
    raise RuntimeError('gateway did not become ready: '+name)

def main():
    server=ThreadingHTTPServer(('0.0.0.0',0),Fixture)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    results=[]
    try:
        for label in ('baseline','fixed'):
            name,port,admin,folder=create_gateway(label,server.server_port)
            for mode in ('control','parallel'):
                key=label+'-'+mode
                CASES[key]=dict(parallel=mode=='parallel',a_started=threading.Event(),b_started=threading.Event(),a_done=threading.Event(),b_done=threading.Event(),errors=[])
                if mode=='control':
                    results.append(request(port,key,'a'))
                else:
                    with concurrent.futures.ThreadPoolExecutor(2) as pool:
                        futures=[pool.submit(request,port,key,role) for role in ('a','b')]
                        results.extend(f.result() for f in futures)
                assert not CASES[key]['errors'],CASES[key]['errors']
            c=http.client.HTTPConnection('127.0.0.1',admin,timeout=5);c.request('GET','/stats?filter=wasm');response=c.getresponse();stats=response.read().decode();c.close()
            (folder/'wasm-stats.txt').write_text(stats)
            (folder/'envoy.log').write_text(docker('logs',name))
            for line in stats.splitlines():
                if any(k in line for k in ('crash_total','worker_fail_open_skip_total','worker_uninitialized','rebuild_memory_total')):
                    assert line.rsplit(':',1)[1].strip()=='0',line
        assert all(r['correct'] for r in results if r['case'].endswith('control') or r['case'].startswith('fixed'))
        assert any(not r['correct'] for r in results if r['case']=='baseline-parallel')
        (ROOT/'gateway-results.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(results,indent=2))
    finally:
        for name in CONTAINERS:
            p=subprocess.run(['docker','logs',name],capture_output=True,text=True)
            (ROOT/'gateway'/(name+'.log')).write_text(p.stdout+p.stderr)
            subprocess.run(['docker','rm','-f',name],capture_output=True)
        server.shutdown();server.server_close()
        (ROOT/'gateway-cleanup.json').write_text(json.dumps({'containers_removed':CONTAINERS,'fixture_closed':True},indent=2)+'\n')

if __name__=='__main__':
    main()
