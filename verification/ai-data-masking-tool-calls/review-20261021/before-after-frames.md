# 真实请求的客户端输出摘录

以下只摘录 choices 和结束标志，省略 id、model、usage 等字段。完整原始正文位于 live/responses；每条请求均有同一次调用在插件前抓到的 upstream.body，可以核对，不能把原版和修复版两次独立生成当成同一请求。

## main 原版

```text
data: {"choices": [{"delta": {}, "finish_reason": null, "index": 0, "logprobs": null, "stop_reason": null, "token_ids": null}]}
```

## 修复版

```text
data: {"choices": [{"index": 0, "delta": {"tool_calls": [{"id": "chatcmpl-tool-9b762152ad97e2d9", "type": "function", "index": 0, "function": {"name": "read"}}]}, "logprobs": null, "finish_reason": null, "token_ids": null}]}
data: {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"path\": \"README.md"}}]}, "logprobs": null, "finish_reason": null, "token_ids": null}]}
data: {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"}"}}]}, "logprobs": null, "finish_reason": null, "token_ids": null}]}
data: {"choices": [{"index": 0, "delta": {}, "logprobs": null, "finish_reason": "tool_calls", "stop_reason": null, "token_ids": null}]}
data: [DONE]
```

