import http.client
import json
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parent
PORT=16333
def request(method,path,body=None):
    conn=http.client.HTTPConnection("127.0.0.1",PORT,timeout=10)
    conn.request(method,path,None if body is None else json.dumps(body),{"content-type":"application/json"})
    response=conn.getresponse()
    raw=response.read()
    conn.close()
    try:result=json.loads(raw)
    except json.JSONDecodeError:result=raw.decode()
    record=dict(method=method,path=path,request=body,status=response.status,response=result)
    assert response.status==200,record
    return record
for _ in range(100):
    try:
        version=request("GET","/")
        assert version["response"]["version"]=="1.20.0"
        break
    except (OSError,AssertionError):time.sleep(.1)
else:raise RuntimeError("Qdrant not ready")
name="higress_smoke_"+str(time.time_ns())
records=[version]
records.append(request("PUT","/collections/"+name,dict(vectors=dict(size=2,distance="Cosine"))))
records.append(request("PUT","/collections/"+name+"/points?wait=true",dict(points=[
    dict(id=1,vector=[1.,0.],payload=dict(question="vector A",answer="answer A",consumer="fixture-consumer")),
    dict(id=2,vector=[0.,1.],payload=dict(question="vector B",answer="answer B",consumer="fixture-consumer"))])))
search=request("POST","/collections/"+name+"/points/search",dict(vector=[1.,0.],limit=1,with_payload=True))
assert search["response"]["result"][0]["id"]==1
assert search["response"]["result"][0]["payload"]["answer"]=="answer A"
assert search["response"]["result"][0]["score"]>.999
records.append(search)
stored=request("GET","/collections/"+name+"/points/1")
assert stored["response"]["result"]["payload"]["answer"]=="answer A"
records.append(stored)
result=dict(real_database=True,version=version["response"],collection=name,records=records,write_read_search_passed=True)
(ROOT/"smoke-results.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(dict(version=version["response"],collection=name,write_read_search_passed=True)))
