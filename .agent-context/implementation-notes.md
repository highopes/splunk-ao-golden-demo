# 实施与验收上下文

2026-10-06。任务依据同目录 splunk-ao-golden-demo-task-v2.md；操作以根 README 为准，实际结果与 Trace UUID 以 documentation/VALIDATION.md 为准。

上游 main 已导入，SHA 2f05a6f5448fd103e06982e5b6e832c59650c0a0。原目录无提交历史；未提交、未推送。保留四行业与原框架，差异见 documentation/UPSTREAM.md。

.venv、独立 PostgreSQL/pgvector、Streamlit 已运行；14 项 runtime 与 10 项真实数据库/框架夹具测试通过。用户已填写 Galileo / OpenAI Key；真实 Healthcare / Bank embedding 已加载。Healthcare UI 正常双轮同 Session、Hallucination 原生失败评分、三个云端 Control、503 / Sloppiness / Data Corruption / Disconnect 的云端证据已通过。

用户最新要求：secrets 简化为 Console 根地址 + Galileo Key + Control name/header + OpenAI + PG；可选 API/Control 地址自动推导，各 Domain Project/stream 来自 YAML。已改模板、setup/preflight、README 与回归；不编辑用户真实文件，用户将自行注释冗余变量。不要输出 secrets，即使字段名看似非敏感。

实际联调修复：Control proxy 不带 /splunkse；SDK init 吞健康失败后要注册回读；RunnableConfig 中 callback manager 仅保留本地；OpenAI async 连接池不跨 asyncio.run；每轮刷新云端策略；Data Corruption 仅在 Tool 结果后注入；Experiment 使用当前 SDK GalileoMetrics，租户不支持 Chunk Attribution Utilization，默认只保留其余三个已回读原生指标。

用户已本人登录 Console。Healthcare UI 15 样本 Experiment、Bank RAG/Tool/独立 Trace/UI 9 样本 Experiment、Console 原生评分/控制/核心 Chaos 均已通过。标准路径首次连续 GUI 排练约 12 分钟操作 + 3 分钟话术；Reset 后重复真实查询、GUI 切换 PII / Injection、Hallucination、DELETE、503。

Reset 复测发现仅 clear Session 会让 Streamlit 回填旧 Chaos checkbox 值，已改为清空后显式设五类 widget 为 false。真实 UI 验证已开启的 Tool Instability → Reset → 正常 P001；五个开关同时开启 → Reset → 全关闭，RAG / P001 同一新 Session 正常。旧失败 Trace 保留；修复后 24 项回归再次通过。最新复测 UI run healthcare-experiment-df50c0 已完成 15 样本、零运行错误，原生指标全部完成，Console 15 Traces / 390 Spans / 1 Session；README / VALIDATION 已同步为限定环境 Demo-ready。

三个本 Demo Controls 当前 SQL Enabled、PII / Injection Disabled；只关联 Healthcare 自有 stream。不要改其他项目/共享原规则。失败 Trace/run 保留，不删除或冒充成功。Bank Guardrails、Insurance/Restaurant、Docker/Ollama/Bedrock 未验收。Data Corruption 两次真实输出错误已验证，但仍受模型遵循影响，保持 Optional。

Demo-ready 仅限已验证的 macOS / Healthcare / OpenAI / splunkse 路径。Kubernetes、Qwen Judge、cisco-demo 只预留文档，不扩大当前架构/UI。真实 secrets/.venv/数据库/Trace readback 留在忽略目录；公开文件已按真实 credential 字节扫描，无 Key / 密码。Console 截图因含账号信息不作为公开交付；只保留 synthetic 应用截图。

2026-10-27：Healthcare 异常的根因是重启后项目 PG 未启动（10-26 20:59 正常关闭，残留 postmaster.pid），而 start-demo.sh 不检查数据库，5 个 Domain 都受影响。新增 `db.py check`（只测连接，不输出密码，Docker 也能用）；start-demo.sh 不通时，若 `.runtime/postgres` 已初始化就自动执行 `db.py start` 并复检，失败则不启动 App；未初始化时不自动 initdb，只给出指引。check_demo 按 OperationalError / ProgrammingError 分别提示。Insurance / Restaurant 表与 Hosted 索引此前从未加载，本次已加载，只做了单问 UI 冒烟，仍未验收。49 项测试通过；README 3.2/3.4/3.6/4.4/5.8/6.5/7、VALIDATION（#db-autostart）、UPSTREAM 已同步。未提交。
