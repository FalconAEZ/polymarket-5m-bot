---
title: Gasless relayer (and why we mostly don't need it)
tags: [concept, polymarket, infrastructure, OD-4]
---

# Gasless relayer

> Polymarket's mechanism for placing orders without paying per-tx gas. We use the standard CLOB API (which is gasless by default for orders) and pay our own MATIC only on one-time approvals.

## OD-4 resolution (decision #20) ✅ shipped 2026-05-06

Captured in `design/gasless.md` (commit `80df145`) and verified end-to-end via `scripts/test_auth.py` against live Polymarket (Phase 1A gate `1537a18`).


The original concern was: do we need to register with Polymarket's Builder Program and use the Relayer SDK to submit orders gasless? Per the resolution captured in `design/gasless.md`:

1. **Orders go via the standard CLOB API**, NOT the Relayer SDK. The CLOB itself is the off-chain orderbook; orders don't hit Polygon mainnet per fill. So they're "gasless" in the operator's sense — no gas cost per order — without needing the Builder Program.

2. **Skip the Builder Program.** The Builder Program is for builders who run their own UIs and want order attribution / rebates. Solo retail doesn't need it. Signer pays its own MATIC for one-time on-chain transactions only.

3. **`signature_type = 0`** (EOA — externally-owned account, the simplest). No proxy wallet contract needed.

4. **CLOB `funder` parameter = Signer's own address.** Same wallet for the L1 EIP-712 signature and the on-chain settlement target.

## What costs MATIC (one-time)

- **USDC approve()** to the Polymarket exchange contract (`0x4bFb…982E` for CTF, `0xC5d5…f80a` for NegRisk). One-time per exchange. Approves an unlimited spend so you don't repeat. Costs a few cents of MATIC.
- **Conditional Token redeems** when a position resolves and you want USDC out. Optional — auto-redeem can be triggered by the exchange.

That's it. Order placement, cancellation, fills — all CLOB-mediated and free.

## What does NOT cost MATIC (per-trade)

- Order placement (signed off-chain, settled in batches by Polymarket).
- Order cancellation.
- Fills (the matching is off-chain).

## Why this matters operationally

The Signer wallet only needs **a few dollars of MATIC** total — enough to cover the one-time approval transactions in Phase 1B and any future redeems. We don't need to keep refilling MATIC.

That keeps the operational footprint simple and supports [[funder-signer|the Funder/Signer split]]: Signer doesn't need a meaningful MATIC reserve, just dust.

## Implementation snippet

```python
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

client = ClobClient(
    "https://clob.polymarket.com",
    chain_id=POLYGON,
    key=os.environ["POLY_PRIVATE_KEY"],   # Signer key
    signature_type=0,                       # EOA
    funder=signer_address,                  # same as signer
)

# Derive L2 creds (one-time, no gas)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

# Place order (CLOB-mediated, no gas)
client.create_and_post_order(...)

# Approve USDC (on-chain, costs MATIC) — see py-clob-client README
```

## See also

- [[../decisions/README#decision-17|Decision #17]] — Polymarket gasless relayer (locked)
- [[../decisions/README#decision-20|Decision #20]] — OD-4 resolution + 1A/1B split
- [[funder-signer]] — wallet topology that this enables
- [[../phases/phase-1-wallet-auth]] — when this gets implemented
- `~/.claude/skills/agent-skills/gasless.md` — Polymarket's official skill doc
- `references/py-clob-client/README.md` — official Python client
