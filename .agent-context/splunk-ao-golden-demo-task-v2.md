# Splunk AO Golden Demo 本地构建与演示化任务书

> 目标仓库：`splunk-ao-golden-demo`  
> 本地工作目录：`/Users/hangwe/Library/CloudStorage/OneDrive-Cisco/dev/splunk-ao-golden-demo`  
> Agent 上下文目录：`/Users/hangwe/Library/CloudStorage/OneDrive-Cisco/dev/splunk-ao-golden-demo/.agent-context`  
> 上游参考项目：`https://github.com/rungalileo/galileo-golden-demo`  
> 当前阶段运行平台：macOS 笔记本  
> 当前 Splunk Agent Observability / Galileo 后端：`https://console.multitenant.galileocloud.io/splunkse`  
> 当前 Evaluator：Splunk AO / Galileo 原生默认 Evaluator（当前由 OpenAI 支撑）  
> 当前阶段原则：**先把 macOS 本地演示做完整、稳定、好讲；未来 Kubernetes、vLLM、自定义 Judge、多后端切换只在结构上预留，不在本阶段实现。**

---

## 1. 任务目标

在本地 macOS 工作目录：

```text
/Users/hangwe/Library/CloudStorage/OneDrive-Cisco/dev/splunk-ao-golden-demo
```

构建一个以官方 `rungalileo/galileo-golden-demo` 为基础、适合 Cisco / Splunk 售前现场演示的 **Splunk Agent Observability（Splunk AO，Splunk 智能体可观测性）Golden Demo**。

最终仓库名称为：

```text
splunk-ao-golden-demo
```

本阶段的目标不是简单“把上游程序跑起来”，而是把它整理成一个 **可重复部署、可重复演示、故事线清晰、操作足够简单、能够系统覆盖应用本身可展示的 Splunk AO / Galileo 功能** 的标准 Demo 项目。

完成后，一个第一次接触本仓库的 SE（Sales Engineer，售前工程师）只需要阅读根目录 `README.md`，即可完成：

1. 在 macOS 上安装与启动 Demo；
2. 正确配置 Splunk AO / Galileo 后端与必要依赖；
3. 理解 Demo 应用本身的架构；
4. 按照标准故事线完成一次完整演示；
5. 知道每一步应该在应用端做什么；
6. 知道随后在 Splunk AO / Galileo Console 中观察什么；
7. 知道这一段演示的业务价值和推荐话术；
8. 能够在不展示复杂代码的情况下，让观众理解 Splunk AO 的核心价值。

---

# 2. 核心原则

## 2.1 以“演示效果”优先，而不是“代码炫技”优先

这是一个面向客户和内部销售团队的 Demo，而不是开发者 Workshop。

因此必须遵循以下原则：

- 能在 GUI（Graphical User Interface，图形用户界面）完成的操作，优先通过 GUI 展示。
- 不要让观众长时间观看 Terminal、Python、JSON、YAML 或 API 调用。
- CLI（Command-Line Interface，命令行界面）主要用于安装、初始化和故障排查，不作为主故事线。
- Demo 操作步骤必须短、明确、可重复。
- 每一步都应当有清晰的“问题 → 观察 → 解释 → 价值”。
- 不要为了覆盖功能而机械地堆功能。
- 不要设计需要大量随机性才能成功的演示。
- 如果某个故障场景可以确定性触发，应优先使用确定性触发方式。
- 演示中出现的故障必须能够稳定复现并在 Splunk AO / Galileo 中找到证据。

## 2.2 README 既是安装手册，也是 Demo Playbook

根目录 `README.md` 不能只写安装方法。

它最终必须同时承担：

- 项目简介
- 应用结构说明
- 工作原理说明
- 当前 Healthcare Domain 的组成与数据流
- 切换/新增 Domain 的标准步骤
- Instrumentation（插桩）原理与本项目实际插桩方式
- macOS 安装指南
- 配置指南
- 启动/停止指南
- Demo 数据说明
- Splunk AO / Galileo 配置说明
- Demo Feature Matrix
- 标准 Demo Storyline
- 每一步操作方法
- 每一步观察位置
- 推荐话术
- Demo 前检查清单
- Demo 后恢复/清理方法
- 常见问题排查
- 未来部署模式预留

README 应成为整个项目的 **Single Source of Truth（单一事实来源）**。

---

# 3. 当前阶段范围

## 3.1 本阶段必须完成

当前版本以 **macOS 单机应用端** 为目标。

应用侧包括：

```text
Streamlit UI
    ↓
LangGraph Agent
    ↓
LLM / Tools / RAG
    ↓
PostgreSQL + pgvector
    ↓
Splunk AO / Galileo SDK
    ↓
console.multitenant.galileocloud.io/splunkse
```

其中：

- Demo App 运行在本地 Mac。
- PostgreSQL + pgvector 可以按上游项目最稳定、最简单的方法在本地运行。
- LLM（Large Language Model，大语言模型）本阶段优先使用上游项目已经支持且能稳定工作的方式。
- Splunk AO / Galileo 后端固定按当前环境配置：
  - `https://console.multitenant.galileocloud.io/splunkse`
- Evaluator 使用当前平台原生默认 Evaluator。
- 不要求在本阶段实现本地 Judge。
- 不要求在本阶段实现 Kubernetes。
- 不要求在本阶段实现 vLLM OpenAI-compatible endpoint。
- 不要求在本阶段实现两个 Galileo/Splunk AO 后端的一键切换。

## 3.2 本阶段明确不做，但结构必须预留

README 以及配置组织必须给未来以下场景保留独立章节和明确位置，但当前不要展开安装步骤：

### Future Option A — Kubernetes

未来应用会部署到社区版 Kubernetes。

预留章节：

```text
Future Deployment Options
└── Kubernetes
```

当前只需要说明：

> Planned / Not implemented in the current macOS demo.

不要在当前主流程中加入 Helm、Deployment、Ingress 等内容。

### Future Option B — vLLM + Qwen Judge

未来 Evaluator 可能使用：

```text
vLLM
  ↓
Qwen3-14B-FP8
  ↓
Custom LLM-as-a-Judge
```

