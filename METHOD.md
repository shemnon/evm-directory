# Method

Notes about *how the dataset is built and what it cannot hold*, rather than about what
any chain does. This material is deliberately repo-only: it is useful to someone
reading or extending the dataset, and it is not part of the published site.

The other two method documents are:

- [SCHEMA.md](SCHEMA.md) — the schema every `chains/<slug>/chain.yaml` is written in:
  the axes, the vocabularies, the evidence tiers, and the boundaries the schema draws
  (precompile vs. system contract, `stack` vs. `template`, `tombstoned` vs. `removed`).
- [SITE.md](SITE.md) — how `website/` is generated, what each page reads, and the CI
  gates that keep the tree honest.

The notes below were previously carried in [`findings.yaml`](findings.yaml) under
`axis: method` and rendered on the site. They are methodology, not chain data, so they
live here instead. Everything in `findings.yaml` now maps to one of the eight axes and
appears on the site.

## Axes the schema does not model

Some rows do not fit the schema's axes. Each is recorded explicitly rather than reduced
to a zero the schema can hold.

Arbitrum's Stylus runs WebAssembly alongside the EVM, so "no custom opcodes" is accurate
and omits a second virtual machine. Base's precompiles are not enumerable. opBNB has two
parents. Each is recorded explicitly rather than reduced to a zero the schema can hold.

| Chain | What the schema cannot hold |
|---|---|
| [Arbitrum](chains/arbitrum/) | Stylus runs WebAssembly alongside the EVM, so "no custom opcodes" is accurate and omits a second virtual machine. |
| [Base](chains/base/) | Base's precompiles are resolved by predicate and are not enumerable, so no address-keyed column can hold them. |
| [opBNB](chains/opbnb/) | opBNB has two parents — the OP Stack and BSC — and the lineage axis models one ancestry per kind. |

## Four of fifteen candidate clients were at the wrong address

