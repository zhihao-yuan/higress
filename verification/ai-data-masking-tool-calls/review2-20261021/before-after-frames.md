# 本轮真实模型工具流摘录

本轮 dsv4 测试服务请求，模型响应没有重放或人为分段。下方省略顶层信息、role、usage 和附加元数据；完整正文及同次请求的上游 Tap 在 `live/responses/`。

## main 原版客户端

```text
data: {"choices":[{"index":0,"delta":{},"finish_reason":null}]}
```

## 最终版客户端

```text
data: {"choices":[{"index":0,"delta":{"tool_calls":[{"id":"chatcmpl-tool-b0a057671d58c001","type":"function","index":0,"function":{"name":"read"}}]},"finish_reason":null}]}
data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"path\": \"README.md"}}]},"finish_reason":null}]}
data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"}"}}]},"finish_reason":null}]}
data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}
data: [DONE]
```

最终版两次流式工具请求的完整正文都与各自上游逐字节一致。工具只是协议声明，没有执行。
