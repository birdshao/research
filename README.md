# AI Agent GitHub Radar

每天自动扫描 GitHub 上与 **AI Agent / Agentic AI / LLM Agent / Multi-Agent** 相关的开源项目，保存历史快照，并生成三类榜单与两类解读：

- **增长最快**：关注最近 1–3 天和约 7 天的 Star 增速。
- **当前最热**：综合累计 Stars、Forks、增长速度和代码活跃度。
- **新兴项目**：关注创建时间较短、单位时间增长较快的项目。
- **重点项目介绍**：说明项目方向、功能、技术信息和入选理由。
- **社区评价与使用建议**：基于维护活跃度、社区健康、Issue、贡献者、许可证等信号，明确给出“值得使用 / 值得试用 / 谨慎试用 / 暂不建议直接用于关键生产”。

最新日报见 [`reports/latest.md`](reports/latest.md)，完整表格数据见 [`data/latest.csv`](data/latest.csv)，机器可读的社区评价见 [`data/community/latest.json`](data/community/latest.json)。

## 运行时间

GitHub Actions 默认在每天 **09:15（America/Chicago）** 执行，并自动适配夏令时。也可以在仓库的 **Actions → AI Agent GitHub Radar → Run workflow** 中手动执行。

调度配置位于 [`.github/workflows/ai-agent-radar.yml`](.github/workflows/ai-agent-radar.yml)：

```yaml
on:
  schedule:
    - cron: "15 9 * * *"
      timezone: "America/Chicago"
```

## 输出内容

每次运行会更新：

| 路径 | 内容 |
|---|---|
| `reports/YYYY-MM-DD.md` | 当日完整 Markdown 日报 |
| `reports/latest.md` | 最新日报的固定入口 |
| `data/latest.csv` | 当前所有入选项目及计算指标 |
| `data/snapshots/YYYY-MM-DD.json.gz` | 用于计算增长的每日压缩快照 |
| `data/community/YYYY-MM-DD.json` | 当日重点项目社区信号、评分、风险和使用建议 |
| `data/community/latest.json` | 最新社区评价的固定机器可读入口 |

工作流还会把日报写入 GitHub Actions 的 Job Summary，并上传一份保留 14 天的运行产物。

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

工作流默认使用 GitHub 自动提供的 `github.token` 运行仓库搜索和提交日报，并只授予当前仓库 `contents: write` 权限。

`github.token` 的权限只限当前仓库，因此跨仓库社区评价默认使用受控数量的匿名公开 API 请求：每个重点项目读取社区健康、最近活跃 Issue 和贡献者，12 个项目最多 36 次请求。

为避免匿名 API 配额不足，可在仓库设置中创建 Actions Secret：

- 名称：`AI_AGENT_RADAR_TOKEN`
- 建议：使用只读 Token，仅授予读取公开仓库元数据、Contents 和 Issues 所需的最小权限

工作流会将该 Secret 用于搜索和社区信号采集；若未设置，基础日报和社区评价仍会以匿名公开 API 继续生成。

## 数据限制

GitHub Search API 返回的是搜索索引和候选排序结果，而不是全站每一次 Star 事件的完整流水。Issue 指标采用最近活跃样本，贡献者接口也可能存在缓存，因此不等同于项目全部历史表现。因此本项目适合做趋势发现、项目筛选和每日观察，不应被解释为 GitHub 全站绝对精确排名或最终技术选型结论。
