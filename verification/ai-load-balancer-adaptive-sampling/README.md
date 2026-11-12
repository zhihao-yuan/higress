# ai-load-balancer AdaptiveScore：重复服务名导致采样不结束

这是未修改官方代码的缺陷发现记录，不是修复版验收。

基线：`dedd5ed720b6aedd0f719860379e043764c820c9`。主工作区从 upstream/main 创建 `fix/ai-load-balancer-adaptive-sampling`，生产源码和现有测试均未修改。源码文件摘要、Go/SDK 版本、构建命令和 Wasm SHA-256 见 provenance.json 与 dependencies.json。

## 触发与对照

实际运行固定 Gateway 发布镜像，加载本机从上述基线编译的原始 Wasm。每组单 worker、fail_open=false、1 CPU / 768MiB，独立新容器。服务 a/b/c/d 是实际存在的 Envoy cluster，通过 `x-higress-target-cluster` 做路由；另设无 Wasm 的健康 listener，共用同一个 worker。

| 配置 | P2C 数量 | 独立组数 | 触发请求 | 后续健康路由 | 上游生成请求到达数 |
|---|---|---:|---|---|---:|
| `[a,b,c,d]` | 3 | 1 | 三次200 | 200 | 3 |
| `[a,a,b,b]` | 2 | 1 | 三次200 | 200 | 3 |
| `[a,a,a,b]` | 3 | 3 | 客户端3秒超时 | 客户端2秒超时 | 0 |
| `[a,a,a]` | 默认2 | 3 | 客户端3秒超时 | 客户端2秒超时 | 0 |

每组触发前健康 listener 都是200。重复配置被接受，容器仍在运行而没有OOM；相关组的CPU快照见 docker-stats.json。快照约100%仅用于辅助识别空转，不是性能压测。

这些不是网关返回的 HTTP 503，记录的是客户端读超时。上游为固定 HTTP 响应，不是真实模型；有问题的配置在选择服务时就卡住，上游没有收到生成请求。正常对照能返回完全相同的固定正文。

源码中配置保留重复项，sampleAdaptiveCandidates 按原候选列表长度选择分支，再循环收集 P2CChoices 个唯一名字；两个唯一名字无法组成三个不同候选。这解释了持续循环，也与真实 Gateway 的 worker 停滞一致。发现阶段只验证现状，候选修复、正式回归和两版对照待维护者批准后执行。

## 文件

- discovery-commands.json：每组实际命令和退出码；脚本退出0表示观察到上述现有缺陷或正常对照，不表示修复。
- summary.json：逐组响应、上游到达数、容器状态和清理断言。
- 每组目录：envoy.json、plugin-config.json、results.json、fixture-events.json、envoy.log、Wasm指标快照、容器状态、CPU快照和cleanup.json。
- discover_gateway.py / envoy-template.json：可复跑的原始 Gateway 驱动；不提取、替换或模拟采样函数。
- dedup-summary.json：公开检索范围；未发现相同根因修复，不保证不存在遗漏。
- 初次仅有 Content-Length 读取的预跑 unique-control-1 不计入本轮八组记录。最终脚本同时支持 Content-Length 与 chunked；最终唯一列表对照为 unique-control-final。

## 复跑

用独立 clone checkout 上述基线，从插件模块构建到本目录（Wasm二进制不提交）：

```sh
export GOTOOLCHAIN=local GOWORK=off
cd /path/to/higress/plugins/wasm-go/extensions/ai-load-balancer
GOOS=wasip1 GOARCH=wasm go build -mod=readonly -buildvcs=false -buildmode=c-shared -o /path/to/discovery/baseline.wasm .
cd /path/to/discovery
python3 discover_gateway.py --case unique --label rerun-unique
python3 discover_gateway.py --case duplicate-safe --label rerun-duplicate-safe
python3 discover_gateway.py --case duplicate --label rerun-duplicate-1
python3 discover_gateway.py --case identical --label rerun-identical-1
```

每次使用新 label，脚本拒绝覆盖已有证据。需 Docker Desktop 可用；固定镜像摘要在每组 results.json 中。不同本机编译路径可能导致不同 Wasm 摘要，保存实际摘要，不覆盖本次原始记录。

## 清理与边界

每组最后强制删除自己创建的 Gateway，关闭 HTTP 服务和线程，并检查全部测试端口关闭。已有本机 Qdrant 服务与数据不属于本次测试，没有修改或删除。

本次只复现本地 AdaptiveScore 路径；全局 in-flight 也调用同一采样函数是源码关系，不冒称运行过真实 Redis。没有复用客户生产环境或发送真实模型请求。
