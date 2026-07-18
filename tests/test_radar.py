from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ai_agent_radar as radar  # noqa: E402


class RadarTests(unittest.TestCase):
    def make_repo(
        self,
        full_name: str,
        stars: int,
        forks: int,
        created_at: str = "2025-01-01T00:00:00Z",
        pushed_at: str = "2026-07-17T00:00:00Z",
    ) -> dict:
        return {
            "full_name": full_name,
            "owner": full_name.split("/", 1)[0],
            "name": full_name.split("/", 1)[1],
            "url": f"https://github.com/{full_name}",
            "description": "An AI agent framework",
            "stars": stars,
            "forks": forks,
            "open_issues": 10,
            "watchers": 0,
            "language": "Python",
            "license": "MIT",
            "topics": ["ai-agent"],
            "created_at": created_at,
            "updated_at": pushed_at,
            "pushed_at": pushed_at,
            "default_branch": "main",
            "size_kb": 100,
            "matched_queries": ["topic:ai-agent"],
        }

    def test_enrich_metrics_calculates_deltas(self) -> None:
        repos = [self.make_repo("example/fast-agent", 1_000, 100)]
        previous = {
            "_comparison_days": 1,
            "repositories": [{"full_name": "example/fast-agent", "stars": 900, "forks": 90}],
        }
        weekly = {
            "_comparison_days": 7,
            "repositories": [{"full_name": "example/fast-agent", "stars": 600, "forks": 60}],
        }

        radar.enrich_metrics(repos, previous, weekly, dt.date(2026, 7, 18))
        repo = repos[0]
        self.assertEqual(repo["star_delta_previous"], 100)
        self.assertEqual(repo["star_velocity_previous"], 100)
        self.assertEqual(repo["star_delta_week"], 400)
        self.assertEqual(repo["star_delta_7d_equivalent"], 400)
        self.assertGreater(repo["stable_growth_7d"], 0)

    def test_growth_ranking_prefers_fast_mover(self) -> None:
        repos = [
            self.make_repo("example/fast-agent", 1_000, 100),
            self.make_repo("example/large-agent", 20_000, 2_000),
        ]
        previous = {
            "_comparison_days": 1,
            "repositories": [
                {"full_name": "example/fast-agent", "stars": 900, "forks": 95},
                {"full_name": "example/large-agent", "stars": 19_995, "forks": 1_999},
            ],
        }
        weekly = {
            "_comparison_days": 7,
            "repositories": [
                {"full_name": "example/fast-agent", "stars": 600, "forks": 70},
                {"full_name": "example/large-agent", "stars": 19_950, "forks": 1_990},
            ],
        }

        radar.enrich_metrics(repos, previous, weekly, dt.date(2026, 7, 18))
        ranked = radar.sort_growth(repos)
        self.assertEqual(ranked[0]["full_name"], "example/fast-agent")
        self.assertGreater(ranked[0]["growth_score"], ranked[1]["growth_score"])

    def test_report_contains_required_sections(self) -> None:
        repos = [self.make_repo("example/agent", 500, 50, created_at="2026-05-01T00:00:00Z")]
        radar.enrich_metrics(repos, None, None, dt.date(2026, 7, 18))
        config = {
            "timezone": "America/Chicago",
            "report_top_n": 20,
            "emerging_max_age_days": 180,
            "emerging_minimum_stars": 5,
        }
        stats = {
            "successful_requests": 1,
            "total_requests": 1,
            "failures": [],
        }
        report = radar.format_report(
            repos,
            config,
            stats,
            dt.date(2026, 7, 18),
            dt.datetime(2026, 7, 18, 9, 15, tzinfo=dt.timezone(dt.timedelta(hours=-5))),
            None,
            None,
        )
        self.assertIn("## 增长最快", report)
        self.assertIn("## 当前最热", report)
        self.assertIn("## 新兴项目", report)
        self.assertIn("example/agent", report)

    def test_collect_filters_forks_and_irrelevant_projects(self) -> None:
        config = {
            "minimum_stars": 10,
            "emerging_minimum_stars": 5,
            "emerging_max_age_days": 180,
            "results_per_query": 50,
            "search_delay_seconds": 0,
            "queries": ["topic:ai-agent"],
            "search_sorts": ["stars"],
        }
        fixture = [
            {
                "full_name": "example/agent-framework",
                "html_url": "https://github.com/example/agent-framework",
                "description": "AI agent framework",
                "fork": False,
                "archived": False,
                "disabled": False,
                "stargazers_count": 100,
                "forks_count": 10,
                "open_issues_count": 2,
                "topics": ["ai-agent"],
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-07-17T00:00:00Z",
                "pushed_at": "2026-07-17T00:00:00Z",
                "language": "Python",
            },
            {
                "full_name": "example/forked-agent",
                "description": "AI agent",
                "fork": True,
                "archived": False,
                "stargazers_count": 100,
                "topics": ["ai-agent"],
            },
            {
                "full_name": "example/weather-app",
                "description": "Weather dashboard",
                "fork": False,
                "archived": False,
                "stargazers_count": 100,
                "topics": ["weather"],
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        repos, stats = radar.collect_repositories(config, client=None, fixture_items=fixture)
        self.assertEqual([repo["full_name"] for repo in repos], ["example/agent-framework"])
        self.assertEqual(stats["tracked_repositories"], 1)


if __name__ == "__main__":
    unittest.main()
