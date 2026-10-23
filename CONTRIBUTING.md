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
