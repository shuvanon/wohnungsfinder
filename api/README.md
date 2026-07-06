# Wohnungsfinder API

A small **read-only HTTP API** serving scraped Berlin apartment listings as
JSON. Consume it without knowing anything about the scraper — this document is
the whole contract.

## Base URL & access

```
http://<host>:8002
```

- Bound to a private **Tailscale IP** by default. **No authentication** — access
  is controlled by network reachability (the tailnet).
- **Read-only.** No write endpoints exist; requests never modify data.
- Interactive/machine-readable schema: **`/docs`** (Swagger UI),
  **`/openapi.json`**.

## Conventions

- All responses are JSON. List endpoints return a JSON **array**; single-item
  endpoints return a JSON **object**.
- **Pagination:** `limit` (default 50, max 500) and `offset` (default 0).
- **Timestamps** are ISO-8601 strings (UTC), e.g. `2026-06-29T09:19:48.820+00:00`.
- `features` is an **array of strings**. Numeric fields are numbers or `null`.
- Newest-first ordering is by `seen_at` (when the listing was first seen).

## Endpoints

### `GET /health`
Liveness + basic stats.
```bash
curl http://<host>:8002/health
```
```json
{ "status": "ok", "listing_count": 1234, "schema_version": 3 }
```

### `GET /candidates`
**The main feed.** Listings that **passed** the filters (latest decision per
listing is "passed"), newest first, each with the full datasheet plus
`priority` and `score`.

| Param | Type | Default | Notes |
|---|---|---|---|
| `limit` | int | 50 | max 500 |
| `offset` | int | 0 | |
| `since` | string | — | ISO `seen_at`; return only listings newer than this (incremental polling) |

```bash
curl "http://<host>:8002/candidates?limit=20"
curl "http://<host>:8002/candidates?since=2026-06-29T09:00:00+00:00"
```
```json
[
  {
    "url": "https://www.berlinovo.de/de/wohnung-id/1100-2505-1309",
    "title": "Barrierearmes Wohnen im Dröpkeweg!",
    "address": "Dröpkeweg 11, 12353, Neukölln",
    "district": "Neukölln",
    "rooms": 1.0,
    "size_m2": 30.66,
    "cold_rent": 430.36,
    "total_rent": 599.12,
    "wbs": "nicht erforderlich",
    "wbs_tier": null,
    "available": "01.06.2026",
    "posted": "03.07.2026",
    "floor": "3 von (insg. 11)",
    "year_built": 2022,
    "features": ["Balkon", "Aufzug", "Fernwärme"],
    "heizkosten": null,
    "deposit": null,
    "energy_class": "C",
    "heating_type": "Fernwärme",
    "pets_allowed": null,
    "description_summary": "Helle 1-Zimmer-Wohnung, barrierearm.",
    "seen_at": "2026-07-03T08:12:05.120+00:00",
    "detail_fetched_at": "2026-07-03T08:14:11.540+00:00",
    "priority": "🔴 HIGH",
    "score": 70
  }
]
```

### `GET /listings`
All listings (not just passed), newest first. Same fields as `/candidates`
**minus** `priority`/`score` and **minus** the bulky `detail_text`.

| Param | Type | Default | Notes |
|---|---|---|---|
| `limit` | int | 50 | max 500 |
| `offset` | int | 0 | |
| `district` | string | — | exact match |
| `min_rent` | number | — | `total_rent >=` |
| `max_rent` | number | — | `total_rent <=` |
| `wbs` | string | — | e.g. `nicht erforderlich` |

```bash
curl "http://<host>:8002/listings?district=Mitte&max_rent=900&limit=10"
```

### `GET /listing`
One listing's **full** datasheet, including the raw `detail_text`.

| Param | Type | Notes |
|---|---|---|
| `url` | string | **required**, URL-encoded (it contains `:` and `/`) |

```bash
curl "http://<host>:8002/listing?url=https%3A%2F%2Fwww.berlinovo.de%2Fde%2Fwohnung-id%2F1100-2505-1309"
```
Returns the object (same fields as above) plus `detail_text` and `processed_at`.
**404** if no listing has that URL.

## Field reference

| Field | Type | Meaning |
|---|---|---|
| `url` | string | Unique key — the company's own listing/application deeplink |
| `title` | string | Listing title |
| `address` | string | Full address |
| `district` | string | Berlin Bezirk (e.g. `Pankow`) |
| `rooms` | number \| null | Rooms |
| `size_m2` | number \| null | Living area (m²) |
| `cold_rent` | number \| null | Nettokaltmiete (€) |
| `total_rent` | number \| null | Warmmiete / total (€) |
| `wbs` | string \| null | `nicht erforderlich` / `erforderlich` |
| `wbs_tier` | string \| null | e.g. `WBS 140` |
| `available` | string \| null | Availability date/text |
| `posted` | string \| null | When the listing was posted |
| `floor` | string \| null | Floor |
| `year_built` | int \| null | Construction year |
| `features` | string[] | Feature names (Balkon, Aufzug, …) |
| `heizkosten` | number \| null | Monthly heating cost (€) |
| `deposit` | number \| null | Kaution (€) |
| `energy_class` | string \| null | Energy efficiency class A–H |
| `heating_type` | string \| null | e.g. `Fernwärme`, `Gas` |
| `pets_allowed` | int \| null | `1`/`0` |
| `description_summary` | string \| null | One-line summary |
| `seen_at` | string | First seen (ISO) |
| `detail_fetched_at` | string \| null | When the detail page was enriched (ISO) |
| `priority` | string | *(`/candidates` only)* e.g. `🔴 HIGH` |
| `score` | int | *(`/candidates` only)* priority score |
| `detail_text` | string \| null | *(`/listing` only)* cleaned detail-page text |

## Integration pattern (polling for new candidates)

1. Call `GET /candidates?limit=500`. Process the results.
2. Remember the **highest `seen_at`** you've handled.
3. Poll `GET /candidates?since=<that seen_at>` on your own interval to get only
   listings that appeared since — dedupe on `url` (a listing can be re-seen).

## Errors

Standard HTTP status codes with a JSON body:
```json
{ "detail": "Listing not found" }
```
`404` — unknown `url` on `/listing`. `422` — invalid query params (e.g. `limit`
out of range).
