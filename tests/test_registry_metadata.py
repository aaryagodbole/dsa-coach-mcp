"""The MCP Registry checks the PyPI description (this README) for the server's name."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_server_json_matches_the_package_and_readme() -> None:
    server = json.loads((ROOT / "server.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    (package,) = server["packages"]

    assert package["registryType"] == "pypi"
    assert package["identifier"] == project["name"]
    assert server["version"] == package["version"] == project["version"]
    assert f"<!-- mcp-name: {server['name']} -->" in (ROOT / "README.md").read_text()
    # The registry schema caps a server description at 100 characters.
    assert len(server["description"]) <= 100
