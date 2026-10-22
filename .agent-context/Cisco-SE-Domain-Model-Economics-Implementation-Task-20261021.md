# Splunk AO Golden Demo：Cisco SE Domain 与双模型经济性演示实施任务书

> **任务类型**：对现有仓库的增量开发 / Codex 或 GitHub Copilot 执行说明  
> **目标仓库**：`https://github.com/highopes/splunk-ao-golden-demo`  
> **建议放置路径**：`.agent-context/cisco-se-domain-model-economics-task.md`  
> **编制日期**：2026-10-21  
> **任务目标**：新增 `cisco_se` Domain，使用真实 RAG（Retrieval-Augmented Generation，检索增强生成）回答 Cisco 与 H3C 公开产品技术参数问题；使用同一 Dataset 对 **GPT-5 nano** 和 **GPT-6.1 Sol** 执行真实的 Splunk Agent Observability（AO）Experiment；导出结构化 CSV，供另一个仓库的 Splunk Enterprise Dashboard 使用。

---

## 0. 给执行 Agent 的工作约定

你是本仓库的实施工程师。**请直接完成代码、数据、测试与文档修改，不要停留在方案设计或只创建 TODO。** 首先阅读本仓库最新 `README.md`、`.agent-context/`、`documentation/VALIDATION.md`、`tests/` 以及本文引用的实现，确认本地分支和依赖锁文件的真实状态。本文依据 2026-10-21 可访问的 `main` 代码编制；若执行时仓库已演进，以现有代码为准，在不改变本任务目标的前提下作最小适配，并在最终交付说明中记录差异。

- **保留既有 Healthcare、Bank、Insurance、Restaurant Domain**，以及当前能够运行的 Healthcare 15 分钟和 30 分钟 Golden Demo；不得通过重命名、迁移、替换默认 Healthcare 流程来实现新需求。
- 遵循已有架构：`DomainManager` + `AgentFactory` + `LangGraphAgent` + `PostgreSQL/pgvector` + Splunk AO SDK / Agent Control。优先复用既有 Python 类与 Experiment 逻辑；新增的抽象必须有实际复用价值。
- **不要在代码或文档中硬编码 API Key、Console 密钥、数据库密码、令牌或私有服务地址。** 不要提交 `.streamlit/secrets.toml`、本地运行状态、生产 Trace 导出或含敏感字段的日志。
- 允许联网检索 Cisco / H3C / OpenAI / Splunk 的**公开官方文档**，必须核实产品型号与参数；来源不可访问或参数矛盾时，不要猜数字，应更换有充分证据的题目。研究竞争对手事实必须客观准确。
- 保持已有 README 的**中文、分层结构、操作手册式语言和人类可读性**；新增内容应说明“做什么、怎么操作、看到什么、成功标准、失败如何处理”，而不是简单堆积 SDK 接口。
- 不能提供虚假的在线验收结论：如果实际 OpenAI Key、Splunk AO 租户、网络或费用权限不具备，仍须完成可离线验证的改动与测试，明确列出无法在线验收的项目及复现命令；不得生成虚构的 Experiment、Judge 分数、费用或演示截图。
- 按本任务的范围控制开发量。**本次不制作 Splunk Enterprise App / Dashboard。** 不实现额外的业务安全演示来扩大范围。

### 实施前建议重点阅读

| 文件 / 位置 | 当前作用 / 要核对的点 |
|---|---|
| `README.md` 第 4.2、4.3、5 节 | Domain 扩展办法、模型切换、Experiments 与 Demo 叙述 |
| `domain_manager.py`, `agent_factory.py` | 新 Domain 自动发现、模型覆盖和 Factory 创建 |
| `agent_frameworks/langgraph/agent.py` | Main LLM、工具调用、`@control`、RAG Tool、Callback |
| `agent_frameworks/langgraph/langgraph_rag.py` | 当前 pgvector + retrieval chain、模型与 top_k 选择 |
| `helpers/setup_vectordb.py`, `helpers/pgvector_utils.py` | `docs/qa.csv` 的导入优先级、Embedding 集合与自动回退行为 |
| `helpers/llm_utils.py` | `ChatOpenAI` 配置、API 类型、`temperature` 与 Reasoning 参数 |
| `experiments/experiment_helpers.py`, `app.py` | Dataset、运行 Experiment、Scorer 选择和 UI 操作 |
| `setup_env.py`, `.streamlit/secrets.toml.example` | 共享 Key 与 Console 设置、Domain 专属 Project / Stream |
| `documentation/VALIDATION.md`, `tests/` | 既有验收基线，回归测试 |
| 参考导出器：`https://github.com/highopes/alicloud-ack-byocni/blob/main/scripts/export-banking-cn-economics` | Experiment / Trace / Span / Judge 字段采集、CSV 一致性与校验，不可原样复制 |
| 参考可视化：`https://github.com/highopes/splunk-galileo-dashboard` | **仅用于确定 CSV 消费契约；本次不修改此仓库** |

## 1. 交付目标、边界与验收闭环

### 1.1 本次必须完成（In scope）

1. 建立一个独立的 `cisco_se` Domain，模拟 Cisco 售前工程师查询 Cisco Nexus 9300D/9300E 400G/800G 产品和 H3C 竞品的技术指标。
2. 从下述 Cisco / H3C **公开官方资料**提取可溯源的知识片段，并构造小规模、真实、可维护的 RAG 知识库；不能仅依赖模型预训练记忆回答，也不能把 Experiment 的 Ground Truth 硬编码为运行时答案。
3. 构造 **10 条左右**适合现场展示的问答 `dataset.csv`，含可核对的 Ground Truth，兼有单厂商参数问答和跨厂商比较。
4. 新场景使用两款固定应用模型：**Model A = `gpt-5-nano`；Model B = `gpt-6.1-sol`**。两者必须真实调用；保持同一 Prompt、知识库版本、Embedding、Tool 定义和评测器，并分别建立 Splunk AO Experiment。
5. 复用已有 `.streamlit/secrets.toml` 的 Console URL、Key、Agent Control 端点、PostgreSQL、Embedding 等共享设置；新增**与 Healthcare 不重名**的 Project、Agent Stream、Experiment Group，不修改旧 Demo 的租户资源。
6. 为 Cisco SE 增加本地可运行的只读 CSV Exporter，从 Splunk AO 拉取**真实**的模型、质量、Token、成本、时延和 Trace 明细；形成可直接交给另一个仓库消费的 CSV，提供字段说明与完整性校验。
7. 更新本仓库 README 的第 **4.2** 和第 **5** 节，并按需同步第 4.3、5.1、安装/操作索引与 `documentation/VALIDATION.md`。补足有实际意义的自动化测试与手动验收步骤。

