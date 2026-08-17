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

## Status

| Chain | Client | Pinned | Baseline |
|---|---|---|---|
| [Ethereum Mainnet](chains/ethereum/SUMMARY.md) | go-ethereum | `v1.17.5` | Osaka (baseline) |
| [BNB Smart Chain](chains/bnb/SUMMARY.md) | bsc | `v1.7.8` | Osaka |
| [Avalanche C-Chain](chains/avalanche-c/SUMMARY.md) | coreth | `v0.16.0` | Cancun |
| [Avalanche subnet-evm](chains/avalanche-subnet/SUMMARY.md) | subnet-evm | `v0.8.0` | Cancun |
| [OP Stack](chains/op-stack/SUMMARY.md) *(stack node)* | op-geth | `v1.101702.2` | Osaka |
| [World Chain](chains/worldchain/SUMMARY.md) | world-chain builder | `v2.4.2` | Osaka |
| [Tron](chains/tron/SUMMARY.md) | java-tron | `GreatVoyage-v4.8.2.1` | Cancun (opcodes only) |

## What the first pass established

**Address enumeration is not enough.** OP Stack has **zero** custom precompile
addresses and **six** divergent precompiles — input caps on BN256/BLS12-381 (a
fault-proof constraint leaking into consensus) and P256VERIFY at half mainnet's gas.
Any survey that diffs address lists calls it equivalent and is wrong six times.

**`0x0100` is the one universal address, and it means something different everywhere.**
All seven rows have P256VERIFY there, arriving through four unrelated forks — mainnet
Osaka, OP Stack Fjord (RIP-7212), Avalanche Granite, and Tron. Five of the seven
diverge from mainnet's semantics or gas. Presence proves nothing about lineage or
fork level.

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
