# ai-cache 上传完成回调：修复前后验证

- Proposal: https://github.com/higress-group/higress/issues/5340
- Design / Verification Plan: https://github.com/higress-group/higress/issues/5341
- 维护者批准: https://github.com/higress-group/higress/issues/5340#issuecomment-6792678223
- 实现 TASK: https://github.com/higress-group/higress/issues/5341#issuecomment-6792477667
- 验证 TASK: https://github.com/higress-group/higress/issues/5341#issuecomment-6792479043

## 结果

上传方法收到 nil 完成回调；当 HTTP 回执在原请求结束前执行时，provider 直接调用该函数会导致 Wasm panic。修复在公共调用方为两种上传接口提供有效回调，异步 err 只记警告，保留同步返回错误时的回退和原有跳过条件。

| 版本 / 模式 | 重复组数 | 每组三次请求 | 每组 crash_total | 每组模型测试上游调用数 |
|---|---:|---|---:|---:|
| 基线 / 正常转发 | 3 | 200 / 200 / 200 | 0 | 1 |
| 基线 / 等待上传回调 | 3 | 200 / 503 / 503 | 1 | 1 |
| 修复 / 正常转发 | 3 | 200 / 200 / 200 | 0 | 1 |
| 修复 / 等待上传回调 | 3 | 200 / 200 / 200 | 0 | 1 |

共36次客户端请求，每组使用新 Gateway 和新建空集合。每组都独立读回、搜索了真实 Qdrant 中的记录，核对 question、answer、consumer 和二维向量。首个模型响应保持原始字节，成功的后续请求核对缓存模板和答案。未发生 fail-open 跳过、worker 未初始化或 VM rebuild。

正常转发的基线没有崩溃，因此不主张每次写回都必现。Lua 的等待只用于确定完成回调先于原响应结束；观察实际上传 http-call end 后再放行，没有用固定 sleep 制造结论。单 worker、fail_open=false。

**Qdrant 是真实服务，模型和 embedding 为固定 HTTP 响应。** 七种 provider 的轻量回归运行真实 provider 代码与 SDK 测试宿主，其余六种后端没有部署真实服务。

## 源码与二进制

基线 `f0260049bd352bb273a52aef314f283ad254537a`，修复 `2510ff24276ac4160cbc22261ff302edb7b81a02`。开工时拉取 upstream/main；ai-cache 模块相对发现版本 d388d06a 没有变化。仅生产 core.go 与 core_upload_test.go 有改动，见 candidate.patch。

- 基线 Wasm SHA-256: `b09afedd944e81d4b66e9f47fa67ccc1f384b0d83f1df0deb03fc41ba32601fe`
- 修复 Wasm SHA-256: `05e8137d9319d3ab07cfe613efb1881b56abc4dd461ddf7bac2b86e693abdf82`
- Gateway: `higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299`
- Qdrant 1.20.0: `ghcr.io/qdrant/qdrant/qdrant@sha256:3a80102f9b2855184d74b6d79e3351320314298c4be1f88ecaf832f147ef7a02`
- macOS 15.6.1 x86_64；Go 1.27.3；Docker Desktop Linux VM。Gateway 每组限1 CPU / 768MiB；Qdrant 1 CPU / 768MiB。

二进制不提交；provenance.json、environment.json、每组 identity.json 记录实际运行版本。基线另用 Go overlay 在修复分支还原原 core.go 重建，结果与实际基线模块逐字节相同；修复提交后的重建也逐字节相同。buildvcs=false，编译路径仍可能影响不同机器重建出的模块摘要。

## Go / Wasm 回归

新增 TestUploadEmbeddingAndAnswer 系列覆盖七种 provider、两种上传接口、异步错误、同步错误回退、两种同步错误及四个跳过条件。DashVector 和 Qdrant 完整请求链同时运行 Go 与 Wasm 宿主。

baseline-regression.log：新增目标用例因 nil 回调失败（退出码1），原有同步错误与跳过控制用例通过。candidate-full-test.log：模块全量测试通过（退出码0）；candidate-vet.log：vet 通过（退出码0）。check-commands.json 记录命令、环境和退出码。

第二种上传接口通过测试 HttpContext 在第一次 answer upload 的 consumer 查找注入一次同步错误来进入原有 fallback；之后真实 DashVector embedding 上传完成。另用非法 URL 转义覆盖两次同步返回错误。这些是同步 provider/请求构造错误注入，不声称覆盖 SDK 派发失败，也不代表正常认证流程。

## 独立复跑

使用支持上述源码的 Go，安装 Python3 与 Docker。先将 reproduce_checks.py、reproduce_runtime.py、verify_gateway.py、summarize.py、envoy-template.json 和 provenance.json 复制到新的空工作目录，本机准备独立的 Higress fork clone，确保能读取两条源码提交。不要复制已有 runtime 目录或覆盖已保存证据。

```sh
# 新工作目录下；--repo 为本机 Higress clone，--go 可传 Go 的绝对路径。
python3 reproduce_checks.py --repo /path/to/higress --go /path/to/go
# 基线预期退出1，脚本会确认目标 nil panic；候选和 vet 预期0。

# Qdrant compose 位于上一级发现记录的 real-qdrant/compose.yaml。
docker compose -f ../real-qdrant/compose.yaml up -d
python3 reproduce_runtime.py
python3 summarize.py
```

reproduce_checks.py 以 git archive 读取指定源码，不修改传入仓库，基线只附加候选回归测试。它重新生成 baseline.wasm / candidate.wasm。若新机器生成的二进制摘要不同，复跑前更新本副本 provenance.json 的 artifacts 为实际两个文件 SHA-256，再运行 summarize.py；保留原始记录不动。

verify_gateway.py 的单组命令示例：

```sh
python3 verify_gateway.py --variant=baseline --hold-response --label=baseline-held-1
python3 verify_gateway.py --variant=candidate --hold-response --label=candidate-held-1
```

runtime/* 保存各组配置、请求、响应、正文摘要、调用计数、数据库读回、日志、Wasm 指标、回调观察和清理证明。summary.json 与 summarize.py 为跨组断言，runtime-commands.json 保留实际退出码。

## 清理

每组退出时删除自己创建的 Gateway、HTTP 服务和唯一命名集合，检查测试端口关闭、线程结束和集合不再存在。保留原有 Qdrant 服务、命名卷与五个已有集合；不删除其他容器。cleanup.json 逐组记录结果。

如明确不再需要本机验证服务，可运行 `docker compose -f ../real-qdrant/compose.yaml stop`，这不会删除数据卷。重跑脚本的源文件临时目录保留在新工作目录内，可在导出证据后删除该新工作目录。

SHA256SUMS 覆盖此目录的文本证据；路径脱敏规则见 redaction.json。此前发现记录仍保留在上一级目录，其旧版四组结果不计入本轮36次。
