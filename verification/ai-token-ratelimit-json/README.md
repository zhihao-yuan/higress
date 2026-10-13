这个最小验证只使用固定测试上游、实际 Envoy 和实际 Redis，不调用模型服务。用于复现非流式 JSON 分段漏记、合法空行少记，并检查 SSE 与约 2MiB JSON 的对照结果。它不是性能基准，不用于推断自然请求的失败率。

需要 Go 1.24.4、Python 3、Docker 和 Docker Compose。Gateway 固定为 linux/amd64，因此 ARM 机器需要容器架构模拟支持。先拉取以下镜像：

```sh
docker pull --platform linux/amd64 higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299
docker pull --platform linux/amd64 public.ecr.aws/docker/library/redis@sha256:bb186d083732f669da90be8b0f975a37812b15e913465bb14d845db72a4e3e08
```

在包含固定修复提交 8f7276835290c926428733637db1cb856c97f673 及基线 c74d7e2ddf69c38687f61dfbc2d560a9ae838b26 的 Higress checkout 中执行（不要使用缺少历史提交的 shallow clone）：

```sh
python3 verification/ai-token-ratelimit-json/run.py --repo .
```

可用 `--go /path/to/go` 指定 Go 1.24.4，用 `--output /path/to/new-directory` 指定新输出目录。已有输出不会被覆盖。脚本从固定基线导出插件源码，构建两份 Wasm，启动专用 Compose 项目，并对两版分别执行四种场景、各三次。

| 场景 | 基线累计 | 修复累计 | 应累计 |
| --- | --- | --- | --- |
| usage 字段名中间分段 | 0 | 25 | 25 |
| 完整 JSON 中含合法空行 | 20 | 50 | 50 |
| 普通 SSE | 25 | 25 | 25 |
| 约 2MiB JSON | 本次为 0，随实际分段变化 | 25 | 25 |

本次 24 次正式请求中，原版分段/空行两类已知缺陷得到复现，修复版 12 次请求全部正确。约 2MiB 基线用例记录实际计数，不假设原版一定正确或一定漏记；修复版必须累计 25。每个请求同时检查用户 key、共享 key 增量及客户端正文 SHA-256。分段案例保留实际 Envoy `proxy_on_response_body` trace；脚本会检查基线确实出现多次正长度回调，不能只凭上游两次 write 认定分段。缓冲后的 host 回调可能暴露累计正文长度，不能简单相加。

报告为新输出目录的 `report.json`，原始 Envoy 日志也保存在该目录。本次归档的 `report.json` 是真实运行结果，所有正文来自该目录的固定 fixture 源码。未包含真实模型原始正文、账号凭据或内网地址。

只绑定 127.0.0.1 的 18511、18512、19511 端口，Redis 不对宿主机暴露端口且不持久化。脚本拒绝占用中的端口或已有专用 Compose 项目；结束时清理该项目及本地 fixture 镜像，保留官方镜像和其他项目。
