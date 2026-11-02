# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-02

First release.

### Added

- MCP server with `list_platforms`, `get_profile`, `search_problems`, `log_review`,
  `revisions_due`, `mistake_kinds`, `list_mistakes` and `mistake_patterns` tools, and
  `practice_plan` and `revision_quiz` prompts.
- LeetCode adapter over its public GraphQL API, and Codeforces adapter over its official
  REST API. A review reads the problem's title, link and tags from the platform.
- SM-2 spaced-repetition scheduling, stored in local SQLite with a versioned schema.
- Mistake journal: each review records the mistakes behind it, labelled by the model in
  its own words, and the journal is read back as entries and patterns.

[Unreleased]: https://github.com/aaryagodbole/dsa-coach-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aaryagodbole/dsa-coach-mcp/releases/tag/v0.1.0
