# Task packet — SEC filing poller has no actual schedule (gap found)

**Requested by:** Tiago, 2026-08-17. **For:** DeepSeek. Not urgent, but
real — close this loop.

## The gap

`scripts/poll_sec_filings.py` is sound code and its own docstring
recommends a 5-minute Railway cron cadence, but `railway.json` in this
repo only defines the main web service (`gunicorn ... webhook_receiver:app`)
— there is no scheduled/cron service anywhere in the repo config that
actually runs this script. Unless Tiago finds a separately-configured
Railway cron service in the dashboard (outside what's tracked in this
repo), a real dilution filing today would only get picked up if someone
manually runs the script by hand — not automatically, not in good timing.

Tiago is checking Railway's dashboard directly for whether a second
service/cron job already exists. **Wait for his answer before doing
anything** — if one already exists, this task is just closing the loop
on documentation; if none exists, it's a real setup gap.

## If no scheduled job exists — what's needed

Railway supports cron-scheduled services (a second service in the same
project, sharing the volume/env vars, running on a cron expression rather
than as a persistent web server). This is primarily a **Railway
dashboard/infra configuration step**, not a code change — but check
whether it can also be expressed in `railway.json` (Railway's newer
config format supports multiple services with `cronSchedule` in some
setups) so it's reproducible/version-controlled rather than a manual
dashboard-only setup that could get lost.

Also worth deciding alongside this: the ADV liquidity bands
(`adv_liquidity.py`) have the exact same problem — a precomputed table
that only refreshes when someone manually re-runs the script. If a
scheduled-job mechanism gets set up for the SEC poller, consider whether
it's worth generalizing to also periodically refresh ADV bands (and
potentially the reliability mask / silence baseline later) — same root
cause, don't necessarily solve it four separate times. Flag this as an
option, don't build it without confirming scope with Tiago/Claude first.

## Boundary

Investigate and propose, but don't change Railway's actual live
configuration without explicit confirmation — this affects production
infrastructure, not just repo code. If a `railway.json` change is the
right fix, prepare it and report back; don't deploy it yourself.

## What to report back

Whether a cron job already exists (per Tiago's dashboard check), and if
not, a concrete proposal for how to set one up — plus whether bundling
the ADV-refresh problem into the same mechanism makes sense or should
stay separate.
