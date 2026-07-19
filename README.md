# AI Agent GitHub Radar

每天自动扫描 GitHub 上与 **AI Agent / Agentic AI / LLM Agent / Multi-Agent** 相关的开源项目，保存历史快照，并把以下内容合并为一份完整的每日日报：

- **增长最快**：关注最近 1–3 天和约 7 天的 Star 增速。
- **当前最热**：综合累计 Stars、Forks、增长速度和代码活跃度。
- **新兴项目**：关注创建时间较短、单位时间增长较快的项目。
- **重点项目介绍**：说明项目方向、功能、技术信息和入选理由。
- **社区评价与使用建议**：基于维护活跃度、社区健康、Issue、贡献者、许可证等信号，明确给出“值得使用 / 值得试用 / 谨慎试用 / 暂不建议直接用于关键生产”。

最新完整日报见 [`reports/latest.md`](reports/latest.md)，完整表格数据见 [`data/latest.csv`](data/latest.csv)，机器可读的社区评价见 [`data/community/latest.json`](data/community/latest.json)。

## 运行时间

GitHub Actions 每天早上 **08:00（America/Chicago）** 主触发，并自动适配夏令时。为降低 GitHub Actions 整点高负载导致计划延迟或丢失的影响，工作流在 **08:20** 设有一次自动补偿触发：若 08:00 已成功完成，补偿任务会通过当天完成标记立即跳过；若主触发未运行或执行失败，08:20 会重新生成完整日报。

也可以在仓库的 **Actions → AI Agent GitHub Radar → Run workflow** 中手动生成。对脚本、测试、配置或工作流的普通代码提交只执行单元测试，不会提前覆盖当日日报。

调度配置位于 [`.github/workflows/ai-agent-radar.yml`](.github/workflows/ai-agent-radar.yml)：

```yaml
on:
  schedule:
    - cron: "0 8 * * *"
      timezone: "America/Chicago"
    - cron: "20 8 * * *"
      timezone: "America/Chicago"
```

## 每日日报生成流程

每次正式日报运行会依次完成：

1. 搜索并去重 AI Agent 相关 GitHub 项目，计算增长、热度与新兴评分。
2. 生成三类榜单和今日概览。
3. 为重点项目补充方向、功能简介、技术栈与入选理由。
4. 采集 GitHub 社区健康、近期 Issue、贡献者、许可证和维护活跃度。
5. 给出社区分、风险提示以及“值不值得使用”的明确结论。
6. 将所有内容合并进同一份 `reports/YYYY-MM-DD.md` 和 `reports/latest.md`。
7. 上传完整 Artifact，并把日报与历史快照提交回仓库。

## 输出内容

每次运行会更新：

| 路径 | 内容 |
|---|---|
| `reports/YYYY-MM-DD.md` | 当日完整 Markdown 日报，包含榜单、项目介绍、社区评价和使用建议 |
| `reports/latest.md` | 最新完整日报的固定入口 |
| `data/latest.csv` | 当前所有入选项目及计算指标 |
| `data/snapshots/YYYY-MM-DD.json.gz` | 用于计算增长的每日压缩快照 |
| `data/community/YYYY-MM-DD.json` | 当日重点项目社区信号、评分、风险和使用建议 |
| `data/community/latest.json` | 最新社区评价的固定机器可读入口 |
| `data/run-state/YYYY-MM-DD.done` | 成功完成定时报表的内部标记，用于阻止 08:20 补偿任务重复生成 |

工作流还会把完整日报写入 GitHub Actions 的 Job Summary，并上传一份保留 14 天的运行产物。

## 统计口径

候选项目来自多组 GitHub Repository Search 查询，包括：

- `ai-agent`、`ai-agents`、`agentic-ai`、`llm-agent` 等主题；
- `AI agent`、`agentic AI`、`LLM agent` 等名称、描述、主题和 README 关键词；
- 默认排除归档、禁用和 Fork 项目；
- 默认纳入至少 10 Stars 的项目，同时保留创建 180 天内且至少 5 Stars 的新项目。

核心趋势指标：