### 1.2 明确不在本次实现（Out of scope）

- 不创建、部署、打包 Splunk Enterprise App，不编写 Dashboard Studio JSON、XML、SPL 可视化或跨仓库自动部署；这些由 `splunk-galileo-dashboard` 的**后续独立任务**完成。
- 不在本任务实现 Cisco SE 场景的幻觉注入按钮、Prompt Injection、安全控制策略演示、PII 脱敏、SQL 防护、Chaos 故障、外部实时竞品搜索或自动采购建议；只将其放入 README Roadmap。
- 不改写 / 删除 Healthcare 的演示场景、数据、Project、Stream、Control、Experiment、测试集或现有 `.streamlit/secrets.toml` 配置。
- 不将本任务扩展为 Multi-Agent、多厂商完整产品库、全网爬虫、复杂知识图谱、独立 Web UI 或 Kubernetes 部署。
- 不在实现中自行调用收费的模型生成“预计准确率/预计成本”并冒充真实 Experiment；真实采集指标只从正式执行产生的 Trace / Scorer 获取。

### 1.3 必须打通的最小演示链路

```text
Streamlit -> 选择 Cisco SE Domain -> 真实产品技术问题
          -> LangGraph Agent -> RAG Tool -> 同一 pgvector 知识库
          -> 实际模型生成回答（可核对来源）
          -> Splunk AO Trace / Span

Cisco SE 同一 Dataset + 同一知识库 + 同一 Evaluators
          |-- Experiment A: gpt-5-nano
          `-- Experiment B: gpt-6.1-sol
          -> Ground Truth / Context / Tokens / Cost / Latency
          -> 只读 CSV Exporter
          -> data/cisco_se_model_economics.csv
          -> 交给另一个仓库建设 Splunk Enterprise Dashboard（本次到此为止）
```

## 2. 目录、配置和租户隔离

### 2.1 建议实现目录

```text
domains/cisco_se/
  config.yaml
  system_prompt.json
  dataset.csv                        # 现有 Experiment 所需 input,output
  dataset_sources.yaml               # 题目 ID / 厂商证据 / 来源 / 版本，供人工验收
  docs/
    qa.csv                           # 真正进入 pgvector 的结构化官方技术事实
    source_manifest.yaml             # 官方来源 URL、章节、核验时间、型号，原则上不直接向量化
  tools/
    __init__.py
    logic.py
    schema.json

scripts/
  export-cisco-se-economics           # 或相同作用的 .py + 可执行包装器
  run-cisco-se-ab                     # 建议：顺序启动两个独立 Experiment 的便捷入口

documentation/
  CISCO_SE_MODEL_ECONOMICS_CSV.md     # CSV schema、指标口径、运行/检查方法
  VALIDATION.md                       # 既有验收记录后追加新 Domain 小节

tests/
  test_cisco_se_domain.py             # 可拆分为少量聚焦测试
```

目录结构是建议而非强制接口：允许为减少重复适度调整，但必须保留新 Domain 标准四件套 `config.yaml`、`system_prompt.json`、`tools/schema.json`、`tools/logic.py`，以及现有 Experiment 支持的 `dataset.csv`。**不要直接 `cp -R healthcare` 后留下患者、药物、删除病历、Healthcare Control 等行业残留。**

### 2.2 使用现有共享 TOML，而不是创建第二套密钥

请复用当前 `.streamlit/secrets.toml` 的真实参数：OpenAI Key、Splunk AO Console/API/Agent Control、PostgreSQL 密码、Embedding、TLS 等。**这个 TOML 位于仓库根下的 `.streamlit/`，不是 `domains/healthcare/` 的私有 TOML。** 不复制、提交或重建它。

在 `domains/cisco_se/config.yaml` 中明确配置以下**建议固定名称**：

```yaml
domain:
  name: cisco_se
  description: "Cisco presales technical advisor: Cisco/H3C public data-center switch specifications"

galileo:
  project: "splunk-ao-golden-demo-cisco-se"
  log_stream: "cisco-se"

# Experiment Group 的目标显示名：Cisco SE Model Economics
# 这不是凭空假定支持 config.yaml 下的某个 SDK 字段；请按真实 SDK 契约实现或读取。
model:
  hosted_default_model: "gpt-5-nano"
  hosted_additional_models:
    - "gpt-6.1-sol"
  # 不要为了复制 Healthcare 配置而发送 GPT-6.1 Sol 不支持的参数。
rag:
  enabled: true
  top_k: 3
