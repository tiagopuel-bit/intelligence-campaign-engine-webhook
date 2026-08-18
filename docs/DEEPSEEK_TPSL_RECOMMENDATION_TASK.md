# Task packet — DNA-recommended TP/SL levels (spec-then-build)

**Requested by:** Tiago, 2026-08-17. **For:** DeepSeek. Spec-then-build —
this feeds real capital-protection reasoning into the `set_bracket`
proposal flow (`docs/DEEPSEEK_MULTI_ASSET_AND_FIXES_TASK.md` item 4,
shipped tonight). Write the design doc, stop for review, same discipline
as every major feature tonight.

## What's being asked

The `set_bracket` approval lifecycle is fully built and shipped — proposal
→ approval → `upsert_bracket`, trigger/fill mechanics all correct. What's
missing: DNA doesn't suggest *where* the stop/target should sit. Tiago
wants DNA to recommend TP/SL levels grounded in the actual DNA read
(structural support/resistance, not arbitrary distances), sized
appropriately for the portfolio challenge's own risk framework.

## Reuse, don't duplicate — the building block already exists

`decision_engine.py`'s `suggest_trailing_stop()` (already used by the
manual `poll_and_recommend.py` CLI, never wired into `paper_execution`)
already does half of this correctly:

- `CampaignState.recent_support_price` — a real, tracked structural level:
  the close price at each timeframe's most recent bullish signal event
  (STRONG START/RELOAD/ADD/MANAGE). Not a guess, not synthesized.
- `suggest_trailing_stop()` picks the **tightest defensible support below
  current price** across timeframes, and enforces a strict discipline:
  only ever suggests raising a stop, never lowering it, and refuses to
  suggest anything while a cross-timeframe exit signal is already active
  (`synthesize_multi_timeframe_decision().action.startswith("EXIT
  SIGNAL")`).

**This function is built for *trailing an existing stop*, not proposing
the *initial* one.** It early-returns `None` if `position.current_stop is
None`. That gate needs to come off for the initial-suggestion case, using
the same `recent_support_price` mechanism.

**There is no equivalent for the target/resistance side yet** — this is
the actual new design work.

## What to design (spec, not code)

1. **Initial stop suggestion** — reuse `recent_support_price` the same
   way `suggest_trailing_stop()` does, but for the no-existing-stop case:
   the tightest defensible support below current price. State exactly how
   this differs from the trailing case (no "must already have a stop"
   gate, otherwise same discipline).
1a. **Trailing (ongoing) stop updates — explicitly in scope, not just the
   initial level.** Tiago confirmed this matters as much as the initial
   suggestion. `suggest_trailing_stop()` already works correctly today
   (tightest defensible support below price, only ever raises, refuses
   while a cross-TF exit signal is active) — it just isn't wired to
   anything. Design how a raised-stop suggestion becomes a real proposal:
   likely a `set_bracket` proposal against the *existing* active bracket
   (an update, not a fresh one — decide whether that's a new action
   variant or `set_bracket` with the bracket's ticker reused and the old
   one superseded on approval, mirroring how `upsert_bracket` already
   supersedes the prior ACTIVE bracket). State plainly whether this reuses
   existing `upsert_bracket` semantics as-is or needs a small extension.
2. **Target/resistance suggestion — the real new piece.** Propose a
   symmetric structural mechanism to `recent_support_price` but for the
   *upside*: candidates include (a) the price level of the nearest
   stretch-family event (`PEAK`/`MANAGE`/`PREMIUM` — the same "stretch"
   family from `CAMPAIGN_LIFECYCLE_SPEC.md` §3) above current price on
   any timeframe, (b) a risk-reward-derived target (e.g., a declared
   multiple of the stop distance — state the multiple and justify it, not
   an arbitrary round number), or (c) something else you find in the
   existing data. Evaluate options, recommend one, and be explicit that
   unlike the support side, there may not be an existing tracked field for
   this — say plainly if new tracking is needed and what it costs.
3. **"Adapted to our challenge goals"** — what this concretely means:
   should suggested position-level risk relate to the experiment's
   declared caps (`max_daily_paper_loss`, `single_contract_max_pct`,
   etc. — the same caps DS flagged as unenforced earlier tonight)? Should
   the reasoning text reference the campaign lifecycle stage the position
   is in (e.g., "ignition, tight stop" vs. "established campaign, wider
   trail")? Propose a concrete rule, don't hand-wave it.
4. **Trigger — when does DNA propose a bracket?** Options to evaluate: on
   every paper tick for any open position without an active bracket
   (matches Entry Discovery's on-tick pattern), only right after a new
   `open`/`add` fills (the position just changed, natural moment to set
   protection), or only on request. State the tradeoff and recommend one.
5. **Output shape** — a `set_bracket` proposal via the existing
   `create_proposal` path (reuse, per §4 of `ENTRY_DISCOVERY_SPEC.md`'s
   same reasoning for why reusing the real proposal machinery beats a
   separate candidate object). Reasoning text must state the real level
   and which timeframe/event it came from — same evidence-attribution
   discipline as `suggest_trailing_stop()`'s existing reason string.

## Grounded validation

Run the proposed initial-stop and target logic read-only against AMC's
current or recent real position/state and report what it would have
suggested — concrete numbers and their structural justification, not a
description of the method.

## Boundary

- Design/spec phase: read-only, no code, no proposal creation.
- Does not weaken any existing gate — a DNA-suggested bracket still goes
  through the exact same `PENDING_APPROVAL` → approval → `upsert_bracket`
  path as a manually-specified one. Nothing here changes `set_bracket`
  staying out of `VERY_HIGH_AUTO_ACTIONS`.
- Stop after the spec and grounded-validation report. Wait for review
  before any implementation.

## What to report back

The spec document plus the grounded-validation numbers — same bar as
every other spec tonight.
