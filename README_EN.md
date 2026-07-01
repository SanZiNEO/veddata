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
| `scout_inspect` | Show full request/response for an API (preview or full mode) |
| `scout_search` | Global search: API bodies → SSR JSON → page source → DOM text |
| `scout_context` | Search keyword and return exact field paths + sample values |
| `scout_export` | Export single API: compressed field doc + raw JSON |
| `scout_export_all` | Batch-export all captured APIs at once |
| `scout_peek` | Open → listen → match API by path → return details in one call |

### Scan (1)
| Tool | Description |
|------|-------------|
| `scout_scan` | `mode="all"` full scan (API + SSR + DOM). `mode="dom"` keyword scan |

## Recommended Workflow

### 🚀 Fast Path (Recommended)

```bash
# 1. Open page, pick a visible keyword from text
scout_open("https://www.bilibili.com")
→ page text: 原神 男人领域 鬼畜 …

# 2. Scroll to trigger more APIs (recommendation/feed)
scout_act("scroll")
→ +11 APIs, hits feed/rcmd endpoint

# 3. Search by keyword to find which API contains it
scout_search("男人领域")
→ [51] GET feed/rcmd  ← hit!

# 4. See exact field path and value
scout_context("男人领域")
→ data.item[0].title = "男人领域"

# 5. Confirm target, inspect params, export
scout_inspect(51)
scout_export(51)
```

**Key insight**: skip enumeration (scan/apis), go directly from keyword → search → context to pinpoint the exact API and field. Much faster than "full scan → inspect one by one".

### Full Scan (when you do not have a keyword)

```bash
scout_open(url)
scout_act("search", kw)      # trigger search APIs
scout_scan(mode="all")       # full scan
scout_apis()                 # list all endpoints
scout_inspect(n)             # inspect one by one
scout_export(n)
```

### SSR Pages (dxy.com, etc.)

Data is in HTML/DOM, not XHR. Use `scout_search` + `scout_scan(mode="dom")` instead.
`scout_apis()` returning 0 is expected behavior.

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
