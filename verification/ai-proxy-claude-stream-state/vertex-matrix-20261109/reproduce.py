"""Build both pinned revisions, then run all 28 local Gateway requests.

Usage: GO=/path/to/go python3 reproduce.py /path/to/higress
Requires Python 3.12+, Docker and Go 1.27.3.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent
repo = Path(sys.argv[1]).resolve()
meta = json.loads((ROOT / "provenance.json").read_text())
go = os.environ.get("GO", "go")
env = dict(os.environ, GOTOOLCHAIN="local", GOWORK="off", GOOS="wasip1", GOARCH="wasm")
builds = []
for label in ("baseline", "fixed"):
    revision = meta[label + "_revision"]
    archive = subprocess.run(["git", "-C", str(repo), "archive", revision,
        "plugins/wasm-go/extensions/ai-proxy", "plugins/wasm-go/pkg/pathutil",
        "plugins/wasm-go/pkg/jsonbody"], check=True, capture_output=True).stdout
    with tempfile.TemporaryDirectory(prefix="claude-matrix-") as directory:
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(directory, filter="data")
        command = [go, "build", "-mod=readonly", "-buildvcs=false", "-buildmode=c-shared",
                   "-o", str(ROOT / (label + ".wasm")), "."]
        subprocess.run(command, cwd=Path(directory) / "plugins/wasm-go/extensions/ai-proxy",
                       env=env, check=True)
        builds.append(dict(label=label, revision=revision, command=command,
            sha256=hashlib.sha256((ROOT / (label + ".wasm")).read_bytes()).hexdigest()))
(ROOT / "rerun-build-results.json").write_text(json.dumps(builds, indent=2) + "\n")
subprocess.run([sys.executable, str(ROOT / "verify_gateway.py")], check=True)
