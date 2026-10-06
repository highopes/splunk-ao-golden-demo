# Chaos 实现说明

演示操作、话术与恢复以根 [README](../README.md) 为准；实际证据见 [验收记录](VALIDATION.md)。

| 开关 | 实际行为 | 验证限制 |
|---|---|---|
| Tool Instability | Tool 前返回 synthetic 503，后端不执行 | 演示注入，不冒充实际服务宕机 |
| Sloppiness | Tool 正确结果记录后，改变数字再交给主 LLM | 对比 Tool output 与 LLM input；不改数据库 |
| Data Corruption | 拿到 Tool 结果后，主 LLM system prompt 才要求故意错误呈现正确结果 | 真实 gpt-4o 连续两次 10mg input → 99mg output；其他模型可能拒绝/忽略 |
| RAG Disconnects | 主检索与备用 retrieval 返回空 docs / rag_failure | 不实际关闭 PostgreSQL |
| Rate Limits | Tool 前返回 synthetic 429 | 不冒充真实模型服务配额 |

每次只启用一项，用同一个问题比较正常/故障两条 Trace。JSON error 不一定自动成为平台 FAIL；检查实际 span 与 scorer。主线只用预验收的一个模式，三个核心模式用于根因对比。

Chaos counters 是应用计数，不是平台评分。关闭全部开关、reset counters、Reset Demo Session；远程 Control 状态在 Console 独立恢复。
