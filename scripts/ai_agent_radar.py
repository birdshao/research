#!/usr/bin/env python3
"""Build a daily GitHub radar for fast-growing and hot AI-agent projects."""

from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import gzip
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence
from zoneinfo import ZoneInfo

API_ROOT = "https://api.github.com"
Repo = dict[str, Any]


def log(message: str) -> None:
    print(f"[ai-agent-radar] {message}", flush=True)


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_config(path: Path) -> dict[str, Any]:
    config = load_json(path)
    if not isinstance(config, dict):
        raise ValueError("Config root must be a JSON object")
    defaults = {
        "timezone": "America/Chicago",
        "api_version": "2026-03-10",
        "minimum_stars": 10,
        "emerging_minimum_stars": 5,
        "emerging_max_age_days": 180,
        "results_per_query": 50,
        "report_top_n": 20,
        "snapshot_retention_days": 60,
        "search_delay_seconds": 0.4,
        "request_timeout_seconds": 30,
        "max_retries": 3,
        "search_sorts": ["stars", "updated"],
        "queries": [],
        "output": {
            "snapshot_dir": "data/snapshots",
            "latest_csv": "data/latest.csv",
            "report_dir": "reports",
            "latest_report": "reports/latest.md",
        },
    }
    merged = defaults | config
    merged["output"] = defaults["output"] | config.get("output", {})
    ZoneInfo(str(merged["timezone"]))
    if not merged["queries"]:
        raise ValueError("config.queries must not be empty")
    return merged


class GitHubAPI:
    def __init__(self, token: str | None, version: str, timeout: int, retries: int) -> None:
        self.token, self.version, self.timeout, self.retries = token, version, timeout, retries

    def search(self, query: str, sort: str, per_page: int) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode(
            {"q": query, "sort": sort, "order": "desc", "per_page": min(per_page, 100)}
        )
        url = f"{API_ROOT}/search/repositories?{params}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.version,
            "User-Agent": "ai-agent-radar/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                items = payload.get("items", []) if isinstance(payload, dict) else []
                if not isinstance(items, list):
                    raise RuntimeError("GitHub search returned an invalid items field")
                return [item for item in items if isinstance(item, dict)]
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last = RuntimeError(f"GitHub API HTTP {exc.code}: {body[:300]}")
                retryable = exc.code in {403, 429, 500, 502, 503, 504}
                if not retryable or attempt >= self.retries:
                    raise last from exc
                delay = self._delay(exc, attempt)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                if attempt >= self.retries:
                    break
                delay = min(2**attempt, 8)
            log(f"API request failed; retrying in {delay:.1f}s")
            time.sleep(delay)
        raise RuntimeError(f"GitHub API request failed: {last}")

    @staticmethod
    def _delay(exc: urllib.error.HTTPError, attempt: int) -> float:
        retry_after = exc.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 65.0)
            except ValueError:
                pass
        reset = exc.headers.get("X-RateLimit-Reset")
        if reset:
            try:
                return min(max(float(reset) - time.time() + 1, 1), 65)
            except ValueError:
                pass
        return float(min(5 * (attempt + 1), 30))


def add_candidate(store: MutableMapping[str, Repo], raw: Mapping[str, Any], source: str) -> None:
    name = raw.get("full_name")
    if not isinstance(name, str) or "/" not in name:
        return
    if name not in store:
        store[name] = dict(raw)
        store[name]["_matched_queries"] = [source]
    elif source not in store[name].setdefault("_matched_queries", []):
        store[name]["_matched_queries"].append(source)


