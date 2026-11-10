from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from dsa_coach_mcp.browser import dashboard_page, host_page, make_server
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
    assert set(result["structuredContent"]) == {
        "progress",
        "due",
        "patterns",
        "insights",
        "accounts",
        "next_steps",
    }
    assert "ui/notifications/tool-result" in page


@pytest.fixture
def port() -> Iterator[int]:
    with make_server("<p>dashboard</p>") as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield httpd.server_address[1]
        httpd.shutdown()


def get(port: int, host: str) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", "/", headers={"Host": host})
    status = connection.getresponse().status
    connection.close()
    return status


def test_server_answers_only_its_own_loopback_host(port: int) -> None:
    assert get(port, f"127.0.0.1:{port}") == 200
    assert get(port, f"localhost:{port}") == 200
    # A rebinding page sends its own host name.
    assert get(port, f"attacker.example:{port}") == 404


def test_a_busy_port_exits_with_a_message(port: int) -> None:
    with pytest.raises(SystemExit, match=f"port {port}"):
        make_server("", port)
