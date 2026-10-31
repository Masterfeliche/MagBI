"""MagBI end to end, the way a Power BI author and reader would use it.

Runs against a running dev server (``python dev_server.py``) and web app
(``npm run dev``), in its own "E2E check" workspace, signed in as a dedicated
editor and a viewer it creates on first run (their logins are kept in the
gitignored data folder). Every step records its Power BI equivalent, what was
checked, and the result; ``results.json`` and screenshots go to ``--out``.

The data refresh is checked against a small OData service this script starts
on 127.0.0.1, so no database or network is needed. ``--warehouse WID:DID``
also refreshes that dataset from its real source (for example MSD_ERP).

Exits 1 when any step fails, so CI can gate on it::

    python scripts/e2e.py --out e2e-results
"""

import argparse
import asyncio
import csv
import json
import secrets
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from scripts.qa_gate import Chrome, Tab

# Set from the command line in main().
HERE = SERVER / "e2e-results"
SHOTS = HERE / "shots"
DATA = SERVER / "data"
API = "http://127.0.0.1:8000/api/v1"
WEB = "http://localhost:3000"
WAREHOUSE: tuple[str, str] | None = None
RESULTS: list[dict] = []


# ---------------------------------------------------------------- helpers

def call(method, path, body=None, token=None, raw=None, content_type=None):
    url = API + path
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", content_type or "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            text = response.read()
            return response.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as exc:
        text = exc.read()
        try:
            return exc.code, json.loads(text)
        except ValueError:
            return exc.code, text.decode("utf-8", "replace")


def record(area, step, power_bi, ok, detail="", severity=None):
    RESULTS.append({"area": area, "step": step, "powerBi": power_bi, "ok": bool(ok), "detail": detail,
                    "severity": severity or ("" if ok else "fail")})
    print(("PASS " if ok else "FAIL ") + f"[{area}] {step}: {detail}".encode("ascii", "replace").decode())


def upload(token, wid, did, file: Path, table: str):
    boundary = uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"table_name\"\r\n\r\n{table}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{file.name}\"\r\nContent-Type: text/csv\r\n\r\n".encode()
        + file.read_bytes() + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return call("POST", f"/workspaces/{wid}/datasets/{did}/upload", raw=b"".join(parts), token=token,
                content_type=f"multipart/form-data; boundary={boundary}")


def query(token, wid, did, select, where=None, roles=None):
    body = {"query": {"from": [], "select": select, **({"where": where} if where else {})}, "roles": roles or []}
    return call("POST", f"/workspaces/{wid}/datasets/{did}/query", body, token)


def m(table, measure):
    return {"measure": {"table": table, "measure": measure}}


def col(table, column):
    return {"column": {"table": table, "column": column}}


# ---------------------------------------------------------------- data

REGIONS = {"North": "Asha", "South": "Baraka", "East": "Chausiku", "West": "Daudi"}
PRODUCTS = ["Gloves", "Syringes", "Masks"]


