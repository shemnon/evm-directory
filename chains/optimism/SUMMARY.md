# OP Mainnet — the empty delta

**Chain ID 10 · role: `fork` · upstream: [op-stack](../op-stack/SUMMARY.md) · baseline: Osaka**

Reference: op-geth `v1.101702.2` @ `e8800cff` — the same client as the op-stack row.
Fork times from the superchain registry.

## The point of this row is that it is empty

OP Mainnet adds **nothing** to OP Stack. No precompiles, no transaction types, no
opcodes, no system contracts, no fee components. Its EVM *is* the op-stack row.

That is worth recording rather than skipping, for two reasons.

**It validates the stack-node model.** The inheritance machinery resolves OP Mainnet's
complete effective set — `0x7e` deposits, the six modified precompiles, thirty
predeploys, three fee components — from a file that declares none of them. If the model
works anywhere it should work here, and it does.

**It makes Base's divergence legible.** Base shares this upstream and this OP Stack
version, and reimplements the EVM layer in Rust with five fixed precompiles, an
unbounded dynamic precompile range, native account abstraction and four bespoke forks.
Without an empty row alongside it, "runs the OP Stack" would look like a strong
constraint. Side by side, it is clearly not one: **the same upstream produces both the
emptiest and one of the fullest delta files in the dataset.**

## Fork schedule

From `superchain-registry/superchain/configs/mainnet/op.toml` — per-chain configuration,
not client constants, which is why it lives in a registry rather than in op-geth.

| Fork | Activated | Mainnet equivalent |
|---|---|---|
| Canyon | 2024-01-11 | Shanghai |
| Delta | 2024-02-22 | — |
| Ecotone | 2024-03-14 | Cancun |
| Fjord | 2024-07-10 | — |
| Granite | 2024-09-11 | — |
| Holocene | 2025-01-09 | — |
| Isthmus | 2025-05-09 | **Prague** |
| Jovian | 2025-12-02 | — |
| Karst | 2026-07-08 | — |

Isthmus landed two days after mainnet's Prague — the tightest tracking of any chain
here. For contrast, World Chain runs the same stack and reached Isthmus on 2025-11-25,
over six months later, and has not activated Karst at all.

## Re-verify

```
git clone --depth 1 https://github.com/ethereum-optimism/superchain-registry
grep -E "^name|^chain_id|_time =" superchain/configs/mainnet/op.toml
```
