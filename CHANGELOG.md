# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- MCP server with `list_platforms`, `get_profile`, `search_problems`, `log_review`
  and `revisions_due` tools.
- LeetCode adapter over its public GraphQL API.
- Codeforces adapter over its official REST API.
- SM-2 spaced-repetition scheduling, stored in local SQLite.
- Mistake journal: `log_review` records the mistakes behind each review, labelled by the
  model in its own words; `mistake_kinds`, `list_mistakes` and `mistake_patterns` read
  them back.
- `practice_plan` and `revision_quiz` prompts built on the journal.
- Versioned SQLite schema, so existing databases upgrade in place.
