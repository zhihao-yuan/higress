# AdaptiveScore 候选去重：实现与验证

- Proposal: https://github.com/higress-group/higress/issues/5345
- Design / Verification Plan: https://github.com/higress-group/higress/issues/5346
- 批准及 TASK 授权: https://github.com/higress-group/higress/issues/5345#issuecomment-6918763401
- SPEC: https://github.com/higress-group/higress/issues/5345#issuecomment-6816823878
- 实现 TASK: https://github.com/higress-group/higress/issues/5346#issuecomment-6816870827
- 验证 TASK: https://github.com/higress-group/higress/issues/5346#issuecomment-6816886898

## 结论

原版按列表长度要求采样多个不同服务，实际唯一服务不足时随机循环无法结束。修复只改公共采样：保留原请求占比与冷却过滤，随后按服务名精确字符串去重，保留首次出现顺序，再用部分 Fisher–Yates 有界不放回抽样。局部选择和全局 Lua 参数构造共用同一方法，原配置切片不变。

候选通过模块全量测试、vet、Wasm 构建、两条入口的旧红新绿、24组真实 Gateway 矩阵及6组同 worker 并发验收。这里的 baseline assertions_passed 只代表预期缺陷已观察到，不能视为修复通过。

## 版本与环境

- 基线：`7059b8d28cce435a91569feb6288760585287460`（2026-11-17 拉取 upstream/main；与原发现基线相比，本插件源码和依赖未变化）。
- 修复：`d80e31ac5bc742e3209a33c7ee1379070393279f`，分支 `fix/ai-load-balancer-adaptive-sampling`。
- Go：1.24.4 darwin/amd64；模块 go.mod 为 go 1.24.1 / toolchain go1.24.3。两版使用同一实际工具链，详见 provenance.json。
- Gateway：`higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299`，实际 Envoy V8；每组单 worker、fail_open=false、1 CPU / 768 MiB。
- macOS / Docker 版本见 provenance.json、docker-version.json；两个独立组可并行运行，始终是每组一 worker，不将 CPU 快照作性能压测。
- 基线 Wasm SHA-256：`ac3ddf87258783b45a80815d1f17bf0a026f5f914017764afa4d97d5ad74778c`。
- 修复 Wasm SHA-256：`2eed1c4cbfdac0a507910355983b4b5e22506be21860a972512bdad6261447a7`。提交后按准确 HEAD 重建，与实际测试模块逐字节相同，见 exact-head-build.json。

固定 HTTP 上游返回同一份 JSON，不调用真实模型或 Redis。全局入口的验证是运行真实参数构造代码、检查 Lua 候选数和 service/score 参数，不声称执行了真实 Redis Lua。

## 原函数入口红绿

新增 TestAdaptiveScoreDuplicateCandidatesReturn 通过公开配置构造两种配置，并分别调用局部 selectAdaptiveScore 与全局 buildGlobalInflightLuaKeys。

每个调用放在独立测试子进程：Go test 的1秒超时输出堆栈，外层 context 3秒负责强制回收。旧版四个子用例均因 sampleAdaptiveCandidates 的循环超时退出；堆栈分别经过局部/全局入口。新版四个子用例均通过，未留下后台循环或 goroutine。

新增 TestAdaptiveScoreSamplesUniqueServicesWithoutChangingConfig 覆盖唯一/部分重复/全相同列表，默认、显式1、子集、全部、choices 大于唯一数及大于原列表长度、精确字符串身份，断言候选唯一、数量/来源正确、全部比较时保留顺序、配置切片不变。

TestAdaptiveScoreSamplingPreservesFilteringAndFallback 的请求占比+冷却、全部达到请求占比、全部冷却、过滤后全部冷却四种兼容用例，在基线与候选均通过。既有全量模块测试也在两版通过。

baseline-red-and-compat.log 退出1是目标回归红；candidate-cluster-tests.log、baseline-full-tests.log、candidate-full-tests.log、两版 vet/build 均退出0。准确命令、工作目录、环境、退出码在 check-commands.json。模块 go test 为 native 测试，真实 Wasm 执行由下述 Gateway 验证覆盖；不将 WASM_FILE_PATH 环境变量本身当作执行 Wasm 的证明。

## 真实 Gateway 矩阵：每版每配置3组，共24组

| 配置 | choices | 旧版各组 | 修复版各组 |
| --- | --- | --- | --- |
| [a,b,c,d] | 3 | 三次200，健康路由200 | 三次200，健康路由200 |
| [a,a,b,b] | 2 | 三次200，健康路由200 | 三次200，健康路由200 |
| [a,a,a,b] | 3 | 触发3秒客户端超时，随后健康路由2秒超时，上游零到达 | 三次200，健康路由200 |
| [a,a,a] | 默认2 | 同上 | 三次200，健康路由200 |

