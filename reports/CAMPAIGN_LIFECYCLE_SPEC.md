# Campaign Lifecycle — Design Spec (Ignition → Establishment → Resolution)

**Status:** design/spec phase. Read-only against existing data; no code changed.
Advisory/dashboard-only — this does **not** feed `paper_execution` `VERY_HIGH`
roots or any execution path, and nothing touches Pine/TradingView/webhook
ingestion. This spec stops before any implementation and waits for review.

## 0. What this formalizes

Three hand-traced chart walkthroughs (TSLA live; CHWY manual; both per the task
brief) reduce to the same three-beat shape: a quiet higher timeframe, a first
flicker on the lower timeframes, a sustained clean run, then one of three
distinct endings. The hard part is that *which* timeframes are clean is not the
same set per ticker, so the model must be per-asset rather than hardcoding one
tier-weighting.

## 1. Closed vocabulary

| kind | token | meaning |
|---|---|---|
| stage | `idle` | no active cycle |
| stage | `ignition` | first lower-tier entry flicker while higher tiers are quiet |
| stage | `establishment` | sustained clean lower-tier run, not yet resolved |
| stage | `resolved` | the cycle ended |
| resolution | `cascade_up` | a higher tier confirmed (campaign graduated) |
| resolution | `fail_cluster` | multiple lower tiers failed together (breakdown) |
| resolution | `stretch_cluster` | multiple lower tiers stretched together (take-profit, not necessarily campaign-ending) |

No free text, no synthesized score. Each stage is a discrete condition, matching
the "warming up" flag's design principle (a real `signal_event` fired, recently).

## 2. Fields read (exact)

From `GET /state_all/<symbol>` → `states[]`:

- `timeframe` (`"3" "5" "15" "30" "60" "120" "180" "240" "D" "W"`)
- `signal_event` (fresh entry signal, e.g. `STRONG START` / `RELOAD` / `ADD`)
- `recent_event` (last classified event)
- `phase` (DNA phase label)
- `bar_time` (epoch-ms or ISO)

Only these. `health`/`confidence`/`exhaustion_warning` are **not** consumed by
the stage detector (they stay in the existing campaign-condition read).

## 3. Event families (deterministic)

| family | events | tone |
|---|---|---|
| `entry` | STRONG START, CAMPAIGN START, FIRE ADD, ACCUMULATE, IGNITION, ADD, RELOAD | pos |
| `entry_test` | START TEST, IGNITION TEST | pos (test) |
| `stretch` | PREMIUM, PEAK, MANAGE | warn |
| `fail` | FAIL (any severity) | neg |
| `fail_test` | FAIL TEST | neg (shakeout) |

## 4. Tier model

| tier | timeframes | role |
|---|---|---|
| backbone | D, W | direction |
| owner | 180, 240 | campaign |
| confirm | 60, 120 | confirmation |
| timing | 15, 30 | timing |
| micro | 3, 5 | right now |

Backfilled replays carry `5m, 15m, 30m, 1H, 2H, 3H, 4H, 1D` (no 3m, no W);
the live ladder adds 3m. The detector reads whichever timeframes exist.

## 5. Stage detection (state machine)

### Ignition — `idle → ignition`

All of:
1. a **timing** tier bar (`15m` or `30m`) fires an `entry` event; **and**
2. the **micro** tier (`5m`) fired `entry` or `entry_test` within ±15 min of it
   (lower-tier alignment — one 15m bar alone is not ignition); **and**
3. the higher tiers are **quiet**: no `entry`/`stretch`/`fail`/`fail_test` on
   confirm within the last 4h, owner 6h, backbone 12h.

Ignition is deliberately one step *earlier* and *broader* than the existing
"warming up" flag: warming-up requires the campaign (owner) tier to already be
pos; ignition only requires the higher tiers to be *not yet reacting*.

### Establishment — `ignition → establishment`

The ignition **holds** when, within the next 4 timing bars (~1h), the timing
tier fires another `entry`/`entry_test` without a resolution firing. "Sustained
clean run" means exactly this: repeated constructive timing prints, with a
single-tier `fail_test` (shakeout) or `stretch` (extension warning) allowed as
normal texture — a single tier printing is noise; a *cluster* is a resolution
(§6).

### Resolution — `ignition/establishment → resolved`

Within an 8-hour window from ignition, the first of:

- `cascade_up` — a **confirm/owner/backbone** tier fires an `entry` event.
- `fail_cluster` — ≥2 distinct lower tiers (`{5m,15m,30m}`) fire `fail` or
  `fail_test` within a 30-min cluster window.
- `stretch_cluster` — ≥2 distinct lower tiers fire `stretch` within a 30-min
  window.

After resolution (or the 8h window laps with no cluster), the cycle resets to
`idle`.

### Precedence (single-bar tiebreak)

1. `cascade_up` (higher-tier confirmation) wins.
2. `fail_cluster` beats `stretch_cluster` (breakdown is the more severe read).

## 6. "Cluster" and "simultaneous" — precise

A cluster is **≥2 distinct lower-tier timeframes** firing the same family, where
"simultaneous" means the two bars' `bar_time` timestamps are within **30
minutes** of each other. 30 min is the coarsest lower timeframe's bar span, so
a 5m print and a 30m print that both fall inside the same 30m window count as
one cluster; this sidesteps the fact that bars close at different times per
timeframe.

## 7. Per-asset reliability (the hard part)

