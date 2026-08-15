# Options DNA Calibration Protocol v0.1

## Objective

Calibrate near-entry and near-exit navigation for options without issuing exact
orders. The underlying DNA remains the campaign authority; Options DNA measures
whether a specific contract is expressing that campaign cleanly, weakly, or
unreliably. Position context and catalysts determine urgency, not direction by
themselves.

## Decision stack

1. **Catalyst:** external event and its freshness/severity.
2. **Underlying DNA:** campaign, confirmation, timing, pressure propagation.
3. **Contract response:** relative response, participation, range, retention.
4. **Contract pressure:** DTE, moneyness, intrinsic/extrinsic composition.
5. **Position context:** entry, average price, size, P&L and strategy.
6. **Navigation:** bounded advisory state, never an automatic order.

## Causal and fidelity invariants

- RAW option and underlying bars only.
- A feature at bar `t` may use `t` and earlier bars; its baseline excludes `t`.
- Option bars are joined to the identical underlying timestamp. Missing option
  bars are never forward-filled because a missing bar may mean no qualifying
  trade.
- Percentage moves are not compared directly across contracts. Baselines are
  contract-, timeframe-, DTE- and moneyness-aware during calibration.
- No IV, Greek, spread, open-interest or quote claim is made from OHLCV.
- Modeled values, if added later, remain visibly distinct from vendor facts.
- A sparse/stale contract can only be `UNRELIABLE`, never `HOT` or `WEAK`.
- `HOT` is not an entry instruction; `HOT` and `EXHAUSTION RISK` may coexist.
- `DRAINED` is not synonymous with cheap.

## Free-plan evidence ledger

The first implementation produces components, not a combined score:

| Component | Definition at the active bar |
|---|---|
| `option_return` | Contract close-to-close log return. |
| `underlying_directional_return` | Underlying log return, inverted for puts. |
| `relative_response_residual` | Option return minus a causal rolling-beta expectation from the underlying. |
| `relative_response_z` | Residual standardized against prior residuals only. |
| `volume_ratio` | Current contract volume divided by prior active-bar mean volume. |
| `transaction_ratio` | Same calculation for aggregate transaction count when supplied. |
| `range_expansion` | Current high-low range divided by prior mean range. |
| `close_location` | Close location from zero (bar low) to one (bar high). |
| `vwap_distance_pct` | Close distance from aggregate VWAP when supplied. |
| `drawdown_from_high_pct` | Current close below the prior rolling premium high. |
| `dte` | Calendar days from bar date to expiration. |
| `moneyness_pct` | Direction-aware distance of underlying from strike. |
| `intrinsic_value` | Intrinsic value from underlying close and strike. |
| `extrinsic_value_observed` | Non-negative contract close minus intrinsic value. Not IV or theta. |
| `activity_ratio` | Matched active option bars divided by underlying bars in the lookback. |

## Data-quality gate

The ledger emits `ready=false` until all minimum causal-history requirements are
met. Quality reasons are explicit:

- insufficient matched history;
- sparse option activity;
- non-positive/invalid prices;
- zero underlying variance for relative response;
- invalid contract metadata.

Optional `vw` and `n` fields must remain optional. Their absence cannot corrupt
OHLCV analysis or be silently replaced with invented values.

## Candidate navigation vocabulary (not calibrated yet)

- `ENTRY WINDOW FORMING`
- `CONFIRMATION ACTIVE`
- `WAIT — CONTRACT NOT RESPONDING`
- `HOT DEVELOPING`
- `HOT CONFIRMED`
- `HOT, BUT CHASE RISK`
- `HOLDING PREMIUM`
- `WEAK RESPONSE`
- `PREMIUM DRAIN`
- `MANAGE — VERTICAL EXPANSION`
- `PROTECT — PRESSURE PROPAGATING`
- `EXHAUSTION / EXIT WINDOW DEVELOPING`
- `THESIS DAMAGED`
- `UNRELIABLE CONTRACT DATA`

These labels are hypotheses until historical replay and live shadow validation
establish thresholds and transition behavior.

## Historical calibration units

Use AMC calls and puts sampled across ITM/ATM/OTM and approximately 7, 14, 30,
60 and 90 DTE. Each observation must retain contract ticker, bar timestamp,
timeframe, DTE/moneyness bucket, underlying DNA state and catalyst state.

Forward outcome targets:

- maximum favorable and adverse premium excursion;
- direction-adjusted return relative to the underlying;
- time to premium peak/trough;
- gain retention after the first impulse;
- drawdown and recovery success;
- subsequent premium drain;
- underlying pressure propagation and campaign invalidation.

