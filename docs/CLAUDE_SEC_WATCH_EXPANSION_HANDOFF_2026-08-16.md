# Claude handoff — SEC filing watch expansion to the 7 portfolio assets (sentiment + push)

**Date:** 2026-08-16 (America/Los_Angeles). **From:** opencode session with Tiago.
**Purpose:** bring Claude up to date on what was decided/prototyped this session, and what needs a decision before it reaches production.

## What happened this session

- Looked at TradingView's AI Chart Copilot (video + TradingView blog). Verdict: it's a UI-only Chrome extension with **no public API**, so it cannot be wired into the project directly. The one reusable idea is "AI-summarize/classify SEC filings."
- Extended the scratch AMC poller (`~/Documents/Default Project/amc_poller.py`) into a **multi-asset SEC monitor** for the 7 portfolio assets.
- Added **sentiment classification** (`bullish`/`bearish`/`neutral`) alongside dilution detection — because an SEC filing can be a positive catalyst (Form 4 insider buying, 13D accumulation, buyback 8-K), not just dilution.
- Tiago chose **push** as the alert surface (over web dashboard / log file).

## The 7 assets (matches `DEEPSEEK_PORTFOLIO_MULTI_ASSET_SPEC_TASK.md`)

`AMC, GME, PYPL, RBLX, SPY, VALE, U` — AMC is the anchor (30% floor). MARA/TSLA/ARB are out of scope.

## What the prototype does (reference only — NOT production)

In `~/Documents/Default Project/amc_poller.py`:

- ticker → CIK resolution from SEC `company_tickers.json` (cached to `sec_cik_map.json`); all 7 resolve (verified).
- dilution detection on `424B5 / 424B3 / S-3 / F-3 / S-8 / FWP / S-1 / F-1`, plus share-count drift and >3% price-move signals.
- sentiment classification, two modes: AI-backed (OpenAI/Anthropic/Google, `--summarize`) returning `{summary, sentiment, reason}` JSON, or form-based fallback (dilution forms → bearish, `13D/13G` → bullish, else neutral).
- broadened form coverage for ADR/foreign/ETF issuers: VALE files `20-F/6-K`, SPY files `485BPOS/497`.
- per-ticker state in `sec_state.json`; first run seeds silently (no backlog alerts).
- verified: full `--once` run succeeds on all 7; dilution detection + sentiment heuristic unit-checked.

## Prototype vs production boundary (important)

- The prototype uses **yfinance + laptop-local JSON state + laptop polling** — all three are explicitly forbidden by the production SEC watch's non-negotiables (`docs/DEEPSEEK_SEC_FILING_WATCH_PROMPT.md`: cloud-only Railway+SQLite, no yfinance, no local state, no laptop daemon).
- Production SEC watch **already exists and is AMC-only**: `sec_filings.py` (`SYMBOL_TO_CIK` contains only `AMC`), `scripts/poll_sec_filings.py`, `tests/test_sec_filings.py`.
- Treat `amc_poller.py` as a **signal/requirements prototype**. The production path is extending `sec_filings.py` to the 7 symbols + adding sentiment + adding push.

## Decisions to carry forward

1. Multi-asset SEC watch over the 7 assets (aligns with the multi-asset spec).
2. Sentiment classification is wanted, AI-backed with a form-based fallback. This goes beyond the original SEC spec's "do not call every filing bearish" — see safety note below.
3. Push notifications for dilution/sentiment alerts. **Channel not yet decided.**

## Reconciliation with `DEEPSEEK_SEC_FILING_WATCH_PROMPT.md`

- That spec listed "email/SMS/push notifications" and "polling every tracked asset before AMC proven" as **out of scope** — this session now requests both.
- It also mandated: "Do not call every filing bearish" and "Form 3/4/5 are context only without transaction parsing." The prototype's heuristic only marks dilution forms bearish and `13D/13G` bullish; `3/4/5` and everything else stay neutral. The AI sentiment path is a higher-signal capability but must keep the same conservative framing (advisory only, never an entry/exit instruction).

## Open items needing a decision

1. **Push channel — decided 2026-08-16 (Tiago, via Claude session): no new
   push/phone channel for now.** Don't build a Telegram/Discord/email bot.
   Existing `paper_alert_check.py` → Claude `/loop` → phone path stays the
   only push surface.
2. **Fold into production now, or after the multi-asset spec lands? —
   decided: wait.** Specifically wait for Monday 2026-08-17's AMC
   activation to confirm clean (per `docs/MONDAY_ACTIVATION_RUNBOOK.md`)
   before reopening the SEC-watch expansion. It also still rides behind
   `reports/PORTFOLIO_MULTI_ASSET_SPEC.md` review — DS is finishing the
   spec's missing auto-entry-policy section
   (`docs/DEEPSEEK_PORTFOLIO_SPEC_FOLLOWUP_AUTOENTRY.md`) now.
3. **Sentiment LLM provider/key** — none configured yet, still open,
   not urgent given items 1-2 are deferred.

## Uncommitted state at handoff (not from this session)

- Modified: `positions.py`, `tests/test_webhook.py`, `ui/dna_dashboard.html`, `webhook_receiver.py`.
- Untracked: `docs/DEEPSEEK_PORTFOLIO_MULTI_ASSET_SPEC_TASK.md`, `docs/DEEPSEEK_TSLA_BACKFILL_RETRY_TASK.md`, `reports/PORTFOLIO_MULTI_ASSET_SPEC.md`.

## Boundaries

- Nothing from this session modified the DNA repo except this handoff file. All prototype code lives in `~/Documents/Default Project/`.
- No commits, no deploy, no Railway changes made or requested by this session.
