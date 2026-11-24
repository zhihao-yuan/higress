# log-request-response string encoding costs

Exploratory measurements from 2026-11-13, based on upstream `0316bc904789ab25a9cd42db58eafca11f6a2205`. This is a performance opportunity, not a claim of corrupt logs or measured whole-gateway performance improvement. No production fix or PR is included.

## Opportunity

`setPropertyWithMarshal` wraps an input string in a one-entry map, marshals that map, parses the JSON again with gjson, extracts the string and removes its quotes before SetProperty. The isolated experiment marshals the string directly and removes the outer quotes. lab/baseline-main.go and prototype-main.go capture the exact module sources; logging-prototype.diff captures the single-helper change. The main working checkout was not changed.

Fetched upstream/main on 2026-11-24: `22915ae3d048fdfbc66da0a9635d6e7b6142fc26`. Its plugin main.go is byte-identical to the tested baseline. go.mod/go.sum **have since changed SDK versions**; no runtime verification of those newer dependencies is claimed. Final implementation should revalidate on its approved base.

## Native helper measurements

Go 1.24.4 darwin/amd64, Intel Core i5-1038NG7. Three repetitions, medians:

| Synthetic SSE size | Original helper | Direct string experiment | Allocations/op, original → experiment |
| --- | --- | --- | --- |
| 4 KiB | 43.259 us | 17.359 us | 12 → 3 |
| 64 KiB | 757.108 us | 332.902 us | 14 → 3 |

Native SetProperty is a byte-recording stub, not an Envoy host call. These figures measure isolated helper work, including its Go allocations; they do not establish Wasm speed, QPS, production CPU savings, peak memory or billing impact. All raw samples, other input sizes and medians are under lab/. The benchmark samples were checked against the summary medians before publication.

The native byte-identity test covers empty input, ASCII, quotes, backslashes, Chinese, control characters, invalid UTF-8, HTML-sensitive characters and Unicode line separators. Native module code, tests, go.mod and go.sum are under native/.

## Real Wasm compatibility comparison

Full baseline and experimental plugins were separately loaded into fresh real Higress gateway v2.2.5/Envoy V8 containers. No host functions were replaced in these gateway runs. Fixed local HTTP fixtures return synthetic 4 KiB/64 KiB SSE-like text containing Chinese, quotes, backslashes, LF and HTML-sensitive characters. Payloads are truncated to exact lengths; they are encoding fixtures, not asserted to be complete model-protocol event streams. No model inference is involved.

For each size and variant, 30 plugin requests and 30 bypass requests: **240 requests**, including 120 plugin requests. All HTTP 200. Client bodies equal fixture bytes; decoded access-log body properties equal the expected UTF-8 replacement-decoded body for both variants. Bypass produces no logged body property. No content, format or property-name change was observed. Full request/response metadata, body samples and hashes, Envoy logs, Wasm counters, commands and cleanup are retained under lab/runtime/.

Each gateway uses one worker, one CPU, 768 MiB and fail_open=false. Crash/rebuild/fail-open skip counters are zero. Containers removed, fixture threads stopped, four test ports per run closed. This was a compatibility run, **not an isolated gateway load test**. Scheduling, loopback network and log I/O affect recorded elapsed times; do not treat them as performance results.

Baseline Wasm SHA-256: `722106cfc50eed2b37a5f69a929e6212b24a08497c9e69439317c3fe8d436ff0`.

Experiment Wasm SHA-256: `d3228b3b09c2347f0aebbe1f11bbf529c2e441be9d27b8fa85c98bdbdb20d54d`.

Gateway image: `higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299`.

## Rerun

Native tests/benchmark (requires Go 1.24.4, GOTOOLCHAIN=local, GOWORK=off):

```sh
cd "$EVIDENCE_DIR/native"
go test -mod=readonly ./officiallogging -run '^TestPropertyBytes$' -count=1 -v
go test -mod=readonly ./officiallogging -run '^$' -bench '^BenchmarkProperty$' -benchmem -benchtime=200ms -count=3
```

For real gateway reproduction, Docker Desktop and Python 3 are required. Set EVIDENCE_DIR to this evidence directory and BUILD_DIR to an existing empty directory outside any Git checkout, both absolute paths. From a source Git checkout containing the pinned revision:

```sh
mkdir -p "$BUILD_DIR/baseline" "$BUILD_DIR/prototype"
git archive 0316bc904789ab25a9cd42db58eafca11f6a2205 plugins/wasm-go/extensions/log-request-response | tar -x -C "$BUILD_DIR/baseline"
cp -R "$BUILD_DIR/baseline/plugins/wasm-go/extensions/log-request-response/." "$BUILD_DIR/prototype/"
cp "$EVIDENCE_DIR/lab/prototype-main.go" "$BUILD_DIR/prototype/main.go"
cd "$BUILD_DIR/baseline/plugins/wasm-go/extensions/log-request-response"
GOTOOLCHAIN=local GOWORK=off GOOS=wasip1 GOARCH=wasm go build -trimpath -buildmode=c-shared -o "$EVIDENCE_DIR/lab/logging-baseline.wasm" .
cd "$BUILD_DIR/prototype"
GOTOOLCHAIN=local GOWORK=off GOOS=wasip1 GOARCH=wasm go build -trimpath -buildmode=c-shared -o "$EVIDENCE_DIR/lab/logging-prototype.wasm" .
cd "$EVIDENCE_DIR/lab"
python3 harness-v1.py logging baseline rerun-baseline
python3 harness-v2.py logging prototype rerun-prototype
```

Recorded identities refer to the unmodified executed harness versions, both included. Their historical sibling template path is retained under higress-adaptive-sampling-20261112/ solely for reproducibility. Only logging-final-baseline-1 and logging-final-prototype-1 are evidence for this report. Earlier log-key setup attempts are excluded. Use fresh labels to avoid overwriting recorded results; finally cleanup removes only the run's own container, stops the fixture and checks ports. No Wasm binaries are committed.

Public records redact local home/lab path prefixes bytewise. Payloads, response hashes, timing, counters, results and exact harness sources remain unchanged. .gitattributes prevents raw body newline conversion. SHA256SUMS covers published files after redaction; identities retain the executed module and harness hashes.