Before expansion results are inspected, v1 freezes six semantic path
hypotheses: early premium confirmation, confirmation failure, retained
expansion, giveback after expansion, persistent premium damage, and runaway
continuation. Their numeric cutoffs are discovery-cell quantiles rather than
fixed price percentages. Only fully observed windows may define those cutoffs;
right-censored paths keep their audit status but expose no calibration value.
The future target matrix is prohibited from any live or UI payload.

The signal bar close is the first known decision price; the next option bar
open is the executable research proxy. Path outcomes retain both baselines and
use only subsequent bar highs/lows for favorable/adverse excursion. They also
record the signal-close-to-next-open gap, whether the premium peak preceded the
trough, and peak-to-terminal giveback. This permits separate study of ordinary
cooldowns, poor peak-candle entries, and rare squeeze paths that never offer a
meaningful pullback.

Discovery and holdout periods must be separated before thresholds are frozen.
Outcome-label cutoffs are part of the frozen research definition, not a free
preprocessing choice. Define them from DISCOVERY path distributions within
comparable contract cells (CALL/PUT, target DTE and target moneyness), record
the exact quantiles and numeric cutoffs, and apply those cutoffs unchanged to
HOLDOUT. A cell with fewer than 20 independent discovery anchors remains
unscored. Multiple contracts from the same underlying anchor cannot count as
independent observations or alter a cell cutoff.

### Pilot acquisition design

The first bounded AMC pilot uses audited 15m RAW/RTH replay anchors and samples
four evidence families independently in discovery and holdout partitions:

- entry forming: STRONG START / CAMPAIGN START / IGNITION;
- continuation: ADD / RELOAD;
- risk or exhaustion: MANAGE / PEAK;
- thesis pressure: FAIL / FAIL TEST.

If multiple events print on one bar, thesis pressure has priority, then risk,
continuation and entry formation. `t_utc` is the source bar open; the signal is
not available until `decision_available_utc`, 15 minutes later. Outcomes begin
after that point. The pilot selects standard ATM calls and puts near 14, 30 and
60 DTE. Wider ITM/OTM cells are a later expansion after the pilot proves data
coverage and timestamp fidelity.

The 16-anchor pilot is a **fidelity and coverage gate only**. It is forbidden
from freezing navigation thresholds. `options_dna_calibration.py` requires at
least 20 independent discovery anchors and 10 independent holdout anchors by
default. Contract rows belonging to the same underlying event share equal
total weight, preventing a six-contract cohort from masquerading as six
independent market events. Candidate feature cutoffs and outcome-label cutoffs
are selected on discovery rows only; holdout values cannot influence their
threshold, direction, or the definition of a successful path.

### Catalyst clocks

SEC catalyst context keeps two explicitly separate causal scenarios:

- `PUBLIC_ACCEPTANCE` uses the SEC acceptance timestamp as the earliest public
  research clock. A compact timestamp without an offset is interpreted as SEC
  Eastern time.
- `OPERATIONAL_SEEN` uses `first_seen_at`, representing the first successful
  Railway poll that observed the accession. Seed records are excluded because
  initialization is not a live alert.

Historical results must name the clock used. Filing date alone is never a
valid intraday availability time. S-3 is financing capacity, not proof of an
immediate offering. All filing categories modify urgency only; market/DNA
evidence retains directional authority.

Historical catalyst joins also require an explicit source-coverage interval.
An anchor outside a declared complete interval is `SOURCE_UNAVAILABLE`, never
an inactive catalyst. Calibration expansion requires complete
`PUBLIC_ACCEPTANCE` coverage at every anchor. `OPERATIONAL_SEEN` is retained as
a separate optional historical scenario until genuine live `first_seen_at`
coverage exists; reconstructed polling timestamps are forbidden.

### Position context

Position context selects the navigation scope; it does not rewrite the market
state. With no open contract the scope is `OBSERVE_ENTRY`. A purchased CALL or
PUT is `MANAGE_OPEN_LONG_PREMIUM`. The factual ledger retains average cost,
current observed premium and its source, P&L, DTE, held days, lifecycle elapsed,
direction-aware moneyness and observable intrinsic/extrinsic composition.
P&L cannot turn weak evidence into confirmation, and a catalyst cannot turn a
losing position into a directional thesis.

