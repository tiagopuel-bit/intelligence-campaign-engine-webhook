# Progress log — 2026-08-13 (dashboard UI session)

For GPT (frontend) and DeepSeek (backend/data) to catch up. Everything below
happened in `webhook/ui/dna_dashboard.html` unless noted. See
`docs/UI_HANDOFF.md` for the full API surface and dashboard structure this
builds on — that doc is still accurate, this is a delta on top of it.

## Deploy status — READ THIS FIRST

`/dashboard` on Railway (added earlier today, see commit `15e6c8c`) is
serving an **older** build. Four commits below landed on `main` after that
route went live and have **not** been deployed:

```
15e6c8c Serve dashboard at GET /dashboard from the deployment
4b9b363 Track one selected holding at a time on the chart + Position Insight panel
45e36a8 Adopt the DNA Asset Intelligence artifact's color palette; hold positions sort first
e6f7936 Add a manual light/dark theme toggle
```

Plus one more commit landing right after this log (see "In progress" below).
**Someone needs to run `railway up` from `webhook/`** to catch Railway up —
Tiago is handling the GitHub App reconnect (which would make this automatic
going forward) but that doesn't retroactively deploy what's already pushed.
Until then, `file://` locally on a fresh `git pull` and the live `/dashboard`
URL will show different things.

## Shipped and pushed (commit-by-commit)

1. **`4b9b363` — One holding tracked at a time.** Position Insight used to
   print a block for every open holding on an asset simultaneously. Now it
   tracks exactly one — click a row in Shares/Options and both the chart's
   entry marker and the insight panel narrow to just that holding.
   Auto-picks when there's only one holding total; prompts "click one below"
   when there's more than one and nothing's selected. Click the same row
   again to deselect. Verified against two real POSTed test positions
   (100 shares + a $3 CALL) on AMC locally.

2. **`45e36a8` — Color palette + ordering.**
   - Swapped the light/dark palette (both `prefers-color-scheme` and the
     `data-theme` overrides) for the one from the published "DNA Asset
     Intelligence" design artifact — deep green-black dark, soft mint-white
     light, same teal accent family. Same CSS variable names throughout
     (`--ink`, `--surface`, `--accent`, `--positive`, `--warning`,
     `--critical`, etc.) so no other CSS rule needed to change. `--accent2`
     isn't in the artifact's variable set (used for the Shares/Options
     section headings here) — it's a hand-picked darker/lighter shade of the
     same hue, not a literal artifact value.
   - Asset list ordering: assets you actually hold a position in now sort
     first, then by urgency, then name — previously urgency-only, so a held
     asset with "nothing to do" could get buried under unrelated cards.
     Verified by inserting a synthetic held asset (`ZZZ`, alphabetically
     after AMC and not otherwise held) and confirming it sorted above AMC.

3. **`e6f7936` — Manual light/dark toggle.** The `data-theme` CSS overrides
   existed but nothing wired them up — the page only ever followed the OS
   setting. Added a ◐ button next to Load that cycles
   system-default → opposite-of-OS → the other explicit theme, persisted in
   `localStorage` (`dna_theme`). Verified: forcing the browser to dark, one
   click flips to light and a reload keeps it.

## In progress — committed by the time DS/GPT read this, verify assumption

Three more asks landed together, not yet committed as of this log:

1. **"Campaign insights" restyle + reorder.** `renderPositionInsights` used
   to render in its own `.insight-block` style, positioned right after the
   chart. Renamed to "Campaign insights", restyled to match the "What to
   do" `.action` card language (icon + title + text, tone-colored via
   `primary.tone` → critical/watch/opportunity), and moved to sit directly
   above "What to do" (after "The flow", before the actions list) instead of
   living up by the chart. The old `.insight-wrap/.insight-block/etc.` CSS
   was deleted (dead code) in favor of reusing `.stage-head`/`.actions`/
   `.action`/`.no-actions`, which already existed for "What to do".

2. **Chart timeframe fix.** `drawChart` always opened on the shortest
   timeframe with data (usually 3m/5m) — if your entry was days or weeks
   old, it fell off the left edge of an ~80-bar 3m window and was
   invisible. Now:
   - It computes the same "which holding is selected" pick used by Campaign
     Insights *before* loading bars, and auto-widens through the available
     timeframe ladder (still shortest-first) until the entry's timestamp
     actually falls inside the loaded bar range, instead of always stopping
     at the first timeframe that has any data.
   - Added manual timeframe toggle buttons above the chart (one per
     timeframe this asset actually reports, e.g. 5m/15m/1H/4H/D) so you can
     override the auto pick yourself. Persisted per-symbol in
     `chartTfOverride`; click the active button again to go back to auto.

3. **Colored phase pills on the raw table.** The "Every timeframe, raw"
   table's Phase column was plain text. Now it's a rounded pill badge,
   colored via the existing `phaseTone()` red/amber/green/gray mapping
   (same tone logic already used for the flow-step chips elsewhere), and the
   `<details>` wrapper defaults to `open` now instead of collapsed. Row
   order flipped to ascending (shortest timeframe first) to match the
   reference screenshot Tiago shared.

**Verification status on this batch:** in progress when this log was
written. Restyle + reorder (#1) and phase pills (#3) are straightforward DOM
output changes with no async dependency, low risk. The chart timeframe
auto-widen (#2) is the one that actually needs live verification — it was
being tested against mocked `/ohlc` responses across multiple timeframes
(5m/15m/1H/4H/D, using synthetic AMC alert rows temporarily inserted then
removed) when a browser fetch-mock issue interrupted the check (mock stopped
intercepting after a page reload — needs a fresh look, not a logic problem
as far as the code trace shows). If you're picking this up: re-verify #2
specifically before trusting it, the code path is more complex than the
other two.

## Notes for DS specifically

- Roll-candidate suggestion (`suggestRollCandidate`) was independently
  verified against real chain data earlier today — confirmed correct
  (nearest further-OTM same-type contract, prefers same-expiry, only fires
  on bullish tone). No action needed there.
- No backend/schema changes in any of today's work — everything above is
  `dna_dashboard.html` only.
