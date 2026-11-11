# Review copy and redaction

The original local records remain outside this branch. This package contains selected review copies. It includes synthetic gateway fixtures and a previously captured small live-model round using synthetic secrets. It contains no SSH session setup or credential files.

Administrative host paths were replaced with `/path/to/verification-lab`. Private Docker peer addresses in logs and config dumps were replaced with `[docker-peer]`. The earlier live copy also removed unrelated service/model-list metadata and transport headers outside the verification allowlist. The same-request request/response bodies and their body hashes were retained. Tap truncation flags remain available.

Synthetic case bodies, fixture inputs, Wasm modules and Rust source snapshots remain unchanged. Native patches keep their original bytes and digests. The interruption note has no fabricated exit code and is not counted as a completed mutation. Local environment failures and the corrected live coverage analysis remain identified separately from successful results.

Run-local `public-copy.json` files, where present, identify the original checksum-manifest hash and administrative files changed in that review copy. A regenerated checksum manifest proves the public copy; it is not a claim that a redacted file still has its private original hash.

The package is scanned for personal host paths, the private registry hostname, credential-shaped strings and private network addresses, including decompressed gzip payloads. Private-address matches in public source or synthetic fixtures are reviewed separately from actual transport addresses. Package verification also recomputes request/response body hashes, which detects accidental edits to preserved case bodies.

The root `SHA256SUMS` covers every package file except itself and Git's worktree control file. The offline checker disables bytecode generation and verifies that checking the package does not add files to it. `.git` and generated Python caches are never part of the published package.


## 2026-11-11 follow-up review

The new round uses synthetic strings, one approved health generation and 14 formal model generations; no tools were executed. Personal administrative paths and Docker peer addresses in logs are redacted in this public copy. Case data, fixtures, captured upstream/client bodies, script snapshots and Wasm bytes are preserved and checked against their private originals. Unrelated model-list entries, ownership fields and creation metadata are omitted; the selected model and the private original listing hash remain in public-copy.json.

The full scan covered text, binary files and decompressed gzip payloads. No credential-shaped or personal-path matches were found. The eight private-address review hits are the upstream repository's existing README configuration examples, repeated in source snapshots and the two source archives. They are public source examples, not test endpoints. Real SSH credentials, transport endpoints and raw system power logs are excluded. The sleep diagnosis includes only relevant event times, reason category and temporary power-assertion state.

The failed first capacity round is separate from the clean full round. Its timeout, body, logs and cleanup are retained; it is not counted as a successful capacity result. No case payload or refusal body was changed during privacy review. The model connection was closed after the 15 approved calls, and its localhost forwarding port was verified absent.
