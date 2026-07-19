# Project introduction enrichment

`enrich_report.py` runs after the daily repository collection step and inserts a generated **重点项目内容介绍** section into both:

- `reports/latest.md`
- `reports/YYYY-MM-DD.md`

The section selects unique repositories across the hot, growth, and emerging rankings. Each entry includes:

- a Chinese project-direction classification;
- the repository author's GitHub description;
- Stars and Forks;
- language, license, and selected Topics;
- the ranking and activity signals that caused the project to be highlighted.

The section is wrapped in stable HTML comment markers, so repeated runs replace it rather than duplicate it.
