# P2A Independent Acceptance

Status: `CODE_ACCEPTED_RELAY_CONFIGURATION_REQUIRED`

The deterministic PAPER_ONLY execution path and Asset Page UI contract are
implemented and regression-tested. No broker route exists.

## Corrected acceptance boundaries

- Position-changing proposals bind to exact `position_ref` and
  `instrument_ref`; missing or mismatched references fail closed.
- TradingView event alerts are not treated as a price heartbeat. The cloud
  provider requires a distinct underlying-heartbeat table and an exact live
  option-contract relay.
- Paper order/fill persistence, lifecycle completion, execution provenance,
  and isolated paper cash/position ledger changes commit in one transaction.
- Missing execution prices remain `UNSCORABLE_EXECUTION_DATA`; they are not
  relabelled as ordinary unfilled orders.
- SEC dilution vetoes apply only to new, non-seed high-severity records inside
  the active 24-hour window.
- Roll reconstruction requires two independently priced legs.
- `/paper/health` exposes `active_experiment_id`,
  `authoritative_provider_ready`, `runner_ready`, and `blockers` without
  secrets or balances. UI controls require `runner_ready=true`.

## Verification

- Focused P2/P2A suite: 20 tests passed.
- Complete repository suite: 336 tests passed.
- `git diff --check`: clean.

## Activation blockers

The code must remain fail-closed until both cloud feeds exist and pass their
freshness checks:

1. `BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT`
2. `BLOCKED_NO_FRESH_OPTION_HEARTBEAT:<instrument_ref>`

The Blueprint is mounted by `webhook_receiver.py`. Every accepted heartbeat
causes a bounded event-driven runner tick, so no sleeping process or laptop
scheduler is required. The experiment activates atomically only after the AMC
underlying and every held AMC option have fresh exact 1-minute relays.

TradingView still requires one `UNDERLYING_HEARTBEAT` alert on AMC 1m and one
`OPTION_HEARTBEAT` alert for each held option contract, all pointing to the
existing `/webhook` URL. Until those alerts are configured and observed, the
UI remains locked and no proposal can execute.