def make_data():
    rows = []
    order = 1
    for year in (2025, 2026):
        for month in range(1, 13):
            if year == 2026 and month > 9:
                break
            for index, region in enumerate(REGIONS):
                amount = 100 * (index + 1) + month * 7 + (year - 2025) * 50
                rows.append({"OrderID": order, "OrderDate": f"{year}-{month:02d}-15", "Region": region,
                             "Product": PRODUCTS[(order + index) % 3], "Amount": amount})
                order += 1
    data = HERE / "data"
    data.mkdir(exist_ok=True)
    with (data / "sales.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (data / "regions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Region", "Manager"])
        writer.writerows(REGIONS.items())
    return rows


# ---------------------------------------------------------------- browser

async def go(tab, url, wait=3.0):
    await tab.send("Page.navigate", {"url": url})
    await asyncio.sleep(wait)


async def text(tab, js):
    return await tab.evaluate(js)


async def shot(tab, name):
    await tab.screenshot(SHOTS / f"{name}.png")


async def set_input(tab, selector, value):
    await tab.evaluate(f"""(() => {{ const el = document.querySelector({json.dumps(selector)});
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      set.call(el, {json.dumps(value)}); el.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()""")


async def click_text(tab, selector, label):
    return await tab.evaluate(f"""(() => {{
      const el = [...document.querySelectorAll({json.dumps(selector)})].find((n) => n.textContent.trim().includes({json.dumps(label)}));
      if (!el) return false; el.click(); return true; }})()""")


async def mouse_click(tab, x, y):
    """A real click as the chart library sees it: press, release and click at one point."""
    await tab.evaluate(f"""(() => {{
      const target = document.elementFromPoint({x}, {y});
      for (const type of ['mousemove', 'mousedown', 'mouseup', 'click']) {{
        target.dispatchEvent(new MouseEvent(type, {{ clientX: {x}, clientY: {y}, bubbles: true, cancelable: true, view: window, button: 0 }}));
      }} }})()""")


FIND_BAR = r"""
(([colour]) => {
  const want = colour.match(/[0-9a-f]{2}/gi).map((h) => parseInt(h, 16));
  for (const canvas of document.querySelectorAll('.visual canvas')) {
    const box = canvas.getBoundingClientRect();
    const ctx = canvas.getContext('2d');
    if (!ctx || box.width < 50) continue;
    const ratio = canvas.width / box.width;
    const y = Math.floor(canvas.height * 0.82);
    const row = ctx.getImageData(0, y, canvas.width, 1).data;
    const runs = [];
    let start = -1;
    for (let x = 0; x < canvas.width; x++) {
      const i = x * 4;
      const hit = Math.abs(row[i] - want[0]) < 6 && Math.abs(row[i + 1] - want[1]) < 6 && Math.abs(row[i + 2] - want[2]) < 6;
      if (hit && start < 0) start = x;
      if (!hit && start >= 0) { runs.push([start, x]); start = -1; }
    }
    if (runs.length >= 2) {
      const [a, b] = runs[0];
      return { x: box.left + (a + b) / 2 / ratio, y: box.top + y / ratio, bars: runs.length };
    }
  }
  return null;
})
"""


# ---------------------------------------------------------------- run

async def browser_flows(ctx):
    chrome = Chrome()
    try:
        async with websockets.connect(chrome.new_tab(), max_size=64 * 1024 * 1024) as socket:
            tab = Tab(socket)
            await tab.send("Page.enable")
            await tab.send("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})

            # --- sign in
            await go(tab, f"{WEB}/workspaces")
            path = await text(tab, "location.pathname")
            record("Sign-in", "App pages need a session", "Power BI sends you to sign in", path == "/login", f"landed on {path}")
            await set_input(tab, "#signin-email", ctx["email"])
            await set_input(tab, "#signin-password", "not-the-password")
            await tab.evaluate("document.querySelector('.signin-submit').click()")
            await asyncio.sleep(2)
            error = await text(tab, "document.body.innerText.includes(\"don't match\")")
            record("Sign-in", "Wrong password is refused with a clear message", "Same", error, "message shown" if error else "no message")
            await set_input(tab, "#signin-password", ctx["password"])
            await tab.evaluate("document.querySelector('.signin-submit').click()")
            await asyncio.sleep(3)
            path = await text(tab, "location.pathname")
            record("Sign-in", "Right password opens the workspace list", "Same", path == "/workspaces", path)
            listed = await text(tab, "document.body.innerText.includes('E2E check')")
            record("Workspaces", "The workspace appears in the list", "Workspaces list", listed, "")
            await shot(tab, "01-workspaces")

            # --- report viewer
            view = f"{WEB}/workspaces/{ctx['wid']}/reports/{ctx['rid']}/view"
            await go(tab, view, 6)
            await shot(tab, "02-report")
            state = await text(tab, """(() => ({
              visuals: document.querySelectorAll('.visual').length,
              canvases: document.querySelectorAll('.visual canvas').length,
              card: document.querySelector('.card-number')?.textContent ?? null,
              table: document.querySelectorAll('.data-table tbody tr').length,
              errors: [...document.querySelectorAll('.visual')].map((v) => v.innerText).filter((t) => /fail|error|couldn/i.test(t)),
            }))()""")
            record("Report view", "Every visual draws with data", "Report reading view",
                   state["visuals"] >= 6 and state["canvases"] >= 3 and not state["errors"],
                   f"{state['visuals']} visuals, {state['canvases']} charts, errors: {state['errors'] or 'none'}")
            card = (state["card"] or "").replace(",", "").split(".")[0]
            record("Report view", "Card shows the dataset total", "Card visual", card == str(ctx["total"]),
                   f"card '{state['card']}', expected {ctx['total']:,}")
            record("Report view", "Card uses the measure's format string (#,0)", "Power BI cards follow the measure format",
                   state["card"] == f"{ctx['total']:,}", f"card '{state['card']}'")
            record("Report view", "Table lists one row per region", "Table visual", state["table"] == 4, f"{state['table']} rows")

            # --- cross-filter: click the first column
            target = None
            for colour in ("#118DFF", ctx["first_colour"]):
                target = target or await tab.evaluate(f"({FIND_BAR})({json.dumps([colour])})")
            if target:
                await mouse_click(tab, target["x"], target["y"])
                await asyncio.sleep(3)
                after = await text(tab, "document.querySelector('.card-number')?.textContent ?? ''")
                changed = after.replace(",", "").split(".")[0] != card
                record("Interactions", "Clicking a column filters the other visuals", "Cross-filter on click", changed,
                       f"card {state['card']} → {after} after clicking 1 of {target['bars']} columns")
                await shot(tab, "03-cross-filter")
                await mouse_click(tab, target["x"], target["y"])
                await asyncio.sleep(2)
            else:
                record("Interactions", "Clicking a column filters the other visuals", "Cross-filter on click", False, "no column found to click")

            # --- slicer
            await go(tab, view, 6)
            picked = await tab.evaluate("""(() => {
              const select = [...document.querySelectorAll('.slicer select')].find((s) => [...s.options].some((o) => o.value === 'North'));
              if (!select) return false;
              Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(select, 'North');
              select.dispatchEvent(new Event('change', { bubbles: true })); return true; })()""")
            await asyncio.sleep(3)
            sliced = (await text(tab, "document.querySelector('.card-number')?.textContent ?? ''")).replace(",", "").split(".")[0]
            record("Interactions", "A slicer filters the page", "Slicer", picked and sliced == str(ctx["north"]),
                   f"North picked: card {sliced}, expected {ctx['north']}")
            await shot(tab, "04-slicer")

            # --- reader switches
            await go(tab, view, 5)
            await click_text(tab, "button", "High contrast")
            await asyncio.sleep(1.5)
            bg = await text(tab, "getComputedStyle(document.querySelector('.page')).backgroundColor")
            await shot(tab, "05-high-contrast")
            await go(tab, view, 5)
            kept = await text(tab, "localStorage.getItem('magbi.reader.highContrast') === '1' && getComputedStyle(document.querySelector('.page')).backgroundColor === 'rgb(255, 255, 255)'")
            record("Themes", "High contrast switch for the reader, kept after reload", "Windows high contrast / accessible themes",
                   bg == "rgb(255, 255, 255)" and kept, f"page {bg}, kept after reload: {kept}")
            await click_text(tab, "button", "High contrast")
            await asyncio.sleep(1)
            await click_text(tab, "button", "Larger text")
            await asyncio.sleep(1.5)
            scale = await text(tab, "getComputedStyle(document.querySelector('.card-number') || document.body).fontSize")
            record("Themes", "Larger text switch", "No direct equivalent (mobile layout is separate)", True, f"card font now {scale}", severity="info")
            await click_text(tab, "button", "Larger text")

            # --- designer: gallery, customize, import
            designer = f"{WEB}/workspaces/{ctx['wid']}/datasets/{ctx['did']}/designer?report={ctx['rid']}"
            await go(tab, designer, 6)
            loaded = await text(tab, "document.body.innerText.includes('E2E Sales report')")
            record("Designer", "Report opens in the designer", "Edit report", loaded, "")
            await click_text(tab, ".ribbon-tab, button", "Format")
            await asyncio.sleep(0.5)
            await click_text(tab, "button.rb", "Themes")
            await asyncio.sleep(1)
            tiles = await text(tab, "document.querySelectorAll('.theme-tile').length")
            await shot(tab, "06-gallery")
            await click_text(tab, ".theme-tile-name", "Health")
            await asyncio.sleep(4)
            _status, saved = call("GET", f"/workspaces/{ctx['wid']}/reports/{ctx['rid']}", token=ctx["token"])
            draft_theme = (saved.get("draft") or {}).get("theme", {})
            record("Themes", "Gallery applies a theme and the draft saves it", "View → Themes",
                   tiles >= 9 and draft_theme.get("id") == "health", f"{tiles} themes shown, draft theme {draft_theme}")
            record("Designer", "Editing saves a draft; viewers still see the published report", "Power BI: edits stay unsaved until Save",
                   saved.get("has_draft") and (saved["definition"].get("theme") or {}).get("id") != "health",
                   f"published theme {saved['definition'].get('theme')}, draft theme {draft_theme}")
            status_text = await text(tab, "document.querySelector('.statusbar')?.innerText ?? ''")
            record("Designer", "The status bar says the draft isn't published", "Unsaved changes indicator",
                   "not published" in status_text, status_text.split("|")[1].strip()[:90] if "|" in status_text else status_text[:90])
            await shot(tab, "07-health")

            await click_text(tab, "button.rb", "Customize")
            await asyncio.sleep(1)
            await tab.evaluate("""(() => {
              const field = [...document.querySelectorAll('.theme-field')].find((f) => f.textContent.startsWith('Muted text'));
              const input = field.querySelector('input[type=color]');
              Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '#d0d0d0');
              input.dispatchEvent(new Event('input', { bubbles: true })); })()""")
            await asyncio.sleep(0.5)
            blocked = await text(tab, "[...document.querySelectorAll('.theme-actions button')].find((b) => b.textContent.includes('Save')).disabled")
            problems = await text(tab, "document.querySelectorAll('.theme-problems li').length")
            record("Themes", "Customize refuses an unreadable theme and says why", "Customize current theme (no checks in Power BI)",
                   blocked and problems > 0, f"{problems} problems listed, Save disabled: {blocked}")
            await shot(tab, "08-customize-refused")
            await tab.evaluate("""(() => {
              const field = [...document.querySelectorAll('.theme-field')].find((f) => f.textContent.startsWith('Muted text'));
              const input = field.querySelector('input[type=color]');
              Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '#4d6566');
              input.dispatchEvent(new Event('input', { bubbles: true }));
              [...document.querySelectorAll('.theme-targets input')][1]?.click(); })()""")
            await asyncio.sleep(0.5)
            await set_input(tab, ".theme-dialog input[type=text]", "E2E team theme")
            await click_text(tab, ".theme-check", "Use for every report")
            await asyncio.sleep(0.3)
            await click_text(tab, ".theme-actions button", "Save theme")
            await asyncio.sleep(3)
            _status, ws = call("GET", f"/workspaces/{ctx['wid']}/themes", token=ctx["token"])
            names = [item["name"] for item in ws["workspace"]]
            record("Themes", "Customize saves a workspace theme for everyone in the workspace", "Organizational themes (admin portal)",
                   "E2E team theme" in names, f"workspace themes: {names}")

            # import a Power BI theme file through the ribbon
            file = HERE / "data" / "contoso.json"
            file.write_text(json.dumps({"name": "Contoso", "dataColors": ["#0B5394", "#E69138", "#6AA84F", "#674EA7"],
                                        "good": "#38761D", "neutral": "#BF9000", "bad": "#990000"}), encoding="utf-8")
            await tab.send("DOM.enable")
            doc = await tab.send("DOM.getDocument", {"depth": -1})
            found = await tab.send("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": "label.rb input[type=file]"})
            await tab.send("DOM.setFileInputFiles", {"nodeId": found["nodeId"], "files": [str(file)]})
            await asyncio.sleep(4)
            _status, saved = call("GET", f"/workspaces/{ctx['wid']}/reports/{ctx['rid']}", token=ctx["token"])
            colours = (saved.get("draft") or {}).get("theme", {}).get("overrides", {}).get("data", {}).get("categorical")
            record("Themes", "Import a Power BI theme JSON file", "View → Themes → Browse for themes", colours == ["#0B5394", "#E69138", "#6AA84F", "#674EA7"],
                   f"saved chart colours {colours}")
            await shot(tab, "09-imported")
            await click_text(tab, ".ribbon-tab, button", "Home")
            await asyncio.sleep(0.5)
            await click_text(tab, "button.rb", "Publish")
            await asyncio.sleep(3)
            _status, saved = call("GET", f"/workspaces/{ctx['wid']}/reports/{ctx['rid']}", token=ctx["token"])
            live = (saved["definition"].get("theme") or {}).get("overrides", {}).get("data", {}).get("categorical")
            record("Designer", "Publish makes the draft live and clears it", "File → Save / Publish",
                   not saved.get("has_draft") and live == ["#0B5394", "#E69138", "#6AA84F", "#674EA7"], f"has draft {saved.get('has_draft')}, live colours {live}")

            # --- organisation lock (created and removed straight away)
            status, org = call("POST", "/organisation/themes", {"name": "E2E lock check", "definition": {"extends": "enterprise-light"},
                                                              "isDefault": True, "locked": True})
            try:
                await go(tab, designer, 6)
                await click_text(tab, ".ribbon-tab, button", "Format")
                await asyncio.sleep(0.5)
                await click_text(tab, "button.rb", "Themes")
                await asyncio.sleep(1)
                banner = await text(tab, "document.querySelector('.theme-locked')?.textContent ?? ''")
                disabled = await text(tab, "[...document.querySelectorAll('.theme-tile')].every((t) => t.disabled)")
                await shot(tab, "10-locked")
                record("Themes", "A locked organisation theme holds every report", "Organizational themes cannot be locked in Power BI",
                       status == 201 and "locked" in banner and disabled, banner.strip()[:90])
            finally:
                if isinstance(org, dict) and org.get("id"):
                    call("DELETE", f"/organisation/themes/{org['id']}")

            # --- embed
            secret = call("POST", "/admin/service-tokens", {"workspaceId": ctx["wid"], "name": f"e2e-{secrets.token_hex(3)}"})[1]["token"]
            status, minted = call("POST", "/embed/token", {"userEmail": "reader@example.com", "userName": "Reader", "reports": [ctx["rid"]],
                                                         "datasets": [ctx["did"]], "rls": {"roles": ["North only"]}}, secret)
            embed_token = minted["token"]
            await go(tab, f"{WEB}/embed/{ctx['rid']}?token={embed_token}&themeId=finance", 6)
            page = await text(tab, "getComputedStyle(document.querySelector('.page')).backgroundColor")
            card_embed = (await text(tab, "document.querySelector('.card-number')?.textContent ?? ''")).replace(",", "").split(".")[0]
            await shot(tab, "11-embed")
            record("Embedding", "Embedded report opens with a host-picked theme", "Embed for your customers + themes via report JSON",
                   page == "rgb(240, 242, 245)", f"page {page} (Finance is rgb(240, 242, 245))")
            record("Embedding", "Embed token carries row-level security", "Embed token with effective identity (RLS)",
                   card_embed == str(ctx["north"]), f"card {card_embed}, North only = {ctx['north']}")
            # other routes refused for the embed token
            refused = call("GET", f"/workspaces/{ctx['wid']}/datasets", token=embed_token)[0]
            record("Embedding", "Embed token cannot reach other routes", "Embed tokens are scoped", refused == 403, f"GET datasets → {refused}")

            # --- sign out
            await go(tab, f"{WEB}/workspaces", 3)
            await click_text(tab, "button", "Sign out")
            await asyncio.sleep(2)
            path = await text(tab, "location.pathname")
            await go(tab, view, 3)
            back = await text(tab, "location.pathname")
            record("Sign-in", "Sign out ends the session", "Sign out", path == "/login" and back == "/login", f"after sign out {path}, report link → {back}")

            # --- a viewer
            await go(tab, f"{WEB}/login", 2)
            await set_input(tab, "#signin-email", ctx["viewer_email"])
            await set_input(tab, "#signin-password", ctx["viewer_password"])
            await tab.evaluate("document.querySelector('.signin-submit').click()")
            await asyncio.sleep(3)
            await go(tab, f"{WEB}/workspaces/{ctx['wid']}", 3)
            await click_text(tab, ".ws-tab", "Reports")
            await asyncio.sleep(1.5)
            edit_buttons = await text(tab, "[...document.querySelectorAll('button')].filter((b) => /designer|New dataset|New connection/.test(b.textContent)).length")
            record("Security", "A viewer gets no edit actions in the workspace", "Viewers can't edit in Power BI", edit_buttons == 0, f"{edit_buttons} edit buttons shown")
            await go(tab, designer, 5)
            landed = await text(tab, "location.pathname")
            record("Security", "A viewer who opens the designer is sent to the report view", "Viewers can't edit in Power BI",
                   landed.endswith(f"/reports/{ctx['rid']}/view"), landed)
            await asyncio.sleep(3)
            card_viewer = (await text(tab, "document.querySelector('.card-number')?.textContent ?? ''")).replace(",", "").split(".")[0]
            await shot(tab, "12-viewer-rls")
            record("Security", "A viewer in the role 'North only' sees only North in the app", "RLS role members (Manage security)",
                   card_viewer == str(ctx["north"]), f"card {card_viewer}, North = {ctx['north']}")
    finally:
        chrome.close()


def api_flows():
    ctx = {}
    password = secrets.token_urlsafe(12)
    email = "e2e-editor@magbi.test"
    login = DATA / "e2e-login.json"
    if login.exists():
        saved = json.loads(login.read_text(encoding="utf-8"))
        email, password = saved["email"], saved["password"]
    else:
        status, body = call("POST", "/admin/users", {"email": email, "name": "E2E Editor", "password": password})
        assert status == 201, body
        login.write_text(json.dumps({"email": email, "password": password}), encoding="utf-8")
    ctx.update(email=email, password=password)
    viewer_login = DATA / "e2e-viewer.json"
    if viewer_login.exists():
        viewer = json.loads(viewer_login.read_text(encoding="utf-8"))
    else:
        viewer = {"email": "e2e-viewer@magbi.test", "password": secrets.token_urlsafe(12)}
        status, body = call("POST", "/admin/users", {"email": viewer["email"], "name": "E2E Viewer", "password": viewer["password"]})
        assert status == 201, body
        viewer_login.write_text(json.dumps(viewer), encoding="utf-8")
    ctx.update(viewer_email=viewer["email"], viewer_password=viewer["password"])

    workspaces = call("GET", "/workspaces")[1]
    wid = next((w["id"] for w in workspaces if w["name"] == "E2E check"), None) or call("POST", "/workspaces", {"name": "E2E check"})[1]["id"]
    call("POST", f"/workspaces/{wid}/members", {"email": email, "role": "admin"})
    call("POST", f"/workspaces/{wid}/members", {"email": ctx["viewer_email"], "role": "viewer"})
    token = call("POST", "/auth/login", {"email": email, "password": password})[1]["token"]
    ctx.update(wid=wid, token=token)
    record("Workspaces", "Editor signs in and is a workspace admin", "Workspace roles", bool(token), wid)

    # get data
    rows = make_data()
    name = f"E2E Sales {time.strftime('%H%M%S')}"
    status, dataset = call("POST", f"/workspaces/{wid}/datasets", {"name": name}, token)
    did = dataset["id"]
    s1, _ = upload(token, wid, did, HERE / "data" / "sales.csv", "Sales")
    s2, _ = upload(token, wid, did, HERE / "data" / "regions.csv", "Region")
    record("Get data", "Upload two CSV files as tables", "Get data → Text/CSV", s1 in (200, 201) and s2 in (200, 201), f"{s1}, {s2}")
    ctx["did"] = did

    # model
    definition = call("GET", f"/workspaces/{wid}/datasets/{did}/definition", token=token)[1]
    version = definition["model_version"]
    status, body = call("POST", f"/workspaces/{wid}/datasets/{did}/definition/relationships", {"model_version": version, "relationship": {
        "from": {"table": "Sales", "column": "Region"}, "to": {"table": "Region", "column": "Region"}, "cardinality": "many-to-one"}}, token)
    message = (body.get("error", {}).get("validation", {}).get("errors") or [{}])[0].get("message", "") if isinstance(body, dict) else ""
    record("Model", "Relationship on a unique column works without marking it as a key", "Power BI detects the unique side by itself",
           status in (200, 201), f"{status}: {message}", severity=None if status in (200, 201) else "gap")
    if status not in (200, 201):
        model = definition["definition"]
        for table in model["tables"]:
            if table["name"] == "Region":
                for column in table["columns"]:
                    if column["name"] == "Region":
                        column["is_primary_key"] = True
        call("PUT", f"/workspaces/{wid}/datasets/{did}/definition", {"model_version": version, "definition": model}, token)
        version = call("GET", f"/workspaces/{wid}/datasets/{did}/definition", token=token)[1]["model_version"]
        call("POST", f"/workspaces/{wid}/datasets/{did}/definition/relationships", {"model_version": version, "relationship": {
            "from": {"table": "Sales", "column": "Region"}, "to": {"table": "Region", "column": "Region"}, "cardinality": "many-to-one"}}, token)
    version = call("GET", f"/workspaces/{wid}/datasets/{did}/definition", token=token)[1]["model_version"]
    # a repeating column is refused with how many repeat
    dupes = HERE / "data" / "dupes.csv"
    dupes.write_text("Region,Note\nNorth,a\nNorth,b\n", encoding="utf-8")
    upload(token, wid, did, dupes, "Dupes")
    version = call("GET", f"/workspaces/{wid}/datasets/{did}/definition", token=token)[1]["model_version"]
    status, body = call("POST", f"/workspaces/{wid}/datasets/{did}/definition/relationships", {"model_version": version, "relationship": {
        "from": {"table": "Sales", "column": "Region"}, "to": {"table": "Dupes", "column": "Region"}, "cardinality": "many-to-one"}}, token)
    message = body.get("error", {}).get("message", "") if isinstance(body, dict) else str(body)
    record("Model", "A repeating column is refused as the one side, with the count", "Power BI refuses it too",
           status == 422 and "repeat" in message, f"{status}: {message}")
    version = call("GET", f"/workspaces/{wid}/datasets/{did}/definition", token=token)[1]["model_version"]
    for measure in ({"name": "Total sales", "expression": "SUM(Sales[Amount])", "format": "#,0"},
                    {"name": "Orders", "expression": "COUNTROWS(Sales)", "format": "#,0"},
                    {"name": "Average order", "expression": "DIVIDE([Total sales], [Orders])", "format": "#,0.0"},
                    {"name": "North sales", "expression": "CALCULATE([Total sales], Region[Region] = \"North\")", "format": "#,0"}):
        status, body = call("POST", f"/workspaces/{wid}/datasets/{did}/definition/measures", {"model_version": version, "table": "Sales", "measure": measure}, token)
        record("Model", f"DAX measure {measure['name']} = {measure['expression']}", "New measure (DAX)", status in (200, 201), "" if status in (200, 201) else str(body)[:300])
        version = call("GET", f"/workspaces/{wid}/datasets/{did}/definition", token=token)[1]["model_version"]
    status, body = call("POST", f"/workspaces/{wid}/datasets/{did}/definition/measures", {"model_version": version, "table": "Sales",
                        "measure": {"name": "Ranked", "expression": "RANKX(ALL(Region), [Total sales])"}}, token)
    message = (body.get("error", {}).get("validation", {}).get("errors") or [{}])[0].get("message", "") if isinstance(body, dict) else str(body)
    record("Model", "RANKX measure", "RANKX works in Power BI", status in (200, 201), message, severity=None if status in (200, 201) else "gap")
    if status in (200, 201):
        ranked = query(token, wid, did, [col("Region", "Region"), m("Sales", "Ranked")])
        ranks = {row[0]: row[1] for row in ranked[1]["rows"]} if ranked[0] == 200 else {}
        record("Engine", "RANKX ranks the visual's rows", "RANKX(ALL(Region), [Total sales])",
               ranks == {"West": 1, "East": 2, "South": 3, "North": 4}, str(ranks))
    version = call("GET", f"/workspaces/{wid}/datasets/{did}/definition", token=token)[1]["model_version"]
    status, body = call("POST", f"/workspaces/{wid}/datasets/{did}/definition/date-table", {"model_version": version}, token)
    record("Model", "Generate a date table", "Mark as date table / CALENDARAUTO", status in (200, 201), str(status) if status in (200, 201) else str(body)[:300])

    # figures
    total = sum(r["Amount"] for r in rows)
    north = sum(r["Amount"] for r in rows if r["Region"] == "North")
    ctx.update(total=total, north=north)
    status, body = query(token, wid, did, [m("Sales", "Total sales"), m("Sales", "Orders")])
    got = body["rows"][0] if status == 200 else None
    record("Engine", "Totals match the CSV", "Same numbers as Power BI", got and round(got[0]) == total and got[1] == len(rows), f"{got} vs {total}, {len(rows)}")
    status, body = query(token, wid, did, [col("Region", "Region"), m("Sales", "Total sales")])
    by_region = {r[0]: r[1] for r in body["rows"]} if status == 200 else {}
    expected = {region: sum(r["Amount"] for r in rows if r["Region"] == region) for region in REGIONS}
    record("Engine", "Dimension groups the fact through the relationship", "Same", by_region == expected, json.dumps(by_region))
    status, body = query(token, wid, did, [m("Sales", "Total sales")], where=[{"column": {"table": "Region", "column": "Manager"}, "operator": "eq", "values": ["Asha"]}])
    record("Engine", "A filter on the dimension filters the fact", "Single-direction filter", status == 200 and round(body["rows"][0][0]) == north, str(body["rows"] if status == 200 else body)[:120])
    status, body = query(token, wid, did, [m("Sales", "North sales")])
    record("Engine", "CALCULATE with a filter argument", "CALCULATE", status == 200 and round(body["rows"][0][0]) == north, str(body["rows"] if status == 200 else body)[:120])

    # RLS
    definition = call("GET", f"/workspaces/{wid}/datasets/{did}/definition", token=token)[1]
    model = definition["definition"]
    model["roles"] = [{"name": "Short form", "table_filters": [{"table": "Region", "expression": "[Region] = \"North\""}]}]
    status, body = call("PUT", f"/workspaces/{wid}/datasets/{did}/definition", {"model_version": definition["model_version"], "definition": model}, token)
    short = query(token, wid, did, [m("Sales", "Total sales")], roles=["Short form"])
    record("Security", "RLS rule written as [Region] = \"North\" on the Region table", "Power BI accepts the unqualified column",
           short[0] == 200, f"{short[0]}: {str(short[1])[:200]}", severity=None if short[0] == 200 else "gap")
    definition = call("GET", f"/workspaces/{wid}/datasets/{did}/definition", token=token)[1]
    model = definition["definition"]
    model["roles"] = [{"name": "North only", "table_filters": [{"table": "Region", "expression": "Region[Region] = \"North\""}],
                       "members": [ctx["viewer_email"]]}]
    status, body = call("PUT", f"/workspaces/{wid}/datasets/{did}/definition", {"model_version": definition["model_version"], "definition": model}, token)
    record("Security", "Define a row-level security role", "Manage roles", status == 200, "" if status == 200 else str(body)[:300])
    status, body = query(token, wid, did, [m("Sales", "Total sales")], roles=["North only"])
    record("Security", "View as role returns only that role's rows", "View as role", status == 200 and round(body["rows"][0][0]) == north, str(body["rows"] if status == 200 else body)[:120])

    # report
    def visual(kind, x, y, w, h, wells, **props):
        return {"id": f"e2e-{kind}-{x}-{y}", "type": kind, "x": x, "y": y, "width": w, "height": h, "wells": wells, "properties": props}
    region = {"table": "Region", "column": "Region"}
    report = {
        "schemaVersion": "1.0", "name": f"E2E Sales report {time.strftime('%H%M%S')}", "datasetId": did,
        "pages": [{"name": "page-1", "displayName": "Sales", "width": 1760, "height": 990, "visuals": [
            visual("card", 40, 40, 380, 160, {"y-axis": [{"table": "Sales", "measure": "Total sales"}]}, title="Total sales"),
            visual("slicer", 440, 40, 380, 160, {"field": [region]}, slicerMode="dropdown", caption="Region"),
            visual("column", 40, 220, 820, 360, {"x-axis": [region], "y-axis": [{"table": "Sales", "measure": "Total sales"}]}, title="Sales by region"),
            visual("pie", 880, 220, 400, 360, {"x-axis": [{"table": "Sales", "column": "Product"}], "y-axis": [{"table": "Sales", "measure": "Orders"}]}, title="Orders by product"),
            visual("line", 40, 600, 820, 360, {"x-axis": [{"table": "Sales", "column": "OrderDate"}], "y-axis": [{"table": "Sales", "measure": "Total sales"}]}, title="Sales over time"),
            visual("table", 880, 600, 840, 360, {"columns": [region, {"table": "Sales", "measure": "Total sales"}, {"table": "Sales", "measure": "Average order"}]}, title="Regions"),
        ]}],
    }
    status, created = call("POST", f"/workspaces/{wid}/reports", {"name": report["name"], "dataset_id": did, "definition": report, "is_published": True}, token)
    rid = created["id"]
    record("Report", "Save and publish a report with six visuals", "Publish", status in (200, 201), rid)
    ctx.update(rid=rid, first_colour="#3F6FB0")
    # drop any workspace theme from a previous run so the report starts in Enterprise Light
    for theme in call("GET", f"/workspaces/{wid}/themes", token=token)[1]["workspace"]:
        call("DELETE", f"/workspaces/{wid}/themes/{theme['id']}", token=token)

    odata_flow(ctx)
    if WAREHOUSE is not None:
        refresh_flow()
    return ctx


# ---------------------------------------------------------------- a source to refresh from

STOCK = [{"ItemID": i, "Item": f"Item {i}", "Store": ["Dodoma", "Mwanza", "Mbeya"][i % 3], "Quantity": i * 10,
          "Received": f"2026-{(i % 9) + 1:02d}-0{(i % 8) + 1}T08:00:00Z", "Site": {"Region": "Central" if i % 2 else "Lake"}}
         for i in range(1, 8)]
STOCK_METADATA = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx"><edmx:DataServices>
<Schema Namespace="E2E" xmlns="http://docs.oasis-open.org/odata/ns/edm">
<ComplexType Name="Site"><Property Name="Region" Type="Edm.String"/></ComplexType>
<EntityType Name="Stock"><Key><PropertyRef Name="ItemID"/></Key>
<Property Name="ItemID" Type="Edm.Int32" Nullable="false"/><Property Name="Item" Type="Edm.String"/>
<Property Name="Store" Type="Edm.String"/><Property Name="Quantity" Type="Edm.Int64"/>
<Property Name="Received" Type="Edm.DateTimeOffset"/><Property Name="Site" Type="E2E.Site"/></EntityType>
<EntityContainer Name="Container"><EntitySet Name="Stock" EntityType="E2E.Stock"/></EntityContainer>
</Schema></edmx:DataServices></edmx:Edmx>"""


class _ODataStub(BaseHTTPRequestHandler):
    """A read-only OData v4 service with one entity set, 3 records per page."""

    def log_message(self, *args):  # keep the run's output to the steps
        pass

    def _send(self, status, body, kind="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("OData-Version", "4.0")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
        root = f"http://127.0.0.1:{self.server.server_port}/odata/"
        if path in ("/odata", "/odata/"):
            return self._send(200, {"value": [{"name": "Stock", "kind": "EntitySet", "url": "Stock"}]})
        if path == "/odata/$metadata":
            return self._send(200, STOCK_METADATA, "application/xml")
        if path == "/odata/Stock/$count":
            return self._send(200, str(len(STOCK)), "text/plain")
        if path == "/odata/Stock":
            skip = int(params.get("$skiptoken", "0"))
            top = int(params["$top"]) if "$top" in params else None
            page = STOCK[skip: skip + 3]
            body = {"value": page[:top] if top is not None else page}
            if top is None and skip + 3 < len(STOCK):
                body["@odata.nextLink"] = f"{root}Stock?$skiptoken={skip + 3}"
            return self._send(200, body)
        return self._send(404, {"error": "not found"})


def odata_flow(ctx):
    """Connection → dataset → refresh → query, from a source this script serves."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ODataStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/odata/"
    wid, token = ctx["wid"], ctx["token"]
    try:
        status, tested = call("POST", f"/workspaces/{wid}/connections/test", {"kind": "odata", "config": {"url": url}}, token)
        record("Data refresh", "Test a connection to an OData feed", "Get data → OData feed",
               status == 200 and tested.get("success"), json.dumps(tested)[:120])
        name = f"E2E feed {time.strftime('%H%M%S')}"
        status, conn = call("POST", f"/workspaces/{wid}/connections", {"name": name, "kind": "odata", "config": {"url": url}}, token)
        cid = conn["id"] if status == 201 else None
        status, tables = call("GET", f"/workspaces/{wid}/connections/{cid}/tables?schema=odata", token=token)
        columns = [c["name"] for c in tables["tables"][0]["columns"]] if status == 200 and tables["tables"] else []
        record("Data refresh", "Browse the feed's tables and columns", "Navigator",
               columns == ["ItemID", "Item", "Store", "Quantity", "Received", "Site_Region"], str(columns))
        status, ds = call("POST", f"/workspaces/{wid}/datasets", {"name": name, "import_spec": {
            "connection_id": cid, "tables": [{"schema": "odata", "name": "Stock"}]}}, token)
        did = ds["id"]
        call("POST", f"/workspaces/{wid}/datasets/{did}/refresh", {}, token)
        final = None
        for _ in range(60):
            time.sleep(1)
            history = call("GET", f"/workspaces/{wid}/datasets/{did}/refresh/history", token=token)[1]
            if history and history[0]["status"] in ("succeeded", "failed"):
                final = history[0]
                break
        record("Data refresh", "Refresh now imports every page of the feed", "Refresh now",
               final is not None and final["status"] == "succeeded", f"{final['status']} ({final.get('error') or 'no error'})" if final else "timed out")
        status, body = query(token, wid, did, [col("Stock", "Site_Region"),
                                                {"column": {"table": "Stock", "column": "Quantity"}, "aggregation": "sum"}])
        got = {row[0]: row[1] for row in body["rows"]} if status == 200 else body
        expected = {"Central": sum(s["Quantity"] for s in STOCK if s["Site"]["Region"] == "Central"),
                    "Lake": sum(s["Quantity"] for s in STOCK if s["Site"]["Region"] == "Lake")}
        record("Data refresh", "The refreshed table has its columns and the right totals", "Same numbers as the source",
               got == expected, f"{got} vs {expected}")
    finally:
        server.shutdown()


def refresh_flow():
    """Refresh a dataset from its real source, when --warehouse names one."""
    assert WAREHOUSE is not None
    wid_w, did_w = WAREHOUSE
    status, job = call("POST", f"/workspaces/{wid_w}/datasets/{did_w}/refresh", {})
    started = time.time()
    state = None
    if status in (200, 201, 202):
        job_id = job.get("refresh_id")
        for _ in range(60):
            time.sleep(2)
            state = call("GET", f"/workspaces/{wid_w}/datasets/{did_w}/refresh/{job_id}")[1]
            if str(state.get("status")).lower() in ("succeeded", "success", "completed", "failed", "error"):
                break
    ok = state is not None and str(state.get("status")).lower() in ("succeeded", "success", "completed")
    record("Data refresh", "Refresh now from the warehouse's own source (read-only)", "Refresh now / scheduled refresh", ok,
           f"{state.get('status') if state else status} in {time.time() - started:.0f} s")
    schedule = call("GET", f"/workspaces/{wid_w}/datasets/{did_w}")[1].get("schedule_cron")
    record("Data refresh", "A daily schedule is set on the Warehouse dataset", "Scheduled refresh", bool(schedule), str(schedule)[:80], severity=None if schedule else "info")


def main() -> int:
    global HERE, SHOTS, DATA, API, WEB, WAREHOUSE
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="the API server")
    parser.add_argument("--web", default="http://localhost:3000", help="the web app")
    parser.add_argument("--out", type=Path, default=SERVER / "e2e-results", help="where results.json and screenshots go")
    parser.add_argument("--data", type=Path, default=SERVER / "data", help="where the test logins are kept (gitignored)")
    parser.add_argument("--warehouse", help="WORKSPACE_ID:DATASET_ID of a dataset to refresh from its real source as well")
    parser.add_argument("--refresh-only", action="store_true", help="only refresh --warehouse")
    args = parser.parse_args()
    HERE, DATA = args.out.resolve(), args.data.resolve()
    SHOTS = HERE / "shots"
    API, WEB = args.api.rstrip("/") + "/api/v1", args.web.rstrip("/")
    if args.warehouse:
        workspace, _, dataset = args.warehouse.partition(":")
        WAREHOUSE = (workspace, dataset)
    if args.refresh_only and WAREHOUSE is None:
        parser.error("--refresh-only needs --warehouse")
    SHOTS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        if args.refresh_only:
            refresh_flow()
        else:
            ctx = api_flows()
            asyncio.run(browser_flows(ctx))
    except Exception:  # noqa: BLE001 - keep what was recorded
        traceback.print_exc()
        RESULTS.append({"area": "Run", "step": "The run stopped early", "powerBi": "", "ok": False, "detail": traceback.format_exc()[-600:], "severity": "fail"})
    name = "results-refresh.json" if args.refresh_only else "results.json"
    (HERE / name).write_text(json.dumps(RESULTS, indent=1), encoding="utf-8")
    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"{passed} of {len(RESULTS)} steps passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
