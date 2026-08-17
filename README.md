# EVM-intel

A master table of EVM differences across major EVM chains, built from **pinned source
clones, not documentation**.

Tracks, per chain: custom transaction types, custom precompile addresses, custom
opcodes, predeploy/system contracts, gas & fee model, block/tx envelope fields,
upstream ancestry, and the **EIP activation set** — the last being the one that makes
the rest comparable.

## Generated tables

| File | What it answers |
|---|---|
| [MATRIX.md](MATRIX.md) | the chain × feature grid, plus every chain's gotchas |
| [PRECOMPILES.md](PRECOMPILES.md) | every address, every chain, what diverges |
| [TX-TYPES.md](TX-TYPES.md) | type bytes — and transactions that have none |
| [LINEAGE.md](LINEAGE.md) | ancestry tree and how each fork mapping was established |

## Method

**Ethereum Mainnet is the Schelling point.** Every other chain is described as a delta
against it, using one fixed vocabulary (`added` / `removed` / `modified` / `inherited`
/ `pending`). A chain that is genuinely EVM-equivalent produces a nearly empty file,
and that emptiness is a finding. See [SCHEMA.md](SCHEMA.md).

Fork names are recorded as *claims*; the `eips:` map is the *measurement*. "Prague-
equivalent" is not a fact — BSC took Prague's EVM half and dropped its beacon half.

Repos are cloned shallow and pinned to a **released tag**, so every finding is
reproducible. Each `SUMMARY.md` ends with the exact commands to re-verify it.

Where no client is public, a row is built from **live probes of the running network**
instead, pinned to a block height and marked `evidence: documented`. Such a row states
what the network *did*, not what a client *would* do — see [SCHEMA.md](SCHEMA.md).

## Status

| Chain | Client | Pinned | Baseline |
|---|---|---|---|
| [Ethereum Mainnet](chains/ethereum/SUMMARY.md) | go-ethereum | `v1.17.5` | Osaka (baseline) |
| [BNB Smart Chain](chains/bnb/SUMMARY.md) | bsc | `v1.7.8` | Osaka |
| [Polygon PoS](chains/polygon/SUMMARY.md) | bor | `v2.10.0` | Prague |
| [Avalanche C-Chain](chains/avalanche-c/SUMMARY.md) | coreth | `v0.16.0` | Cancun |
| [Avalanche subnet-evm](chains/avalanche-subnet/SUMMARY.md) *(template)* | subnet-evm | `v0.8.0` | Cancun |
| [Arbitrum One](chains/arbitrum/SUMMARY.md) | nitro | `v3.11.3` | Osaka (ArbOS 50) |
| [OP Stack](chains/op-stack/SUMMARY.md) *(stack node)* | op-geth | `v1.101702.2` | Osaka |
| [OP Mainnet](chains/optimism/SUMMARY.md) | op-geth | `v1.101702.2` | Osaka |
| [Base](chains/base/SUMMARY.md) | base-reth-node | `v1.2.0` | Osaka |
| [World Chain](chains/worldchain/SUMMARY.md) | world-chain builder | `v2.4.2` | Osaka |
| [opBNB](chains/opbnb/SUMMARY.md) | op-geth (BNB fork) | `v0.5.10` | Cancun |
| [Tron](chains/tron/SUMMARY.md) | java-tron | `GreatVoyage-v4.8.2.1` | Cancun (opcodes only) |
| [Hyperliquid](chains/hyperliquid/SUMMARY.md) *(documented)* | *none public* | live @ block `43436288` | pre-Prague (probed) |

## What the data shows

**Address collisions are real, shipped, and multiplying.** Arbitrum's ArbSys, ArbInfo,
ArbAddressTable, ArbBLS, ArbFunctionTable and ArbosTest occupy `0x64`–`0x69` — *exactly*
the six addresses BSC uses for its cross-chain and consensus precompiles. Two of the
largest EVM chains, no shared code, six identical addresses, unrelated functions.
opBNB makes `0x66` and `0x67` three-way. Polygon and BSC both put a contract called
`ValidatorContract` at `0x…1000`, with different code. Any tool holding one global
address-keyed map is wrong on some major chain.

**Two allocation frontiers are closing on each other.** Mainnet assigns transaction
type bytes upward from `0x04`. Chains assign downward from the `0x7f` ceiling:
Arbitrum `0x78`, Base `0x79`, OP Stack `0x7e`, Polygon `0x7f`. The legal range is
`0x00`–`0x7f` and there is no registry in between.

**Some precompiles cannot be listed at all.** Base installs a lookup that resolves
precompiles by *predicate over the address* — every `0xb2`-prefixed address matching
its B-20 pattern is a precompile, ~2^72 of them. An address-keyed table is
structurally incapable of representing this, so the schema records the predicate.

**"Runs the OP Stack" constrains almost nothing.** OP Mainnet's delta file is empty.
Base, on the same stack and the same client version, reimplements the EVM layer in
Rust, adds five fixed precompiles plus the dynamic range, native account abstraction
(EIP-8130) with its own tx type `0x79`, and four bespoke forks. opBNB, also on the OP
Stack, carries BSC's precompiles and is frozen three fork-generations back.