def normalize(raw: Mapping[str, Any]) -> Repo | None:
    name = raw.get("full_name")
    if not isinstance(name, str) or raw.get("fork") or raw.get("archived") or raw.get("disabled"):
        return None
    topics = sorted({str(x).lower() for x in raw.get("topics", []) if isinstance(x, str)})
    license_value = raw.get("license")
    license_id = license_value.get("spdx_id") if isinstance(license_value, Mapping) else None
    if license_id in {"NOASSERTION", "OTHER"}:
        license_id = None
    description = " ".join(str(raw.get("description") or "").split())[:240]
    return {
        "full_name": name,
        "owner": name.split("/", 1)[0],
        "name": name.split("/", 1)[1],
        "url": raw.get("html_url") or f"https://github.com/{name}",
        "description": description,
        "stars": safe_int(raw.get("stargazers_count")),
        "forks": safe_int(raw.get("forks_count")),
        "open_issues": safe_int(raw.get("open_issues_count")),
        "language": raw.get("language") if isinstance(raw.get("language"), str) else None,
        "license": license_id,
        "topics": topics,
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "pushed_at": raw.get("pushed_at"),
        "default_branch": raw.get("default_branch"),
        "size_kb": safe_int(raw.get("size")),
        "matched_queries": sorted(set(raw.get("_matched_queries", []))),
    }


def relevant(repo: Mapping[str, Any]) -> bool:
    exact = {
        "ai-agent", "ai-agents", "agentic-ai", "llm-agent", "llm-agents",
        "autonomous-agents", "multi-agent", "multi-agent-systems", "agent-framework",
    }
    topics = set(repo.get("topics", []))
    if topics & exact:
        return True
    text = " ".join(
        [str(repo.get("full_name", "")), str(repo.get("description", "")), " ".join(topics)]
    ).lower()
    return any(
        phrase in text
        for phrase in (
            "ai agent", "ai-agent", "llm agent", "llm-agent", "agentic ai",
            "agentic-ai", "autonomous agent", "multi agent", "multi-agent",
            "agent framework", "agent orchestration",
        )
    )


def collect_repositories(
    config: Mapping[str, Any],
    client: GitHubAPI | None,
    fixture_items: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[Repo], dict[str, Any]]:
    candidates: dict[str, Repo] = {}
    failures: list[dict[str, str]] = []
    total = successful = 0
    if fixture_items is not None:
        total = successful = 1
        for item in fixture_items:
            add_candidate(candidates, item, "fixture")
    else:
        if client is None:
            raise ValueError("GitHub client is required")
        for query in config["queries"]:
            for sort in config["search_sorts"]:
                total += 1
                source = f"{query} | sort:{sort}"
                try:
                    items = client.search(str(query), str(sort), int(config["results_per_query"]))
                    for item in items:
                        add_candidate(candidates, item, source)
                    successful += 1
                    log(f"Collected {len(items):>3} results from {source}")
                except Exception as exc:
                    failures.append({"source": source, "error": str(exc)[:500]})
                    log(f"WARNING: {source}: {exc}")
                time.sleep(float(config.get("search_delay_seconds", 0)))
    if successful == 0:
        raise RuntimeError("All GitHub searches failed")

    now = dt.datetime.now(dt.timezone.utc)
    repos: list[Repo] = []
    for raw in candidates.values():
        repo = normalize(raw)
        if repo is None or not relevant(repo):
            continue
        created = parse_time(repo.get("created_at"))
        age = max((now - created).total_seconds() / 86400, 1) if created else 99999
        enough = safe_int(repo["stars"]) >= int(config["minimum_stars"])
        emerging = (
            safe_int(repo["stars"]) >= int(config["emerging_minimum_stars"])
            and age <= int(config["emerging_max_age_days"])
        )
        if enough or emerging:
            repos.append(repo)
    repos.sort(key=lambda x: (safe_int(x["stars"]), x["full_name"]), reverse=True)
    return repos, {
        "total_requests": total,
        "successful_requests": successful,
        "failed_requests": len(failures),
        "failures": failures,
        "raw_unique_candidates": len(candidates),
        "tracked_repositories": len(repos),
    }


