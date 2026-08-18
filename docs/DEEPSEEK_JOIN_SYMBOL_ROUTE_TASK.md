# Wire join_symbol_if_ready to an API route

**For:** DeepSeek. Confirmed by Tiago tonight — go ahead.

## What

`paper_execution/activation.py:153` `join_symbol_if_ready(paper_db_path,
webhook_db_path, experiment_id, symbol)` is built and tested (shipped in
`745c8d8`) but has no way to be triggered — nothing calls it in production.
Add a route so Tiago (or a future automated caller) can actually add a
tracked symbol to the live experiment.

## Route

`POST /paper/experiments/<id>/symbols` in `paper_execution/api.py`, same
pattern as the existing routes in that blueprint (`create_bracket`,
`kill_switch`, etc.):

- `require_auth()` first, same as every other mutating route.
- Body: `{"symbol": "GME"}` — reject unknown fields, same
  `_unknown_fields()` helper already used elsewhere in this file.
- Call `join_symbol_if_ready(PAPER_DB_PATH, DB_PATH, experiment_id, symbol)`
  — note the function needs both DB paths; check how `webhook_receiver.py`
  wires `PAPER_DB_PATH`/`DB_PATH` into the blueprint today
  (`create_paper_blueprint` call) and follow the same pattern, don't
  hardcode paths in `api.py`.
- Map the function's `status` to an HTTP code: `JOINED` → 201,
  `ALREADY_TRACKED` → 200 (idempotent, not an error), `BLOCKED` → 409 with
  the `blocker` reason in the body, `EXPERIMENT_NOT_FOUND` → 404.

## Boundary

This only exposes the *ability* to add a symbol — it does not add any
symbol itself, and does not change auto-entry scope (still AMC-only,
unaffected). Nothing about this route should get called automatically by
anything; it's a manual, explicit action Tiago (or a future dashboard
button) triggers deliberately per asset, same spirit as everything else in
`docs/DEEPSEEK_MULTI_ASSET_AND_FIXES_TASK.md`.

Full suite + `git diff --check` clean. Tests: authorized call with an
eligible symbol + fresh heartbeat joins (201); already-tracked symbol
returns 200 `ALREADY_TRACKED`; ineligible symbol returns 409
`ASSET_NOT_ELIGIBLE`; stale/missing heartbeat returns 409
`BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT`; unknown experiment returns 404;
unauthorized request returns 401 (existing pattern).

## Report back

File/line of the new route, test names, full suite result, `git diff
--check` result. Log a one-line summary to `docs/PAPER_TRADE_DESK_LOG.md`
when done.
