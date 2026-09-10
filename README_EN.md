# veddata

> **Disclaimer**: This project is for educational, research, and technical exchange purposes only. Users are responsible for complying with target websites' `robots.txt` and terms of service. The author does not encourage or participate in any unlawful use.

An MCP server that helps AI discover web data sources — not a scraper. It tells AI *where the data lives and what it looks like* before the scraper is written.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

> [中文 README](./README.md)

## Positioning

**veddata is a discovery tool, not a scraper.**
**Nor is it a general-purpose browser** — for plain web browsing other MCP tools fit better. Page access here is only the prerequisite for finding data sources.

| Does | Does NOT |
|------|----------|
| Event-driven capture of network requests + embedded data | Interactive breakpoint debugging (step / pause) |
| DOM directory tree: containers / fields / interactive markers | JS encryption / wasm reversing |
| Request params + response schema extraction | WebSocket binary frame decoding |
| Batch observation: request / JS breakpoints auto-snapshot | E2EE decryption |
| Compressed field docs for AI to write scrapers from | Anti-detection / bot-protection fighting |

Built for standard HTTP JSON API sites. Not for encrypted streams, wasm obfuscation, or reverse-engineering scenarios.

## How It Works

```
Website → Browser (Playwright event-driven capture)
       ↓                                ↓
  network requests + embedded data  DOM directory tree
  (with trigger context, no type    (containers / fields / interactive)
   labels)
       ↓                                ↓
  ved_goto returns data manifest ←────┘
       ↓
  keyword lookup (ved_search / ved_trace_value) → field paths
       ↓
  batch observation (ved_watch) → auto-snapshot on request/JS breakpoints
       ↓
  field docs (ved_export) → AI writes the scraper
```

## Quick Start

```bash
git clone https://github.com/SanZiNEO/veddata.git
cd veddata
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
```

### MCP Configuration

**Paths are configured through command-line arguments only** — `args` is the one surface every MCP
client has, while `env` passthrough differs between them. Both arguments are optional, but **you must
set `--response-dir` if you want exports/screenshots**:

| Argument | Default | Description |
|----------|---------|-------------|
| `--profile-dir <abs path>` | `<data root>/veddata/profile` | Browser profile holding login state |
| `--response-dir <abs path>` | **none** (writes fail until it is set) | Where exports / screenshots land |

Only **absolute paths** are accepted (`~` is expanded); relative paths are rejected — resolving them
against CWD would hand the destination to whatever the host happens to set as working directory.

For `mcpServers`-style configs (Claude Desktop, Cursor, …):

```json
{
  "mcpServers": {
    "veddata": {
      "command": "path\\to\\veddata\\.venv\\Scripts\\python.exe",
      "args": ["-m", "veddata.server", "--response-dir", "D:\\veddata-out"]
    }
  }
}
```

VS Code (`args` supports `${workspaceFolder}`, so artifacts can follow the project):

```json
{
  "servers": {
    "veddata": {
      "command": "path\\to\\veddata\\.venv\\Scripts\\python.exe",
      "args": ["-m", "veddata.server", "--response-dir", "${workspaceFolder}\\.veddata-out"]
    }
  }
}
```

Runtime env vars (browser behaviour only — nothing to do with paths):

| Variable | Default | Description |
|----------|---------|-------------|
| `HEADLESS` | `"false"` | Headless mode (`"true"` = no visible browser) |
| `BROWSER_PATH` | (auto) | Browser path, `"edge"` for Edge |
| `BROWSER_ADDRESS` | — | Connect to existing browser (e.g. `127.0.0.1:9222`), overrides HEADLESS/BROWSER_PATH |
| `MAX_TEXT_LENGTH` | `"3000"` | Max characters for page text |

### Paths & data

Nothing is written into your project directory, and **nothing depends on the process CWD** — the same
client gets the same locations on any agent / harness platform, from any working directory:

```
<data root>/veddata/        Windows: %LOCALAPPDATA%\veddata
├── profile/                browser profile (default, keeps login state)
└── cache/                  ved_fetch page-text cache (internal, newest 32 kept)

<--response-dir>/           exports / screenshots — you choose this in your config
```

- **One stable profile by default, login state kept across sessions**, and it never moves with the
  launch directory.
- A Chromium profile can only be used by one browser at a time: **two sessions opening a browser at
  once will collide** (the second fails to start). Give each one its own `--profile-dir` if you need
  to run them in parallel.