def load_snapshot(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid snapshot: {path}")
    return payload


def write_snapshot(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def choose_baselines(directory: Path, today: dt.date) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    snapshots: list[tuple[dt.date, Path]] = []
    if directory.exists():
        for path in directory.glob("????-??-??.json.gz"):
            try:
                day = dt.date.fromisoformat(path.name[:10])
            except ValueError:
                continue
            if day < today:
                snapshots.append((day, path))
    previous_candidates = [item for item in snapshots if 1 <= (today - item[0]).days <= 3]
    weekly_candidates = [item for item in snapshots if 5 <= (today - item[0]).days <= 9]

    def loaded(item: tuple[dt.date, Path] | None) -> dict[str, Any] | None:
        if item is None:
            return None
        day, path = item
        data = load_snapshot(path)
        data["_comparison_days"] = (today - day).days
        return data

    previous = max(previous_candidates, default=None, key=lambda x: x[0])
    target = today - dt.timedelta(days=7)
    weekly = min(weekly_candidates, default=None, key=lambda x: abs((x[0] - target).days))
    return loaded(previous), loaded(weekly)


def snapshot_map(snapshot: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not snapshot or not isinstance(snapshot.get("repositories"), list):
        return {}
    return {
        str(repo["full_name"]): repo
        for repo in snapshot["repositories"]
        if isinstance(repo, Mapping) and isinstance(repo.get("full_name"), str)
    }


def percentile(repositories: Sequence[Mapping[str, Any]], key: str) -> list[float]:
    parsed: list[float | None] = []
    positive: list[float] = []
    for repo in repositories:
        try:
            value = float(repo.get(key)) if repo.get(key) is not None else None
        except (TypeError, ValueError):
            value = None
        if value is None or not math.isfinite(value) or value <= 0:
            parsed.append(None)
        else:
            parsed.append(value)
            positive.append(value)
    positive.sort()
    if not positive:
        return [0.0] * len(repositories)
    result: list[float] = []
    for value in parsed:
        if value is None:
            result.append(0.0)
        else:
            left, right = bisect.bisect_left(positive, value), bisect.bisect_right(positive, value)
            result.append(((left + right) / 2) / len(positive))
    return result


def enrich_metrics(
    repositories: list[Repo],
    previous_snapshot: Mapping[str, Any] | None,
    weekly_snapshot: Mapping[str, Any] | None,
    today: dt.date,
) -> None:
    previous, weekly = snapshot_map(previous_snapshot), snapshot_map(weekly_snapshot)
    previous_days = safe_int(previous_snapshot.get("_comparison_days")) if previous_snapshot else 0
    weekly_days = safe_int(weekly_snapshot.get("_comparison_days")) if weekly_snapshot else 0
    now = dt.datetime.combine(today, dt.time.min, tzinfo=dt.timezone.utc)

    for repo in repositories:
        name, stars, forks = str(repo["full_name"]), safe_int(repo["stars"]), safe_int(repo["forks"])
        created, pushed = parse_time(repo.get("created_at")), parse_time(repo.get("pushed_at"))
        age = max((now - created).total_seconds() / 86400, 1) if created else 3650
        since_push = max((now - pushed).total_seconds() / 86400, 0) if pushed else 3650
        old, week = previous.get(name), weekly.get(name)
        delta = stars - safe_int(old.get("stars")) if old is not None and previous_days else None
        delta_week = stars - safe_int(week.get("stars")) if week is not None and weekly_days else None
        fork_delta = forks - safe_int(old.get("forks")) if old is not None and previous_days else None
        velocity = delta / previous_days if delta is not None else None
        weekly_velocity = delta_week / weekly_days if delta_week is not None else None
        stable = None
        if delta_week is not None and week is not None:
            stable = (delta_week / max(safe_int(week.get("stars")), 50)) * (7 / weekly_days)
        repo.update(
            age_days=round(age, 2),
            days_since_push=round(since_push, 2),
            freshness=math.exp(-since_push / 30),
            lifetime_star_velocity=stars / age,
            previous_comparison_days=previous_days if old is not None else None,
            weekly_comparison_days=weekly_days if week is not None else None,
            star_delta_previous=delta,
            star_velocity_previous=velocity,
            star_delta_week=delta_week,
            star_velocity_week=weekly_velocity,
            star_delta_7d_equivalent=weekly_velocity * 7 if weekly_velocity is not None else None,
            stable_growth_7d=stable,
            fork_delta_previous=fork_delta,
            new_to_radar=old is None,
        )

    ranks = {
        key: percentile(repositories, key)
        for key in (
            "stars", "forks", "star_velocity_previous", "star_velocity_week",
            "stable_growth_7d", "lifetime_star_velocity",
        )
    }
    for i, repo in enumerate(repositories):
        fresh = float(repo.get("freshness") or 0)
        recent, week = ranks["star_velocity_previous"][i], ranks["star_velocity_week"][i]
        relative, lifetime = ranks["stable_growth_7d"][i], ranks["lifetime_star_velocity"][i]
        repo["growth_score"] = round(100 * (0.30 * recent + 0.30 * week + 0.20 * relative + 0.15 * lifetime + 0.05 * fresh), 2)
        repo["hot_score"] = round(100 * (0.20 * ranks["stars"][i] + 0.10 * ranks["forks"][i] + 0.20 * recent + 0.20 * week + 0.15 * relative + 0.10 * lifetime + 0.05 * fresh), 2)
        repo["emerging_score"] = round(100 * (0.55 * lifetime + 0.20 * week + 0.15 * relative + 0.10 * fresh), 2)


def sort_growth(repositories: Sequence[Repo]) -> list[Repo]:
    return sorted(repositories, key=lambda x: (float(x.get("growth_score") or 0), float(x.get("star_velocity_previous") or 0), float(x.get("star_velocity_week") or 0), safe_int(x.get("stars"))), reverse=True)


def sort_hot(repositories: Sequence[Repo]) -> list[Repo]:
    return sorted(repositories, key=lambda x: (float(x.get("hot_score") or 0), safe_int(x.get("stars"))), reverse=True)


def sort_emerging(repositories: Sequence[Repo], config: Mapping[str, Any]) -> list[Repo]:
    candidates = [
        repo for repo in repositories
        if float(repo.get("age_days") if repo.get("age_days") is not None else 99999) <= int(config["emerging_max_age_days"])
        and safe_int(repo.get("stars")) >= int(config["emerging_minimum_stars"])
    ]
    return sorted(candidates, key=lambda x: (float(x.get("emerging_score") or 0), float(x.get("lifetime_star_velocity") or 0), safe_int(x.get("stars"))), reverse=True)


def signed(value: Any, decimals: int = 0) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+,.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def percent(value: Any) -> str:
    return "—" if value is None else f"{float(value) * 100:+.1f}%"


def age_text(value: Any) -> str:
    try:
        days = float(value)
    except (TypeError, ValueError):
        return "—"
    if days < 1:
        return "<1天"
    if days < 30:
        return f"{days:.0f}天"
    if days < 365:
        return f"{days / 30:.1f}月"
    return f"{days / 365:.1f}年"


def link(repo: Mapping[str, Any]) -> str:
    name = str(repo.get("full_name", "unknown")).replace("|", "\\|")
    return f"[{name}]({repo.get('url') or f'https://github.com/{name}'})"


def format_report(
    repositories: Sequence[Repo],
    config: Mapping[str, Any],
    query_stats: Mapping[str, Any],
    day: dt.date,
    generated_at: dt.datetime,
    previous_snapshot: Mapping[str, Any] | None,
    weekly_snapshot: Mapping[str, Any] | None,
) -> str:
    top = int(config["report_top_n"])
    growth, hot, emerging = sort_growth(repositories)[:top], sort_hot(repositories)[:top], sort_emerging(repositories, config)[:top]
    comparable = sum(x.get("star_delta_previous") is not None for x in repositories)
    comparable_week = sum(x.get("star_delta_week") is not None for x in repositories)
    active = sum(x.get("days_since_push") is not None and float(x["days_since_push"]) <= 30 for x in repositories)
    new = sum(bool(x.get("new_to_radar")) for x in repositories)
    lines = [
        f"# AI Agent GitHub 雷达 — {day.isoformat()}", "",
        f"> 统计时间：{generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}  ·  时区：`{config['timezone']}`  ·  候选项目：**{len(repositories)}**  ·  成功查询：**{query_stats['successful_requests']}/{query_stats['total_requests']}**",
        "", "## 今日概览", "", "| 指标 | 数值 |", "|---|---:|",
        f"| 纳入跟踪的项目 | {len(repositories)} |", f"| 与最近快照可比 | {comparable} |",
        f"| 与约 7 日前快照可比 | {comparable_week} |", f"| 最近 30 天有推送 | {active} |",
        f"| 今日首次进入雷达 | {new} |", "", "## 增长最快", "",
        "增长分综合近期 Star 日增速、约 7 日增速、稳定化相对增长、项目年龄归一化增速和活跃度。", "",
        "| # | 项目 | Stars | 近期日增 | 7日增量* | 7日增幅* | 最近推送 | Growth |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {i} | {link(r)} | {safe_int(r.get('stars')):,} | {signed(r.get('star_velocity_previous'), 1)} | {signed(r.get('star_delta_7d_equivalent'))} | {percent(r.get('stable_growth_7d'))} | {age_text(r.get('days_since_push'))} | {float(r.get('growth_score') or 0):.1f} |"
        for i, r in enumerate(growth, 1)
    ] or ["| — | 暂无数据 | — | — | — | — | — | — |"]
    lines += ["", "## 当前最热", "", "热度分在增长信号之外，同时考虑累计 Stars、Forks 与最近活跃度。", "", "| # | 项目 | Stars | Forks | 近期日增 | 7日增量* | 活跃度 | Hot |", "|---:|---|---:|---:|---:|---:|---:|---:|"]
    lines += [
        f"| {i} | {link(r)} | {safe_int(r.get('stars')):,} | {safe_int(r.get('forks')):,} | {signed(r.get('star_velocity_previous'), 1)} | {signed(r.get('star_delta_7d_equivalent'))} | {age_text(r.get('days_since_push'))} | {float(r.get('hot_score') or 0):.1f} |"
        for i, r in enumerate(hot, 1)
    ] or ["| — | 暂无数据 | — | — | — | — | — | — |"]
    lines += ["", "## 新兴项目", "", f"项目年龄不超过 {config['emerging_max_age_days']} 天，且至少 {config['emerging_minimum_stars']} Stars。", "", "| # | 项目 | Stars | Stars/天 | 7日增量* | 创建天数 | 最近推送 | Emerging |", "|---:|---|---:|---:|---:|---:|---:|---:|"]
    lines += [
        f"| {i} | {link(r)} | {safe_int(r.get('stars')):,} | {float(r.get('lifetime_star_velocity') or 0):.1f} | {signed(r.get('star_delta_7d_equivalent'))} | {float(r.get('age_days') or 0):.0f} | {age_text(r.get('days_since_push'))} | {float(r.get('emerging_score') or 0):.1f} |"
        for i, r in enumerate(emerging, 1)
    ] or ["| — | 暂无符合条件的项目 | — | — | — | — | — | — |"]
    lines += ["", "## 口径与数据质量", "", "- `近期日增` 使用最近 1–3 天内可用快照折算为每日增量。", "- `7日增量*` 与 `7日增幅*` 使用距今 5–9 天的最接近快照折算为 7 天口径。", "- 相对增长以至少 50 Stars 为分母进行稳定化，避免极小项目因少量增长占据榜首。", "- GitHub Search API 结果受搜索排序、索引与候选集合影响；本榜适合发现趋势，不等同于全站精确 Star 事件统计。"]
    if previous_snapshot is None or weekly_snapshot is None:
        missing = "和".join(name for value, name in ((previous_snapshot, "近期"), (weekly_snapshot, "约 7 日")) if value is None)
        lines.append(f"- 当前缺少{missing}历史基线；首轮榜单会更多依赖累计规模、项目年龄归一化增速与活跃度。")
    failures = query_stats.get("failures", [])
    if failures:
        lines += ["", "### 查询失败", ""] + [f"- `{x.get('source', 'unknown')}`：{x.get('error', 'unknown error')}" for x in failures[:10] if isinstance(x, Mapping)]
    lines += ["", "---", "", "由 GitHub Actions 每日自动生成。完整机器可读数据见 `data/latest.csv` 与 `data/snapshots/`。", ""]
    return "\n".join(lines)


def write_csv(path: Path, repositories: Sequence[Repo]) -> None:
    fields = ["full_name", "url", "description", "stars", "forks", "open_issues", "language", "license", "created_at", "pushed_at", "age_days", "days_since_push", "star_delta_previous", "star_velocity_previous", "star_delta_week", "star_delta_7d_equivalent", "stable_growth_7d", "lifetime_star_velocity", "growth_score", "hot_score", "emerging_score", "topics", "matched_queries"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fields, extrasaction="ignore")
        writer.writeheader()
        for repo in sort_hot(repositories):
            row = dict(repo)
            row["topics"] = ";".join(repo.get("topics", []))
            row["matched_queries"] = ";".join(repo.get("matched_queries", []))
            writer.writerow(row)


def cleanup(directory: Path, today: dt.date, retention: int) -> None:
    cutoff = today - dt.timedelta(days=max(retention, 1))
    for path in directory.glob("????-??-??.json.gz") if directory.exists() else []:
        try:
            if dt.date.fromisoformat(path.name[:10]) < cutoff:
                path.unlink()
        except ValueError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.environ.get("RADAR_CONFIG", "config.json"))
    parser.add_argument("--fixture")
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    base = config_path.resolve().parent
    now = dt.datetime.now(ZoneInfo(str(config["timezone"])))
    today = dt.date.fromisoformat(args.date) if args.date else now.date()
    fixture = None
    if args.fixture:
        fixture_payload = load_json(Path(args.fixture))
        fixture = fixture_payload.get("items", []) if isinstance(fixture_payload, dict) else fixture_payload
        if not isinstance(fixture, list):
            raise ValueError("Fixture must be a list or contain an items list")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    client = None if fixture is not None else GitHubAPI(token, str(config["api_version"]), int(config["request_timeout_seconds"]), int(config["max_retries"]))
    repositories, stats = collect_repositories(config, client, fixture)

    output = config["output"]
    snapshots = base / str(output["snapshot_dir"])
    previous, weekly = choose_baselines(snapshots, today)
    enrich_metrics(repositories, previous, weekly, today)
    report = format_report(repositories, config, stats, today, now, previous, weekly)
    if args.dry_run:
        print(report)
        return 0

    reports = base / str(output["report_dir"])
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{today.isoformat()}.md").write_text(report, encoding="utf-8")
    latest_report = base / str(output["latest_report"])
    latest_report.parent.mkdir(parents=True, exist_ok=True)
    latest_report.write_text(report, encoding="utf-8")
    write_csv(base / str(output["latest_csv"]), repositories)
    snapshot_repos = [{key: repo.get(key) for key in ("full_name", "url", "description", "stars", "forks", "open_issues", "language", "license", "topics", "created_at", "updated_at", "pushed_at", "age_days", "days_since_push", "growth_score", "hot_score", "emerging_score")} for repo in repositories]
    snapshot_path = snapshots / f"{today.isoformat()}.json.gz"
    write_snapshot(snapshot_path, {"schema_version": 1, "date": today.isoformat(), "generated_at": now.isoformat(), "timezone": config["timezone"], "query_stats": stats, "repositories": snapshot_repos})
    cleanup(snapshots, today, int(config["snapshot_retention_days"]))
    log(f"Tracked repositories: {len(repositories)}")
    log(f"Report: {reports / f'{today.isoformat()}.md'}")
    log(f"Snapshot: {snapshot_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        log(f"ERROR: {exc}")
        raise
