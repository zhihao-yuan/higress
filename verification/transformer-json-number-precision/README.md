# transformer JSON number precision reproduction

This records the request-path behavior of the **unmodified upstream transformer** plugin. It is baseline bug reproduction, not fixed-version verification. It uses a real Higress gateway/Envoy V8 Wasm runtime and a local HTTP echo fixture; no model inference is involved.

## Observed behavior

The request rules rename `identifier` to `renamed`, then copy the original JSON body value to `copied` (the map source is captured before transformation). Both rules are in the same configuration, not separate gateway experiments. See `runtime/group-1/plugin-config.json`.

Input:

```json
{"identifier":9007199254740993}
```

Backend receives, and the echo returns:

```json
{"renamed":9007199254740992,"copied":9007199254740992}
```

Expected values are `9007199254740993`. The nested object/array case also rounds the integer. Small integer `42` and the string `"9007199254740993"` are preserved. The separate gateway listener without the plugin preserves every original input.

Two fresh gateway containers completed 48 requests: four payloads × two listeners × three repetitions × two runs. All returned HTTP 200. Twelve plugin requests reproduced the wrong numeric values. The fixture records the exact incoming body, and the harness checks it against the response bytes. Raw requests, responses, body hashes, backend arrivals, access logs, Wasm counters and cleanup results are in `runtime/`.

## Versions

- Upstream source: `392b64e8cce43e63d3207f00ba5c8fe2ff8921d9`.
- Plugin: `plugins/wasm-go/extensions/transformer`; original dependencies, no edits or replacements.
- Go: 1.24.4 darwin/amd64; Wasm SDK v1.2.1.
- Wasm SHA-256: `185db2f1f157d917c1e6959a208bb8bea78d0ecba9be25e4a624357ad53b1f6e`.
- Gateway image: `higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299` (cached release v2.2.5).
- One Envoy worker, one CPU, 768 MiB, `fail_open=false`.

Original source-file hashes and build command are in `provenance.json`. The harness hash recorded in each identity file matches the published `verify.py`.

## Reproduce

Requires Docker Desktop (the fixture is reached through `host.docker.internal`), Python 3 and Go 1.24.4. Export the pinned upstream plugin directory into a separate build directory, without changing its files:

```sh
git archive 392b64e8cce43e63d3207f00ba5c8fe2ff8921d9 plugins/wasm-go/extensions/transformer | tar -x -C "$BUILD_DIR"
cd "$BUILD_DIR/plugins/wasm-go/extensions/transformer"
GOTOOLCHAIN=local GOWORK=off GOOS=wasip1 GOARCH=wasm go build -mod=readonly -buildvcs=false -trimpath -buildmode=c-shared -o "$EVIDENCE_DIR/transformer.wasm" .
cd "$EVIDENCE_DIR"
python3 verify.py rerun-1
python3 verify.py rerun-2
```

Set `BUILD_DIR` to an existing empty directory and `EVIDENCE_DIR` to this evidence directory first, with absolute paths. Use new run labels; the harness refuses to overwrite an existing run. The Wasm binary is intentionally not committed. Each run cleans up its own container, closes the fixture server and checks that all four ports are closed. Recorded cleanup passed for both runs; Wasm crash, rebuild and fail-open skip counters were zero.

## Cause and scope

At the pinned source, `main.go:1074` (rename) and `main.go:1194` (JSON body map) pass `gjson.Result.Value()` to `sjson.SetBytes`. Numeric values are converted to `float64`, including numbers nested in objects/arrays, before serialization. Values outside exact integer precision can change even though the operation only renames or copies a field. Preserve the JSON value without the intermediate lossy conversion.

Runtime coverage here is the request JSON path. Response-path confirmation and compatibility regressions belong to the eventual approved fix. No implementation change is included.

## Public record handling

Local user/home and laboratory path prefixes in published logs/configuration are replaced with `<lab>` or `<checkout>`. Payloads, response hashes, module/harness hashes, timestamps, counters and results are unchanged. `SHA256SUMS` covers the published files after this path redaction; identity hashes refer to the exact executed source and module. The published harness itself is unchanged.
