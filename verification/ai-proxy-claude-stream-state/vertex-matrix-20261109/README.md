# Claude / Vertex 流状态对照

本轮只给已有修复补测试，生产代码与 `94f2b327` 相同。新增用例从 Vertex 请求转换入口识别 Claude，再调用 Vertex 的公开流式响应入口，没有手工设置 Claude 路由标记。

- 基线：`bfcd87d1a22fedae9efaa1d901caadd1a9ffcf6d`
- 候选：`7dc1162c4629d437bc518a3e24b42c33250d50d3`
- 工具链：Go 1.27.3，macOS amd64；Gateway v2.2.5 镜像摘要见 provenance.json。
- 上游是本地固定 SSE 测试桩，没有连接真实模型或 Google Vertex。

## 网关结果

两条入口各执行：基线 1 次单请求 + 3 组双流；候选同样执行，共 28 次 HTTP 请求。4 次单流对照均正确；基线 6 组双流均分别命中两种目标错误；候选 12 条并发流均正确。

| 入口 | 版本 | A 输入/输出/总量 | B 输入/输出/总量 | 双流结果 |
| --- | --- | --- | --- | --- |
| Claude | 基线 | 45/256/301 | 45/766/811 | 3 组均复现错误 |
| Claude | 候选 | 955/256/1211 | 45/510/555 | 3 组均正确 |
| Vertex→Claude | 基线 | 45/256/301 | 45/766/811 | 3 组均复现错误 |
| Vertex→Claude | 候选 | 955/256/1211 | 45/510/555 | 3 组均正确 |

所有响应均为 HTTP 200。逐块保存 ID 和 service tier 的期望检查，逐项检查最终 prompt/completion/total；同时检查正文、工具 ID/名称/arguments 和 finish_reason。基线断言明确要求 A 被 B 覆盖、B 多算 A 的输出，不能用任意一次失败代替复现。

脚本通过客户端握手固定 A start → B start → A delta/stop → B delta/stop；不以 sleep 控制交错。每组 timeline.json 同时记录上游发送和下游接收，timing-results.json 保存顺序断言。

Vertex 的上游请求还检查 `publishers/anthropic/models/claude-fixture:streamRawPredict`、`anthropic_version` 和 model 字段移除，确认实际经过 Vertex→Claude 转换。

## 文件

- gateway-results.json：28 条逐请求断言。
- comparison.json、summary.json：汇总。
- gateway/：生效 Envoy 配置、上游/客户端请求与 SSE、响应头、时序、网关日志和 Wasm 指标。
- provenance.json：源码版本、工具链、镜像与两版 Wasm SHA-256。
- checks.json 及 *.log：Go、Wasm、vet 的命令、退出码、日志。基线回归叠加同一份候选测试，生产源码保持基线；该回归预期失败。
- gateway-cleanup.json：4 个容器已移除，8 个网关端口和测试桩端口关闭，服务线程已结束。
- SHA256SUMS：当前证据文件的 SHA-256；不上传 Wasm 二进制。
- 本轮 vet 两版均未通过，84 行诊断完全相同；不计为 vet 通过。

## 本轮检查

- 新增回归：基线因目标字段错误失败，候选通过。
- provider/config：通过。
- Claude、Vertex 的 Go/Wasm 用例：通过，295.594 秒。
- 全量 `go test -mod=readonly ./... -timeout=30m -count=1 -v`：通过，835.457 秒。
- `go vet -mod=readonly ./...`：两版均退出 1，84 行已有诊断完全相同。
- 日志和命令中的本机绝对路径已替换为占位符；原始日志摘要见 redaction.json。

## 复跑

在单独目录保存本证据目录，安装 Python 3.12+、Go 1.27.3 和 Docker，并让本地 Higress 仓库包含上述两个提交：

```sh
GO=/path/to/go python3 reproduce.py /path/to/higress
```

脚本从固定提交导出代码，构建两版 Wasm，然后执行 28 次网关请求。构建禁用 VCS 信息，使用 `GOTOOLCHAIN=local GOWORK=off GOOS=wasip1 GOARCH=wasm go build -mod=readonly -buildvcs=false -buildmode=c-shared`。构建目录不同可能影响 Wasm 字节和 hash，复跑的实际 hash 另存到 rerun-build-results.json。provenance.json 记录本次实际测试的模块 hash。

测试完成或异常退出均会移除本轮容器、关闭测试桩，并检查端口。只清理脚本自己创建的容器，不操作现有环境。Docker 必须可用，镜像固定为 provenance.json 的摘要。
