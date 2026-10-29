---
name: hotspot-monitoring
description: 管理脉冲台的关键词监控与领域热点发现，读取多来源证据、AI 核实状态和提醒。用户要求持续监控关键词、发现最新热点或查询监控结果时使用。
---

# 热点监控

本技能调用本项目网页版的本机 API。持续扫描由后端服务负责；技能命令用于创建任务、手动扫描和读取结果。

## 开始前

1. 在项目根目录运行 `python .cursor/skills/hotspot-monitoring/scripts/hotspot.py status`。
2. 服务未启动时按项目 [README](../../../README.md) 启动后端。API 默认地址为 `http://127.0.0.1:8000`。
3. 检查 `ai_configured`、`x_configured` 与来源状态。缺少 AI 配置或调用失败时，不把待核实线索描述为已核实。

## 常用操作

```powershell
python .cursor/skills/hotspot-monitoring/scripts/hotspot.py add "GPT 新模型发布" --kind keyword
python .cursor/skills/hotspot-monitoring/scripts/hotspot.py add "AI 编程" --kind topic
python .cursor/skills/hotspot-monitoring/scripts/hotspot.py rules
python .cursor/skills/hotspot-monitoring/scripts/hotspot.py scan 1
python .cursor/skills/hotspot-monitoring/scripts/hotspot.py events --rule-id 1
python .cursor/skills/hotspot-monitoring/scripts/hotspot.py alerts
```

关键词任务默认每 5 分钟扫描并对已核实事件创建提醒；领域任务默认每 30 分钟扫描并展示发现结果。`add` 可带 `--interval` 指定 5 到 1440 分钟。用 `update ID --pause`、`update ID --resume`、`update ID --query 内容` 或 `update ID --interval 分钟` 修改任务。删除任务会删除历史数据，只有用户明确要求时才用 `delete ID`。

## 向用户报告

- 对每项事件提供标题、中文摘要、状态、核实理由、发现时间及原始来源链接。
- “已核实”只表示项目证据规则已满足；“待核实”和“疑似误传”应明确标注。不能根据标题或 AI 摘要自行提升可信度。
- 如果某来源失败、OpenRouter 受限或服务未运行，说明实际状态和可能延迟，不声称已经完成持续监控。
- 监控任务创建后仍需本机后端保持运行；技能本身不会在 AI 会话结束后驻留。

命令脚本只依赖 Python 标准库。更多项目功能及配置见 [README](../../../README.md)。
