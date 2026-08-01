# Web Scout

> **Disclaimer**: This project is for educational, research, and technical exchange purposes only. Users are responsible for complying with target websites' `robots.txt` and terms of service. The author does not encourage or participate in any unlawful use.

An MCP server that helps AI discover web data sources — not a scraper. It tells AI *where the data lives and what it looks like* before the scraper is written.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

> [中文 README](./README.md)

## Positioning

**Web Scout is a discovery tool, not a scraper.**
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
  scout_goto returns data manifest ←────┘
       ↓
  keyword lookup (scout_search / scout_trace_value) → field paths
       ↓
  batch observation (scout_watch) → auto-snapshot on request/JS breakpoints
       ↓
  field docs (scout_export) → AI writes the scraper
```

## Quick Start

```bash
git clone https://github.com/SanZiNEO/web-scout.git
cd web-scout
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
```

### MCP Configuration

Add to `kilo.json`:

```json
"web-scout": {
    "type": "local",
    "command": ["path\\to\\web-scout\\.venv\\Scripts\\web-scout.exe"],
    "enabled": true
}
```

Optional env vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `HEADLESS` | `"false"` | Headless mode (`"true"` = no visible browser) |
| `BROWSER_PATH` | (auto) | Browser path, `"edge"` for Edge |
| `BROWSER_ADDRESS` | — | Connect to existing browser (e.g. `127.0.0.1:9222`), overrides HEADLESS/BROWSER_PATH |
| `USER_DATA_DIR` | `".web-scout-data"` | Persistent profile for login state |
| `MAX_TEXT_LENGTH` | `"3000"` | Max characters for page text |
| `RESPONSE_DIR` | `"./response"` | Default export directory, overridable by `output_dir` param |

## Tools (29)

### Navigate (6)
| Tool | Description |
|------|-------------|
| `scout_open` | Start a data-discovery session: launch browser, begin capturing page data sources. No navigation |
| `scout_goto` | Navigate and auto-discover all data sources: returns DOM tree + data manifest + actions |
| `scout_close` | Close entire browser, clear all data |
| `scout_tabs` | List all tabs with CDP short IDs, mark the current one |
| `scout_tab_switch` | Switch to a specified tab (short ID prefix match) |
| `scout_tab_close` | Close tab(s) by short ID, prune their data records. Comma-separated for batch close |

### Observe (7)
| Tool | Description |
|------|-------------|
| `scout_fetch` | Full page text (scroll to bottom + innerText + links) to help pick keywords |
| `scout_screenshot` | Screenshot of current page (viewport or full page) |
| `scout_dom_tree` | DOM directory tree (in-memory snapshot): containers/fields/interactive markers, auto re-scanned after navigation |
| `scout_dom_search` | Search text/attrs/id in the in-memory DOM tree, returns node paths |
| `scout_dom_locate` | Locate a node by path (e.g. `div.content > div.post-list > article:nth-child(3)`) |
| `scout_cookies` | View cookies (current domain or all, summary or full info). Filter by tab |
| `scout_console` | Page console: execute JS / view log/warn/error messages |

### Act (2)
| Tool | Description |
|------|-------------|
| `scout_act` | Chain operations (input/scroll/click/select), reports new data records + trigger context per step |
| `scout_login` | Wait for manual login via cookie change detection |

### Discover (13)
| Tool | Description |
|------|-------------|
| `scout_apis` | List all captured data (network, embedded, JS globals), each with trigger context, no type labels |
| `scout_inspect` | Full request/response details, supports comma-separated IDs |
| `scout_search` | Cross-source search: network → embedded → script source → DOM, comma-separated keywords |
| `scout_context` | Search keyword returning exact field paths + sample values, comma-separated keywords |
| `scout_watch` | Batch observation: register request/JS-breakpoint watches → trigger → collect all variable snapshots at once (auto-continues, never pauses the page) |
| `scout_list_scripts` | List all loaded JS scripts (URL, size, line count) |
| `scout_search_scripts` | Search all JS sources (supports /regex/) |
| `scout_script_source` | View a script's source with search highlight and context |
| `scout_trace_value` | Trace a value through JS source / network / DOM / globals / WebSocket |
| `scout_export` | Export data: field doc + raw JSON, comma-separated IDs, `output_dir` |
| `scout_export_all` | Batch-export all captured data |
| `scout_peek` | Open → capture → match data by path → return details in one call |
| `scout_request` | Replay HTTP requests (captured or custom), auto-sync browser cookies |

### Scan (1)
| Tool | Description |
|------|-------------|
| `scout_scan` | `mode="all"` full scan (APIs + DOM tree + embedded data). `mode="dom"` keyword scan |

## Recommended Workflow

### 🚀 Fast Path (Recommended)

Pick a keyword from the data manifest and trace it directly to its source:

1. `scout_open()` → `scout_goto(url)` — launch browser → navigate, read the DOM tree + data manifest, pick keywords
2. `scout_act("scroll")` — scroll to trigger feed/recommendation APIs
3. `scout_search("kw1,kw2")` — find which data sources contain the keywords
4. `scout_context("kw1,kw2")` — see exact field paths and values, confirm targets
5. `scout_inspect(indices="1,3")` → `scout_export(indices="1,3")` — batch inspect and export

**Key insight**: skip enumeration (scan/apis), go directly from keyword to API + field paths.

### Full Scan (when you have no keyword)

1. `scout_open()` → `scout_goto(url)` — read the DOM tree and data manifest directly
2. `scout_scan(mode="all")` — capture APIs + DOM structure + embedded data in one call
3. `scout_apis()` — list all endpoints, inspect one by one with `scout_inspect(n)`

### Batch Observation (reverse-locating values)

To capture intermediate values when code hits a certain line (e.g. encryption params):

1. `scout_search_scripts("encrypt")` — locate the sensitive code line
2. `scout_watch(observations=[{"type":"js","url":"...app.js","line":147,"variables":["key"]}])` — register a JS watch
3. `scout_act(...)` — trigger; the breakpoint auto-snapshots and continues (page never pauses)
4. `scout_watch(collect=True)` — collect all snapshots at once

### Pages Where Data Lives in HTML

Few XHR requests → few `scout_apis()` results is normal. Use `scout_dom_search` + `scout_trace_value` to find embedded data (`<script>` JSON blocks, `window.__xxx__` globals).

## Architecture

```
src/web_scout/
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
> Web Scout is a general-purpose web data source discovery tool. It does not initiate scraping requests, nor does it store or transmit any website data. Users should:
> 
> 1. Respect target websites' `robots.txt` and Terms of Service
> 2. Control request frequency to avoid causing excessive load
> 3. Only scrape publicly available data; do not bypass authentication or authorization
> 4. Assume full legal responsibility for their use of this tool
> 
> The author (ShanZhi / SanZiNEO) does not encourage or participate in any use that violates laws, regulations, or website terms. This project is intended solely for educational, research, and technical exchange purposes.
