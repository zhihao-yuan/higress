# 维护者意见后的最终验证（2026-10-21）

维护者意见：https://github.com/higress-group/higress/issues/5168#issuecomment-6309039625 。本目录是该意见落实后的版本；父目录保留 10 月 20 日的早期候选验证，不作为当前最终版本。

## 版本和环境

- 官方 main 基线：`43ad04ee54139935e9b51fbebec19986fb9f8508`。
- 修复提交：`b364fa90d65030d3f7b741e7a508b1cc97592cf0`，分支 `fix/ai-data-masking-tool-calls`。
- macOS 15.6.1；Docker Linux/amd64；Rust/Cargo 1.82.0；wasm32-wasip1。
- 固定 Gateway：`higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299`，Envoy 1.36.10，单工作线程。
- 固定 Builder：`higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/wasm-rust-builder@sha256:31758209b0ab11bb81db4c07789d1b93072c46f63ecb10f1ee88863baf659d90`。
- 基线 WASM 沿用父目录中从上述 main 源码构建并核对过的产物；相关基线构建日志和 62 个源码文件核对记录见父目录。没有使用发布版 WASM 冒充 main 构建。

| 模块 | SHA-256 |
| --- | --- |
| baseline.wasm | 6798495acea60881c23d3b88b61868d43daf422d6b06c912f336bae2c82d6484 |
| fixed.wasm | 3e8a3555c542092f3744eb6d5ddc22ed49f0ee3982530c5f2f8af2ee1abb3bd3 |

## 代码与原生测试

按 choice 刷新文字，不再用 last_value 复制文字帧；保留工具、role、refusal、未知及空字段。辅助元数据不打断跨帧文字匹配。正常收到 DONE 时及时转发并去重；只有全部 choice 有结束原因且没有上游错误时，才在 HTTP 结束处为缺少 DONE 的正常响应补一个。未完成和报错的流不会被补成正常结束。

原生测试最终 24 项通过，fmt、Clippy（-D warnings）、release WASM 构建及维护者指定的 make test 入口均通过。精确日志在本目录。

```sh
make -C plugins/wasm-rust PLUGIN_NAME=ai-data-masking test
cd plugins/wasm-rust/extensions/ai-data-masking
cargo fmt --all --check
cargo test --offline --locked
cargo clippy --offline --locked --all-features --all-targets -- -D warnings
cargo build --offline --locked --release --target wasm32-wasip1
```

命令在固定 Builder 中执行，测试清理目标目录使用挂载目录的子目录。第一次 make 已通过测试但 cargo clean 无法删除挂载点，改用子目录后完整 make 返回 0；最终日志为 make-test-review-final.log。

native-red.log 是最初在官方 main 上加入五项回归后的 9 通过、5 失败。native-review-red.log 是上一候选提交加新测试后的 17 通过、4 失败；native-ancillary-red.log 是改造中间版本的 23 通过、1 失败，复现了元数据打断文字还原的问题。最终 native-review-final.log 和 make-test-review-final.log 均为 24 通过。不要将中间候选红测说成官方 main 的原生测试结果。

## 实际 Gateway / proxy-Wasm 固定响应对照

共 366 次请求，关闭插件、main 原版和修复版各 122 次。每条路径有 80 次流式工具请求。每个流式场景分别一次写出、逐事件写出、17 字节写出、首字节单独写出后再分段，各重复两轮，另有两次非流式工具请求。

| 路径 | 请求数 | 工具增量不一致 / 流式工具请求 |
| --- | ---: | ---: |
| 关闭插件 | 122 | 0 / 80 |
| main 原版 | 122 | 71 / 80 |
| 修复版 | 122 | 0 / 80 |

修复版 122 次全部通过工具、按 choice 拼接的文字和思考字段、结束原因、DONE、usage、错误及附加元数据检查。71 是这一轮分段对照的观察值，不代表生产失败率；上游 write 边界不等于 Envoy 回调边界。

在原有场景上加入多 choice 交错、role/refusal/未知字段、finish-only、缺少 DONE、结束后报错。普通文字场景同时携带真实服务常见的 logprobs:null、token_ids:null 等元数据。JSON 对象成员的排列顺序不参与比较，但同一字段的多次值序列和重复数量必须一致。工具声明和返回的工具名称及参数也做离线校验。

原始请求、上游响应、客户端响应、日志和结果在 runtime-evidence-review/。固定响应脚本不调用真实模型，不执行工具。

## 真实模型

最终版本重新向模型 ID 为 dsv4 的服务发起 14 次请求：直连模型 2 次，关闭插件、main 原版、修复版各 4 次，含流式工具、普通文本和非流式工具。没有回放或人为切分模型响应，没有执行工具。

原版的两次流式工具请求：插件前每次 3 个增量，客户端每次 0 个；修复版两次均为 3 → 3，finish_reason 和 DONE 完整。两次修复版的整个工具流正文也与同一次请求的原生 Tap 上游正文逐字节一致。普通文字的 MASKED_TOKEN 能还原为 DEMO_SECRET，非流式工具正常。

完整请求和响应在 live/，同一次上游抓取为 *.upstream.body。Tap 上限 1MiB，未截断。WASM crash、fail-open 和未初始化相关计数为 0。输出摘录见 before-after-frames.md。

这验证的是指定测试模型服务，不是客户生产部署，也不据模型 ID 判断底层模型的准确版本。开发中失败的中间尝试保留在本地，不混入本目录的最终 14 次结果。

## 重跑和边界

```sh
shasum -a 256 -c SHA256SUMS
python3 check_results.py
python3 -u verify_runtime.py
```

前两条离线核对保存的结果和哈希；第三条需要 Docker、Python 3、curl，重发 366 次固定请求，会覆盖本地同名输出，先复制保存原始记录。Builder 首次构建还需安装 rustfmt、clippy 和 wasm32-wasip1，首次准备锁定依赖需要网络。

真实模型脚本 live/verify_live.py 需要自行配置本机 127.0.0.1:20537 和 Docker host.docker.internal:20537 到测试模型的接入，再运行会产生 14 次真实生成请求。脚本不读取凭据，不配置隧道。

工具参数原样保留，不做文字替换。usage 按上游事件保留，不再按旧逻辑累加。文字重组、辅助元数据独立透传可能改变分帧数量和边界；不保证修复路径与上游逐字节相同，工具流逐字节一致只是这两次真实请求的实测结果。没有生产容量和并发性能基准，不声称零开销。

测试容器、网络、构建容器及 SSH 隧道已清理，20537 无监听，见 cleanup-complete.json。没有修改客户生产环境。验证材料放在独立分支，不随修复 PR 合入官方代码。
