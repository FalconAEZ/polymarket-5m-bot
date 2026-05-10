# Out-of-tree patches deployed to the VPS

These files are full copies of source modules that exist as
**untracked files** on the VPS at `/home/ops/polymarket-5m-bot/`
(under `src/polymarket_bot/dashboard/` and
`src/polymarket_bot/dashboard_server/`). They originate from the
parallel branch `claude/dashboard-pm-truth-fix-7e103f` /
`claude/trusting-spence-03c165` (the dashboard-v3 work) and have
never been merged into `claude/jovial-hermann-7e103f` or `main`.

When an operator-driven session needs to modify those modules and
re-deploy them on the VPS, the workflow is:

1. `scp` the current VPS copy to /tmp.
2. Apply the change.
3. `scp` the patched file back.
4. `sudo systemctl restart dashboard-server.service`.
5. Save a copy here for traceability + future review.

Each file is named `<module>__<change-summary>.py`. The `__` is the
delimiter — everything after is freeform description of what changed.

## Current contents

| File | Origin path on VPS | Change |
|------|--------------------|--------|
| `dashboard_loaders__settled_correction_overlay.py` | `src/polymarket_bot/dashboard/loaders.py` | Adds `apply_settled_corrections()` that overlays `kind=settled_correction` records from the bot's raw decision log on top of `decisions-resolved/` rows. Per phase-5-settle-resolution-bug session 2026-05-10 followup #1. |
| `dashboard_state__apply_corrections.py` | `src/polymarket_bot/dashboard_server/state.py` | Imports + calls `apply_settled_corrections(rows, raw_dir)` after the existing `load_decisions(resolved_dir)`. Same session/followup as above. |

## Followup

These should eventually be merged into the proper dashboard branch
and deployed via that branch's normal flow. Until then, keeping a
copy here means: (a) the diff is recoverable if the VPS file is
lost, and (b) anyone reviewing the dashboard's behavior can find the
canonical source without SSHing.