```

最终完整 YAML 的其他必要字段（`ui`、`tools`、`vectorstore` 等）按 `DomainManager` 契约补齐，不必原样使用以上示意结构。

具体租户隔离要求：

| 对象 | 目标名称 | 要求 |
|---|---|---|
| Splunk AO Project | `splunk-ao-golden-demo-cisco-se` | 与现有 `splunk-ao-golden-demo` 分开；可由有权限的 SDK 创建或由管理员预创建 |
| Agent / Log Stream | `cisco-se` | 属于上述新 Project；不得写入 `healthcare` stream |
| Experiment Group | `Cisco SE Model Economics` | 在新 Project 内可见且名称明确；不得与 Healthcare 的 Group 混用 |
| Experiment A | `Cisco SE Model Economics - gpt-5-nano - <run标识>` | 记录精确模型、Dataset version、日期/标识 |
| Experiment B | `Cisco SE Model Economics - gpt-6.1-sol - <run标识>` | 同一 Dataset ID/version，使用另一模型 |
| 本地 CSV | `data/cisco_se_model_economics.csv` | 不覆盖 Banking 文件；默认路径可自定义 |

`setup_env.py` 已允许通过 `galileo.project` / `galileo.log_stream` 进行 Domain 特定覆盖；使用这个机制，而不是为了新场景去修改共享 TOML 中的全局默认 Project。确保 Project/Stream 的新建、可见性和权限在真实租户已验证。

**Experiment Group 的 API 不得凭猜测实现。** 先查看实际安装的 Splunk AO/Galileo SDK 与本项目 `run_experiment` 的真实 Group/Run 语义；如果默认按名字归组，验证 Group 的实际显示名和 ID；若须显式创建/指定 Group，则使用 SDK 支持的方式实现并回读校验。不能只在 Experiment 名称里出现该字符串就宣称建成了 Group，也不能静默退回 Healthcare Group。

## 3. 公开产品资料与首批 RAG 知识

### 3.1 选用产品与官方来源（已预选，实施时再核验）

以**具体 SKU**为对象，不把“N9300D 系列”“N9300E 系列”当作所有成员参数相同的型号。首批只做 400G 与 800G 对比，避免选取没有官方数据表支撑的竞品指标。

| 厂商 / 建议型号 | 首批可验证事实方向 | 官方来源（实施时记录页面日期、章节与取证时间） |
|---|---|---|
| Cisco **N9332D-H2R**（400G） | 32 × 400G QSFP-DD；1RU；25.6 Tbps；80 MB on-die buffer + 8 GB HBM；ECMP 最高路径数 | [Cisco N9332D-H2R Switch Data Sheet](https://www.cisco.com/c/en/us/products/collateral/switches/nexus-9000-series-switches/nexus-9332d-h2r-switch-ds.html)（更新 2026-07-15） |
| Cisco **N9364E-SG2-Q / N9364E-SG2-O**（800G） | 64 × 800G；Q=QSFP-DD、O=OSFP；2RU；256 MB on-die buffer；102.4 Tbps **交换带宽（按厂商描述）** | [Cisco N9364E-SG2 Switches Data Sheet](https://www.cisco.com/c/en/us/products/collateral/switches/nexus-9000-series-switches/nexus-9364e-sg2-switch-ds.html)（更新 2026-07-31） |
| H3C **S9827-64E**（800G） | 64 × QSFP-DD800；2U；型号专属电源/外形规格 | [H3C S9827 Series Data Center Switches](https://www.h3c.com/en/Products_and_Solutions/InterConnect/Switches/Products/Data_Center/Aggregation/S9800/H3C_S9827/) |
| H3C **S9827-64EP**（800G） | 64 × OSFP800；4U；与 64E 的接口类型与机架高度差异 | [H3C S9827 & S9857 Hardware Information and Specifications](https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Product_Literature/Hardware_Information___Specifications/H3C_S-19215/202508/2614982_294551_0.htm)（5W102） |
| H3C **S9827-128DH**（400G） | 128 × QSFP112；型号与机架尺寸，必要时查阅原厂端口章节核实 400G 模式 | 同上两份 H3C 官方文件 |

备注：**同为 64 个 800G 端口 ≠ 产品全面等效**。交换容量、转发速率、缓存、功耗、RoCE、ECMP、软件版本、业务特性必须分别核对；厂商的 `switch bandwidth`、`forwarding capacity`、单向/双向吞吐率也不能在未经核对时直接当成同一口径比较。

应把每条官方事实精简、准确地整理进 `docs/qa.csv`（或等效、可检索的短文档），每条保留 `vendor`、`sku`、`attribute`、`value`、`unit`、`source_url`、`source_title`、`source_section`、`source_updated_at` / `verified_at` 等元数据。**不要整段复制大篇受版权保护的技术资料，也不要把引用 URL 当成模型一定阅读过的证据。**

注意当前 `helpers/setup_vectordb.py` 的分支：**`docs/qa.csv` 存在时走 `_build_qa_documents()`，不会同时通过 `_load_and_split_generic()` 导入旁边的 PDF/Markdown 材料。** 因此本任务建议采用轻量、结构化的官方事实语料作为唯一主知识库，并扩展其 metadata 映射；不要把大量 `.md` 放进 `docs/` 却从未向量化。若增加多文件导入，必须改变 loader 并用检索测试证明实际入库。

### 3.2 Dataset：建议十条题目与参考答案

`domains/cisco_se/dataset.csv` **必须保留现有 SDK 使用的 `input,output` 两列**（UTF-8，使用合规 CSV 引号；`output` 即 Ground Truth）。以下是**实施候选内容**。Codex/Copilot 必须对上述官方来源再次核验后写入真正 CSV；题目若无法证实就替换，不得保留未经核实的数字。

| ID | 建议 input（可按场景略作措辞优化） | Ground Truth 必须包含的要点 / 检查来源 |
|---|---|---|
| Q01 | Cisco N9332D-H2R 有多少个 400G 端口？机架高度和交换带宽是多少？ | **32 × 400G QSFP-DD；1RU；25.6 Tbps**（Cisco N9332D-H2R Data Sheet，Overview） |
| Q02 | Nexus N9332D-H2R 的 on-die buffer 和 HBM 各有多大？ | **80 MB on-die buffer；8 GB HBM**；不可把两者混为一个普通片上缓存值（Cisco N9332D-H2R Data Sheet） |
| Q03 | N9332D-H2R 支持的 ECMP 最大路径数是多少？ | **128**；明确是该型号数据表的最大 ECMP paths，不等于其他 Nexus 型号（Cisco N9332D-H2R Data Sheet，Performance/Scalability） |
| Q04 | Cisco N9364E-SG2-O 提供多少个 800G 端口，使用什么接口形态，机架高度是多少？ | **64 × 800G OSFP，2RU**（Cisco N9364E-SG2 Data Sheet） |
| Q05 | Cisco N9364E-SG2-Q 和 -O 的 800G 接口形态有什么区别？ | **Q 是 64 × 800G QSFP-DD；O 是 64 × 800G OSFP**；不要把两者写成同时具备两类物理端口（Cisco N9364E-SG2 Data Sheet） |
| Q06 | Cisco N9364E-SG2 的 on-die buffer 和数据表中的 switch bandwidth 分别是多少？ | **256 MB fully shared on-die buffer；102.4 Tbps switch bandwidth**；保留厂商原始术语（Cisco N9364E-SG2 Data Sheet） |
| Q07 | H3C S9827-64E 有多少 800G 端口、什么接口形态和机架高度？ | **64 × QSFP-DD800；2U**（H3C S9827 官方产品页、硬件规格） |
| Q08 | H3C S9827-64E 和 S9827-64EP 在 800G 物理接口与机架高度上有什么区别？ | **64E：64 × QSFP-DD800、2U；64EP：64 × OSFP800、4U**（H3C S9827 官方产品页、硬件规格） |
| Q09 | 如果只比较 800G 端口数量及接口类型，Cisco N9364E-SG2-O 和 H3C S9827-64EP 有何异同？ | **两者各 64 个 800G OSFP 端口；Cisco 2RU，H3C 4U**；只比较这些可验证维度，不宣称总体性能等效（Cisco / H3C 官方资料） |
| Q10 | “Cisco N9332D-H2R 和 H3C S9827-64E 都是 64 端口 800G 交换机”，这句话正确吗？ | **不正确**；Cisco 型号是 **32 × 400G**，H3C S9827-64E 是 **64 × 800G**；清楚识别型号和速率（Cisco / H3C 官方资料） |

任务执行者可将题目设为中英文混合，但应保证各模型回答的验收逻辑不依赖“字面上逐字一致”；Ground Truth 应是简洁且可验证的技术事实，而不是长段营销话术。`dataset_sources.yaml` 可记录 `Q01...Q10` 与 `source_url`、`source_section`、`verified_at` 对应关系供人工追查，不必传入现有两列 Dataset API。确保题目 ID / 输入匹配关系可通过稳定 hash 校验。

### 3.3 Agent 的真实 RAG 行为要求

- 新 Domain 的系统指令应是售前技术顾问：**默认先检索，再基于检索资料回答**；区分型号、接口、单位、版本；能指出两个厂商事实，但不臆造竞争优劣。
- 只做**只读知识检索** Tool，不引入患者 SQL、删除动作或会改变远端系统状态的工具；沿用 LangGraph Agent 及现有 Callback。允许编写最少量的 Domain Tool 适配。
- 输出应给出可追溯来源 URL/标题或可读引用。当前 `DomainRAGSystem.search()` 最终返回 `result["answer"]`，容易丢失 `source_documents` 元数据：要为 Cisco SE 打通 **Retriever → 原始 chunk / metadata → RAG Tool 输出 → 最终答案** 的可见性，并在 Splunk AO Span 中核查实际检索文档，不只看模型编写的“来源”。改动应兼容旧 Domain。
- 同一请求不需要多个检索型 Tool 的重复调用。如果保留通用 `retrieve_cisco_se_documents`，就不再添加内容等价的第二个 `search_xxx` Tool；如为演示更可控而采用独立 Tool，需证明其在 Callback 和 Trace 中可见。
- 对无法在当前知识库确认的事实，应明确表示无法核实，而不是推测；对模糊 SKU 应先澄清或指出型号差异。
- 验收时随机选择至少两条非按钮预置的同义自然语言问题，确认仍发生**真实向量检索**与模型生成。不能仅按题目字符串匹配预置答案。

## 4. 模型 A/B 实现与公平性控制

### 4.1 模型标识与兼容性（关键阻塞点）

| 显示名 | 实际 API model ID | 位置 |
|---|---|---|
| GPT-5 nano（Model A） | `gpt-5-nano` | Domain 模型列表 + Experiment A |
| GPT-6.1 Sol（Model B） | `gpt-6.1-sol` | Domain 模型列表 + Experiment B |

**特别注意 OpenAI API 兼容性：**截至本文编制时，OpenAI 官方 GPT-6 迁移文档说明：`gpt-6.1-sol` 的 **tool calling 应使用 Responses API**；Chat Completions 仅用于不带工具的请求，而且 `reasoning.effort=none/minimal` 不被该模型支持。模型开启 Reasoning 时不能发送不支持的 `temperature`、`top_p` 等参数。见：<https://developers.openai.com/api/docs/guides/latest-model>。

现有 `helpers/llm_utils.py` 通过 `ChatOpenAI(**kwargs)`，主 Agent 随后 `.bind_tools(self.tools)`。**不要仅把 `gpt-6.1-sol` 加入 YAML 就声称支持成功。** 必须先核对当前锁定的 `langchain-openai`、OpenAI Python SDK 与 `GalileoCallback` 是否支持所需的 Responses 模式及工具调用、消息格式、Token Usage；采用**对现有 Hosted 模型最小侵入且向后兼容**的实现。必要时隔离 GPT-6.1 Sol 的适配分支，避免破坏 Healthcare 当前 OpenAI 路径。

要求：

1. 真实调用两模型，至少分别完成一次 **包含工具调用的 RAG 查询**；识别和验证精确返回的模型 ID、Tool Call、Retriever、LLM Span、输出内容。
2. 仅在确认 SDK 能正确插桩后启用 Responses 模式；若需要升级 `langchain-openai` 等依赖，先做锁文件差异评估与 Healthcare 回归，不允许无边界升级整个 Python 环境。
3. Reasoning Effort 为模型独立、显式且可记录的配置；首轮优先选择可运行且较低开销的共同设置（如支持时用 `low`），不要强行给不支持的模型设置 `none`。模型不支持的采样参数必须省略；**记录实际配置**，不要假装模型内部计算成本相同。
4. 模型或 Key 不可访问时 **fail fast**，给出可读诊断；不得偷偷切换为其他 GPT、Ollama、Mock 或缓存答案。

### 4.2 A/B 的固定条件

**必须固定：**

- 相同的 `dataset_id`、**dataset_version**、每个题目的 `scenario_key`、Ground Truth 文本；最好同时记录 Dataset 内容 hash。
- 相同的系统 Prompt / Tool schema / Agent Graph / RAG 编排 / `top_k` / chunking / 文档版本及检索索引。
- 相同 Embedding provider、Embedding 模型、向量 Collection，且各 Trace 中可核查。**禁止在 A/B 过程中无提示地自动回退到其他 pgvector index**：可在新 Domain / Experiment 的受控执行路径添加 strict index 模式，不影响其他 Domain 的默认行为。
- 相同的 Eval 列表和 Judge 配置（Evaluator 是第三方/独立的评判机制，不要因切换应用模型自动改变 Judge 模型）。
- 相同的 Control/Chaos 状态；本次对比默认没有演示性故障注入，没有故意错误答案、人工修改输出或 Steer 重试。如果已有 Control 影响模型结果，要从 Trace 记录并使对应样本不计入可比样本。
- 每道题独立新会话上下文，防止 Model A/B 的前一题内容泄漏；每次保存精确 model ID、SDK/API 模式、reasoning effort、运行时间和代码版本。

**允许自然不同：**两模型自行选择 Tool Call 次数、Token 量、推理步骤和响应长度。这些本就是端到端 Agent 对比的一部分；应**记录而不是偷偷人为拉齐结果**。展示时说清楚这是 *End-to-End Agent A/B*，不是单独的纯模型能力 Benchmark。

### 4.3 Experiment 工作流

保持 Streamlit 原有的 `Experiments -> Dataset Setup -> Experiment Configuration -> Run Experiment` 路径可用。用户通过侧边栏选择 Model A、运行 Experiment A；再切为 Model B、选择**同一云端 Dataset 及版本**运行 Experiment B。实验名称应带模型和 run 标识；新 Group 必须能在 Splunk AO UI 中明确找到。

建议新增一个**可选但推荐的 CLI 便捷脚本** `scripts/run-cisco-se-ab`：执行前检查 Project、Group、Dataset、知识库、模型可用性，再顺序运行 A 与 B；复用 `experiments/experiment_helpers.py` 或 SDK，不另建第二套 Agent。两个 Experiment 仍各自独立，不人为混合两模型的 Trace。命令建议如下（具体参数按现有项目习惯实现并在 README 写实）：

```bash
# 首次建库（新 Domain 数据必须真实进入 pgvector）
python helpers/setup_vectordb.py cisco_se

