"""Fresh real-model calls, native Envoy Tap observes the same upstream response.
Tools are declared only and never executed. SSH tunnel is provided separately.
"""
import base64,collections,datetime,hashlib,json,pathlib,subprocess,time
ROOT=pathlib.Path(__file__).resolve().parent
MODULES=ROOT.parent
GATEWAY='higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299'
NETWORK='higress-masking-review2-live-20261021'
CONTAINERS=[]
RESULTS=[]
TOOLS=[{'type':'function','function':{'name':'read','description':'Read a project demonstration file','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}}]

def run(args):return subprocess.check_output(args,stderr=subprocess.STDOUT,text=True).strip()

def parse(raw,stream):
 events=[];done=0;errors=[]
 if stream:
  for line in raw.splitlines():
   if not line.startswith('data:'):continue
   if line[5:].strip()=='[DONE]':done+=1
   else:events.append(json.loads(line[5:]))
 else:events=[json.loads(raw)]
 text='';reasoning='';finish=[];deltas=[];tools=collections.defaultdict(lambda:{'id':'','name':'','arguments':''});usage=[]
 for e in events:
  if e.get('error'):errors.append(e['error'])
  if e.get('usage'):usage.append(e['usage'])
  for c in e.get('choices',[]):
   if c.get('finish_reason'):finish.append(c['finish_reason'])
   delta=c.get('delta',c.get('message',{})) or {};text+=delta.get('content') or '';reasoning+=(delta.get('reasoning') or '')+(delta.get('reasoning_content') or '')
   for t in delta.get('tool_calls') or []:
    deltas.append(t);item=tools[(c.get('index',0),t.get('index',0))];item['id']+=t.get('id') or '';f=t.get('function') or {};item['name']+=f.get('name') or '';item['arguments']+=f.get('arguments') or ''
 values=[]
 for (choice,index),v in sorted(tools.items()):
  try:arguments=json.loads(v['arguments']);valid=isinstance(arguments,dict)
  except:valid=False
  values.append({'choice':choice,'index':index,**v,'valid':bool(v['id'] and v['name']=='read' and valid)})
 return {'events':len(events),'text':text,'reasoning':reasoning,'finish':finish,'done':done,'deltas':deltas,'tools':values,'usage':usage,'errors':errors}

def request_for(kind):
 if kind=='tools':
  return {'model':'dsv4','messages':[{'role':'system','content':'这是网关工具协议连通性测试，测试标签 DEMO_SECRET。请先调用 read 工具读取 README.md。本轮只返回工具调用，不直接生成报告。'},{'role':'user','content':'帮我输出一份项目验收报告，先读取 README.md。'}],'tools':TOOLS,'tool_choice':'required','stream':True,'max_tokens':1024,'temperature':0,'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}
 if kind=='tools-json':
  body=request_for('tools');body['stream']=False;body.pop('stream_options');return body
 return {'model':'dsv4','messages':[{'role':'user','content':'请简短回复测试连接成功，并在回复中原样包含测试标签 DEMO_SECRET。'}],'stream':True,'max_tokens':512,'temperature':0,'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}

def tap_body(body):
 assert not body.get('truncated',False),'Tap trace truncated'
 if 'as_bytes' in body:return base64.b64decode(body['as_bytes'])
 if 'asBytes' in body:return base64.b64decode(body['asBytes'])
 return body.get('as_string',body.get('asString','')).encode()

def trace_after(directory,before):
 for _ in range(50):
  files=[p for p in directory.glob('trace*') if p not in before and p.is_file()]
  if files:
   assert len(files)==1,files
   try:return files[0],json.loads(files[0].read_text())
   except json.JSONDecodeError:pass
  time.sleep(.1)
 raise RuntimeError('Native tap file not found')


def call(name, base, kind, mode, tap_dir=None):
 body=request_for(kind)
 req=ROOT/'requests'/(name+'.json')
 req.write_text(json.dumps(body,ensure_ascii=False,indent=2))
 before=set(tap_dir.glob('trace*')) if tap_dir else set()
 p=subprocess.run(['curl','-sS','-N','--connect-timeout','5','--max-time','100',base+'/v1/chat/completions',
                   '-H','Content-Type: application/json','-H','x-observation-id: '+name,'--data-binary','@'+str(req),
                   '-D',str(ROOT/'responses'/(name+'.headers')),'-o',str(ROOT/'responses'/(name+'.body')),
                   '-w','%{http_code}'],capture_output=True,text=True,timeout=110)
 assert p.returncode==0 and p.stdout=='200',(name,p.stdout,p.stderr)
 raw=(ROOT/'responses'/(name+'.body')).read_bytes()
 actual=parse(raw.decode(),body['stream'])
 original=None
 if tap_dir:
  _,trace=trace_after(tap_dir,before)
  data=trace.get('http_buffered_trace',trace.get('httpBufferedTrace'))
  observed=json.loads(tap_body(data['request']['body']))
  upstream=tap_body(data['response']['body'])
  (ROOT/'responses'/(name+'.upstream.body')).write_bytes(upstream)
  (ROOT/'requests'/(name+'.upstream.json')).write_text(json.dumps(observed,ensure_ascii=False,indent=2))
  original=parse(upstream.decode(),body['stream'])
  expected=json.loads(json.dumps(body))
  if mode!='bypass':
   for message in expected['messages']:message['content']=message['content'].replace('DEMO_SECRET','MASKED_TOKEN')
  assert observed==expected,(name,'request changed unexpectedly')
  if mode=='bypass':assert upstream==raw,(name,'bypass altered bytes')
 source=original or actual
 if kind.startswith('tools'):
  assert source['tools'] and all(v['valid'] for v in source['tools']), (name,source)
  assert source['finish']==['tool_calls'],(name,source)
 else:
  assert source['text'] and source['finish']==['stop'],(name,source)
 if body['stream']:assert source['done']==1,(name,source)
 if mode=='fixed':
  assert actual['tools']==original['tools'],(name,'tool loss',actual)
  assert actual['finish']==original['finish'] and actual['done']==original['done'],(name,'terminal loss',actual)
  assert actual['text']==original['text'].replace('MASKED_TOKEN','DEMO_SECRET'),(name,'text restore',actual)
  assert actual['usage']==original['usage'] and actual['errors']==original['errors'],(name,'metadata loss',actual)
 if mode=='baseline' and kind=='tools':
  assert not actual['tools'] or not all(v['valid'] for v in actual['tools']), (name,'baseline bug did not reproduce')
 result={'case':name,'variant':mode,'kind':kind,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'http':p.stdout,'real_model_request':True,'same_request_native_tap':bool(original),
         'upstream_tool_deltas':len(original['deltas']) if original else None,
         'downstream_tool_deltas':len(actual['deltas']), 'valid_downstream_calls':sum(v['valid'] for v in actual['tools']),
         'upstream_finish':original['finish'] if original else None,'downstream_finish':actual['finish'],
         'upstream_done':original['done'] if original else None,'downstream_done':actual['done'],
         'body_sha256':hashlib.sha256(raw).hexdigest()}
 RESULTS.append(result)
 (ROOT/'results.json').write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2))
 print(json.dumps(result),flush=True)


try:
 run(['docker','network','create',NETWORK])
 call('direct-tools','http://127.0.0.1:20637','tools','direct')
 call('direct-text','http://127.0.0.1:20637','text','direct')
 for mode in ['bypass','baseline','fixed']:
  cn=NETWORK+'-'+mode
  CONTAINERS.append(cn)
  run(['docker','run','-d','--name',cn,'--network',NETWORK,
       '-v',str(ROOT)+':/lab:ro','-v',str(MODULES)+':/modules:ro',
       '-v',str(ROOT/('tap-'+mode))+':/tap','-p','127.0.0.1::10000',
       '--entrypoint','/usr/local/bin/envoy',GATEWAY,'-c','/lab/'+mode+'.json','--concurrency','1','--log-level','info'])
  port=run(['docker','port',cn,'10000/tcp']).split(':')[-1]
  (ROOT/(mode+'.port')).write_text(port)
  for _ in range(100):
   p=subprocess.run(['docker','exec',cn,'curl','-sf','http://127.0.0.1:15000/ready'],capture_output=True)
   if p.returncode==0:break
   time.sleep(.2)
  else:raise RuntimeError('Envoy failed to become ready: '+cn)
  for label,kind in [('tools-1','tools'),('tools-2','tools'),('text','text'),('tools-json','tools-json')]:
   call(mode+'-'+label,'http://127.0.0.1:'+port,kind,mode,ROOT/('tap-'+mode))
  stats=run(['docker','exec',cn,'curl','-sf','http://127.0.0.1:15000/stats?filter=wasm'])
  (ROOT/(mode+'.stats.txt')).write_text(stats)
  for line in stats.splitlines():
   if any(k in line for k in ['crash_total','worker_fail_open_skip_total','worker_uninitialized']):assert line.rsplit(': ',1)[1]=='0',line
  (ROOT/(mode+'.envoy.log')).write_text(run(['docker','logs',cn]))
  (ROOT/(mode+'.config-dump.json')).write_text(run(['docker','exec',cn,'curl','-sf','http://127.0.0.1:15000/config_dump']))
  run(['docker','rm','-f',cn]);CONTAINERS.remove(cn)
 assert len(RESULTS)==14
 summary={'status':'passed','real_model_requests':len(RESULTS),'fixed_requests':sum(v['variant']=='fixed' for v in RESULTS),
          'tools_executed':False,'sliced_or_replayed_responses':False}
 (ROOT/'summary.json').write_text(json.dumps(summary,indent=2))
 print(json.dumps(summary),flush=True)
finally:
 for cn in CONTAINERS:
  try:
   (ROOT/(cn+'.envoy.log')).write_text(run(['docker','logs',cn]));run(['docker','rm','-f',cn])
  except Exception as e:print('cleanup error',cn,str(e),flush=True)
 run(['docker','network','rm',NETWORK])
 cleanup={'containers_remaining':run(['docker','ps','-aq','--filter','name='+NETWORK]),
          'network_remaining':run(['docker','network','ls','-q','--filter','name='+NETWORK])}
 (ROOT/'cleanup.json').write_text(json.dumps(cleanup,indent=2))
 assert not any(cleanup.values()),cleanup
