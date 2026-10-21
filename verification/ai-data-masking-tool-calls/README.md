> 最新的 review 后验证见 [review2-20261021](review2-20261021/README.md)：提交 `f16adbc7`，30 项原生测试、600 次固定网关请求和 14 次新的真实模型请求。以下保留首轮验证记录。

> 最新维护者意见后的代码和验证见 [2026-10-21 最终记录](review-20261021/README.md)。以下为 2026-10-20 的历史候选记录。

# ai-data-masking 流式工具调用修复验证

2026-10-20 的本地验证记录。验证材料放在独立分支，不随插件修复 PR 合入官方代码。

## 版本与环境

- main 基线：`43ad04ee54139935e9b51fbebec19986fb9f8508`。
- 修复提交：`551307a9b87c21c96ca1d4efed191e9ce53127f2`，位于贡献者 fork 的 `fix/ai-data-masking-tool-calls` 分支。
- macOS 15.6.1；Docker Linux/amd64；Rust 1.82.0、Cargo 1.82.0；构建目标 wasm32-wasip1。
- 两版均从官方源码构建，使用各自源码中未修改的 Cargo.lock；SDK 锁定至 `8c902102091698bec953471c850bdf9799bc344d`。
- 官方 Gateway v2.2.5，Envoy 1.36.10，单工作线程。
- 固定 Gateway 镜像：`higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299`。
- 固定构建及测试上游镜像：`higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/wasm-rust-builder@sha256:31758209b0ab11bb81db4c07789d1b93072c46f63ecb10f1ee88863baf659d90`。

| 模块 | SHA-256 |
| --- | --- |
| baseline.wasm | 6798495acea60881c23d3b88b61868d43daf422d6b06c912f336bae2c82d6484 |
| fixed.wasm | 08490515334f7975f54042a246e96d2b8e7bc5bf68aa52e90cf7e6b2254737ce |

构建日志、工具链、源码文件指纹见 baseline-build.log、fixed-build-final.log、toolchain.json、source-revisions.json 和 tested-source-hashes.json。基线目录中已核对的 62 个 Rust 子树文件与 main Git tree 一致。

## 原生测试和代码检查

先在未修复代码上加入五个回归测试，结果为原有 9 项通过、新增 5 项失败，见 native-red.log。修复后再补充最终事件检查用例，最终 15 项全部通过，见 native-final.log。

```sh
cd plugins/wasm-rust/extensions/ai-data-masking
cargo fmt --all --check
cargo test --offline --locked
cargo clippy --offline --locked --all-features --all-targets -- -D warnings
cargo build --offline --locked --release --target wasm32-wasip1
git diff --check
```

首次准备依赖时执行过 `cargo test --locked` 下载锁定依赖，后续使用 offline/locked。固定构建镜像需要先安装 rustfmt、clippy 和 wasm32-wasip1：

```sh
rustup component add rustfmt clippy
rustup target add wasm32-wasip1
```

## 真实 proxy-Wasm 路径：固定响应对照

fixture.py 是公开的合成上游，不调用模型。verify_runtime.py 使用同一份请求模板、脱敏配置和固定 Gateway 镜像，分别关闭插件、加载 main 基线 WASM、加载修复 WASM。

流式场景包括工具调用、文字后调用工具、两个交替工具、普通文字、长参数、单帧混合文字和工具、null/缺少 delta 的结束事件、错误事件、末尾没有分隔空行的文字事件。每个场景分别一次写出、逐事件写出、17 字节分段、首字节单独写出后按 17 字节分段，各重复两轮；另有两次非流式工具调用。

| 路径 | 请求数 | 流式工具请求数 | 工具增量与上游不一致 |
| --- | ---: | ---: | ---: |
| 关闭插件 | 82 | 56 | 0 |
| main 原版 | 82 | 56 | 46 |
| 修复版 | 82 | 56 | 0 |

总计 246 次固定响应请求。关闭插件的响应正文逐字节一致；修复版 82 次均通过工具增量、文字还原、finish_reason、[DONE]、usage 和错误事件检查。长参数场景的 25 个工具增量完整保留。

main 的表现随到达分段变化，不是每种分段都丢工具；上面的 46 是本轮观察值，不是自然请求失败率。上游 write 的边界也不等于 Envoy 的回调边界。本次没有逐个采样所有回调，不能根据 write 次数推算回调次数。