# GUI 可单独执行两次 Experiment；CLI 则顺序执行两模型
./scripts/run-cisco-se-ab
```

Experiment 默认尝试 **Ground Truth Adherence** 和 **Context Adherence** 等当前租户确实可用的原生 Evaluator；保留必要的统一质量指标。**不要假设任意新 Judge 在租户中已配置或自动具有权限**。执行时查询并核对当前租户可用 Scorer，在文档中列出真正启用的名称、ID 与计算口径；如暂时缺少评分权限，记录阻塞，不输出虚假分数。

### 4.4 Token、Cost、Latency 的真实性与边界

- 从模型/SDK 返回的真实 Usage 和平台 Trace/Span 读取 `input_tokens`、`output_tokens`、`total_tokens`，其中 reasoning tokens、cache input tokens 若存在应按平台语义归入并另列，避免漏计或二次合计。
- 使用 **Splunk AO 平台实际计算的应用 Trace Cost** 作为主要 `trace_cost_usd`；不能从公开价格表反推后填充“平台实际成本”。Judge/Evaluator Cost 单独字段，不能混入应用成本。若 Cost 缺失，输出空值、原因/状态标志，不默认为零。
- Trace 真实持续时间从后端或可验证的单次实际耗时取得；区分每条请求 wall-clock latency 与完整测试集总耗时，后续 Dashboard 才能正确计算平均 / P95。
- 使用真实完成状态、异常与错误 Span；失败或超时不可被当成成功评分样本，也不可因无成功 Span 而被隐藏。
- 验证最终**根 Trace**已经包含正确的 Dataset input、Ground Truth、实际 output、子 Span、应用模型以及 Token/Cost；不能只凭 Experiment 对象存在就宣布完成。

## 5. CSV Exporter：实现与数据契约

### 5.1 编写方式

参考 `alicloud-ack-byocni/scripts/export-banking-cn-economics` 的**通用方法**，不要直接复制 Banking 专有代码。该脚本依赖 **Kubernetes Pod + Banking Multi-Agent Supervisor Span + 特定 SDK 环境**；而 Golden Demo 当前是 **macOS + Single Agent + Hosted OpenAI + splunkse**。新导出器应在本地项目 Python 环境运行，依照本项目实际 SDK 与 Console API 契约、权限实现只读查询。

```bash
./scripts/export-cisco-se-economics
./scripts/export-cisco-se-economics --output /absolute/path/cisco_se_model_economics.csv
# 可选 --project / --group / --prefix / --experiment-ids，只能定位本新场景；默认绝不导出 Healthcare
```

操作要求：

1. 读取现有 `.streamlit/secrets.toml`（通过已有配置帮助函数）；不使用 Kubernetes、kubectl、其他仓库 `kup.conf` 或另一个环境的 API Key。
2. 只导出新 Project 下目标 Group 的 Experiment，查询**全部必要的根 Trace 和子 Span**；支持分页、有限重试、限流处理和清晰错误信息。
3. **不触发任何 LLM / Experiment / Control 执行**，不对云端作写操作；输出原子写入（查询/校验失败不覆盖之前有效 CSV）。
4. CSV UTF-8、LF、首行为 header；每个根 Trace 一行，唯一键为 `experiment_id + trace_id`。长文本的换行统一处理为 CSV 合法转义或字面量 `\\n`，并在数据契约中说明，以便 Splunk `inputlookup` 稳定读取。
5. 输出有值数据来自平台读回；缺失保留空值；不泄露 Key、Secret、配置中的个人信息。允许命令行输出汇总和可比性警告。

### 5.2 建议的最小通用字段

名称尽量沿用 Banking CSV 以减少未来 Dashboard 适配工作，但废除无关的 `supervisor_*` 字段。最终在 `documentation/CISCO_SE_MODEL_ECONOMICS_CSV.md` 明确每一列的类型、来源、空值与聚合口径。

| 类别 | 字段（示意，建议保持名称） | 要求 |
|---|---|---|
| 身份 | `schema_version`, `exported_at_utc`, `project_name`, `experiment_group_name`, `experiment_id`, `experiment_name` | 标识同一次导出的每一个独立 Experiment |
| 模型 | `application_model`, `model_provider`, `reasoning_effort` | 不能混入 Judge 模型；如一个 Trace 包含多个应用 LLM ID，应列明并校验 |
| Dataset | `dataset_id`, `dataset_version`, `dataset_hash`, `scenario_key`, `scenario_input`, `ground_truth`, `generated_output` | 两模型按同一 `scenario_key` 配对；哈希/版本一致才可比 |
| 质量 | `ground_truth_adherence_score`, `ground_truth_adherence_pass`, `ground_truth_adherence_scored`, `ground_truth_adherence_rationale`, `context_adherence_score` | 区分 Judge 未完成、无法评分、判失败，不把空值算成 0 |
| Judge | `judge_model`, `judge_input_tokens`, `judge_output_tokens`, `judge_cost_usd` | 与应用成本分开；缺失值不得补零 |
| 效率 | `trace_duration_seconds`, `trace_input_tokens`, `trace_output_tokens`, `trace_total_tokens`, `trace_cost_usd` | 优先使用平台聚合的真实指标，分别读取与校验 |
| 工作流 | `llm_call_count`, `tool_call_count`, `retriever_call_count`, `span_count`, `error_span_count` | 按 Single-Agent 的真实 Span 类型计数 |
| 数据可信度 | `trace_status_code`, `trace_complete`, `quality_ready`, `cost_ready`, `comparison_ready`, `comparison_warning` | 有任何实质缺失则不能标记完整可比 |

`dataset_hash`、`model_provider`、`reasoning_effort` 等字段若后端无原生字段，可以来自**运行时已记录的非敏感 Experiment 元数据**，或明确的本地实验 manifest，须保证与 Trace/Experiment ID 一一对应，并写明数据血缘；不可在导出阶段主观猜测。

`comparison_ready=1` 的基本条件：该 Trace 成功完成、输入/输出与子 Span 齐备、应用模型正确、关键 Token/Duration/Cost 均有有效值、核心 Judge 已成功评分、Dataset 版本/hash 与配对计划一致。为避免未完成评分的实验无法导出，**允许输出 `comparison_ready=0` 的真实行**并给警告，但 Dashboard 不得将其默认作为有效比较。可以额外标记 `quality_ready` 和 `cost_ready`，便于按用途分析。

### 5.3 数据聚合与比较规则

- 分析基本粒度为 **Experiment**：按 `experiment_id` 聚合，不把同一模型不同日期的多次测试静默合并。
- 仅当模型 A 与 B 的 Dataset 身份/版本/hash 以及 `scenario_key` 全部一致，才对相同题目进行逐项配对；差异应给警告。
- Ground Truth 通过率 = `sum(ground_truth_adherence_pass) / sum(ground_truth_adherence_scored)`，仅统计已完成的评分；同时显示通过数与已评分数，避免误导。
- 单个 Experiment 总成本 = `sum(trace_cost_usd)`（仅统计有效应用 Trace）；Judge 费用另计。**每个合格回答的成本** = 有效应用总成本 / 合格回答数量（分母为零返回空值）。
- 平均 Latency / P95 应基于每条有效 `trace_duration_seconds` 计算；**不要用全实验总耗时冒充每条响应时延**。
- 两个模型 Tokenizer/Reasoning 实现不同，绝对 Token 数是服务端计费单位，比较时应以质量和费用作联合解释，不将 Token 数直接等同于“语义详细程度”。

### 5.4 CSV 验收

- 可以在 Splunk AO 找到对应 Group 中两次真实 Experiment，每个目标 Dataset 题目都能映射到唯一 `trace_id`；导出 CSV 的 `(experiment_id, trace_id)` 无重复。
- 能导出至少两个模型的真实结果（如权限不足，代码仍须可运行到明确的权限/模型错误位置）；行数 = 实际已取得的 Experiment Trace 数，不得静默丢失失败行。
- Token/Cost/Latency 不可由假数据替代；Judge 费用与应用费用未混合；缺失字段状态清楚。
- CSV 经 `csv.DictReader` 读回、列校验、数值类型校验、唯一性校验和跨模型配对校验；`--output` 指向指定目录有效；出错不损坏旧文件。
- 对比结果在当前仓库只需输出 CSV + 一个文本摘要（Model A/B、各自 Experiment、通过率、总成本、总 Token、平均时延、有效样本数）。**不要在本次生成 Splunk Dashboard。**

## 6. README、演示手册及 Roadmap 的改动要求

### 6.1 README 第 4.2 节：保留原有通用说明并补充 Cisco SE 实例

将原标题：

`### 4.2 建立新 Domain`

