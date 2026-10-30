"""MagBI QA gate: the same standard the live Power BI dashboards pass, run on MagBI reports.

    python -m scripts.qa_gate --workspace <id> --report <id> [--report <id> ...] --out <folder>

Three layers, each finding a class of defect that reached a live dashboard before:

1. Static: canvas bounds, overlap, KPI card height, theme colours only, a tone rule
   on every status visual.
2. Live (API): every visual's query with no filter and with every value of every
   report filter: no error, under 2 s; headline figures equal to MSD_ERP.
3. Render (headless Chrome at 1920 x 1080): no page scroll, no clipped text, no
   "(Blank)" or NaN, no empty white panel, donut centre on the ring and equal to
   its slices, tables at least 90% of their panel, status as glyph + word.
   The render checks run again for every value of every dropdown.

Exit code 0 only when every report passes. A JSON report and screenshots are
written to --out.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets

PAGE_W, PAGE_H = 1760, 990
VIEW_W, VIEW_H = 1920, 1080
MAX_SECONDS = 2.0
KPI_MIN_H = 122
THEME = {
    "#EEF2F7", "#F8FAFC", "#FFFFFF", "#E9EEF5", "#D3DCE6", "#E2E8EF", "#22324A", "#66758A", "#5A6A80",
    "#2C4F80", "#F3F6FA", "#BCC8D6", "#3F6FB0", "#5F8BC9", "#82A6D6", "#B3C3D8", "#4E9E77", "#D49A55",
    "#C76E6C", "#9EABBC",
}
TONES = {"good", "watch", "action", "none", "info"}
STATUS_TYPES = {"kpi", "meter"}
CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


@dataclass
class Result:
    report: str
    name: str
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.failures


# ---------------------------------------------------------------- API


def _call(method: str, url: str, body: Any = None) -> tuple[int, Any, float]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read() or b"null")
            return response.status, payload, time.perf_counter() - started
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), time.perf_counter() - started


# ---------------------------------------------------------------- 1. static


def _hexes(value: Any) -> list[str]:
    text = json.dumps(value)
    return [item.upper() for item in re.findall(r"#[0-9A-Fa-f]{6}\b", text)]


def static_checks(definition: dict[str, Any], result: Result) -> None:
    visuals = definition["pages"][0]["visuals"]
    solid = [v for v in visuals if v["type"] not in {"frame", "label"}]
    for v in visuals:
        x, y, w, h = v["x"], v["y"], v["width"], v["height"]
        if x < 0 or y < 0 or x + w > PAGE_W or y + h > PAGE_H:
            result.failures.append(f"static: {v['id']} sits outside the {PAGE_W}x{PAGE_H} canvas")
        if v["type"] == "kpi" and h < KPI_MIN_H:
            result.failures.append(f"static: KPI card {v['id']} is {h} px tall; the minimum is {KPI_MIN_H}")
        for colour in _hexes(v.get("properties", {})):
            if colour not in THEME:
                result.failures.append(f"static: {v['id']} uses {colour}, which is not an ERP Native token")
        if v["type"] in STATUS_TYPES and not isinstance(v.get("properties", {}).get("rule"), dict):
            result.failures.append(f"static: {v['id']} shows status without a tone rule")
        colours = v.get("properties", {}).get("colours", {})
        for name, tone in colours.items():
            if not str(tone).startswith("#") and tone not in TONES:
                result.failures.append(f"static: {v['id']} colours {name!r} with unknown tone {tone!r}")
    for index, a in enumerate(solid):
        for b in solid[index + 1:]:
            if a["x"] < b["x"] + b["width"] and a["x"] + a["width"] > b["x"] and a["y"] < b["y"] + b["height"] and a["y"] + a["height"] > b["y"]:
                result.failures.append(f"static: {a['id']} overlaps {b['id']}")


# ---------------------------------------------------------------- 2. live

ROLES = {
    "kpi": ["y-axis", "extra"], "chain": ["x-axis", "columns", "y-axis"], "calendar": ["x-axis", "columns", "y-axis"],
    "donut": ["x-axis", "y-axis"], "pareto": ["x-axis", "y-axis"], "heatmap": ["x-axis", "legend", "y-axis"],
    "grid": ["columns"], "meter": ["y-axis"], "bars": ["x-axis", "y-axis"], "stack100": ["x-axis", "legend", "y-axis"],
    "flow": ["y-axis"],
}


def _select(binding: dict[str, Any]) -> dict[str, Any]:
    if binding.get("measure"):
        return {"measure": {"table": binding["table"], "measure": binding["measure"]}}
    entry: dict[str, Any] = {"column": {"table": binding["table"], "column": binding["column"]}}
    if binding.get("aggregation"):
        entry["aggregation"] = binding["aggregation"]
    return entry


def _where(filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in filters:
        config = item.get("config") or {}
        if config.get("values"):
            out.append({"column": {"table": item["table"], "column": item["column"]}, "operator": config.get("operator", "eq"), "values": config["values"]})
    return out


def visual_query(visual: dict[str, Any], extra: list[dict[str, Any]]) -> dict[str, Any] | None:
    bindings = [b for well in ROLES.get(visual["type"], []) for b in visual["wells"].get(well, [])]
    if not bindings:
        return None
    query: dict[str, Any] = {"from": [], "select": [_select(b) for b in bindings]}
    where = _where(visual.get("filters", []) + extra)
    if where:
        query["where"] = where
    props = visual.get("properties", {})
    if props.get("orderBy"):
        query["orderBy"] = props["orderBy"]
    if isinstance(props.get("limit"), int):
        query["limit"] = props["limit"]
    return query


def filter_values(api: str, wid: str, did: str, slicer: dict[str, Any]) -> list[str]:
    binding = slicer["wells"]["field"][0]
    _status, body, _secs = _call("POST", f"{api}/workspaces/{wid}/datasets/{did}/query",
                                 {"query": {"from": [], "select": [{"column": {"table": binding["table"], "column": binding["column"]}}]}})
    hidden = set(slicer.get("properties", {}).get("hide", []))
    values = sorted({str(row[0]) for row in body["rows"] if row[0] not in (None, "")} - hidden)
    return values


def live_checks(api: str, wid: str, did: str, definition: dict[str, Any], result: Result) -> list[tuple[str, list[str]]]:
    visuals = definition["pages"][0]["visuals"]
    slicers = [v for v in visuals if v["type"] == "slicer"]
    contexts: list[tuple[str, list[dict[str, Any]]]] = [("no filter", [])]
    choices: list[tuple[str, list[str]]] = []
    for slicer in slicers:
        binding = slicer["wells"]["field"][0]
        values = filter_values(api, wid, did, slicer)
        choices.append((slicer["properties"].get("caption", binding["column"]), values))
        for value in values:
            contexts.append((f"{binding['column']} = {value}", [{"table": binding["table"], "column": binding["column"], "type": "basic", "config": {"operator": "in", "values": [value]}}]))
    slowest = 0.0
    runs = 0
    for label, extra in contexts:
        for visual in visuals:
            query = visual_query(visual, extra)
            if query is None:
                continue
            status, body, seconds = _call("POST", f"{api}/workspaces/{wid}/datasets/{did}/query", {"query": query})
            runs += 1
            slowest = max(slowest, seconds)
            if status != 200:
                result.failures.append(f"live: {visual['id']} with {label} failed: {str(body)[:160]}")
                continue
            if seconds > MAX_SECONDS:
                result.failures.append(f"live: {visual['id']} with {label} took {seconds:.2f} s (limit {MAX_SECONDS} s)")
            text = json.dumps(body["rows"])
            if "NaN" in text or "Infinity" in text:
                result.failures.append(f"live: {visual['id']} with {label} returned NaN or Infinity")
    result.stats["queries"] = runs
    result.stats["slowest_query_s"] = round(slowest, 3)
    result.stats["filter_contexts"] = len(contexts)
    return choices


def expected_checks(api: str, wid: str, did: str, expected: dict[str, float], result: Result) -> None:
    """Headline figures in MagBI against the same figures read from MSD_ERP."""
    for key, want in expected.items():
        table, measure = key.split("|", 1)
        status, body, _secs = _call("POST", f"{api}/workspaces/{wid}/datasets/{did}/query",
                                    {"query": {"from": [], "select": [{"measure": {"table": table, "measure": measure}}]}})
        got = body["rows"][0][0] if status == 200 and body["rows"] else None
        if got is None and want is None:
            continue
        if got is None or want is None or abs(float(got) - float(want)) > 1e-9:
            result.failures.append(f"figures: {table}[{measure}] is {got} in MagBI but {want} in MSD_ERP")
    result.stats["figures_checked"] = len(expected)


# ---------------------------------------------------------------- 3. render

DOM_CHECKS = r"""
(() => {
  const out = { failures: [], warnings: [], loading: 0 };
  const bad = /\(Blank\)|\bNaN\b|\bundefined\b|\bnull\b|Infinity/;
  const doc = document.documentElement;
  if (doc.scrollWidth > innerWidth + 1 || doc.scrollHeight > innerHeight + 1) out.failures.push(`page scrolls: ${doc.scrollWidth}x${doc.scrollHeight} in ${innerWidth}x${innerHeight}`);
  const visuals = [...document.querySelectorAll('.visual')];
  for (const v of visuals) {
    const id = v.querySelector('[data-visual-id]')?.dataset.visualId || v.id || '';
    const text = v.innerText || '';
    if (/Loading…/.test(text)) out.loading += 1;
    if (bad.test(text)) out.failures.push(`text "${text.match(bad)[0]}" shown in ${id || text.slice(0, 40)}`);
    if (/Couldn't load/.test(text)) out.failures.push(`error shown: ${text.slice(0, 120)}`);
  }
  // Clipped text: anything cut by its own box. Panel subtitles may truncate by design.
  const clipped = (el) => el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 2;
  for (const el of document.querySelectorAll('.kit-kpi > div, .kit-step b, .kit-step i, .kit-panel-hd h3, .kit-title, .kit-crumb, .kit-question, .kit-asat, .kit-units, .kit-meter-line, .slicer-cap, .kit-legend td, .kit-flow-name, .kit-flow-val')) {
    if (clipped(el)) out.failures.push(`clipped: "${el.innerText.trim().slice(0, 60)}" (${el.className || el.tagName})`);
  }
  for (const el of document.querySelectorAll('.kit-panel-sub')) if (clipped(el)) out.warnings.push(`subtitle truncated: "${el.innerText.trim()}"`);
  for (const card of document.querySelectorAll('.kit-kpi')) if (card.scrollHeight > card.clientHeight + 1) out.failures.push(`KPI card content taller than the card: "${card.querySelector('.kit-kpi-cap')?.innerText ?? ''}"`);
  for (const card of document.querySelectorAll('.kit-kpi > div')) { const box = card.getBoundingClientRect(); const host = card.parentElement.getBoundingClientRect(); if (box.bottom > host.bottom - 1) out.failures.push(`KPI line cut by the card edge: "${card.innerText.trim()}"`); }
  for (const th of document.querySelectorAll('.kit-grid th, .kit-heat th')) {
    for (const word of th.innerText.split(/\s+/)) {
      const probe = document.createElement('span'); probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;font:inherit;letter-spacing:inherit;text-transform:inherit'; probe.textContent = word; th.appendChild(probe);
      if (probe.offsetWidth > th.clientWidth) out.failures.push(`header word "${word}" is wider than its column`); probe.remove();
    }
  }
  // KPI cards: status is glyph + word.
  for (const st of document.querySelectorAll('.kit-kpi-st')) if (!/^[▲◆▼–●]\s+\S/.test(st.innerText.trim())) out.failures.push(`status without glyph and word: "${st.innerText}"`);
  // Panels: never an empty white body.
  for (const body of document.querySelectorAll('.kit-panel-bd')) {
    const filled = body.querySelector('canvas, svg, table, .kit-state, .kit-flow, .kit-meter');
    if (!filled || body.innerText.trim() === '' && !body.querySelector('canvas, svg')) out.failures.push(`empty panel: ${body.parentElement?.querySelector('h3')?.innerText}`);
  }
  // Tables fill at least 90% of their panel.
  for (const table of document.querySelectorAll('.kit-grid, .kit-heat')) {
    const host = table.closest('.kit-panel-bd'); if (!host) continue;
    const width = host.clientWidth - 24;
    if (table.offsetWidth < 0.9 * width) out.failures.push(`table fills ${Math.round(100 * table.offsetWidth / width)}% of "${host.parentElement.querySelector('h3')?.innerText}"`);
  }
  for (const wrap of document.querySelectorAll('.kit-heat-wrap')) if (wrap.scrollHeight > wrap.clientHeight + 1) out.failures.push(`heat matrix scrolls inside its panel`);
  for (const wrap of document.querySelectorAll('.kit-grid-wrap')) if (wrap.scrollHeight > wrap.clientHeight + 1) out.warnings.push(`table scrolls: ${wrap.closest('.kit-panel')?.querySelector('h3')?.innerText}`);
  // Donuts: the centre sits on the ring and, without a centre measure, equals the slices.
  for (const ring of document.querySelectorAll('.kit-donut-ring')) {
    // The centre is the figure and its unit word together; that block sits in the hole.
    const centre = ring.querySelector('.kit-donut-centre b'); const word = ring.querySelector('.kit-donut-centre span'); const box = ring.getBoundingClientRect();
    const parts = [centre, word].filter(Boolean).map((el) => el.getBoundingClientRect());
    const c = parts.length ? { left: Math.min(...parts.map((r) => r.left)), top: Math.min(...parts.map((r) => r.top)), width: Math.max(...parts.map((r) => r.right)) - Math.min(...parts.map((r) => r.left)), height: Math.max(...parts.map((r) => r.bottom)) - Math.min(...parts.map((r) => r.top)) } : null;
    if (!centre) { out.failures.push('donut without a centre'); continue; }
    const dx = Math.abs((c.left + c.width / 2) - (box.left + box.width / 2)); const dy = Math.abs((c.top + c.height / 2) - (box.top + box.height / 2)) ;
    if (dx > 2 || dy > 2) out.failures.push(`donut centre off by ${dx.toFixed(1)}, ${dy.toFixed(1)} px`);
    const legend = ring.parentElement.querySelector('.kit-legend');
    const counts = [...legend.querySelectorAll('tbody tr td:nth-child(2)')].map((td) => Number(td.innerText.replace(/,/g, '')));
    const sum = counts.reduce((a, b) => a + b, 0);
    if (!/%/.test(centre.innerText) && Number(centre.innerText.replace(/,/g, '')) !== sum) out.failures.push(`donut centre ${centre.innerText} differs from its slices (${sum})`);
  }
  return out;
})()
"""

SELECT_FILTER = r"""
(([index, value]) => {
  const select = document.querySelectorAll('.kit-slicer select')[index];
  if (!select) return false;
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
  setter.call(select, value);
  select.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
})
"""


class Chrome:
    """A headless Chrome driven over the DevTools protocol."""

    def __init__(self) -> None:
        exe = next((path for path in CHROME if Path(path).is_file()), None)
        if exe is None:
            raise SystemExit("Chrome or Edge is required for the render checks")
        self.profile = tempfile.mkdtemp(prefix="magbi-qa-")
        self.port = 9333
        self.proc = subprocess.Popen(
            [exe, "--headless=new", f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
             f"--window-size={VIEW_W},{VIEW_H}", "--hide-scrollbars", "--force-device-scale-factor=1", "--no-first-run", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1):
                    return
            except OSError:
                time.sleep(0.2)
        raise SystemExit("Chrome did not start")

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    def new_tab(self) -> str:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/json/new?about:blank", method="PUT")
        with urllib.request.urlopen(request, timeout=5) as response:
            return str(json.loads(response.read())["webSocketDebuggerUrl"])


class Tab:
    def __init__(self, socket: Any) -> None:
        self.socket = socket
        self.next_id = 0

    async def send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.next_id += 1
        mine = self.next_id
        await self.socket.send(json.dumps({"id": mine, "method": method, "params": params or {}}))
        while True:
            message = json.loads(await self.socket.recv())
            if message.get("id") == mine:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    async def evaluate(self, expression: str) -> Any:
        result = await self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            raise RuntimeError(f"page script failed: {details.get('exception', {}).get('description') or details.get('text')}")
        return result.get("result", {}).get("value")

    async def settle(self, timeout: float = 20.0) -> None:
        """Wait until no visual says Loading and charts have drawn."""
        deadline = time.monotonic() + timeout
        await asyncio.sleep(1.0)
        while time.monotonic() < deadline:
            busy = await self.evaluate("document.body.innerText.includes('Loading') || !document.querySelector('.page')")
            if not busy:
                await asyncio.sleep(1.2)  # chart animation
                return
            await asyncio.sleep(0.4)

    async def screenshot(self, path: Path) -> None:
        shot = await self.send("Page.captureScreenshot", {"format": "png"})
        path.write_bytes(base64.b64decode(shot["data"]))


async def render_checks(web: str, wid: str, report_id: str, choices: list[tuple[str, list[str]]], out: Path, result: Result) -> None:
    chrome = Chrome()
    try:
        async with websockets.connect(chrome.new_tab(), max_size=64 * 1024 * 1024) as socket:
            tab = Tab(socket)
            await tab.send("Page.enable")
            await tab.send("Emulation.setDeviceMetricsOverride", {"width": VIEW_W, "height": VIEW_H, "deviceScaleFactor": 1, "mobile": False})
            await tab.send("Page.navigate", {"url": f"{web}/workspaces/{wid}/reports/{report_id}/view"})
            await tab.settle()
            shot = out / f"{result.name}.png"
            await tab.screenshot(shot)
            result.stats["screenshot"] = str(shot)
            found = await tab.evaluate(DOM_CHECKS)
            result.failures += [f"render: {item}" for item in found["failures"]]
            result.warnings += [f"render: {item}" for item in found["warnings"]]
            renders = 1
            for index, (caption, values) in enumerate(choices):
                for value in values:
                    await tab.evaluate(f"({SELECT_FILTER})({json.dumps([index, value])})")
                    await tab.settle()
                    found = await tab.evaluate(DOM_CHECKS)
                    renders += 1
                    result.failures += [f"render ({caption} = {value}): {item}" for item in found["failures"]]
                    slug = re.sub(r"[^A-Za-z0-9]+", "-", f"{caption}-{value}").strip("-")
                    await tab.screenshot(out / f"{result.name}--{slug}.png")
                await tab.evaluate(f"({SELECT_FILTER})({json.dumps([index, ''])})")
                await tab.settle()
            result.stats["renders"] = renders
    finally:
        chrome.close()


# ---------------------------------------------------------------- run


def run(api: str, web: str, wid: str, report_ids: list[str], out: Path, expected: dict[str, dict[str, float]]) -> list[Result]:
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for report_id in report_ids:
        _status, report, _secs = _call("GET", f"{api}/workspaces/{wid}/reports/{report_id}")
        definition = report["definition"]
        did = report["dataset_id"]
        result = Result(report_id, re.sub(r"[^A-Za-z0-9]+", "-", report["name"]).strip("-"))
        static_checks(definition, result)
        choices = live_checks(api, wid, did, definition, result)
        expected_checks(api, wid, did, expected.get(report["name"], {}), result)
        asyncio.run(render_checks(web, wid, report_id, choices, out, result))
        results.append(result)
    (out / "qa-report.json").write_text(json.dumps([r.__dict__ | {"passed": r.passed} for r in results], indent=1), encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--report", action="append", required=True)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--web", default="http://localhost:3000")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected", type=Path, help="JSON: {report name: {'Table|Measure': value}}")
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text(encoding="utf-8")) if args.expected else {}
    results = run(args.api, args.web, args.workspace, args.report, args.out, expected)
    for result in results:
        print(f"{'PASS' if result.passed else 'FAIL'}  {result.name}  {json.dumps(result.stats)}")
        for item in result.failures:
            print(f"   x {item}")
        for item in result.warnings:
            print(f"   ! {item}")
    raise SystemExit(0 if all(result.passed for result in results) else 1)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
