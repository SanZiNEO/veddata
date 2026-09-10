# veddata

A Model Context Protocol (MCP) server for data-source discovery on web pages — capturing network traffic, extracting embedded data, analysing scripts, and tracking data flow through interaction and watch points.

[中文](README.md)

## Features

- **Network data sources** — every request and response, grouped by endpoint with field structure
- **Embedded data** — JSON inside `<script>` tags and `window` globals
- **Script analysis** — list and search loaded scripts, read sources, trace where a value appears
- **Interaction** — click, input, select, scroll, targeted by visible text or `css=` and `//` (XPath) selectors
- **Watch points** — request watches (record on pattern match) and JS breakpoint watches (scope-variable snapshots on hit)
- **Document structure** — DOM tree snapshot, keyword lookup, path lookup, all server-side
- **Tool chains** — run several tools in one call (with waits and repeats) and get a causality diff for each action
- **Page facts** — address, title, body length, keyword hits with original context, visible and hidden widgets
- **Downloads** — filename, save path, state and size reported in the tool message
- **Server-side retention** — results stay on the server; responses carry compact summaries

## Requirements

- Python 3.10 or newer
- Chrome or Edge (launched headed by default, with a persistent profile that keeps login state)

## Install and use

Run it without installing anything (recommended):

```json
{
  "mcpServers": {
    "veddata": {
      "command": "uvx",
      "args": ["veddata", "--response-dir", "/path/to/out"]
    }
  }
}
```

Or install it once with `uv tool install veddata` (or `pip install veddata`), then

```json
{
  "mcpServers": {
    "veddata": {
      "command": "veddata",
      "args": ["--response-dir", "/path/to/out"]
    }
  }
}
```

Run from source (for development):

```bash
uv venv
uv pip install -e ".[dev]"
```

Client configuration (standard input/output):

```json
{
  "mcpServers": {
    "veddata": {
      "command": "/path/to/veddata/.venv/bin/python",
      "args": ["-m", "veddata.server",
               "--profile-dir", "/path/to/profile",
               "--response-dir", "/path/to/out"]
    }
  }
}
```

## Configuration

| Option | Description |
|--------|-------------|
| `--profile-dir <dir>` | Browser profile directory (persistent, keeps login state). Defaults to `<user-data-root>/veddata/profile` |
| `--response-dir <dir>` | Output directory for `ved_export` and `ved_screenshot`. Without it, those tools report an error when writing |

| Environment variable | Description |
|----------------------|-------------|
| `HEADLESS=true` | Run without a window (headed by default) |
| `BROWSER_PATH <path>` | Browser executable to use (`edge` selects Edge) |
| `BROWSER_ADDRESS <url>` | Attach to a running browser over the debugging protocol instead of launching one |

## Tools

### Session and tabs

- **ved_open** — start a session (launch a plain Chrome and attach over the debugging protocol)
- **ved_status** — current page facts, tab list, captured record count, observation state
- **ved_tabs**, **ved_tab_switch**, **ved_tab_close** — list, switch, close tabs
- **ved_close** — close the browser and clear captured data

### Navigation and reading

- **ved_goto** — navigate; returns document structure, data-source preview and page facts
- **ved_fetch** — read the current page text (paged)
- **ved_dom_tree**, **ved_dom_search**, **ved_dom_locate** — tree snapshot, keyword, path
- **ved_console** — run JS or read console messages
- **ved_cookies**, **ved_screenshot** — cookies and screenshot to disk

### Interaction

- **ved_act** — `input`, `click`, `select`, `scroll`; single step or chained; `target` accepts visible text, `css=` or `//`

### Data sources

- **ved_apis**, **ved_inspect** — capture list and single record detail (request headers, response body, field structure)
- **ved_export**, **ved_export_all** — write captures to disk (raw or compact)
- **ved_peek** — open a URL and return its data sources
- **ved_request** — replay a captured endpoint or send a custom request (cookies synced)
- **ved_search**, **ved_context**, **ved_trace_value** — search and trace across network, embedded data, scripts and globals

### Scripts

- **ved_list_scripts**, **ved_search_scripts**, **ved_script_source** — list, search, source

### Watch points

- **ved_watch** — register, list, collect, remove; request and JS kinds; snapshots stay server-side

