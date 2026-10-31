"""Export a report to PDF by printing the web viewer in headless Chrome.

The viewer's ``?export=1`` mode draws every page at full size, one per printed
sheet, so the PDF looks exactly like the report on screen. The browser signs
in with a short-lived token for the person exporting, so row-level security
applies to the PDF as it does on screen. The token is put in the page's
session storage, never in the URL.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from magbi.config import Settings

CHROME = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
STEP_TIMEOUT = 60.0
RENDER_TIMEOUT = 90.0


class ExportError(Exception):
    """The PDF couldn't be made; the message says why, for the person exporting."""


def find_chrome(settings: Settings) -> str | None:
    if settings.chrome_path:
        return settings.chrome_path if Path(settings.chrome_path).is_file() else None
    found = next((path for path in CHROME if Path(path).is_file()), None)
    return (
        found
        or shutil.which("chrome")
        or shutil.which("chromium")
        or shutil.which("google-chrome")
    )


class _Tab:
    def __init__(self, socket: Any) -> None:
        self.socket = socket
        self.next_id = 0

    async def send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.next_id += 1
        mine = self.next_id
        await self.socket.send(
            json.dumps({"id": mine, "method": method, "params": params or {}})
        )
        while True:
            try:
                raw = await asyncio.wait_for(self.socket.recv(), timeout=STEP_TIMEOUT)
            except TimeoutError:
                raise ExportError(
                    "the browser stopped answering while making the PDF"
                ) from None
            message = json.loads(raw)
            if message.get("id") == mine:
                if "error" in message:
                    raise ExportError(f"the browser refused {method}")
                return message.get("result", {})

    async def evaluate(self, expression: str) -> Any:
        result = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        return result.get("result", {}).get("value")


def _launch(exe: str) -> tuple[subprocess.Popen[bytes], int, str]:
    profile = tempfile.mkdtemp(prefix="magbi-export-")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    proc = subprocess.Popen(
        [
            exe,
            "--headless=new",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--hide-scrollbars",
            "--no-first-run",
            "--disable-extensions",
            "--window-size=1920,1080",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(75):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=1
            ):
                return proc, port, profile
        except OSError:
            time.sleep(0.2)
    proc.kill()
    shutil.rmtree(profile, ignore_errors=True)
    raise ExportError("the browser for PDF export did not start")


def _new_tab(port: int) -> str:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT"
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return str(json.loads(response.read())["webSocketDebuggerUrl"])


async def report_pdf(
    settings: Settings, token: str, workspace_id: str, report_id: str, pages: int
) -> bytes:
    """The report's pages as one PDF. ``pages`` is how many pages the report has."""
    import websockets

    exe = find_chrome(settings)
    if exe is None:
        raise ExportError(
            "PDF export needs Chrome or Edge on the server; set MAGBI_CHROME_PATH"
        )
    base = settings.web_base_url.rstrip("/")
    proc, port, profile = await asyncio.to_thread(_launch, exe)
    try:
        url = await asyncio.to_thread(_new_tab, port)
        async with websockets.connect(url, max_size=256 * 1024 * 1024) as connection:
            tab = _Tab(connection)
            await tab.send("Page.enable")
            await tab.send("Page.navigate", {"url": f"{base}/login"})
            await asyncio.sleep(1.0)
            await tab.evaluate(
                f"sessionStorage.setItem('magbi.token', {json.dumps(token)})"
            )
            await tab.send(
                "Page.navigate",
                {
                    "url": f"{base}/workspaces/{workspace_id}/reports/{report_id}/view?export=1"
                },
            )
            await _settle(tab, pages)
            printed = await tab.send(
                "Page.printToPDF",
                {
                    "printBackground": True,
                    "preferCSSPageSize": True,
                    # Only the report's pages: the app shell can leave a blank sheet after them.
                    "pageRanges": f"1-{max(pages, 1)}",
                    "marginTop": 0,
                    "marginBottom": 0,
                    "marginLeft": 0,
                    "marginRight": 0,
                },
            )
            return base64.b64decode(printed["data"])
    except OSError as exc:
        raise ExportError(
            f"couldn't reach the browser for PDF export ({type(exc).__name__})"
        ) from None
    finally:
        proc.terminate()
        try:
            await asyncio.to_thread(proc.wait, 10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


async def _settle(tab: _Tab, pages: int) -> None:
    """Wait until every page is drawn and no visual is still loading."""
    deadline = time.monotonic() + RENDER_TIMEOUT
    await asyncio.sleep(1.0)
    while time.monotonic() < deadline:
        state = await tab.evaluate(
            "(() => ({ pages: document.querySelectorAll('.export-page').length,"
            " busy: document.body.innerText.includes('Loading'),"
            " error: document.querySelector('.ws-error')?.textContent ?? '' }))()"
        )
        state = state or {}
        if state.get("error"):
            raise ExportError(f"the report didn't open for export: {state['error']}")
        if state.get("pages", 0) >= max(pages, 1) and not state.get("busy"):
            await asyncio.sleep(1.5)  # chart animations
            return
        await asyncio.sleep(0.4)
    raise ExportError("the report took too long to draw for export")
