from __future__ import annotations

import json
import re
from pathlib import Path

from dsa_coach_mcp.browser import dashboard_page, host_page
from dsa_coach_mcp.server import create_server
from dsa_coach_mcp.store import ReviewStore


def script_json(page: str, name: str) -> object:
    match = re.search(rf"^const {name} = (.*);$", page, re.M)
    assert match, name
    return json.loads(match.group(1))


def test_host_page_keeps_a_closing_script_tag_inside_the_view() -> None:
    page = host_page({"due": []}, "<script>x()</script>", "dark")

    # Only the host page's own script may close a script element.
    assert page.count("</script>") == 1
    assert '"<script>x()<\\/script>"' in page
    assert script_json(page, "result") == {"structuredContent": {"due": []}}
    assert 'const theme = "dark" ??' in page


def test_with_no_theme_the_page_follows_the_browser() -> None:
    assert "const theme = null ??" in host_page({}, "", None)


async def test_dashboard_page_wraps_the_live_show_dashboard_result(tmp_path: Path) -> None:
    server = create_server({}, ReviewStore(tmp_path / "coach.db"))

    page = await dashboard_page(server)

    result = script_json(page, "result")
    assert isinstance(result, dict)
    assert set(result["structuredContent"]) == {"progress", "due", "patterns", "insights"}
    assert "ui/notifications/tool-result" in page
