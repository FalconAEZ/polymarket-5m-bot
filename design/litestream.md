# Design — litestream replication of `state/trades.db` (Phase 5.7 criterion #8)

> Purpose: lock the architecture for off-box durability of the bot's local SQLite
> trade ledger. Anti-vibe rule #1: this doc lands and locks before
> `runbooks/litestream.yml` and `runbooks/systemd/litestream.service` are
> committed.
>
> Anchors:
> - `RUNBOOK.md` §"PHASE 5" — gate criterion #8 ("litestream replicating `trades.db`").
> - `state/phases/phase-5-vps.md` — Phase 5 tracker; lists litestream as the only
>   blocker for `phase-5-pass`.
> - `runbooks/systemd/README.md` (Phase 5.4) — sibling-unit deploy pattern.
> - `phase-prompts/phase-5.7-litestream-prompt.txt` — handoff spec from the
>   prior session, codified here.
> - locked decision **#11** (Funder/Signer split) — this doc's "what does NOT
>   leave the box" section enforces it.
> - locked decision **#2** (Dublin VPS) — bucket region chosen to match.
>
> Out of scope: cross-region DR, multi-replica fan-out, point-in-time restore
> beyond litestream's own snapshot+WAL window. One bucket, one VPS, one DB.

---

## 1. The picture

```
   bot-staging.service  (now)                          litestream.service  (NEW, Phase 5.7)
   bot.service          (Phase 6)                      |
            |                                          |
            v                                          v
   /home/ops/polymarket-5m-bot/state/trades.db  ---->  AWS S3 (eu-west-1)
                  ^                                    s3://polymarket-5m-litestream-falcon/
                  |                                       trades.db/
                  |                                          generations/<id>/
                  +---  (litestream restore on disaster)---  snapshots/   <- every 1h
                                                             wal/         <- every 1s
```

litestream is a sidecar process. It opens `trades.db` read-only, watches the
WAL, ships WAL frames to S3 every `sync-interval` (1s), and uploads a full
snapshot every `snapshot-interval` (1h). On disaster, `litestream restore`
reconstructs the DB from the most recent snapshot + WAL frames into a chosen
local path.

## 2. What gets replicated

**Replicated:** `state/trades.db` only.

**Why this file specifically:**
- Phase 6 will populate it with order/fill rows (locked decision #11, #17 —
  the gasless-relayer call sites write here).
- Today (Phase 5.7) the file may not exist yet, or contain only the
  `_placeholder` table created by the bootstrap step. litestream handles a
  zero-row source fine: it ships an initial snapshot and waits.
- The schema itself is part of the recovery payload — restoring the DB on a
  fresh box gives Phase 6 immediate continuity.

**NOT replicated (intentional):**
- `state/decisions/<UTC-date>.jsonl` — append-only, idempotent on replay,
  re-derivable from feed captures + git-tracked code; no business-critical
  state lost on box loss.
