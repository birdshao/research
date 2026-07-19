#!/usr/bin/env python3
"""Add GitHub community evaluation and a clear usage recommendation to the radar report."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import enrich_report as intro

API_ROOT = "https://api.github.com"
SECTION_START = "<!-- AI_AGENT_COMMUNITY_REVIEW_START -->"
SECTION_END = "<!-- AI_AGENT_COMMUNITY_REVIEW_END -->"
QUALITY_HEADING = "## 口径与数据质量"
Repo = dict[str, str]
Review = dict[str, Any]


def number(value: Any) -> float:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def integer(value: Any) -> int:
    return int(number(value))


def ratio(part: int, total: int) -> float | None:
    return part / total if total else None


def topics(repo: Mapping[str, Any]) -> list[str]:
    value = repo.get("topics", "")
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


class GitHubCommunityClient:
    """Read three public endpoints per project; 12 projects use at most 36 requests."""

    def __init__(
        self,
        token: str | None = None,
        api_version: str = "2026-03-10",
        timeout: int = 30,
        retries: int = 2,
        request_delay: float = 0.2,
    ) -> None:
        self.token = token.strip() if token else None
        self.api_version = api_version
        self.timeout = timeout
        self.retries = retries
        self.request_delay = max(request_delay, 0)

    @staticmethod
    def repo_path(full_name: str) -> str:
        if full_name.count("/") != 1:
            raise ValueError(f"Invalid repository name: {full_name}")
        owner, name = full_name.split("/", 1)
        return f"/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(name, safe='')}"

    def get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        allow_not_found: bool = False,
    ) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = f"{API_ROOT}{path}" + (f"?{query}" if query else "")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
            "User-Agent": "ai-agent-radar-community-review/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                if self.request_delay:
                    time.sleep(self.request_delay)
                return json.loads(raw.decode("utf-8")) if raw else None
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and allow_not_found:
                    return None
                body = exc.read().decode("utf-8", errors="replace")
                last = RuntimeError(f"GitHub API HTTP {exc.code}: {body[:200]}")
                if exc.code not in {403, 429, 500, 502, 503, 504} or attempt >= self.retries:
                    raise last from exc
                time.sleep(min(2 ** attempt, 8))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                if attempt >= self.retries:
                    raise RuntimeError(f"GitHub API request failed: {last}") from exc
                time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"GitHub API request failed: {last}")

    def profile(self, full_name: str) -> Mapping[str, Any] | None:
        value = self.get(self.repo_path(full_name) + "/community/profile", allow_not_found=True)
        return value if isinstance(value, Mapping) else None

    def issues(self, full_name: str, per_page: int = 30) -> list[Mapping[str, Any]]:
        value = self.get(
            self.repo_path(full_name) + "/issues",
            {"state": "all", "sort": "updated", "direction": "desc", "per_page": min(per_page, 100)},
        )
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, Mapping) and "pull_request" not in item]

    def contributors(self, full_name: str, per_page: int = 100) -> list[Mapping[str, Any]]:
        value = self.get(
            self.repo_path(full_name) + "/contributors",
            {"anon": "1", "per_page": min(per_page, 100)},
            allow_not_found=True,
        )
        return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def safe_call(label: str, operation: Any, errors: list[str]) -> tuple[Any, bool]:
    try:
        return operation(), True
    except Exception as exc:  # One unavailable endpoint must not break the daily report.
        errors.append(f"{label}: {str(exc)[:160]}")
        return None, False


def collect_signals(repo: Mapping[str, Any], client: GitHubCommunityClient) -> Review:
    full_name = str(repo.get("full_name", ""))
    errors: list[str] = []
    profile, profile_ok = safe_call("community_profile", lambda: client.profile(full_name), errors)
    issue_rows, issues_ok = safe_call("issues", lambda: client.issues(full_name), errors)
    contributor_rows, contributors_ok = safe_call("contributors", lambda: client.contributors(full_name), errors)
    issue_rows = issue_rows if isinstance(issue_rows, list) else []
    contributor_rows = contributor_rows if isinstance(contributor_rows, list) else []

    health = integer(profile.get("health_percentage")) if isinstance(profile, Mapping) else None
    closed = sum(str(item.get("state")) == "closed" for item in issue_rows)
    engaged = sum(integer(item.get("comments")) > 0 for item in issue_rows)
    risk_terms = {"bug", "security", "regression", "crash", "critical", "breaking"}
    risky_open = 0
    for item in issue_rows:
        if str(item.get("state")) != "open":
            continue
        labels = item.get("labels") if isinstance(item.get("labels"), list) else []
        names = {
            str(label.get("name", "")).lower()
            for label in labels
            if isinstance(label, Mapping)
        }
        title = str(item.get("title", "")).lower()
        if names & risk_terms or any(term in title for term in risk_terms):
            risky_open += 1

    contributions = [integer(item.get("contributions")) for item in contributor_rows]
    total_contributions = sum(contributions)
    top_share = max(contributions, default=0) / total_contributions if total_contributions else None
    available = [isinstance(profile, Mapping), issues_ok, contributors_ok]
    return {
        "full_name": full_name,
        "community_health_percentage": health,
        "issue_sample_count": len(issue_rows),
        "closed_issue_sample_count": closed,
        "issue_close_ratio": ratio(closed, len(issue_rows)),
        "issue_engagement_ratio": ratio(engaged, len(issue_rows)),
        "risky_open_issue_sample_count": risky_open,
        "risky_open_issue_ratio": ratio(risky_open, len(issue_rows)),
        "contributor_count_sample": len(contributor_rows),
        "contributors_at_least_100": len(contributor_rows) >= 100,
        "top_contributor_share": top_share,
        "signal_coverage": sum(available) / len(available),
        "errors": errors,
    }


def maintenance_points(days: float) -> float:
    if days <= 1:
        return 25
    if days <= 7:
        return 23
    if days <= 14:
        return 20
    if days <= 30:
        return 16
    if days <= 90:
        return 9
    if days <= 180:
        return 4
    return 0


def adoption_points(stars: int, forks: int) -> float:
    star_points = 10 if stars >= 100_000 else 9 if stars >= 50_000 else 8 if stars >= 10_000 else 7 if stars >= 5_000 else 5 if stars >= 1_000 else 3 if stars >= 100 else 1
    fork_points = 5 if forks >= 5_000 else 4 if forks >= 1_000 else 3 if forks >= 250 else 2 if forks >= 50 else 1 if forks >= 10 else 0
    return star_points + fork_points


def contributor_points(count: int, top_share: float | None) -> float:
    points = 10 if count >= 100 else 9 if count >= 50 else 8 if count >= 20 else 7 if count >= 10 else 5 if count >= 5 else 3 if count >= 2 else 1 if count == 1 else 5
    if top_share is not None and count >= 5 and top_share >= 0.85:
        points -= 2
    return max(points, 0)


def score(repo: Mapping[str, Any], raw: Review) -> Review:
    days = number(repo.get("days_since_push"))
    stars, forks = integer(repo.get("stars")), integer(repo.get("forks"))
    license_value = str(repo.get("license") or "").strip()
    health = raw.get("community_health_percentage")
    health_points = number(health) * 0.20 if health is not None else 10

    issue_count = integer(raw.get("issue_sample_count"))
    if issue_count >= 5:
        issue_points = 17 * number(raw.get("issue_close_ratio")) + 8 * number(raw.get("issue_engagement_ratio"))
    elif issue_count:
        issue_points = 10 + 9 * number(raw.get("issue_close_ratio")) + 4 * number(raw.get("issue_engagement_ratio"))
    else:
        issue_points = 12.5

    value = (
        maintenance_points(days)
        + adoption_points(stars, forks)
        + min(max(health_points, 0), 20)
        + min(max(issue_points, 0), 25)
        + contributor_points(integer(raw.get("contributor_count_sample")), raw.get("top_contributor_share"))
        + (5 if license_value else 0)
    )
    value = round(max(min(value, 100), 0), 1)

    warnings: list[str] = []
    if not license_value:
        warnings.append("未标注明确开源许可证")
    if days > 90:
        warnings.append(f"距最近代码推送约 {days:.0f} 天")
    elif days > 30:
        warnings.append(f"最近约 {days:.0f} 天未推送代码")
    if health is not None and number(health) < 50:
        warnings.append(f"社区健康档案仅 {integer(health)}%")
    if issue_count >= 8 and number(raw.get("issue_close_ratio")) < 0.4:
        warnings.append("近期活跃 Issue 样本关闭率偏低")
    if issue_count >= 8 and number(raw.get("risky_open_issue_ratio")) >= 0.3:
        warnings.append("Bug/安全/回归类开放 Issue 信号较多")
    contributors = integer(raw.get("contributor_count_sample"))
    if contributors <= 2 and raw.get("signal_coverage", 0) >= 0.67:
        warnings.append("贡献者样本较集中，存在维护者依赖")
    if raw.get("top_contributor_share") is not None and number(raw.get("top_contributor_share")) >= 0.85:
        warnings.append("提交高度集中于单一贡献者")
    if number(raw.get("signal_coverage")) < 0.67:
        warnings.append("可用社区信号有限")

    if number(raw.get("signal_coverage")) < 0.34:
        verdict = "信息不足，建议先小范围试用"
    elif value >= 82:
        verdict = "值得使用"
    elif value >= 70:
        verdict = "值得试用"
    elif value >= 58:
        verdict = "谨慎试用"
    else:
        verdict = "暂不建议直接用于关键生产"
    if (not license_value or days > 180) and verdict in {"值得使用", "值得试用"}:
        verdict = "谨慎试用"

    coverage = number(raw.get("signal_coverage"))
    confidence = "中等" if coverage >= 0.67 else "较低"
    result = dict(raw)
    result.update(
        url=str(repo.get("url") or f"https://github.com/{repo.get('full_name', '')}"),
        category=intro.project_category(repo),
        stars=stars,
        forks=forks,
        license=license_value or None,
        days_since_push=round(days, 2),
        community_score=value,
        verdict=verdict,
        confidence=confidence,
        warnings=warnings,
    )
    return result


def percent(value: Any) -> str:
    return "—" if value is None else f"{number(value) * 100:.0f}%"


def signal_text(repo: Mapping[str, Any], review: Mapping[str, Any]) -> str:
    parts = [f"最近推送约 {number(repo.get('days_since_push')):.0f} 天前"]
    health = review.get("community_health_percentage")
    parts.append(f"社区健康 {integer(health)}%" if health is not None else "社区健康数据不可用")
    count = integer(review.get("issue_sample_count"))
    if count:
        issue = f"活跃 Issue 样本关闭 {integer(review.get('closed_issue_sample_count'))}/{count}（{percent(review.get('issue_close_ratio'))}）"
        risky = integer(review.get("risky_open_issue_sample_count"))
        if risky:
            issue += f"，{risky} 条开放 Issue 带风险信号"
        parts.append(issue)
    else:
        parts.append("Issue 样本不足")
    contributors = integer(review.get("contributor_count_sample"))
    parts.append("贡献者至少 100 人" if review.get("contributors_at_least_100") else f"贡献者样本 {contributors} 人")
    return "；".join(parts) + "。"


def usage_advice(repo: Mapping[str, Any], review: Mapping[str, Any]) -> str:
    verdict = str(review.get("verdict", "谨慎试用"))
    if intro.project_category(repo) == "教程、案例与学习资源":
        return "适合作为学习、选型和原型参考，但示例代码不应未经审查直接进入生产。"
    if verdict == "值得使用":
        return "可列入优先试用清单；生产采用前仍需核对安全边界、数据处理和版本兼容性。"
    if verdict == "值得试用":
        return "适合个人、PoC 或小团队验证；关键业务接入前建议完成回归测试和安全评估。"
    if verdict == "谨慎试用":
        return "建议在隔离环境、小规模验证，观察维护响应和版本稳定性后再扩大使用。"
    if verdict.startswith("信息不足"):
        return "先在非关键场景验证安装、核心流程和升级路径，再决定是否长期采用。"
    return "当前更适合研究和技术评估，不建议直接进入关键生产系统。"


def build_section(rows: Sequence[Repo], reviews: Mapping[str, Review], top_n: int) -> str:
    selected, _ = intro.select_featured(rows, top_n)
    lines = [
        SECTION_START,
        "## 社区评价与使用建议",
        "",
        "> “是否值得使用”基于 GitHub 原生公开信号自动评估：近期维护、采用度、社区健康档案、"
        "活跃 Issue 样本、贡献者广度和许可证。它不是用户口碑调查、安全审计或生产可用性保证。",
        "",
        "| 项目 | 是否值得使用 | 社区分 | 置信度 | 核心依据 |",
        "|---|---|---:|---|---|",
    ]
    for repo in selected:
        name = str(repo.get("full_name", "unknown/unknown"))
        url = str(repo.get("url") or f"https://github.com/{name}")
        item = reviews.get(name, {})
        lines.append(
            f"| [{name}]({url}) | **{item.get('verdict', '信息不足')}** | "
            f"{number(item.get('community_score')):.1f}/100 | {item.get('confidence', '较低')} | "
            f"{signal_text(repo, item).replace('|', '\\|')} |"
        )

    lines += ["", "### 逐项判断", ""]
    for index, repo in enumerate(selected, 1):
        name = str(repo.get("full_name", "unknown/unknown"))
        url = str(repo.get("url") or f"https://github.com/{name}")
        item = reviews.get(name, {})
        warnings = item.get("warnings") if isinstance(item.get("warnings"), list) else []
        risk = "；".join(str(value) for value in warnings[:4]) + "。" if warnings else "未发现明显的维护与社区结构风险信号，但仍需自行验证安全性与兼容性。"
        lines += [
            f"#### {index}. [{name}]({url})",
            "",
            f"- **是否值得使用**：**{item.get('verdict', '信息不足')}**（社区分 {number(item.get('community_score')):.1f}/100，{item.get('confidence', '较低')}置信度）",
            f"- **社区评价**：{signal_text(repo, item)}",
            f"- **主要风险**：{risk}",
            f"- **使用建议**：{usage_advice(repo, item)}",
            "",
        ]
    lines.append(SECTION_END)
    return "\n".join(lines)


def inject(report: str, section: str) -> str:
    marked = re.compile(rf"{re.escape(SECTION_START)}.*?{re.escape(SECTION_END)}", re.DOTALL)
    if marked.search(report):
        return marked.sub(section, report, count=1)
    heading = f"\n{QUALITY_HEADING}"
    if heading in report:
        return report.replace(heading, f"\n{section}\n\n{QUALITY_HEADING}", 1)
    return report.rstrip() + "\n\n" + section + "\n"


def enrich(
    report_path: Path,
    csv_path: Path,
    output_json: Path,
    client: GitHubCommunityClient,
    top_n: int = 12,
) -> list[Path]:
    rows = intro.load_rows(csv_path)
    selected, _ = intro.select_featured(rows, top_n)
    reviews = {
        str(repo.get("full_name", "")): score(repo, collect_signals(repo, client))
        for repo in selected
    }
    report = inject(report_path.read_text(encoding="utf-8"), build_section(rows, reviews, top_n))
    report_path.write_text(report, encoding="utf-8")
    written = [report_path]
    day = intro.report_date(report)
    if day:
        dated_report = report_path.with_name(f"{day}.md")
        dated_report.write_text(report, encoding="utf-8")
        written.append(dated_report)

    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "report_date": day,
        "methodology": {
            "score_range": "0-100",
            "weights": {
                "recent_maintenance": 25,
                "stars_and_forks_adoption": 15,
                "community_profile_health": 20,
                "recent_active_issue_sample": 25,
                "contributor_breadth": 10,
                "license_clarity": 5,
            },
            "disclaimer": "GitHub-native heuristic; not a user survey, security audit, or production guarantee.",
        },
        "projects": [reviews[str(repo.get("full_name", ""))] for repo in selected],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output_json.write_text(text, encoding="utf-8")
    written.append(output_json)
    if day:
        dated_json = output_json.with_name(f"{day}.json")
        dated_json.write_text(text, encoding="utf-8")
        written.append(dated_json)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="reports/latest.md")
    parser.add_argument("--csv", default="data/latest.csv")
    parser.add_argument("--output-json", default="data/community/latest.json")
    parser.add_argument("--top-n", type=int, default=12)
    args = parser.parse_args()
    if args.top_n < 1:
        parser.error("--top-n must be at least 1")
    client = GitHubCommunityClient(
        token=os.environ.get("COMMUNITY_GH_TOKEN"),
        api_version=os.environ.get("GITHUB_API_VERSION", "2026-03-10"),
    )
    written = enrich(Path(args.report), Path(args.csv), Path(args.output_json), client, args.top_n)
    print("Added community evaluation to: " + ", ".join(str(path) for path in written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
