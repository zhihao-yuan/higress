import copy,hashlib,http.client,json,re,socket,subprocess,sys,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

ROOT=Path(__file__).resolve().parent
IMAGE='higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299'
EVENTS=[];COMMANDS=[]
REQUEST=b'{"model":"fixture","messages":[{"role":"user","content":"hello"}],"stream":true}'
def digest(b):return hashlib.sha256(b).hexdigest()
def command(*args):
    p=subprocess.run(args,capture_output=True,text=True,timeout=60);COMMANDS.append(dict(args=args,exit=p.returncode,stdout=p.stdout,stderr=p.stderr))
    if p.returncode:raise RuntimeError(p.stderr)
    return p.stdout.strip()
def payload(case):
    if case.startswith('named'):lines=['event: custom','data: {"ok":true}']
    elif case.startswith('multiline'):lines=['data: {"value":','data: 1}']
    else:lines=['data: {"ok":true}']
    eol='\r\n' if 'crlf' in case else '\n'
    return (eol.join(lines)+eol+eol).encode()

def parse_sse(raw):
    # Minimal independent implementation of WHATWG line and dispatch rules.
    events=[];data=[];typ=''
    for line in re.split(r'\r\n|\r|\n',raw.decode()):
        if line=='':
            if data:events.append(dict(type=typ or 'message',data='\n'.join(data)))
            typ='';data=[];continue
        if line.startswith(':'):continue
        field,sep,value=line.partition(':')
        if value.startswith(' '):value=value[1:]
        if field=='data':data.append(value)
        elif field=='event':typ=value
    return events

class Fixture(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*a):pass
    def do_POST(self):
        if self.headers.get('Transfer-Encoding','').lower()=='chunked':
            parts=[]
            while True:
                n=int(self.rfile.readline().split(b';')[0],16)
                if n==0:
                    while self.rfile.readline() not in (b'\r\n',b'\n',b''):pass
                    break
                parts.append(self.rfile.read(n));assert self.rfile.read(2)==b'\r\n'
            body=b''.join(parts)
        else:body=self.rfile.read(int(self.headers.get('Content-Length','0')))
        assert json.loads(body)==json.loads(REQUEST)
        case=self.headers['x-fixture-case'];raw=payload(case)
        EVENTS.append(dict(id=self.headers['x-observation-id'],case=case,request=body.decode(),response_sha256=digest(raw)))
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(raw)));self.end_headers()
        if 'fragmented' in case:
            for b in raw:self.wfile.write(bytes([b]));self.wfile.flush();time.sleep(.003)
        else:self.wfile.write(raw);self.wfile.flush()

def get(port,path):
    c=http.client.HTTPConnection('127.0.0.1',port,timeout=5);c.request('GET',path);r=c.getresponse();b=r.read();c.close();return r.status,b

