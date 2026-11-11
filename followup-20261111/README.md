# 2026-11-11 review follow-up

Code: `9efa167c17346817ad7487e752ede06d20276b72`. Baseline: upstream `1fef633553462434ccafad94a6ef35d2b367450f`. Both runtime modules were built with Rust 1.80.0, the same locked dependencies, and the pinned builder recorded in `builder-identity.json`. The primary module SHA256 is `59b25818e30da43aa32b071e34ce22e4ccfccdfebac94cb86da7bc08c878af6b`.

The raw deny checker now receives a frame only after its wire size has been checked; it no longer copies an entire host batch. Tests also check retained allocation and rejection before copying an oversized frame. Recognized ordinary JSON responses no longer acquire the unparsed-SSE ceiling. A real pre-fix red run preserves both maintainer repros.

Defaults remain **1 MiB per call / 4 MiB per response / 128 calls**, following the [latest maintainer review](https://github.com/higress-group/higress/pull/5299#issuecomment-6773247925). These are transitional values. Lowering them later requires decoded argument P95/P99 and exceedance observations. The deny-word overlap and HTTP/JSON/encoding allocations are separate costs; these byte quotas are not RSS caps.

`lock-provenance-corrections.json` corrects six earlier build manifests: the effective project lock is `plugins/wasm-rust/extensions/ai-data-masking/Cargo.lock` (SHA256 `267ee4b1873ea76e260d416e20bdf0335c9e63df3fe3098854254b7aa848f99c`). `6fc987...` belongs to the SDK root lock, now labeled separately. Original uncorrected manifests remain immutable in evidence commit `b5a7e51cf7a68a69db52110b9cb0ab9f9520f891`; source, Wasm and runtime payloads were not changed by this correction.

## Current-source verification

- Rust 1.80.0: formatting, 93 native tests and all-feature/all-target Clippy passed.
- Rust 1.82.0: formatting, Clippy, release build and the original Makefile test entry passed (93 tests). An additional Rust 1.82.0 `cargo test --locked --offline` run passed the same 93 tests (test debug information disabled, assertions unchanged). Its alternate module is build-only evidence; gateway runs use the Rust 1.80 module above.
- Six new behavior-breaking mutations on this source were all caught by assertions (exit 101, not compilation errors). Sources were restored byte-for-byte. The earlier 20-mutation rounds remain labeled with their actual earlier revisions; they are not relabeled as runs on this head.
- Full runtime: 1,568 checks; all eight switch combinations/dictionary modes: 448; legacy rules: 96; disabled large/malformed inputs: 80; upstream content merge: 70.
- Framing/format: 160 checks, including raw-deny batching, oversized-then-DONE, and ordinary JSON without Content-Type. The pre-P2 baseline forwarded 48 cases the candidate rejects.
- Configurable limits: 520 checks, including default 127/128/129 call edges. Additional unchanged defaults: 192 checks around 1 MiB input, request history, restored output, and 4 MiB total retained bytes including attribution metadata. Equal-size cases are not hidden by restoration shortening.
- Configuration updates and deliberate diagnostic VM failure passed. The deliberate panic module and patch are separate from the production candidate; its failure must not be called a candidate runtime crash.
- Capacity: 36 groups, 32 formal requests and four warm-ups per group, concurrency 1/8/32; 1,152 formal responses passed complete argument/text/usage/finish/DONE checks. Compilers and other owned functional runners completed before measurement.
- Real model: 1 health generation plus 14 formal generations; all 14 target cases covered. Same-request Tap and client captures retained. No tool execution, no automatic retry. Offline reanalysis makes zero new model calls.

## Capacity observations at concurrency 32

| Group | Sampled peak RSS (MiB) | Complete-response P95 (s) |
| --- | ---: | ---: |
| 4k-c32-baseline | 422.1 | 0.224 |
| 4k-c32-candidate-off | 434.2 | 0.332 |
| 4k-c32-candidate-on | 431.6 | 0.238 |
| 256k-c32-baseline | 424.2 | 0.613 |
| 256k-c32-candidate-off | 427.5 | 0.518 |
| 256k-c32-candidate-on | 451.6 | 1.831 |
| 1m-c32-baseline | 421.5 | 2.828 |
| 1m-c32-candidate-off | 429.3 | 2.123 |
| 1m-c32-candidate-on | 594.2 | 9.528 |
| near-total-c32-baseline | 423.3 | 7.804 |
| near-total-c32-candidate-off | 430.0 | 4.103 |
| near-total-c32-candidate-on | 694.8 | 25.081 |

These are developer-machine measurements with one gateway worker; fixture, client and gateway share the recorded Docker host. RSS is sampled. The raw Wasm metric names and values are preserved per group. These data do not establish production capacity.

## Rechecking and attempts

Run `python3 -B verify_followup.py` from this directory, or the parent `python3 -B verify_package.py` for the complete historical-plus-current bundle. Checks re-read saved bodies, source/lock hashes, complete capacity responses and same-request model Tap; they do not call the network.

Every run preserves its actual source/fixture/script/module hashes, configurations, commands, payloads, statistics and cleanup. Administrative paths and Docker peer addresses in logs are removed only in this public copy. Case data, script snapshots and Wasm bytes remain identical to the private originals. Unrelated model-list entries and server metadata are omitted; the selected model and original private listing hash are retained.

Attempts are retained separately. They include a test-harness compile correction, a corrected whole-body Jieba oracle, cancelled diagnostic/compiler runs, and the sequential controller refusing an already-running parallel legacy directory. Successful parallel receipts identify the actual run; this transition did not repeat the suite. The first capacity round contains a 504/UT while the laptop was in a documented clamshell sleep: Envoy measured 124.564 seconds, versus 7.718 seconds on the client clock. That performance round is invalidated and retained separately. A temporary awake assertion and open lid were confirmed; a targeted 32-request control and a complete fresh round followed with identical code, quotas and 120-second route timeout. Native red and mutation assertion failures are distinct from these attempts.