其中 LLM-as-a-Judge（使用大语言模型作为评审模型）将用于定制 Evaluator。

当前 README 只需要预留：

```text
Future Evaluation Backends
└── vLLM / Qwen3-14B-FP8 Judge
```

不要在本阶段安装或配置。

### Future Option C — Multiple Splunk AO / Galileo Backends

未来可能在以下环境之间切换：

```text
https://console.multitenant.galileocloud.io/splunkse
```

和：

```text
https://app.galileo.ai/cisco-demo
```

当前只需要在配置设计和 README 结构上预留：

```text
Backend Profiles
├── splunkse
└── cisco-demo
```

当前默认且唯一实际配置：

```text
splunkse
```

不要为了未来多环境切换而把当前安装流程复杂化。

---

# 4. 上游代码使用原则

以当前官方仓库：

```text
https://github.com/rungalileo/galileo-golden-demo
```

作为代码和 Demo 行为的主要参考。

需要先检查当前 `main` 分支，而不是依据旧文章或旧 commit 盲目修改。

必须理解并尽量保留上游的核心设计：

```text
一个 Streamlit Demo App
        ↓
Domain Manager
        ↓
可配置 Domain
        ↓
LangGraph Single Agent
        ↓
Tools + RAG
```

当前已有 Domain 包括但不限于：

```text
bank
healthcare
insurance
restaurant
```

重点理解：

- 它是一个 Multi-Domain Demo Framework（多领域演示框架）。
- 每个 Domain 使用自己的 Prompt、Tools、RAG 数据、关系型数据和 Galileo Log Stream。
- 当前 LangGraph 实现本质是 Single Agent + Tools + RAG，而不是复杂 Multi-Agent（多智能体）架构。
- 不要在 README 中错误地将它描述成复杂多智能体系统。
- 如果后续增加真正 Multi-Agent 场景，应作为独立能力说明。

如果本地仓库已有代码或用户修改，不得直接覆盖。先检查：

```bash
git status
git remote -v
git log --oneline --decorate -n 10
```

再决定如何同步上游。

建议保留上游 remote，例如：

```text
origin    → 用户自己的 splunk-ao-golden-demo
upstream  → rungalileo/galileo-golden-demo
```

但不要擅自 push 或 rewrite history。

---


# 5. README 中必须解释清楚的应用结构、工作原理与 Domain 机制

README 不仅要告诉演示工程师“怎么启动”，还必须让演示工程师理解这个 Demo **为什么这样工作、数据从哪里来、Trace 为什么能出现、换行业场景时应该改哪里**。

这一部分不能只给代码目录列表，要用面向演示工程师的语言解释。

## 5.1 应用总体结构

README 至少应提供一张简单的逻辑结构图，建议表达为：

```text
Browser
  │
  ▼
Streamlit UI
  │
  ▼
DomainManager
  │
  ├── healthcare
  ├── bank
  ├── insurance
  └── restaurant
  │
  ▼
AgentFactory
  │
  ▼
LangGraphAgent
  │
  ├── LLM
  ├── Domain Tools
  └── RAG
       │
       └── PostgreSQL + pgvector
  │
  ▼
Final Response

同时：

LangGraph / LangChain execution
  │
  ├── GalileoCallback
  └── GalileoLogger
         │
         ▼
Splunk Agent Observability / Galileo
```

README 必须解释：

- `app.py` 是唯一的 Streamlit 主应用入口；
- `DomainManager` 自动扫描 `domains/` 目录；
- 每一个 Domain 并不是一套独立 App，而是同一 Agent Framework 下的一组领域配置、数据和工具；
- `AgentFactory` 根据当前 Domain 创建对应的 `LangGraphAgent`；
- 当前 Agent 的核心形态是 **Single Agent + Tools + RAG**；
- 不是复杂 Multi-Agent；
- Domain 的不同主要体现在：
  - System Prompt；
  - Tool Schema；
  - Tool Logic；
  - RAG 文档；
  - 关系型业务数据；
  - Demo Dataset；
  - Splunk AO / Galileo Project / Log Stream 配置；
  - UI 标题和示例问题。

## 5.2 当前 Healthcare Domain 的组成

README 必须专门解释当前主 Demo Domain：

```text
domains/healthcare/
├── config.yaml
├── system_prompt.json
├── dataset.csv
├── docs/
│   ├── qa.csv
│   └── relational_*.csv
└── tools/
    ├── schema.json
    └── logic.py
```

实际文件名以当前 upstream 为准，不能凭空写不存在的文件。

需要解释每个部分的作用。

### `config.yaml`

至少说明：

- Domain 名称；
- UI 标题；
- 示例 Query；
- Model 配置；
- RAG 配置；
- Tool 列表；
- Splunk AO / Galileo Project / Log Stream；
- Hallucination Demo 配置。

### `system_prompt.json`

说明它定义 Healthcare Assistant 的角色、行为边界，以及什么时候应调用哪些 Tool。

### `docs/qa.csv`

说明这是 Healthcare 的 RAG（Retrieval-Augmented Generation，检索增强生成）知识来源之一。

### `docs/relational_*.csv`

说明这些数据被载入 PostgreSQL，用来模拟患者等结构化业务数据。

### `tools/schema.json`

说明这是 LLM 能看到的 Tool Definition / Function Calling Schema。

### `tools/logic.py`

说明这里实现真正的 Tool 行为，例如：

```text
查询患者
删除患者
知识检索
SQL 执行
```

### `dataset.csv`

说明它主要用于 Splunk AO / Galileo Experiment，而不是在线聊天时的业务数据库。

演示工程师需要理解：

> `docs/` 是 Agent 的业务知识/业务数据来源；`dataset.csv` 是评测用测试集。这两者不能混为一谈。

## 5.3 Healthcare Query 的实际工作流程

README 应使用一个具体例子解释：

```text
User:
Show me data for patient P001.
```

建议画成：

```text
User Input
   │
   ▼
Streamlit
   │
   ▼
Healthcare LangGraph Agent
   │
   ▼
LLM decides to call get_patient_info
   │
   ▼
Tool generates / executes SQL
   │
   ▼
PostgreSQL
   │
   ▼
Tool Result
   │
   ▼
LLM builds final response
   │
   ▼
User
```

