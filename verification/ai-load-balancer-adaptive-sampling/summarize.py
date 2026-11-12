import hashlib,json,re
from pathlib import Path
r=Path(__file__).resolve().parent
labels=["unique-control-final","duplicate-safe-control"]+[f"duplicate-{i}" for i in range(1,4)]+[f"identical-{i}" for i in range(1,4)]
rows=[];hashes=set()
for label in labels:
 p=r/label;d=json.loads((p/"results.json").read_text());c=json.loads((p/"cleanup.json").read_text());state=json.loads((p/"process-state.json").read_text());events=json.loads((p/"fixture-events.json").read_text());after=json.loads((p/"after-stats.json").read_text());hashes.add(d["wasm_sha256"])
 assert d["assertions_passed"] and d["configuration_accepted"] and d["health_before"]["status"]==200
 assert state["Running"] and not state["OOMKilled"]
 assert c["container_absent"] and c["thread_stopped"] and c["fixture_closed"] and all(c["ports_closed"].values())
 assert after["status"]==200
 metrics={k:int(v) for k,v in re.findall(r"^([^:]+): (\d+)$",after["body"],re.M)}
 for key,value in metrics.items():
  if key.endswith((".crash_total",".worker_uninitialized",".worker_fail_open_skip_total",".rebuild_total")):assert value==0,(label,key,value)
 calls=[e for e in events if e["path"]=="/v1/chat/completions"]
 if d["case"] in ("duplicate","identical"):
  assert len(d["trigger"])==1 and d["trigger"][0]["error"]=="TimeoutError" and d["health_after"]["error"]=="TimeoutError" and len(calls)==0
 else:
  assert len(calls)==3 and all(x["status"]==200 for x in d["trigger"]) and d["health_after"]["status"]==200
  for call in calls:
   assert dict(call["headers"])["x-higress-target-cluster"] in d["services"]
   assert json.loads(call["body"])["messages"][0]["content"]=="hello"
 rows.append(dict(label=label,case=d["case"],trigger=[x.get("status",x.get("error")) for x in d["trigger"]],health_after=d["health_after"].get("status",d["health_after"].get("error")),model_calls=len(calls),cpu=json.loads((p/"docker-stats.json").read_text())["CPUPerc"],configuration_accepted=True,process_running=True,oom=False,cleanup_verified=True,assertions_passed=True))
assert len(hashes)==1
summary=dict(groups=len(rows),affected_groups=6,healthy_controls=2,wasm_sha256=next(iter(hashes)),all_assertions_passed=True,real_gateway=True,real_model=False,source_modified=False,cases=rows)
(r/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
print(json.dumps(summary,indent=2))
