# Base — precompiles that cannot be enumerated

**Chain ID 8453 · role: `fork` · upstream: [op-stack](../op-stack/SUMMARY.md) · baseline: Osaka**

Reference: [base/base `v1.2.0`](https://github.com/base/base) @ `8e28af24` — a
reth/op-reth-based client in Rust.

## First: the repo trap

`base/node` (68k stars, "Everything required to run your own Base node") is **Docker
packaging only**. It contains a `versions.env` pointing at the real client, `base/base`.
Reading the obvious repo would have produced a confidently empty row asserting Base
has no EVM divergence. It has more than any other OP-Stack descendant here.

## Base precompiles are not enumerable

This is the finding that breaks the dataset's own model. At the **Beryl** upgrade,
Base installs a `PrecompileLookup` (`crates/common/precompiles/src/lookup.rs`) that
resolves precompiles **by predicate over the address**, not from a fixed map:

```rust
pub fn from_address(address: Address) -> Option<Self> {
    let bytes = address.as_slice();
    if bytes[0] != 0xb2 || bytes[1..10] != [0u8; 9] { return None; }
    Self::from_discriminant(bytes[10])       // 0 = Asset, 1 = Stablecoin
}
```

Any address matching `0xb2` + nine zero bytes + a valid variant byte **is a
precompile** — roughly 2^72 addresses per variant, with the low bytes carrying token
identity. These are the B-20 native token precompiles.

Every other chain in this dataset has a precompile set you can list. Base has one you
can only *test membership in*. `PRECOMPILES.md` is an address-keyed table and is
structurally incapable of representing this; the row records a `dynamic_range` entry
with the predicate instead of pretending to enumerate. The same class of problem as
Arbitrum's Stylus: a chain diverging along an axis the schema has no column for.

Decompilers, tracers and static analysers that build a fixed precompile set are all
wrong on Base, and wrong *silently* — an unknown address looks like an ordinary
account.

## Five fixed precompiles, chain-ID-prefixed

| Address | Name |
|---|---|
| `0x8453…0001` | Activation |
| `0x8453…0002` | Policy |
| `0x8130…aa01` | Nonce (2D nonces for EIP-8130) |
| `0x8130…aa02` | TxContext |
| `0xB20F…0000` | B20Factory |

Base uses **its own chain ID (8453) as the address prefix** — a placement convention
no other chain here uses. Collision-free by construction, but only if everyone adopts
it, and BSC/Arbitrum/opBNB demonstrate that nobody has.

## Native account abstraction, enshrined

`crates/execution/eip8130/` implements **EIP-8130, "Account Abstraction by Account
Configuration"**. Its README is explicit: *"Enshrined, not a precompile."* It brings
2D nonces, a **sender/payer split**, an intrinsic gas schedule (`Eip8130GasSchedule`),
stateful actor authorization and config-change authorization — gated behind the
**Cobalt** upgrade.

It has its own transaction type: **`0x79`** (`EIP8130_TX_TYPE_ID = 121`).

Base also supports EIP-7702, so **two distinct account-abstraction mechanisms coexist**
on the same chain, with two different transaction types.

## Its own fork line

Beyond the OP Stack sequence (Bedrock → Jovian), Base has **Azul, Beryl, Cobalt,
Zombie**. Beryl installs the dynamic precompile lookup; Cobalt gates EIP-8130.

Base is **absent from the superchain-registry mainnet configs** in this snapshot —
unlike OP Mainnet and World Chain, whose activation timestamps are published there.
So fork *order* is verified from the `BaseUpgrade` enum, but timestamps are runtime
configuration and are not recorded rather than guessed.

## Contrast with OP Mainnet

Same upstream, same OP Stack, and OP Mainnet's delta file is **empty**. Base
reimplements the EVM layer in Rust, adds five fixed precompiles plus an unbounded
dynamic range, native AA with its own tx type, and four bespoke forks. "Runs the OP
Stack" constrains a chain far less than it sounds like it does.

## Re-verify

```
git clone --depth 1 --branch v1.2.0 https://github.com/base/base
sed -n '60,80p' crates/common/precompiles/src/b20_factory/variant.rs   # the predicate
sed -n '1,50p'  crates/common/precompiles/src/lookup.rs                # BerylLookup
grep -rn "pub const ADDRESS: Address" crates/common/precompiles/src/*/storage.rs
sed -n '1,20p'  crates/common/consensus/src/transaction/tx_type.rs     # 0x79
head -20 crates/execution/eip8130/README.md                            # "enshrined"
```
