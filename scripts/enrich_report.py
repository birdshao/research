#!/usr/bin/env python3
"""Add readable project introductions to an AI Agent GitHub Radar report."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

Repo = dict[str, str]

SECTION_START = "<!-- AI_AGENT_PROJECT_INTRO_START -->"
SECTION_END = "<!-- AI_AGENT_PROJECT_INTRO_END -->"
QUALITY_HEADING = "## 口径与数据质量"


def compact(value: Any, limit: int = 320) -> str:
    """Normalize whitespace and cap long GitHub descriptions."""
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return "GitHub 暂未提供项目简介，可进入仓库结合 README 与示例进一步了解。"
    return text if len(text) <= limit else text[: max(limit - 1, 1)].rstrip() + "…"


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def integer(value: Any) -> int:
    return int(number(value))


def topics(repo: Mapping[str, Any]) -> list[str]:
    value = repo.get("topics", "")
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def project_category(repo: Mapping[str, Any]) -> str:
    """Classify a repository into a readable Chinese product direction."""
    text = " ".join(
        [
            str(repo.get("full_name", "")),
            str(repo.get("description", "")),
            " ".join(topics(repo)),
        ]
    ).lower()

    rules: Sequence[tuple[tuple[str, ...], str]] = (
        (
            (
                "design",
                "image",
                "video",
                "media",
                "slide",
                "ui generator",
                "prototyp",
            ),
            "设计、内容与多媒体 Agent",
        ),
        (
            (
                "tutorial",
                "beginner",
                "course",
                "learn",
                "awesome",
                "examples",
                "best practice",
                "cookbook",
            ),
            "教程、案例与学习资源",
        ),
        (
            (
                "browser",
                "web automation",
                "web scraping",
                "scraper",
                "crawler",
                "search agent",
                "web agent",
            ),
            "浏览器、搜索与 Web 自动化",
        ),
        (
            (
                "finance",
                "stock",
                "trading",
                "research",
                "analysis",
                "data agent",
                "deep research",
            ),
            "研究、数据分析与垂直场景",
        ),
        (
            (
                "rag",
                "retrieval",
                "memory",
                "knowledge",
                "vector",
                "document",
            ),
            "知识库、记忆与 RAG",
        ),
        (
            (
                "coding agent",
                "code agent",
                "code review",
                "developer",
                "claude code",
                "codex",
                "terminal",
                "cli",
                "ide",
            ),
            "编程、代码审查与开发者 Agent",
        ),
        (
            (
                "multi-agent",
                "multi agent",
                "orchestration",
                "agent framework",
                "agent workflow",
                "workflow engine",
                "agent platform",
                "autonomous agents",
            ),
            "Agent 框架、编排与平台",
        ),
        (
            (
                "assistant",
                "productivity",
                "automation",
                "personal agent",
                "desktop agent",
            ),
            "个人助理与流程自动化",
        ),
    )
    for keywords, label in rules:
        if any(keyword in text for keyword in keywords):
            return label
    return "通用 AI Agent 与 Agent 工具"


def rank_rows(
    rows: Sequence[Repo],
    score: str,
    tie_breakers: Sequence[str],
    *,
    eligible: Any = None,
) -> list[Repo]:
    candidates = [row for row in rows if eligible is None or eligible(row)]
    keys = (score, *tie_breakers)
    return sorted(
        candidates,
        key=lambda row: tuple(number(row.get(key)) for key in keys),
        reverse=True,
    )


def select_featured(
    rows: Sequence[Repo],
    top_n: int,
    *,
    emerging_max_age_days: int = 180,
    emerging_minimum_stars: int = 5,
) -> tuple[list[Repo], dict[str, dict[str, int]]]:
    """Round-robin across hot, growth and emerging lists to preserve variety."""
    hot = rank_rows(rows, "hot_score", ("stars",))
    growth = rank_rows(
        rows,
        "growth_score",
        ("star_velocity_previous", "star_delta_7d_equivalent", "stars"),
    )
    emerging = rank_rows(
        rows,
        "emerging_score",
        ("lifetime_star_velocity", "stars"),
        eligible=lambda row: (
            number(row.get("age_days")) <= emerging_max_age_days
            and number(row.get("stars")) >= emerging_minimum_stars
        ),
    )

    rankings = {"热度榜": hot, "增长榜": growth, "新兴榜": emerging}
    rank_maps = {
        label: {
            str(row.get("full_name", "")): index
            for index, row in enumerate(ranking, 1)
        }
        for label, ranking in rankings.items()
    }

    selected: list[Repo] = []
    seen: set[str] = set()
    max_length = max((len(ranking) for ranking in rankings.values()), default=0)
    for index in range(max_length):
        for ranking in (hot, growth, emerging):
            if len(selected) >= max(top_n, 0):
                return selected, rank_maps
            if index >= len(ranking):
                continue
            row = ranking[index]
            name = str(row.get("full_name", ""))
            if not name or name in seen:
                continue
            selected.append(row)
            seen.add(name)
    return selected, rank_maps


def technical_summary(repo: Mapping[str, Any]) -> str:
    values = [
        str(repo.get("language") or "语言未标注"),
        str(repo.get("license") or "许可证未标注"),
    ]
    topic_values = topics(repo)[:5]
    if topic_values:
        values.append("Topics: " + " / ".join(topic_values))
    return " · ".join(values)


def push_activity(repo: Mapping[str, Any]) -> str:
    days = number(repo.get("days_since_push"))
    if days < 1:
        return "最近 1 天内仍有代码推送"
    if days <= 7:
        return f"最近约 {days:.0f} 天内仍有代码推送"
    if days <= 30:
        return f"最近约 {days:.0f} 天内有代码推送"
    return f"距最近代码推送约 {days:.0f} 天"


def reason_text(
    repo: Mapping[str, Any],
    rank_maps: Mapping[str, Mapping[str, int]],
    rank_limit: int = 20,
) -> str:
    name = str(repo.get("full_name", ""))
    parts: list[str] = []

    hot_rank = rank_maps.get("热度榜", {}).get(name)
    if hot_rank is not None and hot_rank <= rank_limit:
        parts.append(f"热度榜第 {hot_rank} 名（Hot {number(repo.get('hot_score')):.1f}）")

    growth_rank = rank_maps.get("增长榜", {}).get(name)
    if growth_rank is not None and growth_rank <= rank_limit:
        velocity = repo.get("star_velocity_previous")
        if velocity not in (None, ""):
            parts.append(
                f"增长榜第 {growth_rank} 名（近期约 {number(velocity):+,.1f} Stars/天）"
            )
        else:
            parts.append(f"增长榜第 {growth_rank} 名")

    emerging_rank = rank_maps.get("新兴榜", {}).get(name)
    if emerging_rank is not None and emerging_rank <= rank_limit:
        parts.append(
            f"新兴榜第 {emerging_rank} 名"
            f"（生命周期约 {number(repo.get('lifetime_star_velocity')):,.1f} Stars/天）"
        )

    parts.append(push_activity(repo))
    return "；".join(parts) + "。"


def build_intro_section(
    rows: Sequence[Repo],
    top_n: int = 12,
    *,
    emerging_max_age_days: int = 180,
    emerging_minimum_stars: int = 5,
) -> str:
    selected, rank_maps = select_featured(
        rows,
        top_n,
        emerging_max_age_days=emerging_max_age_days,
        emerging_minimum_stars=emerging_minimum_stars,
    )
    lines = [
        SECTION_START,
        "## 重点项目内容介绍",
        "",
        "> 本节根据 GitHub 项目简介、Topics 和本期榜单指标自动整理。"
        "项目简介保留仓库作者原意；“方向”和“入选理由”用于帮助快速判断项目定位。",
        "",
    ]

    if not selected:
        lines += ["暂无可介绍的项目。", "", SECTION_END]
        return "\n".join(lines)

    for index, repo in enumerate(selected, 1):
        name = str(repo.get("full_name") or "unknown/unknown")
        url = str(repo.get("url") or f"https://github.com/{name}")
        stars = integer(repo.get("stars"))
        forks = integer(repo.get("forks"))
        lines += [
            f"### {index}. [{name}]({url})",
            "",
            f"- **方向**：{project_category(repo)}",
            f"- **项目简介**：{compact(repo.get('description'))}",
            f"- **当前规模**：{stars:,} Stars · {forks:,} Forks",
            f"- **技术信息**：{technical_summary(repo)}",
            f"- **本期关注理由**：{reason_text(repo, rank_maps, max(20, top_n))}",
            "",
        ]

    lines.append(SECTION_END)
    return "\n".join(lines)


def inject_section(report: str, section: str) -> str:
    """Insert once, or replace a previously generated introduction section."""
    marked = re.compile(
        rf"{re.escape(SECTION_START)}.*?{re.escape(SECTION_END)}",
        flags=re.DOTALL,
    )
    if marked.search(report):
        return marked.sub(section, report, count=1)

    heading = f"\n{QUALITY_HEADING}"
    if heading in report:
        return report.replace(heading, f"\n{section}\n\n{QUALITY_HEADING}", 1)

    footer = "\n---\n"
    if footer in report:
        return report.replace(footer, f"\n{section}\n\n---\n", 1)

    return report.rstrip() + "\n\n" + section + "\n"


def load_rows(path: Path) -> list[Repo]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    if not rows:
        raise ValueError(f"No repository rows found in {path}")
    return rows


def report_date(report: str) -> str | None:
    match = re.search(r"^# AI Agent GitHub 雷达 — (\d{4}-\d{2}-\d{2})\s*$", report, re.MULTILINE)
    return match.group(1) if match else None


def enrich_report(
    report_path: Path,
    csv_path: Path,
    top_n: int = 12,
    *,
    emerging_max_age_days: int = 180,
    emerging_minimum_stars: int = 5,
    sync_dated_report: bool = True,
) -> list[Path]:
    rows = load_rows(csv_path)
    original = report_path.read_text(encoding="utf-8")
    section = build_intro_section(
        rows,
        top_n,
        emerging_max_age_days=emerging_max_age_days,
        emerging_minimum_stars=emerging_minimum_stars,
    )
    updated = inject_section(original, section)
    report_path.write_text(updated, encoding="utf-8")
    written = [report_path]

    day = report_date(updated)
    if sync_dated_report and day:
        dated = report_path.with_name(f"{day}.md")
        if dated != report_path:
            dated.write_text(updated, encoding="utf-8")
            written.append(dated)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="reports/latest.md")
    parser.add_argument("--csv", default="data/latest.csv")
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--emerging-max-age-days", type=int, default=180)
    parser.add_argument("--emerging-minimum-stars", type=int, default=5)
    parser.add_argument("--no-sync-dated-report", action="store_true")
    args = parser.parse_args()

    if args.top_n < 1:
        parser.error("--top-n must be at least 1")

    written = enrich_report(
        Path(args.report),
        Path(args.csv),
        args.top_n,
        emerging_max_age_days=args.emerging_max_age_days,
        emerging_minimum_stars=args.emerging_minimum_stars,
        sync_dated_report=not args.no_sync_dated_report,
    )
    print("Added project introductions to: " + ", ".join(str(path) for path in written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
