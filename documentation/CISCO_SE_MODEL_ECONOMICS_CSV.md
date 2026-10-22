# Cisco SE Model Economics CSV 数据契约

本文件是 `data/cisco_se_model_economics.csv` 的数据契约，供后续 Splunk Enterprise Dashboard 仓库（[splunk-galileo-dashboard](https://github.com/highopes/splunk-galileo-dashboard)）作为 `inputlookup` 数据源。生成命令、演示步骤见根 [README 5.6](../README.md#cisco-se-economics)；验收证据见 [VALIDATION.md](VALIDATION.md#cisco-se)。

**本仓库只交付 CSV 与本契约，不包含 Splunk Dashboard。**

## 1. 生成方式与边界

```bash
./scripts/export-cisco-se-economics
./scripts/export-cisco-se-economics --output /absolute/path/cisco_se_model_economics.csv
# 可选：--project / --group / --prefix / --experiment-ids / --gt-pass-threshold
```

| 项目 | 规则 |
|---|---|
| 范围 | 默认只读 `domains/cisco_se/config.yaml` 的 Project `splunk-ao-golden-demo-cisco-se` 与 Group `Cisco SE Model Economics`；`--project` 指向其他 Domain 的 Project 会被拒绝，绝不导出 Healthcare |
| 只读 | 只调用 Experiment、Experiment 标签、根 Trace、子 Span 的查询接口；不运行 LLM、Experiment、Control，不对平台写入 |
| 凭据 | 通过 `setup_env` 读取 `.streamlit/secrets.toml`；不打印、不写入 Key |
| 分页与重试 | 每次查询 100 条，按 `next_starting_token` 翻页（没有 token 且整页时按 offset 继续）；记录按 `id` 去重；超时/429/5xx 有限重试 4 次，其他错误立即失败 |
| 原子写入 | 写入同目录临时文件 → `csv.DictReader` 回读校验 → `os.replace`；任何查询或校验失败都不覆盖原有 CSV |
| 输出位置 | 默认 `data/cisco_se_model_economics.csv`（`data/` 已被 `.gitignore` 忽略，导出结果不入库） |
| Group 中有多次运行 | 默认导出 Group 内**全部** Experiment（每个 Experiment 单独汇总，不合并）。Dataset 版本或 hash 与当前 `dataset_sources.yaml` 不一致的历史运行（如 `cisco-se-2026-10-21.v1`）仍会导出，但 `comparison_ready=0`、`comparison_warning` 含 `dataset_not_in_plan`（题目已被修改的行另含 `scenario_not_in_dataset_plan`），并打印配对警告。只要某一轮时用 `--experiment-ids <A>,<B>`；当前交付的 `data/cisco_se_model_economics.csv` 即只含 v2 的两个 Experiment |

## 2. 文件格式

- UTF-8（无 BOM），LF 行尾，首行为 header，列顺序固定为下表顺序。
- 每个**根 Trace** 一行；唯一键 `(experiment_id, trace_id)`。
- 长文本（`scenario_input`、`ground_truth`、`generated_output`、`ground_truth_adherence_rationale` 等）中的 `\` 写作 `\\`，CR/LF 统一写作字面量 `\n`，Tab 写作 `\t`；因此**每条记录只占一行物理行**，Splunk `inputlookup` 不会被嵌入换行拆分。逗号与双引号按 RFC 4180 加引号转义。
- 空字符串 = 平台没有返回该值或尚未完成；**不补零、不估算**。
- 浮点以 Python `repr` 写出（完整精度）；整数不带小数点；布尔用 `0` / `1`。
- `schema_version=1`。增加列或改变口径时提高版本号并更新本文件。

## 3. 数据血缘

| 来源 | 提供字段 |
|---|---|
| Experiment 对象（`get_experiments(project_id, experiment_group)`） | `experiment_*`、`experiment_group_*`、`dataset_id`、`dataset_name`、`dataset_version_index` |
| Experiment 标签（运行时由 `experiments/experiment_helpers.py` 写入） | `application_model`、`model_provider`、`api_mode`、`reasoning_effort`、`dataset_version`、`dataset_hash`、`code_version`、`chaos_state`、`run_id` |
| 根 Trace（`experiment_id` 过滤的 trace 查询） | 输入、Ground Truth、输出、`metrics`（duration、tokens、cost）、`metric_info`（Judge）、状态 |
| 子 Span（同一 Experiment 的 span 查询） | 观察到的 LLM 模型、Span 计数、错误 Span、Tool 名称、Span 级 Context Adherence 与 token 回退 |
| 本地 `domains/cisco_se/dataset_sources.yaml` | `scenario_id`（Q01–Q10）的映射，以及用于比对的期望 `dataset_version` / `dataset_hash` |

`dataset_hash` 是云端 Dataset 内容（排序后的 `[input, output]` 对的紧凑 JSON）的 sha256，在 Experiment 启动前由运行器从**云端**读回计算并写入标签；导出时与本地 `dataset_sources.yaml` 比对，不在导出阶段猜测。

## 4. 字段

类型：`str` 字符串、`int` 整数、`float` 浮点、`bool` 0/1。“空值”列说明什么情况下为空。

### 4.1 身份

| 列 | 类型 | 来源 / 含义 | 空值 |
|---|---|---|---|
| `schema_version` | int | 契约版本，当前 `1` | 从不为空 |
| `exported_at_utc` | str | 本次导出时间，ISO-8601 UTC（`Z`），同一次导出所有行相同 | 从不为空 |
| `project_name` | str | Splunk AO Project 名称 | 从不为空 |
| `project_id` | str | Project UUID | — |
| `experiment_group_name` | str | Experiment Group 名称 | 平台未返回 |
| `experiment_group_id` | str | Group UUID | 平台未返回 |
| `experiment_id` | str | Experiment UUID；与 `trace_id` 组成唯一键 | 从不为空 |
| `experiment_name` | str | Experiment 名称，形如 `Cisco SE Model Economics - <model> - <run_id>` | — |
| `experiment_created_at_utc` | str | Experiment 创建时间 UTC | 平台未返回 |
| `run_id` | str | 运行器为同一轮 A/B 生成的标识（UTC 时间戳）；UI 运行时为空 | UI 运行 |
| `code_version` | str | 运行时 git commit；`-dirty` 表示有未提交改动 | 无 git |

### 4.2 模型（只描述应用 LLM，Judge 另列）

| 列 | 类型 | 来源 / 含义 | 空值 |
|---|---|---|---|
| `application_model` | str | 运行时配置的应用模型（标签），如 `gpt-5-nano` / `gpt-6.1-sol` | 标签缺失 |
| `observed_llm_models` | str | 子 LLM Span 实际记录的模型 ID，`;` 分隔；OpenAI 可能返回带日期快照，如 `gpt-5-nano-2025-08-07` | 没有 LLM Span |
| `model_provider` | str | 标签，`openai` | 标签缺失 |
| `api_mode` | str | 标签，`responses`（Responses API + Tool Calling） | 标签缺失 |
| `reasoning_effort` | str | 标签，运行时显式发送的 reasoning effort，当前两模型均为 `low` | 标签缺失 |

`observed_llm_models` 中每个 ID 都必须等于 `application_model` 或以 `application_model-` 开头（日期快照），否则警告 `application_model_mismatch` 且不可比。

### 4.3 Dataset

| 列 | 类型 | 来源 / 含义 | 空值 |
|---|---|---|---|
| `dataset_id` | str | 云端 Dataset UUID | 平台未返回 |
| `dataset_name` | str | 云端 Dataset 名称 | 平台未返回 |
| `dataset_version_index` | int | 云端 Dataset 版本序号 | 平台未返回 |
| `dataset_version` | str | 标签，人工维护的语义版本，如 `cisco-se-2026-10-21.v1` | 标签缺失 |
| `dataset_hash` | str | 标签，云端 Dataset 内容 sha256（见第 3 节） | 标签缺失 |
| `scenario_id` | str | `dataset_sources.yaml` 中的题号 Q01–Q10 | 题目不在计划中 |
| `scenario_key` | str | `sha256(去首尾空白的 input)` 前 16 位十六进制；跨模型配对键 | 从不为空 |
| `scenario_input` | str | Dataset input（转义见第 2 节） | — |
| `ground_truth` | str | Dataset 参考答案 | 平台未返回 |
| `generated_output` | str | 应用最终回答 | 平台未返回 |

### 4.4 Trace 身份

| 列 | 类型 | 含义 | 空值 |
|---|---|---|---|
| `trace_id` | str | 根 Trace UUID | 从不为空 |
| `session_id` | str | 所属 Session | 平台未返回 |
| `trace_created_at_utc` | str | Trace 创建时间 UTC | 平台未返回 |

### 4.5 质量（Ground Truth Adherence 为核心 Judge）

| 列 | 类型 | 来源 / 含义 | 空值 |
|---|---|---|---|
| `ground_truth_adherence_metric_id` | str | 根 Trace `metric_info` 中 GT Adherence 的 metric ID | Scorer 未挂载 |
| `ground_truth_adherence_status` | str | 平台状态：`success` / `pending` / `failed` / `error` / `not_computed` 等，原样小写 | Scorer 未挂载 |
| `ground_truth_adherence_score` | float | 0..1；多 Judge 时为平台 `multijudge_average`，否则数值均值。**仅 `status=success` 时有值** | 未完成或失败 |
| `ground_truth_adherence_pass` | bool | `score ≥ threshold` → 1，否则 0 | 未评分 |
| `ground_truth_adherence_scored` | bool | 已成功评分 = 1；pending / failed / 缺失 = 0 | 从不为空 |
| `ground_truth_adherence_pass_threshold` | float | 本次导出使用的阈值，默认 `0.5`（`--gt-pass-threshold`） | 从不为空 |
| `ground_truth_adherence_rationale` | str | Judge 解释原文（转义） | 平台未返回 |
| `context_adherence_status` | str | Context Adherence 状态；根 Trace 只有 `roll_up` 时取**最终回答 LLM Span** 的状态 | 未挂载 |
| `context_adherence_score` | float | 根 Trace 有数值时取根值；否则取**最终回答 LLM Span**（`created_at` 最晚）的成功分数。不对多个 LLM Span 求平均：前面的 LLM Span 只是“决定调用工具”，没有回答，Judge 对它打 0 或 1 都不稳定，平均会得到误导性的 0.5 | 未完成 |
| `context_adherence_cost_usd` | float | Context Adherence 评分费用：所有 LLM Span 的 CA 费用之和（每个 LLM Span 都会被评分并计费） | 平台未返回 |

Judge 尚未完成（`pending`）、无法评分（`failed`/`error`）与判定不通过（`scored=1, pass=0`）三者不同：前两者 `score`、`pass` 为空，不计入通过率分母。

### 4.6 Judge 用量（与应用费用分开）

| 列 | 类型 | 来源 / 含义 | 空值 |
|---|---|---|---|
| `judge_model` | str | GT Adherence Judge 模型别名（`metric_info.model_alias` 或根 metrics `<alias>_model_alias`） | 平台未返回 |
| `judge_count` | int | Judge 数量（`num_judges`） | 平台未返回 |
| `judge_input_tokens` | int | Judge 输入 tokens | 平台未返回 |
| `judge_output_tokens` | int | Judge 输出 tokens | 平台未返回 |
| `judge_cost_usd` | float | GT Adherence 评分费用（`metric_info.cost` 或根 metrics `<alias>_metric_cost`） | 平台未返回 |

Judge 费用**从不**计入 `trace_cost_usd`。

### 4.7 效率（平台计算的根 Trace 指标）

| 列 | 类型 | 来源 / 含义 | 空值 |
|---|---|---|---|
| `trace_duration_seconds` | float | 根 Trace `metrics.duration_ns / 1e9`；每条响应的端到端时延 | 平台未返回 |
| `trace_input_tokens` | int | 应用 LLM 输入 tokens | 见 `token_source` |
| `trace_output_tokens` | int | 应用 LLM 输出 tokens（含推理 tokens 的计费口径以平台为准） | 见 `token_source` |
| `trace_total_tokens` | int | 应用 LLM 总 tokens | 见 `token_source` |
| `token_source` | str | `trace`＝根 Trace roll-up；`llm_spans`＝根 Trace 无 roll-up，取子 LLM Span 之和；空＝两者都没有 | — |
| `trace_cost_usd` | float | 根 Trace `metrics.cost`，**平台按其价格表计算的应用 LLM 费用**（不含 Judge） | 平台未返回 |
| `trace_cost_status` | str | 根 Trace `metrics.cost_status` 原值 | 平台未返回 |
| `llm_reasoning_tokens` | int | 子 LLM Span `num_reasoning_tokens` 之和 | **当前平台不返回该字段，预期为空** |
| `llm_cached_input_tokens` | int | 子 LLM Span `num_cached_input_tokens` 之和 | **当前平台不返回该字段，预期为空** |

关于成本：

- 价格来自 Splunk AO 平台价格表（本租户 `GET /models/price_overrides` 为空，使用平台默认价；导出器**不使用**任何本地或公开价格表重算）。
- 本租户对 `reliable=False` 的 Trace 写入会把 LLM 成本存为 `0.0`（`cost_status=success`）。`cisco_se` 通过 `galileo.reliable_ingest: true` 让该 Project 的写入使用 `reliable=True`，平台因此计算出真实成本并给根 Trace 写入 token roll-up（`token_source=trace`）。原因与证据见 [VALIDATION.md](VALIDATION.md#cisco-se)。
- `trace_cost_usd=0` 而 `trace_total_tokens>0` 视为平台未定价：警告 `platform_cost_zero_with_tokens`，`cost_ready=0`，**不作为“免费”**。
- 两个模型的 tokenizer 与推理实现不同；token 数是服务端计费单位，不等同于回答的语义详细程度，应与质量、费用联合解读。

### 4.8 工作流（Single Agent Span 类型计数）

| 列 | 类型 | 含义 |
|---|---|---|
| `span_count` | int | 该 Trace 的全部子 Span 数（不含根） |
| `llm_call_count` | int | `type=llm` Span 数（应用 Agent 的模型调用） |
| `tool_call_count` | int | `type=tool` Span 数 |
| `retriever_call_count` | int | `type=retriever` Span 数 |
| `control_span_count` | int | `type=control` Span 数（Agent Control 评估） |
| `error_span_count` | int | 带 `error_message` 或 `status_code ≥ 400` 的 Span 数 |
| `unique_tools` | str | 去重排序后的 Tool 名，`;` 分隔，正常为 `search_cisco_se_specs` |

### 4.9 可信度

| 列 | 类型 | 含义 |
|---|---|---|
| `trace_status_code` | int | 根 Trace `status_code`；SDK 默认不设置（`0`/空视为正常），`200–399` 正常，其余视为失败 |
| `trace_complete` | bool | 平台 `is_complete` |
| `agent_error` | bool | 输出以应用/SDK 错误前缀开头（`Error processing your request:` / `error during executing`） |
| `control_intervention` | bool | Trace 或 Span 文本含 Agent Control 阻断/Steer 标记 |
| `chaos_state` | str | 标签，运行时 Chaos 开关状态；`off` 才可比 |
| `quality_ready` | bool | `= ground_truth_adherence_scored` |
| `cost_ready` | bool | duration、cost、三项 tokens 均有值，且不是“有 token 但 cost=0” |
| `comparison_ready` | bool | 见下 |
| `comparison_warning` | str | 机器可读警告码，`;` 分隔（见第 5 节） |

`comparison_ready=1` 当且仅当**全部**满足：Trace 完成且状态正常；无错误 Span；有子 Span 且至少一个 LLM Span；input / ground truth / output 均非空；无 agent error；无 Control 干预；`chaos_state=off`；观察到的模型与 `application_model` 一致；运行时标签齐全；`dataset_version` 与 `dataset_hash` 等于本地计划；题目在计划中；`cost_ready=1`；`quality_ready=1`；同一 Experiment 内该题只有一条 Trace。

`comparison_ready=0` 的行仍然导出（不静默丢弃失败或未完成样本），Dashboard **默认不得**把它们作为有效比较样本。

## 5. 警告码（`comparison_warning`）

| 警告码 | 含义 |
|---|---|
| `no_llm_model_observed` / `application_model_mismatch` | 没有 LLM Span 模型 / 观察到的模型与配置不一致 |
| `scenario_not_in_dataset_plan` | 输入不在 `dataset_sources.yaml` 计划中 |
| `duplicate_scenario_in_experiment` | 同一 Experiment 中同一题出现多条 Trace |
| `agent_error_output` / `agent_control_intervened` | 应用错误输出 / Control 干预 |
| `chaos_not_off` / `chaos_state_unknown` | Chaos 未关闭 / 无 Chaos 标签 |
| `ground_truth_adherence_missing` | 根 Trace 没有 GT Adherence |
| `ground_truth_adherence_<status>` | GT Adherence 未成功，例如 `_pending`、`_failed` |
| `context_adherence_<status>` | Context Adherence 无成功分数（仅提示，不影响 `comparison_ready`） |
| `trace_cost_missing` / `platform_cost_zero_with_tokens` / `trace_tokens_or_duration_missing` | 成本缺失 / 平台未定价 / tokens 或时延缺失 |
| `trace_incomplete` / `trace_status_<code>` / `error_spans` / `no_child_spans` | Trace 未完成 / 异常状态码 / 有错误 Span / 无子 Span |
| `missing_input_output_or_ground_truth` | 输入、参考答案或输出为空 |
| `missing_runtime_tags` / `dataset_not_in_plan` | 运行时标签缺失 / Dataset 版本或 hash 与计划不一致 |

## 6. 聚合口径（导出器文本摘要与 Dashboard 应一致）

- **粒度是 Experiment**：按 `experiment_id` 聚合；同一模型不同日期的多次运行不合并。
- **配对**：只有 `dataset_id`、`dataset_version_index`、`dataset_hash` 一致且 `scenario_key` 相同的题目才逐项配对；不一致时导出器打印配对警告。
- **Ground Truth 通过率** = `sum(ground_truth_adherence_pass) / sum(ground_truth_adherence_scored)`，同时显示通过数与已评分数。
- **应用总成本** = `comparison_ready=1` 行的 `sum(trace_cost_usd)`；评分费用 `sum(judge_cost_usd)`（GT Adherence）与 `sum(context_adherence_cost_usd)` 另列，不计入应用成本。
- **每个合格回答的成本** = 应用总成本 / `comparison_ready=1` 行中的通过数；分母为 0 时为空。
- **平均时延 / P95** 基于 `comparison_ready=1` 行的 `trace_duration_seconds`；P95 用 nearest-rank。**不要用 Experiment 总耗时代替每条时延**。
- 文本摘要另外给出“全部行”的成本与 tokens，以便看到未就绪行的实际消耗。

示例 SPL（仅说明口径，本仓库不交付 Dashboard）：

```spl
| inputlookup cisco_se_model_economics.csv
| where comparison_ready=1
| stats count AS samples sum(ground_truth_adherence_pass) AS passed sum(ground_truth_adherence_scored) AS scored
        sum(trace_cost_usd) AS app_cost avg(trace_duration_seconds) AS avg_latency perc95(trace_duration_seconds) AS p95_latency
        BY experiment_id application_model
| eval pass_rate=round(passed/scored,3), cost_per_pass=if(passed>0, app_cost/passed, null())
```

Splunk `perc95` 与导出器 nearest-rank P95 在小样本上可能略有差异。

## 7. 校验（每次导出自动执行）

写入后 `csv.DictReader` 回读：header 与本契约完全一致；必填列非空；`(experiment_id, trace_id)` 无重复；整数/浮点/布尔列类型正确且为有限数；`token_source` 取值合法；没有未转义换行；`comparison_ready=1` 的行必须有成本与成功评分；回读行数等于写入行数。任一失败都不替换旧文件，并以非零退出码结束。

单元测试（`tests/test_cisco_se_domain.py`，mock 数据仅用于自动化测试）覆盖：分页（token / offset / 去重）、有限重试、重复 Trace、模型缺失或不一致、成本 null / 0、Judge pending / failed、Context Adherence 取最终回答 LLM Span、Dataset 版本不一致、Chaos、Agent 错误、原子写入失败保留旧文件、P95 与跨模型配对。
