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
live here instead. A third, `ordered-then-invalid`, went the other way: it turned out to
be chain data rather than methodology, and is now the `ordering` axis. Everything left in
`findings.yaml` maps to one of the nine axes and appears on the site.

## Axes the schema does not model

Some rows do not fit the schema's axes. Each is recorded explicitly rather than reduced
to a zero the schema can hold.

Arbitrum's Stylus runs WebAssembly alongside the EVM, so "no custom opcodes" is accurate
and omits a second virtual machine. Base's precompiles are not enumerable. opBNB has two
parents. Blast's accounts have no balance field. Each is recorded explicitly rather than
reduced to a zero the schema can hold.

The fourth is the first that is about **state** rather than about execution, and it is
the one worth watching: an axis the schema does not model can still be caught by an
extractor or a live probe as long as it is *addressed* — a precompile, a type byte, a
header field. Blast's is not addressed at all. It was found by reading a struct
definition, and confirmed only because `eth_getProof` happens to expose the account's
shape over JSON-RPC.

| Chain | What the schema cannot hold |
|---|---|
| [Arbitrum](chains/arbitrum/) | Stylus runs WebAssembly alongside the EVM, so "no custom opcodes" is accurate and omits a second virtual machine. |
| [Base](chains/base/) | Base's precompiles are resolved by predicate and are not enumerable, so no address-keyed column can hold them. |
| [opBNB](chains/opbnb/) | opBNB has two parents — the OP Stack and BSC — and the lineage axis models one ancestry per kind. |
| [Blast](chains/blast/) | The consensus **account** is not Ethereum's. `types.StateAccount` is `{Nonce, Flags, Fixed, Shares, Remainder, Root, CodeHash}` — seven RLP items with no `Balance` — and a balance is computed from a share price held in one predeploy's storage. The schema has axes for opcodes, precompiles, transactions, headers and fees, and none for the state representation those all operate on, so the fact is carried in `gotchas` and in an `eips.1186` entry about `eth_getProof` rather than in a section of its own. |

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
