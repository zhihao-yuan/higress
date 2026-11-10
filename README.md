# #5213 / #5299 verification records

This review copy was prepared on 2026-11-10 for [PR #5299](https://github.com/higress-group/higress/pull/5299). These records support review; they do not mean every Design TASK is complete or that a maintainer has accepted the verification.

## Current head and CI follow-up

The current head is `7d9223a61c1dd88a827945d8aabc8afc70e119ce`, merging upstream `1fef633553462434ccafad94a6ef35d2b367450f` (v2.2.6). Its committed Rust workspace is in `source-head`. The current release module was built with Rust 1.80.0 and has SHA256 `3b1c7e8f1f1a69824b0435d0b4302b00d064027744d49817ea7023c34f7eb6d1`.

| Records | Current-head result |
| --- | --- |
| `native/ci-rust180-merged-20261110` | 88 tests, formatting, Clippy with warnings denied, and release Wasm compilation passed under Rust 1.80.0 |
| `native/head-7d9223a6-native-20261110` | Rust 1.82 verification and the Makefile test entry after restoring the mutations; exact commands and results retained |
| `mutations/head-7d9223a6` | 20 behavior-breaking mutations tested on this head; every one caused an assertion failure and the source was restored |
| `runs/unparsed-ci-rust180-20261110-a` | 72 raw-buffer checks passed; the pre-P2 comparison forwarded 24 over-limit cases that the candidate rejects |
| `runs/red-green-ci-rust180-20261110-a` | Eight expected upstream assertion failures followed by eight candidate passes |
| `runs/capacity-options-head-7d9223a6-20261110-a` | 128 formal requests passed across two configured capacity profiles, with the same current module off/on at concurrency 32 |
| `ci/ci-github-green-20261110.json` | All five GitHub workflows passed on this head; workflow/run IDs retained for independent live checking |

The two gateway runs used source `35c50060f6c935e76101a3460bc044141396e3b7`. The subsequent upstream merge changed only the official `VERSION` file under the Rust workspace. The post-merge build produced exactly the same Wasm bytes, checked against both saved runtime modules. Both builds, their source hashes and the binary identity are retained under `builds/ci-rust180-*`. This does not reclassify the earlier full functional matrix below as a run on the current module.

The CI compiler failure is retained: `Option::is_none_or` worked in the earlier Rust 1.82 builder but was unavailable in the plugin Dockerfile's Rust 1.80 build. The fix uses an explicit match and retains rejection on overflow or a breached limit. The minimal compiler failure is separate from the assertion-based mutation results.

Mutation 20 was interrupted before a result was recorded. Its partial log/source snapshot are retained under `ci/interrupted-probe-ceiling-20261110` and are not counted as a killed mutation. The temporary change was verified and restored, then that focused test was rerun to obtain the completed result. The other 19 results were retained.

The first CI follow-up also compared a new upstream 2.2.6 snapshot against the old event base. Synchronizing upstream corrected the comparison scope; no snapshot hashes or release policy were edited. Local optional release-tool checks in the minimal Go image failed for missing git/jq, and two host tests failed because macOS Bash lacks `mapfile`. Those attempts are retained under `ci`; they are not counted as passed. Host catalog validation passed, and the actual Linux GitHub preparation workflow, including its release-tool tests, passed on the current head.

The current-module profile subset used three arguments per response, four warm-up requests and 32 measured requests per off/on group, concurrency 32 and one gateway worker. These are two explicit configurations, not approved release defaults or the full V4 capacity matrix:

| Per-call / response limits | Argument size × count | Complete-arguments P95 off / on | Sampled gateway RSS off / on |
| --- | --- | --- | --- |
| 64 KiB / 256 KiB / 128 calls | 63 KiB × 3 | 1.46 s / 3.63 s | 426.0 MiB / 429.0 MiB |
| 256 KiB / 1 MiB / 128 calls | 255 KiB × 3 | 3.05 s / 6.31 s | 425.0 MiB / 467.0 MiB |

The module is the current Rust 1.80 artifact on both sides. Saved result rows, `/proc/1/status` samples, cgroup CPU/memory readings and Wasm memory gauges are retained; the offline checker recomputes response assertions, sampled RSS and nearest-rank P95. Host timing differs from the earlier historical round; no speedup or regression across those rounds is inferred from these numbers.

## Full functional matrix on revision 3f7a3a3c

This functional revision is `3f7a3a3c8163e07b09e414cd5e3d0ebd405aa5d8`. Its Rust 1.82 release Wasm SHA256 is `162d579bce687752d12832a13e24df70ba081d2797ee599fd2972f594f4a6c03`. The committed Rust workspace snapshot is in `source/plugins/wasm-rust`. Build commands, source hashes and logs are in `builds/build-p2-final-20261109`.

| Records | Result on revision 3f7a3a3c |
| --- | --- |
| `native/p2-unparsed-20261109-final` | 88 native tests, formatting and Clippy with warnings denied passed |
| `native/p2-final-20261109-make-test` | Makefile test entry passed, 88 tests, after mutations were restored |
| `mutations/current` | 20 behavior-breaking mutations caused assertion failures; none survived; source restored |
| `runs/red-green-p2-final-20261109-a` | 8 expected baseline assertion failures, then 8 candidate passes |
| `runs/unparsed-final-20261109-a` | 72 checks passed, including 24 demonstrated pre-fix buffer bypasses |
| `runs/runtime-p2-final-20261109-a` | 1,568 runtime checks passed |
| `runs/limits-p2-final-20261109-a` | 424 logical-budget checks passed |
| `runs/flags-p2-final-20261109-a` | 448 explicit-false checks passed |
| `runs/legacy-p2-final-20261109-a` | 96 legacy checks passed |
| `runs/disabled-p2-final-20261109-a` | 80 disabled-scope and large-input checks passed |

Each run has its actual fixture, configuration, script snapshot, request/response bytes, module hashes, logs, result ledger and cleanup record. Counts describe that run's checks; they are not counts of independent production requests. Synthetic runs made zero model calls.

`max_unparsed_bytes` bounds a pending raw frame or undecided protocol prefix before appending. It inherits the configured `max_buffer_bytes` unless explicitly set. It is independent of decoded argument budgets because JSON escaping and protocol bytes have different sizes. A callback containing many individually valid frames is processed incrementally; its aggregate size is not treated as one frame. Rejection clears buffered state and later callbacks cannot emit arguments or DONE.

The two native `*-red` directories retain real failing assertions: the original unclosed-frame case and the separate undecided-prefix case. Their source snapshots and patches identify the test inputs. Intermediate green snapshots are omitted; final green checks use the committed source above. Mutation failures are assertions, not compiler failures.

## Baselines and historical records

The upstream baseline used in the recorded tool-scope comparisons is `942b6cfa56fc0c352ad75ca07a0a7a09272f0879`, Wasm SHA256 `6f7c14be55be28008463e1a01439e6fbfc7c365dd1cf4310d3d0e8beaaab4b7d`. The P2 comparison uses the pre-P2 functional source `8ee506a2a727cb7793bc909fc74e53c204df6218`, Wasm SHA256 `4680dc6260926a59b72414d1dbe051d6b71cc0adff79d64b0f47e675a6305021`. Per-run manifests identify which baseline was actually used. Later upstream `1fef6335` updates the Rust plugin VERSION but does not change its Rust implementation from `942b6cfa`.

`history` contains earlier evidence. Its capacity and live-model results used source `aedc63503d7ab3f42f8dd246c7e02c44fd0818bc`, Wasm SHA256 `5ddb3f79f8bf08b0317d7c0251a52a6d305ff05d33c85a60fc56890dab0dcea2`. Those results do not verify the current source. The live round made 15 actual calls: one health check and 14 formal requests. A later offline analysis corrected a finish-reason assertion against the same saved captures; it made no new calls. Both the original result and corrected analysis are retained. The separate host-failure probe deliberately panics and is not a release module. Failed attempts remain identified as failures.

The final scalar defaults still need maintainer confirmation: code retains candidate values of 1 MiB per call, 4 MiB total and 128 calls; 64 KiB / 256 KiB / 128 was proposed in the Design discussion. The full V1/V2 matrix on the final module/configuration, current-source capacity and live-model release validation remain pending under T1/T4/T5/T6. Historical capacity results and successful synthetic tests do not settle that decision or complete those TASKs.

## Offline verification

Use Python 3.12 or later. From this directory:

```sh
python3 -B verify_package.py
```

This checks the root file manifest, run manifests, body hashes, saved red/green and raw-buffer assertions, native source/diff hashes, all 20 mutation failures and restoration, and the offline live-capture analysis. It does not start Docker or contact a model. Nested manifests cover the files in their own directory; the root manifest also covers nested manifests and all published files.

## Repeating tests

Use a fresh clone of the repository at the revision for the records being reproduced. Build manifests record the exact commands. The pinned builder is:

`higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/wasm-rust-builder@sha256:31758209b0ab11bb81db4c07789d1b93072c46f63ecb10f1ee88863baf659d90`

It provides Rust 1.82 and `wasm32-wasip1`. The CI compatibility runs installed the exact additional toolchain with `rustup toolchain install 1.80.0 --profile minimal --component rustfmt --component clippy --target wasm32-wasip1`. Native commands from `plugins/wasm-rust/extensions/ai-data-masking` are `cargo test --locked`, `cargo fmt --all --check`, and `cargo clippy --locked --all-features --all-targets -- -D warnings`. Build the release module with `cargo build --locked --release --target wasm32-wasip1`. Use `cargo +1.80.0` for the CI module or `cargo +1.82.0` for the Design's native matrix. Actual run records include `--offline`, which requires an already populated dependency cache.

The pinned runtime is:

`higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299`

Gateway 2.2.5 / Envoy 1.36.10 runs Linux amd64 with one worker. The recorded host is macOS x86_64 with an x86_64 Docker Linux VM, eight vCPUs and about 8.22 GB VM memory. Timings include the development VM and shared host resources and are not production capacity promises. Run the saved script, supplying newly built modules and a fresh output directory/resource prefix, for example:

```sh
python3 -u reproduce/verify_unparsed.py \
  --baseline-wasm /absolute/path/pre-p2.wasm \
  --candidate-wasm /absolute/path/candidate.wasm \
  --baseline-source 8ee506a2a727cb7793bc909fc74e53c204df6218 \
  --candidate-source 3f7a3a3c8163e07b09e414cd5e3d0ebd405aa5d8 \
  --output /absolute/path/new-unparsed-run \
  --resource-prefix unique-owned-name
```

The current Rust 1.80 raw-buffer run can be repeated with the same command using the current module and `--candidate-source 7d9223a61c1dd88a827945d8aabc8afc70e119ce`. It is the same executable script and the tested module bytes are identical across the upstream merge.

Other runs retain their exact executable script under their snapshot directory and their arguments in the manifest. Paths are placeholders after review redaction. For mutation reproduction, put the clone at `LAB/higress`, copy `run_native.py`, `run_mutations_b.py`, `run_mutations_c.py` and the selected current-mutations helper from `reproduce` to `LAB`, and create an owned builder container named `higress5213-builder` with `LAB/higress/plugins/wasm-rust` mounted at `/src`. Use `run_current_mutations_20261109.py` at source `3f7a3a3c`, or `run_current_mutations_20261110.py` at source `7d9223a6`. Each creates a fresh evidence directory, changes one source location at a time, records the assertion failure and restores the original bytes. Use a disposable clone; do not run it in a shared working copy.

## Review redaction

Administrative absolute host paths and private Docker peer addresses in logs were replaced. Synthetic case bytes, committed source, fixtures and Wasm modules remain unchanged. Earlier live evidence was separately reviewed to remove unrelated service metadata while preserving the request bodies, Tap bodies and truncation flags. Original records stay private and immutable. Where provided, `public-copy.json` records the original checksum-manifest hash and changed administrative files. Public checksum manifests were regenerated after redaction; they verify this review copy, not the private originals.
