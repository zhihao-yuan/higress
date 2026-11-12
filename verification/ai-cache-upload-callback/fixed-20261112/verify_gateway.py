import copy, hashlib, http.client, json, re, shutil, socket, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parent
VARIANT=next(a.split("=",1)[1] for a in sys.argv if a.startswith("--variant="))
assert VARIANT in ("baseline","candidate")
WASM=ROOT/(VARIANT+".wasm")
assert WASM.is_file()
COLLECTION="higress_ai_cache_"+str(time.time_ns())
IMAGE="higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299"
EVENTS=[]
UPLOAD=threading.Event()
HOLD_RELEASE=threading.Event()
STOP=threading.Event()
HELD="--hold-response" in sys.argv
CALLBACK_IDS=[]
ANSWER=b'{"choices":[{"message":{"role":"assistant","content":"answer"}}]}'
class Fixture(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self,*args):pass
    def do_POST(self):
        if self.headers.get("Transfer-Encoding","").lower()=="chunked":
            parts=[]
            while True:
                n=int(self.rfile.readline().split(b";")[0],16)
                if n==0:
                    while self.rfile.readline() not in (b"\r\n",b"\n",b""):pass
                    break
                parts.append(self.rfile.read(n));assert self.rfile.read(2)==b"\r\n"
            body=b"".join(parts)
        else:body=self.rfile.read(int(self.headers.get("Content-Length","0")))
        EVENTS.append(dict(path=self.path,body=body.decode(),headers=list(self.headers.items()),time_ns=time.monotonic_ns()))
        if self.path == "/hold":
            if not HOLD_RELEASE.wait(15):raise TimeoutError("no observed upload callback")
            response=b"held"
        elif self.path.endswith("text-embedding"):
            response=b'{"output":{"embeddings":[{"embedding":[0.1,0.2]}]}}'
        else:response=ANSWER
        self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(response)));self.end_headers()
        self.wfile.write(response);self.wfile.flush()

def docker(*args):
    return subprocess.run(["docker",*args],check=True,capture_output=True,text=True,timeout=60).stdout.strip()
def get(port,path):
    c=http.client.HTTPConnection("127.0.0.1",port,timeout=5);c.request("GET",path);r=c.getresponse();body=r.read();c.close();return r.status,body.decode()

