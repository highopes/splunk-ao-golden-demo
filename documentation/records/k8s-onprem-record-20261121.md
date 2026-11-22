# 工程记录：Golden Demo 部署到 Kubernetes、后端改为 Splunk AO On-prem（2026-11-21 起）

> 本文件是本次升级改造的**逐条执行记录**（审计用，已脱敏）。想按步骤安装或日常运维：看 [KUBERNETES.md](../KUBERNETES.md) 与 [README.md](../../README.md)。
>
> 脱敏约定（本仓库为 Public）：
>
> | 占位符 | 含义 |
> | --- | --- |
> | `<AO_DOMAIN>` | AO On-prem 的公网域名后缀（`console.<AO_DOMAIN>`、`api.<AO_DOMAIN>`） |
> | `<APP_HOST>` | 本应用的公网主机名（`golden.<AO_DOMAIN>`） |
> | `<OPS_NODE>` | 执行 kubectl/helm 的集群运维节点（本应用工作副本 `/root/<WORKDIR>`） |
> | `<BUILD_HOST>` | 镜像构建主机（工作副本 `/root/<BUILD_WORKDIR>`） |
> | `<NODE_IP>` | 集群节点 IP |
> | `<PG_NODE>` | PostgreSQL 固定调度的节点 |
> | `<BASIC_AUTH_USER>` | Basic Auth 账号名 |
>
> 原始日志在各主机工作副本的 `.work/logs/`（不进 Git），本文只写路径与摘要。

## 当前状态

| 项 | 状态 |
| --- | --- |
| 阶段 | 0–3、5、6、8、9 全部完成（第 4、7 阶段按决策取消） |
| 本仓库 HEAD（GitHub / Mac / `<OPS_NODE>` / `<BUILD_HOST>`） | 见本节之后的最后一次提交（四处一致） |
| 镜像 | 运行中 `highope/sao-golden:1.0.0-e93c4d6`（`sha256:4a7076fc…12b2`）；此前 `1.0.0-03a0a1f`（`sha256:3536d717…e19f`）。均为 Public |
| 命名空间 `sao-golden` | Helm release `sao-golden` rev4；app / auth / postgres 均就绪；`40-verify.sh` ALL PASS；外网经 Basic Auth 可用 |
| Demo Control | SQL 启用；PII、Prompt Injection 停用（标准状态） |
| 未决事项 | 无（阶段 6 的 15 样本 Experiment 已在集群内完成） |

## 执行记录

### 2026-11-21 阶段 0：准备工作目录与核对（执行者：Mac 上的 GitHub Copilot，经 JumpServer Web 终端；20:42 开始，20:50 完成）

1. **Mac**：本仓库 `90602f3` 与 `origin/main` 一致，工作区干净（`.git/info/exclude` 已含 `.streamlit/secrets.toml.*`）。AO 平台仓库与 GitHub 一致。
2. **Mac 配置核对**（只输出键名与“空/非空”，不显示值）：`secrets.toml.imlab-onprem`（16 个键）与 `secrets.toml.imlab-onprem-k8s`（21 个键 + `[k8s]` 表 8 个键）全部非空；`galileo_api_key`、`[k8s].basic_auth_password` 已由用户填写。
3. **`<OPS_NODE>`**：AO 平台仓库工作副本与 GitHub 一致（无需快进）。
4. **`<OPS_NODE>` 本应用工作副本**：用户已放入 `.streamlit/secrets.toml`（及各后端版本）并执行过空的 `git init`，因此原地初始化：
   ```bash
   cd /root/<WORKDIR>
   git remote add origin git@github.com:highopes/splunk-ao-golden-demo.git
   printf '.streamlit/secrets.toml.*\n.work/\n' >> .git/info/exclude
   git fetch -q origin && git checkout -q -B main origin/main && git branch -q -u origin/main
   chmod 700 . .streamlit && chmod 600 .streamlit/secrets.toml*
   mkdir -p .work/logs && chmod 700 .work .work/logs
   ```
   结果：`main` 跟踪 `origin/main`，HEAD `90602f3`，`git status --short` 为空。`secrets.toml` 键齐全、值非空；其 SHA256 与 Mac 上 `secrets.toml.imlab-onprem-k8s` 一致。
5. **`<BUILD_HOST>`**：`apt-get install -y tmux`（tmux 3.4，A1）；`git clone` 到 `/root/<BUILD_WORKDIR>`（HEAD `90602f3`）；`.git/info/exclude` 加 `.work/`、`.streamlit/secrets.toml.*`；建 `.work/logs`（700）。Docker Hub 已登录（`/root/.docker/config.json` 只核对键 `https://index.docker.io/v1/`，权限 600）；`docker buildx ls` 默认 builder 运行中（BuildKit v0.29.0，含 linux/amd64）。根盘剩余 223G。
6. **Mac 防休眠**：`caffeinate -dimsu`（异步，全部结束后停止）。
7. **结果**：✅ 四处 HEAD 一致、工作区干净；H1～H3 核对通过，无缺项。

### 2026-11-21 阶段 1：代码适配（执行者：Mac 上的 GitHub Copilot；20:55 开始，21:25 完成）

