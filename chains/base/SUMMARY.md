# Base — precompiles that cannot be enumerated

**Chain ID 8453 · role: `fork` · upstream: [op-stack](../op-stack/SUMMARY.md) · baseline: Osaka**

Reference: [base/base `v1.5.4`](https://github.com/base/base) @ `8bb377af` — a
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
stateful actor authorization and config-change authorization. At the previous pin
this was gated behind the **Cobalt** upgrade, then **Zenith**. At v1.5.4 it is gated
behind **Everest**, and that is the single most important fact on this row.

It has its own transaction type: **`0x79`** (`EIP8130_TX_TYPE_ID = 121`).

**Cobalt went live on mainnet on 2026-09-30 18:00 UTC and did not bring it.** Cobalt
installs the two EIP-8130 support precompiles — NonceManager at `0x8130…aa01` and
TxContext at `0x8130…aa02`, both gated `>= Cobalt` in
`provider.rs:install_with_observer` — so the *infrastructure* for native account
abstraction is live and callable on Base mainnet today. The transaction type that
would use it is not submittable, because `EIP8130_REJECTION_MSG` now reads *"gated
behind Everest"*. The earlier reading of this row was that the type sat behind a gate
no runtime override could open. That no longer holds: Everest is contract-backed and in
the execution ladder, though unscheduled on every network. Zenith, which is still
`ForkCondition::Never`, now holds only the Keystore, so until it activates a `0x79`
transaction may use only delegation and native secp256k1 keys.

Base also supports EIP-7702, so **two distinct account-abstraction mechanisms coexist**
on the same chain, with two different transaction types.

### …and it is a CLOSED set, which is the interesting part

`sender_auth` is `authenticator(20) || authenticator_data`, and `AuthenticatorDispatch`
routes that 20-byte selector through a hardcoded if-chain over **four** canonical
values, falling through to `AuthError::NotCanonical` for anything else:

| selector | scheme | verified by |
|---|---|---|
| `address(1)` (`K1_AUTHENTICATOR`) | secp256k1 | native `ecrecover` — no deployed contract exists |
| `0x8130C8…A256` | secp256r1, raw | native Rust |
| `0x813007…F1d0` | secp256r1 under a WebAuthn envelope (a passkey) | native Rust |
| `0x81301A…ade1` | *not a scheme* — 1-hop delegation over one of the above | — |

There is **no path by which a user-deployed contract validates a transaction
signature.** That is the exact opposite of zkSync, where the account's own code *is* the
authentication rule and the scheme set is open and unbounded. Base's is enshrined and
finite.

So **on Base a P-256 key can move a wei.** Eleven rows in this dataset carry
`P256VERIFY` and on almost all of them the precompile is a tool for *contracts* and a
P-256 key cannot sign anything; here the same curve is a first-class transaction signer,
verified by the client. Base is the sharpest counter-example to that pattern. Base even
prices the enshrined authenticators *off* those precompiles deliberately —
`Eip8130GasSchedule` pins 3,000 for k1 and 6,900 for P-256 to the `ECRECOVER` and
EIP-7951 costs.

**Not the unpaired finding**, and that is a real result: every scheme here has a
verifier a contract can reach (`0x01`, `0x0100`, and the WebAuthn construction
reassembled from `0x0100` + `0x02`).

**Two parties, two different digests** — the same shape Kaia arrived at independently.
`payer` is an optional second account authorizing over `payer_signature_hash`, which
substitutes the *resolved* sender into the digest and is domain-separated by its own
magic byte (`0x7A`), so a payer signature cannot be replayed under a different sender.
The payer's blob takes the same `authenticator(20) || data` form, so a **sponsor may
itself be a passkey**.

**Not live on mainnet**, and the reason is two fork gates rather than a deployment gap.
The canonical contracts are CREATE2 deployments with mined salts sharing a `0x8130…`
prefix, and any bytecode change moves an address; this row's earlier `0x2403…`/`0x2809…`
set is gone for that reason. None of the current five has code on mainnet at block
55270259. The binding constraint at v1.5.4 is two fork gates:
the only transaction type that reaches `AuthenticatorDispatch` is `0x79`, which sits
behind Everest, and non-secp256k1 keys also need Zenith's Keystore. The P-256 schemes stay `pending`, and Cobalt's activation did not
change that — a P-256 key still cannot move a wei on Base mainnet.

## Its own fork line

Beyond the OP Stack sequence (Bedrock → Jovian), Base has **Azul, Beryl, Cobalt, Denim,
Everest** plus the **Zenith** gate. `zombie` is gone: Zenith replaced it as the
never-activating gate.

| Upgrade | Mainnet | What it is |
|---|---|---|
| Azul | 2026-05-28 18:00 UTC | first Base-specific upgrade; Osaka pricing for MODEXP/P256VERIFY |
| Beryl | 2026-06-25 18:00 UTC | installs the dynamic B-20 precompile lookup |
| **Cobalt** | **2026-09-30 18:00 UTC** | NonceManager + TxContext precompiles, builder tx extensions. **Not** EIP-8130's type byte |
| **Denim** | **2026-11-05 18:00 UTC, block 53556127** (Sepolia since 2026-10-21) | 200ms blocks, gas parameters scaled 10×, `BaseTime` predeploy, B-20 V3 |
| Everest | `None` on every network | declared since v1.5.1, still unscheduled at v1.5.4; holds the EIP-8130 type |
| Zenith | `Never` | gate for future features; holds the Keystore. Not runtime-activatable |

Base is **absent from the superchain-registry mainnet configs** in this snapshot —
unlike OP Mainnet and World Chain, whose activation timestamps are published there.
So fork *order* is verified from the `BaseUpgrade` enum, but timestamps are runtime
configuration and are not recorded rather than guessed.

## Denim: 200ms blocks and a clock that stays in seconds

**Live on mainnet since block 53556127**, the first block at or after 2026-11-05 18:00 UTC.
The last 2s block, 53556126, is stamped 1793901599. From 53556127 on, the gas limit is 40,000,000 and
the BaseTime deposit sits at `tx[1]`. Over the 100,000 blocks to 55270259, `block.timestamp`
advanced 20,000s and `BaseTime.timestampMs()` advanced 20,000,000ms: 200ms per block exactly.

`block.timestamp` does not gain precision. Blocks 53556127 to 53556131 all report
1793901601, five to a second. Three things follow:

- **Time is not block count.** Five blocks share one timestamp, and code holding block-count
  constants written for 2s blocks runs ten times faster.
- **`tx[1]` is now a system deposit.** Every block calls `setTimestampMillisPart` on
  `BaseTime` at `0x4200…0030`, ahead of user transactions.
- **`BaseTime` is wrong during `tx[0]`.** The client says so: 200ms behind within a second,
  800ms ahead at rollover.

At the first Denim block the gas limit is divided by 10 and the EIP-1559 denominator
multiplied by 10, and mainnet did exactly that. The gas limit went from 400,000,000 to
40,000,000. The Holocene `extraData` denominator went from 100 to 1000, with elasticity 5 and
the Jovian minimum base fee of 5,000,000 wei both unchanged. The first base-fee step after
the boundary, +8,447 wei on 21,516,598 gas used, is what denominator 1000 predicts.
`BaseTime.timestampMs()` reverts with "Proxy: implementation not initialized" at 53556126
and answers 1793901601000 at 53556127.

**PREVRANDAO now repeats for 60 blocks, not five or six.** It is still the L1 origin's
RANDAO mix, shared by every L2 block in one 12s L1 epoch, and an epoch now holds 60 Denim
blocks.

## Contrast with OP Mainnet

Same upstream, same OP Stack, and OP Mainnet's delta file is **empty**. Base
reimplements the EVM layer in Rust, adds five fixed precompiles plus an unbounded
dynamic range, native AA with its own tx type, and four bespoke forks. "Runs the OP
Stack" constrains a chain far less than it sounds like it does.

## Re-verify

```
git clone --depth 1 --branch v1.5.4 https://github.com/base/base
sed -n '60,80p' crates/common/precompiles/src/b20_factory/variant.rs   # the predicate
sed -n '1,50p'  crates/common/precompiles/src/lookup.rs                # BerylLookup
grep -rn "pub const ADDRESS: Address" crates/common/precompiles/src/*/storage.rs
sed -n '1,20p'  crates/common/consensus/src/transaction/tx_type.rs     # 0x79
head -20 crates/common/eip8130/README.md                               # "enshrined"
```