server=ThreadingHTTPServer(("0.0.0.0",0),Fixture)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
label=next((a.split("=",1)[1] for a in sys.argv if a.startswith("--label=")),"gateway-held" if HELD else "gateway")
folder=ROOT/"runtime"/label;folder.mkdir(parents=True,exist_ok=False)
cfg=json.loads((ROOT/"envoy-template.json").read_text())
hcm=cfg["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][0]["typed_config"]
plugin=hcm["http_filters"][0]["typed_config"]["config"];plugin["name"]="ai-cache"
config=dict(embedding=dict(type="dashscope",apiKey="fixture-key",serviceName="embedding.static",servicePort=8080),
    vector=dict(type="qdrant",collectionID=COLLECTION,serviceName="qdrant.static",serviceHost="higress-pr-qdrant",servicePort=6333,threshold=.8,thresholdRelation="gt"),
    enableSemanticCache=True,cacheKeyStrategy="lastQuestion")
plugin["configuration"]["value"]=json.dumps(config)
if HELD:
    hcm["http_filters"].insert(0,{"name":"envoy.filters.http.lua","typed_config":{"@type":"type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua","inline_code":'function envoy_on_response(h) h:body(); h:httpCall("fixture", {[":method"]="POST",[":path"]="/hold",[":authority"]="fixture"}, "", 20000) end'}})
cluster=cfg["static_resources"]["clusters"][0]
cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]["address"]["socket_address"]["port_value"]=server.server_port
for name in ("outbound|8080||embedding.static","outbound|6333||qdrant.static"):
    extra=copy.deepcopy(cluster);extra["name"]=name;extra["load_assignment"]["cluster_name"]=name
    if "qdrant.static" in name:
        address=extra["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]["address"]["socket_address"]
        address.update(address="higress-pr-qdrant",port_value=6333)
    cfg["static_resources"]["clusters"].append(extra)
(folder/"envoy.json").write_text(json.dumps(cfg,indent=2)+"\n")
(folder/"plugin-config.json").write_text(json.dumps(config,indent=2)+"\n")
shutil.copyfile(WASM,folder/"plugin.wasm")
(folder/"request.json").write_text('{"messages":[{"role":"user","content":"question"}],"stream":false}')
(folder/"identity.json").write_text(json.dumps(dict(variant=VARIANT,wasm_sha256=hashlib.sha256(WASM.read_bytes()).hexdigest(),gateway_image=IMAGE,held=HELD),indent=2)+"\n")
name="ai-cache-qdrant-discovery-"+str(time.time_ns());created=False
results=[]
port=admin=None
assertions_passed=False
def observe_callback():
    while not STOP.wait(.1):
        logs=subprocess.run(["docker","logs",name],capture_output=True,text=True)
        text=logs.stdout+logs.stderr
        for call_id in re.findall(r"http call start, id: ([^,]+),[^\n]+url: /collections/[^/]+/points,",text):
            if "http call end, id: "+call_id+"," in text:
                if call_id not in CALLBACK_IDS:CALLBACK_IDS.append(call_id)
                EVENTS.append(dict(path="observer-release",time_ns=time.monotonic_ns(),call_id=call_id))
                HOLD_RELEASE.set()
monitor=threading.Thread(target=observe_callback,daemon=True)

def database(method,path,body=None):
    c=http.client.HTTPConnection("127.0.0.1",16333,timeout=10)
    c.request(method,path,None if body is None else json.dumps(body),{"content-type":"application/json"})
    r=c.getresponse();raw=r.read();c.close()
    result=json.loads(raw)
    assert r.status==200,(r.status,result)
    return result

database("PUT","/collections/"+COLLECTION,dict(vectors=dict(size=2,distance="Cosine")))
try:
    docker("run","-d","--name",name,"--network","higress-pr-vector-lab","--cpus","1","--memory","768m","-p","127.0.0.1::10000","-p","127.0.0.1::15000","-v",str(folder)+":/lab:ro","--entrypoint","/usr/local/bin/envoy",IMAGE,"-c","/lab/envoy.json","--concurrency","1","--log-level","debug");created=True
    port=int(docker("port",name,"10000/tcp").rsplit(":",1)[1]);admin=int(docker("port",name,"15000/tcp").rsplit(":",1)[1])
    for _ in range(100):
        try:
            if get(admin,"/ready")[0]==200:break
        except OSError:pass
        time.sleep(.1)
    else:raise RuntimeError("not ready")
    if HELD:monitor.start()
    for index in range(3):
        UPLOAD.clear()
        c=http.client.HTTPConnection("127.0.0.1",port,timeout=10)
        body=b'{"messages":[{"role":"user","content":"question"}],"stream":false}'
        try:
            c.request("POST","/v1/chat/completions",body,{"content-type":"application/json","x-mse-consumer":"fixture-consumer"})
            r=c.getresponse();response=r.read();results.append(dict(index=index,status=r.status,body=response.decode(),body_sha256=hashlib.sha256(response).hexdigest(),time_ns=time.monotonic_ns(),upstream_bytes_preserved=response==ANSWER,headers=r.getheaders()))
            for _ in range(40):
                stored=database("POST","/collections/"+COLLECTION+"/points/scroll",dict(limit=10,with_payload=True,with_vector=True))
                if stored["result"]["points"]:break
                time.sleep(.05)
        except Exception as error:results.append(dict(index=index,error=repr(error)))
        finally:c.close()
    stats=get(admin,"/stats?filter=wasm")[1]
    (folder/"wasm-stats.txt").write_text(stats)
    (folder/"results.json").write_text(json.dumps(results,indent=2)+"\n")
    stored=database("POST","/collections/"+COLLECTION+"/points/scroll",dict(limit=10,with_payload=True,with_vector=True))
    points=stored["result"]["points"]
    assert len(points)==1,stored
    assert points[0]["payload"]==dict(question="question",answer="answer",consumer="fixture-consumer")
    assert len(points[0]["vector"])==2
    search=database("POST","/collections/"+COLLECTION+"/points/search",dict(vector=[.1,.2],limit=1,with_payload=True))
    assert search["result"][0]["payload"]["answer"]=="answer"
    (folder/"database-proof.json").write_text(json.dumps(dict(collection=COLLECTION,scroll=stored,search=search),indent=2)+"\n")
    expected=[200,503,503] if VARIANT=="baseline" and HELD else [200,200,200]
    actual=[r.get("status") for r in results]
    assert actual==expected, (actual,expected)
    assert results[0]["upstream_bytes_preserved"]
    assert dict(results[0]["headers"])["content-type"]=="application/json"
    model_calls=[e for e in EVENTS if e["path"] not in ("/hold","observer-release") and not e["path"].endswith("text-embedding")]
    assert len(model_calls)==1,model_calls
    if expected[1]==200:
        for r in results[1:]:
            cached=json.loads(r["body"])
            assert cached["id"]=="from-cache"
            assert cached["choices"][0]["message"]["content"]=="answer"
    metrics={k:int(v) for k,v in re.findall(r"^([^:]+): (\d+)$",stats,re.M)}
    prefix="wasm.envoy.wasm.runtime.v8.plugin.ai-cache."
    assert metrics[prefix+"crash_total"]==(1 if expected[1]==503 else 0),metrics
    for key in ("worker_fail_open_skip_total","worker_uninitialized","rebuild_total"):
        assert metrics[prefix+key]==0,(key,metrics)
    if HELD:
        assert CALLBACK_IDS
        assert next(e["time_ns"] for e in EVENTS if e["path"]=="observer-release") < results[0]["time_ns"]
    assertions_passed=True
    summary=dict(variant=VARIANT,held=HELD,expected=expected,actual=actual,model_calls=len(model_calls),crash_total=metrics[prefix+"crash_total"],collection=COLLECTION,assertions_passed=True)
    (folder/"assertions.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary))
finally:
    STOP.set()
    if HELD and monitor.ident is not None:monitor.join(5)
    (folder/"callback-observations.json").write_text(json.dumps(CALLBACK_IDS,indent=2)+"\n")
    (folder/"fixture-events.json").write_text(json.dumps(EVENTS,indent=2)+"\n")
    if created:
        logs=subprocess.run(["docker","logs",name],capture_output=True,text=True)
        (folder/"envoy.log").write_text(logs.stdout+logs.stderr)
        docker("rm","-f",name)
    fixture_port=server.server_port
    server.shutdown();server.server_close();thread.join(5)
    # Only this invocation's uniquely named collection may be removed.
    database("DELETE","/collections/"+COLLECTION)
    remaining=database("GET","/collections")["result"]["collections"]
    collection_absent=COLLECTION not in [c["name"] for c in remaining]
    ports_closed={}
    for probe_port in [port,admin,fixture_port]:
        if probe_port is None:continue
        with socket.socket() as probe:
            probe.settimeout(1);ports_closed[str(probe_port)]=probe.connect_ex(("127.0.0.1",probe_port)) != 0
    absent=not docker("ps","-a","--filter","name=^/"+name+"$","--format","{{.Names}}")
    (folder/"cleanup.json").write_text(json.dumps(dict(collection=COLLECTION,collection_absent=collection_absent,remaining_collections=remaining,container=name,container_absent=absent,fixture_closed=server.fileno()==-1,thread_stopped=not thread.is_alive(),ports_closed=ports_closed),indent=2)+"\n")

assert assertions_passed and absent and collection_absent and all(ports_closed.values())