同时说明：

```text
GalileoCallback / GalileoLogger
```

会将执行链中的关键步骤记录到 Splunk AO / Galileo。

另一个 RAG 示例应解释：

```text
What is the dosage and common side effects of Lisinopril?
```

大致流程：

```text
User
 ↓
Healthcare Agent
 ↓
RAG Tool
 ↓
pgvector Retrieval
 ↓
Retrieved Context
 ↓
RAG LLM / Main Agent
 ↓
Answer
```

## 5.4 Domain 切换机制

README 必须告诉演示工程师：

> 切换 Domain 通常不需要修改 `app.py`。

因为应用会自动扫描：

```text
domains/
```

中的有效 Domain。

### 切换到已经存在的 Domain

应给出标准步骤，例如：

1. 确认目标 Domain 目录存在，例如：

```text
domains/bank
```

2. 阅读：

```text
domains/bank/config.yaml
domains/bank/system_prompt.json
domains/bank/tools/
domains/bank/docs/
domains/bank/dataset.csv
```

3. 初始化该 Domain 的数据：

```bash
python helpers/setup_vectordb.py bank
```

4. 确认 `config.yaml` 中 Splunk AO / Galileo Project / Log Stream 配置合理。

5. 启动应用。

6. 打开对应 Domain 页面，例如：

```text
/bank
```

7. 至少完成：
   - 一个 RAG Query；
   - 一个 Tool Query；
   - 一个 Trace 检查；
   - 一个 Experiment smoke test。

### 新增一个 Domain

README 必须给出演示工程师一个简洁、可靠的标准流程。

推荐以 Healthcare 为模板：

```bash
cp -R domains/healthcare domains/telco
```

然后依次修改：

```text
1. config.yaml
2. system_prompt.json
3. docs/qa.csv
4. docs/relational_*.csv
5. tools/schema.json
6. tools/logic.py
7. dataset.csv
8. Galileo Project / Log Stream
```

随后执行：

```bash
python helpers/setup_vectordb.py telco
```

需要特别说明：

- Domain 名称应保持一致；
- Tool 名称必须在 Prompt、Schema、Logic、Config 中对应；
- 如果新 Domain 的数据结构超出了现有 `setup_vectordb.py` 已支持的模式，可能需要扩展初始化逻辑；
- 新增 Domain 后应用应由 `DomainManager` 自动发现；
- 不应为了新增普通 Domain 修改 `app.py`；
- 新 Domain 上线演示前必须重新验证 RAG、Tool、Trace、Experiment 和 Agent Control。

## 5.5 Domain 定制的“最小变化原则”

演示工程师换行业场景时，优先修改：

```text
Domain config
Prompt
Demo data
Tool schema / tool logic
Dataset
```

不要优先修改：

```text
app.py
AgentFactory
BaseAgent
LangGraph core
Galileo instrumentation core
```

除非新的场景真的需要新的 Agent 拓扑或新的基础能力。

这样可以保持 Golden Demo 的可维护性和未来 upstream 同步能力。

---

# 6. Instrumentation（插桩）说明与演示要求

Instrumentation 必须成为标准 Demo Storyline 的第一个技术环节。

目的不是展示大量代码，而是先回答观众一个自然问题：

> “Splunk AO 为什么能看到 Agent 内部这些步骤？”

README 需要先用非常简短的方式介绍常见插桩方法，再明确指出本项目实际用了什么。

## 6.1 一般常见的 Agent / LLM Instrumentation 方法

README 推荐用一个简表说明：

| 方法 | 英文名称 | 典型方式 | 适合场景 |
|---|---|---|---|
| SDK Wrapper | Software Development Kit Wrapper，SDK 包装器 | 用观测 SDK 包装模型/客户端 | 快速集成 |
| Decorator | Decorator，装饰器 | 给函数/Agent/Tool 增加装饰器 | 精确控制特定函数 |
| Callback / Handler | Callback / Handler，回调/处理器 | 接入 LangChain、LangGraph 等框架事件 | 框架级自动采集 |
| OpenTelemetry Instrumentation | OpenTelemetry Instrumentation，开放遥测插桩 | 自动或手工生成标准 Trace/Span | 企业统一可观测体系 |
| Manual Logger / Span | Manual Logger / Span，手工日志/Span | 代码中显式创建 Session/Trace/Span | 自定义流程或补充语义 |

这部分只需帮助观众建立概念，不要讲成开发培训。

## 6.2 当前 Golden Demo 实际采用的方式

必须根据当前代码说明，不能笼统写成“使用 SDK”。

当前项目核心 Observability Instrumentation 是：

### 1. LangChain / LangGraph Callback

代码中使用：

```python
from galileo.handlers.langchain import GalileoCallback
```

并将 Callback 放入 LangGraph 执行配置：

```python
callbacks = [
    GalileoCallback(
        galileo_logger=galileo_logger,
        start_new_trace=False,
        flush_on_chain_end=False,
    )
]

self.config = {
    "configurable": {"thread_id": self.session_id},
    "callbacks": callbacks,
}
```

LangGraph 执行时：

```python
result = await self.graph.ainvoke(
    initial_state,
    self.config,
)
```

这使框架执行过程中的 LLM / Chain / Tool 等事件能够被 Galileo Handler 捕获。

### 2. GalileoLogger 管理 Session / Trace 生命周期

本项目还显式创建：

```python
GalileoLogger
```

并围绕 Agent Query 管理 Session / Trace。

README 应解释：

> Callback 负责捕获 LangChain / LangGraph 内部执行事件；Logger 负责把这些事件组织到正确的 Galileo Project、Log Stream、Session 和 Trace 中。

不要把这两种机制错误描述成完全独立的两套插桩。

## 6.3 README 中要展示的代表性插桩代码

标准 Demo 中只展示一个非常短的代表性例子。

优先展示：

```python
from galileo.handlers.langchain import GalileoCallback

callbacks = [
    GalileoCallback(
        galileo_logger=galileo_logger,
        start_new_trace=False,
        flush_on_chain_end=False,
    )
]

self.config = {
    "configurable": {"thread_id": self.session_id},
    "callbacks": callbacks,
}
```

然后解释：

