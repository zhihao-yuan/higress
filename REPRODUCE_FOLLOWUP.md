# Rechecking the current follow-up

For offline verification, run `python3 -B verify_package.py` from the package root, or `python3 -B followup-20261111/verify_followup.py` for the new round. Use Python 3.12 or newer (the recorded host used Python 3.14). Neither check starts a gateway or calls a model.

For a fresh runtime run, use a separate lab directory with the Higress Git checkout named `higress`, check out source `9efa167c17346817ad7487e752ede06d20276b72`, and copy the needed scripts from `followup-20261111/tooling` into the lab root. Paths in saved command receipts use `/path/to/verification-lab` for this directory. They are administrative substitutions, not literal paths to use on another machine.

The pinned builder image is recorded in `followup-20261111/builder-identity.json`. The approved native build uses its Rust 1.82.0 toolchain. The runtime comparison additionally installs exact Rust 1.80.0 with rustfmt, Clippy and target wasm32-wasip1; commands select that toolchain explicitly. Prepare Cargo dependencies with the extension Cargo.lock before using the recorded --offline commands. The SDK root lock is separate and is not the selected extension lock.

`build_review2_20261111.py REVISION LABEL CACHE_LABEL` exports the requested Git revision, verifies the selected Cargo project, builds with --locked/--offline, and records source/lock/archive/module hashes. Build both upstream `1fef633553462434ccafad94a6ef35d2b367450f` and the candidate with the same toolchain. Detailed per-run commands and configurations are in each run and the receipt files. The standalone runtime runner captures fixture.py and verify_runtime.py; the shared generic integrity checker is retained in the other Lab-based run snapshots.

All gateway runs use the recorded immutable Higress image and one worker. Give each functional runner its own output directory and Docker resource prefix. Complete compiler and other functional jobs before capacity measurement. Capacity makes no automatic request retries. Keep the machine awake and its lid open for the entire run; the first round's documented lid sleep is retained as an invalid measurement attempt.

The deliberate panic module under followup-20261111/builds/fault-probe is diagnostic only. Its recorded patch must never be substituted for the candidate module.

Real-model calls require separate authorization and access. The retained round already spent its full budget: one health call and 14 formal calls. To inspect it again, use offline reanalysis; do not run verify_live.py merely to check this package. A new live run requires a fresh bounded plan. Declare tools only; never execute generated calls as part of this verification.