- `state/token_side_index.json` — derivable from CLOB at bot start.
- `state/halt.sentinel` — ephemeral; remote `/halt` recreates it instantly.
- `.envrc`, `.envrc.litestream` — secrets; never replicated to S3 or anywhere
  off the VPS (locked decision #11).
- Any artefact of the operator's laptop vault under `state/staging/` —
  produced by `make sync-staging`, not bot-side state.

## 3. Where, and how it's secured

**Bucket:** `polymarket-5m-litestream-falcon`
**Region:** `eu-west-1` (Ireland) — same region as the Lightsail VPS, so
intra-region traffic is free and ≤5 ms write latency.
**Versioning:** enabled (gives a rescue layer on top of litestream's own
generations if a corrupt snapshot is ever pushed).
**Encryption:** SSE-S3 (AWS-managed keys) — sufficient for trade data; the
Signer key still NEVER goes in this bucket (locked decision #11).
**Public access:** all four "Block public access" toggles ON.

**IAM:** dedicated user `litestream-vps` with a least-privilege inline policy
limited to four actions on this single bucket: `s3:ListBucket`,
`s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`. No `*` resources, no list
of all buckets, no console access. The user's access keys live ONLY in
`/home/ops/polymarket-5m-bot/.envrc.litestream` on the VPS, mode `0600`,
never committed to git.

**Why a separate `.envrc.litestream` file (not `.envrc`):**
- `.envrc` already sources cleanly via `bash -c 'source .envrc && exec …'` for
  `bot-staging.service` and `tg-alerter.service`. Mixing AWS keys in there
  means more code paths see them (the alerter doesn't need S3 perms).
- `litestream.service` reads its own `EnvironmentFile=` via systemd directly
  — bare `KEY=VALUE` lines, no shell expansion. A separate file matches that
  format without regressing the `export KEY=VAL` shape that direnv expects on
  the operator's laptop.

## 4. Replication parameters

| | Value | Why |
|---|---|---|
| `sync-interval` | `1s` | litestream default; trade volume is low, the 1 s WAL ship is cheap and bounds RPO. |
| `snapshot-interval` | `1h` | Bounds restore time; one extra full snapshot per hour at <1 MB each is negligible at S3 prices. |
| `retention` | `24h` | We keep 24 h of WAL + snapshots in S3. Older generations age out. Phase 6 may extend to 7 d once we see real trade volume; revisit then. |
| `validation-interval` | `12h` | litestream periodically does a self-check restore-to-tmp-and-diff; cheap insurance against silent corruption. |

RPO target: ≤2 s (1 s sync + 1 s upload). RTO target: ≤5 min (one
`litestream restore` on a fresh box).

## 5. Recovery procedure (the one-liner that matters)

```bash
# On a freshly provisioned VPS, after litestream is installed and
# /home/ops/polymarket-5m-bot/runbooks/litestream.yml + .envrc.litestream
# are in place:

sudo systemctl stop bot-staging.service     # if it was running
rm -f state/trades.db                       # remove any local stub
/usr/bin/litestream restore \
    -config runbooks/litestream.yml \
    state/trades.db
sudo systemctl start litestream.service
sudo systemctl start bot-staging.service
```

That's the documented restore. The command exits non-zero if no generation
is reachable in S3 — caller wraps with `&&` or checks `$?` for safety.

## 6. Failure modes (and what they mean for the bot)

| Mode | Detection | Effect on bot | Recovery |
|---|---|---|---|
| **Bucket auth fail (rotated key, deleted IAM)** | `litestream.service` fails its first sync, `Restart=on-failure` retries every 15 s, `journalctl -u litestream.service` shows `403 Forbidden` or `InvalidAccessKeyId`. | **Bot keeps running.** Trades are written to local SQLite as normal. RPO degrades to "until we fix the auth"; no live decisions affected. | Rotate key in `.envrc.litestream`, `sudo systemctl restart litestream.service`. Litestream resumes from local WAL position. |
| **Network partition (S3 unreachable)** | Same — `journalctl` shows DNS/timeout errors. | **Bot keeps running.** litestream queues WAL frames locally; drains when S3 returns. | Heals automatically. |
| **Disk full on source** | `bot-staging.service` would crash on first `INSERT` into `trades.db`. Telegram alert fires via the existing `RedisAlertSink`. | **Bot fails.** | Operator-driven — page goes to Telegram per Phase 5.5 wiring. trades.db is small (<1 GB/year worst case at Phase 6 expected volume); disk-full is a config/log-bloat bug, not a steady-state risk. |
| **Bucket deletion / corruption upstream** | First `litestream restore` returns no generations. | None at runtime; **only matters on disaster recovery.** | Recreate bucket + IAM, re-run `litestream replicate`. Loses history older than the local DB on the VPS. |
| **Source DB corruption** | bot crashes or `sqlite3 trades.db "PRAGMA integrity_check"` shows errors. Telegram alert. | **Bot fails.** | Stop both services, rename the corrupt local copy, `litestream restore` to a known-good generation, restart. |

**What litestream is NOT:**
- **Not a kill-switch.** That's `state/halt.sentinel` + `/halt` Telegram from
  Phase 5.5. litestream failing does not stop the bot, and the bot stopping
  does not stop litestream.
- **Not a backup of the LLM API ledger or Anthropic spend.** Those live in
  `state/decisions/` and the operator's billing dashboard.
- **Not a substitute for the Phase 6 staged-restore drill.** Before flipping
  live, we'll do a full restore-to-fresh-VPS rehearsal as part of the Phase
  6 prereq checklist.

## 7. Operational expectations

- **Cost:** trades.db at Phase 6 expected volume is sub-100 MB. With 24 h
  retention and 1 h snapshots, total stored bytes are <1 GB/month. AWS S3
  Standard at $0.023/GB/mo + intra-region transfer free → effective cost
  $0.00–0.03/mo. Well inside the $200/mo OPEX cap (locked decision #14).
- **CPU/RAM on VPS:** litestream is a single Go binary; previous benchmarks
  show <1 % CPU and <30 MB RSS at 1 Hz sync. The 4 GB Lightsail host
  swallows it without notice.
- **Logs:** `journalctl -u litestream.service`. Steady state is silent.
  Each snapshot logs a `snapshot completed` line at INFO.

## 8. Gate criterion (Phase 5.7 #8)

The phase gate considers this criterion satisfied iff ALL of:

1. `systemctl is-active litestream.service` → `active`
2. `aws s3 ls s3://polymarket-5m-litestream-falcon/trades.db/generations/` → at least one generation directory present (proves a snapshot was uploaded)
3. The restore drill in §5 above runs end-to-end and the restored DB matches
   the pre-restore `.dump` byte-for-byte (md5 equal). Output captured at
   `runbooks/gate-evidence/phase-5.7-litestream-restore.txt`.

If all three pass, the phase script exits 0 and we tag `phase-5-pass`.

## 9. Open questions (icebox)

- Phase 6: extend `retention` to 7 d once we see real trade volume.
- Phase 6: add a second replica destination (cross-region S3 or a different
  provider) once the bot is making real money. Today's single-bucket setup
  is right-sized for paper.
- Phase 6 prereq: write `runbooks/disaster-recovery-drill.md` codifying the
  full restore-to-fresh-VPS rehearsal (out of scope for 5.7).