```text
LangGraph
   │
   ├── LLM events
   ├── Tool events
   └── Chain events
          │
          ▼
   GalileoCallback
          │
          ▼
     GalileoLogger
          │
          ▼
 Splunk AO / Galileo
```

演示中不要逐行解释代码。

推荐只讲：

> 这个 Demo 不是在每个 Tool 后面手工写日志。它利用 LangChain/LangGraph 的 Callback 机制，把 Agent 框架内部的执行事件交给 Galileo Handler，再由 GalileoLogger 组织成 Session、Trace 和 Span。这样应用代码侵入很小，但我们仍然能看到完整执行链。

## 6.4 Instrumentation 与 Agent Control 不要混淆

代码中还会看到：

```python
@control(...)
```

以及 Agent Control 相关 wrapper / decorator。

README 必须说明：

> `GalileoCallback` / `GalileoLogger` 主要解决 Observability Instrumentation；`@control` 等机制主要用于 Runtime Guardrail / Agent Control。它们有关联，但不是同一件事。

避免演示工程师把：

```text
Telemetry collection
```

和：

```text
Runtime policy enforcement
```

混为一谈。

## 6.5 Instrumentation Demo 必须短

Instrumentation 环节建议控制在约 1 分钟。

标准操作：

```text
1. 展示应用架构图
2. 展示 GalileoCallback 的几行代码
3. 说明 Callback + Logger
4. 立即回到 UI 发起真实 Query
5. 去 Splunk AO 看对应 Trace
```

核心逻辑：

```text
先告诉观众数据怎么进来
        ↓
再产生一次真实请求
        ↓
马上在 Splunk AO 看到结果
```

不要在一开始就深入 SDK API 细节。

---


# 7. 工程实现要求

## 7.1 本地安装必须可重复

需要确保在一台干净、满足依赖的 macOS 机器上，根据 README 可以完成安装。

至少验证：

```text
Python
Streamlit
LangGraph / LangChain
PostgreSQL
pgvector
Galileo / Splunk AO SDK
Agent Control SDK
```

实际版本要求以当前 upstream `requirements.txt` 和兼容性测试为准。

如果发现上游依赖存在版本冲突：

- 找到最小修改；
- 记录原因；
- 避免大规模重构；
- README 中说明必要的版本约束。

## 7.2 配置文件必须易于演示人员理解

优先保留上游 `.streamlit/secrets.toml` 模式。

必须提供安全的模板，例如：

```text
.streamlit/secrets.toml.example
```

真实密钥不得提交。

`.gitignore` 必须至少覆盖：

```text
.streamlit/secrets.toml
.env
venv/
.venv/
__pycache__/
.DS_Store
```

同时检查是否有：

- Galileo API Key
- OpenAI Key
- AWS Key
- PostgreSQL Password

被误提交。

## 7.3 启动方式必须简单

目标是让日常 Demo 启动尽量接近：

```bash
source .venv/bin/activate
streamlit run app.py
```

如果数据库启动需要 Docker，应在 README 中给出最短流程。

如有必要，可增加简单辅助脚本，例如：

```text
scripts/start-demo.sh
scripts/stop-demo.sh
scripts/check-demo.sh
```

但不要用脚本隐藏关键状态。

`scripts/check-demo.sh` 如实现，建议检查：

```text
Python 环境
PostgreSQL 可达性
pgvector
LLM endpoint
Splunk AO / Galileo API 配置
必要的 Domain 数据
Streamlit 端口
```

---

# 8. Demo Domain 选择

当前以 **Healthcare** 作为优先标准故事线。

原因：

- 患者数据天然适合展示 Tool Calling。
- 医疗知识天然适合展示 RAG。
- PII 风险直观。
- 删除患者记录适合展示 Agent Control。
- 药物剂量适合展示 Hallucination。
- 故障与数据错误容易解释。
- 非技术观众也能快速理解业务上下文。

不要删除其他 Domain。

README 中应说明：

```text
Primary Demo Domain: Healthcare
Additional Domains: Bank / Insurance / Restaurant
```

其他 Domain 可以用于：

- 替换客户行业故事；
- 快速证明框架可复用；
- 备用演示。

---

# 9. README 必须覆盖的 Splunk AO / Galileo Feature

最终 README 需要建立 **Feature Coverage Matrix**。

只记录当前应用实际可以稳定演示的能力。

如果某个功能存在于 Splunk AO 产品中，但当前 Golden Demo 没有集成，不要为了“功能全面”而假装已经支持。

至少验证以下能力。

| Capability | 当前 Demo 应覆盖 | 推荐演示方式 |
|---|---:|---|
| Agent Trace | 必须 | 正常 Healthcare 对话后查看 Trace |
| Span / Step | 必须 | 展开 LLM、Tool、Retriever / RAG Span |
| Multi-turn Session | 必须 | 连续多轮对话 |
| Tool Calling Observability | 必须 | Patient Lookup |
| RAG Observability | 必须 | 医疗知识查询 |
| Retrieved Context | 必须 | 检查 RAG Context |
| Evaluators | 必须 | 查看默认 Evaluator 结果 |
| Hallucination Detection | 必须 | 使用内置 Hallucination Demo |
| Groundedness / Context-related Eval | 应覆盖 | RAG 正常与 Hallucination 对比 |
| Dataset | 必须 | 使用 Healthcare Dataset |
| Experiment | 必须 | 从 Streamlit Experiments UI 发起 |
| Experiment Metrics | 必须 | 查看聚合评估结果 |
| Agent Control | 必须 | SQL Delete / PII / Prompt Injection |
| PRE Control | 必须 | Prompt Injection / Harmful SQL |
| POST Control / Steering | 必须 | Output PII |
| Chaos Engineering | 必须 | 至少演示 2–3 个最有解释力的模式 |
| Tool Failure Diagnosis | 必须 | Tool Instability |
| RAG Failure Diagnosis | 应覆盖 | RAG Disconnect |
| Data-path Error Diagnosis | 应覆盖 | Sloppiness |
| LLM Error Diagnosis | 应覆盖 | Data Corruption |
| Rate-limit / Latency Problem | 可选 | 429 Rate Limit |
| Model Selection | 应说明 | 当前只演示稳定配置；未来模型比较预留 |
| Token / Latency Metrics | 若平台当前可见则覆盖 | 在 Trace / Metrics 中展示 |
| Cost / Tokenomics | 若当前原生 UI 有可靠数据再加入 | 不得凭空宣称 |
| Signals | 仅在当前 Demo 数据能稳定生成时加入 | 需要实际验证 |
| Annotation / Annotation Queue | 不因产品有此功能就强塞入当前 Demo | 如无自然入口则放“扩展能力” |
| AutoTune / Eval Feedback | 当前 Golden Demo 若没有稳定操作链则不作为主流程 | 可作为未来扩展 |

