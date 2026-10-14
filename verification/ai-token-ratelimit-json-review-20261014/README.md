# 无响应正文的补充验证

这个目录记录 PR #5080 按审核意见补充无正文判断后的验证结果。

对照的是补充修改前后的两个提交，两版都已包含非流式 JSON 完整缓冲和用量解析修复。因此，这次正常 JSON 的预期计数在两版中相同；这里验证的是新增的无正文处理及已有行为是否受影响。

- 补充修改前：`8e41342a18e870fa6de564bb2edd468a36002baa`（报告中的 `base`）。
- 补充修改后：`741af109421800bf6c86e74204cef020616f8701`（报告中的 `fixed`）。
- 生产代码只增加 `ctx.HasResponseBody()` 判断，无正文时调用 `ctx.DontReadResponseBody()` 并返回。

使用官方 Gateway v2.2.5 镜像中的 Envoy 1.36.10、Redis 7.4.5 和固定测试上游。两版插件由 Go 1.24.4 编译。未调用真实模型服务。

七个场景、两个版本、每种组合三次，共 42 次正式请求。每次检查 HTTP 状态、客户端正文、用户计数、共享计数以及 Envoy 的回调日志。

| 场景 | 两版每次应累计 | 补充修改前设置缓冲上限 | 补充修改后设置缓冲上限 |
| --- | --- | --- | --- |
| `usage` 字段名中间分段 | 25 | 是 | 是 |
| 完整 JSON 含合法空行 | 50 | 是 | 是 |
| 正常 SSE | 25 | 否 | 否 |
| 约 2MiB JSON | 25 | 是 | 是 |
| 204，无正文 | 0 | 是 | 否 |
| 200，空 JSON 正文 | 0 | 是 | 否 |
| HEAD，带非零 Content-Length | 0 | 是 | 否 |

42 次请求的用户计数、共享计数和正文均符合预期。三个无正文场景中，日志确认响应头回调的结束标记为真，没有正文回调；修改后的版本没有设置正文缓冲上限。设置上限不代表预先分配 100MiB 内存。

这次补充处理没有改变 JSON/SSE 的解析和累计方式，也没有做性能压测。原版社区代码的分段漏计复现见同一仓库的 `verification/ai-token-ratelimit-json` 目录。

## 复跑

需要 Go 1.24.4、Python 3、Docker 和 Docker Compose。Gateway 为 Linux/amd64；其他架构需要容器架构模拟。先拉取脚本中固定的镜像：

```sh
docker pull --platform linux/amd64 higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299
docker pull --platform linux/amd64 public.ecr.aws/docker/library/redis@sha256:bb186d083732f669da90be8b0f975a37812b15e913465bb14d845db72a4e3e08
```

使用完整克隆保留两个对照提交。验证脚本在验证记录分支中，另外建立修改后源码的工作区：

```sh
git clone https://github.com/zhihao-yuan/higress.git higress-json-review
cd higress-json-review
git switch evidence/ai-token-ratelimit-json
git worktree add --detach ../higress-json-review-source 741af109421800bf6c86e74204cef020616f8701
python3 verification/ai-token-ratelimit-json-review-20261014/run.py --repo ../higress-json-review-source --go /path/to/go
```

已有仓库也可采用上述两个工作区的方式。脚本要求 `--repo` 指向的插件源码与修改后提交一致。

可用 `--output /path/to/new-directory` 指定新输出目录，已有记录不会被覆盖。脚本导出对照版本源码、编译两份 Wasm、创建专用容器并执行测试。测试结束后清理专用容器、网络及测试上游镜像，保留官方镜像和其他项目。

端口只绑定 127.0.0.1 的 18521、18522、19521，Redis 不向宿主机暴露端口、不持久化。报告与原始日志保存在输出目录。本目录的 `report.json` 为本次实际运行记录，SHA-256：

```text
905cec16e24d96810f6c3edac16c026fa75bc80dcdedaaf514abf2a0c8952023
```