改为：

`### 4.2 建立新 Domain 和新 Demo 内容`

（若需完全遵从既有标题无空格风格，可写 `### 4.2 建立新 Domain和新Demo内容`，保持 Markdown 层级即可。）**保留第 4.2 节现有通用 `telco` 示例及适用的一般 Domain 建立方法**，补充清楚的 Cisco SE 实际实现与使用步骤，包括：

- 新 Domain 的目标、与 Healthcare 的区别、公开知识范围、模型 A/B；
- 实际目录结构、共享 TOML 与专属 Project/Stream/Experiment Group；
- 官方资料及其维护原则、知识入库命令、加载后检查；
- 创建 / 选择相同 Dataset、运行双模型、导出 CSV 的真实命令和必要 UI 操作；
- 哪些部件自动发现，哪些必须显式配置 / 云端创建；
- 新 Demo 的验收项、常见报错，以及**不影响现有 Healthcare** 的说明。

如果新 Domain 与现有“复制 Healthcare 并建立关系业务表”的通用做法不同，应明确解释：**本次是只读技术知识 RAG 场景，不需要患者/客户表和可写 SQL Tool。** 不要为套用模板而引入没有业务意义的数据库操作。

### 6.2 README 第 5 节：新增可实际照做的 Model Economics Demo