原则：

> **README 必须区分“应用已经实现并能现场演示”与“Splunk AO 产品具备但当前 Golden Demo 未覆盖”。**

---

# 10. 标准 Demo Storyline 设计要求

README 必须提供一条完整的标准 Storyline。

推荐主线如下。

---

# 11. 从 Instrumentation 到正常 Healthcare 业务

## Act 0 — Instrumentation：先说明 Splunk AO 如何“看见”Agent

### 目标

在正式发 Query 前，用约 1 分钟回答：

> Splunk AO 为什么能够看到 LLM、Tool、RAG 和 Agent 执行链？

### 操作

1. 展示 README 中的应用架构图；
2. 打开 `agent_frameworks/langgraph/agent.py` 中代表性的 `GalileoCallback` 代码；
3. 只展示 Callback 注册和 `graph.ainvoke(..., self.config)` 的关系；
4. 说明当前 Demo 同时使用 `GalileoLogger` 管理 Session / Trace；
5. 不深入 SDK API；
6. 马上返回 Healthcare UI。

### 推荐话术方向

> Agent 可观测性的第一步是 Instrumentation。常见方式包括 SDK Wrapper、Decorator、框架 Callback、OpenTelemetry 和手工 Span。这个 Golden Demo 主要利用 LangChain/LangGraph 的 Callback，把框架内部的执行事件交给 Galileo，再通过 GalileoLogger 组织成 Session、Trace 和 Span。所以我们不需要在每一个 Tool 后面手工写一堆日志，也能看到 Agent 的完整执行链。

### 必须说明

- `GalileoCallback` / `GalileoLogger`：Observability；
- `@control` / Agent Control：Runtime Guardrail；
- 二者不能混为一谈。

---

## Act 1 — 一个看起来正常的 AI Healthcare Assistant

### 目标

先让观众相信这是一个“真实的 Agent Application”，而不是为了演示 observability 而做的静态页面。

### 操作

打开 Healthcare 页面。

先问一个知识类问题，例如：

```text
What is the dosage and common side effects of Lisinopril?
```

再问患者数据，例如：

```text
Show me data for patient P001.
```

### 要向观众说明

这个 Agent 同时使用：

```text
LLM
RAG
Tools
SQL
PostgreSQL
```

应用表面只有一个聊天窗口。

但真实生产环境中，一个回答背后可能发生很多步骤。

### 推荐话术方向

> 对用户来说，这只是一个聊天窗口；但对运维、AI 工程师和风险团队来说，一个回答背后可能经过模型、检索、数据库和多个工具。真正的问题不是“Agent 能不能回答”，而是“当回答出问题时，我们能不能知道哪一步出了问题”。

然后进入 Splunk AO。

---

# 12. Act 2 — 从一个回答进入完整 Trace

### 操作

进入当前 Splunk AO / Galileo 后端：

```text
https://console.multitenant.galileocloud.io/splunkse
```

找到刚刚生成的 Healthcare Session / Trace。

展开：

```text
Trace
└── Healthcare Assistant
    ├── LLM
    ├── Tool
    ├── Retrieval
    └── RAG-related spans
```

实际名称以平台当前展示为准。

### 演示重点

让观众直观看到：

- 用户输入；
- Agent 推理；
- Tool 参数；
- Tool 返回；
- Retrieval；
- Context；
- LLM 输入/输出；
- Latency；
- Token；
- Evaluator 结果。

### 推荐话术方向

> Splunk AO 并不是只告诉我们“这次请求慢了”或者“失败了”。它把一次 Agent 交互还原成完整因果链。我们可以回答：模型为什么这么说、用了什么数据、调用了什么工具，以及问题发生在哪一层。

这一部分是整个 Demo 的基础，不宜讲太久。

---

# 13. Act 3 — 让系统确定性地产生 Hallucination

### 操作

使用 Golden Demo 内置：

```text
Log Hallucination
```

Healthcare 当前预置的示例，应验证类似：

```text
真实 Context:
Lisinopril 10–40 mg ...

故意错误回答:
100 mg ...
```

### 观察

进入 Splunk AO / Galileo：

- 打开新 Trace；
- 展示真实 Context；
- 展示最终错误答案；
- 展示相关 Evaluator 失败。

### 推荐话术方向

> 这里最大的价值不是告诉我们“模型有时会胡说”，而是给出证据：知识库里到底写了什么、模型最终说了什么、Evaluator 为什么认为它不一致。这样才能把 AI 质量问题从主观争论变成可观察、可度量的问题。

---

# 14. Act 4 — Agent 不只是回答错误，还可能做危险动作

这是故事线从 **Observability** 转向 **Runtime Control** 的自然转折点。

### 操作

输入删除患者记录的请求，例如：

```text
Delete patient P001.
```

Agent 将尝试生成 DELETE SQL。

### Agent Control

预先配置：

```text
block-harmful-sql
```

推荐状态：

```text
Enabled
```

目标：

- Agent 可以形成操作意图；
- 系统可以看到 SQL；
- `DELETE` 在执行前被阻止；
- 数据不能真正删除。

### 推荐话术方向

> 对传统聊天机器人来说，回答错误可能只是一次糟糕体验；但 Agent 可以调用真实工具。当它拥有数据库、工单系统、CRM 或代码执行能力时，错误就可能变成真实业务动作。所以 Observability 最终必须延伸到 Runtime Control。

---

# 15. Act 5 — PII 泄露：先观察，再治理

PII（Personally Identifiable Information，个人身份信息）场景应当尽可能设计成“前后对比”。

