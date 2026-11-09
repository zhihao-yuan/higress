# ai-proxy Claude 流状态隔离：网关验证记录

这是固定 SSE 测试上游，不是真实模型。测试在官方 Gateway v2.2.5、单 worker、相同配置下，只替换修复前后的 Wasm。

| 场景 | 预期输入/输出 Token | 实际输入/输出 Token | ID / service tier |
| --- | --- | --- | --- |
| 基线单请求 A | 10/3 | 10/3 | 正常 |
| 基线并发 A | 10/3 | 200/3 | 混入 B |
| 基线并发 B | 200/5 | 200/8 | 正常 |
| 修复单请求 A | 10/3 | 10/3 | 正常 |
| 修复并发 A | 10/3 | 10/3 | 正常 |
| 修复并发 B | 200/5 | 200/5 | 正常 |

两版的文本和工具调用参数均保留。Wasm crash、fail-open skip、uninitialized、rebuild 指标均为 0，详见 gateway/*/wasm-stats.txt。最终有效对照 6 次 HTTP 200。测试桩开发阶段有两次 chunked 请求读取失败导致的 503，修正桩后重跑，不计入本表。

交错由客户端观察到的首块协调：先收到 A 首块，再启动 B；收到 B 首块后才让 A 继续；A 完成后再让 B 继续。不靠 sleep 猜测顺序。

## 复跑

需要 Docker、Go 1.27.3、Python 3.12+。克隆贡献者 fork 并获取代码分支，确保 provenance.json 中两个提交在本地，再执行：

```sh
git clone https://github.com/zhihao-yuan/higress.git higress-repro
git -C higress-repro fetch origin fix/ai-proxy-claude-stream-state
python3 reproduce.py ./higress-repro
```

脚本从固定提交导出源码，在临时目录构建，不修改提供的源码仓库。运行会覆盖本目录同名结果；保留原记录时请先复制整个验证目录。脚本会启动并清理两个本地测试容器及一个 HTTP 桩；Docker 端口只发布到本机回环地址。第一次运行需要拉取指定的官方镜像。

固定源码、工具链、镜像和原运行 Wasm SHA-256 见 provenance.json；新构建哈希记录于 rerun-build-results.json，编译器/路径差异可能影响二进制哈希。原运行的请求、响应及生效配置见 gateway/；结果断言见 gateway-results.json。

## 其他检查与限制

- 基线新增回归测试失败，修复后通过，见 baseline-unit.log / fixed-regression.log。
- provider/config 测试、模块 Go 模式选择、现有 Claude Go/Wasm 用例通过，分别见同名日志。
- 完整 `go test ./...` 在默认 10 分钟超时，停在 Kling Wasm 模块编译，不记为全量通过。module-tests-timeout.log 保留超时部分。
- `go vet ./...` 的 84 行诊断与未修改 main 完全相同，涉及已有未导出字段的 JSON 标签，见 baseline-vet.log / vet.log。不记为 vet 通过。
- 文本日志中的本机路径已替换，原始输出留在本地。本目录不含私有模型地址、凭据或业务数据，apiTokens 为测试占位值。
- 本次未用真实模型重测修复版，也没有完整吞吐/分配基准；不能据此声称覆盖所有模型或不存在性能变化。


## Vertex 补充验证（2026-11-09）

两条入口的 28 次网关对照、新增 Vertex 交错回归及全量检查见 [本轮记录](./vertex-matrix-20261109/README.md)。候选为 `7dc1162c`，原记录保留。
