# Position-Replay Coverage Protocol — Draft (R0, design only)

**Status:** pre-registration draft. No provider requests, no execution. This
draft is a separate track from the entry replication and must not borrow the
CALL/14 entry candidate as an exit, roll, protect or manage rule.

## Objective

Design a pre-registered coverage protocol for open-position navigation across
CALL/PUT × 14/30-DTE cells, preserving each asset independently. It addresses
the frozen AMC finding that PUT cells fail the position-replay gate for
liquidity reasons, without lowering that gate.

## Scope

- Cells: `{CALL, PUT} × {14, 30}` DTE.
- Assets: `SPY`, `TSLA`, `GME`, `U`, `RBLX`, `PYPL`, `LULU`, `VALE` (AMC is
  provenance only and is excluded from the new sample).
- Episode origins: `ENTRY_FORMING` and `CONTINUATION` only (the two permitted
  open-position origins).
- Execution: exact next option-bar open; no shifted/synthetic fill.

## Liquidity eligibility gates (frozen before outcomes)

A cell is eligible for a position episode only when it meets, at the decision
timestamp and causally:

- exact signal-bar presence and exact next-bar open presence;
- minimum matched causal history and activity ratio;
- non-zero actual movement at entry and at each later snapshot;
- standard 100-share contract status and the existing selection policy.

Sparse cells resolve to `CONTRACT_DATA_UNRELIABLE`; they never receive borrowed
guidance from a different maturity or contract type.

## Chronology and independence

- Global `2026-02-01` Discovery/Holdout seal, unchanged.
- Independent unit: one episode per underlying anchor per asset.
- Clustered events deduplicated deterministically before selection.

## Acceptance minima (to be finalized at the execution authorization, before
any outcome is inspected)

- ≥20 independent Discovery episodes and ≥10 Holdout episodes per cell per
  asset.
- Per-asset visibility retained; no pooling that hides per-asset failure.
- Asset-balanced pooled estimator for generalization only.

## Out of scope

No exit, roll, protect or manage thresholds are defined or fit at R0. This
draft only freezes the coverage/liquidity design that a later authorized round
would execute.