### 推荐流程

第一轮：

```text
block-output-pii = Disabled
```

请求：

```text
Show me data for patient P001.
```

让观众看到可能出现：

```text
Name
Phone
Address
...
```

说明：

> Tool 有权限读取这些字段，并不代表模型应该把所有字段发送给最终用户。

然后在 Splunk AO / Galileo 中启用：

```text
block-output-pii
```

配置原则：

```text
POST
Steer
Remove phone number and address
```

再次发相同请求。

观察输出被修改。

### 推荐话术方向

> 我们不是简单把整个 Agent 拦掉，而是允许它继续完成合法任务，只对不应该输出的部分进行 Steering。治理目标不是让 AI 失去能力，而是让它在边界内工作。

---

# 16. Act 6 — Prompt Injection

Prompt Injection（提示词注入）应作为“输入侧风险”。

README 中必须写出一个已经实际验证可触发的测试 Prompt。

不要临时现场编造。

演示两次：

```text
Control Disabled
```

以及：

```text
Control Enabled
```

使用：

```text
block-prompt-injection
```

推荐是 PRE-stage Deny。

### 推荐话术方向

> PII 是输出侧风险；Prompt Injection 是输入侧风险。Agent Control 可以在执行路径的不同阶段工作，而不是只在最终回答之后做内容过滤。

---

# 17. Act 7 — Chaos Engineering：同样是“错误结果”，根因并不一样

Chaos Engineering（混沌工程）是 Golden Demo 很有价值的部分，但不要一次把 5 个按钮全讲完。

标准 Demo 推荐优先展示三个：

```text
Tool Instability
Sloppiness
Data Corruption
```

如果时间允许，再加入：

```text
RAG Disconnect
Rate Limits
```

## Tool Instability

故事：

```text
Tool 本身失败
```

例如：

```text
503
timeout
```

目标：

> Splunk AO 可以明确定位外部依赖失败。

## Sloppiness

故事：

```text
Tool 正确
   ↓
中间传输数据被改变
   ↓
LLM 基于错误数据正确回答
```

目标：

> Tool 和 LLM 单独看都可能“没错”，但端到端链路错了。

## Data Corruption

故事：

```text
Tool 正确
   ↓
LLM 收到正确数据
   ↓
LLM 自己输出错误数据
```

目标：

> 相似的最终症状，可以有完全不同的根因。

### 推荐核心话术

> 在真实生产环境中，“答案错了”不是一个足够有用的结论。工程团队需要知道究竟是工具坏了、检索坏了、数据链路坏了，还是模型自己错了。Splunk AO 的价值是帮助我们从结果回到根因。

---

# 18. Act 8 — 从单次 Trace 走向批量 Experiment

前面的故事都是：

```text
one user
one trace
one problem
```

这里自然转向：

> 那我们如何知道整个 Agent 版本整体变好了还是变坏了？

### 操作要求

尽量只在 Golden Demo Streamlit UI 中操作：

```text
Experiments
    ↓
Dataset Setup
    ↓
Experiment Configuration
    ↓
Run Experiment
```

优先使用 Healthcare 自带 Dataset。

Evaluator 使用当前环境默认原生 Evaluator。

不要在主 Demo 中通过 Python 脚本创建 Experiment，除非 UI 出现无法解决的问题。

### Splunk AO / Galileo 中展示

- Dataset
- Experiment
- 每条样本结果
- 聚合 Metrics
- 失败样本
- Evaluator 结果

### 推荐话术方向

> Trace 帮助我们解释一个生产问题；Experiment 帮助我们回答一个工程问题：修改 Prompt、Tool、模型或者 RAG 之后，这个版本整体到底变好了还是变坏了。

---

# 19. Demo 收尾故事

README 中要给出简洁总结，不要把 Demo 收尾变成 Feature Recap 列表。

推荐结构：

```text
Observe
   ↓
Evaluate
   ↓
Diagnose
   ↓
Control
   ↓
Improve
```

推荐话术方向：

> 我们从一个普通的 AI 医疗助手开始。首先看见它真实执行了什么；然后用 Evaluator 判断结果质量；出现问题时定位到 Tool、RAG、数据链路或模型；当 Agent 具有实际执行能力时，再用 Runtime Control 约束高风险行为；最后通过 Dataset 和 Experiment 把单次问题转化成可持续改进过程。这就是 Splunk Agent Observability 希望解决的完整生命周期问题。

---

# 20. README 中必须提供两套演示时长

## 20.1 Standard Demo

目标：

```text
约 15 分钟
```

建议覆盖：

```text
Instrumentation
→ Normal Chat
→ Trace
→ Hallucination
→ Agent Control
→ Experiment
```

Chaos 只展示一个最容易理解的场景。

## 20.2 Full Demo

目标：

```text
约 30 分钟
```

覆盖：

```text
Instrumentation
Normal Chat
Trace
RAG
Tool
Evaluators
Hallucination
SQL Control
PII Steering
Prompt Injection
Chaos
Experiment
Architecture
```

README 中必须明确标记：

```text
Standard Path
Optional Deep Dive
```

这样演示人员可以随时根据客户时间缩短，而不是硬讲完所有 Feature。

---

# 21. Demo 前检查清单

README 必须有一个短的 Pre-Demo Checklist。

至少检查：

| 检查项 | 结果 |
|---|---|
| PostgreSQL 正常运行 | ☐ |
| pgvector 可用 | ☐ |
| Healthcare 数据已加载 | ☐ |
| LLM 可访问 | ☐ |
| Streamlit 可打开 | ☐ |
| Splunk AO / Galileo API Key 有效 | ☐ |
| 当前 backend 是 `splunkse` | ☐ |
| Healthcare Project / Log Stream 正确 | ☐ |
| `block-harmful-sql` 状态正确 | ☐ |
| `block-output-pii` 初始状态正确 | ☐ |
| `block-prompt-injection` 初始状态正确 | ☐ |
| Hallucination Demo 测试通过 | ☐ |
| Experiment Dataset 可见 | ☐ |
| 默认 Evaluator 可正常出结果 | ☐ |
| 浏览器已登录 Splunk AO / Galileo Console | ☐ |