- **Exports are named by site + timestamp**: `<site>_<endpoint>_<YYYYMMDD-HHMMSS>.json`; screenshots
  are `[<prefix>_]<site>_<YYYYMMDD-HHMMSS>.png`. The site name is parsed from the URL —
  `www.example.com` → `example`, `api.example.co.uk` → `example`. A `-2` suffix is added only when
  the same export happens twice within the same second.
- Without `--response-dir`, **only the 3 writing tools fail** (`ved_export` / `ved_export_all` /
  `ved_screenshot`); every other tool keeps working, and the error tells you how to configure it.
- **The program never cleans up after itself** — deliverables are yours to manage.

### Output limits & how to continue

Every tool result has a **soft cap**; when it is hit the output is truncated **and always says how to fetch
the rest** (the convention shared by opencode, the official fetch server and DSH):

| Rule | Value | Notes |
|------|-------|-------|
| Soft cap per result | ~8000 chars | truncated with a footer naming the continuation parameter |
| Max chars per line | 2000 | saves you from a 1 MB single-line JS bundle |
| Default list size | 30 (`limit=`) | footer hands out `offset=N` |
| Default tree depth | 2 (`depth=`) | `ved_goto` / `ved_dom_tree` / `ved_dom_locate` |
| Inline data | summarized only | a 200 KB+ `data:` wasm/base64 payload is never returned verbatim |

**Three paging granularities — don't mix them**:

- lines — `ved_script_source(start_line=, line_count=)`, or just use `query=` to locate
- char offset — `ved_fetch(max_length=, start_index=)`
- item offset — `offset` / `limit` on `ved_apis` / `ved_dom_search` / `ved_list_scripts` / `ved_scan`

When `--response-dir` is configured, the **full** truncated payload is also spilled to
`<response-dir>/_spill/` (newest 32 kept) and the path is included in the reply; without it you just get
the paging parameters (no error). The data itself stays on the server, so you can always ask again.

**Watch (`ved_watch`) lifecycle**:

- **Register many at once**: `observations=[{...}, {...}]`; each watch gets an auto id (`w1`, `w2`, … monotonic, never reused) or your own `{"id": "login"}`
- **`max` (default 1)**: how many hits to record — the watch is **removed automatically** once reached, so a breakpoint on a hot line won't keep interrupting the page; `max: 0` means unlimited (still bounded globally: 20 per watch / 200 total)
- **List**: `ved_watch()` shows id / type / target / hits / state
- **Remove**: `ved_watch(remove="w1,w3")` or `remove="all"`
- JS watch `line` is **1-based** (same as the line numbers `ved_script_source` prints)
**Read before watching (JS watches)**: you must read a script with `ved_script_source(url=...)`
before setting a breakpoint on it — otherwise the watch is refused with a "read it first" remedy.
If the script has changed since (page reload), re-read it, or you would be setting a breakpoint on a
stale line. **Request watches do not touch code and have no such requirement.**
## Tools (29)

### Navigate (6)
| Tool | Description |
|------|-------------|
| `ved_open` | Start a data-discovery session: launch browser, begin capturing page data sources. No navigation |
| `ved_goto` | Navigate and auto-discover all data sources: returns DOM tree + data manifest + actions |
| `ved_close` | Close entire browser, clear all data |
| `ved_tabs` | List all tabs with CDP short IDs, mark the current one |
| `ved_tab_switch` | Switch to a specified tab (short ID prefix match) |
| `ved_tab_close` | Close tab(s) by short ID, prune their data records. Comma-separated for batch close |

### Observe (7)
| Tool | Description |
|------|-------------|
| `ved_fetch` | Full page text (scroll to bottom + innerText + links) to help pick keywords |
| `ved_screenshot` | Screenshot of current page (viewport or full page) |
| `ved_dom_tree` | DOM directory tree (in-memory snapshot): containers/fields/interactive markers, auto re-scanned after navigation |
| `ved_dom_search` | Search text/attrs/id in the in-memory DOM tree, returns node paths |
| `ved_dom_locate` | Locate a node by path (e.g. `div.content > div.post-list > article:nth-child(3)`) |
| `ved_cookies` | View cookies (current domain or all, summary or full info). Filter by tab |
| `ved_console` | Page console: execute JS / view log/warn/error messages |

### Act (2)
| Tool | Description |
|------|-------------|
| `ved_act` | Chain operations (input/scroll/click/select), reports new data records + trigger context per step |
| `ved_login` | Wait for manual login via cookie change detection |

