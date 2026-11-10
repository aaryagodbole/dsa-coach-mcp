# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- A [live demo](https://aaryagodbole.github.io/dsa-coach-mcp/) of the dashboard with made-up sample data, published to GitHub
  Pages from `examples/dashboard_host.py --demo` on every change to main.
- **What you still know** on the dashboard: per topic, problems solved on your linked
  accounts, problems revised here, and how many of those you would get right today
  (the sum of their FSRS recall), plus the topics you solved most but never revised.
- **Before you submit** on the dashboard: a checklist per topic built from your own
  mistake journal, most frequent mistake first, each with the latest note you logged.
- The dashboard opens with **Do this next**: up to four steps picked by fixed rules from
  your own data (the revision most at risk, a mistake with no clean review since, a weak
  topic, and a problem rated easy then failed), and **Weekly report**, **Plan my session**
  and **Quiz me** buttons that send the request to your assistant in hosts that accept
  messages from the view, or show it to paste elsewhere.
- `weekly_report` prompt: what you did, what is slipping, recurring mistakes and three
  next steps, for the last 7 days or the number of days given.
- `link_account` saves your username on a platform (checking it exists) and
  `unlink_account` forgets it. `get_profile` and `review_evidence` default to the linked
  handle, and the dashboard's new **My platforms** panel shows each linked account live:
  solved per level or rating, strongest tags, tags tried and never solved, and tags barely
  practised. A platform that is down or slow shows as unavailable without holding up the
  rest.

### Changed

- The dashboard has a new look: a cream, brown and terracotta theme with bold borders and
  hard shadows, a header, and each panel titled with a short explanation underneath.

## [0.3.0] - 2026-11-10

### Added

- The dashboard shows a forgetting forecast per tag, mistake recovery, overconfident
  reviews (easy, then failed) and calibration of FSRS's predictions against your
  reviews. Cards now store their problem's tags; older cards take them from a recorded
  problem or the mistakes logged on them.
- `review_evidence` suggests a review rating from the user's submissions since the last
  review (again, hard or good), so ratings stop depending on self-assessment alone.
  Profiles say whether a platform lists rejected submissions.
- `dsa-coach-mcp dashboard` opens the dashboard in a browser, for MCP clients that
  cannot render MCP Apps.

### Changed

- The dashboard is a React + TypeScript app built with Vite, talking to the host
  through the official MCP Apps SDK instead of hand-written postMessage code.
- Read-only tools declare every behavior hint explicitly (`destructiveHint: false`,
  `idempotentHint: true`), since an unset `destructiveHint` defaults to true.
- Agent evals retry rate-limited and overloaded model APIs (429 and 5xx, honoring
  `Retry-After`) instead of ending the run on the first busy response.
- The PyPI page describes the server as working on any judge, and its images and links
  resolve there (the README now uses absolute links).

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

[Unreleased]: https://github.com/aaryagodbole/dsa-coach-mcp/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/aaryagodbole/dsa-coach-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/aaryagodbole/dsa-coach-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aaryagodbole/dsa-coach-mcp/releases/tag/v0.1.0
