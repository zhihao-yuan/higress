# ai-cache 上传完成回调：基线复现

生产源码固定为 `d388d06a92dd125bbe99330888690fd6deeb352f`，未修改生产代码。本目录用于复现现有问题，尚无修复版对照。

## 组件与结果

- Gateway：官方 v2.2.5 镜像，固定摘要，单 worker，fail_open=false。
- 向量库：真实 Qdrant 1.20.0，镜像与存储由 real-qdrant/compose.yaml 定义。
- embedding 和模型：本地固定 HTTP 响应。
- 原插件：从固定官方提交编译的 ai-cache Wasm。
- 辅助宿主测试：使用原模块和测试 SDK，DashVector HTTP 响应为固定值。

| 场景 | 请求结果 | Wasm crash_total | 数据检查 |
| --- | --- | --- | --- |
| 正常转发，空集合开始 | 200、200、200 | 0 | 首次写入真实 Qdrant，后两次命中答案 |
| 响应等待，第 1 个全新 Gateway | 200、503、503 | 1 | 写入数据可独立读回、检索 |
| 响应等待，第 2 个全新 Gateway | 200、503、503 | 1 | 写入数据可独立读回、检索 |
| 响应等待，第 3 个全新 Gateway | 200、503、503 | 1 | 写入数据可独立读回、检索 |

响应等待由 Lua 完整读取响应后发起另一个 HTTP 调用实现。测试桩等日志中出现本次 Qdrant 写入的完成回调开始后才放行该调用；不靠固定延迟猜测回调时机。写入回执在原请求仍有响应处理未完成时到达，触发上传方法中的空回调。

该条件必须保留：正常转发对照没有崩溃，不能将结果说成每次语义缓存写回都会崩溃。回溯指向 qdrantProvider.UploadAnswerAndEmbedding.func1，crash 发生后同一单 worker 测试实例的后续请求为 503。

DashVector 的 Go/Wasm 宿主测试同样捕获空指针。该测试主动要求旧代码 panic，测试 PASS 表示成功观察到现有问题，不代表问题已修复。

## 查证

- provenance.json：源码、Go/SDK、Gateway/Qdrant 镜像和实际 Wasm 摘要。
- discovery_upload_test.go、host-repro.log：原模块的 Go/Wasm 请求、响应和写回回调。
- real-qdrant/gateway-direct/：正常对照、请求响应、Wasm 指标、真实数据库读取证明。
- real-qdrant/gateway-held-{1,2,3}/：三轮异常、网关日志、回调观察及真实数据证明。
- real-qdrant/smoke-results.json：真实建库、写入、按 ID 读取和向量检索。
- real-qdrant/persistence-results.json：容器重启完成后，原记录仍可读取。
- redaction.json：本机绝对路径替换前的原始文件 hash；请求响应中的测试数据保留。
- SHA256SUMS：本目录文件的 SHA-256，不上传 Wasm 二进制。

临时 Gateway、HTTP 测试桩及其端口已清理。Qdrant 作为本机验证服务保留运行，测试集合和数据卷保留；该服务不是临时网关清理范围。

## 复跑

需要 Python 3.12+、Go 1.27.3、Docker Compose，并让本地 Higress 仓库包含上述提交。进入本目录：

```sh
GO=/path/to/go python3 reproduce.py /path/to/higress
```

脚本从固定提交构建原插件，执行辅助 Go/Wasm 复现，启动真实 Qdrant，再跑正常对照及 3 个全新 Gateway 的响应等待复现。每轮创建独立集合并保留数据。Wasm 构建禁用 VCS 信息；源码目录不同可能影响二进制字节，本轮实际模块 hash 见 provenance.json。

单独运行网关复现：

```sh
docker compose -f real-qdrant/compose.yaml up -d
python3 real-qdrant/verify_gateway_real.py --label=rerun-direct
python3 real-qdrant/verify_gateway_real.py --hold-response --label=rerun-held
```

上述命令需要先有构建出的 baseline.wasm。API 只绑定本机 http://127.0.0.1:16333，数据库容器名为 higress-pr-qdrant。停止数据库并保留数据可执行 docker stop higress-pr-qdrant；再次启动用 docker start higress-pr-qdrant。

当前证据只覆盖基线缺陷发现。正式修复和验证按维护者批准的 Design/TASK 开展。
