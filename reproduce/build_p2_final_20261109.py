import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time

lab = Path(__file__).resolve().parent
repo = lab / 'higress'
revision, label = sys.argv[1:3]
cache_label = sys.argv[3] if len(sys.argv) > 3 else label
assert all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in label)
revision = subprocess.check_output(['git','rev-parse',revision],cwd=repo,text=True).strip()
output = lab / ('build-' + label)
output.mkdir(exist_ok=False)
archive = subprocess.check_output(['git','archive',revision,'plugins/wasm-rust'],cwd=repo)
source = repo / 'plugins/wasm-rust/target' / (label + '-source')
source.mkdir(parents=True,exist_ok=False)
with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
    stream.extractall(source,filter='data')
working = '/src/target/' + label + '-source/plugins/wasm-rust/extensions/ai-data-masking'
target = '/src/target/' + cache_label + '-artifacts'
command = ['docker','exec','-w',working,'-e','CARGO_TARGET_DIR='+target,'higress5213-builder',
    'cargo','build','--locked','--offline','--release','--target','wasm32-wasip1']
record = {'source_revision':revision,'archive_sha256':hashlib.sha256(archive).hexdigest(),
    'lock_sha256':hashlib.sha256((source/'plugins/wasm-rust/Cargo.lock').read_bytes()).hexdigest(),
    'command':command,'source_files_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (source/'plugins/wasm-rust/extensions/ai-data-masking/src').glob('*.rs')}}
start=time.time()
with (output/'build.log').open('w') as log:
    result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
record.update(exit_code=result.returncode,elapsed_seconds=time.time()-start)
if result.returncode==0:
    module=(repo/'plugins/wasm-rust/target'/(cache_label+'-artifacts')/'wasm32-wasip1/release/ai_data_masking.wasm').read_bytes()
    (lab/'wasm'/(label+'.wasm')).write_bytes(module)
    record.update(wasm_sha256=hashlib.sha256(module).hexdigest(),wasm_bytes=len(module))
(output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record),flush=True)
raise SystemExit(result.returncode)
