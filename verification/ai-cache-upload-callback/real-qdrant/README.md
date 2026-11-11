# 本机真实 Qdrant 验证环境

已启动 Qdrant 1.20.0，镜像固定为官方发布地址：
`ghcr.io/qdrant/qdrant/qdrant@sha256:3a80102f9b2855184d74b6d79e3351320314298c4be1f88ecaf832f147ef7a02`。

- API：http://127.0.0.1:16333
- 管理页面：http://127.0.0.1:16333/dashboard/
- 容器：`higress-pr-qdrant`
- 数据卷：`higress-pr-qdrant-data`
- Docker 网络：`higress-pr-vector-lab`
- 资源上限：1 CPU、768 MiB；测试时实际内存约 100 MiB。
- 端口仅绑定 127.0.0.1。容器保留运行，数据卷保留。
- 模型和 embedding 使用固定 HTTP 响应；向量存储、读取、检索由真实 Qdrant 执行。

## 已完成

1. 创建真实集合，写入两个二维向量，按 ID 读回并做向量检索，结果符合预期。
2. 重启 Qdrant 容器并等重启命令完成后，再次读回原记录，确认数据持久化。
3. 官方源码 `d388d06a92dd125bbe99330888690fd6deeb352f` 编译的原 ai-cache Wasm 接入真实 Qdrant。首次查询未命中，模型固定答案写入真实库；后两次请求命中库内答案，模型测试上游只收到一次请求。
4. 增加 Lua 响应等待，在上传回调日志出现后才放行等待。三个全新 Gateway 实例均为 `200 → 503 → 503`，每轮 ai-cache Wasm crash_total 为 1，回溯为 Qdrant 上传完成回调；每轮写入的真实记录均已独立读取和检索确认。
5. 临时 Gateway 容器、测试桩和相应端口已清理；Qdrant 服务按本机验证环境保留。

## 文件

- compose.yaml：可重复启动的本地数据库配置。
- smoke.py、smoke-results.json：建库、写入、读取和检索。
- persistence-results.json：重启后的持久化验证。
- verify_gateway_real.py：真实 Qdrant + 未修改官方插件的网关复现。
- gateway-direct/：正常对照、命中缓存、真实数据和网关日志。
- gateway-held-1/、gateway-held-2/、gateway-held-3/：三轮异常复现、数据库记录、Wasm 指标和清理证明。
- status.json：本轮结果及组件真假边界。

## 启停与复跑

启动：

```sh
docker compose -f <evidence>/real-qdrant/compose.yaml up -d
```

停止并保留数据：

```sh
docker stop higress-pr-qdrant
```

再次启动：`docker start higress-pr-qdrant`。

重复基础检索验证：`python3 smoke.py`。网关脚本需要上一级的固定 baseline.wasm 和 envoy-template.json：
`python3 verify_gateway_real.py --label=run-direct`；
`python3 verify_gateway_real.py --hold-response --label=run-held`。
每次创建独立集合并保留数据证据；异常和正常退出都清理本次临时网关及 HTTP 测试桩。

当前只完成基线缺陷发现，生产代码尚未修改，Issue/PR 尚未提交。
