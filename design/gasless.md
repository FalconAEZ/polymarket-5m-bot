# Design — Gasless / order-submission flow (OD-4)

> Purpose: resolve open decision **OD-4** before any wallet is funded. Documents
> what is and is not "gasless" on Polymarket for our use case, what the bot
> needs in MATIC vs USDC.e, whether the Builder Program is required, and the
> exact sign-and-submit flow that `scripts/test_gasless_order.py` (Phase 1B,
> task 1.5) will implement.
>
> Anchors: [`agent-skills/authentication.md`](../../.claude/skills/agent-skills/authentication.md),
> [`agent-skills/gasless.md`](../../.claude/skills/agent-skills/gasless.md),
> [`references/py-clob-client/README.md`](../references/py-clob-client/README.md),
> locked decisions [#11, #13, #17] in
> `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md`.

---

## 1. The terminology fix that drives everything below

The phrase "gasless relayer for order submission" in locked **decision #17** is
technically misnamed in the Polymarket ecosystem and was the source of OD-4's
ambiguity. There are **two distinct submission paths** and only one of them is
the "Relayer":

| Path | What goes through it | Mempool exposure | Relayer SDK? | Builder Program? |
|---|---|---|---|---|
| **CLOB API** (`https://clob.polymarket.com`) | Limit and market orders | None — orders are off-chain EIP-712 messages matched off-book; on fill the exchange contract settles | No | No |
| **Relayer SDK** (`https://relayer-v2.polymarket.com`) | Wallet deployment, ERC-20 / ERC-1155 approvals, CTF split / merge / redeem, transfers | None — relayer co-signs and submits | Yes (`py-builder-relayer-client`) | **Yes** — required |

The MEV-protection benefit decision #17 cites comes from path 1 (CLOB off-chain
matching), **not** from path 2 (the Relayer SDK). Decision #17's intent stands;
its wording is updated below.

> **Resolution of decision #17 (clarification, not change):**
> "All trading orders go through the standard CLOB API (path 1). This achieves
> MEV protection because orders never enter a public mempool — they are
> off-chain matched and only settle on-chain on fill. The Polymarket Relayer
> SDK (path 2) is a separate facility for on-chain ops; we are not using it.
> See OD-4b below."

## 2. OD-4a — what is and is not gasless for us

| Operation | Path | Costs MATIC on Signer? |
|---|---|---|
| Place a limit order on the CLOB | CLOB API (off-chain EIP-712 sign) | **No** |
| Place a market order on the CLOB | CLOB API (off-chain EIP-712 sign) | **No** |
| Cancel a CLOB order | CLOB API (HMAC-signed REST) | **No** |
| First-time USDC.e approval to CTF Exchange (`0x4bFb...982E`) | Direct on-chain `approve()` from Signer EOA | **Yes** — one-time, ~$0.01 |
| First-time USDC.e approval to Neg-Risk CTF Exchange (`0xC5d5...f80a`) | Direct on-chain `approve()` from Signer EOA | **Yes** — one-time, ~$0.01 |
| First-time USDC.e approval to Neg-Risk Adapter (`0xd91E...5296`) | Direct on-chain `approve()` from Signer EOA | **Yes** — one-time, ~$0.01 |
| First-time CTF (1155) approval for the same three contracts | Direct on-chain `setApprovalForAll()` from Signer EOA | **Yes** — one-time, ~$0.01 |
| Settling on a winning position (CTF redeem) | Direct on-chain `redeemPositions()` | **Yes** — per-redemption, ~$0.005 |
| Funder → Signer transfers | Standard Polygon tx via MetaMask | **Yes** — per-transfer, ~$0.005 |

