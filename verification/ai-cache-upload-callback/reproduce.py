"""Rebuild the pinned original plugin, then reproduce with a real local Qdrant.
Usage: GO=/path/to/go python3 reproduce.py /path/to/higress
"""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT=Path(__file__).resolve().parent
repo=Path(sys.argv[1]).resolve()
go=os.environ.get("GO","go")
revision=json.loads((ROOT/"provenance.json").read_text())["source_revision"]
env=dict(os.environ,GOTOOLCHAIN="local",GOWORK="off")
raw=subprocess.run(["git","-C",str(repo),"archive",revision,
    "plugins/wasm-go/extensions/ai-cache"],check=True,capture_output=True).stdout
with tempfile.TemporaryDirectory(prefix="ai-cache-callback-") as directory:
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(directory,filter="data")
    cwd=Path(directory)/"plugins/wasm-go/extensions/ai-cache"
    subprocess.run([go,"build","-mod=readonly","-buildvcs=false","-buildmode=c-shared",
        "-o",str(ROOT/"baseline.wasm"),"."],cwd=cwd,
        env=dict(env,GOOS="wasip1",GOARCH="wasm"),check=True)
    shutil.copyfile(ROOT/"discovery_upload_test.go",cwd/"discovery_upload_test.go")
    subprocess.run([go,"test","-mod=readonly",".","-run","^TestDiscoveryUploadCallback$",
        "-count=1","-timeout=3m","-v"],cwd=cwd,
        env=dict(env,WASM_FILE_PATH=str(ROOT/"baseline.wasm")),check=True)
subprocess.run(["docker","compose","-f",str(ROOT/"real-qdrant/compose.yaml"),"up","-d"],check=True)
subprocess.run([sys.executable,str(ROOT/"real-qdrant/smoke.py")],check=True)
run=str(time.time_ns())
for mode in ("direct","held-1","held-2","held-3"):
    command=[sys.executable,str(ROOT/"real-qdrant/verify_gateway_real.py"),
        "--label=rerun-"+run+"-"+mode]
    if mode!="direct":command.append("--hold-response")
    subprocess.run(command,check=True)
print("Baseline reproduction complete. The Qdrant container and its test data remain available.")
