---
name: product-collateral
description: >
  Self-running loop: for each BottlePOS item that is new or whose name,
  description, or category has changed since last enrichment, a PocketBase
  `products` record exists with UPC-sourced image/description and a
  crawler-sourced tasting profile, marked `published` when both sources were
  found or `needs_review` otherwise. Fires weekly and on manual request.
---

# product-collateral

## Goal

**Exit predicate (checked every run):** every BottlePOS item with a non-empty
UPC that is new or has a changed name/description/category since its last
enrichment has a `products` record in PocketBase with `confidence`/`status`
set per the rule below, and `runs/<run_id>.json` names every item processed
this run plus any per-item errors. This is a per-run predicate — the loop
produces a fresh incremental batch each time it fires, it does not drain a
queue across runs.

## Pattern: ReAct + deterministic verifier

Each run proceeds in order:

### 1. Read state

Load `STATE.json` (this repo's root). If `consecutive_failures >= 10`, STOP
immediately and raise the budget gate in `HUMAN-GATES.md` — do not run.

### 2. Discover

Fetch the full BottlePOS catalog via `BottleIntegrations`' `BottlePOSClient.list_items()`
(not `search_items()` — it needs a filter). Diff against PocketBase's
`products` collection via `spot_product_collateral.bottlepos_scan.find_items_needing_enrichment`,
which hashes each item's name/description/category and compares against the
stored `bottlepos_snapshot_hash`.

### 3. Act

For each item needing enrichment: look up the UPC via
`spot_product_collateral.upc_lookup.lookup_upc`, crawl for a tasting profile
via `spot_product_collateral.crawler.crawl_tasting_profile` (Claude web
search — writes an original summary, never republishes scraped text), build
the PocketBase fields via `spot_product_collateral.enrichment.build_product_fields`,
and upsert via `PocketBaseClient.upsert_by_upc`. A record is `confidence:
high, status: published` only when both the UPC lookup and the crawl found
something; otherwise `confidence: low, status: needs_review` and it waits for
manual review in the PocketBase admin UI — no separate review tool.

Per-item failures are caught and logged to the run's `errors` list; they do
not abort the run.

### 4. Verify

`spot_product_collateral.verifier.verify_manifest` checks every manifest
entry has a `upc` and a valid `status`. On failure, increment
`consecutive_failures` in `STATE.json` and STOP — do not silently retry. At
10 consecutive failures this trips the budget gate in `HUMAN-GATES.md`.

### 5. Write state

Update `STATE.json` regardless of pass/fail, per step 4.

### 6. Check exit predicate

If `runs/<run_id>.json` exists and the verifier passed, this run's goal
predicate holds. The loop waits for the next trigger (weekly cron or manual
request) to produce the next batch.

## How to run

Consult `TRIGGER.md` for the per-host invocation. Before the first live run,
clear gate G1 in `HUMAN-GATES.md`.

## What "done" means (per run)

- `runs/<run_id>.json` exists and the verifier returned `True` for it.
- `STATE.json` has an updated `last_run` timestamp.
- No open gate from `HUMAN-GATES.md` is blocking.

The loop never reaches a final "done" state — it recurs weekly. "Done"
applies per run, per the predicate above.
