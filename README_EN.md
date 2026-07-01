# Web Scout

> **Disclaimer**: This project is for educational and research purposes only. Users are responsible for complying with target websites' robots.txt and terms of service. The author does not encourage or participate in any unlawful use.

MCP server for **web data source discovery** — not a scraper. Finds where data lives and what it looks like so AI can write the scraper.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

> [中文 README](./README.md)

## Positioning

**Web Scout is a discovery tool, not a scraper.**

| Does | Does NOT |
|------|----------|
| Network sniffing → JSON API endpoints | XHR breakpoint call-chain tracing |
| DOM scanning → repeating structures + CSS selectors | JS encryption / wasm reversing |
| Request params + response schema extraction | WebSocket binary frame decoding |
| Full-page text → Markdown for AI to read | E2EE decryption |
| Compressed field docs for AI to write scrapers from | Auto-generating runnable crawler code |

For standard HTTP JSON API sites. Not for encrypted streams, wasm obfuscation, or reverse-engineering scenarios.

## How It Works

```
Website → Browser → Full-page text (Markdown)
       ↓           ↓
   Network listen  AI reads text → picks keywords
       ↓           ↓
   API capture     Search → match APIs containing keywords
       ↓               ↓
   Field docs ←────────┘
   Raw data packets saved to disk
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
| `MULTI_BROWSER` | `"false"` | `"true"` tries multiple debug ports (9222-9231) to avoid conflicts |
| `USER_DATA_DIR` | (temp) | Persistent profile for login state |
| `LOGIN_TIMEOUT` | `"300"` | Max login wait in seconds |
| `MAX_TEXT_LENGTH` | `"3000"` | Max characters for scout_open page text |
| `RESPONSE_DIR` | `"./response"` | Export output directory |

## Tools (19)

### Navigate (5)
| Tool | Description |
|------|-------------|
| `scout_open` | Open URL → extract rendered text → start network monitor |
| `scout_close` | Close entire browser, clear all data |
| `scout_tabs` | List all tabs, mark current active |
| `scout_tab_switch` | Switch to a specified tab |
| `scout_tab_close` | Close a tab, clean up its monitor data |

### Observe (3)
| Tool | Description |
|------|-------------|
| `scout_fetch` | Get full page text + all links (supports chunked reading) |
| `scout_screenshot` | Screenshot of current page (viewport or full page) |
| `scout_elements` | List clickable elements and DOM containers |

### Act (3)
| Tool | Description |
|------|-------------|
| `scout_act` | Execute search or scroll to trigger new API requests |
| `scout_click` | Click an element (pagination / tab switch / load more) |
| `scout_login` | Wait for manual login in browser window |

### Discover (7)
| Tool | Description |
|------|-------------|
| `scout_apis` | List captured API endpoints, with optional keyword filter |
| `scout_inspect` | Show request/response for APIs, supports comma-separated IDs |
| `scout_search` | Global search: API bodies → SSR JSON → page source → DOM, supports comma-separated keywords |
| `scout_context` | Search keyword returning field paths + values, supports comma-separated keywords |
| `scout_export` | Export APIs: field doc + raw JSON, supports comma-separated IDs |
| `scout_export_all` | Batch-export all captured APIs at once |
| `scout_peek` | Open → listen → match API by path → return details in one call |

### Scan (1)
| Tool | Description |
|------|-------------|
| `scout_scan` | `mode="all"` full scan (API + SSR + DOM). `mode="dom"` keyword scan |

## Recommended Workflow

### 🚀 Fast Path (Recommended)

Pick a visible keyword from page text and trace it directly to the API:

1. `scout_open(url)` — open page, read rendered text, pick keywords (can be multiple)
2. `scout_act("scroll")` — scroll to trigger feed/recommendation APIs
3. `scout_search("kw1,kw2")` — find which APIs contain the keywords
4. `scout_context("kw1,kw2")` — see exact field paths and values, confirm targets
5. `scout_inspect(indices="1,3")` → `scout_export(indices="1,3")` — batch inspect and export

**Key insight**: skip enumeration (scan/apis), go directly from keyword to API+field. Four steps to pinpoint the target API.

### Full Scan (when you do not have a keyword)

When you have no direction and need to survey available data sources:

1. `scout_open(url)` → `scout_act("search", kw)` — trigger search APIs
2. `scout_scan(mode="all")` — capture APIs + DOM containers + SSR data in one call
3. `scout_apis()` — list all endpoints, inspect one by one with `scout_inspect(n)`

### SSR Pages

Data lives in HTML/DOM, not XHR. `scout_apis()` returning 0 is expected. Use `scout_search` + `scout_scan(mode="dom")` instead.

## Architecture

```
src/web_scout/
├── server.py           # FastMCP entry + 19 tools
├── state.py            # Global state + multi-tab isolation
├── browser.py          # Chromium wrapper + text extraction + multi-tab management
├── monitor.py          # Network listener + JSON API filter + SSR extraction + query
├── dom.py              # Element scanner + container discovery + field extraction
├── export.py           # Compressed field docs + raw packet save
├── login.py            # Login detection + manual login wait + CAPTCHA handling
└── tools/
    ├── navigate.py     # Navigate: open close tabs tab_switch tab_close
    ├── observe.py      # Observe: fetch screenshot elements
    ├── act.py          # Act: act click login
    ├── discover.py     # Discover: apis inspect search context export export_all peek
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
