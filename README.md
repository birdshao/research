# AI Agent GitHub Radar

每天自动扫描 GitHub 上与 **AI Agent / Agentic AI / LLM Agent / Multi-Agent** 相关的开源项目，保存历史快照，并生成三类榜单：

- **增长最快**：关注最近 1–3 天和约 7 天的 Star 增速。
- **当前最热**：综合累计 Stars、Forks、增长速度和代码活跃度。
- **新兴项目**：关注创建时间较短、单位时间增长较快的项目。

最新日报见 [`reports/latest.md`](reports/latest.md)，完整表格数据见 [`data/latest.csv`](data/latest.csv)。

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

工作流还会把日报写入 GitHub Actions 的 Job Summary，并上传一份保留 14 天的运行产物。

## 统计口径

候选项目来自多组 GitHub Repository Search 查询，包括：

- `ai-agent`、`ai-agents`、`agentic-ai`、`llm-agent` 等主题；
- `AI agent`、`agentic AI`、`LLM agent` 等名称、描述、主题和 README 关键词；
- 默认排除归档、禁用和 Fork 项目；
- 默认纳入至少 10 Stars 的项目，同时保留创建 180 天内且至少 5 Stars 的新项目。

核心指标：

| 指标 | 说明 |
|---|---|
| `star_velocity_previous` | 最近 1–3 天可用快照折算的日均 Star 增量 |
| `star_delta_7d_equivalent` | 距今 5–9 天的最近快照折算为 7 天的 Star 增量 |
| `stable_growth_7d` | 以至少 50 Stars 为分母稳定化后的 7 日相对增幅 |
| `lifetime_star_velocity` | Stars / 项目创建天数，用于识别快速起量的新项目 |
| `growth_score` | 近期与 7 日增长、相对增长、生命周期增速、活跃度的综合分 |
| `hot_score` | 在增长指标基础上增加累计 Stars 与 Forks 的综合热度分 |

首日没有历史快照，因此增长榜会更多参考累计规模、项目年龄归一化增速和最近活跃度；从第二天开始出现近期增速，从约第七天开始形成完整的 7 日趋势。

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

工作流默认使用 GitHub 自动提供的 `github.token`，并只授予当前仓库 `contents: write` 权限，用于提交日报和快照。

若公共仓库搜索遇到 API 配额或组织策略限制，可在仓库设置中创建 Actions Secret：

- 名称：`AI_AGENT_RADAR_TOKEN`
- 建议：只授予读取公共仓库元数据所需的最小权限

工作流会优先使用该 Secret，否则回退到 `github.token`。

## 数据限制

GitHub Search API 返回的是搜索索引和候选排序结果，而不是全站每一次 Star 事件的完整流水。因此本项目适合做趋势发现、项目筛选和每日观察，不应被解释为 GitHub 全站的绝对精确排名。