| 指标 | 说明 |
|---|---|
| `star_velocity_previous` | 最近 1–3 天可用快照折算的日均 Star 增量 |
| `star_delta_7d_equivalent` | 距今 5–9 天的最近快照折算为 7 天的 Star 增量 |
| `stable_growth_7d` | 以至少 50 Stars 为分母稳定化后的 7 日相对增幅 |
| `lifetime_star_velocity` | Stars / 项目创建天数，用于识别快速起量的新项目 |
| `growth_score` | 近期与 7 日增长、相对增长、生命周期增速、活跃度的综合分 |
| `hot_score` | 在增长指标基础上增加累计 Stars 与 Forks 的综合热度分 |

首日没有历史快照，因此增长榜会更多参考累计规模、项目年龄归一化增速和最近活跃度；从第二天开始出现近期增速，从约第七天开始形成完整的 7 日趋势。

## 社区评价与“值不值得使用”

日报会从热度榜、增长榜和新兴榜轮询去重，选择 12 个重点项目。社区分为 **0–100**，主要考察：

| 维度 | 重点 |
|---|---|
| 近期维护 | 距最近代码推送的时间 |
| 社区采用 | Stars 与 Forks 的规模，仅作为采用度信号，不等同于质量 |
| 社区健康 | README、CONTRIBUTING、行为准则、Issue/PR 模板等社区健康文件 |
| Issue 维护 | 最近活跃 Issue 样本的关闭率、讨论参与度和风险标签 |
| 贡献者广度 | 贡献者样本数量，以及是否过度集中于单一维护者 |
| 许可证 | 是否有清晰的开源许可证 |

推荐档位：

- **值得使用**：综合信号较强，可优先试用；生产采用前仍需完成安全、数据和兼容性验证。
- **值得试用**：适合个人、PoC 或小团队验证，关键业务接入前应完成回归测试。
- **谨慎试用**：维护、许可证、Issue 或贡献者结构存在明显风险，建议隔离环境、小范围验证。
- **暂不建议直接用于关键生产**：当前社区与维护信号偏弱，更适合研究和技术评估。
- **信息不足，建议先小范围试用**：API 信号不足，系统不会用缺失数据制造确定性结论。

这一评价是可解释的 GitHub 原生信号启发式模型，**不是用户口碑调查、安全审计、性能评测或生产可用性保证**。热门项目也可能不适合特定场景；低分项目也可能在非常具体的用途上有价值。

## 配置

修改 [`config.json`](config.json) 可调整：

- 时区、最低 Stars、新兴项目年龄；
- 每个查询的结果数量和日报 Top N；
- 搜索关键词与主题；
- 快照保留天数；
- GitHub API 版本、超时和重试策略。

脚本只使用 Python 标准库，不需要安装依赖。本地运行：

```bash
export GH_TOKEN="你的 GitHub Token"
python scripts/ai_agent_radar.py --config config.json
python scripts/enrich_report.py --report reports/latest.md --csv data/latest.csv --top-n 12
python scripts/community_review.py \
  --report reports/latest.md \
  --csv data/latest.csv \
  --output-json data/community/latest.json \
  --top-n 12
```

离线测试：

```bash
python -m unittest discover -s tests -v
python scripts/ai_agent_radar.py \
  --config config.json \
  --fixture tests/fixture_repositories.json \
  --dry-run
```

## Token 与权限

工作流默认只授予 `contents: read`。只有正式的 `daily-report` 作业临时使用当前仓库的 `contents: write` 权限，以便提交日报、快照、社区评价和当天完成标记；普通代码提交触发的验证作业只有读取权限。

`github.token` 的权限只限当前仓库，因此跨仓库社区评价默认使用受控数量的匿名公开 API 请求：每个重点项目读取社区健康、最近活跃 Issue 和贡献者，12 个项目最多 36 次请求。

为避免匿名 API 配额不足，可在仓库设置中创建 Actions Secret：

- 名称：`AI_AGENT_RADAR_TOKEN`
- 建议：使用只读 Token，仅授予读取公开仓库元数据、Contents 和 Issues 所需的最小权限

工作流会将该 Secret 用于搜索和社区信号采集；若未设置，基础日报和社区评价仍会以匿名公开 API 继续生成。

## 数据限制

GitHub Search API 返回的是搜索索引和候选排序结果，而不是全站每一次 Star 事件的完整流水。Issue 指标采用最近活跃样本，贡献者接口也可能存在缓存，因此不等同于项目全部历史表现。因此本项目适合做趋势发现、项目筛选和每日观察，不应被解释为 GitHub 全站绝对精确排名或最终技术选型结论。