保留标题 **`## 5. 演示：标准流程与深入场景`**，保持现有 5.3 标准 15 分钟及 5.4 深入 30 分钟 **Healthcare 主线不变**。建议在 5.5 后追加：

`### 5.6 Cisco SE：双模型 Model Economics 对比（新增）`

新增内容必须包含如下**人类可直接照做**的演示脚本，分为准备与现场操作：

1. **准备**：启动原应用、确认 Cisco SE 选择和 pgvector、检查新 Project/Stream/Group、确认两个模型真实可用、固定 Dataset / Embedding、确认故障注入关闭、准备好两个已完成或可运行的 Experiment。
2. **Act A — 业务问题**：用 Cisco `N9332D-H2R` 与 H3C `S9827-64E` 的技术问题展示真实 RAG、来源与 Span。话术重点：售前回答必须精确到 SKU、有官方依据。
3. **Act B — 相同测试集**：在 Splunk AO Experiments 中明确展示 **同一 Dataset 和相同 Judge**，分别以 `gpt-5-nano` / `gpt-6.1-sol` 运行；强调仅应用 LLM 发生变化。
4. **Act C — 质量与经济性**：展示每个 Experiment 的 Ground Truth、Token、Cost、Latency 及代表性 Trace；**不预先宣称一定哪种模型更好、更省钱**。说明 Judge 异步完成、Cost 可能暂时未生成。
5. **Act D — 导出**：执行实际 CSV 命令，展示字段校验、两模型对齐、导出路径；说明 Splunk Enterprise Dashboard 将在**另一个仓库的后续任务**实现，本次演示止于可消费的数据。
6. **失败与回退**：模型/Key/SDK 不支持、RAG 未命中、评分 pending、Cost 为空、Dataset 版本不一致时的现场解释和处理；已经完成的历史样本可以作为备选展示，但必须标明采集时间，不能冒充本次实时运行。

