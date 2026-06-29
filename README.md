# Wohnungsfinder Scraper

Monitors [inberlinwohnen.de](https://www.inberlinwohnen.de/wohnungsfinder) every ~12 minutes and sends Telegram notifications for new apartment listings. Supports hard filtering (block WBS-only, keywords, rent limits) and priority scoring (🔴 HIGH / 🟡 MEDIUM / ⚪ LOW). Notifies one or multiple people simultaneously.

## How it works

Each scrape cycle:
1. Fetches the Wohnungsfinder page and paginates through all listings via the Livewire API
2. Finds listings not seen before
3. Marks them as seen in a local SQLite database
4. Runs each new listing through hard filters — blocked listings are dropped
5. **(optional)** For survivors, fetches the listing's own detail page and uses an LLM to re-extract the **whole datasheet** from it; those values overwrite the list data (the detail page is authoritative), then re-applies the hard filters
6. Scores remaining listings by your priority rules
7. Sends a Telegram notification to all configured recipients

The list view is shallow and **frequently wrong** — a total rent shown as 600 €
can really be 1100 € on the listing's own page, and a WBS requirement is often
hidden there too. Each listing links out to the housing company's own site
(degewo, howoge, gewobag, wbm, gesobau, …), where the real detail lives. Since
every provider's page is structured differently, the optional enrichment step
(5) hands the page text to an LLM to normalize it into structured fields rather
than maintaining a parser per provider. **The detail page wins:** every field
the LLM extracts overwrites the list value; the list value is kept only where
the page doesn't yield that field. The LLM only fills fields — your config
rules still decide pass/fail, now on the corrected datasheet.

Because a self-hosted LLM is a single stream and new listings arrive in bursts
(0 for an hour, then 30 at once), discovery and enrichment are decoupled: each
cycle marks all new listings seen, then drains a **budgeted slice** of the
pending queue (`max_enrich_per_cycle` / `max_enrich_seconds`). Bursts drain
across cycles; idle stretches let the queue catch up; a crash mid-drain just
leaves listings pending for the next cycle. The `enrich_scope` setting controls
how much gets enriched: `"survivors"` (default) runs the cheap filters on list
data first so obvious nos never cost a detail fetch; `"all"` enriches every new
listing and lets the (often-wrong) list data decide nothing. Enrichment is
**off by default**; enable it in the `llm` config section (see below).

On the **first run**, all current listings are silently saved as "seen" — no notifications are sent. From the second run onwards, only genuinely new listings trigger notifications.

## Project structure

```
wohnungsfinder/
├── main.py                        # Entry point and scrape loop
├── requirements.txt               # Runtime dependencies (3 packages)
├── setup.sh                       # One-command Ubuntu server setup
├── wohnungsfinder.service         # systemd unit for 24/7 operation
├── README.md
├── config/
│   ├── loader.py                  # Config validation
│   └── settings.json              # All user-facing configuration
├── scraper/
│   ├── fetcher.py                 # HTTP fetching + Livewire pagination
│   ├── parser.py                  # Livewire snapshots → listing dicts
│   ├── detail_fetcher.py          # Fetch + clean a listing's detail page
│   └── store.py                   # SQLite store (listings + filter audit log)
├── enrich/
│   └── llm.py                     # LLM extraction (OpenAI-compatible endpoint)
├── filters/
│   ├── hard_filter.py             # Block unwanted listings
│   └── priority.py                # Score and label remaining listings
├── notifier/
│   ├── telegram.py                # Multi-recipient Telegram delivery
│   └── formatter.py               # Build notification message text
├── data/
│   ├── berlin_postcodes.json      # Postcode → Bezirk mapping
│   └── listings.db                # SQLite database (auto-created on first run)
├── logs/
│   └── scraper.log                # Log file (auto-created on first run)
└── tests/
    ├── fixtures.py                # Shared test listing dicts
    ├── test_parser.py             # 22 tests
    ├── test_hard_filter.py        # 22 tests
    ├── test_priority.py           # 18 tests
    ├── test_store.py              # 29 tests
    ├── test_formatter.py          # 14 tests
    ├── test_detail_fetcher.py     # 7 tests
    ├── test_llm.py                # 26 tests
    └── test_telegram.py           # 29 tests
```

## Deployment (Ubuntu server)

### 1. Copy the project to your server

```bash
scp -r wohnungsfinder/ youruser@your-server-ip:~/services/wohnungsfinder
```

Or clone from git:

```bash
git clone https://github.com/youruser/wohnungsfinder.git ~/services/wohnungsfinder
```

### 2. Set up Telegram

**Create the bot** (you do this once):

1. Open Telegram → search `@BotFather` → send `/newbot`
2. Follow the prompts and copy the token it gives you

**Get each recipient's chat ID:**

1. Each person searches for your bot by username and sends it any message
2. Open `https://api.telegram.org/botYOUR_TOKEN/getUpdates` in a browser
3. Find `"chat": {"id": 123456789}` — that number is their chat ID

If `getUpdates` returns an empty result, try `https://api.telegram.org/botYOUR_TOKEN/getUpdates?offset=-1` to force the latest update.

### 3. Configure

```bash
nano ~/services/wohnungsfinder/config/settings.json
```

Fill in your credentials:

```json
"telegram": {
    "bot_token": "7291038475:AAFx3mK9z2QpLzVjHbNwEuI8dYcXeT1rAoQ",
    "chat_ids": [
        "123456789",
        "987654321"
    ]
}
```

Use a list for multiple recipients, or a single string for one person.
Then tune `hard_filters` and `priority_scoring` to your preferences — see **Configuration reference** below.

### 4. Run setup

```bash
cd ~/services/wohnungsfinder
chmod +x setup.sh
sudo ./setup.sh
```

The script checks Python version, installs dependencies, runs all 177 tests, and offers to install the systemd service. When asked `Install as a systemd service? [y/N]` → type `y`.

### 5. Verify

```bash
sudo systemctl status wohnungsfinder
sudo journalctl -u wohnungsfinder -f
```

You should see the scraper start, paginate through ~240 listings across ~24 pages, and go to sleep for ~12 minutes.

## Useful commands

```bash
# Restart after changing settings.json
sudo systemctl restart wohnungsfinder

# View last 100 log lines
sudo journalctl -u wohnungsfinder -n 100

# Query the database directly
sqlite3 ~/services/wohnungsfinder/data/listings.db

# How many listings seen total?
# SELECT COUNT(*) FROM listings;

# Recent HIGH priority listings that passed filters:
# SELECT address, cold_rent, total_rent, seen_at FROM listings
#   JOIN filter_results USING(url)
#   WHERE passed=1 AND priority='🔴 HIGH'
#   ORDER BY seen_at DESC LIMIT 20;

# Why were listings blocked?
# SELECT block_reason, COUNT(*) FROM filter_results
#   WHERE passed=0 GROUP BY block_reason ORDER BY 2 DESC;

# Score breakdown for a specific listing:
# SELECT reasons FROM filter_results WHERE url='https://...' ORDER BY seen_at DESC LIMIT 1;
```

## Configuration reference

All settings live in `config/settings.json`. Restart the service after any change.

### `telegram`

| Key | Type | Description |
|---|---|---|
| `bot_token` | string | Token from @BotFather |
| `chat_ids` | string or list | One chat ID or a list of chat IDs |

### `hard_filters`

Listings matching any hard filter are dropped entirely and never scored or notified.

| Key | Type | Description |
|---|---|---|
| `max_total_rent` | number or null | Block listings above this total rent / Warmmiete (€) |
| `min_rooms` | number or null | Block listings with fewer rooms |
| `max_rooms` | number or null | Block listings with more rooms |
| `block_if_wbs_required` | bool | Block all WBS-required listings (set `true` if you don't hold a WBS) |
| `block_wbs_categories` | list | Block specific WBS categories e.g. `["WBS 100"]`. Matched against title, address, and — once enriched — the detail text / `wbs_tier`. |
| `block_keywords` | list | Block listings whose text contains any of these strings (case-insensitive). Searches title + address, plus the detail text / description once enriched (so markers buried in the listing body are caught). Without enrichment, only the title/address are available. |

### `priority_scoring`

Each rule adds points if the listing matches. Final score determines the label: 🔴 HIGH, 🟡 MEDIUM, or ⚪ LOW.

```json
"rules": [
    { "name": "No WBS required",  "field": "wbs",        "match": "nicht erforderlich", "points": 30 },
    { "name": "Total rent <€900", "field": "total_rent",  "max": 900,                    "points": 25 },
    { "name": "Total rent <€1100","field": "total_rent",  "min": 900, "max": 1100,       "points": 15 },
    { "name": "Has balcony",      "field": "features",    "contains": "Balkon",           "points": 10 },
    { "name": "District: Mitte",  "field": "district",    "contains": "Mitte",            "points": 15 }
],
"thresholds": {
    "high":   50,
    "medium": 25
}
```

Rule match types:

| Type | Example | Matches when |
|---|---|---|
| `match` | `"match": "nicht erforderlich"` | Field equals this value exactly |
| `contains` | `"contains": "Balkon"` | Field contains this substring |
| `min` | `"min": 3` | Numeric field ≥ value |
| `max` | `"max": 900` | Numeric field ≤ value |
| `min` + `max` | `"min": 900, "max": 1100` | Numeric field is within range |

**Available fields:**

| Field | Type | Description |
|---|---|---|
| `cold_rent` | number | Base rent (Kaltmiete) in € |
| `total_rent` | number | Total rent incl. extras (Warmmiete) in € — recommended for scoring |
| `rooms` | number | Number of rooms |
| `size_m2` | number | Living area in m² |
| `year_built` | number | Year of construction |
| `wbs` | text | `"nicht erforderlich"` or `"erforderlich"` |
| `district` | text | Berlin Bezirk e.g. `"Pankow"`, `"Mitte"` |
| `address` | text | Full address string |
| `title` | text | Listing title |
| `features` | list | `"Balkon"`, `"Loggia"`, `"Aufzug"`, `"Keller"`, `"Garten"`, `"Barrierefrei"`, `"Rollstuhlgerecht"`, `"Einbauküche"`, `"Badewanne"`, `"Dusche"`, `"Gäste WC"`, `"Parkett"`, `"Stellplatz"`, `"Tiefgarage"`, `"Möbliert"` |

> **Note on cold rent vs total rent:** `cold_rent` is the base rent shown prominently on each listing card. `total_rent` includes additional costs (Nebenkosten) and is what you actually pay each month. Using `total_rent` for scoring is more accurate since Nebenkosten vary significantly between buildings.

### `scraper`

| Key | Default | Description |
|---|---|---|
| `interval_minutes` | `12` | How often to check for new listings |
| `jitter_minutes` | `3` | Random ± added to interval (avoids fixed schedule) |
| `request_timeout` | `30` | HTTP timeout in seconds |
| `store_file` | `data/listings.db` | Path to SQLite database |
| `log_file` | `logs/scraper.log` | Path to log file |
| `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

### `llm` (optional detail-page enrichment)

When enabled, each listing that passes the cheap hard filters has its **detail
page** fetched and run through an LLM that extracts structured fields the list
view misses (see **How it works**, step 5). The backend is any
**OpenAI-compatible** `/v1/chat/completions` endpoint — a self-hosted server on
your own machine, a local runtime like Ollama, or a cheap cloud API. Switching
backends is a config change, not a code change.

| Key | Default | Description |
|---|---|---|
| `enabled` | `false` | Master switch. When `false`, the pipeline runs on list-view data only (unchanged behaviour). |
| `base_url` | `http://localhost:8000/v1` | Base URL of the OpenAI-compatible endpoint (no trailing `/chat/completions`). |
| `model` | `gemma-2-2b-it` | Model name to request. |
| `api_key_env` | `LLM_API_KEY` | Name of the **environment variable** holding the API key. Leave the variable unset for a local server that needs no key. |
| `timeout` | `60` | Per-request timeout in seconds. |
| `max_detail_chars` | `8000` | Cap on detail-page text sent to the model (bounds prompt size / latency). Most rent/WBS/energy facts are early on the page; 5000 is a good value for a CPU server. |
| `max_tokens` | `512` | Cap on the model's output. The extraction JSON is small, so this is ample — it exists to bound the worst case (an uncapped model can run away and generate until it fills the context, blowing the timeout). |
| `enrich_scope` | `survivors` | `survivors` = cheap-filter on list data first, only enrich passers; `all` = enrich every new listing (detail page is the sole authority). |
| `max_enrich_per_cycle` | `15` | Max listings enriched per cycle. Leftovers stay pending and drain next cycle. |
| `max_enrich_seconds` | `480` | Wall-clock cap on the enrichment phase per cycle (`0` = no cap). Keeps a burst from overrunning the scrape interval. |

The extractor re-reads the **whole datasheet** from the detail page and those
values overwrite the list data. It returns:

- **Datasheet fields** (overwrite the list value): `total_rent`, `cold_rent`,
  `rooms`, `size_m2`, `wbs`, `year_built`, `available`, `features`.
- **Detail-only fields** (not in the list view): `wbs_tier`, `heizkosten`,
  `deposit`, `energy_class`, `heating_type`, `pets_allowed`,
  `description_summary`.

All are stored on the listing and usable as `field` values in `hard_filters` /
`priority_scoring`. The merge is **detail-wins**: each field the LLM returns
overwrites the list value; a field the page doesn't yield keeps the list value.
The LLM never makes the pass/fail decision itself — it only fills fields; your
rules still decide, now on the corrected datasheet. If the endpoint is
unreachable or returns bad output, enrichment degrades gracefully and the
listing is processed on list-view data alone.

The raw detail-page text and a `detail_fetched_at` timestamp are also stored,
so extraction can be re-run after a prompt/model change without re-fetching.

## Viewing the data

The SQLite database at `data/listings.db` contains two tables:

**`listings`** — every apartment ever seen, with all parsed (and, when enrichment is on, detail-corrected) fields. `detail_fetched_at` shows when the detail page was enriched; `processed_at IS NULL` marks listings still queued for enrichment.

**`filter_results`** — one row per new listing per cycle, recording whether it passed filters, why it was blocked, its priority label, score, and score breakdown.

You can query it directly on the server with `sqlite3`, or copy it to your local machine and open it in a GUI like [TablePlus](https://tableplus.com/) or [DBeaver](https://dbeaver.io/).

## Running tests

```bash
./run-tests.sh           # activates venv if present, prefers pytest, falls back to unittest
./run-tests.sh -v        # extra args pass through (verbose)
```

Or run a runner directly:

```bash
python3 -m pytest tests/ -v
python3 -m unittest discover -s tests -v   # no extra dependency
```

Safe to run anytime, including on the deployment server — every test mocks HTTP and uses in-memory SQLite, so it never touches `settings.json`, the live database, or sends Telegram messages.

177 tests covering parser, hard filter, priority scorer, store, detail fetcher, LLM extraction, formatter, and Telegram notifier.

## Updating the code

```bash
cd ~/services/wohnungsfinder
git pull
sudo systemctl restart wohnungsfinder
```
