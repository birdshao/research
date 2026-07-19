from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import enrich_report as intro  # noqa: E402


class EnrichReportTests(unittest.TestCase):
    def make_rows(self) -> list[dict[str, str]]:
        return [
            {
                "full_name": "example/code-agent",
                "url": "https://github.com/example/code-agent",
                "description": "An autonomous coding agent for terminal workflows.",
                "stars": "1000",
                "forks": "100",
                "language": "Python",
                "license": "MIT",
                "topics": "ai-agent;coding-agent;cli",
                "days_since_push": "0.5",
                "hot_score": "80",
                "growth_score": "90",
                "emerging_score": "70",
                "star_velocity_previous": "100",
                "star_delta_7d_equivalent": "500",
                "lifetime_star_velocity": "20",
                "age_days": "50",
            },
            {
                "full_name": "example/browser-agent",
                "url": "https://github.com/example/browser-agent",
                "description": "A browser automation agent for repeatable web tasks.",
                "stars": "500",
                "forks": "50",
                "language": "TypeScript",
                "license": "Apache-2.0",
                "topics": "browser;ai-agent",
                "days_since_push": "2",
                "hot_score": "70",
                "growth_score": "60",
                "emerging_score": "80",
                "star_velocity_previous": "20",
                "star_delta_7d_equivalent": "100",
                "lifetime_star_velocity": "30",
                "age_days": "20",
            },
        ]

    def test_project_category_is_readable(self) -> None:
        rows = self.make_rows()
        self.assertEqual(
            intro.project_category(rows[0]),
            "编程、代码审查与开发者 Agent",
        )
        self.assertEqual(
            intro.project_category(rows[1]),
            "浏览器、搜索与 Web 自动化",
        )

    def test_generated_section_contains_description_and_reason(self) -> None:
        section = intro.build_intro_section(self.make_rows(), top_n=2)
        self.assertIn("## 重点项目内容介绍", section)
        self.assertIn("An autonomous coding agent", section)
        self.assertIn("热度榜第 1 名", section)
        self.assertIn("技术信息", section)

    def test_injection_is_idempotent(self) -> None:
        base = (
            "# AI Agent GitHub 雷达 — 2026-07-19\n\n"
            "## 今日概览\n\n"
            "## 口径与数据质量\n"
        )
        section = intro.build_intro_section(self.make_rows(), top_n=2)
        once = intro.inject_section(base, section)
        twice = intro.inject_section(once, section)
        self.assertEqual(once, twice)
        self.assertEqual(once.count(intro.SECTION_START), 1)
        self.assertLess(once.index("## 重点项目内容介绍"), once.index("## 口径与数据质量"))

    def test_enrich_report_syncs_dated_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "latest.md"
            data = root / "latest.csv"
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

            written = intro.enrich_report(report, data, top_n=2)
            dated = root / "2026-07-19.md"
            self.assertEqual(written, [report, dated])
            self.assertTrue(dated.exists())
            self.assertEqual(report.read_text(encoding="utf-8"), dated.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