按现有文档风格给每一幕写简短**操作、现象、Console 位置、建议话术、成功标志、未达预期处理**。新增场景的建议演示时长可为 8–12 分钟（仅讲解，不包括完整跑完所有异步评分），具体以实测为准。提供 2–3 条适合复制的例题，避免长篇产品选型论述。

### 6.3 其他文档核对与 Roadmap

- README 目录/索引、Domain 列表、第 4.3 配置表、5.1 能力矩阵与适用的 Troubleshooting 段落同步新增 Cisco SE 信息，不要让文档仍写“只有 Healthcare 可进行本场景的 Experiment”。
- `documentation/VALIDATION.md` 增加“Cisco SE Domain / Model A-B / CSV Export”单独小节，写明命令、模型、Dataset、索引、Experiment ID/Group、成功/失败状态与残余问题。真实未验收时明确标 **Not verified**，不能套用 Healthcare 的 Demo-ready。
- 将未来想做但**本次不做**的内容放入 README 既有的 Roadmap 区域，建议包含：Cisco SE 领域专属 Hallucination、Document-based Prompt Injection、Agent Control 策略演示、Chaos、长期官方资料版本更新、自动化资料摄入 / Citation Accuracy 评分、Fixed-Context 模型对比、Splunk Enterprise Dashboard（明确在另一仓库单独实施）。
- 增加 CSV 契约文档，但不要在 README 复制几十列详细 schema；README 写运行路径和简要解释，详细字段留在 `documentation/CISCO_SE_MODEL_ECONOMICS_CSV.md`。

## 7. 开发步骤与完成判定（Definition of Done）

### 阶段一：静态检查与实现

- [ ] 扫描现有 Domain / Model / RAG / Experiment / SDK 运行链路；核实 `gpt-6.1-sol` Responses Tool Calling 的可执行方式。
- [ ] 新 `domains/cisco_se/` 被 `DomainManager.list_domains()` 自动发现，其他 Domain 没有变化。
- [ ] 有可重建、可检索、带来源的 Cisco + H3C 技术资料；没有依赖伪造的固定回答。
- [ ] `dataset.csv` 含约 10 条有效 `input,output`，与证据 manifest 一一对应；Ground Truth 数字/型号核对通过。
- [ ] Model A/B 可显式选择；应用通过实际工具调用访问 Responses 兼容模型；Reasoning / 不支持参数处理有针对性测试。
- [ ] 配置指向独立新 Project、Stream、Group，复用共享 Key/Console，不把 Healthcare 配置覆盖。
- [ ] UI 原有 Experiment 仍可使用；至少有顺序执行两模型的明确路径，自动化入口优先。
- [ ] 新 CSV Exporter、数据契约和完整性检测实现；只读、原子写入、缺失指标不造假。
- [ ] README 4.2 / 5.x、Roadmap、CSV 文档和验收记录更新完成，保留原文档结构与中文风格。

### 阶段二：本地测试与回归

至少覆盖：