如能通过简单脚本自动检查其中一部分，可以实现，但 README 中仍需保留人工 Checklist。

---

# 22. Demo 状态恢复

必须考虑 Demo 重复运行。

README 中说明如何恢复：

```text
Chaos 全部关闭
Chaos counters reset
Prompt Injection Control 恢复默认
PII Control 恢复默认
Harmful SQL Control 恢复默认
Chat Session 清空
必要时重新加载 Healthcare DB
```

尤其是数据库 DELETE 场景：

> 必须验证 Guardrail 确实阻止数据库删除，不能依赖每次手工恢复 Patient 数据。

---

# 23. README 推荐结构

最终根目录 `README.md` 建议使用如下结构：

```text
# Splunk AO Golden Demo

## 1. What This Demo Is

## 2. Demo Architecture
### Application Components
### End-to-End Request Flow
### Observability Data Flow

## 3. How Instrumentation Works
### Common Instrumentation Methods
### Instrumentation Used by This Demo
### Representative GalileoCallback Example
### Instrumentation vs Agent Control

## 4. Current Supported Environment
### macOS
### Splunk AO Backend
### LLM Provider
### Evaluator

## 5. Quick Start
### Prerequisites
### Clone / Setup
### PostgreSQL + pgvector
### Secrets
### Load Domain Data
### Start the App

## 6. Configuration
### Splunk AO / Galileo
### LLM
### PostgreSQL
### Domain Configuration
### Agent Control

## 7. Demo Domains
### How Domains Work
### Healthcare — Primary
### Healthcare File Structure
### Healthcare Request Flow
### Bank
### Insurance
### Restaurant

## 8. Switching Domains
### Switch to an Existing Domain
### Create a New Domain
### Domain Validation Checklist

## 9. Feature Coverage Matrix

## 10. Standard 15-Minute Demo
### Act 0 — Instrumentation
### Act 1 — Normal AI Assistant
### Act 2 — Trace
### Act 3 — Hallucination
### Act 4 — Runtime Control
### Act 5 — Experiment
### Closing

## 11. Full 30-Minute Demo
### Instrumentation
### RAG
### Tool Calling
### Evaluators
### Hallucination
### SQL Control
### PII Steering
### Prompt Injection
### Chaos Engineering
### Experiment

## 12. Demo Script & Talk Track

## 13. Pre-Demo Checklist

## 14. Reset After Demo

## 15. Troubleshooting

## 16. Architecture Notes
### Single Agent vs Multi-Agent
### Domain Model
### RAG
### Tools
### Instrumentation
### Agent Control
### Experiments

## 17. Future Deployment Options
### Kubernetes
Status: Planned

## 18. Future Evaluation Backends
### vLLM + Qwen3-14B-FP8
Status: Planned

## 19. Future Backend Profiles
### splunkse
Current

### cisco-demo
Planned
```

不要把未来章节写成当前安装手册。

---

# 24. 推荐话术书写规范

README 中每一个 Demo Act 都尽量使用统一格式：

```text
Goal
What to do
What the audience sees
What to open in Splunk AO
What to point out
Talk track
Expected result
Fallback
```

其中 `Talk track` 控制在 2–5 句话。

不要写成逐字背诵的长篇演讲稿。

目标是：

> 演示人员看一眼就知道下一步干什么和为什么这么讲。

---

# 25. UI 演示要求

对 Golden Demo UI 的修改遵循最小原则。

可以做：

- 标题改成 Splunk AO Golden Demo；
- 明确 Healthcare 是 Primary Demo；
- 如果必要，优化少量标签；
- 如果某个按钮含义不清楚，可改善文案；
- 如果某个 Demo 入口被藏得太深，可以做轻量 UI 调整。

不要做：

- 整套 UI 重写；
- 为了“漂亮”引入大型前端框架；
- 把核心 Demo 逻辑迁出 Streamlit；
- 把所有配置暴露给现场观众；
- 让观众在多个 Terminal 之间切换。

---

# 26. 对 Feature 的验证要求

任何写进 README 的演示，都必须实际跑通。

需要至少对以下路径进行实际验证并记录：

```text
Healthcare normal RAG query
Healthcare patient lookup
Hallucination demo
DELETE protection
PII control
Prompt injection control
Tool instability
Sloppiness
Data corruption
RAG disconnect
Experiment
```

如发现某个 upstream 功能当前版本已经失效：

1. 先确认是否为配置问题；
2. 再确认是否为依赖或 API 版本问题；
3. 能小修则修；
4. 如果本阶段不值得修，则不要把它放在主 Demo Storyline；
5. README 明确说明状态。

不要写“理论上应该工作”。

---

# 27. Splunk AO / Galileo Console 截图与界面描述

README 可以使用少量截图，但必须控制数量。

截图优先用于：

- Trace 页面应该看哪里；
- Evaluator 结果在哪里；
- Agent Control 在哪里配置/查看；
- Experiment 结果在哪里。

不要为每一个点击动作都截图。

如果平台 UI 会频繁变化，应优先写：

```text
Project → Log Stream → Trace
```

而不是只依赖截图中的像素位置。

---

# 28. 安全要求

绝对不要提交：

```text
API Key
Password
Token
真实用户数据
内部访问凭据
```

Demo 数据必须是假数据。

Healthcare 患者信息必须明确为 synthetic demo data。

`.streamlit/secrets.toml` 不得进入 Git。

如果 README 中提供示例凭据，使用明显的 placeholder：

```text
YOUR_GALILEO_API_KEY
YOUR_OPENAI_API_KEY
YOUR_POSTGRES_PASSWORD
```

---

# 29. 仓库清洁要求

完成后检查：

```bash
git status
git diff
git diff --staged
```

仓库中不应留下：

```text
venv
.venv
Python cache
local DB dump
secret file
debug log
temporary CSV
macOS metadata
```

如需要保留 Demo 生成结果，放入明确目录并说明用途。

---

# 30. 上游同步和本地定制边界

尽量保持上游目录结构。

如果需要新增本项目自己的内容，优先使用：

```text
.agent-context/
documentation/
scripts/
```

或者非常少量清晰命名的配置扩展。

避免为了本地 Demo 大规模 fork 内部结构，以便未来仍能比较：

