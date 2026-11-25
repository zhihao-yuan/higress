import copy, hashlib, http.client, json, re, socket, statistics, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VARIANT=__import__('sys').argv[1]
IMAGE = 'higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299'
EVENTS = []

def digest(b): return hashlib.sha256(b).hexdigest()
def command(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=60)
    COMMANDS.append(dict(args=list(args), exit=p.returncode, stdout=p.stdout, stderr=p.stderr))
    if p.returncode: raise RuntimeError(p.stderr)
    return p.stdout.strip()

def payload(case):
    index=int(case.split('-')[1])
    chunks=[{'id':'chat-sparse-fixture','model':'fixture','choices':[{'index':0,'delta':{'tool_calls':[{'index':index,'id':'call-fixed','type':'function','function':{'name':'weather','arguments':'{"city":"Beijing"}'}}]}}]}, {'id':'chat-sparse-fixture','choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]}]
    return (''.join('data: '+json.dumps(x,separators=(',',':'))+'\n\n' for x in chunks)+'data: [DONE]\n\n').encode(), 'text/event-stream'

class Fixture(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self,*args): pass
    def do_POST(self):
        if self.headers.get('Transfer-Encoding','').lower() == 'chunked':
            parts=[]
            while True:
                n=int(self.rfile.readline().split(b';')[0],16)
                if n==0:
                    while self.rfile.readline() not in (b'\r\n',b'\n',b''): pass
                    break
                parts.append(self.rfile.read(n)); assert self.rfile.read(2)==b'\r\n'
            body=b''.join(parts)
        else: body=self.rfile.read(int(self.headers.get('Content-Length','0')))
        case=self.headers['x-fixture-case']; data,ct=payload(case)
        EVENTS.append(dict(id=self.headers['x-observation-id'],case=case,body=body.decode(),response_sha256=digest(data)))
        self.send_response(200);self.send_header('Content-Type',ct);self.send_header('Content-Length',str(len(data)));self.end_headers()
        if 'fragmented' in case:
            for offset in range(0,len(data),17):
                self.wfile.write(data[offset:offset+17]);self.wfile.flush();time.sleep(.002)
        else: self.wfile.write(data);self.wfile.flush()

def get(port,path):
    c=http.client.HTTPConnection('127.0.0.1',port,timeout=10);c.request('GET',path);r=c.getresponse();b=r.read();c.close();return r.status,b

def run(kind,variant,label):
    global COMMANDS
    COMMANDS=[]; EVENTS.clear()
    folder=ROOT/'runtime'/label;folder.mkdir(parents=True,exist_ok=False)
    server=ThreadingHTTPServer(('0.0.0.0',0),Fixture);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    cfg=json.loads((ROOT/'envoy-template.json').read_text())
    listener=cfg['static_resources']['listeners'][0]
    hcm=listener['filter_chains'][0]['filters'][0]['typed_config'];plugin=hcm['http_filters'][0]['typed_config']['config']
    plugin['name']='ai-statistics' if kind=='statistics' else 'log-request-response'
    plugin['vm_config']['vm_id']=kind+'-'+variant
    plugin['vm_config']['code']['local']['filename']='/lab/plugin.wasm'
    conf={'attributes':[{'key':'tool_calls','apply_to_log':True}]} if kind=='statistics' else {'response':{'body':{'enabled':True,'maxSize':1048576,'contentTypes':['text/event-stream']}}}
    plugin['configuration']['value']=json.dumps(conf)
    field='ai_log' if kind=='statistics' else 'log-response-body'
    fmt='OBS id=%REQ(X-OBSERVATION-ID)% status=%RESPONSE_CODE% duration=%DURATION% value=%FILTER_STATE(wasm.'+field+':PLAIN)%\n'
    hcm['access_log'][0]['typed_config']['log_format']['text_format_source']['inline_string']=fmt
    bypass=copy.deepcopy(listener);bypass['name']='bypass';bypass['address']['socket_address']['port_value']=10001
    bypass['filter_chains'][0]['filters'][0]['typed_config']['http_filters']=hcm['http_filters'][-1:]
    cfg['static_resources']['listeners'].append(bypass)
    cfg['static_resources']['clusters'][0]['load_assignment']['endpoints'][0]['lb_endpoints'][0]['endpoint']['address']['socket_address']['port_value']=server.server_port
    (folder/'envoy.json').write_text(json.dumps(cfg,indent=2)+'\n');(folder/'plugin-config.json').write_text(json.dumps(conf,indent=2)+'\n')
    wasm=ROOT/(kind+'-'+variant+'.wasm' if kind!='statistics' else 'statistics-'+VARIANT+'.wasm')
    (folder/'plugin.wasm').write_bytes(wasm.read_bytes())
    name='higress-official-check-'+str(time.time_ns());created=False;ports=[];results=[];logs=''
    try:
        command('docker','run','-d','--name',name,'--cpus','1','--memory','768m','-p','127.0.0.1::10000','-p','127.0.0.1::10001','-p','127.0.0.1::15000','-v',str(folder)+':/lab:ro','--entrypoint','/usr/local/bin/envoy',IMAGE,'-c','/lab/envoy.json','--concurrency','1','--log-level','info','--file-flush-interval-msec','100');created=True
        ports=[int(command('docker','port',name,str(n)+'/tcp').rsplit(':',1)[1]) for n in [10000,10001,15000]]
        for _ in range(100):
            try:
                if get(ports[2],'/ready')[0]==200:break
            except OSError: pass
            time.sleep(.1)
        else:raise RuntimeError('gateway not ready')
        cases=['index-0','index-100000','index-1000000','index-10000000']
        count=3 if kind=='statistics' else 30
        for case in cases:
            expected,ct=payload(case)
            (folder/(case+'-upstream.body')).write_bytes(expected)
            for route in ['bypass','plugin']:
                conn=http.client.HTTPConnection('127.0.0.1',ports[route=='bypass'],timeout=15)
                for i in range(count):
                    obs=label+'-'+case+'-'+route+'-'+str(i);body=b'{"model":"fixture","messages":[{"role":"user","content":"weather?"}],"stream":true}'
                    start=time.perf_counter_ns();conn.request('POST','/v1/chat/completions',body,{'content-type':'application/json','x-observation-id':obs,'x-fixture-case':case});r=conn.getresponse();received=r.read();elapsed=time.perf_counter_ns()-start
                    assert r.status==200 and received==expected,(case,route,r.status,received[:100])
                    results.append(dict(id=obs,case=case,route=route,status=r.status,bytes=len(received),sha256=digest(received),elapsed_ns=elapsed,headers=r.getheaders()))
                    if i==0:(folder/(case+'-'+route+'.body')).write_bytes(received)
                conn.close()
        (folder/'stats.txt').write_bytes(get(ports[2],'/stats?filter=wasm')[1]);time.sleep(1.2)
        cmd=subprocess.run(['docker','logs',name],capture_output=True,text=True,timeout=15);logs=cmd.stdout+cmd.stderr
        observed={}
        for line in logs.splitlines():
            m=re.match(r'OBS id=(\S+) status=(\d+) duration=(\S+) value=(.*)',line)
            if m:
                obs,status,duration,value=m.groups();value=None if value=='-' else json.loads('"'+value+'"')
                observed[obs]=dict(status=int(status),duration=duration,value=json.loads(value) if kind=='statistics' and value is not None else value)
        for row in results:
            assert row['id'] in observed,('missing access log',row['id'])
            row['log']=observed[row['id']]
            if row['route']=='bypass': assert row['log']['value'] is None
            if kind=='statistics' and row['route']=='plugin':
                attrs=row['log']['value'];calls=attrs['tool_calls'];assert len(calls)==1 and calls[0]['function']['name']=='weather'
                assert calls[0].get('index',0)==int(row['case'].split('-')[1]);args=calls[0]['function']['arguments'];expected_args='{}{"city":"Beijing"}' if row['case'].startswith('empty-') else '{"city":"Beijing"}'
                assert args==expected_args,(row['id'],args)
                if not row['case'].startswith('empty-'): assert json.loads(args)=={'city':'Beijing'}
                else:
                    try: json.loads(args)
                    except json.JSONDecodeError: pass
                    else: raise AssertionError('expected malformed logged arguments')
            if kind=='logging' and row['route']=='plugin':
                want=payload(row['case'])[0].decode(errors='replace');assert row['log']['value']==want,('log bytes mismatch',row['id'])
        assert len(EVENTS)==len(results)
        assert not re.search(r'(?:panic:|wasm trap|Function: proxy_on_response_body failed)',logs,re.I)
        (folder/'identity.json').write_text(json.dumps(dict(image=IMAGE,wasm_sha256=digest(wasm.read_bytes()),kind=kind,variant=variant,source_sha=json.loads((ROOT/'identity.json').read_text())['source_sha'],harness_sha256=digest(Path(__file__).read_bytes())),indent=2)+'\n')
        (folder/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'label':label,'requests':len(results),'case_logs':{case:next(r['log']['value'] for r in results if r['case']==case and r['route']=='plugin') for case in cases}} if kind=='statistics' else {'label':label,'requests':len(results),'body_and_log_parity':True},ensure_ascii=False),flush=True)
    finally:
        (folder/'fixture-events.json').write_text(json.dumps(EVENTS,indent=2)+'\n')
        if created:
            cmd=subprocess.run(['docker','logs',name],capture_output=True,text=True,timeout=15);(folder/'envoy.log').write_text(cmd.stdout+cmd.stderr)
            command('docker','rm','-f',name)
        server.shutdown();server.server_close();thread.join(5)
        absent=not command('docker','ps','-a','--filter','name=^/'+name+'$','--format','{{.Names}}')
        closed=[]
        for port in ports+[server.server_port]:
            with socket.socket() as s:s.settimeout(1);closed.append(s.connect_ex(('127.0.0.1',port))!=0)
        cleanup=dict(container_absent=absent,ports_closed=closed,thread_stopped=not thread.is_alive())
        (folder/'cleanup.json').write_text(json.dumps(cleanup,indent=2)+'\n');(folder/'commands.json').write_text(json.dumps(COMMANDS,indent=2)+'\n')
        assert absent and all(closed) and not thread.is_alive(),cleanup
    return results

if __name__=='__main__':
    import sys
    run('statistics',VARIANT,sys.argv[2])