Historical management/exit calibration uses a separate simulated-position
replay. Entry episodes originate only from predeclared ENTRY_FORMING or
CONTINUATION anchors and open at an option aggregate exactly matching the
underlying decision timestamp; the aggregate open is the research proxy.
Missing entry/snapshot bars are never shifted. The same contract is followed
at later audited DNA events for at most 21 calendar days. Causal snapshots
contain entry/current premium, unrealized return, elapsed underlying bars,
contract response/quality and underlying state; H1–D10 paths live in a
separate future-only ledger. The replay explicitly omits spreads, fees,
slippage, sizing, exercise and assignment and therefore cannot be presented as
verified trade performance.

### Shadow-mode freshness gate

Every shadow observation records the option bar's actual as-of timestamp,
entitlement, age, component-quality reasons, position scope and calibration
version. The allowed gates are `UNRELIABLE`, `FUTURE_DATA_REJECTED`,
`EOD_ONLY`, `STALE`, `UNCALIBRATED`, and `READY_FOR_SHADOW_RULES`.
`candidate_labels` remains empty before a frozen rule bundle exists. End-of-day
option data is never eligible for intraday guidance even when the underlying
DNA and catalyst feeds are current.

Frozen bundles are serialized with a deterministic content hash; a modified
rule file is rejected. Shadow observations enter an append-only research
journal only after their decision time. Unchanged polling states are deduped,
out-of-order observations are rejected, and stale/EOD/unreliable observations
cannot carry a label. The journal also rejects future outcome fields and label
payloads containing price, quantity or order data. Unique decisions count
toward coverage without automatically counting as transitions. Transitions
require a material gate/fact/advisory change, and a genuine A→B→A return is
stored rather than colliding with the first A state.

Shadow promotion uses explicitly supplied minimum unique decisions, calendar
days, labeled observations, maximum ineligible-data fraction and maximum
one-step advisory-reversal fraction **for every required CALL/PUT × target-DTE
cell independently**. An unobserved cell fails; missing cell metadata is kept
as `UNKNOWN:-1` and cannot satisfy another cohort's gate. There are no
convenient built-in defaults that could be chosen after seeing the shadow
results.

The live runner is provider-neutral: it accepts one already assembled causal
snapshot, applies the frozen shadow bundle, and appends only material changes
to the research journal. It performs no market-data request and therefore
cannot bypass entitlement, freshness, or component-quality gates.

Before expansion results, v1 freezes the live-shadow acceptance gate at three
distinct contracts, 20 unique decisions, 20 calendar days, 10 material
transitions and 10 labeled observations per required cell. No more than 20%
of recorded observations in a cell may be ineligible and no more than 20% of
material transitions may be one-step advisory reversals. These are minimum
evidence/stability requirements, not proof of economic value; historical
holdout preservation remains a separate prerequisite. The machine-readable
definition is `reports/options_dna_expansion/shadow_acceptance_criteria_v1.json`.

The earlier DNA Position Vocabulary library remains useful copy research, but
its fixed DTE bands and action mappings are not validated Options DNA rules.
They cannot bypass this protocol's discovery, holdout, freshness and live
transition gates.

`scripts/build_options_dna_dataset.py` defaults to a network-free plan. Its
`--fetch` mode is intended for an authorized Railway/worker environment with
`MASSIVE_API_KEY` already configured. It shares the production five-per-minute
limiter, caches each contract artifact, records partial failures, and never
writes the provider key. It does not modify the webhook database.

## Production gate

No combined Options DNA state enters the Asset Page until:

1. component ledger tests pass;
2. historical cohort coverage and censoring are documented;
3. state thresholds are frozen on discovery data;
4. holdout results preserve direction and acceptable stability;
5. live shadow observations demonstrate data freshness and transition fidelity;
6. guidance wording remains advisory and position-specific.

### Frozen shadow bundle contract

Validated historical rules enter shadow mode only through a versioned
`FrozenGuidanceBundle`. Every rule must carry discovery and unchanged-holdout
evidence for every CALL/PUT × DTE cell it can match. A broad rule cannot borrow
one maturity's evidence and silently apply to another. Catalyst-only or
position-only direction claims are invalid, and all future path fields are
prohibited from rule conditions.

The only candidate labels are advisory states: `ENTRY_WINDOW_FORMING`,
`PREMIUM_CONFIRMING`, `PREMIUM_NOT_CONFIRMING`, `MANAGE_ATTENTION`,
`PROTECT_ATTENTION`, and `EXIT_RISK_ELEVATED`. Position scope controls which
labels can appear. None may contain price, quantity, order, BUY, SELL, CLOSE,
ROLL or exercise instructions. When multiple validated states coexist, the
bundle returns a deterministic primary advisory while retaining supporting
rule/evidence identities for audit.