def run(label):
    folder=ROOT/'runtime'/label;folder.mkdir(parents=True,exist_ok=False)
    server=ThreadingHTTPServer(('0.0.0.0',0),Fixture);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    cfg=json.loads((ROOT.parent/'higress-adaptive-sampling-20261112/envoy-template.json').read_text())
    listener=cfg['static_resources']['listeners'][0];hcm=listener['filter_chains'][0]['filters'][0]['typed_config'];plugin=hcm['http_filters'][0]['typed_config']['config']
    plugin['name']='ai-data-masking';plugin['vm_config']['vm_id']='masking-crlf';conf={'deny_openai':True,'system_deny':False,'deny_words':['UNMATCHED_SYNTHETIC_WORD']}
    plugin['configuration']['value']=json.dumps(conf)
    hcm['access_log'][0]['typed_config']['log_format']['text_format_source']['inline_string']='OBS id=%REQ(X-OBSERVATION-ID)% status=%RESPONSE_CODE% flags=%RESPONSE_FLAGS%\n'
    bypass=copy.deepcopy(listener);bypass['name']='bypass';bypass['address']['socket_address']['port_value']=10001;bypass['filter_chains'][0]['filters'][0]['typed_config']['http_filters']=hcm['http_filters'][-1:];cfg['static_resources']['listeners'].append(bypass)
    cfg['static_resources']['clusters'][0]['load_assignment']['endpoints'][0]['lb_endpoints'][0]['endpoint']['address']['socket_address']['port_value']=server.server_port
    (folder/'envoy.json').write_text(json.dumps(cfg,indent=2)+'\n');(folder/'plugin-config.json').write_text(json.dumps(conf,indent=2)+'\n');wasm=(ROOT/'baseline.wasm').read_bytes();(folder/'plugin.wasm').write_bytes(wasm)
    name='higress-masking-crlf-'+str(time.time_ns());created=False;ports=[];results=[]
    try:
        command('docker','run','-d','--name',name,'--cpus','1','--memory','768m','-p','127.0.0.1::10000','-p','127.0.0.1::10001','-p','127.0.0.1::15000','-v',str(folder)+':/lab:ro','--entrypoint','/usr/local/bin/envoy',IMAGE,'-c','/lab/envoy.json','--concurrency','1','--log-level','info','--file-flush-interval-msec','100');created=True
        ports=[int(command('docker','port',name,str(n)+'/tcp').rsplit(':',1)[1]) for n in [10000,10001,15000]]
        for _ in range(100):
            try:
                if get(ports[2],'/ready')[0]==200:break
            except OSError:pass
            time.sleep(.1)
        else:raise RuntimeError('gateway not ready')
        for case in ['named-lf','named-crlf','named-crlf-fragmented','multiline-lf','multiline-crlf','dataonly-lf','dataonly-crlf']:
            original=payload(case);expected=parse_sse(original);(folder/(case+'-upstream.body')).write_bytes(original)
            for route in ['bypass','plugin']:
                for i in range(3):
                    obs=label+'-'+case+'-'+route+'-'+str(i);c=http.client.HTTPConnection('127.0.0.1',ports[route=='bypass'],timeout=10);c.request('POST','/v1/chat/completions',REQUEST,{'content-type':'application/json','x-observation-id':obs,'x-fixture-case':case});r=c.getresponse();body=r.read();c.close();actual=parse_sse(body)
                    if i==0:(folder/(case+'-'+route+'.body')).write_bytes(body)
                    row=dict(id=obs,case=case,route=route,status=r.status,headers=r.getheaders(),original_sha256=digest(original),body_sha256=digest(body),body=body.decode(),expected_events=expected,actual_events=actual);results.append(row)
                    assert r.status==200,row
                    defect=route=='plugin' and case in ['named-crlf','named-crlf-fragmented','multiline-crlf']
                    assert (actual!=expected)==defect,row
                    if route=='bypass':assert body==original
                    if defect and case.startswith('named'):assert actual==[dict(type='message',data='{"ok":true}')],row
                    if defect and case.startswith('multiline'):assert actual==[dict(type='message',data='{"value":'),dict(type='message',data='1}')],row
        (folder/'stats.txt').write_bytes(get(ports[2],'/stats?filter=wasm')[1]);time.sleep(.3)
        assert len(EVENTS)==len(results)
        (folder/'results.json').write_text(json.dumps(results,indent=2)+'\n');(folder/'identity.json').write_text(json.dumps(dict(image=IMAGE,wasm_sha256=digest(wasm),harness_sha256=digest(Path(__file__).read_bytes())),indent=2)+'\n')
        print(json.dumps(dict(label=label,requests=len(results),defect_plugin_requests=sum(x['actual_events']!=x['expected_events'] for x in results),assertions_passed=True)),flush=True)
    finally:
        (folder/'fixture-events.json').write_text(json.dumps(EVENTS,indent=2)+'\n')
        if created:
            logs=subprocess.run(['docker','logs',name],capture_output=True,text=True,timeout=15);(folder/'envoy.log').write_text(logs.stdout+logs.stderr);command('docker','rm','-f',name)
        server.shutdown();server.server_close();thread.join(5);absent=not command('docker','ps','-a','--filter','name=^/'+name+'$','--format','{{.Names}}');closed=[]
        for port in ports+[server.server_port]:
            with socket.socket() as s:s.settimeout(1);closed.append(s.connect_ex(('127.0.0.1',port))!=0)
        cleanup=dict(container_absent=absent,ports_closed=closed,thread_stopped=not thread.is_alive());(folder/'cleanup.json').write_text(json.dumps(cleanup,indent=2)+'\n');(folder/'commands.json').write_text(json.dumps(COMMANDS,indent=2)+'\n');assert absent and all(closed) and not thread.is_alive()
if __name__=='__main__':run(sys.argv[1])
