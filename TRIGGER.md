# product-collateral — Trigger Definition

## Verifiable goal (per run)

> Every BottlePOS item with a UPC that is new or changed since last
> enrichment has a PocketBase `products` record with confidence/status set
> per the rule in `SKILL.md`, and a run manifest exists naming every
> processed item and any errors.

## State files

```
STATE.json
runs/<run_id>.json
```

(All paths relative to this repo's root. Every run reads `STATE.json` at
startup and writes it before stopping.)

## Trigger 1: recurring schedule

**Cadence:** every Sunday at 8:00 AM (operator's local time) — chosen to run
after `SpotOrderRecommender`'s Sunday 7:00 AM job so the two don't contend
for the BottlePOS API at the same moment.

**Mechanism: Windows Task Scheduler** (same mechanism `SpotOrderRecommender`
uses — not `CronCreate`, which is session-only and dies with the Claude Code
process, and not the `schedule` skill's cloud routines, which have no access
to this machine's `.venv` or environment variables).

- **Task name:** `SpotProductCollateral Weekly`
- **Action:** runs `run_weekly.ps1` (this repo's root) via `powershell.exe`.
  If the full path contains spaces, use the 8.3 short path the same way
  `SpotOrderRecommender/TRIGGER.md` documents, rather than fighting
  `schtasks` quoting.
- **Schedule:** Weekly, Sunday, 8:00 AM, logon mode "Interactive only".
- **Created via:** `schtasks /create /tn "SpotProductCollateral Weekly" /tr
  "powershell.exe -NoProfile -ExecutionPolicy Bypass -File <path-to-run_weekly.ps1>"
  /sc WEEKLY /d SUN /st 08:00 /rl LIMITED /f` — re-verify this syntax against
  current `schtasks /create /?` output before creating it.

## Trigger 2: manual invocation

Ask the agent in chat, e.g.:

> Run the product-collateral loop now.

This loads `SKILL.md` fresh and proceeds through the same
read-state → discover → act → verify → write-state sequence.

## Launch prompt (host-agnostic fallback)

> Read `STATE.json` in this repo and the `product-collateral` skill's
> `SKILL.md`, then run the product-collateral loop.

## Trigger notes

- Gate G1 in `HUMAN-GATES.md` must be cleared before the recurring trigger is
  created.
- Since no human is present for the scheduled run, a tripped gate simply stops
  the run rather than self-clearing: `run_once` increments
  `consecutive_failures` in `STATE.json`, `main.py` prints the reason to stderr
  and exits non-zero, and `run_weekly.ps1` propagates that exit code so Task
  Scheduler records the run as failed. There is no separate structured
  gate-request record in `STATE.json` — a human diagnoses the halt from the
  `consecutive_failures` count in `STATE.json` plus the stderr messages in
  `run_weekly.log`, then resets the counter by hand.
- The budget/stop limit (10 consecutive failures) in `HUMAN-GATES.md` takes
  precedence over the weekly cadence.
