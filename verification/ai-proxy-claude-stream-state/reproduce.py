"""Build pinned original/fixed revisions, then run the local Envoy comparison.
Usage: python3 reproduce.py /path/to/higress
Requires Python 3.12+, Go 1.27.3, Docker, and both commits in the local repo.
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
meta = json.loads((ROOT / 'provenance.json').read_text())
env = dict(os.environ, GOTOOLCHAIN='local', GOWORK='off', GOOS='wasip1', GOARCH='wasm')
results = []
for label in ('baseline', 'fixed'):
    rev = meta[label + '_revision']
    archive = subprocess.run(['git', '-C', str(repo), 'archive', rev,
        'plugins/wasm-go/extensions/ai-proxy', 'plugins/wasm-go/pkg/pathutil',
        'plugins/wasm-go/pkg/jsonbody'], check=True, capture_output=True).stdout
    with tempfile.TemporaryDirectory(prefix='claude-state-') as directory:
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(directory, filter='data')
        cwd = Path(directory) / 'plugins/wasm-go/extensions/ai-proxy'
        subprocess.run(['go', 'build', '-mod=readonly', '-buildvcs=false',
            '-buildmode=c-shared', '-o', str(ROOT / (label+'.wasm')), '.'],
            cwd=cwd, env=env, check=True)
        results.append({'label': label, 'revision': rev,
            'sha256': hashlib.sha256((ROOT/(label+'.wasm')).read_bytes()).hexdigest()})
(ROOT/'rerun-build-results.json').write_text(json.dumps(results, indent=2)+'\n')
subprocess.run([sys.executable, str(ROOT/'verify_gateway.py')], check=True)
