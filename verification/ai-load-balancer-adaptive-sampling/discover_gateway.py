"""Discovery only: run an unmodified official Wasm module in a bounded Gateway."""
import argparse,copy,hashlib,http.client,json,socket,subprocess,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--case",choices=("unique","duplicate","identical","duplicate-safe"),required=True);p.add_argument("--label",required=True);a=p.parse_args()
ROOT=Path(__file__).resolve().parent;folder=ROOT/a.label;folder.mkdir(exist_ok=False)
IMAGE="higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299"
CASES={"unique":(["a","b","c","d"],3),"duplicate":(["a","a","a","b"],3),"identical":(["a","a","a"],None),"duplicate-safe":(["a","a","b","b"],2)}
services,choices=CASES[a.case];broken=a.case in ("duplicate","identical")
events=[];ANSWER=b'{"choices":[{"message":{"role":"assistant","content":"fixture-answer"}}]}'
class Handler(BaseHTTPRequestHandler):
 protocol_version="HTTP/1.1"
 def log_message(self,*args):pass
 def do_GET(self):self.respond()
 def do_POST(self):self.respond()
 def respond(self):
  if self.headers.get("Transfer-Encoding","").lower()=="chunked":
   parts=[]
   while True:
    size=int(self.rfile.readline().split(b";")[0],16)
    if size==0:
     while self.rfile.readline() not in (b"\r\n",b"\n",b""):pass
     break
    parts.append(self.rfile.read(size));assert self.rfile.read(2)==b"\r\n"
   body=b"".join(parts)
  else:body=self.rfile.read(int(self.headers.get("content-length",0)))
  events.append(dict(path=self.path,body=body.decode(),headers=list(self.headers.items()),time_ns=time.monotonic_ns()))
  self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(ANSWER)));self.end_headers();self.wfile.write(ANSWER)
