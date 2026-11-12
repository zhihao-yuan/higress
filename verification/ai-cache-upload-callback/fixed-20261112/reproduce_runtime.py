import json, subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
records=[]
for variant in ("baseline","candidate"):
    for held in (False,True):
        for group in range(1,4):
            label=f"{variant}-{'held' if held else 'direct'}-{group}"
            cmd=["python3",str(root/"verify_gateway.py"),"--variant="+variant,"--label="+label]+(["--hold-response"] if held else [])
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
            (root/(label+".log")).write_text(r.stdout+r.stderr)
            record=dict(command=cmd,exit_code=r.returncode)
            records.append(record)
            (root/"runtime-commands.json").write_text(json.dumps(records,indent=2)+"\n")
            print(json.dumps(record),flush=True)
            if r.returncode:raise SystemExit(r.returncode)
