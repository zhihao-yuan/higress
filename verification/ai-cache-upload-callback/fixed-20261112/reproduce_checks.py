"""Rebuild and test the pinned sources. Use a disposable local clone via --repo."""
import argparse, hashlib, json, os, shutil, subprocess, tarfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--repo",required=True);p.add_argument("--go",default="go");a=p.parse_args()
root=Path(__file__).resolve().parent
identity=json.loads((root/"provenance.json").read_text())
records=[]
def run(cmd,cwd,env,log,expected=0):
    with (root/log).open("w") as f:
        r=subprocess.run(cmd,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT)
    records.append(dict(command=cmd,cwd=str(cwd),log=log,exit_code=r.returncode,expected=expected))
    (root/"rerun-commands.json").write_text(json.dumps(records,indent=2)+"\n")
    assert r.returncode==expected,(cmd,r.returncode)
module="plugins/wasm-go/extensions/ai-cache"
for variant in ("baseline","candidate"):
    work=root/("rerun-source-"+variant)
    work.mkdir(exist_ok=False)
    archive=subprocess.check_output(["git","-C",a.repo,"archive",identity[variant+"_source"],module])
    arc=work/"source.tar";arc.write_bytes(archive)
    with tarfile.open(arc) as t:t.extractall(work,filter="data")
    cwd=work/module
    if variant=="baseline":
        test=subprocess.check_output(["git","-C",a.repo,"show",identity["candidate_source"]+":"+module+"/core_upload_test.go"])
        (cwd/"core_upload_test.go").write_bytes(test)
    env=os.environ.copy();env.update(GOTOOLCHAIN="local",GOWORK="off")
    buildenv=env.copy();buildenv.update(GOOS="wasip1",GOARCH="wasm")
    wasm=root/(variant+".wasm")
    run([a.go,"build","-mod=readonly","-buildvcs=false","-buildmode=c-shared","-o",str(wasm),"."],cwd,buildenv,variant+"-rerun-build.log")
    env["WASM_FILE_PATH"]=str(wasm)
    if variant=="baseline":
        run([a.go,"test","-mod=readonly",".","-run","^TestUploadEmbeddingAndAnswer","-count=1","-timeout=3m","-v"],cwd,env,"baseline-rerun-regression.log",1)
        log=(root/"baseline-rerun-regression.log").read_text()
        for name in ("dashvector","chroma","elasticsearch","milvus","pinecone","qdrant","weaviate"):
            assert "--- FAIL: TestUploadEmbeddingAndAnswerProviders/"+name+"/go" in log
        assert "nil pointer dereference" in log
    else:
        run([a.go,"test","-mod=readonly","./...","-count=1","-timeout=30m","-v"],cwd,env,"candidate-rerun-full-test.log")
        run([a.go,"vet","-mod=readonly","./..."],cwd,env,"candidate-rerun-vet.log")
    (root/(variant+"-rerun-wasm.sha256")).write_text(hashlib.sha256(wasm.read_bytes()).hexdigest()+"\n")
print("Pinned source checks completed; run reproduce_runtime.py next.")
