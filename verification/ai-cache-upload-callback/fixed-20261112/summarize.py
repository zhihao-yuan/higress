import hashlib,json,re
from pathlib import Path
root=Path(__file__).resolve().parent
identity=json.loads((root/"provenance.json").read_text())
cases=[]
for variant in ("baseline","candidate"):
 for held in (False,True):
  for group in range(1,4):
   folder=root/"runtime"/f"{variant}-{'held' if held else 'direct'}-{group}"
   a=json.loads((folder/"assertions.json").read_text())
   r=json.loads((folder/"results.json").read_text())
   c=json.loads((folder/"cleanup.json").read_text())
   i=json.loads((folder/"identity.json").read_text())
   assert a["assertions_passed"] and len(r)==3
   assert i["wasm_sha256"]==identity["artifacts"][variant]
   assert c["collection_absent"] and c["container_absent"] and c["thread_stopped"] and c["fixture_closed"] and all(c["ports_closed"].values())
   log=(folder/"envoy.log").read_text()
   if variant=="baseline" and held:
    assert "nil pointer dereference" in log and "qdrantProvider).UploadAnswerAndEmbedding.func1" in log
   else:
    assert "panic:" not in log and "failed: Uncaught RuntimeError" not in log
   db=json.loads((folder/"database-proof.json").read_text())
   point=db["scroll"]["result"]["points"][0]
   assert point["payload"]==dict(question="question",answer="answer",consumer="fixture-consumer")
   assert len(point["vector"])==2 and db["search"]["result"][0]["payload"]==point["payload"]
   if held:
    events=json.loads((folder/"fixture-events.json").read_text())
    assert next(e["time_ns"] for e in events if e["path"]=="observer-release") < r[0]["time_ns"]
   a.update(case=folder.name,cleanup_verified=True,database_read_and_search_verified=True,body_hashes=[x["body_sha256"] for x in r])
   cases.append(a)
assert len(cases)==12 and sum(len(x["actual"]) for x in cases)==36
for idx in range(6):assert cases[idx]["body_hashes"][0]==cases[idx+6]["body_hashes"][0]
summary=dict(client_requests=36,cases=cases,all_assertions_passed=True,real_vector_database=True,real_model=False)
(root/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
print(json.dumps(dict(client_requests=36,groups=12,all_assertions_passed=True)))
