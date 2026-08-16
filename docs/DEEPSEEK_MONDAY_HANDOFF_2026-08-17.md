# Handoff — DS covers Monday market open

**From:** Claude, 2026-08-16 evening. **For:** DeepSeek. Tiago expects to be
low on Claude tokens until midday Monday (2026-08-17), so DS is covering the
market-open activation watch instead of Claude.

## What to do

Follow `docs/MONDAY_ACTIVATION_RUNBOOK.md` exactly — it was written for
precisely this handoff. Short version: poll `GET /paper/health` starting
around/after 9:30am ET, watch the blockers clear in order (underlying
heartbeat first, then each option instrument), confirm
`authoritative_provider_ready` and `runner_ready` flip as expected, and
know the runbook's explicit stop-and-report triggers — don't improvise past
those.

**Token:** you'll need `STATE_API_TOKEN` to call anything but `/paper/health`
(which is public/unauthenticated). Tiago will hand it to you directly,
outside chat logs — don't ask for it in a way that gets it written down
anywhere persistent.

## Log what happens

Whatever you find — blockers clearing normally, something stuck, a real
proposal firing — write it to `docs/PAPER_TRADE_DESK_LOG.md` in its existing
format (see the file's own header for the convention). That file is the one
place all three of us (Claude/GPT/DeepSeek) can pick up context from cold,
and it's exactly the scenario it was built for: something happening while
whichever agent isn't around gets to it later.

## Notification — none needed

The phone-alert check (`scripts/paper_alert_check.py`, running in a Claude
`/loop`) may not be firing tomorrow morning if Tiago's Claude tokens are
low — but he'll be up early and watching directly, so no separate
notification path is needed from you. Just log everything to
`docs/PAPER_TRADE_DESK_LOG.md` as it happens; he'll be reading it live or
shortly after, not doing a delayed catch-up.

## Boundary

Same as every task this week: watch, log, report. Don't approve/reject a
proposal on Tiago's behalf, don't touch the kill switch, don't change any
gate or threshold. If something looks like it needs a human decision inside
the approval window and Tiago's genuinely unreachable, that's a
stop-and-report situation per the runbook, not something to resolve
yourself.
