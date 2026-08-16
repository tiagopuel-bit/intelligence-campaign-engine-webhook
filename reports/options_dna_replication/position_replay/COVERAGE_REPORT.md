# Position-Replay Coverage Protocol — Execution Report (2026-08-15)

Frozen design (`position_replay_coverage_protocol.md`) executed on the eight
non-AMC assets. Cells: `{CALL, PUT} × {14, 30}` DTE; episode origins
`ENTRY_FORMING`/`CONTINUATION` only; exact next-option-bar-open execution; no
borrowing of the frozen `CALL/14` entry candidate as any exit/roll/protect/
manage rule. No thresholds were designed or fit — this is coverage only.

## Headline result

```
cells passing: 2 of 32  →  TSLA:CALL/30 (20 discovery / 11 holdout),
                            TSLA:PUT/30  (20 discovery / 11 holdout)
all other 30 cells fail the >=20 discovery / >=10 holdout minima
```

**The multi-asset sample does not close AMC's PUT position-management gap.**
PUT cells are structurally sparse on nearly every asset — the PUT liquidity
problem is not AMC-specific. Only TSLA's 30-DTE cells clear the gate.

## Reuse of today's entry-replication fetch

Checked before any new request, as instructed:

- **Reused (no re-fetch):** option bars for `CALL/14` tickers already cached by
  the entry replication (160 bar cache hits), plus the underlying audited 15m
  replays for all eight assets.
- **Not reusable:** 30-DTE contract chains (the entry fetch stopped at
  `max_dte=17`), and all `PUT/14` / `CALL/30` / `PUT/30` bars (never selected
  by the entry run, which was `CALL/14`-only).
- **Anchor supply:** the entry plan had 16 discovery / 8 holdout entry-origin
  anchors per asset — below the ≥20/≥10 minima — so a denser entry-origin
  sample was required regardless of data reuse.

## Anchor plan (`anchor_plan.csv`)

- 368 anchors: 15 discovery + 8 holdout per entry family
  (`ENTRY_FORMING`, `CONTINUATION`) per asset → 30 discovery / 16 holdout per
  asset × 8 assets.
- Chronologically sealed at `2026-02-01`; deterministic evenly-spaced sampling;
  no option-availability or outcome consulted during selection.

## Fetch summary

| Metric | Value |
| --- | --- |
| Cohort rows | 1,368 (368 anchors × up to 4 cells) |
| Unique tickers | 1,316 |
| Reference requests (contracts) | 338 |
| Bar requests | 1,156 |
| Bar cache hits (CALL/14 reuse) | 160 |
| Failures | 23 (all `SPY` `contracts` stage, "rate limited after retries") |

## Assembly / episode summary

| Metric | Value |
| --- | --- |
| Position episodes | 409 |
| Rejections | 2,738 |
| — ENTRY_SIGNAL_BAR_ABSENT | 728 |
| — EXACT_NEXT_BAR_OPEN_ABSENT | 231 |
| — SNAPSHOT_SIGNAL_BAR_ABSENT | 1,779 |

Exact-execution yield is ~30% (409 episodes / 1,368 cohort rows). The dominant
loss is the exact-signal-bar gate: for illiquid options the contract simply
does not print on the underlying's exact 15m decision bar.

## Per-asset, per-cell coverage (`coverage_by_cell.csv`)

Minima: ≥20 discovery / ≥10 holdout episodes.

| Asset | CALL/14 | CALL/30 | PUT/14 | PUT/30 |
| --- | --- | --- | --- | --- |
| TSLA | 20 / 8 | **20 / 11 ✓** | 20 / 8 | **20 / 11 ✓** |
| SPY | 16 / 1 | 19 / 1 | 17 / 1 | 20 / 1 |
| PYPL | 20 / 6 | 14 / 4 | 10 / 2 | 7 / 1 |
| GME | 16 / 10 | 13 / 5 | 5 / 5 | 4 / 1 |
| U | 9 / 1 | 4 / 2 | 1 / 0 | 0 / 0 |
| RBLX | 8 / 2 | 7 / 3 | 5 / 2 | 1 / 1 |
| LULU | 13 / 2 | 7 / 4 | 2 / 3 | 4 / 1 |
| VALE | 1 / 2 | 2 / 2 | 1 / 0 | 1 / 1 |

(Each entry is `discovery / holdout` episode counts.)

## Insufficient-data cells (explicit)

- **Every cell except TSLA CALL/30 and TSLA PUT/30** fails at least one frozen
  minimum.
- **PUT/14** — the cell AMC actually needs for its 14-DTE PUT gap — reaches 20
  discovery only for TSLA, and its holdout never exceeds 8 (min 10). No asset
  passes PUT/14.
- **PUT/30** — TSLA passes; SPY reaches 20 discovery but 1 holdout; every other
  asset is ≤7 discovery (VALE 1, U 0, RBLX 1).
- **SPY holdout = PENDING (data-completeness, not a coverage verdict).** All 23
  fetch failures were `SPY` contract references ("rate limited after retries").
  SPY's discovery cells are otherwise healthy (16–20), but its holdout resolves
  to 1 episode because ~15 of 16 SPY holdout anchors never received a contract
  chain. Per the user's direction this session, SPY is left **pending** rather
  than re-fetched; its true holdout coverage is unmeasured until the SPY
  contract-reference rate-limiting is resolved.

## Conclusion

1. Multi-asset position-replay coverage is **not sufficient** to authorize
   AMC exit/roll/protect/manage research on the PUT side: only TSLA 30-DTE
   (both types) clears the gate, and the PUT cells that motivated this study
   (14-DTE in particular) are sparse on all eight assets.
2. The PUT sparsity is a **general liquidity property**, not an AMC-specific
   defect — the same exact-signal filtering that failed AMC PUT/30 also fails
   VALE, U, RBLX, LULU and GME PUT cells here.
3. SPY holdout remains **pending** due to contract-reference rate-limiting.
4. No exit/roll/protect/manage threshold was designed, fit, or authorized by
   this run. Threshold design is a separate, later authorization and is not
   implied by any cell that happened to pass.

## Files

- `reports/options_dna_replication/position_replay/` — `anchor_plan.csv`,
  `manifest.json`, `contracts/`, `cohort_ledger.csv`, `failures.json`,
  `position_episode_ledger.csv`, `coverage_by_cell.csv`, `coverage_report.json`,
  and this report.
- New scripts: `scripts/plan_position_replay_coverage.py`,
  `scripts/build_position_replay_coverage.py`, and
  `options_dna_position_replay_acquisition.py`.
- Production, Pine, webhook ingestion, `paper_execution/` and broker paths were
  not modified. No commit/push.
