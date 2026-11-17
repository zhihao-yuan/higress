"""Rebuild exact revisions in fresh archives; never edit the supplied checkout."""
import argparse,hashlib,io,json,os,subprocess,tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
MODULE='plugins/wasm-go/extensions/ai-load-balancer'
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repo',required=True);parser.add_argument('--go',default='go');args=parser.parse_args()
    provenance=json.loads((ROOT/'provenance.json').read_text());commands=[];env=dict(os.environ,GOTOOLCHAIN='local',GOWORK='off')
    def run(argv,cwd,label,expected=0,extra=None):
        current=dict(env);current.update(extra or {})
        result=subprocess.run(argv,cwd=cwd,env=current,capture_output=True,text=True,timeout=1800)
        output=result.stdout+result.stderr;(ROOT/(label+'.log')).write_text(output)
        commands.append(dict(argv=argv,cwd=str(cwd),environment={'GOTOOLCHAIN':'local','GOWORK':'off',**(extra or {})},exit=result.returncode,expected=expected))
        (ROOT/'rerun-check-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        assert result.returncode==expected,(label,result.returncode,output[-4000:])
        return output
    for variant in ['baseline','candidate']:
        source=ROOT/'reproduction-source'/variant;source.mkdir(parents=True,exist_ok=False)
        archive=subprocess.check_output(['git','-C',args.repo,'archive',provenance[variant+'_sha'],MODULE,'plugins/wasm-go/pkg/jsonbody'])
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:stream.extractall(source,filter='data')
        module=source/MODULE;wasm=ROOT/(variant+'.wasm')
        run([args.go,'build','-mod=readonly','-buildvcs=false','-trimpath','-buildmode=c-shared','-o',str(wasm),'.'],module,variant+'-rebuild',extra={'GOOS':'wasip1','GOARCH':'wasm'})
        provenance['module_sha256'][variant]=hashlib.sha256(wasm.read_bytes()).hexdigest()
        run([args.go,'test','-mod=readonly','./...','-count=1','-timeout=30m','-v'],module,variant+'-rerun-full-tests',extra={'WASM_FILE_PATH':str(wasm)})
        run([args.go,'vet','-mod=readonly','./...'],module,variant+'-rerun-vet')
        if variant=='baseline':
            test=subprocess.check_output(['git','-C',args.repo,'show',provenance['candidate_sha']+':'+MODULE+'/cluster_metrics/lb_policy_test.go'])
            (module/'cluster_metrics/lb_policy_test.go').write_bytes(test)
            red=run([args.go,'test','-mod=readonly','./cluster_metrics','-run','TestAdaptiveScore(DuplicateCandidatesReturn|SamplingPreservesFilteringAndFallback)$','-count=1','-timeout=30s','-v'],module,'baseline-rerun-red',expected=1)
            assert red.count('panic: test timed out after 1s')==4 and 'sampleAdaptiveCandidates' in red
            assert 'selectAdaptiveScore' in red and 'buildGlobalInflightLuaKeys' in red
            assert 'PASS: TestAdaptiveScoreSamplingPreservesFilteringAndFallback' in red
    provenance['rerun_go_version']=subprocess.check_output([args.go,'version'],env=env,text=True).strip()
    (ROOT/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print('Both revisions rebuilt; baseline target red, compatibility green, candidate tests/vet green.')

if __name__=='__main__':main()
