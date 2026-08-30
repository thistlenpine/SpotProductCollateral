# product-collateral — Human Gates & Budget

## Human gates

| # | Gate | Trigger condition | Who approves |
|---|------|-------------------|--------------|
| G1 | Pre-run sign-off | Before the first live run on real BottlePOS/PocketBase data. Must confirm: (a) the UPCitemdb trial endpoint's rate limits are acceptable for this catalog's weekly incremental volume, (b) UPC-sourced images may be stored and displayed on SpotSpirits.com, (c) the PocketBase `products` collection schema (Task 3's migration) matches what's actually deployed. | Loop owner |
| G2 | Verifier anomaly | `verify_manifest` returns `False` on any run | Loop owner |

### How to clear a gate

1. The loop writes a gate-request entry to `STATE.json` with the gate ID,
   reason, and proposed action.
2. A human reads the entry, confirms it's safe, and replies with an explicit
   approval in chat.
3. The loop records the approval in `STATE.json` and continues.

Never self-approve.

## Budget / stop

| Dimension | Limit | Action on breach |
|-----------|-------|-------------------|
| Max consecutive failed runs | 10 | Halt the loop; write `budget-exceeded` to `STATE.json`; wait for a human to diagnose and reset the counter |

Each run is a single weekly (or on-demand) batch, not an open-ended retry
loop, so no separate wall-clock or per-run iteration cap was added beyond
the consecutive-failure count.

## Single-worker note

This loop runs one worker at a time (weekly trigger or manual chat
invocation) against a single `STATE.json`. No parallel/worktree execution.
