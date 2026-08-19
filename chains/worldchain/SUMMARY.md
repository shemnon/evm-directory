# World Chain — zero live EVM divergence from OP Stack

**Chain ID 480 · role: `fork` · upstream: [op-stack](../op-stack/SUMMARY.md) → ethereum**

Reference: [worldcoin/world-chain `v2.4.2`](https://github.com/worldcoin/world-chain)
@ `33281430`. Note this repo is a **block builder, not an execution client** —
World Chain runs stock op-reth/op-geth.

## The finding is the absence

Every EVM-level fact about World Chain today is inherited from OP Stack unchanged:
same opcodes, same precompiles (including all six of OP Stack's semantic divergences
from mainnet), same `0x7e` deposit type, same three-component fee model, same
repurposed `blobGasUsed`. **World Chain adds nothing at the EVM layer.**

This is the case the schema was built to represent honestly. A survey that lists
"World Chain: World ID, PBH, priority for humans" under *EVM differences* would be
describing marketing. The differences are real but they live somewhere else.

## PBH is ordering, not execution

Priority Blockspace for Humans grants verified World ID holders top-of-block
priority. Mechanically:

- It runs through **rollup-boost**, an external block-production sidecar, "while
  remaining fully compatible with the OP Stack" (`specs/pbh/architecture.md:2`).
- PBH transactions are **"standard OP transactions"** that call `pbhMulticall()` or
  `handleAggregatedOps()` on `PBHEntryPoint` with a World ID proof in calldata
  (`specs/pbh/txs.md:3`).
- `PBHEntryPoint` is an **ordinary deployed contract**, not a predeploy — no
  reserved address, no client support required.
- rollup-boost **falls back to the default EL's block** if the builder is late or
  returns an invalid one.

That last point is decisive: a component that can be bypassed by fallback cannot be
part of the state transition function. PBH belongs in a block-policy column, not an
EVM-difference column.

## Everything interesting is in the future tense

`crates/chainspec/src/hardfork.rs` declares two World-Chain-specific hardforks past
the OP sequence — **Tropo** and **Strato**. Both are `ForkCondition::Never` in the
shipped spec (asserted at `crates/chainspec/src/spec.rs:578-579`). Declared, not
scheduled. The chain currently defaults to **Jovian**.

The WIP series (World Chain's EIP analogue) has eight proposals, **all Draft**:

| WIP | Title | Would add |
|---|---|---|
| 1001 | Native Account Abstraction | tx type `0x1D`, account-manager predeploy |
| 1002 | WorldID Subsidy Accounting | |
| 1003 | World ID Transaction Subsidies | |
| 1004 | EdDSA Verification Precompile | Ed25519 at `0x0100` |
| 1005/1006 | Proof System Upgrade / Architecture | |
| 1007 | Flashblock Access Lists | (networking) |
| 1008 | Staked Subblocks and Unsafe-Head BFT | |

WIP-1001 states it "MUST NOT activate until every parameter below is assigned in
fork configuration"; none are assigned in this tree, and `crates/node/src/node.rs:81-83`
describes `WorldChainTxEnvelope` as future work.

## Two allocation problems worth flagging

**Tx type `0x1D` is on a collision course.** Mainnet's typed-envelope allocations
grow upward from `0x04` (currently EIP-7702). `0x1D` = 29 sits directly in that
growth path. Compare OP Stack's `0x7e`, deliberately placed at the top of the legal
`0x00`–`0x7f` range precisely to avoid this. Draft-stage and cheap to change now.

**WIP-1004 places EdDSA at `0x0100` — an address that is already occupied.**
P256VERIFY lives there on World Chain today, inherited from OP Stack Fjord
(RIP-7212) and matching mainnet's EIP-7951. The spec never mentions the overlap, and
its rationale (`wip-1004.md:105`) rests on two premises that were true once and
aren't now:

> "Reserves a precompile slot above the Ethereum-reserved `0x01`–`0x0A` range and
> aligns with RIP-7212's convention of placing non-mainnet precompiles starting at
> `0x0100`."

Mainnet has reserved `0x01`–`0x11` since Prague (EIP-2537 BLS12-381), not `0x01`–`0x0A`.
And RIP-7212 *occupies* `0x0100`; it did not open the range above it. WIP-1001's
parameter table separately lists `BLS12_381_PRECOMPILE` as `TBD`, though BLS12-381
already exists at `0x0b`–`0x11` on this very chain — the same stale address map
showing through twice.

The spec does say the address "MAY be revised by maintainers before activation," so
this is a draft to fix, not shipped behaviour. It is recorded because it is exactly
the allocation-collision class this dataset exists to surface — and because it shows
how fast the "custom precompiles live far from mainnet" convention eroded once
`0x0100` itself became a mainnet address at Osaka.

## Transaction authorization: World ID does not authorize transactions

This is the axis where World Chain looks most likely to diverge and does not. Execution
is stock OP Stack, so secp256k1 is the only scheme that authorizes, `key_binding` is
`derived`, and `0x7e` deposits are unsigned — all of it inherited from op-stack, and the
row states no live delta.

The distinction matters because PBH *looks* like a second authorization scheme. It is
not. The semaphore proof travels in the `signature` field of an ERC-4337
`PackedUserOperation`, inside a bundle addressed to `PBHEntryPoint` — an ordinary
deployed contract. The builder's pool validator checks the proof only **after**
`inner.validate_one` has already accepted the transaction as a valid OP transaction,
i.e. after ordinary secp256k1 sender recovery has succeeded. The proof buys top-of-block
**priority**, not authority. It does not even reach `authorizes: account_code`: ERC-4337
is contract-level, so the protocol runs no account validator. And rollup-boost falls
back to the default EL's block if the builder returns an invalid one, so the builder
cannot make a proof authorize anything the EL would have rejected.

The one genuine proposal on this axis is **WIP-1001**, and it is a change of *kind*
rather than of curve: a `0x1D` envelope executed with a `WORLD_CHAIN_ACCOUNT_MANAGER`
account "framed as the sender", where an immutable EIP-1271 admin signer and a ring of
EIP-1271 session verifiers decide what a valid signature is. The spec states the
principle outright — no signer-specific authentication as a native execution path — so
if it ever ships, World Chain's `key_binding` becomes `account_code` for `0x1D` and stays
`derived` for everything else. Every activation parameter is still TBD, including the
EdDSA precompile address that collides with P256VERIFY. Recorded `pending`.

## Re-verify

```
git clone --depth 1 --branch v2.4.2 https://github.com/worldcoin/world-chain
cat crates/chainspec/src/hardfork.rs                 # Tropo / Strato
sed -n '570,585p' crates/chainspec/src/spec.rs       # ForkCondition::Never
sed -n '1,45p' specs/wips/wip-1001.md                # 0x1D
sed -n '/### Constants/,/### Scheme/p' specs/wips/wip-1004.md   # 0x0100 EdDSA
head -6 specs/pbh/architecture.md                    # rollup-boost, not EVM
grep -rn "precompile" --include="*.rs" crates/       # no custom precompile impls
```
