# Contributing

Thanks for helping out. Bug reports, platform adapters and fixes are all welcome.

## Setup

```bash
git clone https://github.com/aaryagodbole/dsa-coach-mcp
cd dsa-coach-mcp
uv sync
uv run pre-commit install
```

## Workflow

1. Open an issue first for anything larger than a small fix.
2. Branch from `main` (`feat/...`, `fix/...`, `docs/...`).
3. Keep the checks green: `uv run pytest`, `uv run ruff check .`,
   `uv run ruff format --check .` and `uv run mypy`.
4. Write commits in [Conventional Commits](https://www.conventionalcommits.org/) form,
   e.g. `feat(codeforces): add contest history`.
5. Open a pull request to `main` and fill in the template.

## Principles

- **Data, not decisions.** Tools return what the platforms say. Don't hardcode what
  counts as weak, hard or next; leave that to the model calling the tools.
- **No hardcoded vocabularies.** Tags, levels and other filter values come from the
  platform's API, never from lists in the code.
- **Platform code stays in its adapter.** Nothing outside `platforms/<name>.py` should
  name a platform.
- **Tests don't touch the network.** Mock the API with `httpx.MockTransport`.

## Releasing

Releases publish to PyPI through [trusted publishing](https://docs.pypi.org/trusted-publishers/),
so no API token is stored anywhere.

1. Once per project, before the first release: the PyPI owner adds a trusted publisher
   for `dsa-coach-mcp` (repository `aaryagodbole/dsa-coach-mcp`, workflow `release.yml`,
   environment `pypi`) at pypi.org → Publishing. The `pypi` GitHub environment only
   accepts `v*` tags.
2. Bump `version` in `pyproject.toml` and `server.json`, and move the `Unreleased` changelog entries under a
   new `## [x.y.z] - YYYY-MM-DD` heading, in a pull request.
3. After it merges, tag `main` and push the tag:
   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
4. The release workflow checks the tag matches the package version, runs the tests,
   builds, publishes to PyPI, creates the GitHub release from the changelog entry, and
   publishes `server.json` to the MCP Registry. Keep `server.json`'s versions equal to
   `pyproject.toml`'s; a test checks it.