旧版两个异常配置各3组，合计6个触发请求与6个健康请求超时；容器仍运行、无 OOM，上游均未收到触发请求。逐组 CPU 快照仅辅助展示忙循环。

候选12组共36次矩阵请求，正文与固定上游字节一致；路由使用实际 cluster_header，fixture 读回选中服务名验证属于配置集合，不能用跳过插件或拒绝配置蒙混通过。全部正常组 crash_total、rebuild_total、worker_fail_open_skip_total、worker_uninitialized 均为0。

## P1：同一 worker 的真实并发

在候选的两种异常配置各3组中，额外执行一次并发阶段（共6组）。同一 Envoy 进程用 --concurrency 1，三条 listener 分别为：

1. 原样重复配置的受影响 Wasm 路由。
2. 不经过 Wasm、直接返回200的健康 listener（仅加 Lua 线程观测日志）。
3. 同一候选模块、唯一配置 [a,b,c,d]/3 的正常 Wasm 路由。

先发送一个触发请求，上游确认真实到达后暂缓它的响应（最多6秒），保证请求仍在途。再通过屏障同时发8个正常路由请求；期间持续访问无 Wasm 健康 listener。所有正常请求完成、至少3次健康探测成功、且触发请求尚未结束，才放行触发响应；随后再检查3次健康路由。触发和正常请求均有有限客户端超时，异常也进入 finally 强制清理。

实际结果：6个触发请求、48个正常并发请求和40次期间/之后的健康探测全部200。每组真实并发上游到达数为9，观察 ID 无重复，总上游请求数为12（另有3个矩阵请求）。正常请求开始/结束时间全部位于触发请求在途窗口内。Lua 请求日志的实际线程号在每组唯一，受影响/正常/健康路由均被观测到，不能只凭配置宣称同 worker。

全24组总计108次上游到达，与正常矩阵、触发和正常并发请求计数严格吻合。修复版各组指标均确认无崩溃、重建或 fail-open 跳过。旧版卡住后 admin 指标获取会超时，这一限制保留在 after-stats.json，不将无法取得的指标当成0。

## 兼容性与变更范围

候选身份仍是服务名精确字符串，同名但不同 cluster 不引入新的身份系统。重复项过去可能形成未文档化的隐含抽样权重或并列随机行为，本次在 AdaptiveScore 去重会移除这些副作用；README.md、README_EN.md 和 changes/ai-load-balancer-adaptive-sampling.md 已说明。显式权重另行 Proposal。

不改变配置字段、默认值、其他调度模式、原过滤/回退规则、评分、计数生命周期、Redis 脚本、随机种子或依赖。实现 diff 见 candidate.patch。

## 独立复跑

将 verify_gateway.py、summarize.py、reproduce_checks.py、envoy-template.json、provenance.json 复制到新空目录，准备可读取两条源码提交的 Higress clone。不要覆盖原记录或带上已有 runtime 目录。

```sh
python3 reproduce_checks.py --repo /path/to/higress --go /path/to/go
python3 verify_gateway.py --all --jobs 2
python3 summarize.py
```

reproduce_checks.py 在新 archive 内构建两版，原仓库不变；基线先跑原始全量测试，再仅附加候选回归文件做目标红绿。准确工具链可传入 Go 1.24.4。若换工具链导致模块摘要不同，新副本会记录实际摘要，不覆盖本次证据。基线卡死用例必须通过有界驱动运行，不要对原始 sampler 直接执行无超时调用。

单组命令：`python3 verify_gateway.py --variant candidate --case duplicate --iteration 1`。同 label 目录存在时脚本拒绝覆盖。组参数为 unique / duplicate-safe / duplicate / identical，每种各1–3。

## 留档与清理

runtime/ 含每组的 Envoy 配置、插件配置、请求和响应、原文摘要、上游记录、完整日志、Wasm 指标、Docker 命令与退出码、容器状态及清理断言。summary.json / summarize.py 作跨组独立检查。

各组 finally 删除自己创建的唯一命名 Gateway，停止 HTTP 服务和客户端线程，检查全部动态绑定端口关闭。24组及并发阶段清理全部通过；没有遗留 adaptive-verify 容器。已有 Qdrant、buildx 或其他任务容器未动。

预跑 candidate-duplicate-0 不计入24组正式结果。formatter-validation.log 记录预跑配置校验发现此 Envoy 不支持 THREAD_ID access-log 字段；正式驱动改用 Lua 日志里的实际线程号，非生产代码改动。源代码修复后没有再改动生产文件，准确 HEAD 的模块与测试模块一致。

本目录不提交生成的 Wasm 或源码 archive；源码/依赖/模块及证据摘要均保留。SHA256SUMS 覆盖公开留档文件，不包含它自身。

公开版仅对本机绝对路径作占位替换，见 redaction.json。原始命令和日志保留在本机；占位符不作为可直接执行的命令，独立复跑请使用上述脚本参数。请求响应、时序、计数和镜像/源码/模块摘要未改。