### Scanning

- **ved_scan** — one-shot summary of network, document structure and embedded data

### Tool chains

- **ved_chain** — run tools in order; waits support milliseconds, network match, network idle and element visibility; repeats are one level deep

## Behaviour

- **Facts only** — output states what is there, with no verdicts and no next-step advice; page state is reported as address, title, body length, keyword-hit fragments, visible widgets.
- **Server-side retention** — responses carry compact summaries with paging footers; details are fetched on demand via `ved_apis`, `ved_inspect`, `ved_watch(collect)`.
- **Observation** — after a change outside tool calls (self-navigation, tabs added or closed), state-dependent tools return a factual note instead of executing; `ved_status` and `ved_tabs` re-establish observation.
- **Human in the loop** — the window is visible; sign-in or verification is completed by the user in the window, and tools report the page facts.
- **Browser lifecycle** — a browser we launched is closed by `ved_close`; a browser attached through `BROWSER_ADDRESS` is only disconnected.

## Example: finding a download URL on a site with no API documentation

Taking svgrepo as an example (the site publishes no interface documentation, so the agent has to scout it). One tool chain does the whole job:

```json
[
  {"tool": "ved_open"},
  {"tool": "ved_goto", "args": {"url": "https://www.svgrepo.com/vectors/arrow/"}},
  {"tool": "ved_goto", "args": {"url": "https://www.svgrepo.com/svg/535197/arrow-u-up-left"}},
  {"tool": "ved_act",  "args": {"action": "click", "target": "css=a[href*='/download/']"}}
]
```

The tool message then states the facts — the action, its causality, and where the file landed:

```
[click] Clicked 'css=a[href*='/download/']' → +1 new APIs
    GET    https://www.svgrepo.com/_next/data/XJiZPe18H5paekHV…/tools.json
download: arrow-u-up-left-svgrepo-com.svg → E:\Downloads\arrow-u-up-left-svgrepo-com.svg (completed, 399 B)
```

## Development

```bash
pytest tests -q
python scripts/smoke.py
```

## License

MIT License — see [LICENSE](LICENSE).

## Disclaimer

This project is provided for learning, research, technical exchange and lawful, compliant automation testing only. **It must not be used for any unlawful, infringing or abusive purpose.** Please read this disclaimer in full before use; **by downloading, installing, running or otherwise using this project you acknowledge that you have read, understood and agreed to all of the terms below.** If you do not agree, stop using it and delete it.

1. **Compliance is the user's responsibility.** You are responsible for complying with the terms of service, `robots.txt` and usage rules of any target website; the laws and regulations of your jurisdiction (including but not limited to network security, data protection, privacy, copyright, unfair competition and computer misuse legislation); and any applicable industry rules or contractual obligations.
2. **Prohibited uses.** You must not use this project to gain unauthorised access to, interfere with or damage systems or data; to circumvent technical protection measures or access controls; to scrape, hoard or resell third-party data at scale; to infringe intellectual property, trade secrets or personal privacy; or to engage in fraud, harassment, spam or any other malicious activity.
3. **Assumption of risk.** Using this project may result in account suspension, blocked access, service interruption, data loss or other harm. Such risks and consequences are borne solely by the user.
4. **No warranty.** The project is provided "AS IS", without any express or implied warranty of merchantability, fitness for a particular purpose, accuracy, security or non-infringement. No promise is made that any feature will work, remain available, or avoid detection by any target site.
5. **Limitation of liability.** To the maximum extent permitted by applicable law, the authors and contributors shall not be liable for any direct, indirect, incidental, special, punitive or consequential damages (including but not limited to lost profits, lost data, business interruption, third-party claims, administrative penalties or legal liability) arising from the use of, or inability to use, this project.
6. **No legal advice.** This project does not constitute legal advice or a guarantee of compliance; consult a qualified lawyer for compliance decisions.
7. **Responsibility towards third parties.** Any claim, dispute, complaint or demand raised by a third party in connection with your use of this project is your sole responsibility; the authors and contributors accept no liability for it.
8. **Rights reserved.** The authors reserve the right to modify, suspend or discontinue this project at any time and without notice; this disclaimer may be updated at any time and takes effect on publication.
