import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import shutil

root = Path(__file__).resolve().parent
label, *arguments = sys.argv[1:]
if not label or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in label):
    raise SystemExit("invalid evidence label")
if (root / "evidence" / (label + "-result.json")).exists():
    raise SystemExit("evidence label already exists")
command = ["docker", "exec", "higress5213-builder", *arguments]
evidence = root / "evidence"
evidence.mkdir(exist_ok=True)
source = root / "higress"
diff = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=source)
files = {}
snapshot = evidence / (label + "-source")
snapshot.mkdir(exist_ok=True)
for path in (source / "plugins/wasm-rust/extensions/ai-data-masking/src").glob("*.rs"):
    files[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
    shutil.copy2(path, snapshot / path.name)
(evidence / (label + "-source.diff")).write_bytes(diff)
started = time.time()
with (evidence / (label + ".log")).open("w") as log:
    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
record = {
    "command": command,
    "exit_code": result.returncode,
    "elapsed_seconds": time.time() - started,
    "source_files_sha256": files,
    "source_diff_sha256": hashlib.sha256(diff).hexdigest(),
}
(evidence / (label + "-result.json")).write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({"label": label, "exit_code": result.returncode, "elapsed_seconds": record["elapsed_seconds"]}))
print("\n".join((evidence / (label + ".log")).read_text().splitlines()[-40:]))

raise SystemExit(result.returncode)
