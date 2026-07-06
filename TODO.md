# TODO / Tickets

## TICKET-1 — Decouple enrichment cadence from the scrape sleep

**Status:** open · **Priority:** medium

### Problem
Enrichment currently runs *inside* `run_cycle`, before the polite scrape sleep,
so the whole pending-queue drain is gated by the website-politeness interval
(~15 min). But enrichment mostly talks to our **own** local LLM, which has no
politeness budget — it shouldn't wait 15 min between drains. A backlog (e.g. a
burst of ~25 survivors) therefore takes several cycles (~1 hr) to clear instead
of draining as fast as the LLM allows.

Note: discovery is **not** lossy — `find_new()` compares against the DB, and
listings live ≥30 min, so the scrape sleep never misses listings. The sleep is
the intended anti-block / politeness measure and should stay. Only the
*enrichment* coupling is the bug.

### Proposed fix (single-threaded, no threads)
Split the two cadences in the main loop:
- **Scrape**: gate to the polite interval (~15 min ± jitter) — `fetch` +
  `find_new` + `mark_seen` + cheap-filter survivors. The only throttled part.
- **Enrichment**: drain the pending queue **continuously in small batches**
  between scrapes, re-checking the "is a scrape due?" timer after each batch so
  a long backlog defers the next scrape by at most one batch.
- **Idle sleep**: only when no scrape is due *and* the queue is empty.

Loop sketch:
```
last_scrape = -inf
while not shutdown:
    if monotonic() - last_scrape >= next_interval:
        scrape + find_new + mark_seen + cheap-filter
        last_scrape = monotonic(); next_interval = interval ± jitter
    pending = store.get_pending(batch)        # batch = max_enrich_per_cycle
    if pending:
        for l in pending: enrich + _finalize + mark_processed
    else:
        interruptible sleep until next scrape is due
```

### Config changes
- Drop `max_enrich_seconds` (the scrape timer bounds enrichment deferral now).
- Repurpose `max_enrich_per_cycle` → drain **batch size** between timer checks.

### Notes
- The detail-page fetch hits external provider sites, but each fetch is followed
  by ~50–70s of local LLM time, so consecutive external fetches stay naturally
  ~70s apart even when draining continuously — no extra politeness delay needed.
- Disabled-LLM path must keep today's behaviour (scrape → notify immediately →
  sleep).

### Files
`main.py` (loop refactor), `config/settings.json` + `.example`, `README.md`,
tests.

### Acceptance
- A backlog drains across back-to-back batches without waiting a full scrape
  interval between them.
- Scrapes still fire on the polite ~15-min cadence regardless of enrichment load.
- Idle (empty queue) does not busy-spin.

---

## TICKET-2 — Datasette data browser (config drafted, pending install)

**Status:** open · **Priority:** low

Read-only web UI over `data/listings.db` for per-listing lookup, facets, and
ad-hoc SQL — viewed over Tailscale.

**Already drafted (uncommitted, in `analysis/`):**
- `analysis/metadata.json` — title, facets (district / wbs / energy_class /
  heating_type), and 7 canned queries (passed-by-score, cheapest, by-district,
  block-reasons, wbs/energy breakdowns, enrichment-coverage).
- `analysis/datasette.service` — systemd unit binding only to the Tailscale IP,
  read-only.
- README "Browse & analyse with Datasette" section.

**To finish:** commit `analysis/` + README; on the server `pip install datasette
datasette-vega`, `git pull`, install + enable the systemd unit, open
`http://<tailscale-ip>:8001/`.

**Watch out:** Datasette 1.0+ moves canned queries/facets from `metadata.json`
into `datasette.yaml` — convert if on 1.0+ (SQL console works regardless).

---

## TICKET-3 — Grafana data dashboards (SQLite)

**Status:** open · **Priority:** low

Grafana has **no native SQLite datasource**. Two routes:
- **Route A (recommended):** `frser-sqlite-datasource` plugin → add datasource
  pointing at the absolute DB path → SQL panels.
  - Gotcha 1: the `grafana` user must be able to read the DB file + its `-wal`
    and `-shm` sidecars under `/home/shuvanon/…` (group-read or ACL
    `setfacl -m u:grafana:rX`). Plugin opens read-only — safe with the scraper.
  - Gotcha 2: `seen_at` is an ISO string; for time panels convert to epoch:
    `CAST(strftime('%s', seen_at) AS INTEGER) * 1000 AS "time"`.
- **Route B:** `yesoreyeram-infinity-datasource` → pull Datasette JSON
  (`/listings/<query>.json?_shape=array`). Decoupled, reuses Datasette (TICKET-2),
  but fiddlier parsing.

**Starter time-series panels:** listings discovered per day, % blocked over
time, avg `total_rent` trend, HIGH-priority count per day, enrichment backlog
(`processed_at IS NULL`) over time. (Per-listing lookup stays in Datasette;
Grafana is for the aggregate/time view.)

---

## TICKET-4 — Logs in the browser (Loki + Grafana) — replace `journalctl -f`

**Status:** open · **Priority:** low

Live log tail + search in Grafana instead of a terminal. Grafana can't read
journald directly — needs Loki.

**Stack:** Loki (single binary, filesystem storage, `:3100`) + Grafana Alloy
(log shipper; replaces Promtail) + Grafana Loki datasource.

**Process:**
1. Install Loki as a systemd service (minimal single-node config).
2. Install Alloy with a `loki.source.journal` filtered to
   `unit = wohnungsfinder.service` → `loki.write` → `http://localhost:3100/loki/api/v1/push`.
   Alloy needs journal read access (run as root or add to `systemd-journal` group).
3. Add Loki datasource in Grafana.
4. **Explore → Loki →** `{unit="wohnungsfinder.service"}` → toggle **Live** for
   realtime tail. Add as a Logs panel for an always-on view.

**Bonus:** LogQL filters (`|= "BLOCKED"`, `|= "LLM call failed"`); derive
log-based metrics/alerts (e.g. alert when `LLM call failed` spikes). Add other
units (`datasette.service`, `llama-server.service`) as more `unit` labels.

**Watch out:**
- Enable persistent journald (`Storage=persistent` in journald.conf) for history
  across reboots — or ship `logs/scraper.log` via `loki.source.file` instead.
- Set a Loki retention period (e.g. 30 days).
