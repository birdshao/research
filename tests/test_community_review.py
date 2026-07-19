from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import community_review as review  # noqa: E402


class FakeClient:
    def profile(self, full_name: str):
        return {"health_percentage": 20 if full_name.endswith("risky-agent") else 90}

    def issues(self, full_name: str):
        if full_name.endswith("risky-agent"):
            return [
                {
                    "state": "open",
                    "comments": 0,
                    "title": "critical security bug",
                    "labels": [{"name": "bug"}],
                }
                for _ in range(10)
            ]
        return [
            {
                "state": "closed" if index < 8 else "open",
                "comments": 2 if index < 9 else 0,
                "title": "feature request",
                "labels": [],
            }
            for index in range(10)
        ]

    def contributors(self, full_name: str):
        if full_name.endswith("risky-agent"):
            return [{"login": "solo", "contributions": 100}]
        return [
            {"login": f"user-{index}", "contributions": max(50 - index, 1)}
            for index in range(20)
        ]


class CommunityReviewTests(unittest.TestCase):
    def make_rows(self):
        return [
            {
                "full_name": "example/good-agent",
                "url": "https://github.com/example/good-agent",
                "description": "An active coding agent for terminal workflows.",
                "stars": "50000",
                "forks": "5000",
                "language": "Python",
                "license": "MIT",
                "topics": "ai-agent;coding-agent;cli",
                "days_since_push": "0.5",
                "hot_score": "90",
                "growth_score": "95",
                "emerging_score": "80",
                "star_velocity_previous": "100",
                "star_delta_7d_equivalent": "500",
                "lifetime_star_velocity": "20",
                "age_days": "50",
            },
            {
                "full_name": "example/risky-agent",
                "url": "https://github.com/example/risky-agent",
                "description": "An experimental AI agent framework.",
                "stars": "500",
                "forks": "20",
                "language": "Python",
                "license": "",
                "topics": "ai-agent;agent-framework",
                "days_since_push": "220",
                "hot_score": "70",
                "growth_score": "60",
                "emerging_score": "70",
                "star_velocity_previous": "1",
                "star_delta_7d_equivalent": "2",
                "lifetime_star_velocity": "2",
                "age_days": "80",
            },
        ]

    def test_good_project_is_recommended(self):
        repo = self.make_rows()[0]
        result = review.score(repo, review.collect_signals(repo, FakeClient()))
        self.assertEqual(result["verdict"], "值得使用")
        self.assertGreaterEqual(result["community_score"], 82)
        self.assertEqual(result["confidence"], "中等")

    def test_risky_project_is_not_overrecommended(self):
        repo = self.make_rows()[1]
        result = review.score(repo, review.collect_signals(repo, FakeClient()))
        self.assertIn(
            result["verdict"],
            {"谨慎试用", "暂不建议直接用于关键生产"},
        )
        self.assertIn("未标注明确开源许可证", result["warnings"])
        self.assertIn("Bug/安全/回归类开放 Issue 信号较多", result["warnings"])
        self.assertLess(result["community_score"], 58)

    def test_section_contains_explicit_usage_judgment(self):
        rows = self.make_rows()
        results = {
            row["full_name"]: review.score(
                row,
                review.collect_signals(row, FakeClient()),
            )
            for row in rows
        }
        section = review.build_section(rows, results, 2)
        self.assertIn("## 社区评价与使用建议", section)
        self.assertIn("是否值得使用", section)
        self.assertIn("值得使用", section)
        self.assertIn("主要风险", section)
        self.assertIn("不是用户口碑调查", section)

    def test_injection_is_idempotent(self):
        base = "# AI Agent GitHub 雷达 — 2026-07-19\n\n## 口径与数据质量\n"
        section = review.build_section([], {}, 2)
        once = review.inject(base, section)
        twice = review.inject(once, section)
        self.assertEqual(once, twice)
        self.assertEqual(once.count(review.SECTION_START), 1)

    def test_enrich_writes_dated_report_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "latest.md"
            data = root / "latest.csv"
            output = root / "community" / "latest.json"
            report.write_text(
                "# AI Agent GitHub 雷达 — 2026-07-19\n\n"
                "## 今日概览\n\n"
                "## 口径与数据质量\n",
                encoding="utf-8",
            )
            rows = self.make_rows()
            with data.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

            written = review.enrich(report, data, output, FakeClient(), 2)
            self.assertIn(root / "2026-07-19.md", written)
            self.assertIn(root / "community" / "2026-07-19.json", written)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["projects"]), 2)
            self.assertIn(
                "社区评价与使用建议",
                report.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
