"""Approved Design #5346: original/fixed matrix and same-worker concurrency."""
import argparse, concurrent.futures, copy, hashlib, http.client, json, re, socket, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMAGE = 'higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299'
CASES = {'unique': (['a','b','c','d'],3), 'duplicate-safe': (['a','a','b','b'],2), 'duplicate': (['a','a','a','b'],3), 'identical': (['a','a','a'],None)}
ANSWER = b'{"choices":[{"message":{"role":"assistant","content":"fixture-answer"}}]}'
REQUEST = b'{"model":"fixture","messages":[{"role":"user","content":"hello"}],"stream":false}'
def sha(b): return hashlib.sha256(b).hexdigest()

def request(port, path, method='GET', body=None, timeout=3, observation=''):
    start = time.monotonic_ns(); c = http.client.HTTPConnection('127.0.0.1',port,timeout=timeout)
    try:
        c.request(method,path,body,{'content-type':'application/json','x-observation-id':observation})
        r = c.getresponse(); raw = r.read()
        return dict(status=r.status,body=raw.decode(),body_sha256=sha(raw),headers=r.getheaders(),start_ns=start,end_ns=time.monotonic_ns())
    except (OSError,TimeoutError) as err:
        return dict(error=type(err).__name__,detail=str(err),start_ns=start,end_ns=time.monotonic_ns())
    finally: c.close()

