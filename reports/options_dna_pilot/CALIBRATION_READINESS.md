# Options DNA Calibration Readiness — 2026-08-14

## Objective status

The architecture now separates all four required evidence layers:

1. audited underlying DNA state and event timing;
2. contract-specific OHLCV response and quality;
3. SEC catalyst availability and polling latency;
4. factual open-position context.

No production Options DNA guidance exists yet. No HOT, WEAK, ENTRY WINDOW,
MANAGE, PROTECT or EXIT WINDOW threshold is frozen.

## Verified locally

- `options_dna.py`: exact-timestamp option/underlying alignment; no gap filling;
  causal response, activity, range, retention and intrinsic/extrinsic facts.
- `options_dna_dataset.py`: 16-anchor AMC 15m fidelity pilot, split evenly
  across discovery/holdout and four DNA evidence families.
- `options_dna_catalyst.py`: separate SEC public-acceptance and operational
  first-seen clocks; future filings cannot leak; seed records cannot become
  live alerts; filings change urgency but claim no direction.
- `options_dna_catalyst_ledger.py`: coverage-aware historical joins. Missing or
  partial SEC history is `SOURCE_UNAVAILABLE`, never silently catalyst-free.
- `options_dna_position.py`: observation versus open-long-premium scope with
  entry, average cost, P&L, DTE, lifecycle, moneyness and observed premium
  composition.
- `options_dna_position_replay.py`: exact-entry simulated episodes that follow
  the same contract through later DNA events; causal snapshots and future
  paths remain physically separate.
- `options_dna_calibration.py`: discovery-only candidate fitting, equal weight
  per underlying anchor, immutable holdout evaluation and explicit independent
  sample minimums.
- The same module now freezes outcome-label quantiles separately by CALL/PUT,
  target DTE and target moneyness using DISCOVERY only. Duplicate anchors are
  rejected, thin cells remain explicitly unscored, and HOLDOUT can only receive
  the unchanged frozen definition.
- `options_dna_acceptance.py`: provider-neutral artifact gate for manifest and
  required-output completion, anchor/cohort identity, strict 15m bar ordering,
  OHLCV geometry, file/count/ticker coherence, and causal signal/post-decision
  coverage. Sparse bars remain sparse; they are never filled.
- `options_dna_targets.py`: future-only H1/D1/D3/D5/D10 matrix and six v1 path
  hypotheses frozen before expansion results. Right-censored paths retain
  audit status but cannot define numeric cutoffs.
- `options_dna_shadow.py`: deterministic observation identity, material-change
  deduplication and explicit `UNRELIABLE` / `FUTURE_DATA_REJECTED` / `EOD_ONLY`
  / `STALE` / `UNCALIBRATED` / `READY_FOR_SHADOW_RULES` gates. It cannot emit
  candidate labels before a frozen rule bundle exists.
- Full repository test suite: 248 tests passed on 2026-08-14, including the
  deterministic coverage-supplement planner and its fail-closed pool check.

## Pilot acquisition result

The corrected provider artifacts pass the structural acceptance gate for
fidelity review only: 44 contract rows / 28 unique tickers across 11 of 16
anchors. Exactly 33 rows contain the option signal bar and have scored causal
components plus next-open/high-low path outcomes; 11 remain explicitly
`UNSCORED_SIGNAL_BAR_ABSENT`. Five anchors had no eligible ATM contract and no
60-DTE cell was acquired. See `INDEPENDENT_ACCEPTANCE_AUDIT.md`.

This evidence is insufficient for calibration: comparable discovery cells
contain only one or two independent anchors, below the frozen minimum of 20.

The pilot position replay produces 11 exact-entry episodes and 91 ready
same-contract snapshots (455 future window rows). It proves the lifecycle
schema but is heavily CALL-skewed and far below the required 20 discovery / 10
holdout independent episodes in each CALL/PUT × 14/30-DTE cell.

The network-free expansion plan is now frozen at
`reports/options_dna_expansion/`: 92 anchors (60 discovery / 32 holdout),
balanced by evidence family, with CALL/PUT × 14/30-DTE exact-signal acceptance
minimums. AMC coarse-strike fallbacks are labeled as nearest regular strikes
and retain actual moneyness; they are never called ATM.
The expansion gate also requires complete historical SEC public-acceptance
coverage at every anchor and the future-only target matrix. Genuine
operational first-seen history remains a separate optional scenario.

`options_dna_guidance.py` now defines the shadow-only destination for accepted
rules. It rejects future-outcome leakage, catalyst-only direction, thin or
unstable validation cells, broad rules missing maturity/type evidence, scope
mismatches and imperative trade language. It emits auditable advisory states,
never prices, quantities or orders.

`options_dna_shadow_journal.py` supplies the research-only live record:
append-only material transitions, deterministic deduplication, causal time
ordering, future-field/order-payload rejection, and explicit readiness metrics
for coverage, duration, freshness and rapid advisory reversals. Promotion
readiness is evaluated separately for every required CALL/PUT × target-DTE
cell; missing metadata is unclassified and cannot satisfy a required cell.
Every unique decision remains available for coverage, but unchanged decisions
do not inflate transition counts. A true A→B→A return is retained as a distinct
journal event and contributes one reversal.
`options_dna_shadow_runner.py` is the provider-neutral build/evaluate/journal
boundary and performs no provider calls. No production database or route is
wired to either module yet.

