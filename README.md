# IMAX Sentinel

A personal watcher bot for BFI IMAX screenings. Monitors listing pages, detects when watched films appear or tickets open, and sends Telegram alerts so you can book before they sell out.

Built specifically to watch for Christopher Nolan films and other IMAX releases at the BFI IMAX, London.

---

## Table of Contents

- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Project structure](#project-structure)
- [Architecture](#architecture)
  - [Overview](#overview)
  - [Layer 1 — Fetcher](#layer-1--fetcher)
  - [Layer 2 — Parser](#layer-2--parser)
  - [Layer 3 — State store](#layer-3--state-store)
  - [Layer 4 — Notifier](#layer-4--notifier)
  - [Orchestrator](#orchestrator)
- [Anti-bot detection](#anti-bot-detection)
  - [Why Camoufox](#why-camoufox)
  - [Human behaviour simulation](#human-behaviour-simulation)
  - [Challenge detection](#challenge-detection)
- [Configuration](#configuration)
- [Telegram setup](#telegram-setup)
- [How change detection works](#how-change-detection-works)
- [Data model](#data-model)
- [Roadmap](#roadmap)
- [Rate limiting and etiquette](#rate-limiting-and-etiquette)

---

## What it does

On every run IMAX Sentinel:

1. Fetches the BFI IMAX new releases page and the Christopher Nolan films page
2. Extracts every film card (title + permalink URL)
3. Filters against your watchlist
4. Visits each matched film's individual booking page
5. Parses every showtime: title, datetime, venue, booking status
6. Compares against what it saw last time (SQLite)
7. Fires a Telegram alert if anything is new or a status has changed

You get notified when:

- A watched film appears on the listings for the first time
- A performance flips from `unavailable` → `available` (tickets just opened)
- A performance flips from `soldout` → `available` (returned tickets)
- A performance sells out before you could act (awareness alert)

---

## Quick start

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
# Clone and install
git clone https://github.com/yourname/imax-sentinel.git
cd imax-sentinel
uv sync

# Download the Camoufox browser binary (one-time, ~100MB)
uv run python -m camoufox fetch

# Copy and edit config
cp config.example.toml config.toml

# Create .env with your Telegram credentials
echo "TELEGRAM_BOT_TOKEN=your_token" >> .env
echo "TELEGRAM_CHAT_ID=your_chat_id" >> .env

# Run
uv run python -m imax_sentinel.main
```

To dry run without Telegram (no `.env` needed):

```bash
uv run python -m imax_sentinel.main
# Fetches, parses, writes to SQLite — no messages sent
```

---

## Project structure

```
imax-sentinel/
├── imax_sentinel/
│   ├── __init__.py
│   ├── main.py            # Orchestrator — wires all layers together
│   ├── browser_fetch.py   # Camoufox browser session + HTML fetcher
│   ├── fetch.py           # Thin wrapper + HTML snapshot helper
│   ├── parse.py           # HTML parser — listing pages + film pages
│   ├── store.py           # SQLite state store + change detection
│   ├── notify.py          # Telegram notification dispatcher
│   ├── config.py          # TOML config loader
│   └── logging_config.py  # Root logger setup
├── data/
│   ├── raw/               # HTML snapshots of successfully parsed pages
│   ├── challenges/        # HTML snapshots of Cloudflare challenge pages
│   └── sentinel.db        # SQLite database (gitignored)
├── config.toml            # Local config (gitignored)
├── config.example.toml    # Template — commit this, not config.toml
├── .env                   # Telegram secrets (gitignored)
├── pyproject.toml
└── uv.lock
```

---

## Architecture

### Overview

The system is a classic pipeline with four independent layers. Each layer has a single responsibility and communicates with the next via plain Python objects — no shared state, no global variables.

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                              │
│                      (orchestrator)                         │
└──────┬──────────────┬──────────────┬──────────────┬─────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
  browser_fetch    parse.py       store.py      notify.py
   + fetch.py
  (Layer 1)       (Layer 2)      (Layer 3)     (Layer 4)
  Fetches HTML    Parses HTML    SQLite state   Telegram
                  → structs      + change       alerts
                                 detection
```

No layer imports from any other layer except through `main.py`. `parse.py` knows nothing about the database. `store.py` knows nothing about Telegram. This means each layer can be tested, replaced, or extended independently.

---

### Layer 1 — Fetcher

**Files:** `browser_fetch.py`, `fetch.py`

The fetcher is responsible for one thing: given a list of URLs, return a list of HTML strings.

The BFI IMAX website sits behind Cloudflare, which means a simple `requests.get()` call gets blocked. A full browser session is required. The fetcher uses **Camoufox** — a patched Firefox fork that spoofs the signals Cloudflare uses to detect headless browsers.

`fetch.py` is a thin wrapper around `browser_fetch.py`. Its purpose is indirection — `main.py` imports from `fetch`, not from `browser_fetch` directly. This means the underlying engine (Camoufox, Playwright, requests) can be swapped without touching the orchestrator.

`browser_fetch.py` manages the full browser session lifecycle:

- Opens a single persistent Camoufox context for all URLs in a batch (faster and more realistic than opening a new browser per URL)
- Optionally runs a warm-up visit to the BFI homepage first (establishes cookies and TLS state)
- Navigates each URL and captures the rendered HTML after the page has settled
- Applies human behaviour simulation between actions
- Returns a consistent result dict for every URL regardless of success or failure

Every result dict has the same shape:

```python
{
    "url": str,           # original requested URL
    "final_url": str,     # URL after any redirects
    "title": str,         # page <title>
    "html": str,          # full rendered HTML
    "fetch_method": str,  # "camoufox"
    "success": bool,
    "challenge_page": bool,
    "error": str,         # only present on failure
}
```

`save_html_snapshot()` in `fetch.py` writes HTML to disk for debugging. Successful pages go to `data/raw/`, challenge pages go to `data/challenges/`. The filename is derived from the URL with special characters replaced by underscores.

---

### Layer 2 — Parser

**File:** `parse.py`

The parser converts raw HTML strings into structured Python objects. It has no I/O — it takes a string and returns a list. This makes it trivially testable with saved HTML fixtures.

Parsing is two-stage, mirroring the BFI site's own structure.

**Stage 1 — `parse_listing_page()` → `list[FilmStub]`**

A listing page (new releases or Nolan permalink) contains highlight cards. Each card has a title, an optional "From [date]" label, and a link to the film's own page. The parser extracts these into `FilmStub` objects — lightweight breadcrumbs that say "this film exists, here's where to find it."

```python
@dataclass
class FilmStub:
    title: str       # "The Odyssey"
    permalink: str   # "https://whatson.bfi.org.uk/.../odyssey-the-film-imax-70mm-2026"
    date_hint: str   # "From 17 July" (empty string on Nolan page)
```

**Stage 2 — `parse_film_page()` → `list[Performance]`**

A film page contains a booking widget (AudienceView) with one row per showtime. Each row has a title, datetime, venue, and a status indicator. The parser extracts these into `Performance` objects.

```python
@dataclass
class Performance:
    title: str
    article_id: str       # AudienceView UUID for the film
    context_id: str       # AudienceView UUID for this specific screening
    datetime_str: str     # "Saturday 21 March 2026 21:00"
    datetime_parsed: datetime | None
    venue: str
    status: str           # "available" | "soldout" | "unavailable"
    booking_url: str
```

Status is determined by the CSS class on the booking div, not by text content:

- `last-column limited` or `last-column good` + Buy button → `"available"`
- `last-column soldout` + unavailable message → `"soldout"`
- No actionable element → `"unavailable"` (coming soon / not yet on sale)

The `context_id` is the most important field. It's an AudienceView UUID that uniquely identifies a specific screening — stable across runs, unaffected by time adjustments. It's the primary key for the entire state store.

---

### Layer 3 — State store

**File:** `store.py`

The state store gives the bot memory between runs. It uses SQLite — zero infrastructure, single file, no server required.

Two tables:

**`performances`** — current state of every screening ever seen. One row per `context_id`. Updated on every run with the latest status, booking URL, and timestamps.

**`status_history`** — append-only audit log of every status transition. Never updated, only inserted into. Lets you reconstruct the full lifecycle of any screening.

The core function is `upsert_performance()`. It either inserts a new row or updates an existing one, and returns a change dict that tells the orchestrator exactly what happened:

```python
{
    "is_new": bool,         # True if context_id never seen before
    "status_changed": bool, # True if status differs from last run
    "old_status": str,      # previous status ("" if new)
    "new_status": str,      # current status
}
```

This dict is what drives notification logic in `main.py` — no additional DB queries needed.

The `_connect()` context manager handles commit/rollback/close automatically. `PRAGMA journal_mode=WAL` is set on every connection so reads and writes don't block each other.

---

### Layer 4 — Notifier

**File:** `notify.py`

The notifier sends Telegram messages. It has three public functions:

- `notify_new_listing()` — a watched film has appeared for the first time
- `notify_status_change()` — a tracked performance has changed status
- `notify_health_check()` — daily heartbeat (V2, not yet scheduled)

Credentials (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) are read from environment variables on every call. If either is missing the function returns silently — the rest of the run continues normally. This means the bot dry-runs without any Telegram configuration.

Not all status transitions trigger a notification. Only meaningful ones do:

| Transition | Alert |
|---|---|
| `unavailable → available` | 🎟 Tickets now OPEN |
| `soldout → available` | 🎟 Tickets now OPEN (returned) |
| `unavailable → soldout` | ❌ Just sold out |
| `available → soldout` | Silent (too noisy) |

Messages use Telegram's MarkdownV2 format. All dynamic content is passed through `_escape()` which prefixes special characters with a backslash — required by MarkdownV2 or Telegram rejects the message with a 400.

---

### Orchestrator

**File:** `main.py`

`main.py` is the only file that knows all four layers exist simultaneously. It sequences the full run in seven steps:

1. Load config + set up logging + init DB
2. Fetch listing pages → raw HTML
3. Parse listing HTML → `FilmStub` list
4. Filter stubs against watchlist, deduplicate by permalink
5. Fetch each matched film's permalink → raw HTML
6. Parse film HTML → `Performance` list
7. Upsert each performance → if new or changed, notify

The warm-up URL is passed only to the first `fetch_pages()` call. The second call (film pages) passes `warmup_url=None` — the session is already established.

Deduplication happens before the second fetch. The same film can appear on both listing pages (e.g. The Odyssey on new-releases and Nolan page). Without dedup you'd fetch and process it twice, generating duplicate DB writes and duplicate notifications.

---

## Anti-bot detection

### Why Camoufox

The BFI IMAX booking system sits behind Cloudflare. Standard Playwright Chromium gets blocked because it leaks several signals at the network layer that Cloudflare fingerprints before serving any HTML — specifically the JA3/JA4 TLS fingerprint and the HTTP/2 AKAMAI fingerprint. These cannot be fixed with JavaScript patches because they happen before the page loads.

Camoufox is a patched Firefox fork that addresses this at the binary level. It spoofs:

- TLS fingerprint (JA3/JA4) — looks like a real Firefox installation
- WebGL vendor and renderer strings
- Font enumeration
- `navigator.webdriver` flag
- Headless mode indicators

Firefox also has a naturally different TLS fingerprint from Chrome, which helps since most bot detection systems are tuned to detect headless Chromium specifically.

### Human behaviour simulation

Even with the right fingerprint, purely mechanical behaviour (zero mouse movement, perfectly timed requests) can trigger behavioural analysis. The fetcher simulates:

- **Curved mouse movement** — quadratic Bézier paths with random control points and ±2px jitter per step, rather than straight lines
- **Irregular scrolling** — broken into 3–6 chunks with variable delays, occasionally scrolling back up slightly
- **Idle movement** — random cursor repositioning between actions
- **Link hovering** — occasionally moving the mouse over a link without clicking
- **Timing jitter** — all waits are multiplied by a random factor (0.8–1.2×) so timing is never metronomic
- **Between-page delays** — base delay jittered by 0.7–1.5×

### Challenge detection

`is_challenge_page()` checks for three markers that only appear in real Cloudflare interstitial pages:

```python
markers = [
    "performing security verification",
    "cf-turnstile-response",
    "just a moment",
]
```

Deliberately excluded are `"cloudflare"` and `"challenge-platform"` — these appear as residual analytics scripts on successfully loaded pages and cause false positives. The Cloudflare JS telemetry script (`challenge-platform/scripts/jsd/main.js`) stays in the DOM after a page has passed verification and is not an indicator of a blocked request.

---

## Configuration

All settings live in `config.toml`. Copy `config.example.toml` to get started.

```toml
[bfi]
listing_urls = [
  # New releases — all current and upcoming IMAX films
  "https://whatson.bfi.org.uk/imax/Online/default.asp?BOparam::WScontent::loadArticle::permalink=imax-new-releases&BOparam::WScontent::loadArticle::context_id=",
  # Nolan season — dedicated page for Nolan retrospective screenings
  "https://whatson.bfi.org.uk/imax/Online/default.asp?BOparam::WScontent::loadArticle::permalink=christopher-nolan-film&BOparam::WScontent::loadArticle::context_id=",
]

[watch]
titles = ["Interstellar", "Tenet", "Dunkirk", "Oppenheimer", "Inception", "The Odyssey"]
watchlist_only = true   # false = alert on every film, not just watchlist

[app]
log_level = "INFO"
save_raw_html = true          # save HTML snapshots of parsed pages
raw_html_dir = "data/raw"
save_challenge_html = true    # save HTML snapshots of challenge pages
challenge_html_dir = "data/challenges"
db_path = "data/sentinel.db"

browser_headless = false      # headed mode is less suspicious
browser_warmup_url = "https://whatson.bfi.org.uk/imax/"
browser_delay_between_pages_seconds = 2.5
browser_enable_stealth = true
browser_simulate_human_behaviour = true
```

**Never put secrets in `config.toml`** — it's gitignored but still a plain text file. Telegram credentials go in `.env` only.

---

## Telegram setup

1. Open Telegram, search `@BotFather`, send `/newbot`
2. Follow prompts — you get a token like `7123456789:AAFxxxxxxx`
3. Send your bot any message (e.g. `/start`)
4. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
5. Find `result[0].message.chat.id` in the JSON — that's your chat ID
6. Add both to `.env`:

```bash
TELEGRAM_BOT_TOKEN=7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=123456789
```

`python-dotenv` loads `.env` automatically at startup via `load_dotenv()` in `main()`.

---

## How change detection works

Change detection is purely a comparison of the current status against the last-stored status for a given `context_id`.

On every run, for every performance parsed:

```
context_id seen before?
    NO  → INSERT row, return is_new=True
    YES → compare status
            SAME    → UPDATE last_seen_at only, return status_changed=False
            CHANGED → UPDATE status + last_status_at, INSERT status_history row,
                      return status_changed=True
```

`main.py` receives the change dict and decides what to notify:

```
is_new=True          → notify_new_listing()
status_changed=True  → notify_status_change()  (filtered by interesting transitions)
neither              → silent
```

The first run populates the DB from scratch — every performance is `is_new=True` and triggers a new listing alert. Subsequent runs are differential — only genuine changes generate noise.

---

## Data model

```
performances
├── context_id      PK  — AudienceView screening UUID
├── article_id          — AudienceView film UUID (shared across all screenings of same film)
├── title
├── datetime_str        — raw string, e.g. "Saturday 21 March 2026 21:00"
├── venue
├── status              — available | soldout | unavailable
├── booking_url         — deep link to the booking page for this screening
├── source_url          — which listing page surfaced this film
├── first_seen_at       — ISO datetime, set once on insert
├── last_seen_at        — ISO datetime, updated every run
└── last_status_at      — ISO datetime, updated only on status change

status_history
├── id              PK  — autoincrement
├── context_id          — FK to performances
├── old_status
├── new_status
└── changed_at          — ISO datetime
```

You can inspect the DB directly:

```python
uv run python -c "
from imax_sentinel.store import get_all_performances
for p in get_all_performances():
    print(p['title'], '|', p['status'], '|', p['datetime_str'])
"
```

---

## Roadmap

### V1 — Reliable watcher + alerting ✅

Camoufox fetcher, two-stage HTML parser, SQLite change detection, Telegram alerts. Monitors new releases and Nolan season pages. Alerts on new listings and ticket availability changes.

### V2 — Robustness + deployment

- Deploy to a VPS or GitHub Actions scheduled workflow (runs 24/7 without your laptop)
- Exponential backoff and retry logic
- Daily heartbeat Telegram message (`notify_health_check`)
- Sentry exception tracking
- Parser fixtures and golden HTML tests so breakage is caught before missed alerts
- Pagination support for film pages with many screenings

### V3 — Smarter parsing + preferences

- Sniff AudienceView's background API calls (often cleaner than DOM scraping)
- Preference filtering: day-of-week, time windows, format (IMAX 70mm specifically)
- Richer alert messages including format, runtime, special event flag

### V4 — Seat awareness

- Playwright-driven seat map checks for target performances
- Detect available seats in preferred zones
- Tighter polling cadence (every 1–2 min) once a target performance is detected
- Careful rate limiting — only activates for specific performances, not every poll

### V5 — Auto-book assist

- Bot detects tickets are live, opens a real browser window
- Auto-navigates to correct performance, pre-selects date/time/quantity/zone
- Hands off to human for payment confirmation (3D Secure gates the final step)
- Intentionally not fully automated — human stays in the loop

---

## Rate limiting and etiquette

The BFI box office runs on Tessitura/AudienceView — not a hyperscale platform. The bot is designed to be a polite citizen:

- **5–15 minute polling cadence** — more than fast enough, tickets rarely sell out in under 15 minutes for non-premiere screenings
- **Randomised delays** between pages and between runs — never metronomic
- **Single browser session** per run — not concurrent requests
- **Conditional caching** — raw HTML snapshots mean you can re-parse without re-fetching during development
- **Identifies itself** via realistic but non-deceptive browser headers
- **No seat map hammering** — seat awareness (V4) only activates for specific target performances and runs on a separate tighter schedule, not the main polling loop
