"""Discovery through unmodified official Wasm, with bypass and positive controls."""
import argparse,copy,hashlib,http.client,json,re,socket,subprocess,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parent
IMAGE='higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299'
BIG=9007199254740993
VARIANT="baseline"
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def config(kind):
    if kind=='precision':return {'reqRules':[{'operate':'rename','body':[{'oldKey':'identifier','newKey':'renamed'}]},{'operate':'map','mapSource':'body','body':[{'fromKey':'identifier','toKey':'copied'}]}]}
    if kind=='self-rename':return {'reqRules':[{'operate':'rename','headers':[{'oldKey':'X-Client-Id','newKey':'x-client-id'},{'oldKey':'x-old','newKey':'x-new'}],'body':[{'oldKey':'label','newKey':'label'},{'oldKey':'old','newKey':'new'}]}]}
    if kind=='typed-dedupe':return {'reqRules':[{'operate':'dedupe','body':[{'key':'values','strategy':'RETAIN_UNIQUE'}]}]}
    return {'needReference':True,'referenceLocation':'tail' if kind=='search-tail' else 'head','searchFrom':[{'type':'bing','apiKey':'synthetic-local-key','serviceName':'search.static','servicePort':8080}]}
def cases(kind):
    if kind=='precision':return [('large',{'identifier':BIG},{}),('nested-large',{'identifier':{'items':[BIG]}},{}),('small',{'identifier':42},{}),('string',{'identifier':str(BIG)}, {})]
    if kind=='self-rename':return [('same-body',{'label':'keep','untouched':1},{}),('header-case',{'untouched':1},{'X-Client-Id':'client-123'}),('normal',{'old':'keep','untouched':1},{'x-old':'trace-123'})]
    if kind=='typed-dedupe':return [('mixed',{'values':[1,'1',True,'true']},{}),('object-string',{'values':[{'a':1},'{"a":1}']},{}),('strings',{'values':['a','a','b']},{}),('numbers',{'values':[1,1,2]}, {})]
    return [(name,{'model':'fixture','messages':[{'role':'user','content':'NOHITS' if name=='nohits-short' else 'Where is the source?'}],'stream':True},{}) for name in ['short','fragmented-short','boundary29','boundary30','unicode-short','nohits-short']]
