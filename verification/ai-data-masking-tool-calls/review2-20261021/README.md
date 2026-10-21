# ai-data-masking：本轮 review 修改与验证

对应 PR：<https://github.com/higress-group/higress/pull/5209>。
本轮意见：<https://github.com/higress-group/higress/pull/5209#pullrequestreview-5597650312>。

修复提交：`f16adbc79a943da2622ec99e8084ee5500ca5c51`，基于 main `6038393402ca5f57d0946442b3a041b797dc1535`。
上一版 PR 提交：`b364fa90d65030d3f7b741e7a508b1cc97592cf0`。

## 改了什么

同一个 choice 收到非结束的工具事件时，现在只发送文字窗口中可以释放的前缀，保留最近的 2 倍配置窗口。后续文字会继续和尾部拼接，因此 `MA → 工具帧 → SKED` 仍能还原成 `original`，拦截检查也能读到完整词。结束原因、DONE、错误或非 JSON 事件、HTTP 结束仍完整刷新。

检查和还原在切出前缀之前完成。这还覆盖了同一个网络回调包含多个事件、匹配词恰好跨过前缀切点的情况。未通过拦截检查的尾部不会标记为已通过，防止后续结束帧把它释放。

每个 choice 自身的文字顺序保留；同一上游事件中不同 choice 之间的相对输出顺序不保证，因为文字分别缓存。最多一个保留窗口的文字可以跟在本 choice 的非结束协议事件之后。

另外去掉了文字帧上已知无害的空 `logprobs`、`token_ids` 造成的冗余控制帧；非空值和未知字段继续保留。删除未使用的 `number_merge.rs`，并将队列中的文字窗口装入 `Box`。工具参数仍原样透传。

## 回归结果

| 检查 | 结果 |
| --- | --- |
| 原提交增加两个同 choice 回归用例 | 原有 24 项通过，新增 2 项失败 |
| 仅保留尾部、尚未调整检查顺序的开发版本 | 长文本前缀切点用例失败，26 通过 / 1 失败 |
| 被拒绝尾部的结束帧回归 | 补测先失败，最终版本通过 |
| 最终原生测试 | 30/30 通过，包括 1、19 和整帧分段 |
| 格式、Clippy、WASM release、维护者指定 make test | 均通过，见 `checks.json` 及对应日志 |
| 固定响应在实际 Gateway 中的四路径对照 | 552 次：关闭插件、main 原版、上一版 PR、最终版各 138 次 |
| 最终版固定响应检查 | 138/138 通过 |
| 实际敏感词拦截对照 | 48 次；最终版 16/16 命中真实拦截日志，客户端没有收到完整敏感词 |
| 新的 dsv4 测试服务请求 | 14 次，直连 2 次，关闭插件 / main 原版 / 最终版各 4 次 |

上一版 PR 的同 choice 固定用例中，8 次文字还原失败，另有 8 次拦截间隔用例将完整敏感词下发给客户端。最终版本对应检查全部通过。这些是受控用例的结果，不代表生产自然失败率。

固定响应比对允许省略已知无害的空 `logprobs`、`token_ids`；非空值、未知字段及其重复值顺序仍检查。上游 write 分段不等同于 Envoy 的实际 body callback 分段，因此还保留了原生测试中的确定性分段检查。

真实模型使用原始响应，没有重放或人为切分。Envoy 原生 Tap 记录同一次请求的插件前响应，再与 curl 正文比较。两次最终版工具流的完整正文均与对应上游逐字节一致；普通文字还原和非流式工具响应也通过。工具只声明，没有执行。

| 真实流式工具路径 | 插件前增量 | 客户端收到 | 结束原因 / DONE |
| --- | --- | --- | --- |
| 关闭插件，两次 | 每次 3 个 | 每次 3 个 | 完整 |
| main 原版，两次 | 每次 3 个 | 每次 0 个 | 丢失 |
| 最终版，两次 | 每次 3 个 | 每次 3 个 | 完整 |

完整请求、正文、Tap、插件命中日志和配置分别在 `runtime/` 和 `live/`。拦截测试验证的是“确实命中且敏感词没有下发”；原有合成拒绝响应的流式结束协议不在此次修改范围。

## 版本和构建

- Gateway：`higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299`，Envoy 1.36.10。
- Builder：`higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/wasm-rust-builder@sha256:31758209b0ab11bb81db4c07789d1b93072c46f63ecb10f1ee88863baf659d90`，Rust/Cargo 1.82.0，wasm32-wasip1，Linux/amd64。
- `baseline.wasm`：原 main `43ad04ee`；它与本轮 main 的整个 `plugins/wasm-rust` Git tree 相同，见 `source-revisions.json`。
- `runtime/pre-review.wasm`：上一版 PR `b364fa90`，SHA-256 `3e8a3555c542092f3744eb6d5ddc22ed49f0ee3982530c5f2f8af2ee1abb3bd3`。
- `fixed.wasm`：本轮 `f16adbc7`，SHA-256 `4d27a77b268187333f7654e8d532e2b266bb039e63e241098e9ffcd23fd691e3`。
- `tested-source.json` 与 `source-snapshot/` 记录本次实际测试的源码；提交后再次核对相同。

在对应源码及上述工具链中执行：

```sh
make -C plugins/wasm-rust PLUGIN_NAME=ai-data-masking test
cd plugins/wasm-rust/extensions/ai-data-masking
cargo fmt --all --check
cargo test --offline --locked
cargo clippy --offline --locked --all-features --all-targets -- -D warnings
cargo build --offline --locked --release --target wasm32-wasip1
```

`--offline` 需要先备齐 Cargo.lock 对应依赖。实际执行的容器命令、返回码和日志见 `checks.json`。

## 核对与重跑

下载本目录后可离线核对：

```sh
shasum -a 256 -c SHA256SUMS
python3 check_results.py
```

固定响应重跑需要 Docker：

```sh
python3 -u runtime/verify_runtime.py
python3 -u runtime/verify_denial.py
```

真实模型重跑脚本为 `live/verify_live.py`，需另行建立可访问相应 dsv4 测试服务的本地隧道（20637 端口），不包含登录凭据。这里的 dsv4 是测试服务模型名，不代表客户生产部署的验证。

本轮容器、网络和 SSH 隧道均已清理，见各级 `cleanup.json`。没有修改客户生产环境。这些验证材料位于独立分支，不随代码 PR 合入。
