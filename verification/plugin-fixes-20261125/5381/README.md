# Issue #5381: fixed verification

Base: `c4c537f37175befc375e65ba059e8df477dc52a4`. Fixed source: `3c0c536915f0d16706939936fc901cc52ca180dc` on `fix/transformer-json-number-precision`. This is the exact source commit proposed in the PR. The rebuilt committed-head Wasm equals the tested module. Hashes and changed-source hashes are in provenance.json.

## Results

One baseline and two fresh fixed gateway runs: **72 requests**, all HTTP 200; test-owned containers/ports/fixture threads cleaned up. Raw inputs, responses, access/plugin logs, Wasm counters and command exit codes are under runtime/. Baseline/fixed configurations and fixtures are the same within this formal comparison. The backend is a deterministic local HTTP fixture, not real model inference. Go mock/native suite and the new regression passed. The SDK full suite including Wazero mode timed out at the recorded 5/10-minute limit; this is not reported as passed. Real Envoy/V8 Wasm runs passed.

Runtime identity source_sha fields, where present, record the common baseline set before commits were created. They have not been rewritten. The tested fixed commit is bound to the exact module hash via the byte-identical head rebuild and source hashes in provenance.json.

## Rerun

Requires Docker Desktop (host.docker.internal), Python 3, and docker on PATH. Export the base and fixed Git commits' plugin source separately. Build with the pinned toolchain below, copy the resulting files beside verify.py using names `transformer-baseline.wasm` / `transformer-fixed.wasm`, then use a fresh label/iteration:

```sh
python3 verify.py --kind precision --variant fixed --iteration 20
```

Use variant baseline for the red run; choose a fresh iteration/label so existing records are not overwritten. The script cleans up its own container, server and ports in finally. It does not stop unrelated resources. Each runtime commands.json and envoy.json captures the full invocation/configuration. Wasm binaries are intentionally not committed.

Go build: from the exported plugin directory, Go 1.24.4 with `GOTOOLCHAIN=local GOWORK=off GOOS=wasip1 GOARCH=wasm go build -mod=readonly -buildvcs=false -trimpath -buildmode=c-shared -o <absolute-module-path> .`. Go mock/native suite: `go test -mod=readonly -run '/go$' -timeout=2m ./...` with WASM_FILE_PATH set to the built module to avoid an unnecessary SDK build. New direct regressions are separately selected by their Test names in the added test file.

Rust build (where applicable): builder `higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/wasm-rust-builder@sha256:31758209b0ab11bb81db4c07789d1b93072c46f63ecb10f1ee88863baf659d90`, Rust 1.82.0, `cargo build --locked --offline --release --target wasm32-wasi` from extensions/ai-data-masking, preserving the parent crate and existing Cargo dependency cache. `cargo test --locked --offline --lib` is run separately in the parent crate and plugin. See the exact build log and source patch.

## Process status

Proposal #5381 exists. Maintainer approval, Design and authorized TASK lineage were not obtained before implementation. The author explicitly requested direct PR delivery. This is **not** recorded as a compliant approval gate; the PR discloses the missing approval and assistance. No approval is fabricated.