The repository coordinates a chain publishes are not durable, and the drift is invisible
until a clone fails. Of fifteen chains scheduled in one pass, four were not where the
backlog said: `gnosischain/gnosis` **404s** (the live chainspec is inside Nethermind,
while `gnosischain/configs`' genesis is frozen pre-Merge),
`InjectiveLabs/injective-core` **moved orgs** to `InjectiveFoundation`,
`mantlenetworkio` **redirects** to `mantle-xyz`, and `0xPolygonHermez/zkevm-node` is
**archived** and replaced by a different client (`0xPolygon/cdk-erigon`) whose contracts
moved to a third org. Linea had already shown the pattern: Consensys → LFDT-Lineth,
hyperledger/besu → besu-eth. In three of the five cases the running network was
identified only by asking it — `web3_clientVersion` — rather than by reading a document.
Pinning a commit protects a fact once found; it does not help you find the client.

| Chain | Drift |
|---|---|
| [Gnosis](chains/gnosis/) | `gnosischain/gnosis` **404s**. The live chainspec is inside Nethermind, while `gnosischain/configs`' genesis is frozen pre-Merge. |
| [Injective](chains/injective/) | `InjectiveLabs/injective-core` **moved orgs**, to `InjectiveFoundation`. |
| [Mantle](chains/mantle/) | `mantlenetworkio` **redirects** to `mantle-xyz`. |
| [Polygon zkEVM](chains/polygon-zkevm/) | `0xPolygonHermez/zkevm-node` is **archived** and replaced by a different client, `0xPolygon/cdk-erigon`, whose contracts moved to a third org. |
| [Linea](chains/linea/) | Linea had already shown the pattern before this pass: Consensys → LFDT-Lineth, hyperledger/besu → besu-eth. Here as on three of the four others, the running network was identified by asking it — `web3_clientVersion` — rather than by reading a document. |

## A transaction ordered before it is executed has seven different fates

Mainnet checks nonce, balance and gas price *before* a transaction is ordered, so
"ordered but invalid" is not a state it can reach. Every chain that separates ordering
from execution has to invent an answer, and ten rows here have invented seven.
**Erasure, by four unrelated mechanisms:** Conflux defines a third receipt outcome,
`TransactionStatus::Skipped`, then deletes the transaction from the block, the
transaction index and `eth_getTransactionReceipt` alike; IOTA EVM rejects at the ISC
request layer before the EVM is entered, so there is no receipt to write; Artela emits
its indexing event from the *last* ante decorator, so an ante failure leaves the
CometBFT index with no entry while the transaction sits provably in the block; Rollkit's
builder logs a `warn!` and does not append. In all four,
`eth_getTransactionReceipt` returns null forever and the transaction is
indistinguishable from one never submitted. **Taraxa is the counter-pole:** no skip path
at all — included, charged the full gas limit, `status: 0`. **Autonomys escalates:** the
offending transaction poisons its whole `Bundle`, every valid co-passenger is dropped,
and the operator is automatically slashed under `SlashedReason::InvalidBundle`.
**Berachain rejects the block:** the EVM sits behind the Engine API, whose `newPayload`
verdict has no per-transaction skip, so `ProcessProposal` returns REJECT and the client
sees nothing at all. **RISE and MegaETH make the state unreachable**, by opposite
routes — RISE admits synchronously and publishes only after executing, MegaETH creates
the state inside the builder and resolves it before publication. **Monad charges it**,
inside execution. **Hedera bills it without ever executing it, and the bill may land on
the node**: fees are charged before the handler is reached, and the split is by *who was
negligent* rather than by what failed — a due-diligence failure (expiry re-checked
against the consensus clock, a bad payer signature) debits the submitting **node's**
account and the payer nothing, while a duplicate or an unaffordable service fee debits
the **payer** and never calls the handler. It is the only row where the node pays for
the sender's invalid transaction. A record always exists, because Hedera cannot drop
something that reached consensus — but for a wrapped Ethereum transaction the Ethereum
hash is written only inside the handler, so the `eth_*` view is null forever anyway.
There is no portable answer to "was my transaction included", and a null receipt means
"still pending" on some of these chains, "gone forever" on others, and "gone, and you
were charged" on one.

| Chain | Fate |
|---|---|
| [Conflux](chains/conflux/) | **Erases it.** A third receipt outcome, `TransactionStatus::Skipped`, then deletes the transaction from the block, the transaction index and `eth_getTransactionReceipt` alike — so it is indistinguishable from a transaction never submitted, forever. |
| [IOTA EVM](chains/iota-evm/) | **Erases it.** Rejection happens at the ISC request layer before the EVM is entered, so there is no receipt to write and none ever appears. |
| [Artela](chains/artela/) | **Erases it.** The indexing event is emitted from the *last* ante decorator, so an ante failure leaves the CometBFT index with no entry while the transaction sits provably in the block. |
| [Rollkit](chains/rollkit/) | **Erases it.** The builder logs a `warn!` and does not append; `eth_getTransactionReceipt` returns null forever. |
| [Taraxa](chains/taraxa/) | **The counter-pole:** no skip path at all. The transaction is included, charged the full gas limit, and gets a `status: 0` receipt. |
| [Autonomys](chains/autonomys/) | **Escalates.** The offending transaction poisons its whole `Bundle`, every valid co-passenger is dropped, and the operator is automatically slashed under `SlashedReason::InvalidBundle`. |
| [Berachain](chains/berachain/) | **Rejects the block.** The EVM sits behind the Engine API, whose `newPayload` verdict has no per-transaction skip, so `ProcessProposal` returns REJECT and the client sees nothing at all. |
| [RISE](chains/rise/) | **Makes the state unreachable** — it admits synchronously and publishes only after executing, so the ordered-but-invalid state never exists to be observed. |
| [MegaETH](chains/megaeth/) | **Makes the state unreachable** by the opposite route — the state is created inside the builder and resolved before publication. |
| [Monad](chains/monad/) | **Charges it**, inside execution. |
| [Hedera](chains/hedera/) | **Bills it without ever executing it, and the bill may land on the node.** Fees are charged before the handler is reached, and the split is by *who was negligent* rather than by what failed: a due-diligence failure (expiry re-checked against the consensus clock, a bad payer signature) debits the submitting **node's** account and the payer nothing, while a duplicate or an unaffordable service fee debits the **payer** and never calls the handler. It is the only row where the node pays for the sender's invalid transaction. A record always exists, because Hedera cannot drop something that reached consensus — but for a wrapped Ethereum transaction the Ethereum hash is written only inside the handler, so the `eth_*` view is null forever anyway. |
