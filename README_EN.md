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
| `AUTO_CLOSE` | `"true"` | Auto-close browser after export (`"false"` keeps it open) |
| `RESPONSE_DIR` | `"./response"` | Export output directory |

## Tools

18 tools total, grouped by workflow phase:

### Explore
| Tool | Description |
|------|-------------|
| `scout_open` | Open URL → extract rendered text → start network monitor |
| `scout_fetch` | Get full page text + all links (supports chunked reading) |
| `scout_action` | Execute search or scroll to trigger new API requests |
| `scout_wait_login` | Wait for manual login in browser window |

### Analyze
| Tool | Description |
|------|-------------|
| `scout_analyze` | **Core analysis tool**: capture network APIs + SSR JSON + DOM containers in one call |
| `scout_list_apis` | List captured API endpoints, with optional keyword filter |
| `scout_search` | Global search: API bodies → SSR JSON → page source → DOM text |
| `scout_context` | Search keyword and return exact field paths + sample values |

### Inspect & Export
| Tool | Description |
|------|-------------|
| `scout_inspect_api` | Show full request/response for an API (preview or full mode) |
| `scout_export` | Export single API: compressed field doc + raw JSON |
| `scout_export_all` | Batch-export all captured APIs at once |

### Interaction
| Tool | Description |
|------|-------------|
| `scout_list_elements` | List clickable elements and DOM containers |
| `scout_click` | Click an element (pagination / tab switch / load more) |
| `scout_screenshot` | Screenshot of current page (viewport or full page) |
| `scout_list_tabs` | List all open browser tabs |
| `scout_close` | Close a specific tab or current tab |

### One-shot Verification
| Tool | Description |
|------|-------------|
| `scout_fetch_api` | Open → listen → match API by path → return details in one call |
| `scout_inspect_dom` | Open → scan DOM containers by keyword → return in one call |

## Recommended Workflow

### Scenario 1: Discovering Page Data Sources

```
AI: scout_open("https://xiaohongshu.com/explore")
→ "Page text: 减脂餐 健身计划 OOTD …"

AI: scout_action("search", "减脂餐")
→ "2 new APIs captured"

AI: scout_analyze()
→ 3 network APIs + 1 SSR source + 2 DOM containers

AI: scout_list_apis()
→ [1] POST /api/search/notes  → 20 fields
→ [2] [SSR] window.__INITIAL_STATE__ → 156 fields

AI: scout_inspect_api(1)
→ POST https://edith.xiaohongshu.com/api/search/notes
   Body: {"keyword": "减脂餐", "page": 1, ...}
   Response: code=0, data.items[]: count=20, id=..., title=...

AI: scout_export(1)
→ field docs + saved: response/search_notes.json
```

### Scenario 2: Pagination / Infinite Scroll Discovery

```
AI: scout_action("scroll")
→ 3 new, 1 recurring, 5 total APIs

AI: scout_list_apis()
→ [3] GET /api/feed/rcmd ×2 — paginated

AI: scout_list_elements()
→ [1] a "下一页"  [2] [role=tab] "最新"

AI: scout_click(1)
→ triggered 1 new API: GET /api/search?page=2
```

## Architecture

```
src/web_scout/
├── server.py      # FastMCP entry + 18 tools
├── browser.py     # Chromium wrapper + text extraction + multi-tab management
├── monitor.py     # Network listener + JSON API filter + SSR extraction + query
├── dom.py         # Element scanner + container discovery + field extraction
├── export.py      # Compressed field docs + raw packet save
└── login.py       # Login detection + manual login wait + CAPTCHA handling
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
