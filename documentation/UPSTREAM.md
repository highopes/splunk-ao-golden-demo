# 上游来源与修改边界

当前操作以根 [README](../README.md) 为准。来源：[rungalileo/galileo-golden-demo](https://github.com/rungalileo/galileo-golden-demo)。同步于 2026-10-06，基线 upstream/main 的 commit 为 2f05a6f5448fd103e06982e5b6e832c59650c0a0。

导入上游已跟踪文件，保留原项目 .agent-context 与 .gitignore。原项目没有提交历史；没有推送或改写历史。upstream remote 用于比较，未代用户创建 origin。原 README 存档在 [UPSTREAM_README.md](UPSTREAM_README.md)，仅供参考。上游无 LICENSE，本项目未自行添加授权声明。

保留四个 Domain、Streamlit、Single Agent + Tools + RAG、LangGraph、GalileoCallback / GalileoLogger 与 Agent Control SDK。

| 范围 | 必要修改 |
|---|---|
| 环境 | Python 3.12 实测依赖锁；默认移除未使用的金融/Chroma/PDF 重依赖；PDF 解析保留可选安装 |
| macOS | 项目专属 PostgreSQL 集群、启动、只读预检；`db.py check` 连接测试，`start-demo.sh` 启动前检查数据库，原生集群未运行时自动 `db.py start`，失败则不启动 App；保留可选 Docker 配置 |
| secrets | 固定仓库路径读取；Console 根地址自动推导 API、Control、租户登录；可选覆盖；行业 stream 来自 YAML；placeholder 不视为有效 provider |
| UI / 行业 | Healthcare 默认主线；四行业分别使用 stream；轻量标题、状态、Session reset；Reset 显式将 Chaos widget 状态设为 false，避免浏览器重新带回旧勾选；修复上游侧边栏把默认行业列两次、emoji 图标重复显示的问题（默认行业的 `/<domain>` 页隐藏但可直接访问，侧边栏标题去掉与 `icon` 重复的 emoji）；Healthcare 标题保持上游的 `Online Healthcare Assistant` |
| 模型 / RAG | 所选模型用于主 LLM、SQL 与 RAG；独立 async HTTP 客户端避免跨循环连接池；显式传递 RunnableConfig 采集检索 context |
| Logger | Tool 绑定当前会话/Experiment logger；RAG 答案摘要是 Tool；修复 ns 单位；错误结束 Trace |
| SQL | Control 看到实际 SQL；单条 SELECT 检查与 READ ONLY transaction 兜底；正确编码密码并回收连接 |
| Control | 注册回读后才显示 connected；每轮刷新策略；框架 callback manager 保留本地，仅发送业务参数 |
| loader | 普通新行业自动加载 qa.csv / relational CSV；部分 provider 失败返回非零 |
| Chaos | 503 固定复现、Sloppiness 必改数字、RAG Disconnect 覆盖主检索；明确 Data Corruption 非确定性 |
| Hallucination | 明确 synthetic fixture / no model invocation；移除假 token、latency、cost；真实平台评分 |
| Experiment | 校验 CSV；仅在确切冲突复用 Dataset；SDK 管理 sample Trace，Agent 不提前关闭；使用当前租户可用的原生 GalileoMetrics 标签；结果链接采用服务返回的 group/run ID |
| 文档 / 测试 | README 单一事实来源；区分真实云端、数据库/框架与模型夹具；未来能力只列 Planned |
| Backend profile（2026-11-21） | `setup_env.py` 的 `BACKEND_PROFILES` 表：`splunkse` 与 `imlab-onprem`（Splunk AO On-prem：无租户路径、REST 与 Agent Control 直连 API、头名 `Splunk-AO-API-Key`、Luna 指标优先）；显式 `galileo_api_url` / `galileo_ingest_url` / `agent_control_url` 覆盖；`check_demo.py --in-cluster` 预检 |
| Trace 写入（2026-11-21） | `helpers/galileo_ingest.py`：配置 `galileo_ingest_url` 时，SDK 的原生 JSON ingest 门（探测与 `/ingest/*` 写入）改走 ingest-service，其他调用仍走 API。**依赖 SDK 2.6.0 内部实现**，升级 SDK 时由 `tests/test_onprem_k8s.py` 复核 |
| Control 输入（2026-11-21） | LLM 步骤的 `@control` 输入改为最新一条用户消息（`latest_user_text`），完整消息列表另传给模型；避免系统提示词被 Prompt Injection scorer 误判 |
| vLLM provider（2026-11-21） | 新增 provider `vllm`（OpenAI 兼容）与 `helpers/hermes_chat.py`（把正文中的 Hermes `<tool_call>` 解析为结构化 `tool_calls`）；embedding 仍用 OpenAI |
| 评估指标（2026-11-21） | Experiment 默认指标按 profile 选择；Domain YAML 的 `experiments.metrics` 可按 profile 覆盖；导出器按 profile 优先 Luna 指标 |
| 容器 / K8s（2026-11-21） | `Dockerfile`、`.dockerignore`、Helm chart `deploy/helm/splunk-ao-golden-demo`（含 auth-url 认证服务）、`deploy/k8s/{build,scripts}`；`DEMO_DATA_DIR` 让可写输出（CSV、A/B 清单）落到容器卷；`scripts/setup_demo_controls.py` 用代码建立三条 Demo Control；`scripts/check-public-hygiene.sh` 公开仓库卫生检查 |

未来升级先比较基线与新 upstream/main，再逐项应用本地修改。不要覆盖用户 secrets、本地数据库、.runtime 或 .agent-context。
