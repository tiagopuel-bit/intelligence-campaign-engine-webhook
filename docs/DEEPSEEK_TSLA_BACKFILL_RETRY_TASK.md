# Task packet — TSLA historical backfill (retry, verify against live volume)

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek. Retry of
`docs/DEEPSEEK_TSLA_BACKFILL_TASK.md` — that task was reported done earlier
today, but a fresh `/assets` pull just now shows TSLA still at
`timeframe_count: 2, backfill_replay: 0`. The earlier backfill did not
actually land on the live Railway volume. This packet exists because of
that gap, not because the original task's instructions were wrong.

## What likely happened (context, not confirmed)

Later the same day, a separate SSH-access question came up for the MARA
backfill: DS's default local/dev environment cannot reach the Railway
volume DB at all (`RAILWAY_VOLUME_MOUNT_PATH` unset, no `railway` CLI, no
mount). Tiago then approved registering an SSH key with Railway
specifically so DS could reach the real production volume, and MARA's
backfill was confirmed to have landed there afterward (`/assets` now shows
MARA with `backfill_replay: 4182`). The TSLA backfill earlier today was run
before that access existed — it most likely wrote to a local dev DB that
nothing live ever reads, which is why it "succeeded" in its own report but
never showed up on `/assets`.

## What to do

1. Confirm you're running against the **live Railway volume**, the same
   way the MARA backfill was just verified — not a local `dna_alerts.db`.
   If you need the same SSH access used for MARA, use it the same way.
2. Run the existing backfill (`webhook/backfill.py` / `POST /backfill`) for
   `TSLA`, full ladder (3m, 5m, 15m, 30m, 1H, 2H, 3H, 4H, D, W — match
   whatever the standard ladder is for the other assets).
3. Confirm the no-collision rule holds (backfilled rows end where live
   coverage begins, live rows always win on overlap).
4. **Verify with a real `GET /assets` query against the live Railway URL**
   (`https://dna-tradingview-webhook-production.up.railway.app/assets`) —
   report the actual `timeframe_count` and `backfill_replay` count you see
   there for TSLA, not a local DB count and not a description of the
   pipeline running. This is the same mistake to avoid as last time.
5. Also spot-check `GET /state_all/TSLA` against the live URL and report
   whether the campaign tier (180/240) now has real history, since that
   was the original motivating case (the "warming up" flag is structurally
   blind to TSLA without it).

## Boundaries

- No changes to the backfill pipeline itself unless something is actually
  broken.
- No changes to Pine, live webhook ingestion, or alert configuration.
- `phase` on backfilled rows is a reconstruction, not fidelity-tested —
  same caveat as every other backfilled asset.
- Full suite + `git diff --check` clean before reporting done. No
  deploy/commit/push needed — the backfill writes directly to the live DB,
  it doesn't touch tracked repo files unless the pipeline itself needs a
  symbol-list update somewhere.

## What to report back

The actual live `/assets` response for TSLA (row counts per
timeframe/source), confirmation of the no-collision rule, and the
`/state_all/TSLA` campaign-tier read. If for any reason you still can't
reach the live volume, say so explicitly and stop — don't report success
based on a local run again.
