# SpotProductCollateral — Design Spec

Date: 2026-08-29

## Purpose

Store and serve product content — images and written content (descriptions,
tasting notes, region, ABV, etc.) — for the products BottlePOS carries, so
that `SpotWeb` (the storefront) and `SpotSommelier` (the AI sommelier
service) can display richer product information than BottlePOS itself
provides.

Content is sourced automatically: UPC/barcode lookups for images and basic
descriptions, and a web-search-driven crawler for tasting profiles and other
advanced content that isn't available from a structured source.

## Non-goals

- This repo does not run its own product database. It writes into SpotWeb's
  existing PocketBase instance rather than standing up a second one.
- This repo does not scrape and republish third-party text verbatim. All
  crawler-derived content is an original AI-written synthesis with cited
  sources, not a copy of scraped copy.
- No manual content-authoring UI is being built here — PocketBase's built-in
  admin UI serves that role.

## Architecture

A Python repo, matching the style of sibling repos (`BottleIntegrations`,
`SpotOrderRecommender`, `SpotSalesForecasting`), that runs as a Claude
Code-orchestrated **weekly loop**, following the same operational pattern as
`SpotOrderRecommender`:

- `SKILL.md` — the loop's durable logic (goal predicate, pipeline steps,
  verification, stop criteria).
- `TRIGGER.md` — host-agnostic launch contract: weekly Windows Task
  Scheduler trigger (not `CronCreate` — session-only and useless for a
  standing job, per `SpotOrderRecommender`'s documented finding) plus a
  manual chat-invocation trigger.
- `HUMAN-GATES.md` — pre-first-run sign-off, verifier-failure gate, and a
  consecutive-failure budget stop.
- `STATE.md` — runtime state (last run, counters, gate requests). Never
  read as durable logic.

**Data store:** SpotWeb's existing PocketBase instance
(`SpotWeb/apps/pocketbase`). This repo adds new collections via PocketBase
migrations rather than standing up a second instance — SpotWeb already
operates and hosts this PocketBase, so reusing it means one fewer service
to run, and SpotWeb (a consumer) gets local access for free.

**Consumers:**
- `SpotWeb` reads the new collections directly from its own local
  PocketBase instance.
- `SpotSommelier` reads the same collections as a remote HTTP client of
  PocketBase's REST API (its own read-scoped API token).

## Data model (PocketBase collections)

### `products`

One record per BottlePOS catalog item that has been enriched.

| Field | Type | Notes |
|---|---|---|
| `upc` | text, unique | Matches BottlePOS `Item.code` (primary UPC/barcode) |
| `bottlepos_item_id` | text | BottlePOS internal item ID, for traceability |
| `name` | text | From UPC lookup, falls back to BottlePOS item name |
| `image` | file | From UPC lookup, if found |
| `description` | text | From UPC lookup |
| `tasting_profile` | text | AI-synthesized from crawler, cites sources |
| `region` | text | From crawler, if found |
| `abv` | number | From crawler, if found |
| `sources` | JSON (list of URLs) | Every source the crawler cited |
| `confidence` | select: `high` / `low` | See confidence rule below |
| `status` | select: `published` / `needs_review` | Publish gate |
| `last_enriched_at` | date | Timestamp of the enrichment that produced this record |

Exact PocketBase field types/migration scripts are an implementation detail
for the plan, not fixed further here.

## Pipeline (per weekly run)

1. **Scan** — walk the BottlePOS catalog via `BottleIntegrations`'
   `BottlePOSClient.list_items()` (the same pattern `SpotOrderRecommender`
   uses — not `search_items()`, which requires a filter). Diff against the
   `products` collection by `upc` to find items with no record yet, or
   whose BottlePOS data has changed since `last_enriched_at`.
2. **UPC lookup** — for each item needing enrichment, query a barcode/
   product lookup API for name, image, and description. Which specific API
   (Go-UPC, UPCitemdb, UPC Data 4 Spirits, etc.) is an implementation-time
   choice based on coverage/cost, made and recorded in the implementation
   plan or at the pre-run human gate — not fixed in this spec.
3. **Crawl & synthesize** — use Claude's built-in web search tool (Anthropic
   API) to search for tasting profile, region, ABV, and similar advanced
   content. Claude writes an original summary in its own words and returns
   the URLs it drew from — the pipeline never stores or republishes scraped
   text verbatim.
4. **Write** — upsert the `products` record with the results of steps 2–3,
   set `confidence` and `status` per the rule below, set
   `last_enriched_at`.

**Confidence / review rule:** a record is marked `confidence: low` and
`status: needs_review` when the UPC lookup found no matching product, or
the crawler found zero usable sources for the tasting profile. Otherwise
`confidence: high` and `status: published` — content goes live
automatically. You review `needs_review` records directly in PocketBase's
admin UI; there is no separate review tool.

## Error handling & budget

Mirrors `SpotOrderRecommender`'s pattern:

- Per-item failures (a UPC lookup error, a crawl that turns up nothing) are
  logged and the item is skipped for this run, not treated as a run
  failure.
- A `consecutive_failures` counter in `STATE.md` tracks whole-run failures
  (e.g. PocketBase unreachable, BottlePOS auth failure). At 10 consecutive
  failures, the loop halts and raises a human gate rather than continuing
  to fail silently.
- A deterministic verifier (no AI calls) checks the run's manifest before
  the run is considered complete, same shape as `SpotOrderRecommender`'s
  `verifier.py`.

## Testing

- Unit tests mock all external calls (UPC lookup API, PocketBase, Claude
  web search) — no live network calls in CI, matching `BottleIntegrations`'
  `mock_server.py` pattern of standing up a local fake server for
  integration-style tests.
- Cover: BottlePOS-to-PocketBase diffing logic, confidence/status
  determination, PocketBase upsert payloads, and the verifier.

## Human gates

Detailed gate table to be written in `HUMAN-GATES.md` during
implementation, but must include at minimum:

- **Pre-first-run sign-off:** confirm the PocketBase schema, the chosen UPC
  lookup API and its licensing/rate limits, and the assumption that
  UPC-sourced images may be stored and displayed on SpotSpirits.com.
- **Verifier-failure gate:** any run where the verifier returns non-zero.
- **Budget/stop gate:** 10 consecutive failed runs, per Error handling
  above.

## Open implementation-time decisions (not blocking spec approval)

- Specific UPC lookup API/vendor.
- Exact PocketBase migration/field definitions.
- Whether `SpotSommelier`'s PocketBase API token is read-only and how it's
  provisioned/stored.
