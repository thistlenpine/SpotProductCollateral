# product-collateral — Human Gates & Budget

## Human gates

| # | Gate | Trigger condition | Who approves |
|---|------|-------------------|--------------|
| G1 | Pre-run sign-off | Before the first live run on real BottlePOS/PocketBase data. Must confirm: (a) the UPCitemdb trial endpoint's rate limits are acceptable for this catalog's weekly incremental volume, (b) UPC-sourced images may be stored and displayed on SpotSpirits.com, (c) the PocketBase `products` collection schema (Task 3's migration) matches what's actually deployed. | Loop owner |
| G2 | Verifier anomaly | `verify_manifest` returns `False` on any run | Loop owner |

### How to clear a gate

There is no structured gate-request record. `STATE.json` holds exactly three
fields — `consecutive_failures`, `last_run`, and `last_run_id` — so a gate
surfaces as a halted run rather than as an entry to read:

1. The loop halts and exits non-zero. Either `verify_manifest` returned `False`
   for the run (gate G2), which increments `consecutive_failures` and makes
   `main.py` exit `1`; or the `consecutive_failures >= 10` check at the top of
   `main.py` stops the run before it does any work. Both paths print an
   explanatory message to stderr.
2. A human diagnoses the halt by reading the `consecutive_failures` count in
   `STATE.json`, the stderr messages captured in `run_weekly.log` (the
   redirected output of `run_weekly.ps1`), and the run manifest at
   `runs/<run_id>.json`.
3. Once the underlying problem is fixed, the human edits `STATE.json` by hand
   to reset `consecutive_failures` to `0`. The next scheduled or manual run
   then proceeds normally.

For G1 (pre-run sign-off), approval is given by a human in chat before the
first live run; nothing about it is recorded in `STATE.json`.

Never self-approve.

## Budget / stop

| Dimension | Limit | Action on breach |
|-----------|-------|-------------------|
| Max consecutive failed runs | 10 | Halt the loop before doing any work; print the reason to stderr (captured in `run_weekly.log`) and exit non-zero; wait for a human to diagnose and reset `consecutive_failures` in `STATE.json` |

Each run is a single weekly (or on-demand) batch, not an open-ended retry
loop, so no separate wall-clock or per-run iteration cap was added beyond
the consecutive-failure count.

## Single-worker note

This loop runs one worker at a time (weekly trigger or manual chat
invocation) against a single `STATE.json`. No parallel/worktree execution.
