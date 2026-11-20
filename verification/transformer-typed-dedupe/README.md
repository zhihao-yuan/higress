# transformer RETAIN_UNIQUE conflates JSON types

Baseline reproduction on unmodified upstream `392b64e8cce43e63d3207f00ba5c8fe2ff8921d9`, executed 2026-11-18. Fetched upstream/main again on 2026-11-20: still this revision. No source fix or fixed-version acceptance is included.

## Configuration and observations

```json
{"reqRules":[{"operate":"dedupe","body":[{"key":"values","strategy":"RETAIN_UNIQUE"}]}]}
```

| Input values | Actual backend values |
| --- | --- |
| `[1,"1",true,"true"]` | `[1,true]` |
| `[{"a":1},"{\"a\":1}"]` | `{"a":1}` |
| `["a","a","b"]` | `["a","b"]` |
| `[1,1,2]` | `[1,2]` |

The first two inputs contain different JSON types, not duplicate values. The documented single-element collapse explains why the object/string case ends as an object after the string is wrongly removed; collapse itself is not a separate bug.

Two fresh real Higress gateway/Envoy V8 containers; four payloads × two listeners × three repetitions = **48 requests, 12 defect reproductions**. All HTTP 200. Same-type dedupe controls work; the gateway listener without the plugin preserves every original input. The upstream is a local HTTP fixture recording body bytes and headers, returning their JSON representation; no model inference is involved.

Runtime folders retain exact configurations, backend arrivals, original response bodies and hashes, access logs, metrics, Docker commands and cleanup records. Responses were checked against backend records and recorded SHA-256. Crash/rebuild/fail-open skip/worker-uninitialized counters are zero. Both containers were removed, fixture threads stopped and four ports per run closed.

## Cause and proposed scope

At main.go:1222, the JSON RETAIN_UNIQUE loop uses `gjson.Result.String()` as its set key. Number `1` and string `"1"`, boolean `true` and string `"true"`, object and matching JSON text string collide. Preserve JSON type information when deciding uniqueness. Keep first-occurrence order, normal same-type deduplication and documented single-element collapse. Numeric equivalence and object comparison boundaries should be decided explicitly in the eventual Design, not silently expanded here.

Runtime coverage is the request JSON path. Response-path regression coverage belongs to the eventual approved fix.

## Versions and rerun

- Go 1.24.4 darwin/amd64, wasm-go SDK v1.2.1. Source, go.mod and go.sum unchanged; hashes and build flags in provenance.json.
- Wasm SHA-256: `185db2f1f157d917c1e6959a208bb8bea78d0ecba9be25e4a624357ad53b1f6e`.
- Gateway v2.2.5 pinned image: `higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299`.
- One worker, one CPU, 768 MiB, fail_open=false.

Requires Docker Desktop, Python 3, Go 1.24.4 and the pinned source in Git. Set BUILD_DIR to an existing empty directory and EVIDENCE_DIR to this evidence directory, using absolute paths:

```sh
git archive 392b64e8cce43e63d3207f00ba5c8fe2ff8921d9 plugins/wasm-go/extensions/transformer | tar -x -C "$BUILD_DIR"
cd "$BUILD_DIR/plugins/wasm-go/extensions/transformer"
GOTOOLCHAIN=local GOWORK=off GOOS=wasip1 GOARCH=wasm go build -mod=readonly -buildvcs=false -trimpath -buildmode=c-shared -o "$EVIDENCE_DIR/transformer.wasm" .
cd "$EVIDENCE_DIR"
python3 verify_gateway.py --kind typed-dedupe --iteration 3
python3 verify_gateway.py --kind typed-dedupe --iteration 4
```

The original executed harness is unchanged so recorded identity hashes are verifiable. It supports other modes; only typed-dedupe runs 1 and 2 are evidence for this report. Use new iterations to avoid overwriting records. Finally cleanup removes only its own container, stops the fixture and checks closed ports. The Wasm binary is not committed.

Local home/lab path prefixes in published records are replaced with <home>/<lab>. Payloads, timing, hashes, counters and results remain unchanged. SHA256SUMS covers the published files after redaction; identity files retain exact executed harness/module hashes.