Total upper-bound MATIC consumption for Phase 1B (1.4 + 1.5):
roughly $0.10. We hold ~0.5 MATIC on Signer and ~3 MATIC on Funder for headroom
(the runbook's `~$5 MATIC` from CEX sets the ceiling).

## 3. OD-4b — Builder Program: not for us

[`agent-skills/gasless.md`](../../.claude/skills/agent-skills/gasless.md) line 5:

> "Requires Builder Program membership. You need Builder API credentials."

The only operations that benefit from Builder are the on-chain ones in §2 row 4
onward — approvals, CTF redeems, transfers. At our scale those total ~$0.10 in
MATIC across the entire Phase 1B funding ceremony, plus a few cents per redeem
during Phase 6 live trading. Versus that, the Builder Program adds an
application step, ongoing builder API keys (`POLY_BUILDER_*`) in `.envrc`, an
extra HMAC code path, and another rotateable secret.

> **Resolution of OD-4b:** **skip Builder Program.** Signer pays own MATIC for
> approvals and redeems. No `POLY_BUILDER_API_KEY` / `POLY_BUILDER_SECRET` /
> `POLY_BUILDER_PASSPHRASE` in `.envrc`. No `py-builder-relayer-client` /
> `py-builder-signing-sdk` in `pyproject.toml`. Revisit only if Phase 6
> aggregate redeem-gas exceeds $5/month — extremely unlikely at $5-flat sizing.

## 4. OD-4c — `signature_type` and the `funder` parameter

[`py-clob-client/README.md`](../references/py-clob-client/README.md) §Signature Types
specifies three values; we generate plain EOAs via `eth-account` in task 1.1, so:

| `signature_type` | Wallet model | Match for us? |
|---|---|---|
| `0` | EOA — MetaMask, hardware wallets, raw `eth-account` keys | **Yes** |
| `1` | Email / Magic delegated signing | No — we don't use Magic |
| `2` | Gnosis Safe / browser-extension proxy | No — we don't deploy a Safe |

The README's example snippets use `signature_type=1` everywhere, which is
**incorrect for our setup** and would cause every signed call to fail. Use
`signature_type=0`.

The CLOB `funder` parameter is the **address that holds the trading USDC.e**.
For an EOA model this is the **same as** the signing address. The runbook-level
"Funder" wallet (locked decision #11) is a separate, personal capital-segregation
construct that Polymarket never sees. To avoid the name collision:

| Name | What it is |
|---|---|
| Runbook **Funder** | A personal cold wallet holding working capital. Polymarket-unaware. Funds are swept from it to the Signer in chunks. Encrypted offline at `~/secrets/polymarket-5m/funder.age`. **Never** in `.envrc`. |
| Runbook **Signer** | The trading EOA. Holds ≤ 2 days of bankroll. Privkey lives in `.envrc` as `POLY_PRIVATE_KEY`. Encrypted backup at `~/secrets/polymarket-5m/signer.age`. |
| `ClobClient.key` | = Signer privkey |
| `ClobClient.funder` | = **Signer's own address** (because `signature_type=0` ⇒ EOA model) |
| `ClobClient.signature_type` | `0` |

> **Resolution of OD-4c:**
> ```python
> client = ClobClient(
>     host="https://clob.polymarket.com",
>     chain_id=137,
>     key=os.environ["POLY_PRIVATE_KEY"],   # Signer privkey
>     creds=ApiCreds(
>         api_key=os.environ["POLY_API_KEY"],
>         api_secret=os.environ["POLY_API_SECRET"],
>         api_passphrase=os.environ["POLY_API_PASSPHRASE"],
>     ),
>     signature_type=0,
>     funder=Account.from_key(os.environ["POLY_PRIVATE_KEY"]).address,
> )
> ```
> The `funder=` argument is **derived from the same key**, not from a second
> `.envrc` variable. There must be no `POLY_FUNDER_PRIVATE_KEY` or
> `POLY_FUNDER_ADDRESS` in `.envrc`.

## 5. The exact sign-and-submit flow we'll implement in 1.5 (Phase 1B)

This is design-only; the script lives in `scripts/test_gasless_order.py` and
is written when 1B fires (after Phase 4 paper testing closes).

```
                  ┌─────────────────────────────────────────────┐
                  │                                             │
       (1) build  │      ┌─────────────────────────┐            │
       OrderArgs──┼─────▶│ ClobClient.create_order │            │
                  │      │   (EIP-712 signs        │            │
                  │      │    in-process)          │            │
                  │      └────────────┬────────────┘            │
                  │                   │ SignedOrder             │
                  │                   ▼                         │
                  │      ┌─────────────────────────┐            │
       (2) submit │      │ ClobClient.post_order   │            │
                  │      │   POST /order           │ ── HTTPS ──┼──▶ clob.polymarket.com
                  │      │   (L2 HMAC headers)     │            │
                  │      └────────────┬────────────┘            │
                  │                   │ {"orderID": "..."}      │
                  │                   ▼                         │
                  │      ┌─────────────────────────┐            │
       (3) verify │      │ ClobClient.get_order    │            │
                  │      │   GET /data/order/<id>  │ ── HTTPS ──┼──▶ clob.polymarket.com
                  │      │   (L2 HMAC headers)     │            │
                  │      └────────────┬────────────┘            │
                  │                   │ status == "OPEN"        │
                  │                   ▼                         │
                  │      ┌─────────────────────────┐            │
       (4) cancel │      │ ClobClient.cancel       │            │
                  │      │   POST /order/cancel    │ ── HTTPS ──┼──▶ clob.polymarket.com
                  │      │   (L2 HMAC headers)     │            │
                  │      └────────────┬────────────┘            │
                  │                   │ status == "CANCELED"    │
                  │                   ▼                         │
                  └─────────────────────────────────────────────┘
                                                                ▲
                                              All four steps off-chain.
                                              Zero MATIC consumed in 1.5.
```

Concrete sequence captured to `runbooks/gate-evidence/phase-1.txt` at 1B time:

1. `OrderArgs(token_id, price=<far-below-bid>, size=<$5/price>, side=BUY)`
2. `signed = client.create_order(OrderArgs(...))` → in-process EIP-712 sign
3. `resp = client.post_order(signed, OrderType.GTC)` → captures `order_id`
4. `client.get_order(order_id)` → assert `status == "OPEN"`
5. `client.cancel(order_id)` → returns success
6. `client.get_order(order_id)` → assert final `status == "CANCELED"`
7. Append `(1)`–`(6)` raw responses to `runbooks/gate-evidence/phase-1.txt`

**Market choice for the test order in 1.5.** Pick a long-dated, low-volume,
non-BTC market (e.g. an obscure US-state political market resolving > 30 days
out). Limit price set well below the visible bid so the order **cannot fill in
this session**. Operator confirms the chosen market + price in chat before the
script runs.

## 6. Phase 1A vs Phase 1B (decision #20)

Per locked decision #20 (added 2026-05-06), Phase 1 is split:

- **Phase 1A — now.** Tasks 1.0 (this doc), 1.1 (genwallets), 1.2 (derive_creds),
  1.3 (test_auth), 1.6 (wallet-ops). New gate `runbooks/gates/phase-1a.sh`,
  tag `phase-1a-pass`. Zero on-chain footprint. Asserts:
  1. `make verify` green
  2. `scripts/test_auth.py` exits 0 returning the Signer address
  3. `~/secrets/polymarket-5m/funder.age` exists, age-armored header
  4. `~/secrets/polymarket-5m/signer.age` exists, age-armored header
  5. `grep -r "POLY_FUNDER_PRIVATE_KEY\|POLY_FUNDER_ADDRESS" .` returns nothing
  6. `grep -E "^POLY_FUNDER" .envrc` returns nothing
- **Phase 1B — at pre-live.** Tasks 1.4 (fund + sweep), 1.5 (place + cancel
  $5 limit). Original gate (RUNBOOK.md:679-684) plus tag `phase-1-pass`.
  Triggers immediately after Phase 4 paper testing closes, before Phase 5
  systemd promotion to live. The file paths and MATIC budget here are the
  contract; nothing in this doc changes between now and then.

## 7. What this means for `pyproject.toml`

Phase 1A adds exactly two runtime deps: `eth-account`, `py-clob-client`. No
`py-builder-relayer-client`, no `py-builder-signing-sdk`. Pinned with
`uv add <pkg>` so `uv.lock` updates atomically.

## 8. What this means for `.envrc`

After Phase 1A:

```bash
# Existing (Phase 0)
export ANTHROPIC_API_KEY=...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export POLYGON_RPC_URL=...

# Added in Phase 1A
export POLY_PRIVATE_KEY=0x...   # Signer privkey, mode 0600, gitignored
export POLY_API_KEY=...         # derived L2 — UUID
export POLY_API_SECRET=...      # derived L2 — base64
export POLY_API_PASSPHRASE=...  # derived L2 — string
```

Forbidden in `.envrc` ever: `POLY_FUNDER_PRIVATE_KEY`, `POLY_FUNDER_ADDRESS`,
`POLY_BUILDER_*`. The Phase 1A gate greps for the first two; the absence of
the third is enforced by not importing the builder SDK at all.

## 9. Open items deferred to 1B (none block Phase 2)

- **Empirical confirmation that `signature_type=0` + EOA-funder yields a posted
  order.** `test_auth.py` proves the L1→L2 handshake works against Polymarket's
  servers but does not prove order acceptance. If 1B surfaces a `signature_type`
  mismatch we revisit; until then this design is the working hypothesis.
- **CTF redeem gas cost calibration.** First real number lands when the first
  Phase 6 redeem fires. Section 2 estimate is a paper estimate from gas-used
  patterns in the py-clob-client examples directory.

---

**OD-4 closed.** Decision #17 reframed (not changed). Decisions #11 and #13
preserved. New locked decision #20 splits Phase 1 into 1A/1B as above.