def run(variant, case, iteration):
    label = f'{variant}-{case}-{iteration}'; folder = ROOT/'runtime'/label; folder.mkdir(parents=True,exist_ok=False)
    commands=[]; events=[]; results=[]; ports=[]; created=False; failure=None; all_passed=False
    release=threading.Event(); trigger_arrived=threading.Event()
    def docker(*args):
        p=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=45)
        commands.append(dict(args=['docker',*args],exit=p.returncode,stdout=p.stdout,stderr=p.stderr))
        if p.returncode: raise RuntimeError(p.stderr)
        return p.stdout.strip()
    class Fixture(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args): pass
        def do_POST(self):
            if self.headers.get('Transfer-Encoding','').lower()=='chunked':
                chunks=[]
                while True:
                    n=int(self.rfile.readline().split(b';')[0],16)
                    if n==0:
                        while self.rfile.readline() not in (b'\r\n',b'\n',b''): pass
                        break
                    chunks.append(self.rfile.read(n)); assert self.rfile.read(2)==b'\r\n'
                body=b''.join(chunks)
            else: body=self.rfile.read(int(self.headers.get('content-length','0')))
            entry=dict(path=self.path,observation=self.headers.get('x-observation-id'),body=body.decode(),headers=list(self.headers.items()),arrived_ns=time.monotonic_ns())
            events.append(entry)
            if self.path=='/concurrent/trigger':
                trigger_arrived.set()
                entry['released']=release.wait(6)
                if not entry['released']: entry['hold_timeout']=True
            self.send_response(200);self.send_header('content-type','application/json');self.send_header('content-length',str(len(ANSWER)));self.end_headers();self.wfile.write(ANSWER);self.wfile.flush();entry['finished_ns']=time.monotonic_ns()
    server=ThreadingHTTPServer(('0.0.0.0',0),Fixture); server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
    services,choices=CASES[case]; broken=variant=='baseline' and case in ('duplicate','identical')
    concurrency=variant=='candidate' and case in ('duplicate','identical')
    conf=dict(lb_type='cluster',lb_policy='cluster_metrics',lb_config=dict(mode='AdaptiveScore',service_list=services))
    if choices is not None: conf['lb_config']['p2c_choices']=choices
    cfg=json.loads((ROOT/'envoy-template.json').read_text())
    listener=cfg['static_resources']['listeners'][0];hcm=listener['filter_chains'][0]['filters'][0]['typed_config'];plugin=hcm['http_filters'][0]['typed_config']['config'];plugin['name']='ai-load-balancer';plugin['vm_config']['vm_id']='adaptive-affected';plugin['vm_config']['code']['local']['filename']='/modules/'+variant+'.wasm';plugin['configuration']['value']=json.dumps(conf)
    route=hcm['route_config']['virtual_hosts'][0]['routes'][0]['route'];route.pop('cluster',None);route['cluster_header']='x-higress-target-cluster'
    hcm['access_log'][0]['typed_config']['log_format']['text_format_source']['inline_string']='observation=%REQ(X-OBSERVATION-ID)% status=%RESPONSE_CODE% flags=%RESPONSE_FLAGS%\n'
    health=copy.deepcopy(listener);health['name']='no-wasm-health';health['address']['socket_address']['port_value']=10001;hh=health['filter_chains'][0]['filters'][0]['typed_config'];hh['stat_prefix']='health';hh['http_filters']=hh['http_filters'][-1:];hr=hh['route_config']['virtual_hosts'][0]['routes'][0];hr.pop('route');hr['direct_response']={'status':200,'body':{'inline_string':'healthy'}};cfg['static_resources']['listeners'].append(health)
    if concurrency:
        normal=copy.deepcopy(listener);normal['name']='normal-wasm';normal['address']['socket_address']['port_value']=10002;nh=normal['filter_chains'][0]['filters'][0]['typed_config'];nh['stat_prefix']='normal';np=nh['http_filters'][0]['typed_config']['config'];np['vm_config']['vm_id']='adaptive-normal';np['configuration']['value']=json.dumps(dict(lb_type='cluster',lb_policy='cluster_metrics',lb_config=dict(mode='AdaptiveScore',service_list=['a','b','c','d'],p2c_choices=3)));cfg['static_resources']['listeners'].append(normal)
    for configured_listener in cfg['static_resources']['listeners']:
        chain=configured_listener['filter_chains'][0]['filters'][0]['typed_config']
        chain['http_filters'].insert(0,{'name':'envoy.filters.http.lua','typed_config':{'@type':'type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua','inline_code':'function envoy_on_request(h) h:logInfo("adaptive-worker-observation:" .. (h:headers():get("x-observation-id") or "none")) end'}})
    cluster=cfg['static_resources']['clusters'][0];cluster['load_assignment']['endpoints'][0]['lb_endpoints'][0]['endpoint']['address']['socket_address']['port_value']=server.server_port
    for svc in ['a','b','c','d']:
        extra=copy.deepcopy(cluster);extra['name']=svc;extra['load_assignment']['cluster_name']=svc;cfg['static_resources']['clusters'].append(extra)
    (folder/'envoy.json').write_text(json.dumps(cfg,indent=2)+'\n');(folder/'plugin-config.json').write_text(json.dumps(conf,indent=2)+'\n')
    name='adaptive-verify-'+label+'-'+str(time.time_ns());summary={}
    try:
        args=['run','-d','--name',name,'--cpus','1','--memory','768m']
        internal=[10000,10001,15000]+([10002] if concurrency else [])
        for port in internal: args.extend(['-p','127.0.0.1::'+str(port)])
        args.extend(['-v',str(folder)+':/lab:ro','-v',str(ROOT)+':/modules:ro','--entrypoint','/usr/local/bin/envoy',IMAGE,'-c','/lab/envoy.json','--concurrency','1','--log-level','info','--file-flush-interval-msec','100'])
        docker(*args);created=True;ports=[int(docker('port',name,str(n)+'/tcp').rsplit(':',1)[1]) for n in internal];proxy,healthy,admin=ports[:3]
        for _ in range(150):
            ready=request(admin,'/ready',timeout=.5)
            if ready.get('status')==200:break
            time.sleep(.1)
        else: raise RuntimeError(('gateway not ready',ready))
        before=request(healthy,'/health',observation=label+'-health-before');assert before.get('status')==200,before
        (folder/'before-stats.json').write_text(json.dumps(request(admin,'/stats?filter=wasm'),indent=2)+'\n')
        for i in range(1 if broken else 3):results.append(request(proxy,'/v1/chat/completions','POST',REQUEST,observation=label+'-matrix-'+str(i)))
        after=request(healthy,'/health',timeout=2,observation=label+'-health-after')
        if broken:
            assert results[0].get('error')=='TimeoutError' and after.get('error')=='TimeoutError',(results,after)
            assert not events,events
        else:
            assert all(r.get('status')==200 and r['body']==ANSWER.decode() for r in results),results
            assert after.get('status')==200 and len(events)==3,(after,events)
        concurrent_result=None
        if concurrency:
            probes=[];stop_probe=threading.Event();concurrent_start=time.monotonic_ns()
            def probe():
                index=0
                while not stop_probe.is_set():
                    row=request(healthy,'/health',timeout=1,observation=label+'-health-probe-'+str(index));probes.append(row);index+=1;stop_probe.wait(.02)
            prober=threading.Thread(target=probe,daemon=True);prober.start()
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
                    trigger=pool.submit(request,proxy,'/concurrent/trigger','POST',REQUEST,5,label+'-concurrent-trigger')
                    assert trigger_arrived.wait(4),'trigger did not arrive at upstream'
                    barrier=threading.Barrier(8)
                    def normal_request(i):
                        barrier.wait(timeout=3)
                        return request(ports[3],'/concurrent/normal/'+str(i),'POST',REQUEST,3,label+'-concurrent-normal-'+str(i))
                    normals=list(pool.map(normal_request,range(8)))
                    assert all(r.get('status')==200 and r['body']==ANSWER.decode() for r in normals),normals
                    assert not trigger.done(),'trigger must remain in-flight throughout normal traffic'
                    deadline=time.monotonic()+2
                    while len(probes)<3 and time.monotonic()<deadline:time.sleep(.01)
                    released_ns=time.monotonic_ns();release.set();trigger_result=trigger.result(timeout=4)
                    assert trigger_result.get('status')==200 and trigger_result['body']==ANSWER.decode(),trigger_result
                post_probes=[request(healthy,'/health',observation=label+'-health-post-'+str(i)) for i in range(3)]
            finally:
                release.set();stop_probe.set();prober.join(3)
            assert len(probes)>=3 and all(r.get('status')==200 for r in probes+post_probes),(probes,post_probes)
            arrivals=[e for e in events if e['path'].startswith('/concurrent/')]
            assert len(arrivals)==9 and len({e['observation'] for e in arrivals})==9,arrivals
            trigger_event=next(e for e in arrivals if e['path']=='/concurrent/trigger');assert trigger_event['released'] and 'hold_timeout' not in trigger_event
            for r in normals:assert trigger_event['arrived_ns']<=r['start_ns']<r['end_ns']<=released_ns
            concurrent_result=dict(trigger=trigger_result,normal=normals,health_during=probes,health_after=post_probes,start_ns=concurrent_start,release_trigger_ns=released_ns,upstream_arrivals=len(arrivals),normal_completed_while_trigger_held=True,prober_stopped=not prober.is_alive())
            assert concurrent_result['prober_stopped']
        for e in events:
            assert json.loads(e['body'])==json.loads(REQUEST),e
            selected=dict(e['headers'])['x-higress-target-cluster']
            assert selected in (['a','b','c','d'] if e['path'].startswith('/concurrent/normal/') else services),(selected,e)
        stats_result=request(admin,'/stats?filter=wasm',timeout=2);(folder/'after-stats.json').write_text(json.dumps(stats_result,indent=2)+'\n')
        if not broken:
            assert stats_result.get('status')==200,stats_result
            metrics={k:int(v) for k,v in re.findall(r'^([^:]+): (\d+)$',stats_result['body'],re.M)}
            for suffix in ['crash_total','worker_fail_open_skip_total','worker_uninitialized','rebuild_total']:
                found=[v for k,v in metrics.items() if k.startswith('wasm.') and k.endswith('.'+suffix)]
                assert found and all(v==0 for v in found),(suffix,found,metrics)
        state=json.loads(docker('inspect',name,'--format','{{json .State}}'));assert state['Running'] and not state['OOMKilled'],state
        (folder/'process-state.json').write_text(json.dumps(state,indent=2)+'\n')
        if broken:(folder/'cpu-snapshot.json').write_text(docker('stats','--no-stream','--format','{{json .}}',name)+'\n')
        time.sleep(.2)
        log=subprocess.run(['docker','logs',name],capture_output=True,text=True,timeout=15);text=log.stdout+log.stderr
        if not broken:
            observations=re.findall(r'^observation=(\S+) status=(\d+) flags=(\S+)$',text,re.M)
            worker_observations=re.findall(r'\]\[(\d+)\]\[info\]\[lua\].*adaptive-worker-observation:(\S+)',text)
            assert observations and worker_observations and len({x[0] for x in worker_observations})==1,('requests must run on one worker',worker_observations)
            assert {x[0] for x in observations}<={x[1] for x in worker_observations},'missing worker observation'
            assert all(x[1]=='200' and x[2]=='-' for x in observations),observations
            if concurrency:
                seen={x[0] for x in observations}
                assert label+'-concurrent-trigger' in seen
                assert all(label+'-concurrent-normal-'+str(i) in seen for i in range(8))
                assert any('-health-probe-' in x for x in seen)
            assert not re.search(r'wasm trap|panic:|failed to (?:start|initialize).*plugin',text,re.I)
        summary=dict(harness_sha256=sha(Path(__file__).read_bytes()),variant=variant,case=case,iteration=iteration,broken_baseline_expected=broken,configuration_accepted=True,health_before=before,matrix=results,health_after=after,concurrency=concurrent_result,upstream_requests=len(events),wasm_sha256=sha((ROOT/(variant+'.wasm')).read_bytes()),gateway_image=IMAGE,assertions_passed=True)
        (folder/'results.json').write_text(json.dumps(summary,indent=2)+'\n');all_passed=True
    except BaseException as err:
        failure=repr(err);(folder/'failure.json').write_text(json.dumps({'error':failure},indent=2)+'\n');raise
    finally:
        release.set();(folder/'fixture-events.json').write_text(json.dumps(events,indent=2)+'\n')
        if created:
            log=subprocess.run(['docker','logs',name],capture_output=True,text=True,timeout=15);(folder/'envoy.log').write_text(log.stdout+log.stderr);docker('rm','-f',name)
        server.shutdown();server.server_close();server_thread.join(5)
        closed={}
        for port in ports+[server.server_port]:
            with socket.socket() as sock:sock.settimeout(.5);closed[str(port)]=sock.connect_ex(('127.0.0.1',port))!=0
        absent=not docker('ps','-a','--filter','name=^/'+name+'$','--format','{{.Names}}');cleanup=dict(container=name,container_absent=absent,ports_closed=closed,server_thread_stopped=not server_thread.is_alive(),fixture_closed=server.fileno()==-1)
        (folder/'cleanup.json').write_text(json.dumps(cleanup,indent=2)+'\n');(folder/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        assert absent and all(closed.values()) and not server_thread.is_alive(),cleanup
    print(json.dumps(dict(label=label,assertions_passed=all_passed,concurrency=concurrency,upstream_requests=len(events))),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--variant',choices=['baseline','candidate']);p.add_argument('--case',choices=list(CASES));p.add_argument('--iteration',type=int,default=1);p.add_argument('--all',action='store_true');p.add_argument('--jobs',type=int,default=2);args=p.parse_args()
    if args.all:
        work=[(variant,case,n) for variant in ['baseline','candidate'] for case in CASES for n in range(1,4)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures=[pool.submit(run,*x) for x in work];summaries=[f.result() for f in futures]
        (ROOT/'runtime-summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    else:run(args.variant,args.case,args.iteration)