**Same-address divergence comes in four flavours,** each harder to detect than
enumeration: OP Stack **caps inputs** (call reverts), Avalanche **omits** (feature
absent), Polygon **reprices** (identical result, up to 22× the gas), Tron **replaces**
(`0x03` returns something that is not RIPEMD160).

**Fork activation has four incompatible mechanisms.** OP Stack enforces timestamp
equality at startup; Avalanche assigns timestamps; Arbitrum gates on ArbOS version and
ignores timestamps entirely; Polygon uses block numbers. "Read the fork timestamp"
fails on half the dataset.

**The schema keeps meeting axes it doesn't have.** Arbitrum's Stylus runs WebAssembly
beside the EVM — "no custom opcodes" is true and misses an entire second VM. Base's
precompiles aren't enumerable. opBNB has two parents. Each is recorded explicitly
rather than flattened into a convenient zero.

## What the first pass established

**Address enumeration is not enough.** OP Stack has **zero** custom precompile
addresses and **six** divergent precompiles — input caps on BN256/BLS12-381 (a
fault-proof constraint leaking into consensus) and P256VERIFY at half mainnet's gas.
Any survey that diffs address lists calls it equivalent and is wrong six times.

**`0x0100` was the one universal address — until it wasn't.** Twelve of thirteen rows
carry P256VERIFY there, arriving through four unrelated forks (mainnet Osaka, OP Stack
Fjord/RIP-7212, Avalanche Granite, Tron), and most diverge from mainnet's semantics or
gas. Presence proves nothing about lineage or fork level.

Hyperliquid breaks it: `0x0100` is **empty**, behaving exactly like an unallocated
address. That is worse than divergence. EIP-7951 signals *invalid signature* by
returning empty output, which is byte-identical to what a missing precompile returns —
so every P256 verification on that chain reports "invalid" forever, with no revert and
no error. A passkey wallet ported there is broken and looks merely strict. Establishing
this needed a *valid* signature and a mainnet control on identical calldata; the obvious
probe, calling the address and checking for output, cannot tell the two cases apart.

**Fork names lie in both directions.** BSC shipped Prague *seven weeks before mainnet*
and Osaka five months after. Avalanche has P256VERIFY (an Osaka feature) without
BLS12-381 (a Prague feature). OP Stack's precompile switch tests `IsOptimismJovian`
before `IsOsaka`, so activating Osaka never restores mainnet semantics.

**Some transactions have no type byte at all.** Avalanche's atomic import/export txs
(UTXO, Avalanche codec) and all 43 of Tron's protobuf contract types live outside
EIP-2718 entirely. Two independent chains forced the same `non_evm_transactions`
schema section. An indexer enumerating transactions through the EVM envelope misses
all cross-chain value movement on Avalanche.

**Placement discipline and semantic fidelity are independent.** Tron — the most
divergent chain here — put its 16 custom opcodes at `0xd0`–`0xdf`, which mainnet has
never allocated: perfectly safe. It also put `batchValidateSign` on BLAKE2F's `0x09`
and made `0x03` return something that is not RIPEMD160. Meanwhile BSC, the most
mainnet-faithful EVM, parked its customs at `0x64`–`0x69`, leaving only `0x12`–`0x63`
of headroom before mainnet grows into them.

**Precompile addresses are consumed permanently.** Avalanche's native-asset trio and
BSC's `0x64`/`0x65` (at Pasteur) are *tombstoned* — kept alive as always-reverting
stubs. Two chains arrived at the same pattern independently. Note this also fails
differently from an empty account, which returns success.

**Watch the fields that survive their feature.** OP Stack repurposed `blobGasUsed` to
carry the DA footprint; Avalanche pins the same field to zero and rejects anything
else. Same field, same JSON key, three meanings across the dataset.

## Layout

```
chains/<slug>/
  chain.yaml     structured facts — feeds the generated tables
  SUMMARY.md     findings, caveats, and re-verification commands
  repos/         pinned shallow clones (gitignored; evidence, not content)
tools/generate.py   regenerates the four top-level tables
```

## Tooling

```
tools/clone.sh      re-fetch the pinned evidence (gitignored) from chain.yaml
tools/verify.py     re-extract facts from source, diff against chain.yaml
tools/generate.py   regenerate the four top-level tables
```

`verify.py` is what keeps the "from source, not docs" claim honest. Facts reach
`chain.yaml` by a human reading a file once; the verifier re-reads the source and
reports drift in both directions:

- **MISSING** — declared in `chain.yaml`, absent from source (transcription error)
- **UNLISTED** — present in source, undeclared (coverage gap — the worse direction)
- **BAD SRC** — an evidence pointer that no longer resolves
- **PIN MISMATCH** — the clone is not at the recorded commit

It also fails if a tag has been moved upstream, which is why commits are pinned
alongside tags. All four failure modes are exercised; a verifier that cannot fail is
worse than none.