**Decision:** v1 = a **per-asset static reliability mask**, precomputed from
backfill and stored as a data table (like `dna_term_dictionary.csv`), recomputed
manually when backfill is refreshed. Not runtime-recomputed.

**Metric:** for each timeframe, `agreement_rate` = the fraction of that
timeframe's *classified* bars whose tone (§3) matches the tone of the
next-higher timeframe at the same time. A timeframe is `reliable` when
`agreement_rate ≥ 0.50` **and** it has ≥ 50 classified bars (sample-size
floor). Unreliable timeframes are excluded from stage detection; their tier
read falls back to the tier's remaining reliable timeframes.

**Tradeoff stated explicitly:** a static profile is deterministic, cheap, and
free of runtime recompute hazards, but can drift as an asset's microstructure
changes; a periodically recomputed runtime profile stays adaptive but is
nondeterministic and adds a moving part. v1 picks static; a recompute cadence is
documented, not automated.

**Thin/new asset:** a timeframe with < 50 classified bars is `unreliable`; if
**no** timing timeframe is reliable, the lifecycle read degrades to `no-basis`
(no stage, no resolution), exactly the insight-library discipline — a
confident-sounding read with no real basis is forbidden.

**Grounded finding (honest limitation):** the 7 backfilled assets are uniform —
agreement rates run ~0.37–0.72 with no clear "noisy tier" (see table below), so
their masks are near-degenerate and the mechanism does not change their reads.
Its value is for TSLA/CHWY and future assets; it cannot be validated against
CHWY here because CHWY is not in the backfill.

## 8. Grounded validation (real flagged moments, 2-year backfill)

Ran the §5 rules read-only over `_deepseek_expanded_rerun_stage` backfill for
the 7 covered assets. (This used the all-reliable baseline; see §7.)

| asset | ignitions | cascade_up | fail_cluster | stretch_cluster | unresolved |
|---|---:|---:|---:|---:|---:|
| AMC | 115 | 6 | 8 | 1 | 100 |
| GME | 122 | 10 | 15 | 2 | 95 |
| PYPL | 116 | 8 | 2 | 1 | 105 |
| RBLX | 145 | 10 | 4 | 1 | 130 |
| SPY | 141 | 17 | 2 | 5 | 117 |
| VALE | 118 | 2 | 11 | 3 | 102 |
| U | 120 | 12 | 10 | 4 | 94 |

~115–145 ignitions per asset over two years ≈ one ignition every ~4–5 trading
days — a sensible "campaign leg" cadence, not a per-bar flicker. ~80% of
ignitions end **unresolved** inside 8h (single-tier fades that never form a
cluster). This is the honest headline: clean 3-way resolutions are the minority;
the model does not force a resolution where none fired.

**Most recent flagged moments per asset (UTC):**

| asset | ignition | cascade_up | fail_cluster | stretch_cluster |
|---|---|---|---|---|
| AMC | 2026-08-03 19:00 | 2026-08-03 19:00 | 2026-07-16 14:00 | 2026-05-29 15:45 |
| GME | 2026-06-11 17:30 | 2026-06-11 17:30 | 2026-04-06 16:30 | 2025-05-13 18:30 |
| PYPL | 2026-08-11 17:30 | 2026-08-11 17:30 | 2026-05-07 13:30 | 2024-11-13 17:15 |
| RBLX | 2026-08-04 15:45 | 2026-07-15 18:00 | 2026-08-04 15:45 | 2024-11-07 19:15 |
| SPY | 2026-07-30 13:30 | 2026-07-30 13:30 | 2026-03-25 13:30 | 2026-06-01 15:30 |
| VALE | 2026-07-27 16:30 | 2026-05-21 14:15 | 2026-07-27 16:30 | 2026-07-15 15:45 |
| U | 2026-08-10 18:45 | 2026-06-29 19:15 | 2026-03-16 14:00 | 2026-08-10 18:45 |

(Full per-asset lists were produced by the read-only probe; this table shows
the most recent of each type for review.)

### Reliability agreement rates (justifying §7)

| asset | 5m→15m | 15m→30m | 30m→1H | 1H→2H | 2H→3H | 3H→4H |
|---|---:|---:|---:|---:|---:|---:|
| AMC | .44 | .50 | .42 | .53 | .58 | .54 |
| GME | .46 | .47 | .49 | .43 | .53 | .60 |
| PYPL | .44 | .52 | .48 | .56 | .55 | .51 |
| RBLX | .47 | .44 | .43 | .51 | .72 | .45 |
| SPY | .47 | .48 | .52 | .53 | .58 | .54 |
| VALE | .43 | .47 | .37 | .42 | .58 | .51 |
| U | .45 | .46 | .45 | .48 | .57 | .54 |

The lower tiers sit right at the 0.50 boundary; the mask is genuinely
per-asset and the threshold is a v1 choice to revisit at review.

## 9. Open items for review (not implemented, not decided)

1. The 0.50 reliability threshold and 30-min cluster window are proposals; both
   need review against the two hand-traced cases before freezing.
2. The 8-hour resolution window and "unresolved" handling (should an unresolved
   cycle show a `faded` label instead of silently resetting to `idle`?).
3. Whether the 3m timeframe (live-only) should join `micro` for alignment.

## 10. Boundary

Read-only. No code, dashboard, or table changed; Pine/TradingView/webhook
ingestion/`paper_execution` untouched. This stops here for review — the
dashboard implementation is a separate, later authorization.
