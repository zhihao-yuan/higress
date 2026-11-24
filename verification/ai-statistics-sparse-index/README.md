# ai-statistics sparse tool-call index scan

Discovery on unmodified community source `c4c537f37175befc375e65ba059e8df477dc52a4`, 2026-11-24. No fix/prototype is included. This is synthetic input hardening, not an observed production-model failure.

## Cause

`plugins/wasm-go/extensions/ai-statistics/main.go:421-440` finds the largest ToolCalls map key, then probes every integer key from zero through that maximum. One existing tool call at a large index therefore causes work proportional to the index value rather than the number of actual entries. Upstream-provided tool indexes reach this helper through the streaming tool-call parser.

A proposed direction is to collect existing nonnegative keys and order those keys before materializing the tool calls, preserving ascending order and sparse-index identity. Negative indexes, missing inputs and multi-tool compatibility should be explicitly considered in the Design. No new artificial index cap is proposed here.

## Runtime experiment

Two fresh real Higress gateway v2.2.5 / Envoy V8 containers, one worker, one CPU, 768 MiB, fail_open=false. The complete original plugin was compiled with Go 1.24.4 and loaded directly. No helper/host-function replacement.

Config: `{"attributes":[{"key":"tool_calls","apply_to_log":true}]}`.

A local HTTP fixture returns OpenAI-shaped SSE with **one** tool call, fixed name/ID/arguments, and only its index varied: 0, 100000, 1000000, 10000000. Each also has the same finish_reason and [DONE] ending. This large-index input is synthetic; no claim is made that normal providers emit such indexes or that all provider specifications require support for them. The current parser accepts them without rejecting the response. No model inference is involved.

Four indexes × plugin/bypass × three repetitions × two containers: **48 requests**. All HTTP 200. Client response bytes equal fixture bytes, the logged tool count remains one, the original index is preserved (zero is omitted by the existing JSON omitempty rule), and logged arguments remain `{"city":"Beijing"}`. Bypass produces no ai_log property.

Access-log duration medians (ms), three requests per cell:

| Tool index | Run 1 bypass | Run 1 plugin | Run 2 bypass | Run 2 plugin |
| --- | ---: | ---: | ---: | ---: |
| 0 | 2 | 5 | 1 | 2 |
| 100000 | 2 | 7 | 1 | 5 |
| 1000000 | 2 | 40 | 3 | 20 |
| 10000000 | 2 | 874 | 1 | 189 |

Run 2 is recorded as gateway-3. Different host scheduling/load makes the absolute durations vary; these are whole-request wall-clock observations, not CPU profiling or production QPS measurements. Combined with the explicit zero-to-max source loop, they demonstrate that one large accepted index can cause disproportionate gateway work. No fixed-version speedup or same-worker concurrent-blocking result is claimed.

Runtime folders retain configurations, fixture arrivals, response bytes and hashes, access/plugin logs, counters and commands. Wasm crash/rebuild/fail-open skip/worker-uninitialized counters are zero. Both test containers were deleted, fixture threads stopped and four ports per run closed. gateway-2 was a setup-only failed attempt (Docker missing from non-login PATH); it sent no gateway request and created no container, and is excluded from the formal counts. Its failure log is retained.

## Identity and rerun

Wasm SHA-256: `01badfcda1f2de445f593484f4a1a689629e94cb4a6883a4d4280badba4246e4`.

Gateway image: `higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299`.

Go 1.24.4 darwin/amd64, wasm-go SDK v1.2.1; original source and dependencies unchanged. Source-file hashes and exact build flags are in provenance.json; executed harness/module hashes are in each runtime identity. The main working checkout was unchanged.

Requires Docker Desktop, Python 3 and Go 1.24.4; ensure docker is on PATH. Set EVIDENCE_DIR to this evidence directory and BUILD_DIR to an existing empty directory, both absolute paths. From a Git checkout containing the pinned source:

```sh
git archive c4c537f37175befc375e65ba059e8df477dc52a4 plugins/wasm-go/extensions/ai-statistics | tar -x -C "$BUILD_DIR"
cd "$BUILD_DIR/plugins/wasm-go/extensions/ai-statistics"
GOTOOLCHAIN=local GOWORK=off GOOS=wasip1 GOARCH=wasm go build -mod=readonly -buildvcs=false -trimpath -buildmode=c-shared -o "$EVIDENCE_DIR/statistics.wasm" .
cd "$EVIDENCE_DIR"
python3 verify.py rerun-1
python3 verify.py rerun-2
```

Use fresh labels; existing result folders are not overwritten. Requests and subprocesses have timeouts. Finally cleanup removes only its own test container, stops the fixture and checks port closure. No Wasm binaries are committed.

Published records redact local home/lab prefixes bytewise. Payloads, timing, counters, results and exact executed harness source are unchanged. .gitattributes prevents raw body newline conversion. SHA256SUMS covers public files after redaction.
