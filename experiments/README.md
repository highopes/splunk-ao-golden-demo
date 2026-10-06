# Experiments

当前演示手册是根 [README](../README.md)，真实状态见 [验收记录](../documentation/VALIDATION.md)。现场使用 Streamlit **Experiments → Dataset Setup → Experiment Configuration → Run Experiment**。

Healthcare 自带 domains/healthcare/dataset.csv，15 条 input/output 用例，output 是参考答案。UI 支持该文件、上传同合同 CSV 或选择现有 Dataset。缺列、空值在创建前报错；仅确切创建冲突复用 Dataset，不把权限/网络错误当作成功。

experiment_helpers.py 为 UI / CLI 共用逻辑。SDK 管理 sample Trace；Agent、Callback、Tool 使用同一当前 logger，Agent 不提前 conclude / flush。当前使用 SDK GalileoMetrics 的原生标签：Ground Truth Adherence、Prompt Injection、Context Adherence。当前租户缺少上游 Chunk Attribution Utilization，首次 UI run 因此失败，已移出默认配置。

create_galileo_dataset.py 与 run_experiment.py 用于排障，不替代现场 UI。使用前查看 --help 并指定 Domain，不使用上游旧 Finance 路径。创建成功不等于运行与评分完成，必须查看样本、aggregate 与失败说明；原生评分异步完成，实际 UI 验收结果与链接统一记录在验收记录。
