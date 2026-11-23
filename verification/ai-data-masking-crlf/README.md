# ai-data-masking CRLF SSE event boundaries

Baseline reproduction on unmodified upstream `0316bc904789ab25a9cd42db58eafca11f6a2205`, executed 2026-11-13. Fetched upstream/main on 2026-11-23: `392b64e8cce43e63d3207f00ba5c8fe2ff8921d9`; the entire `plugins/wasm-rust` tree is unchanged between these commits. No implementation or fixed-version acceptance is included.

## Configuration and observed bytes

```json
{"deny_openai":true,"system_deny":false,"deny_words":["UNMATCHED_SYNTHETIC_WORD"]}
```

A normal OpenAI-shaped request has `stream:true`; tool_arguments/tool_definitions are not enabled. Fixture text does not match the deny word. Exact request bytes are in lab/verify.py and fixture records.

Upstream response, shown as a JSON string to expose line-ending bytes:

```json
"event: custom\r\ndata: {\"ok\":true}\r\n\r\n"
```

Actual plugin response:

```json
"event: custom\n\ndata: {\"ok\":true}\n\n"
```

One custom event becomes a message event. Another input `data: {"value":\r\ndata: 1}\r\n\r\n` should produce one event with data `{"value":\n1}`. Actual output is two message events, with data `{"value":` and `1}`. Raw response bodies under lab/runtime/ retain the actual CRLF bytes.

[WHATWG SSE parsing rules](https://html.spec.whatwg.org/multipage/server-sent-events.html#parsing-an-event-stream) treat CRLF as one line ending; a blank line triggers dispatch. Multiple data lines are combined into the same event. Semantic results here use a small independent reference parser following those rules, not the plugin parser. No real browser EventSource or Agent was tested. Missing a custom-name listener is an inferred consequence of the changed event type.

## Runtime coverage

Two fresh real Higress gateway v2.2.5/Envoy V8 containers. Each uses one worker, one CPU, 768 MiB and fail_open=false. The full original Rust Wasm module is loaded. Upstream is a local deterministic HTTP SSE service; no model inference is involved.

Seven cases, plugin and bypass paths, three repetitions in each container: **84 requests, 18 defect reproductions**, all HTTP 200.

- Named event with CRLF, including upstream byte-at-a-time writes: custom type becomes message (12 requests across two runs).
- Multiline data with CRLF: one event becomes two (6 requests).
- Named/multiline LF controls and ordinary single-data-line LF/CRLF controls retain semantics.
- Every bypass response is byte-identical to the fixture.

Byte-at-a-time fixture writes exercise fragmentation, including CR/LF separation; TCP/Envoy may coalesce writes, so this is not a proof that every Wasm callback boundary is one byte. The defect also occurs without fragmentation.

Every response, body hash, expected/actual parsed event, fixture arrival, Envoy log, metric, Docker command and cleanup result is in lab/runtime/gateway-1 and gateway-2. Crash/rebuild/fail-open skip counters are zero. Both test containers were removed; fixture threads stopped and all four ports per run closed.

## Source cause and scope

`plugins/wasm-rust/src/event_stream.rs:110-127` treats a single CRLF as an event separator: is_2eol returns Some(2) when size1 is 2, even without a second logical newline. `extensions/ai-data-masking/src/msg_win_openai.rs:265-267` then appends two LF bytes to each raw fragment, turning this parser mistake into changed event boundaries on the wire.

The proposed correction is to distinguish logical line endings from blank-line event separators, including CR/LF split across updates. The eventual Design should cover LF, CRLF, CR, mixed endings, fragments, event/id/retry/comment fields, multiline data, normal OpenAI SSE and end-of-stream/incomplete frames. This report does not claim those untested cases are already covered or fixed.

## Identity and rerun

Wasm SHA-256: `bc3e43c3465c70d978d6b69ed307bbc7f50d28409bd926bb56a058bcfeef984c`.

Builder: `higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/wasm-rust-builder@sha256:31758209b0ab11bb81db4c07789d1b93072c46f63ecb10f1ee88863baf659d90`, Rust 1.82.0, wasm32-wasi (WASI preview1). The initial wasm32-wasip1 attempt failed because that target was not installed; the successful original build used the installed wasm32-wasi target without source/dependency changes. See lab/provenance.json and build-wasi.log.

Gateway: `higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299`.

Requires Docker Desktop, Python 3 and the pinned Git revision. Set EVIDENCE_DIR to this directory using an absolute path. Source extraction/build below should be run on a fresh copy, leaving recorded runtime folders unchanged:

```sh
mkdir -p "$EVIDENCE_DIR/lab/baseline"
git archive 0316bc904789ab25a9cd42db58eafca11f6a2205 plugins/wasm-rust | tar -x -C "$EVIDENCE_DIR/lab/baseline"
docker run --rm -v "$EVIDENCE_DIR/lab:/lab" -v higress5213-cargo:/usr/local/cargo -e CARGO_TARGET_DIR=/lab/target -w /lab/baseline/plugins/wasm-rust/extensions/ai-data-masking --entrypoint cargo higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/wasm-rust-builder@sha256:31758209b0ab11bb81db4c07789d1b93072c46f63ecb10f1ee88863baf659d90 build --locked --offline --release --target wasm32-wasi
cp "$EVIDENCE_DIR/lab/target/wasm32-wasi/release/ai_data_masking.wasm" "$EVIDENCE_DIR/lab/baseline.wasm"
cd "$EVIDENCE_DIR/lab"
python3 verify.py rerun-1
python3 verify.py rerun-2
```

The recorded build used the existing populated higress5213-cargo volume. A fresh cache needs dependencies fetched (omit --offline for that first build). Source build must run from the source Git checkout for git archive to resolve the pinned revision. The original successful command used the builder tag; provenance records the corresponding pinned digest.

The executed lab/verify.py is unchanged and its recorded SHA-256 matches. It expects a sibling historical template path; that exact template is included under higress-adaptive-sampling-20261112/. This directory name is retained solely for reproducibility. New run labels prevent overwriting recorded results. The harness removes only its own test container, stops the fixture and checks port closure in finally. Wasm binaries and Cargo outputs are not committed.

Public records replace local home/lab prefixes with <home>/<lab> bytewise. Payloads, CRLF/LF bytes, hashes, timestamps, counters and results are unchanged. SHA256SUMS covers published artifacts after redaction; identity files retain executed module/harness hashes.

.gitattributes marks raw .body files as -text to preserve original CRLF bytes in Git.
