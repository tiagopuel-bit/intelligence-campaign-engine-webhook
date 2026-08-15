# Monday Activation Runbook — First Live Session After Alert Activation

**Scope:** Monday morning is a *watch-the-pipeline* session, not a trading
session. The goal is to confirm the five activated TradingView alerts actually
produce fresh heartbeats and clear `/paper/health`. It does **not** seed the
experiment or start auto-execution — that is checkpoint P4 and needs separate
explicit authorization. Stop and report anything unusual; do not improvise.

## 1. Poll `/paper/health` (no auth required)

```bash
curl -s https://<railway-host>/paper/health | python3 -m json.tool
```

Response shape (no secrets, no balances):

```json
{
  "status": "ok",
  "paper_only": true,
  "experiments": 0,
  "pending_proposals": 0,
  "approved_proposals": 0,
  "paper_executed_proposals": 0,
  "global_auto_disabled": false,
  "active_experiment_id": null,
  "authoritative_provider_ready": false,
  "runner_ready": false,
  "blockers": [ "..." ]
}
```

The only field you need to watch Monday morning is `blockers` (and the two
`*_ready` booleans).

## 2. What each blocker means (plain language)

| Blocker code | Plain meaning | Clears when |
| --- | --- | --- |
| `BLOCKED_NO_DISTINCT_UNDERLYING_HEARTBEAT` | The underlying-heartbeat table doesn't exist at all. | The webhook ingestion creates it on first accepted relay (structural; should already be true because the alerts are configured). |
| `BLOCKED_NO_LIVE_CONTRACT_RELAY` | The option-heartbeat table doesn't exist at all. | Same as above (structural). |
| `BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT` | AMC's latest 1-minute underlying bar is older than 2 minutes. | The AMC 1m underlying alert fires a fresh confirmed bar. |
| `BLOCKED_NO_FRESH_OPTION_HEARTBEAT:<instrument_ref>` | One held AMC option (that `instrument_ref`) has no 1-minute quote newer than 2 minutes. | That specific option's `OPTION_HEARTBEAT` alert fires a fresh bar. |
| `BLOCKED_NO_AUTHORITATIVE_PROVIDER_STATUS` | The readiness provider isn't mounted. | Should never appear on Railway; report it if it does. |

## 3. Expected clearance order and timing

1. **Structural blockers clear first** (the two heartbeat tables already exist
   on the live instance because the alerts are configured). If you see
   `BLOCKED_NO_DISTINCT_UNDERLYING_HEARTBEAT` or `BLOCKED_NO_LIVE_CONTRACT_RELAY`
   on Monday, the relay isn't even writing tables — stop and report.
2. **`BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT` clears first** — expect it gone
   within ~2–3 minutes after the 9:30 ET open (TradingView confirms each 1-min
   bar at its close, so the first AMC confirmed bar lands ~9:31 ET, then relay
   latency).
3. **`BLOCKED_NO_FRESH_OPTION_HEARTBEAT:<instrument_ref>` clears per instrument
   (6, 8, 9, 10)** as each option's 1-minute relay arrives — usually within the
   same few minutes, but they may stagger.

You should see `authoritative_provider_ready` flip to `true` once all five
freshness blockers are gone.

## 4. What `authoritative_provider_ready` and `runner_ready` actually unlock

- `authoritative_provider_ready: true` means the **data** is fresh (a live AMC
  underlying bar and a fresh quote for every held option). It is what allows a
  proposal to be *created* server-side at all — without it,
  `POST /paper/proposals` returns `409 no authoritative state; proposal
  blocked`.
- `runner_ready: true` means `authoritative_provider_ready` **and** an ACTIVE
  experiment row exists **and** global auto is not disabled. It is what unlocks
  the UI `Approve`/`Modify` controls and the auto-execution runner.

**Crucial Monday nuance:** `runner_ready` will stay `false` even after the
blockers clear, because `active_experiment_id` is still `null` until the P4
activation seeds the experiment. That is correct and expected — it is **not** a
bug. `authoritative_provider_ready: true` + `runner_ready: false` is the exact
"relay pipeline verified, experiment not yet activated" state you want Monday
morning.

**What still requires your explicit approval:** seeding the experiment
(creating the ACTIVE `pe_experiments` row + the atomic starting-holdings
snapshot) and enabling global auto. None of that happens Monday without a
separate P4 go-ahead.

## 5. What a healthy first proposal looks like

Once P4 is live and a proposal is created, check it with (auth required):

```bash
curl -s -H "Authorization: Bearer $STATE_API_TOKEN" \
  https://<railway-host>/paper/proposals | python3 -m json.tool
```

Per-proposal sanity checks:

- `action` in `hold | open | add | partial_reduce | close | roll`.
- `very_high` is `0` or `1`. `1` means all four evidence roots
  (underlying DNA, contract response, execution quality, portfolio risk) were
  present at proposal time.
- `very_high_missing_roots` is `null`/empty when `very_high=1`; otherwise it
  names the missing roots. (The per-root evidence lives in the separate
  `pe_proposal_evidence` table, not in this list.)
- `position_ref` / `instrument_ref` present and matching a real open holding
  for `add` / `partial_reduce` / `close` / `roll`; `null` for `open` / `hold`.
- `mode` is `AUTO_IF_VERY_HIGH_PAPER` only when `very_high=1`, else
  `APPROVAL_REQUIRED`.
- `current_status` starts at `PENDING_APPROVAL`; `expires_at` ≈ 10 minutes
  after `created_at`.

## 6. Stop and report — don't improvise

Stop and log the exact `/paper/health` JSON (and `PAPER_TRADE_DESK_LOG.md`) if
any of these happen:

- A freshness blocker is still present **more than ~5 minutes after the open**
  (underlying should be fresh within ~2–3 min; a stuck
  `BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT` after 5 min means a relay or webhook
  problem).
- A structural blocker (`BLOCKED_NO_DISTINCT_UNDERLYING_HEARTBEAT`,
  `BLOCKED_NO_LIVE_CONTRACT_RELAY`, or `BLOCKED_NO_AUTHORITATIVE_PROVIDER_STATUS`)
  appears at all.
- `authoritative_provider_ready` flips back to `false` mid-session (heartbeats
  stopped flowing).
- `runner_ready` is `true` while a blocker is still listed (inconsistent
  state), or `runner_ready` is `true` while `active_experiment_id` is `null`.
- A proposal has `very_high=1` while the DNA read visibly contradicts it (e.g.
  a FAIL / broken-campaign read still marked very_high), or `position_ref` /
  `instrument_ref` don't match the holdings — this smells like a fabricated
  or bypassed evidence root.
- Anything looks like it's bypassing a gate (a fill with no price reference
  that isn't `UNSCORABLE_EXECUTION_DATA`, a decision that skipped the
  10-minute window, a mutation accepted with unknown fields).

The closed-market blockers you saw this weekend are **not** errors — they are
the fail-closed default. On Monday they are expected to clear in the order
above.

## 7. First real entry

When something actually happens Monday (a proposal is created, a decision is
made, a fill lands), log it in `docs/PAPER_TRADE_DESK_LOG.md` using the
fixed entry format in that file's header (newest at the top). Use
`scripts/export_trade_desk_entry.py <proposal_id>` to pre-fill the skeleton
from the DB rather than retyping it.