本目录只收录工具声明完整后的正式运行。先前一轮固定测试的请求只声明 read，但上游也会返回 search/write，因此未纳入这里的正式结果；原始探索记录保留在本地。正式请求已声明对应 read/search/write 工具。真实模型请求一直正确声明 read，不受这项脚本修正影响。

精确配置见 bypass.json、baseline.json、fixed.json；逐请求输入、响应、状态和哈希在 runtime-evidence-final/。结果见该目录中的 results.json、summary.json 和 analysis-summary.json。Envoy 日志同时记录请求标识、HTTP 状态、字节数、标志和耗时；WASM crash、fail-open、未初始化相关计数均为 0。

### 重跑固定响应对照

在本目录执行，需要 Docker、Python 3 和 curl。会新建专用容器和网络，自动映射本机临时端口，finally 中清理资源。

```sh
shasum -a 256 -c SHA256SUMS
python3 -u verify_runtime.py
```

重跑会覆盖本地同名运行文件，请先复制目录保存这份原始记录。Docker 镜像按 digest 固定；模块由本目录提供，首次拉取镜像需要网络。

## 真实模型补充验证

live/verify_live.py 重新向模型 ID 为 dsv4 的真实服务发起 14 次生成请求，没有回放响应或人为切分模型响应，没有实际执行工具。

- 直连模型：工具流式、普通文本各 1 次。
- 网关关闭插件、加载 main 原版、加载修复版：各 2 次流式工具、1 次普通文本、1 次非流式工具请求。

| 同一次流式工具请求 | 模型在插件前返回 | 客户端收到 | 结束原因 / [DONE] |
| --- | --- | --- | --- |
| main 第 1、2 次 | 每次 3 个工具增量 | 每次 0 个 | 均丢失 |
| 修复版第 1、2 次 | 每次 3 个工具增量 | 每次 3 个 | 均完整 |

修复版的工具参数可正常解析为 JSON，与同一次上游调用一致。普通文本和非流式工具调用也通过。main 普通文本本次保留了 stop，但丢失 [DONE]；不概括为所有回答都会丢 finish_reason。

通过 Envoy 原生 HTTP Tap 抓取同一次调用在插件前的上游响应；抓取上限 1MiB，未截断。关闭插件时，上游和客户端响应逐字节一致。请求里的 tools 定义未改变，测试标签从 DEMO_SECRET 变为 MASKED_TOKEN，确认脱敏生效。

这是测试模型服务的验证，不代表直接验证了客户生产模型部署，也不能据模型 ID 判断底层模型的准确发布版本。公开资料不包含远端内网接入地址或 SSH 凭据。

真实请求及响应见 live/requests/、live/responses/，逐项结果见 live/results.json。重点对照：

- live/responses/baseline-tools-1.upstream.body 与 baseline-tools-1.body。
- live/responses/fixed-tools-1.upstream.body 与 fixed-tools-1.body。

重跑前需自行使对应测试模型可从本机 127.0.0.1:20537、Docker 的 host.docker.internal:20537 访问；脚本模型 ID 为 dsv4。脚本不会配置隧道或读取凭据。配置好后执行 `python3 -u live/verify_live.py`，会产生 14 次真实模型生成请求。

## 修改边界与开销

普通文字仍在窗口中匹配和还原。工具参数作为协议内容保留，不执行文字替换。仅处理已有的 content、reasoning_content 文字字段，其余协议内容按事件保留。

usage 按上游事件保留，不再为文字重组相加并附到某一个重写事件上；依赖旧累计输出行为的非标准上游需要确认兼容性。本次没有修改 number_merge.rs 的数值算法，而是移除了响应重组对它的引用。

纯工具及结束事件可直接排队输出，混合文字事件会拆分并重新序列化。队列随响应回调输出，不等待整个流结束，但仍有事件保存、解析和复制开销。没有进行生产容量或并发性能基准，不声称没有性能退化。

## 清理

固定响应、真实模型测试的专用容器和网络均已删除，构建容器已删除，SSH 隧道已关闭，20537 无监听。见 runtime-evidence-final/cleanup.json、live/cleanup.json、cleanup-complete.json。没有修改客户生产环境。

本地验证完成不等于维护者批准方案或同意合并；本材料不声明已经获得事前批准。
