# BNB Smart Chain — mainnet-faithful EVM, everything else bolted on

**Chain ID 56 · role: `fork` · upstream: go-ethereum · baseline: Osaka**

Reference: [bnb-chain/bsc `v1.7.8`](https://github.com/bnb-chain/bsc) @ `cdb7548b`.

## Fork timing goes both directions

| Fork | BSC | Mainnet | Δ |
|---|---|---|---|
| Prague (BSC: Pascal) | 2025-03-20 | 2025-05-07 | **7 weeks EARLY** |
| Osaka (BSC: Mendel) | 2026-04-28 | 2025-12-03 | ~5 months late |

BSC shipped Prague **before Ethereum did**. "Behind mainnet" is not a stable property
of a chain — it flips fork to fork, which is a good reason for the matrix to carry
activation timestamps rather than a "current fork" label.

`BPO1Time` and `BPO2Time` are `nil` with the comment *"will be skipped in BSC"* — the
blob-parameter forks are explicitly declined.

**Pasteur activates 2026-08-25 — nine days from today and not yet live.** All
precompile facts below are read from `PrecompiledContractsOsaka`, the currently
active set, not from the newer Pasteur map in the same file.

## Prague, split cleanly down the middle

This is the sharpest demonstration in the dataset of why fork names can't be trusted.
`ActiveSystemContracts` (`params/config.go:1917-1923`) has an early-return branch:

```go
if c.IsInBSC() {
    if fork >= forks.Prague {
        active["HISTORY_STORAGE_ADDRESS"] = HistoryStorageAddress
    }
    return active          // <-- everything below is skipped
}
```

| Prague EIP | BSC |
|---|---|
| 2537 BLS12-381 | ✅ present at `0x0b`–`0x11` |
| 7702 SetCode | ✅ tx type `0x04` present |
| 2935 History storage | ✅ the one system contract kept |
| 4788 Beacon roots | ❌ dropped |
| 6110 Deposits | ❌ dropped |
| 7002 Withdrawals | ❌ dropped |
| 7251 Consolidations | ❌ dropped |

BSC takes Prague's EVM-facing half and drops the entire beacon/staking half, which is
meaningless without a beacon chain. A survey recording "BSC: Prague" would be wrong
about four EIPs.

## The most mainnet-faithful EVM here

Everything at `0x01`–`0x11` and `0x0100` matches mainnet Osaka *exactly*, down to the
feature flags:

- `bigModExp{eip2565: true, eip7823: true, eip7883: true}` — identical to mainnet
- `p256Verify{eip7951: true}` — mainnet gas, unlike OP Stack's 3450
- Transaction types `0x00`–`0x04`, including EIP-7702 — **zero tx-type divergence**,
  the only chain here that can say that

BSC and mainnet are the only two chains in this dataset with EIP-7702.

## Six custom precompiles — in the wrong place

| Addr | Name | Notes |
|---|---|---|
| `0x64` | tmHeaderValidate | BNB Beacon Chain bridge. **Tombstoned at Pasteur** |
| `0x65` | iavlMerkleProofValidate | revised 4× (base/Moran/Planck/Plato). **Tombstoned at Pasteur** |
| `0x66` | blsSignatureVerify | |
| `0x67` | cometBFTLightBlockValidate | currently the Hertz variant |
| `0x68` | verifyDoubleSignEvidence | consensus slashing evidence, exposed to the EVM |
| `0x69` | secp256k1SignatureRecover | distinct from `ECRECOVER` at `0x01` |

`0x64`–`0x69` is decimal 100–105, sitting **between** mainnet's occupied `0x01`–`0x11`
and `0x0100`. Mainnet allocates upward from `0x11`, leaving only `0x12`–`0x63` of
headroom before collision.

This is the placement risk predicted from the Ethereum baseline, actually realised.
Every other chain surveyed put customs at `0x0100…`, `0x0200…` or higher; BSC is the
one exception. And because `0x64`/`0x65` are being **tombstoned rather than freed** at
Pasteur — `tmHeaderValidateDeprecated.Run` returns `errors.New("deprecated")` — those
addresses are permanently consumed. Same pattern as Avalanche's native-asset trio,
independently arrived at.

## Client-rewritten system contract bytecode

BSC has **17 system contracts** at `0x…1000`–`1008`, `0x…2000`–`2006`, `0x…3000`
(validator set, slashing, cross-chain, staking, governance, timelock).

The mechanism is the interesting part. `TryUpdateBuildInSystemContract`
(`core/systemcontracts/upgrade.go:1111-1127`) calls **`statedb.SetCode`** at fork
boundaries, and the repo carries twenty per-fork bytecode directories (`bruno`,
`euler`, `gibbs`, `moran`, `planck`, `plato`, `luban`, `kepler`, `feynman`,
`haber_fix`, `bohr`, `pascal`, `lorentz`, `maxwell`, `fermi`, `pasteur`, …).

**Code at a fixed address changes with no transaction in any block.** On every other
chain in this dataset, bytecode at an address changes only by transaction. Any
indexer reconstructing contract history from transaction traces will silently miss
every one of these upgrades. Even EIP-2935's history contract is installed this way
(`upgrade.go:1117-1120`), with the code comment noting it is *"a special system
contract in bsc, which can't be upgraded"*.

## Block time

450 ms, arrived at by successive halving: 3000 ms default → 1500 ms (Lorentz) →
750 ms (Maxwell) → 450 ms (Fermi) (`consensus/parlia/parlia.go:61-64`). Consensus is
Parlia (Proof of Staked Authority), which inserts system transactions from the block
coinbase to system contracts.

## Re-verify

```
git clone --depth 1 --branch v1.7.8 https://github.com/bnb-chain/bsc
sed -n '324,352p' core/vm/contracts.go               # LIVE Osaka set incl. 0x64-0x69
sed -n '/BSCChainConfig = /,/^	}/p' params/config.go  # fork timestamps
sed -n '1910,1935p' params/config.go                 # IsInBSC system contract split
sed -n '1,25p' core/systemcontracts/const.go         # 17 system contracts
sed -n '1111,1130p' core/systemcontracts/upgrade.go  # statedb.SetCode at forks
sed -n '139,150p' core/vm/contracts_lightclient.go   # deprecated => error
```
