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
| `USER_DATA_DIR` | (temp) | Persistent profile for login state |
| `LOGIN_TIMEOUT` | `"300"` | Max login wait in seconds |

## Tools

| Tool | Description |
|------|-------------|
| `scout_open` | Open URL → extract full text → start network monitor |
| `scout_action` | Perform action (search, scroll) |
| `scout_wait_login` | Wait for manual login in browser |
| `scout_list_apis` | List captured API endpoints |
| `scout_inspect_api` | Show full request/response for an API |
| `scout_list_elements` | List page elements for AI to choose from |
| `scout_click` | Click an element by index |
| `scout_export` | Export raw data packet + compressed field docs |

## Example

```
AI: scout_open("https://xiaohongshu.com/explore")
→ "Page text: 减脂餐 健身计划 OOTD …"

AI: scout_action("search", "减脂餐")
→ "2 new APIs captured"

AI: scout_list_apis()
→ [1] POST /api/search/notes  → 20 fields

AI: scout_inspect_api(1)
→ POST https://edith.xiaohongshu.com/api/search/notes
   Body: {"keyword": "减脂餐", "page": 1, ...}
   Response: code=0, data.items[]: count=20, id=..., title=...

AI: scout_export(1)
→ field docs + saved: response/search_notes.json
```

## Architecture

```
src/web_scout/
├── server.py      # FastMCP entry + 8 tools
├── browser.py     # Chromium wrapper + text extraction + login detection
├── monitor.py     # Network listener + API filter + storage
├── dom.py         # Element scanner + container merging
└── export.py      # Compressed field docs + raw packet save
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