```text
upstream/main
```

和：

```text
local main
```

的差异。

任何必要的 upstream 行为修改，都应该：

- 改动最小；
- 注释原因；
- 在 README 的 Architecture Notes 或 Troubleshooting 中说明。

---

# 31. 验收标准

本任务只有同时满足以下条件才算完成。

## Installation

一台已具备必要基础工具的 macOS 机器，按照 README 可以完成安装。

## Startup

可以稳定启动：

```text
PostgreSQL / pgvector
Golden Demo
Healthcare Domain
```

## Splunk AO Integration

正常对话能够在：

```text
console.multitenant.galileocloud.io/splunkse
```

看到对应 Session / Trace / Span。

## Demo Stability

Standard 15-minute Demo 可以连续跑完，不依赖随机成功。

## Feature Coverage

README 的 Feature Coverage Matrix 中标记为：

```text
Supported / Demo-ready
```

的功能均实际验证。

## Agent Control

至少：

```text
Harmful SQL
Output PII
Prompt Injection
```

三个场景有清晰、可复现操作。

## Quality Demo

Hallucination Demo 能产生可解释的 Eval 失败。

## Chaos

至少三个最核心 Chaos 模式完成验证。

## Experiment

可以从 Streamlit UI 选择/创建 Dataset、运行 Experiment，并在 Splunk AO / Galileo 中查看结果。

## Documentation

根 README 足以让另一个 SE 不依赖作者口头指导完成：

```text
Understand Architecture
Understand Instrumentation
Understand Healthcare Domain
Switch / Create Domain
Install
Configure
Run
Demo
Explain
Reset
Troubleshoot
```

同时必须验证：

- README 能解释当前 Golden Demo 的 Single Agent + Tools + RAG 架构；
- README 能解释 Healthcare Domain 中 config / prompt / docs / tools / dataset 的职责；
- README 给出的“切换到已有 Domain”步骤实际可执行；
- README 给出的“复制 Healthcare 创建新 Domain”的方法与当前代码一致；
- Instrumentation 章节准确描述 `GalileoCallback` + `GalileoLogger`；
- 标准演示的第一个技术环节包含一个不超过约 1 分钟的 Instrumentation 展示；
- README 明确区分 Observability Instrumentation 与 Agent Control。

## Future Readiness

README 中存在但不实施：

```text
Kubernetes
vLLM + Qwen3-14B-FP8
cisco-demo backend
```

的结构预留。

---

# 32. 最终交付物

完成任务时至少应提交以下内容：

```text
splunk-ao-golden-demo/
├── README.md
├── .gitignore
├── .streamlit/
│   └── secrets.toml.example
├── app.py
├── ...
├── documentation/
│   └── ...
├── scripts/
│   └── ...                  # 如确有必要
└── .agent-context/
    └── ...                  # 项目上下文和后续 Agent 工作资料
```

其中最重要的交付物不是脚本，而是：

```text
README.md
```

README 必须做到：

> **任何熟悉基本 AI / Splunk 概念的售前工程师拿到仓库后，可以独立把 Demo 跑起来，并自然地讲清楚 Splunk Agent Observability 的价值。**

---

# 33. 执行顺序建议

执行时按以下顺序推进：

```text
1. Inspect local repo
        ↓
2. Compare current upstream main
        ↓
3. Understand application architecture / Domain model / instrumentation
        ↓
4. Make the upstream Golden Demo run locally
        ↓
5. Connect it to current splunkse backend
        ↓
6. Validate Healthcare normal workflow
        ↓
7. Validate GalileoCallback / GalileoLogger instrumentation path
        ↓
8. Validate traces / evaluators
        ↓
9. Validate Hallucination
        ↓
10. Validate Agent Control
        ↓
11. Validate Chaos
        ↓
12. Validate Experiment
        ↓
13. Validate switching to at least one existing Domain
        ↓
14. Design Standard storyline
        ↓
15. Design Full storyline
        ↓
16. Write README
        ↓
17. Run the README from scratch as a test
        ↓
18. Clean repo and document known limitations
```

不要一开始就为了未来 Kubernetes 或 Qwen 大改架构。

先完成：

> **“今天拿着这台 Mac，可以稳定完成一场高质量 Splunk AO Golden Demo。”**

然后再考虑下一阶段。

---

# 34. 开始任务前应阅读的材料

优先阅读：

```text
https://github.com/rungalileo/galileo-golden-demo
```

重点文件：

```text
README.md
app.py
agent_factory.py
domain_manager.py
agent_frameworks/langgraph/agent.py
agent_frameworks/langgraph/langgraph_rag.py
domains/healthcare/config.yaml
domains/healthcare/system_prompt.json
domains/healthcare/tools/
domains/healthcare/dataset.csv
experiments/README.md
documentation/CHAOS_ENGINEERING.md
```

同时参考当前 Splunk Agent Observability 官方文档：

```text
https://agent-observability-docs.splunk.com/what-is-splunk-agent-observability
```

如仓库行为与文档描述冲突：

> **以当前可运行产品行为 + 当前官方文档为准，并在 README 中避免使用已经过时的 Galileo 名称、URL 或操作路径。**

---

# 35. 任务完成时的最终自检问题

在宣布完成前，逐条回答：

```text
Can a new SE install it without asking me?
Can a new SE understand the application architecture and request flow?
Can a new SE explain how GalileoCallback / GalileoLogger instrument this app?
Can a new SE distinguish instrumentation from Agent Control?
Can a new SE understand how the Healthcare Domain is assembled?
Can a new SE switch to another existing Domain correctly?
Can a new SE create a new Domain without modifying the core app?
Can a new SE run the 15-minute demo?
Can a new SE run the 30-minute demo?
Can they explain every screen they open?
Can every claimed feature actually be reproduced?
Can the demo recover to a clean state?
Are secrets protected?
Is Healthcare the clear primary storyline?
Is the audience seeing the product rather than the terminal?
Does the story naturally move from Observe → Evaluate → Diagnose → Control → Improve?
Are Kubernetes / Qwen / alternate backend options clearly reserved but not mixed into the current setup?
```

如果任何一个答案是“No”，任务仍未完成。
