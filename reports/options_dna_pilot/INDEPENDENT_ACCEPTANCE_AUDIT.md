# Independent Acceptance Audit — AMC Options DNA 15m Pilot

Status: **ACCEPTED FOR FIDELITY/COVERAGE REVIEW ONLY**  
Calibration status: **INSUFFICIENT EVIDENCE**

This audit supersedes the first assembly's close-only outcome and timestamp
claims. It does not accept any HOT, WEAK, ENTRY WINDOW, MANAGE, PROTECT or EXIT
WINDOW threshold.

## Corrections required by the independent audit

The first derived ledger used the older close-only outcome helper, treated the
first option bar at or after `decision_available_utc` as the decision bar, and
checked the underlying replay rather than the option series for signal-bar
existence. It also supplied only pre-matched underlying bars to the activity
calculation, which could mechanically inflate activity toward 100%.

The corrected assembly now:

- identifies the causal option bar only by exact
  `signal_bar_open_utc` equality;
- treats that completed bar as knowable at `decision_available_utc`;
- refuses to move an absent option signal bar to the next trade;
- gives the component ledger the full underlying history so activity measures
  option prints against the true underlying grid;
- uses next-bar-open and future high/low path outcomes;
- keeps future outcome columns out of the causal component ledger;
- distinguishes `UNSCORED_SIGNAL_BAR_ABSENT` from true right-censoring.

## Accepted artifact facts

- 16 planned underlying anchors; 11 acquired at least one eligible contract.
- 44 contract rows across 28 unique contract tickers.
- Balanced selected rows: 22 CALL and 22 PUT.
- 33/44 rows have the exact option signal bar and a causal component row.
- 11/44 lack the exact option signal bar and remain explicitly unscored:
  10 PUT rows and 1 CALL row.
- 33 path outcomes are scored and right-censored at contract expiry relative to
  the fixed 21-session horizon.
- 11 missing-signal rows are unscored, not relabeled as right-censored paths.
- No provider-entitlement left censoring was observed.
- No 60-DTE cell was acquired.
- Five anchors had no eligible ATM contract within the frozen tolerance.
- Among exact-signal rows, observed activity ratio ranges from 0.65 to 1.00
  (median 1.00); missing prints were not filled.

The provider-neutral gate reports `READY_FOR_REVIEW` with warnings for the 11
missing signal bars and no structural errors.

## Exact causal proof

For `AMC15-001`:

- underlying source bar opens `2024-08-23T15:15:00Z`;
- its DNA event becomes knowable when that 15m bar closes at
  `2024-08-23T15:30:00Z`;
- for `O:AMC240906C00005000`, the causal component `bar_time` is
  `1724426100000` (15:15), not 15:30;
- the next printed option bar opens at 15:30 and is the executable research
  proxy for the forward path;
- for the paired 14-DTE PUT, no 15:15 option bar exists, so both its component
  classification and path outcome are unscored.

## Why calibration remains prohibited

The pilot contains only five discovery anchors and six holdout anchors with any
selected contracts. Within comparable partition/family/CALL-PUT/DTE cells,
there are only one or two independent anchors—far below the frozen minimum of
20 discovery anchors per outcome cell and 10 holdout anchors for evaluation.
Contract rows sharing one underlying event are not independent samples.

The next historical pull must expand the anchor population and adapt the
contract selection protocol for AMC's coarse strike ladder without changing
the chronological discovery/holdout seal or choosing thresholds from holdout.

## Trading-clock outcome windows

The corrected assembly now also emits 220 long-form path rows at H1, D1, D3,
D5 and D10 horizons. Cutoffs come from subsequent underlying 15m trading bars,
not a fixed number of sparse option prints.

- H1: 32 scored windows, one exact-signal contract with no subsequent print,
  and 11 missing-signal rows.
- D1: 29 complete scored windows, four scored/right-censored windows, and 11
  missing-signal rows.
- D3/D5: 26 complete scored, seven scored/right-censored, 11 missing-signal.
- D10: 16 complete scored, 17 scored/right-censored, 11 missing-signal.

Late-2026 anchors are explicitly censored by the audited underlying replay end;
some D10 paths are censored by contract expiry. These windows establish the
right timing schema for near-entry, premium-drain and giveback research, but
the pilot counts remain far below calibration minimums.

## Future-only target matrix

The 220 window rows pivot deterministically to 44 contract-anchor rows. Fully
observed calibration values exist for 32 H1, 29 D1, 26 D3, 26 D5 and 16 D10
rows. All metrics are blanked in the matrix for right-censored or otherwise
unscored windows, preventing partial paths from defining discovery cutoffs.

Six v1 hypotheses were registered before expansion results: early premium
confirmation, confirmation failure, retained expansion, giveback after
expansion, persistent premium damage and runaway continuation. The last pair
explicitly distinguishes an ordinary peak/giveback exit-risk path from the
rarer squeeze-like path that continues without cooling. They are research
targets only; the pilot cannot freeze their numeric quantiles or produce a
guidance state.

## Simulated open-position replay

To avoid treating isolated per-timeframe entries as position navigation, the
same pilot contracts were replayed after exact next-bar-open entry through
later audited DNA events. The pilot yields 11 episodes, 91 exact-signal causal
snapshots and 455 separate future-window rows. All 91 snapshots pass component
quality; later missing option prints remain 47 explicit rejections rather than
being shifted.

Snapshot evidence is concentrated in THESIS_PRESSURE (62), with 16
CONTINUATION, 11 ENTRY_FORMING and two RISK_OR_EXHAUSTION observations. The
episode set is too small and CALL-heavy to calibrate management guidance. It
is accepted only as proof that entry price, unrealized position context,
contract response and later DNA state can be synchronized without mixing
future MFE/MAE/giveback into the causal ledger.
