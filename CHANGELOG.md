# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-11-03

### Added

- Listed in the official MCP Registry as `io.github.aaryagodbole/dsa-coach-mcp`: the
  release workflow publishes `server.json` after PyPI, authenticated with GitHub OIDC.
- An agent skill (`skills/dsa-coach/SKILL.md`) that tells the agent when and how to use
  the tools; a test keeps it naming only tools, arguments and prompts that exist.

- Agent evals (`evals/`): a model drives the server over MCP against a deterministic
  fixture world, graded without an LLM judge on tool selection, arguments, forbidden
  tools, errors and call budget. The model is configuration: any chat completions API,
  hosted or local, through a pluggable `AgentBackend` interface.

- `show_dashboard`, an MCP App (`ui://dsa-coach/dashboard`, `text/html;profile=mcp-app`):
  progress per platform, revisions due ordered by FSRS's recall estimate, and a heatmap
  of mistakes by label and tag, rendered in the conversation by hosts that support MCP
  Apps. `examples/dashboard_host.py` previews it without a host.

- Any platform: `record_problem` records a problem from a platform with no adapter, as
  read from its page (for example through Playwright MCP's browser extension). The
  platform is the URL's host; such problems are marked `reported`, and `list_platforms`
  lists them. `progress` reports reviewed problems, reviews logged and problems due
  now, per platform.
- `schedule_info` and `personalize_schedule`: inspect the FSRS parameters, and fit them
  to the user's own review history with the `optimizer` extra. A fit that leaves FSRS's
  defaults unchanged (too little history) is reported and not saved.

### Changed

- Revision scheduling moved from SM-2 to FSRS (py-fsrs). `log_review` takes a rating of
  `again`, `hard`, `good` or `easy`; every review is logged; `revisions_due` lists the
  problem the user is least likely to recall first, with FSRS's recall estimate.
  Existing databases upgrade in place: cards keep their due dates and start FSRS at
  their next review.

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

[Unreleased]: https://github.com/aaryagodbole/dsa-coach-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/aaryagodbole/dsa-coach-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aaryagodbole/dsa-coach-mcp/releases/tag/v0.1.0