server=ThreadingHTTPServer(("0.0.0.0",0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
config=dict(lb_type="cluster",lb_policy="cluster_metrics",lb_config=dict(mode="AdaptiveScore",service_list=services))
if choices is not None:config["lb_config"]["p2c_choices"]=choices
cfg=json.loads((ROOT/"envoy-template.json").read_text())
listener=cfg["static_resources"]["listeners"][0]
hcm=listener["filter_chains"][0]["filters"][0]["typed_config"]
plugin=hcm["http_filters"][0]["typed_config"]["config"];plugin["name"]="ai-load-balancer";plugin["configuration"]["value"]=json.dumps(config)
plugin["vm_config"]["code"]["local"]["filename"]="/lab/baseline.wasm"
route=hcm["route_config"]["virtual_hosts"][0]["routes"][0]["route"];route.pop("cluster");route["cluster_header"]="x-higress-target-cluster"
health=copy.deepcopy(listener);health["name"]="no-plugin-health";health["address"]["socket_address"]["port_value"]=10001
hh=health["filter_chains"][0]["filters"][0]["typed_config"];hh["stat_prefix"]="health";hh["http_filters"]=hh["http_filters"][1:];hr=hh["route_config"]["virtual_hosts"][0]["routes"][0]["route"];hr.pop("cluster_header");hr["cluster"]="fixture"
cfg["static_resources"]["listeners"].append(health)
cluster=cfg["static_resources"]["clusters"][0];cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]["address"]["socket_address"]["port_value"]=server.server_port
for name in sorted(set(services)):
 c=copy.deepcopy(cluster);c["name"]=name;c["load_assignment"]["cluster_name"]=name;cfg["static_resources"]["clusters"].append(c)
(folder/"envoy.json").write_text(json.dumps(cfg,indent=2)+"\n");(folder/"plugin-config.json").write_text(json.dumps(config,indent=2)+"\n")
# Avoid copies of the binary in each case; read-only mount its containing folder.
plugin["vm_config"]["code"]["local"]["filename"]="/source/baseline.wasm"
(folder/"envoy.json").write_text(json.dumps(cfg,indent=2)+"\n")
name="higress-p2c-discovery-"+str(time.time_ns());created=False;ports=[];results=[]
def docker(*args):return subprocess.run(["docker",*args],check=True,capture_output=True,text=True,timeout=45).stdout.strip()
def request(port,path,method="GET",body=None,timeout=3):
 start=time.monotonic();c=http.client.HTTPConnection("127.0.0.1",port,timeout=timeout)
 try:
  c.request(method,path,body,{"content-type":"application/json"});r=c.getresponse();raw=r.read();return dict(status=r.status,body=raw.decode(),body_sha256=hashlib.sha256(raw).hexdigest(),headers=r.getheaders(),seconds=time.monotonic()-start)
 except (OSError,TimeoutError) as e:return dict(error=type(e).__name__,detail=str(e),seconds=time.monotonic()-start)
 finally:c.close()
try:
 docker("run","-d","--name",name,"--cpus","1","--memory","768m","-p","127.0.0.1::10000","-p","127.0.0.1::10001","-p","127.0.0.1::15000","-v",str(folder)+":/lab:ro","-v",str(ROOT)+":/source:ro","--entrypoint","/usr/local/bin/envoy",IMAGE,"-c","/lab/envoy.json","--concurrency","1","--log-level","debug");created=True
 ports=[int(docker("port",name,str(n)+"/tcp").rsplit(":",1)[1]) for n in (10000,10001,15000)];proxy,healthy,admin=ports
 for _ in range(120):
  ready=request(admin,"/ready",timeout=.5)
  if ready.get("status")==200:break
  time.sleep(.1)
 else:raise RuntimeError(("not ready",ready))
 before=request(healthy,"/health");assert before.get("status")==200,before
 (folder/"before-stats.json").write_text(json.dumps(request(admin,"/stats?filter=wasm"),indent=2)+"\n")
 for i in range(1 if broken else 3):results.append(request(proxy,"/v1/chat/completions","POST",b'{"model":"fixture","messages":[{"role":"user","content":"hello"}],"stream":false}'))
 after=request(healthy,"/health",timeout=2)
 (folder/"after-stats.json").write_text(json.dumps(request(admin,"/stats?filter=wasm",timeout=2),indent=2)+"\n")
 (folder/"docker-stats.json").write_text(docker("stats","--no-stream","--format","{{json .}}",name)+"\n")
 (folder/"process-state.json").write_text(docker("inspect",name,"--format","{{json .State}}")+"\n")
 model_calls=[e for e in events if e["path"]=="/v1/chat/completions"]
 if broken:
  assert results[0].get("error")=="TimeoutError",results
  assert after.get("error")=="TimeoutError",after
  assert not model_calls,model_calls
 else:
  assert all(r.get("status")==200 and r["body"]==ANSWER.decode() for r in results),results
  assert after.get("status")==200 and len(model_calls)==3,(after,model_calls)
 summary=dict(case=a.case,services=services,p2c_choices=choices if choices is not None else "default=2",configuration_accepted=True,health_before=before,trigger=results,health_after=after,model_calls=len(model_calls),assertions_passed=True,wasm_sha256=hashlib.sha256((ROOT/"baseline.wasm").read_bytes()).hexdigest(),gateway_image=IMAGE)
 (folder/"results.json").write_text(json.dumps(summary,indent=2)+"\n")
 print(json.dumps(dict(case=a.case,trigger=[r.get("status",r.get("error")) for r in results],health_after=after.get("status",after.get("error")),model_calls=len(model_calls),assertions_passed=True)),flush=True)
finally:
 (folder/"fixture-events.json").write_text(json.dumps(events,indent=2)+"\n")
 if created:
  log=subprocess.run(["docker","logs",name],capture_output=True,text=True);(folder/"envoy.log").write_text(log.stdout+log.stderr);docker("rm","-f",name)
 fp=server.server_port;server.shutdown();server.server_close();thread.join(5)
 closed={}
 for port in ports+[fp]:
  with socket.socket() as s:s.settimeout(.5);closed[str(port)]=s.connect_ex(("127.0.0.1",port))!=0
 absent=not docker("ps","-a","--filter","name=^/"+name+"$","--format","{{.Names}}")
 cleanup=dict(container=name,container_absent=absent,ports_closed=closed,thread_stopped=not thread.is_alive(),fixture_closed=server.fileno()==-1)
 (folder/"cleanup.json").write_text(json.dumps(cleanup,indent=2)+"\n")
 assert absent and all(closed.values()) and not thread.is_alive(),cleanup
