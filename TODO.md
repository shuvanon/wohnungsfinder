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