The v1 shadow gate is frozen before expansion results at 3 contracts, 20
unique decisions, 20 calendar days, 10 transitions and 10 labeled observations
per CALL/PUT × 14/30-DTE cell, with maximum 20% ineligible observations and
20% one-step reversals. `scripts/report_options_dna_shadow.py` binds the
criteria hash, frozen bundle hash and journal evidence into one fail-closed
report. Passing this gate does not authorize production use.

## SEC catalyst checkpoint

The uncommitted SEC implementation supplies durable accession identity,
`acceptance_time`, `first_seen_at`, category and severity. First poll seeds
silently. This is sufficient for the causal catalyst contexts above, subject to
later Railway configuration and scheduling. Filing date alone is forbidden as
an intraday timestamp.

## Historical-data gate

DeepSeek owns the Massive pull. The 92-anchor expansion is now fully fetched,
assembled and structurally accepted: 318 component/outcome rows, 1,590 target
windows, 73 exact-entry position episodes and 901 causal snapshots. The audit
correctly exits 3 as `READY_FOR_REVIEW` because calibration coverage is not
ready; it does not fit or emit guidance.

Six of eight isolated-entry cells pass. `DISCOVERY PUT/30` has 18/20 and
`HOLDOUT PUT/30` has 8/10. Position replay is materially thinner: only
`DISCOVERY CALL/14` passes (25/20); the other seven cells remain below their
frozen 20-discovery / 10-holdout minima. There are 107 isolated
`SIGNAL_BAR_ABSENT` outcomes. Position replay rejects 141 snapshots for absent
signal bars, 57 entries for absent signal bars, and 32 entries because the
exact next option-bar open is absent. These are missing observations, not
right-censored successes and not permission to synthesize fills.

A deterministic coverage-only supplement is frozen in
`docs/DEEPSEEK_OPTIONS_DNA_SUPPLEMENT_HANDOFF.md`. It proposes 70 unused
underlying entry/continuation anchors (40 discovery, 30 holdout), evenly spaced
inside the unchanged 2026-02-01 seal without consulting option availability or
future outcomes. The preview produces a combined 162-anchor plan while keeping
the original 92-anchor plan separately identifiable.

This supplement should clear the isolated-entry deficits and may clear most
position cells, but `DISCOVERY PUT/30` is a declared feasibility risk. Its
observed exact-entry yield is 2/30; at that rate its 18-episode deficit would
require roughly 270 additional anchors, while only 133 unused discovery
entry/continuation events exist. If the bounded supplement remains deficient,
the process stops for a new calibration-design decision. It must not silently
delay fills, lower minima, select contracts from future prints, or fit targets.

### Combined-supplement review

The supplement completed with 162 total anchors. All eight isolated-entry
cells now pass their frozen minima. Position replay remains incomplete:
`DISCOVERY PUT/30` has 5/20 and `HOLDOUT PUT/14` has 6/10. When Discovery and
Holdout must both pass for the same contract cell, only CALL/14 and CALL/30 are
complete for open-position research; neither PUT maturity is complete.

The calibration review therefore authorizes a separately implemented
**entry-only target-freeze stage** while leaving the original all-track gate
unchanged and all position-management/exit guidance blocked. The exact scope
is frozen in `docs/DEEPSEEK_OPTIONS_DNA_ENTRY_CALIBRATION_HANDOFF.md`. Further
ordinary AMC anchor expansion is not recommended; the remaining PUT evidence
requires a separately pre-registered, liquidity-aware multi-asset study.

## Live-shadow data gate

Massive documents Options Basic as $0/month with five calls per minute, two
years of history, minute aggregates and **end-of-day data**. Therefore:

- historical intraday contract calibration is supported within the entitlement;
- live underlying DNA and SEC catalyst monitoring can run intraday;
- live intraday contract-response transitions cannot be validated from this
  entitlement and must remain `OPTION DATA EOD / NOT LIVE`;
- an EOD option observation cannot trigger an intraday HOT, DRAIN, MANAGE or
  EXIT-window claim.

Authoritative plan reference:
https://massive.com/pricing?product=options

This is not a request to upgrade. The cloud-only/free-plan constraint remains
in force. A future live source must be separately authorized and evaluated for
freshness, licensing and coverage before the live-shadow gate can pass.

## Next evidence sequence

1. Implement the separate entry-only target-freeze stage without weakening the
   original all-track position gate.
2. Freeze the six predeclared v1 entry outcome hypotheses from DISCOVERY
   numeric quantiles and apply them unchanged to HOLDOUT. Right-censored values
   cannot define a target.
3. Search transparent entry candidates on discovery, evaluate unchanged on
   holdout, and reject unstable cells.
4. Pre-register a liquidity-aware multi-asset position-replay study before
   collecting additional PUT management evidence.
5. Keep all position-management, protect, roll and exit guidance blocked until
   its required cells pass.
6. Shadow underlying/catalyst navigation immediately; keep contract state EOD
   until a sufficiently fresh option source is proven.
7. Only after live transition fidelity passes may validated, advisory wording
   enter the production Asset Page.