def answer(case):return {'short':'hello','fragmented-short':'hello','boundary29':'x'*29,'boundary30':'x'*30,'unicode-short':'你好','nohits-short':'hello'}[case]
def sse(case):
    items=[{'id':'chat-fixture','choices':[{'index':0,'delta':{'role':'assistant'}}]},{'id':'chat-fixture','choices':[{'index':0,'delta':{'content':answer(case)}}]},{'id':'chat-fixture','choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
    return (''.join('data: '+canonical(x)+'\n\n' for x in items)+'data: [DONE]\n\n').encode()
def content(raw):
    pieces=[];done=0;finish=[]
    for frame in re.split(b'\r?\n\r?\n',raw):
        if not frame:continue
        assert frame.startswith(b'data:'),frame
        data=frame[5:].strip()
        if data==b'[DONE]':done+=1;continue
        obj=json.loads(data)
        for choice in obj.get('choices',[]):
            pieces.append(choice.get('delta',{}).get('content','') or '')
            if choice.get('finish_reason') is not None:finish.append(choice['finish_reason'])
    return ''.join(pieces),done,finish

def run(kind,iteration):
    label=VARIANT+'-'+str(iteration);folder=ROOT/'runtime'/label;folder.mkdir(parents=True,exist_ok=False)
    events=[];commands=[];results=[];ports=[];created=False
    def docker(*args):
        p=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=60);commands.append({'argv':['docker',*args],'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        if p.returncode:raise RuntimeError(p.stderr)
        return p.stdout.strip()
    class Fixture(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_GET(self):
            assert self.path.startswith('/v7.0/search?'),self.path
            events.append({'type':'search','path':self.path,'headers':list(self.headers.items()),'time_ns':time.monotonic_ns()})
            response={'webPages':{'value':[] if 'NOHITS' in self.path else [{'name':'Fixture source','url':'https://example.invalid/doc','snippet':'KNOWN_SEARCH_SNIPPET'}]}}
            data=canonical(response).encode();self.send_response(200);self.send_header('content-type','application/json');self.send_header('content-length',str(len(data)));self.end_headers();self.wfile.write(data);self.wfile.flush()
        def do_POST(self):
            if self.headers.get('transfer-encoding','').lower()=='chunked':
                parts=[]
                while True:
                    n=int(self.rfile.readline().split(b';')[0],16)
                    if n==0:
                        while self.rfile.readline() not in (b'\r\n',b'\n',b''):pass
                        break
                    parts.append(self.rfile.read(n));assert self.rfile.read(2)==b'\r\n'
                raw=b''.join(parts)
            else:raw=self.rfile.read(int(self.headers.get('content-length','0')))
            body=json.loads(raw);case=self.headers['x-fixture-case'];headers={k.lower():v for k,v in self.headers.items()}
            events.append({'type':'backend','observation':headers['x-observation-id'],'path':self.path,'headers':headers,'body':body,'raw_body':raw.decode(),'time_ns':time.monotonic_ns()})
            data=sse(case) if kind.startswith('search-') else canonical({'body':body,'headers':headers}).encode()
            self.send_response(200);self.send_header('content-type','text/event-stream' if kind.startswith('search-') else 'application/json');self.send_header('content-length',str(len(data)));self.end_headers()
            if case=='fragmented-short':
                for off in range(0,len(data),17):self.wfile.write(data[off:off+17]);self.wfile.flush();time.sleep(.003)
            else:self.wfile.write(data);self.wfile.flush()
    server=ThreadingHTTPServer(('0.0.0.0',0),Fixture);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    module='ai-search' if kind.startswith('search-') else 'transformer';cfg=json.loads((ROOT/'envoy-template.json').read_text());listener=cfg['static_resources']['listeners'][0];hcm=listener['filter_chains'][0]['filters'][0]['typed_config'];plugin=hcm['http_filters'][0]['typed_config']['config'];plugin['name']=module;plugin['vm_config']['vm_id']=label;plugin['vm_config']['code']['local']['filename']='/modules/'+module+'-'+VARIANT+'.wasm';plugin['configuration']['value']=json.dumps(config(kind));hcm['access_log'][0]['typed_config']['log_format']['text_format_source']['inline_string']='OBS id=%REQ(X-OBSERVATION-ID)% status=%RESPONSE_CODE% flags=%RESPONSE_FLAGS%\n'
    bypass=copy.deepcopy(listener);bypass['name']='bypass';bypass['address']['socket_address']['port_value']=10001;bypass['filter_chains'][0]['filters'][0]['typed_config']['http_filters']=hcm['http_filters'][-1:];cfg['static_resources']['listeners'].append(bypass)
    cluster=cfg['static_resources']['clusters'][0];cluster['load_assignment']['endpoints'][0]['lb_endpoints'][0]['endpoint']['address']['socket_address']['port_value']=server.server_port
    search=copy.deepcopy(cluster);search['name']='outbound|8080||search.static';search['load_assignment']['cluster_name']=search['name'];cfg['static_resources']['clusters'].append(search)
    (folder/'envoy.json').write_text(json.dumps(cfg,indent=2)+'\n');(folder/'plugin-config.json').write_text(json.dumps(config(kind),indent=2)+'\n')
    name='higress-new-discovery-'+label+'-'+str(time.time_ns())
    def get(port,path):
        c=http.client.HTTPConnection('127.0.0.1',port,timeout=3);c.request('GET',path);r=c.getresponse();b=r.read();c.close();return r.status,b
    try:
        docker('run','-d','--name',name,'--cpus','1','--memory','768m','-p','127.0.0.1::10000','-p','127.0.0.1::10001','-p','127.0.0.1::15000','-v',str(folder)+':/lab:ro','-v',str(ROOT)+':/modules:ro','--entrypoint','/usr/local/bin/envoy',IMAGE,'-c','/lab/envoy.json','--concurrency','1','--log-level','info','--file-flush-interval-msec','100');created=True
        ports=[int(docker('port',name,str(n)+'/tcp').rsplit(':',1)[1]) for n in [10000,10001,15000]]
        for _ in range(150):
            try:
                if get(ports[2],'/ready')[0]==200:break
            except OSError:pass
            time.sleep(.1)
        else:raise RuntimeError('gateway not ready')
        for case,body,extra_headers in cases(kind):
            for route in ['bypass','plugin']:
                for n in range(3):
                    obs=label+'-'+case+'-'+route+'-'+str(n);before=len(events);raw=canonical(body).encode();c=http.client.HTTPConnection('127.0.0.1',ports[route=='bypass'],timeout=10);c.request('POST','/v1/chat/completions',raw,{'content-type':'application/json','x-fixture-case':case,'x-observation-id':obs,**extra_headers});r=c.getresponse();received=r.read();c.close();assert r.status==200,(kind,case,route,r.status,received)
                    (folder/(obs+'.body')).write_bytes(received);observed=events[before:];backend=[x for x in observed if x['type']=='backend'];assert len(backend)==1 and backend[0]['observation']==obs,observed
                    row={'id':obs,'case':case,'route':route,'request':body,'request_headers':extra_headers,'status':r.status,'response_sha256':sha(received),'backend':backend[0],'search_calls':len([x for x in observed if x['type']=='search'])}
                    if kind.startswith('search-'):
                        text,done,finish=content(received);row.update(text=text,done_markers=done,finish_reasons=finish);assert done==1 and finish==['stop'],row
                        if route=='bypass':assert received==sse(case) and text==answer(case) and row['search_calls']==0,row
                        else:
                            assert row['search_calls']==1,row
                            if case=='nohits-short':assert text==answer(case) and canonical(backend[0]['body'])==canonical(body),row
                            else:
                                assert 'KNOWN_SEARCH_SNIPPET' in canonical(backend[0]['body']),row
                                missing=kind=='search-head' and len(answer(case).encode())<30
                                assert (text=='')==missing,row
                                if not missing:assert answer(case) in text and 'https://example.invalid/doc' in text,row
                    else:
                        obj=json.loads(received);assert canonical(obj['body'])==canonical(backend[0]['body']),row
                        if route=='bypass':assert canonical(obj['body'])==canonical(body),row
                        elif kind=='precision':
                            value=body['identifier'];want=value
                            if case=='large' and VARIANT=='baseline':want=BIG-1
                            if case=='nested-large' and VARIANT=='baseline':want={'items':[BIG-1]}
                            assert canonical(obj['body'])==canonical({'renamed':want,'copied':want}),row
                        elif kind=='self-rename':
                            if case=='same-body':assert obj['body']==(body if VARIANT=='fixed' else {'untouched':1}),row
                            if case=='header-case':assert (obj['headers'].get('x-client-id')=='client-123')==(VARIANT=='fixed'),row
                            if case=='normal':assert obj['body']=={'new':'keep','untouched':1} and obj['headers'].get('x-new')=='trace-123',row
                        elif kind=='typed-dedupe':
                            want=({'mixed':[1,'1',True,'true'],'object-string':[{'a':1},'{"a":1}'],'strings':['a','b'],'numbers':[1,2]} if VARIANT=='fixed' else {'mixed':[1,True],'object-string':{'a':1},'strings':['a','b'],'numbers':[1,2]})[case]
                            assert canonical(obj['body']['values'])==canonical(want),row
                        row['transformed']=obj
                    results.append(row)
        stats=get(ports[2],'/stats?filter=wasm')[1].decode();(folder/'stats.txt').write_text(stats)
        for suffix in ['crash_total','rebuild_total','worker_fail_open_skip_total','worker_uninitialized']:
            found=re.findall(r'\.'+suffix+r': (\d+)',stats);assert found and all(int(x)==0 for x in found),(suffix,found)
        (folder/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n');(folder/'identity.json').write_text(json.dumps({'source_sha':json.loads((ROOT/'identity.json').read_text())['source_sha'],'module':module,'wasm_sha256':sha((ROOT/(module+'-'+VARIANT+'.wasm')).read_bytes()),'image':IMAGE,'harness_sha256':sha(Path(__file__).read_bytes())},indent=2)+'\n')
        print(json.dumps({'label':label,'requests':len(results),'assertions_passed':True}),flush=True)
    finally:
        (folder/'fixture-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2)+'\n')
        if created:
            log=subprocess.run(['docker','logs',name],capture_output=True,text=True,timeout=15);(folder/'envoy.log').write_text(log.stdout+log.stderr);docker('rm','-f',name)
        server.shutdown();server.server_close();thread.join(5);closed=[]
        for port in ports+[server.server_port]:
            with socket.socket() as sock:sock.settimeout(.5);closed.append(sock.connect_ex(('127.0.0.1',port))!=0)
        absent=not docker('ps','-a','--filter','name=^/'+name+'$','--format','{{.Names}}');cleanup={'container_absent':absent,'ports_closed':closed,'thread_stopped':not thread.is_alive()};(folder/'cleanup.json').write_text(json.dumps(cleanup,indent=2)+'\n');(folder/'commands.json').write_text(json.dumps(commands,indent=2)+'\n');assert absent and all(closed) and not thread.is_alive()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--kind',choices=['precision','self-rename','typed-dedupe','search-head','search-tail'],required=True);parser.add_argument('--iteration',type=int,required=True);parser.add_argument('--variant',choices=['baseline','fixed'],required=True);args=parser.parse_args();VARIANT=args.variant;run(args.kind,args.iteration)
