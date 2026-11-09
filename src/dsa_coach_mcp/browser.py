"""Open the dashboard in a web browser, for MCP clients that cannot render MCP Apps.

A small page plays the host's side of the MCP Apps protocol: it loads the dashboard
view into a sandboxed iframe, answers ui/initialize and sends the show_dashboard
result as ui/notifications/tool-result. It is served on localhost only."""

from __future__ import annotations

import json
import webbrowser
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal

from mcp import Client
from mcp.server.mcpserver import MCPServer

from .server import DASHBOARD_URI

Theme = Literal["light", "dark"]

_HOST_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>DSA coach dashboard</title>
<style>body{margin:0} iframe{border:0;width:100%;height:100vh}</style>
</head><body><iframe id="view" sandbox="allow-scripts"></iframe>
<script>
const view = document.getElementById("view");
const result = __RESULT__;
const theme = __THEME__ ??
  (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
document.body.style.background = theme === "dark" ? "#0d1117" : "#ffffff";
window.addEventListener("message", (e) => {
  if (e.source !== view.contentWindow) return;
  const m = e.data;
  if (!m || m.jsonrpc !== "2.0") return;
  const reply = (body) => view.contentWindow.postMessage({jsonrpc: "2.0", ...body}, "*");
  if (m.method === "ui/initialize") {
    reply({id: m.id, result: {
      protocolVersion: "2026-01-26", hostInfo: {name: "dsa-coach-mcp", version: "1"},
      hostCapabilities: {openLinks: {}}, hostContext: {theme}}});
  } else if (m.method === "ui/open-link") {
    const ok = /^https?:\\/\\//.test(m.params?.url ?? "");
    if (ok) window.open(m.params.url, "_blank", "noopener");
    reply({id: m.id, result: ok ? {} : {isError: true}});
  } else if (m.method === "ui/notifications/initialized") {
    reply({method: "ui/notifications/tool-result", params: result});
  }
});
view.srcdoc = __VIEW__;
</script></body></html>
"""


def _script_json(value: object) -> str:
    """JSON that is safe inside a <script> element: a literal "</script>" in the
    dashboard's HTML would otherwise end the host page's script early."""

    return json.dumps(value).replace("</", "<\\/")


def host_page(structured_content: dict[str, Any], view: str, theme: Theme | None = None) -> str:
    """The host page for one dashboard result; with no theme it follows the browser's."""

    return (
        _HOST_PAGE.replace("__RESULT__", _script_json({"structuredContent": structured_content}))
        .replace("__THEME__", _script_json(theme))
        .replace("__VIEW__", _script_json(view))
    )


async def dashboard_page(server: MCPServer, theme: Theme | None = None) -> str:
    """Call show_dashboard on the server in memory and wrap its result in a host page."""

    async with Client(server) as client:
        result = await client.call_tool("show_dashboard", {})
        resource = (await client.read_resource(DASHBOARD_URI)).contents[0]
    if result.structured_content is None or not hasattr(resource, "text"):
        raise RuntimeError("show_dashboard returned no dashboard")
    return host_page(result.structured_content, resource.text, theme)


def make_server(page: str, port: int = 0) -> ThreadingHTTPServer:
    """Bind a localhost server for the page; port 0 picks a free one."""

    body = page.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            bound = self.connection.getsockname()[1]
            # A DNS-rebinding page reaches this port under its own host name.
            allowed = {f"127.0.0.1:{bound}", f"localhost:{bound}"}
            if self.path != "/" or self.headers.get("Host") not in allowed:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    try:
        return ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as error:
        raise SystemExit(f"Cannot serve the dashboard on port {port}: {error.strerror}") from error


def serve(page: str, port: int = 0, open_browser: bool = True) -> None:
    """Serve the page on localhost until interrupted, opening it in the browser."""

    with make_server(page, port) as httpd:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        print(f"Dashboard at {url} (Ctrl+C to stop)")
        if open_browser:
            webbrowser.open(url)
        with suppress(KeyboardInterrupt):
            httpd.serve_forever()
