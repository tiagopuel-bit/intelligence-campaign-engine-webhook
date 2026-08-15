# Task packet — DNA Trader (AI × Human Fusion) next steps

**Requested by:** Tiago, 2026-08-15. **For:** DeepSeek. Four parts, do them
**in order** — stop and report after Part 1 before continuing, since Part 1
is the one that's actually AMC-relevant right now; Parts 2-4 are worth
scoping but lower urgency.

"DNA Trader" / "AI × Human Fusion on decision" is Tiago's working name for
this whole thread — the AMC paper challenge plus the research that directly
serves it. Keeping it here so the name has one home; not a rebrand of
anything else in the repo.

## Part 1 — Execute the Position-Replay Coverage Protocol (AMC-relevant)

`reports/options_dna_replication/position_replay_coverage_protocol.md` is a
**design-only** draft (explicitly: "No provider requests, no execution").
Its objective is directly AMC-relevant even though its data source is other
assets: AMC's own PUT cells fail the position-replay gate for liquidity
reasons (`DISCOVERY PUT/30` 5/20, `HOLDOUT PUT/14` 6/10), which is *why*
position-management/exit/protect/roll guidance for AMC options stays
`BLOCKED_INSUFFICIENT_REPLAY_COVERAGE` today. This protocol is the
pre-registered plan to actually close that gap.

**Before requesting anything new from the provider:** check whether today's
external replication fetch (`reports/options_dna_replication/contracts/`,
370/384 anchors across SPY/TSLA/GME/U/RBLX/PYPL/LULU/VALE) already covers
enough of what this protocol needs. The asset list is identical. If it's
reusable, this could be materially cheaper than a fresh fetch — check before
assuming a new ~2.5h fetch run is required.

Execute per the frozen protocol: `{CALL, PUT} × {14, 30}` DTE cells,
`ENTRY_FORMING`/`CONTINUATION` episode origins only, exact next-bar-open
execution, the stated liquidity eligibility gates and acceptance minima
(≥20 Discovery / ≥10 Holdout episodes per cell per asset). Do not borrow the
frozen `CALL/14` entry candidate as an exit/roll/protect/manage rule — this
is explicitly a separate track per the protocol's own header.

Report per-asset, per-cell results honestly, same discipline as today's
replication report — including every cell that resolves to
`CONTRACT_DATA_UNRELIABLE` or fails the acceptance minima. This is a
coverage study; it does not itself authorize any new exit/roll/protect
threshold. If coverage now looks sufficient somewhere, say so and stop —
threshold design is a separate, later authorization.

**Stop here and report before continuing to Part 2.**

## Part 2 — Options quote-source evaluation (research only)

Massive's free plan has no real-time bid/ask, which is the documented
weak point in the "execution quality" `VERY_HIGH` evidence root. Research
and compare 2-3 realistic options for a better options quote source —
e.g. a paid Massive/Polygon tier, Tradier's paper-trading quote API, IBKR
paper API, or similar. For each: cost, latency/freshness characteristics,
what evidence root(s) it would actually strengthen, and integration effort.

**This is a comparison document only.** Do not sign up for anything, do not
add any credential, do not integrate a new provider, do not spend any money
or commit to a vendor. That decision is Tiago's alone. Output:
`docs/OPTIONS_QUOTE_SOURCE_EVALUATION.md`.

## Part 3 — Independent auditor pass on paper_execution safety gates

The P2A independent review already caught a real fail-open bug before it
shipped (status set to `PAPER_EXECUTED` without an actual order/fill
record). Do another pass in that same spirit — assume the code is trying to
hide a bug from you and try to find it. Focus areas: kill-switch
enforcement (both global and per-position, including the still-unrouted
`set_kill_switch` from the P3 report), approval-window expiry edge cases,
concurrent/duplicate proposal handling, the two-leg roll atomicity, and
anything that could let a proposal execute without every `VERY_HIGH` root
actually passing. Write findings to
`reports/amc_paper_execution/AUDIT_PASS_2026-08.md`, whether or not you find
anything — a clean pass is itself a useful record. No code fixes in this
pass unless something is actively dangerous; if so, stop and report before
fixing.

## Part 4 — Runner/uptime monitoring (design + read-only detection only)

Once P4 activates, the scheduled runner makes unattended decisions on a
10-minute clock with no current alerting if it silently stops. Scope (don't
build the phone-alert delivery — that's already wired up on Claude's side
via `scripts/paper_alert_check.py` and a local `/loop`; this part is just
the detection logic DS can own):

- what "the runner is healthy" should mean, precisely (e.g. a heartbeat
  timestamp column, a `last_run_at` field on the experiment/runner state);
- a read-only way to detect runner staleness (e.g. "no completed tick in
  the last N minutes during market hours") — likely a new read-only field
  on `/paper/health` or a new lightweight endpoint;
- do not build the actual notification delivery mechanism — just the data
  Claude's existing check script would need to detect and report staleness.

This can stay design-level if implementation would touch `paper_execution/`
write paths in a way that needs separate authorization — if so, write the
design and stop, same boundary as everything else today.

## Boundaries (same as every task today)

- Options DNA multi-asset entry research stays parked — Part 1 reuses that
  data but does not reopen the `CALL/14` promotion question.
- No broker credentials, no real orders, no live execution path, ever.
- No commit/push required from you — hand back for review.
- If Part 1's findings suggest touching `paper_execution/` write paths to
  actually improve exit guidance, stop and report first — that's a new
  authorization, not something this packet grants.
