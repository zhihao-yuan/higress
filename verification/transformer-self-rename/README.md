# transformer self-rename deletes fields

Original upstream transformer, source `392b64e8cce43e63d3207f00ba5c8fe2ff8921d9`. Checked on 2026-11-19: upstream/main still points to this revision. Baseline reproduction only; no implementation or fixed-version acceptance.

## Observations

All cases in each run use the same configuration (runtime/self-rename-1/plugin-config.json).

- JSON `label` → `label`: input `{"label":"keep","untouched":1}` becomes `{"untouched":1}` at the backend.
- Header `X-Client-Id` → `x-client-id`: input `X-Client-Id: client-123` disappears at the backend. Header names are case-insensitive.
- Ordinary `old` → `new` and `x-old` → `x-new` controls work.
- The bypass listener in the same gateway preserves the original body and headers.

Two fresh real Higress gateway/Envoy V8 instances; 3 cases × 2 listeners × 3 repetitions: **36 requests, 12 defect reproductions, all HTTP 200**. The upstream is a local HTTP fixture recording body bytes and headers and returning their JSON representation. No model inference is involved. Runtime directories include exact configurations, requests, backend arrivals, response bodies/hashes, access logs, Wasm metrics, Docker commands and cleanup proof.

## Cause

main.go:1370-1371 lowercases both header names. The key/value rename path at main.go:923-930 writes the target and then deletes the old key, deleting the same entry when the normalized keys match. The JSON path at main.go:1066-1079 also sets then deletes an identical path. Identical effective names should preserve original data. Destination collisions and equivalent JSON path syntax need not be redefined here.

## Versions and rerun

Go 1.24.4 darwin/amd64, wasm-go SDK v1.2.1. Original source, go.mod and go.sum unchanged. Wasm SHA-256: `185db2f1f157d917c1e6959a208bb8bea78d0ecba9be25e4a624357ad53b1f6e`.

Gateway v2.2.5: `higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299`. One worker, one CPU, 768 MiB, fail_open=false. Crash/rebuild/fail-open skip/worker-uninitialized counters are zero. Both containers were removed; fixture threads stopped; all four ports per run closed.

Requires Docker Desktop, Python 3 and Go 1.24.4. Set BUILD_DIR to an existing empty directory and EVIDENCE_DIR to this evidence directory, both absolute paths:

```sh
git archive 392b64e8cce43e63d3207f00ba5c8fe2ff8921d9 plugins/wasm-go/extensions/transformer | tar -x -C "$BUILD_DIR"
cd "$BUILD_DIR/plugins/wasm-go/extensions/transformer"
GOTOOLCHAIN=local GOWORK=off GOOS=wasip1 GOARCH=wasm go build -mod=readonly -buildvcs=false -trimpath -buildmode=c-shared -o "$EVIDENCE_DIR/transformer.wasm" .
cd "$EVIDENCE_DIR"
python3 verify_gateway.py --kind self-rename --iteration 3
python3 verify_gateway.py --kind self-rename --iteration 4
```

The original executed harness is published unchanged to preserve its recorded hash. It supports other modes; only self-rename runs 1 and 2 are evidence here. New iterations prevent overwriting existing results. Cleanup in finally removes only the run's own container, stops the fixture and checks port closure. The Wasm binary is not committed; provenance.json records source hashes and build flags.

Coverage is request headers and JSON body. Response/query/form regressions belong to the eventual Design. Local home/lab path prefixes in records are replaced with <home>/<lab>; payloads, timing, hashes and counters remain unchanged. SHA256SUMS covers published files after redaction. Identity files retain exact executed harness/module hashes.