### Discover (13)
| Tool | Description |
|------|-------------|
| `ved_apis` | List all captured data (network, embedded, JS globals), each with trigger context, no type labels |
| `ved_inspect` | Full request/response details, supports comma-separated IDs |
| `ved_search` | Cross-source search: network → embedded → script source → DOM, comma-separated keywords |
| `ved_context` | Search keyword returning exact field paths + sample values, comma-separated keywords |
| `ved_watch` | Batch observation: register request/JS-breakpoint watches → trigger → collect all variable snapshots at once (auto-continues, never pauses the page) |
| `ved_list_scripts` | List all loaded JS scripts (URL, size, line count) |
| `ved_search_scripts` | Search all JS sources (supports /regex/) |
| `ved_script_source` | View a script's source with search highlight and context |
| `ved_trace_value` | Trace a value through JS source / network / DOM / globals / WebSocket |
| `ved_export` | Export data: field doc + raw JSON, comma-separated IDs, `output_dir` |
| `ved_export_all` | Batch-export all captured data |
| `ved_peek` | Open → capture → match data by path → return details in one call |
| `ved_request` | Replay HTTP requests (captured or custom), auto-sync browser cookies |

### Scan (1)
| Tool | Description |
|------|-------------|
| `ved_scan` | `mode="all"` full scan (APIs + DOM tree + embedded data). `mode="dom"` keyword scan |

## Recommended Workflow

### 🚀 Fast Path (Recommended)

Pick a keyword from the data manifest and trace it directly to its source:

1. `ved_open()` → `ved_goto(url)` — launch browser → navigate, read the DOM tree + data manifest, pick keywords
2. `ved_act("scroll")` — scroll to trigger feed/recommendation APIs
3. `ved_search("kw1,kw2")` — find which data sources contain the keywords
4. `ved_context("kw1,kw2")` — see exact field paths and values, confirm targets
5. `ved_inspect(indices="1,3")` → `ved_export(indices="1,3")` — batch inspect and export

**Key insight**: skip enumeration (scan/apis), go directly from keyword to API + field paths.

### Full Scan (when you have no keyword)

1. `ved_open()` → `ved_goto(url)` — read the DOM tree and data manifest directly
2. `ved_scan(mode="all")` — capture APIs + DOM structure + embedded data in one call
3. `ved_apis()` — list all endpoints, inspect one by one with `ved_inspect(n)`

### Batch Observation (reverse-locating values)

To capture intermediate values when code hits a certain line (e.g. encryption params):

1. `ved_search_scripts("encrypt")` — locate the sensitive code line
2. `ved_watch(observations=[{"type":"js","url":"...app.js","line":147,"variables":["key"]}])` — register a JS watch
3. `ved_act(...)` — trigger; the breakpoint auto-snapshots and continues (page never pauses)
4. `ved_watch(collect=True)` — collect all snapshots at once

### Pages Where Data Lives in HTML

Few XHR requests → few `ved_apis()` results is normal. Use `ved_dom_search` + `ved_trace_value` to find embedded data (`<script>` JSON blocks, `window.__xxx__` globals).

## Architecture

```
src/veddata/
├── server.py           # FastMCP entry + 29 tools
├── state.py            # Global state + attach_page wiring (monitor / script registry)
├── browser.py          # Playwright wrapper + auto-registration of new tabs + prefix matching
├── network_monitor.py  # Event-driven capture (network/embedded/WS) + trigger context, no type labels
├── dom.py              # DOM directory tree: in-memory snapshot + collapse + search/locate
├── watch_engine.py     # Batch observation: request watches + JS breakpoints auto-snapshot
├── scripts.py          # JS script collection (scriptParsed) / search / source
├── requester.py        # httpx request executor + cookie sync
├── export.py           # Compressed field docs + raw packet save
├── login.py            # Cookie-change login detection + manual login wait
└── tools/
    ├── navigate.py     # Navigate: open goto close tabs tab_switch tab_close
    ├── observe.py      # Observe: fetch screenshot dom_tree dom_search dom_locate cookies console
    ├── act.py          # Act: act login
    ├── discover.py     # Discover: apis inspect search context watch scripts trace export peek request
    └── scan.py         # Scan: scan
```

## License

MIT © [ShanZhi](https://github.com/SanZiNEO)

---

> **Disclaimer**
> 
> veddata is a general-purpose web data source discovery tool. It does not initiate scraping requests, nor does it store or transmit any website data. Users should:
> 
> 1. Respect target websites' `robots.txt` and Terms of Service
> 2. Control request frequency to avoid causing excessive load
> 3. Only scrape publicly available data; do not bypass authentication or authorization
> 4. Assume full legal responsibility for their use of this tool
> 
> The author (ShanZhi / SanZiNEO) does not encourage or participate in any use that violates laws, regulations, or website terms. This project is intended solely for educational, research, and technical exchange purposes.