- [ ] Domain 发现、YAML/Schema/Logic/Prompt Tool 名称一致，无 `healthcare` 行业残留。
- [ ] Dataset CSV 两列及非空行校验、来源 URL 有效、事实校验、相同 Dataset/版本比对。
- [ ] 新 `qa.csv` 带来源元数据正确嵌入 pgvector；Retriever 能找出两家厂商至少各 2 个真实文档片段。
- [ ] 严格模式不允许 A/B 在 Provider/Embedding/index 不同的情况下偷偷运行成功。
- [ ] GPT-6.1 Sol 的 Responses / Tool Calling 参数测试；GPT-5 nano 路径和 Healthcare 旧 Hosted 路径回归。
- [ ] 导出器针对分页、重复 Trace、缺少模型、Cost null、Judge pending、不同 Dataset version、API 错误、原子文件写入进行单元测试（可用 mock 数据，但**mock 只用于自动化测试，不作为正式演示结果**）。
- [ ] 运行仓库现有适用的 `pytest` / `scripts/check-demo.sh`（先查看 CLI 帮助与现有依赖；不要凭猜测使用不存在的配置文件）；至少做 Healthcare 模型、RAG 和 Experiment 的关键回归。

### 阶段三：真实在线验收（具备权限时必须执行）

- [ ] `python helpers/setup_vectordb.py cisco_se` 成功建索引，并实测新 Domain 一条 Cisco、一条 H3C 的非预置问法。
- [ ] Console 中有 **`splunk-ao-golden-demo-cisco-se` / `cisco-se`** 的真实 Session/Trace/LLM/Tool/Retriever；`healthcare` Stream 没有新 Cisco SE Trace。
- [ ] Model A 和 Model B 各一次有效 RAG Tool Calling，主模型 ID 正确、官方来源可观察。
- [ ] 两个独立 Experiment 出现在 **`Cisco SE Model Economics`** Group，明确记录实际 Experiment ID、Dataset ID/version/hash。
- [ ] 各题真实 output、适用 Judge 分数、Token 与 Latency 可读回；Cost 不完整的 Trace 不能 `comparison_ready=1`。
- [ ] 导出真实 CSV、读回校验、解释缺失字段；人工核对一条 Model A 与 Model B 的对齐 Scenario、费用和 Judge。
- [ ] 不执行任何 Healthcare 数据清理、Stream 删除、Control 删除或共享租户设置重置操作。

### 阶段四：提交交付说明

执行完成后在回复中提供：

1. 本次新增 / 修改文件摘要，涉及模型适配与知识库的关键设计决策。
2. 实际运行的命令及测试结果（含未运行/失败项目的真实原因）。
3. 官方资料核验表：SKU、事实、来源 URL、核验日期；与 Dataset 题目匹配。
4. 当前实际使用的 Project/Stream/Group 名称、Model ID、Embedding 集合和 Scorer 名称；若已验收，提供真实 Experiment ID/链接。
5. CSV 文件实际生成路径、schema 版本、行数、可比行数、缺失数据说明；不要把导出用的本地私有数据或密钥强行提交仓库。
6. Healthcare 回归结论与残余风险。不要把未实测功能写成 “Demo-ready”。
7. 记录下一仓库的接口：`data/cisco_se_model_economics.csv`、`documentation/CISCO_SE_MODEL_ECONOMICS_CSV.md`；**本次不执行任何 Splunk Dashboard 任务**。

## 8. 实施优先级与技术取舍

如果遇到实际平台权限、模型兼容性或 SDK 限制，按以下顺序确保任务闭环：

1. **P0：两个真实模型都能安全、正确地运行带 Tool 的相同 RAG 任务；模型标识、同一 Dataset 和来源真实。** 若 Sol 无法经当前 SDK 的 Responses 路径工作，这是首要阻塞，不允许通过无 Tool 的伪调用绕过去。
2. **P0：两次真实 Splunk AO Experiment 的信息完整，质量/Token/Cost/Latency 可校验。** 异步 Judge / 平台尚未定价时显式标识不完整，不静默修复。
3. **P0：CSV Exporter 能独立、本地、只读运行，并通过输入输出契约检查。**
4. **P1：优化人类可读的 Trace 引用、提升源资料元数据、命令行便捷封装。**
5. **P1：README、验收记录、回归和可复现性补齐。** 文档和测试属于交付条件，不可因为有一条成功回答就省略。

**工程原则总结**：最小改动；不影响 Healthcare；官方事实可核对；RAG 真检索；双模型真调用；Experiment 真评分；CSV 真数据；平台数据不造假；Splunk Dashboard 不越界。

---

## 附录 A. 官方参考链接清单

1. Cisco N9332D-H2R Data Sheet：<https://www.cisco.com/c/en/us/products/collateral/switches/nexus-9000-series-switches/nexus-9332d-h2r-switch-ds.html>
2. Cisco N9364E-SG2 Data Sheet：<https://www.cisco.com/c/en/us/products/collateral/switches/nexus-9000-series-switches/nexus-9364e-sg2-switch-ds.html>
3. Cisco Nexus 9000 Data Sheet Listing（确认型号及版本）：<https://www.cisco.com/c/en/us/products/switches/nexus-9000-series-switches/datasheet-listing.html>
4. H3C S9827 Series Product Page：<https://www.h3c.com/en/Products_and_Solutions/InterConnect/Switches/Products/Data_Center/Aggregation/S9800/H3C_S9827/>
5. H3C S9827 & S9857 Hardware Information and Specifications 5W102：<https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Product_Literature/Hardware_Information___Specifications/H3C_S-19215/202508/2614982_294551_0.htm>
6. OpenAI GPT-6 Model Migration / Tool Calling：<https://developers.openai.com/api/docs/guides/latest-model>

## 附录 B. 外部项目参考（只读）

- Banking Model Economics Exporter：<https://github.com/highopes/alicloud-ack-byocni/blob/main/scripts/export-banking-cn-economics>
- Banking Model Economics 运行说明：<https://github.com/highopes/alicloud-ack-byocni/blob/main/README.zh-CN.md#export-model-economics-data-for-splunk-enterprise>
- Splunk Enterprise Dashboard 独立仓库：<https://github.com/highopes/splunk-galileo-dashboard>

> **最终范围声明**：交付物是本仓库中的 **Cisco SE Domain、真实双模型 Experiment、真实可消费 CSV、对应文档和测试**。可视化 Dashboard 由用户在另一个仓库以独立任务建设。
