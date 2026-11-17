"""Independently check retained formal evidence, excluding iteration-0 preflight."""
import hashlib,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parent
rows=json.loads((ROOT/'runtime-summary.json').read_text())
assert len(rows)==24
identity=json.loads((ROOT/'provenance.json').read_text())
expected={(v,c,n) for v in ['baseline','candidate'] for c in ['unique','duplicate-safe','duplicate','identical'] for n in range(1,4)}
assert {(r['variant'],r['case'],r['iteration']) for r in rows}==expected
counts={'baseline_matrix_success':0,'baseline_trigger_timeout':0,'baseline_health_timeout':0,'candidate_matrix_success':0,'concurrent_trigger_success':0,'concurrent_normal_success':0,'concurrent_health_success':0,'upstream_requests':0}
groups=[]
for row in rows:
    label=f"{row['variant']}-{row['case']}-{row['iteration']}";p=ROOT/'runtime'/label
    assert row['assertions_passed'] and row['configuration_accepted']
    assert row['wasm_sha256']==identity['module_sha256'][row['variant']]
    assert row['harness_sha256']==hashlib.sha256((ROOT/'verify_gateway.py').read_bytes()).hexdigest()
    cleanup=json.loads((p/'cleanup.json').read_text());assert cleanup['container_absent'] and all(cleanup['ports_closed'].values()) and cleanup['server_thread_stopped'] and cleanup['fixture_closed']
    events=json.loads((p/'fixture-events.json').read_text());assert len(events)==row['upstream_requests'];counts['upstream_requests']+=len(events)
    state=json.loads((p/'process-state.json').read_text());assert state['Running'] and not state['OOMKilled']
    worker_ids=[]
    if row['broken_baseline_expected']:
        assert len(row['matrix'])==1 and row['matrix'][0]['error']=='TimeoutError' and row['health_after']['error']=='TimeoutError' and not events
        counts['baseline_trigger_timeout']+=1;counts['baseline_health_timeout']+=1
    else:
        assert len(row['matrix'])==3 and all(x['status']==200 for x in row['matrix']) and row['health_after']['status']==200
        counts[row['variant']+'_matrix_success']+=3
        stats=json.loads((p/'after-stats.json').read_text());assert stats['status']==200
        metrics={k:int(v) for k,v in re.findall(r'^([^:]+): (\d+)$',stats['body'],re.M)}
        for suffix in ['crash_total','worker_fail_open_skip_total','worker_uninitialized','rebuild_total']:
            found=[v for k,v in metrics.items() if k.startswith('wasm.') and k.endswith('.'+suffix)];assert found and not any(found)
        log=(p/'envoy.log').read_text();worker_rows=re.findall(r'\]\[(\d+)\]\[info\]\[lua\].*adaptive-worker-observation:(\S+)',log);worker_ids=sorted({x[0] for x in worker_rows});assert len(worker_ids)==1
        concurrent=row['concurrency']
        if concurrent:
            assert row['variant']=='candidate' and row['case'] in ['duplicate','identical']
            assert concurrent['normal_completed_while_trigger_held'] and concurrent['prober_stopped']
            assert concurrent['trigger']['status']==200 and len(concurrent['normal'])==8 and all(x['status']==200 for x in concurrent['normal'])
            health=concurrent['health_during']+concurrent['health_after'];assert len(concurrent['health_during'])>=3 and all(x['status']==200 for x in health)
            arrivals=[e for e in events if e['path'].startswith('/concurrent/')];assert len(arrivals)==9 and len({e['observation'] for e in arrivals})==9
            trigger=next(e for e in arrivals if e['path']=='/concurrent/trigger');assert trigger['released'] and not trigger.get('hold_timeout')
            assert all(trigger['arrived_ns']<=x['start_ns']<x['end_ns']<=concurrent['release_trigger_ns'] for x in concurrent['normal'])
            counts['concurrent_trigger_success']+=1;counts['concurrent_normal_success']+=8;counts['concurrent_health_success']+=len(health)
        else:assert row['variant']=='baseline' or row['case'] in ['unique','duplicate-safe']
        assert all('finished_ns' in e for e in events)
    groups.append(dict(label=label,worker_ids=worker_ids,cleanup_passed=True))
assert counts['baseline_trigger_timeout']==6 and counts['baseline_health_timeout']==6
assert counts['baseline_matrix_success']==18 and counts['candidate_matrix_success']==36
assert counts['concurrent_trigger_success']==6 and counts['concurrent_normal_success']==48
assert counts['upstream_requests']==108
summary=dict(formal_groups=24,concurrent_groups=6,counts=counts,groups=groups,all_assertions_passed=True,baseline_assertions_mean='Expected defect observed, not repair acceptance',preflight_excluded='candidate-duplicate-0')
(ROOT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary['counts']))
