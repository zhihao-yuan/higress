"""Reproduce JSON number precision loss in the unmodified transformer plugin."""
import copy,hashlib,http.client,json,re,socket,subprocess,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parent
IMAGE='higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299'
BIG=9007199254740993
CONFIG={'reqRules':[{'operate':'rename','body':[{'oldKey':'identifier','newKey':'renamed'}]},{'operate':'map','mapSource':'body','body':[{'fromKey':'identifier','toKey':'copied'}]}]}
CASES={'large':BIG,'nested-large':{'items':[BIG]},'small':42,'string':str(BIG)}
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))
def sha(raw):return hashlib.sha256(raw).hexdigest()

def run(label):
    folder=ROOT/'runtime'/label;folder.mkdir(parents=True,exist_ok=False)
    events=[];commands=[];rows=[];ports=[];created=False
    def docker(*args):
        result=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=60)
        commands.append(dict(argv=['docker',*args],exit=result.returncode,stdout=result.stdout,stderr=result.stderr))
        if result.returncode:raise RuntimeError(result.stderr)
        return result.stdout.strip()
    class Echo(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_POST(self):
            if self.headers.get('transfer-encoding','').lower()=='chunked':
                parts=[]
                while True:
                    size=int(self.rfile.readline().split(b';')[0],16)
                    if size==0:
                        while self.rfile.readline() not in (b'\r\n',b'\n',b''):pass
                        break
                    parts.append(self.rfile.read(size));assert self.rfile.read(2)==b'\r\n'
                raw=b''.join(parts)
            else:raw=self.rfile.read(int(self.headers.get('content-length','0')))
            events.append(dict(observation=self.headers['x-observation-id'],raw_body=raw.decode(),headers=list(self.headers.items())))
            self.send_response(200);self.send_header('content-type','application/json');self.send_header('content-length',str(len(raw)));self.end_headers();self.wfile.write(raw);self.wfile.flush()
    server=ThreadingHTTPServer(('0.0.0.0',0),Echo);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    cfg=json.loads((ROOT/'envoy-template.json').read_text());listener=cfg['static_resources']['listeners'][0];hcm=listener['filter_chains'][0]['filters'][0]['typed_config'];plugin=hcm['http_filters'][0]['typed_config']['config'];plugin['name']='transformer';plugin['vm_config']['vm_id']='number-precision';plugin['vm_config']['code']['local']['filename']='/modules/transformer.wasm';plugin['configuration']['value']=json.dumps(CONFIG)
    hcm['access_log'][0]['typed_config']['log_format']['text_format_source']['inline_string']='OBS id=%REQ(X-OBSERVATION-ID)% status=%RESPONSE_CODE% flags=%RESPONSE_FLAGS%\n'
    bypass=copy.deepcopy(listener);bypass['name']='bypass';bypass['address']['socket_address']['port_value']=10001;bypass['filter_chains'][0]['filters'][0]['typed_config']['http_filters']=hcm['http_filters'][-1:];cfg['static_resources']['listeners'].append(bypass)
    cfg['static_resources']['clusters'][0]['load_assignment']['endpoints'][0]['lb_endpoints'][0]['endpoint']['address']['socket_address']['port_value']=server.server_port
    (folder/'envoy.json').write_text(json.dumps(cfg,indent=2)+'\n');(folder/'plugin-config.json').write_text(json.dumps(CONFIG,indent=2)+'\n')
    name='transformer-number-'+str(time.time_ns())
    def get(port,path):
        client=http.client.HTTPConnection('127.0.0.1',port,timeout=3);client.request('GET',path);response=client.getresponse();raw=response.read();client.close();return response.status,raw
    try:
        docker('run','-d','--name',name,'--cpus','1','--memory','768m','-p','127.0.0.1::10000','-p','127.0.0.1::10001','-p','127.0.0.1::15000','-v',str(folder)+':/lab:ro','-v',str(ROOT)+':/modules:ro','--entrypoint','/usr/local/bin/envoy',IMAGE,'-c','/lab/envoy.json','--concurrency','1','--log-level','info','--file-flush-interval-msec','100');created=True
        ports=[int(docker('port',name,str(n)+'/tcp').rsplit(':',1)[1]) for n in [10000,10001,15000]]
        for _ in range(150):
            try:
                if get(ports[2],'/ready')[0]==200:break
            except OSError:pass
            time.sleep(.1)
        else:raise RuntimeError('gateway not ready')
        for case,value in CASES.items():
            for route in ['bypass','plugin']:
                for i in range(3):
                    obs=f'{label}-{case}-{route}-{i}';request=canonical({'identifier':value}).encode();before=len(events);client=http.client.HTTPConnection('127.0.0.1',ports[route=='bypass'],timeout=10)
                    client.request('POST','/verify',request,{'content-type':'application/json','x-observation-id':obs});response=client.getresponse();raw=response.read();client.close();assert response.status==200 and len(events)==before+1
                    event=events[-1];assert event['observation']==obs and event['raw_body']==raw.decode();actual=json.loads(raw)
                    expected={'identifier':value} if route=='bypass' else {'renamed':value,'copied':value}
                    bad=route=='plugin' and case in ['large','nested-large']
                    observed_value=BIG-1 if case=='large' else {'items':[BIG-1]}
                    observed={'renamed':observed_value,'copied':observed_value} if bad else expected
                    assert canonical(actual)==canonical(observed),(case,route,actual)
                    assert (canonical(actual)!=canonical(expected))==bad
                    rows.append(dict(id=obs,case=case,route=route,status=response.status,request=request.decode(),response=raw.decode(),response_sha256=sha(raw),expected=expected,defect_reproduced=bad))
        status,raw=get(ports[2],'/stats?filter=wasm');assert status==200;stats=raw.decode();(folder/'stats.txt').write_text(stats)
        for suffix in ['crash_total','rebuild_total','worker_fail_open_skip_total','worker_uninitialized']:
            values=re.findall(r'\.'+suffix+r': (\d+)',stats);assert values and not any(map(int,values))
        (folder/'results.json').write_text(json.dumps(rows,indent=2)+'\n');(folder/'identity.json').write_text(json.dumps({'source_sha':json.loads((ROOT/'provenance.json').read_text())['source_sha'],'module_sha256':sha((ROOT/'transformer.wasm').read_bytes()),'harness_sha256':sha(Path(__file__).read_bytes()),'gateway_image':IMAGE},indent=2)+'\n')
        print(json.dumps(dict(label=label,requests=len(rows),defect_reproductions=sum(r['defect_reproduced'] for r in rows),assertions_passed=True)),flush=True)
    finally:
        (folder/'upstream-events.json').write_text(json.dumps(events,indent=2)+'\n')
        if created:
            logs=subprocess.run(['docker','logs',name],capture_output=True,text=True,timeout=15);(folder/'envoy.log').write_text(logs.stdout+logs.stderr);docker('rm','-f',name)
        server.shutdown();server.server_close();thread.join(5);closed=[]
        for port in ports+[server.server_port]:
            with socket.socket() as sock:sock.settimeout(.5);closed.append(sock.connect_ex(('127.0.0.1',port))!=0)
        absent=not docker('ps','-a','--filter','name=^/'+name+'$','--format','{{.Names}}');cleanup=dict(container_absent=absent,ports_closed=closed,thread_stopped=not thread.is_alive());(folder/'cleanup.json').write_text(json.dumps(cleanup,indent=2)+'\n');(folder/'commands.json').write_text(json.dumps(commands,indent=2)+'\n');assert absent and all(closed) and not thread.is_alive()
if __name__=='__main__':run(sys.argv[1])