**改动清单**（提交点 C1）。按原因归类（哪些是换后端或进集群所必需、哪些是新增能力，插桩是否变化）见 [README 6.6 改动总览](../../README.md#onprem-code-changes)。

| 范围 | 文件 | 要点 |
| --- | --- | --- |
| 忽略规则 | `.gitignore` | 第一个改动：`.streamlit/secrets.toml.*`（保留 `!.streamlit/secrets.toml.example`）、`.work/` |
| Backend profile | `setup_env.py` | `BACKEND_PROFILES` 注册表：`splunkse`（行为不变：Console 代理 `/api/agent-control`、`Galileo-API-Key`、`/splunkse` 入口）与 `imlab-onprem`（API 由 `console.`→`api.` 推导、Agent Control = `<api>/agent-control`、头名默认 `Splunk-AO-API-Key` 也允许 `Galileo-API-Key`、Console 无租户路径、REST 直连 API）；`resolve_backend_settings()` 单一解析入口；显式 `galileo_api_url` / `galileo_ingest_url` / `agent_control_url` 优先；配置错误信息不含任何值（`BackendConfigError`） |
| Ingest 地址 | `helpers/galileo_ingest.py` | `configure_ingest_url()`：SDK 的 `/ingest/healthz` 探测与 `ingest_traces` / `ingest_spans` 写入改用 `galileo_ingest_url`；trace/span 更新与 session 调用仍走 API（与官方 Observe Request Flow 一致：只有 `/ingest` 与 `/otel/v1/traces` 到 ingest-service）。未配置时不打补丁、行为不变 |
| REST helper | `helpers/galileo_api_helpers.py` | `GALILEO_REST_BASE_URL`：splunkse 仍走 `<console>/api/galileo`；imlab-onprem 直连 `<api>/public/v2/...`、`<api>/v2/...`；集群内代码不访问 Console 地址（Console 只用于浏览器链接） |
| Agent Control | `helpers/agent_control_helpers.py` | 头名缺省值取自 profile |
| UI | `app.py` | 按钮 “Open Splunk AO Console”；侧栏与未配置页显示 `Backend: <profile>`；vLLM provider 选项；实验指标按 profile / Domain YAML |
| 预检 | `scripts/check_demo.py` | 按 profile 校验；`--in-cluster`（本 Pod `/_stcore/health`、CA bundle 环境变量、内部地址 TLS 校验、SDK 是否走原生 ingest 门、Agent Control 注册回读） |
| Luna 指标 | `setup_env.py`、`experiments/experiment_helpers.py`、`experiments/cisco_se_economics.py`、`scripts/run_cisco_se_ab.py`、`experiments/run_experiment.py`、`domains/cisco_se/config.yaml` | 实验指标 = Domain YAML `experiments.metrics`（列表或按 profile 的映射）或 profile 默认；imlab-onprem 默认 Ground Truth Adherence（无 Luna 版本，LLM 评判）+ Context Adherence / Prompt Injection / Completeness (SLM)；Cisco SE 导出器在 on-prem 优先取 Luna 变体；`run_experiment.py` 新增 `--provider` |
| vLLM provider | `helpers/hermes_chat.py`（新）、`helpers/llm_utils.py`、`domain_manager.py`、`agent_frameworks/langgraph/*.py` | `HermesToolCallChatOpenAI`：在 `_generate/_agenerate` 内（回调之前）把 `<tool_call>{json}</tool_call>` 解析为结构化 `tool_calls`，JSON 损坏时保留原文；请求带 `chat_template_kwargs.enable_thinking=false` 并清除 `<think>`；关闭流式以保证走解析路径。provider 键 `vllm`（显示名 `vLLM (<模型>)`），优先级最低（默认仍为 OpenAI）；RAG embedding 固定为 hosted |
| 容器化 | `scripts/export_cisco_se_economics.py`、`scripts/run_cisco_se_ab.py` | 输出目录可由 `DEMO_DATA_DIR` 指定（默认仍为 `data/`） |
| 构建与部署 | `Dockerfile`、`.dockerignore`、`deploy/helm/splunk-ao-golden-demo/`、`deploy/k8s/scripts/`、`deploy/k8s/build/build-image.sh` | 见下 |
| 卫生检查 | `scripts/check-public-hygiene.sh` | 通用模式（内网 IPv4、私钥、各类 Key/Token、htpasswd 哈希、JWT）+ 运行时从本地被忽略的 `secrets.toml*` 与 `.work/hygiene-terms.txt` 读取的环境专有词与密钥值；输出只含规则、文件、行号；`--path` 扫描镜像文件系统 |
| 示例配置 | `.streamlit/secrets.toml.example` | profile 说明、按后端保存的文件约定、集群内地址键、vLLM 键、`[k8s]` 表示例（全部占位符） |
| 测试 | `tests/test_onprem_k8s.py`（新，20 个） | profile 推导与覆盖、切换 profile 清除旧 ingest 地址、错误不泄露值、REST 路径、ingest 地址补丁（探测/写入/更新分流、未配置不变）、Hermes 解析（单个/多个/JSON 损坏/无调用/`<think>`/回调前解析/回传消息格式）、vLLM provider 与 embedding、Luna 指标选择、`[k8s]` 表剥离与密钥不上终端 |

**部署设计要点**：
- Dockerfile：`python:3.12-slim` 固定 digest（Python 3.12.16）+ uv 0.11.2，`requirements.txt` 以 `requirements.lock.txt` 约束安装到 `/opt/venv`，构建内 `uv pip check`；非 root（uid 10001）；`STREAMLIT_SERVER_ADDRESS=0.0.0.0` 等以环境变量覆盖（不改 Mac 的 `config.toml`）；`HEALTHCHECK /_stcore/health`。`.dockerignore` 排除 `.git .venv .runtime .work data .agent-context secrets.toml*（保留 example）tests documentation deploy` 等。
- Helm chart：app Deployment（1 副本、`Recreate`、只读根文件系统、`automountServiceAccountToken: false`、`/tmp` `/home/app` `/data` 为 emptyDir、initContainer 合并系统 CA 与 ConfigMap `ao-internal-ca` → `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE`、`config-checksum` 注解使配置变更触发重建）；PostgreSQL StatefulSet（`pgvector/pgvector:pg17`、PVC 5Gi、节点可固定）；Ingress（`nginx`、TLS、Basic Auth 注解、超时 3600）；init Job 模板默认不渲染。Secret 只按名称引用，密钥不进 Helm values / release 历史；`image.tag` 必填且禁止 `latest`。
- 脚本：`secrets_tool.py`（只读 `secrets.toml`；`check` 只输出键名与 set/EMPTY；密钥类输出拒绝写到终端，只能进管道）；`10-prepare-namespace.sh`（幂等；只读 AO 的 CA ConfigMap；自签 TLS 已存在则复用；`openssl passwd -apr1 -stdin` 计算哈希）；`20-deploy.sh <tag>`；`30-init-data.sh`（按需 Job）；`40-verify.sh`（Pod 内预检 + 经共享 ingress NodePort 的 401/200 检查，凭据经 `curl -K -` 标准输入）；`90-rollback.sh`（不含卸载/删除）。

**验证**：
- 单元测试：`DEMO_TEST_POSTGRES=1 python -m unittest discover -s tests -p 'test_*.py' -v` → **Ran 70, OK**（原 50 + 新 20；含 PG 集成测试）。
- `helm lint` 通过；`helm template` 渲染 5 个对象（2 Service、Deployment、StatefulSet、Ingress），init Job 单独渲染正常；缺 `image.tag` 或为 `latest` 时拒绝渲染。
- **splunkse 回归**（SaaS Key 有效）：`scripts/check-demo.sh --live` 全部 PASS（含 Project/Log Stream、原生 ingest 门、Agent Control `/health`、5 个 hosted 模型）；UI Healthcare 两个例题：Lisinopril（10–40 mg、干咳等，RAG 正确）、P001（George Rivera，工具调用正确），侧栏 “Agent Control connected”、`Backend: splunkse`。
- 卫生检查：`bash scripts/check-public-hygiene.sh` → PASS；反向验证（临时文件含环境词、内网 IP、apr1 哈希）3 处均被拦截。

**问题与处理**：
- 单元测试日志写到 OneDrive 同步目录中**同名**文件时被清空（退出码 120，内容丢失）；同样的测试输出到 `/tmp` 正常。原因：OneDrive 对快速重写的同名文件的同步干扰。处理：日志文件名一律带时间戳。
- 卫生检查初版把 `agent_control_api_key_header`（键名含 key，值只是头名）当成密钥值造成误报；改为排除 `*_header` 键。
- `[k8s]` 表最初按“必须在末尾”设计；实现上任意位置都能正确剥离，并以“剥离后重新解析应等于原内容去掉 k8s”作校验（多行字符串中含 `[k8s]` 文本时拒绝）。

### 2026-11-21 阶段 2：On-prem 兼容性验证（执行者：Mac 上的 GitHub Copilot；21:35 开始，22:40 完成）

执行方式：Mac 上 `cp .streamlit/secrets.toml.imlab-onprem .streamlit/secrets.toml` 后启动本地 App（经公网访问 AO），`<OPS_NODE>` 上只读查看 AO 日志；结束后已用 `secrets.toml.splunkse` 恢复。

1. **预检**：`scripts/check-demo.sh --live`（imlab-onprem）：profile、地址推导、头名 `Splunk-AO-API-Key`、AO API `/healthcheck`、`/ingest/healthz`、Agent Control `/health`、5 个 hosted 模型均 PASS。首次运行时 Project/Log Stream 尚不存在（A5：首条 Trace 自动创建）；“SDK 原生 ingest 门”探测偶发 FAIL——SDK 探测超时固定 2 秒且结果按进程缓存，经公网偶尔超时；`check_demo.py` 改为清缓存重试一次（C1b）。
2. **Trace 写入（原生 JSON 门）**：UI Healthcare 两例题（Lisinopril / P001）回答正确，自动创建 Project `splunk-ao-golden-demo` 与 Log Stream `healthcare`。ingress 访问日志：`POST /ingest/traces/<pid>`（→ ingest-service:8081，200，0.04–0.9 s）；没有 Legacy `POST /v2/projects/<pid>/traces`；session 调用 `POST /v2/projects/<pid>/sessions` 走 api（与官方 Observe Request Flow 一致）。
3. **Agent Control（G2a ✅）**：SDK 8.11.0 对服务端 v0.5.30：`init` → 注册回读 → 运行时评估均正常（侧栏 “Agent Control connected”）；`Splunk-AO-API-Key` 与 `Galileo-API-Key` 两种头都可读回 Agent。**SDK 版本决定（A10）**：`galileo` 2.6.0、`agent-control-sdk` 8.11.0 保持不变。
4. **Luna 指标盘点**：AO 共 94 个 scorer，其中文本类 SLM（Luna）17 个，归为 13 个指标族，与 Wizard 的 13 个 LoRA adapter（编号 1、3–14）一一对应：

   | 指标族（Luna / SLM） | scorer 标签 | 演示场景 |
   | --- | --- | --- |
   | Context Adherence | Context Adherence (SLM) | RAG 回答是否忠于检索内容（幻觉） |
   | Completeness | Completeness (SLM) | 回答是否覆盖检索到的要点 |
   | Context Relevance | Context Relevance (SLM) | 检索结果与问题是否相关 |
   | Chunk Relevance | Chunk Relevance (SLM) | 每个检索块是否有用 |
   | PII | Input PII (SLM)、Output PII (SLM) | 患者电话/地址检出；POST Steer Control |
   | Prompt Injection | Prompt Injection (SLM) | 注入攻击检出；PRE Deny Control |
   | Toxicity | Input / Output Toxicity (SLM) | 有害内容 |
   | Sexism | Input / Output Sexism (SLM) | 偏见内容 |
   | Tone | Input / Output Tone (SLM) | 语气分类 |
   | Tool Selection Quality | Tool Selection Quality (SLM) | Agent 是否选对工具 |
   | Tool Error Rate | Tool Error Rate (SLM) | 工具调用是否出错（Chaos 演示） |
   | Action Completion | Action Completion (SLM) | 会话级：用户目标是否完成 |
   | Action Advancement | Action Advancement (SLM) | 每轮是否推进用户目标 |

   AO API（scorer 定义）与 Wizard 日志 / Prometheus 指标都不暴露“adapter 编号 ↔ 指标”的对应，表中按指标族对应，不写编号。启用后实测出分（`healthcare` 启用 17 个、`cisco-se` 启用 9 个）：P001 的 Output PII 检出 `address, name, phone_number`；Prompt Injection 0.004；Action Advancement 0.905；Cisco SE span 级 Context Adherence (SLM) 0.984 / 0.531、Completeness 1.0、Tool Selection Quality 0.996、Tool Error Rate 0、Context Relevance 1.0、Chunk Relevance [1, 0, 0]。Wizard 当时累计 42 次 Luna 推理，平均 0.80 s/次（本地 L4）。
5. **Controls（G2b，经用户决策后 ✅）**：新增 `scripts/setup_demo_controls.py`（按 profile 查 Luna scorer ID、幂等、按需启用/停用绑定），在 on-prem 创建 `splunk-ao-golden-demo-block-harmful-sql`（PRE Deny，`input.sql`）、`-block-output-pii`（POST Steer，Output PII (SLM)，`or` + 两个 `contains`）、`-block-prompt-injection`（PRE Deny，Prompt Injection (SLM) ≥ 0.80），绑定 `healthcare` Log Stream。
   - **问题**：三条全部启用时，普通请求也被 Prompt Injection 拦截（“Show me data for patient P001.” 0.933、“Delete patient P001.” 0.894）。原因：LLM 步骤的 Control 输入是整段消息列表的字符串（系统提示词 + 历史 + 工具结果），on-prem Luna 对其给出高分。对照实测（`check_evaluation`，PRE）：只送用户本轮消息时普通问题 0.0001–0.04、Steer 重试提示 0.12、固定攻击 Prompt 0.9998；送 App 原载荷时普通问题 0.851。
   - **决策（用户选择方案 A）**：App 侧让 LLM 步骤的 Control 输入只取最新一条用户消息（或 Steer / 工具修正提示）（`agent.py` 的 `latest_user_text()`，`_invoke_llm(input, msgs)`），两个后端一致，阈值保持 0.80；该 Control 不再检查系统提示词与工具返回内容（间接注入不在其范围）。放弃的方案：只在 on-prem 把阈值提到 0.95（普通 0.85–0.93 与攻击 0.9998 间余量过小）；改用 LLM 评判（偏离“Luna 优先”）；保持现状仅在演示时临时启用（存在误拦截）。
   - **修改后实测**（三条全部启用）：P001 → PI 0.0056 放行 → Output PII 检出 address/name/phone → Steer → 重试 PI 0.063 放行 → 复检只剩 name → 回答不含电话/地址；Lisinopril → PI 0.00015，正常；删除 P001 → PI 0.040 放行 → SQL PRE Deny（`healthcare_patient` 仍 30 行、P001 仍在）；固定攻击 Prompt → PI 0.9998 PRE Deny，无模型调用，整条 Trace 1.0 s。结束后恢复标准演示状态：SQL 启用，PII / Injection 停用。
6. **Dataset / Experiment**：`create_galileo_dataset.py healthcare` 建 Dataset（15 条）。Experiment 指标按 profile：Ground Truth Adherence（LLM 评判）+ Context Adherence / Prompt Injection / Completeness (SLM)。2 条样本的实验写入并出分（PI (SLM) 均值 0.001、GT Adherence 完成、CA/Completeness 为 span 级）。**15 条样本在 Mac 上未能写入**：SDK 在实验结束时一次性上传 15 条 Trace，`IngestTraces` 报错（信息为空）被 SDK 吞掉后仍显示“Successfully flushed”，集群 ingress 无此请求。原因：Mac 经公网的上行很慢（无凭据请求体对照：1 MB 用时 77 s），超过 SDK 60 s 超时。集群内直连 ingest-service 不受影响，15 条样本实验放到阶段 6 在集群内验收（这次排查中向公网入口发送了最大 8 MB 的无凭据请求体，用户指出没有必要，之后不再做这类测试）。
7. **成本 / reliable_ingest**：on-prem 价格表包含 `gpt-5.4-nano`、`gpt-5-nano`、`gpt-6.1-sol`，LLM Span `cost > 0`、`cost_status=success`，且这些 Trace 均**未**启用 `reliable=True`。结论：on-prem 的原生门写入即可计价，splunkse 的 `reliable_ingest` 变通在 on-prem 不需要（Cisco SE 配置保留，无害）。Cisco SE 双模型各 1 题均正确作答（Project `splunk-ao-golden-demo-cisco-se` 自动创建）。
8. **Console 深链**：`<console>/project/{pid}/log-streams/{sid}` 与 `<console>/project/{pid}/experiments/{group}/{id}` 在 on-prem 均可直接打开（Console 自动重定向到 `/<org-slug>/project/...`），代码无需修改。
9. **结论**：现有插桩（`GalileoCallback` + `GalileoLogger`）经原生 JSON ingest 门写入 on-prem，**无需改 OTLP**；SDK 版本不升级；Luna 指标与三条 Control 可用。

**其他问题与处理**：
- Mac 上 App 的 stdout 重定向到 OneDrive 同步目录内的日志文件时，写入会阻塞并报 `TimeoutError: [Errno 60]`，表现为页面 “Invalid secrets configuration”（`print()` 失败）和删除请求 “Error processing your request: [Errno 60] Operation timed out”。处理：App 运行日志写到 `/tmp`；`setup_env.py` 的通用错误信息附带异常类型名与栈帧位置（不含任何值），便于以后定位。
- `.runtime/postgres` 中 81 个 PG 数据文件被 OneDrive 驱逐为 dataless（Mac 既有布局，本次未改动）。

**C1b 改动**：`agent_frameworks/langgraph/agent.py`（方案 A）、`scripts/setup_demo_controls.py`（新）、`scripts/check_demo.py`（探测重试）、`setup_env.py`（错误诊断信息）、`tests/test_onprem_k8s.py`（+1：LLM Control 输入为最新用户消息）。

### 2026-11-21 阶段 3：镜像构建与推送（执行者：Mac 上的 GitHub Copilot，经 JumpServer 在 `<BUILD_HOST>` 操作；22:33 开始，22:55 完成）

```bash
# <BUILD_HOST>，tmux 会话 sao-golden-build / sao-golden-push
cd /root/<BUILD_WORKDIR> && git pull --ff-only
bash deploy/k8s/build/build-image.sh all  highope/sao-golden   # build + smoke + scan
bash deploy/k8s/build/build-image.sh push highope/sao-golden
```

| 项 | 结果 |
| --- | --- |
| 镜像 | `highope/sao-golden:1.0.0-03a0a1f`（linux/amd64，用户 10001:10001，标签 `org.opencontainers.image.title=sao-golden`，264 MB） |
| digest | `sha256:3536d717b601420095e2787dde1a00c0a8d5f96176bcb1fdb9965b84fd87e19f` |
| 依赖 | 构建内 `uv pip check`：114 个包全部兼容（以 `requirements.lock.txt` 约束；macOS 锁文件在 Linux 上无需调整） |
| 冒烟（`sao-golden-smoke-*` 容器/网络/卷，结束后全部删除） | 只读根文件系统运行：`/_stcore/health` 200、首页 200；系统 CA bundle 存在；容器内 `tests.test_runtime` + `tests.test_onprem_k8s` 37 个 OK（3 个部署工具测试因镜像不含 `deploy/` 而跳过）；连接 `pgvector/pgvector:pg17`（PostgreSQL 17.12）成功 |
| 镜像卫生 | `/app` 无 `.git`、`.venv`、`.runtime`、`.work`、`data`、`.agent-context`、`tests`、`secrets.toml`（`.streamlit/` 仅 `config.toml`、`secrets.toml.example`）；`docker history` 无凭据类构建参数；导出 `/app` 跑 `check-public-hygiene.sh --path` PASS（`<BUILD_HOST>` 的 `.work/hygiene-terms.txt` 提供本地词表） |
| Docker Hub | `is_private: false`；匿名取 manifest 200，digest 与上表一致 |

**问题与处理**（试错）：
1. 构建机上找不到 `deploy/k8s/build/build-image.sh`：上游 `.gitignore` 的 Python 打包规则 `build/` 同时忽略了 `deploy/k8s/build/`，脚本从未进入 Git。处理：规则改为只匹配根目录 `/build/`（提交 `8b72a33`）。
2. 构建后以非 root 运行 `uv pip check` 报 `Failed to initialize cache at /home/app/.cache/uv`：构建时 root 在 `HOME` 下创建了 uv 缓存。处理：`UV_CACHE_DIR=/tmp/.uv-cache`，安装后删除缓存（提交 `7af15f9`）。
3. 冒烟中容器内 3 个测试报错：部署工具测试需要 `deploy/`，而镜像按设计不含。处理：缺少该工具时跳过（提交 `03a0a1f`）。
4. 失败的中间标签 `1.0.0-8b72a33`、`1.0.0-7af15f9` 只在构建机本地，未推送；第 9 阶段清理。

### 2026-11-21 阶段 5：部署到 Kubernetes（执行者：Mac 上的 GitHub Copilot，经 JumpServer 在 `<OPS_NODE>` 操作；22:55 开始，23:25 完成）

**预检**：工作副本快进；`secrets_tool.py check` 键齐全；`helm lint` 通过；`helm template … | kubectl apply --dry-run=client` 通过；只读取得 `galileo/galileo-internal-ca-cert`（Galileo Internal Root CA，到期 2031-11-19）；用该 CA 经 ClusterIP + SNI 校验 `api.galileo.svc.cluster.local`、`ingest-service.galileo.svc.cluster.local` 证书主机名均 `Verify return code: 0 (ok)`（节点自身不解析 `*.svc.cluster.local`）。AO 基线：`galileo-stack` rev5、`pulse` rev1。

| 时间 | 命令（在 `/root/<WORKDIR>`） | 结果 |
| --- | --- | --- |
| 22:55 | `bash deploy/k8s/scripts/10-prepare-namespace.sh` | 命名空间 `sao-golden`（标签 `app.kubernetes.io/part-of`）；ConfigMap `ao-internal-ca`；自签 TLS `sao-golden-tls`（`<APP_HOST>`，到期 2029-11-20）；Secret `sao-golden-postgres`、`sao-golden-app`（21 个键、无 `[k8s]`）、`sao-golden-basic-auth`（1 行 apr1）。约 3 s |
| 22:56 | `bash deploy/k8s/scripts/20-deploy.sh 1.0.0-03a0a1f`（tmux） | rev1；PG 调度到 `<PG_NODE>`，PVC 5Gi（openebs-hostpath）；App Running。约 3 min（含首次拉取镜像） |
| 23:03 | 同上（chart 改为 auth-url，见下） | rev2 |
| 23:07 | 同上（认证服务修复） | rev3 |
| 23:07 | `bash deploy/k8s/scripts/30-init-data.sh`（tmux） | Job `sao-golden-init-…` Complete，2 min 35 s：healthcare 15 篇/30 行、bank 9/30、insurance 9/30、restaurant 19/40、cisco_se 34 篇（`text-embedding-3-large`） |
| 23:16 | `bash deploy/k8s/scripts/20-deploy.sh 1.0.0-e93c4d6` | rev4（修复 `check_demo.py` 后的新镜像） |
| 23:17 | `bash deploy/k8s/scripts/40-verify.sh` | **ALL PASS**（见下） |

**`40-verify.sh`（rev4）**：Pod 就绪；Pod 内 `check_demo.py --in-cluster --live`：profile/地址、REST 不经 Console、Pod `/_stcore/health` 200、CA bundle 149 张证书、`SSL_CERT_FILE`=`REQUESTS_CA_BUNDLE`、AO API `/healthcheck`、ingest-service `/ingest/healthz`、Agent Control `/health`、SDK 选择原生 ingest 门、Project/Log Stream、Agent Control 注册回读、5 个 hosted 模型、pgvector 0.8.7、`healthcare_patient` 30 行、`healthcare_hosted_index` 15 篇 → 全部 PASS；经共享 ingress NodePort：无凭据 401、Basic Auth 200、`/_stcore/health` 200。

**外网（闸门 G5 ✅）**：Mac 访问 `https://<APP_HOST>/` 与 `/_stcore/health` 无凭据均 401（`WWW-Authenticate: Basic realm="Splunk AO Golden Demo"`，`server: openresty`，Let's Encrypt 通配证书）——OpenResty 通配转发已确认，无需 OpenResty 改动。用户在 Chrome 中以 `<BASIC_AUTH_USER>` 登录后：页面正常、WebSocket 正常，Healthcare 两例题 31.8 s / 10.6 s 正确作答，侧栏 “Agent Control connected”、`Backend: imlab-onprem`；“Open Splunk AO Console” 与 “View traces” 链接均指向公网 `console.<AO_DOMAIN>`。

**集群内走内部地址**：ingest-service 日志中有来自 App Pod IP 的 `POST /ingest/traces/<pid>`，同期 ingress 上 `/ingest` 请求为 0——Trace 经 ingest-service 内部地址写入。

**AO 未受影响**：`galileo-stack` rev5、`pulse` rev1 不变；AO 的 `deploy/scripts/70-verify.sh`（只运行）“验证通过”；`/root/ns_galileo` 工作区无变更。

**问题 1：共享 ingress-nginx 无法使用 `auth-type: basic`（设计变更，用户决策）**
- 现象：事件 `AnnotationParsingFailed: unexpected error creating password file: open /etc/ingress-controller/auth/…passwd: read-only file system`；该位置被拒绝，返回 503。
- 原因：AO 的 ingress-nginx 控制器 `readOnlyRootFilesystem: true`，且没有可写的 `/etc/ingress-controller/auth` 挂载；`auth-type: basic` 需要在控制器内写 htpasswd 文件。任务书 4.6 “无需改动 AO 控制器”的前提不成立。
- 决策（用户选择方案 A）：本应用在自己的命名空间部署认证服务 `sao-golden-auth`（`nginxinc/nginx-unprivileged:1.30.6-alpine`，固定 digest，非 root，只读根文件系统），读取同一个 Secret `sao-golden-basic-auth`；Ingress 改用 `nginx.ingress.kubernetes.io/auth-url`（外部认证）。浏览器仍弹 Basic Auth 框，AO 零改动。放弃的方案：Pod 内 nginx sidecar（可行，但改动应用 Pod 结构）；修改 AO 控制器（违反 D15）。

**问题 2：安全事件——约 70 秒的无认证暴露（已处理）**
- 经过：auth-url 版本（rev2，23:03:03）部署后，23:04:19 内网检查发现无凭据也返回 200。23:04:33 执行 `kubectl -n sao-golden scale deploy sao-golden-app --replicas=0` 止损（之后返回 503）。暴露窗口约 23:03:20–23:04:30。
- 影响核查：ingress 访问日志显示该窗口内对 `<APP_HOST>` 的访问只有执行者从 `<OPS_NODE>` 发出的 2 次检查请求，**没有外部访问**。
- 原因：认证服务配置中 `location / { auth_basic …; return 204; }`——nginx 的 `return` 在 rewrite 阶段执行，早于 `auth_basic`（access 阶段），所以所有请求都被放行。
- 处理：改为 `try_files /__authenticated__ =204;`（precontent 阶段，在认证之后），并在模板中注释说明。先在 App 为 0 副本时单独验证认证服务（port-forward：无凭据 401 + `WWW-Authenticate: Basic`、错误凭据 401、正确凭据 204），再 `20-deploy.sh` 恢复 App（rev3）：无凭据 401、错误凭据 401、正确凭据 200；`/_stcore/health`、`/_stcore/stream`、静态资源、`/healthcare` 无凭据均 401。
- 教训：涉及对外暴露的变更，应先在后端不可用时验证认证，再放出后端（已写入 KUBERNETES.md 的变更步骤）。

**问题 3：`check_demo.py` 在 Pod 内报 `UnboundLocalError`**
- 原因：C1b 在 `main()` 中加了局部 `import importlib`，使整个函数里的 `importlib` 变成局部变量。处理：删除局部导入，新增回归测试（模拟缺少 `secrets.toml` 时 `main()` 返回 1、不抛异常），重建镜像 `1.0.0-e93c4d6`（`sha256:4a7076fc8b12a513bf2ed89338ee0a5f9bec231d9b9674e458183061494f12b2`，冒烟 38 个测试 OK、卫生 PASS）。

**当前对象**（命名空间 `sao-golden`）：Deployment `sao-golden-app`（1/1）、`sao-golden-auth`（1/1）；StatefulSet `sao-golden-postgres`（1/1，PVC 5Gi @ `<PG_NODE>`）；Service ×3；Ingress `sao-golden`（`nginx`，TLS，auth-url）；ConfigMap `ao-internal-ca`、`sao-golden-auth`；Secret ×4；Helm release `sao-golden` rev4。

### 2026-11-21 阶段 6：演示验收（执行者：Mac 上的 GitHub Copilot；浏览器在已认证的 `<APP_HOST>` 标签页中操作，命令经 JumpServer 在 `<OPS_NODE>` 执行；23:25 开始，23:55 完成）

汇总结果见 [VALIDATION.md](../VALIDATION.md#onprem-k8s)。这里记录做法与原始数据位置（`<OPS_NODE>:/root/<WORKDIR>/.work/logs/`）。

**浏览器流程**（Playwright 在已登录的标签页中操作；侧栏 `Backend: imlab-onprem`）：

| 场景 | Control 绑定 | 结果 |
|---|---|---|
| Act 3 Hallucination fixture | sql | “100mg daily” 写入 Trace |
| Act 4 删除 P001 | sql | `block-harmful-sql` → deny；之后 `healthcare_patient` 30 行、P001 存在（PG 只读查询） |
| Chaos：Tool Instability / Rate Limits / RAG Disconnect / Sloppiness / Data Corruption | sql | 503；429；检索断开；数字被改（P16）；`gpt-4o` 下 10mg → 99mg。Reset 会清除 Chaos 开关，但模型选择可能保留 |
| PII（Luna `pii`） | sql,pii | 首次输出检出 `address`/`name`/`phone_number` → Steer → 修正后输出不含电话与地址 |
| Prompt Injection（Luna `prompt_injection`） | sql,injection | 攻击 0.9998 → deny（Trace 0.5 s）；Lisinopril 0.00015 放行 |
| 恢复 | sql | `setup_demo_controls.py --bindings-only --enable sql`：SQL enabled、PII disabled、Injection disabled |

**Pod 内运行**（`kubectl -n sao-golden exec deploy/sao-golden-app -c app -- …`，长任务放 tmux）：

| 时间 | 内容 | 日志 / 产物 | 结果 |
|---|---|---|---|
| 23:35 | `experiments/run_experiment.py healthcare --provider hosted --experiment-name healthcare-k8s-luna-<ts>` | `experiment-healthcare-k8s-<ts>.log`、`experiment-summary-*.log`、`experiment-spans-*.log` | 退出码 0；15 条 Trace 全部写入（阶段 2 在笔记本上因上行带宽失败的部分已完成）；LLM Span 上 `context_adherence_luna` 均值 0.884、`completeness_luna` 0.933（各 45 个）；Trace 上 `prompt_injection` 均值 0.001；GT Adherence 约 15 分钟内 15/15 `success` |
| 23:37 | Qwen：探针 `agent_run.py healthcare vllm` 三题 | `qwen-probe-*.log`、`qwen-evidence-*.log` | 18 / 38 / 56 s；LLM Span `model=Qwen/Qwen3-14B-FP8`，`tool_calls`：`get_patient_info`、`search_medicine_qa`、`delete_patient_record`；SQL Control deny；Trace 上 Luna 指标齐全（P001 回答检出 `pii`） |
| 23:41 | `scripts/run_cisco_se_ab.py` → `scripts/export_cisco_se_economics.py` | `cisco-se-ab-*.log`、`cisco-se-export-*.log`；`/data/cisco_se_ab_runs/20261121T154130Z.json`；CSV `kubectl cp` 到 `.work/cisco_se_model_economics-k8s-20261121.csv` | 预检全部 PASS（两个模型真实工具调用、Scorer、Dataset、Group、reliable ingest）；每个模型约 100 s；回读 GT 10/10；导出 20 行、`comparison_ready` 20/20；数值见 VALIDATION |
| 23:42 | Bank / Insurance / Restaurant 冒烟（`agent_run.py <domain> hosted`） | `smoke-domains-*.log` | 6 题全部正确作答，5–12 s |
| 23:45 | 证据回读：探针 `pod_evidence.py splunk-ao-golden-demo healthcare 25` | `control-evidence-*.log` | 各 Control 决策与分数（见上表） |
| 23:46 | Wizard `/metrics`（ClusterIP，只读 GET） | 临时文件已删除 | 726 次请求；e2e 合计 289.9 s（均值 0.40 s）、排队 24.3 s、prefill 222.2 s；`finished_reason=error` 0；节点 GPU 为 NVIDIA L4 |

探针脚本 `agent_run.py`、`pod_evidence.py`、`exp_summary.py`、`exp_spans.py`、`smoke-domains.sh` 在 `.work/probes/`（不进 Git），通过 `kubectl exec -i … python - <args> < 脚本` 在 Pod 内执行，不修改镜像。

**发现**：

1. On-prem 的 Ground Truth Adherence 评判模型是集群内 `Qwen/Qwen3-14B-FP8`（CSV `judge_model`），评判费用 0，但比 SaaS 慢（15 样本约 15 分钟、A/B 每个模型约 5 分钟）。已写入 README 与 CSV 契约。
2. Control Span 时长记为 0（SDK 的决策标记），Luna Control 时延改用整条 Trace 时长与 Wizard 指标说明。
3. Trace 根上的 `context_adherence_luna`、`completeness_luna` 为 `roll_up`，分数在 LLM Span 上（与 SaaS 的 Context Adherence 相同）。
4. 第一次把两个文件并行上传到 `<OPS_NODE>` 的 Web 终端导致该终端会话断开；改为串行上传后正常（只影响操作方式）。
5. Grafana 仪表盘未截图（含账号信息，不入库）；时延数据取自 Wizard `/metrics`。

### 2026-11-21 阶段 8：文档完善与同步（执行者：Mac 上的 GitHub Copilot；23:30 开始，00:10 完成）

- 本仓库（`0972419`）：新增 [KUBERNETES.md](../KUBERNETES.md)（含“部署前人工准备”）；README 增加 K8s / On-prem 入口、1.2 两套环境对照、2.2 Kubernetes、3.1 多后端 `secrets.toml.<后端>` 与 profile、3.5 On-prem 差异、4.6 K8s 维护、5.9 本地化 Luna 演示、6.6 架构原理、第 7 章排障、8.4 Roadmap；[VALIDATION.md](../VALIDATION.md#onprem-k8s) 新章节；UPSTREAM 修改清单；CSV 契约第 8 节。卫生检查 PASS（127 个文件），相对链接与锚点检查 0 错误。
- AO 平台仓库（只改文档，私有）：README 3.17.2（通配转发）、4.2（集群内访问 AO）、新 4.12（独立应用共用入口的约定与已接入应用清单）、5.1 K20（K10 并入）、6.3 排障；OpenResty 配置文件注释；平台事实登记记录。
- 同步：两个仓库在 GitHub、Mac、`<OPS_NODE>`（本应用与 AO 两个工作目录）、`<BUILD_HOST>` 均快进到最新提交，工作区干净。

### 2026-11-22 阶段 9：收尾（00:10–00:20）

- `<BUILD_HOST>`：删除本任务的旧本地镜像标签 `1.0.0-8b72a33`、`1.0.0-7af15f9`（构建失败，未推送）与 `1.0.0-03a0a1f`（已被取代，Docker Hub 上仍保留）；保留运行中的 `1.0.0-e93c4d6`。无 `sao-golden-*` 冒烟容器、网络、卷；未执行任何 `prune`。
- `<OPS_NODE>`：本任务的 tmux 会话已结束；`/tmp` 无本任务文件；`.work/probes/` 与 `.work/logs/` 保留（Git 忽略）。
- Mac：`secrets.toml` 为 `splunkse`；本地 App 已停；删除 `/tmp` 中的 helm 渲染临时文件；停止防休眠。
- 最终核对（23:59）：`40-verify.sh` **ALL PASS**；外网无凭据 401；AO `galileo-stack` rev5、`pulse` rev1，AO `70-verify.sh` 验证通过，AO 工作目录干净、`.secret/` 无新文件、`galileo` 命名空间无本任务创建的对象；Demo Control 为 SQL 启用、PII / Injection 停用。
