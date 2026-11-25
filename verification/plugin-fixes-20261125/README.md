# Plugin fixes, 2026-11-25

Six isolated branches from current upstream/main, one issue per PR. Real gateway verification totals 756 requests across baseline/fixed runs. See each issue directory for actual results and limitations; full default Go/Wazero suites and Rust doctests are not claimed as passing.

- [#5381 transformer-json-number-precision](5381/README.md): 72 requests.
- [#5386 transformer-self-rename](5386/README.md): 54 requests.
- [#5389 transformer-json-dedupe-types](5389/README.md): 72 requests.
- [#5407 ai-data-masking-sse-crlf](5407/README.md): 126 requests.
- [#5418 log-request-response-string-encoding](5418/README.md): 360 requests.
- [#5425 ai-statistics-sparse-index](5425/README.md): 72 requests.

Published records redact local home/workspace path prefixes bytewise. Payloads, line endings, hashes, timings, results and executed harness source remain unchanged. Exact original harness source is preserved; source/heads are bound in provenance, and no Wasm binary is committed. SHA256SUMS covers published files after redaction.
