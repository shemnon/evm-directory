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

**Pasteur went live on 2026-08-25 at block 117920136** (Chapel testnet: 2026-07-21). It
is meta-BEP-673: BEP-682 hardens `0x67`, BEP-695 replaces the StakeHub and Governor
bytecode, and `0x64`/`0x65` are tombstoned. All precompile facts below are read from
`PrecompiledContractsPasteur`, the active set. The row was re-verified on 2026-09-10
against the same `v1.7.8` pin — there is no newer stable release (`v1.8.0-alpha` is a
preview, and schedules no new fork).

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
| `0x64` | tmHeaderValidate | BNB Beacon Chain bridge. **Tombstoned at Pasteur** — every call returns `deprecated` |
| `0x65` | iavlMerkleProofValidate | revised 4× (base/Moran/Planck/Plato). **Tombstoned at Pasteur** |
| `0x66` | blsSignatureVerify | |
| `0x67` | cometBFTLightBlockValidate | Pasteur variant: rejects duplicate validators (BEP-682), 3000 + 16 gas/byte |
| `0x68` | verifyDoubleSignEvidence | consensus slashing evidence, exposed to the EVM |
| `0x69` | secp256k1SignatureRecover | distinct from `ECRECOVER` at `0x01` |

`0x64`–`0x69` is decimal 100–105, sitting **between** mainnet's occupied `0x01`–`0x11`
and `0x0100`. Mainnet allocates upward from `0x11`, leaving only `0x12`–`0x63` of
headroom before collision.

This is the placement risk predicted from the Ethereum baseline, actually realised.
Every other chain surveyed put customs at `0x0100…`, `0x0200…` or higher; BSC is the
one exception. And because `0x64`/`0x65` were **tombstoned rather than freed** at
Pasteur — `tmHeaderValidateDeprecated.Run` returns `errors.New("deprecated")`, and a live
`eth_call` at block 121193504 returns exactly that — those addresses are permanently
consumed. Same pattern as Avalanche's native-asset trio,
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

## What can authorize a transaction: nothing new, and that is the finding

`tx_authorization` on BSC is deliberately boring — secp256k1, one signer, address =
hash of the recovered key, `types.Sender` unmodified from geth. It is recorded anyway
because BSC handles **BLS in two places** and neither is what it looks like:

- **Parlia fast-finality votes** (`core/types/vote.go:VoteAttestation`) are BLS12-381
  signatures over block attestations. They finalise blocks. They cannot move a wei.
- **`blsSignatureVerify` at `0x66`** is a verifier *for contracts* — the BLS analogue
  of P256VERIFY at `0x0100`, and just as unable to authorize a sender.

There is no BSC transaction envelope that accepts a BLS signature.

### Parlia system transactions are signed — unlike OP's deposits

`applyTransaction` builds an ordinary **legacy** transaction and the proposer signs it
with its normal secp256k1 validator key. What is special-cased is the **recovered
address**, not the signature: `IsSystemTransaction` accepts one only when the recovered
sender equals `header.Coinbase`, the effective gas price is zero, and the destination is
a system contract. BSC and Monad sit on this side of the line; OP Stack's `0x7e`
deposits, which carry no signature at all, sit on the other.

## `block.prevrandao` returns 1 or 2, and `mixHash` is a clock

The most mainnet-faithful EVM in this dataset does not have PREVRANDAO. `0x44` pushes
the Parlia difficulty — 1 out of turn, 2 in turn. Verified live at block 121193504, after Pasteur:
`eth_call 0x445f5260205ff3` returns `0x…02`, while the same call on Ethereum mainnet
returns 32 bytes of randomness.

Three edits interact, and no one of them is the whole answer:

1. `NewEVMBlockContext` sets `Random = &header.MixDigest` only when
   `header.Difficulty.Sign() == 0`. Parlia never writes zero, so `Random` stays nil,
   and `Rules()` computes `isMerge = isMerge && c.IsLondon(num)` under a comment that
   says outright **`// always false in BSC`**.
2. Upstream gates `IsShanghai`/`IsCancun`/`IsPrague`/`IsOsaka` on `isMerge`, so that
   alone would switch off every fork after London. BSC re-enables them with
   `(isMerge || c.IsInBSC())`, where `IsInBSC()` is just `c.Parlia != nil`. PUSH0,
   MCOPY and transient storage all work; only `IsMerge` itself stays false.
3. And `newShanghaiInstructionSet` is built from `newLondonInstructionSet()`, where
   upstream geth builds it from `newMergeInstructionSet()`. The merge rung is bypassed
   in the **derivation chain**, so `opRandom` never enters a table BSC can select.
   `mergeInstructionSet` exists in the binary and is unreachable.

Step 3 is the one that actually decides it, and it is invisible from the fork list.

**Core reaches the identical observable by a third route.** It keeps upstream's
merge-based derivation — so its Prague table *does* carry `opRandom` — and then
explicitly rebinds `0x44` back to `opDifficulty` for Satoshi, in a function whose
comment reads *"reverts the PREVRANDAO opcode to DIFFICULTY opcode, as Satoshi doesn't
implement the PREVRANDAO opcode"*. Two chains, one answer, two mechanisms; only the
live probe shows they agree. See `chains/core/SUMMARY.md` §4.

### `mixHash` is not unused — it is validated

From Lorentz, `Prepare` calls `header.SetMilliseconds(blockTime % 1000)`, which stores
that value in `MixDigest`. It is checked in both directions:

```go
// before Lorentz
if header.MixDigest != (common.Hash{}) { return errInvalidMixDigest }
// after
if header.MilliTimestamp()/1000 != header.Time {
    return fmt.Errorf("invalid MixDigest, have %#x, expected the last two bytes to represent milliseconds", header.MixDigest)
}
```

So `mixHash` is a consensus-validated timestamp fraction in `[0, 999]`. At block
121193504 it was `0x352` = 850, with `timestamp` 1789098849 and `milliTimestamp`
1789098849850.

The RPC's `milliTimestamp` key is the honest reading of the field. What is not honest
is `mixHash` itself: a tool that reads it expecting post-merge randomness gets a small
integer that tracks block production. Third meaning for a repurposed header field in
this dataset, after OP Stack's `blobGasUsed` (DA footprint) and Avalanche's (pinned to
zero, and rejected if not).

This row previously carried no `src_live:` facts at all; it now has a `live_probe:`
block, because both of these are cheap to state from source and impossible to believe
from source alone.

## Re-verify

```
git clone --depth 1 --branch v1.7.8 https://github.com/bnb-chain/bsc
sed -n '353,380p' core/vm/contracts.go               # LIVE Pasteur set incl. 0x64-0x69
sed -n '/BSCChainConfig = /,/^	}/p' params/config.go  # fork timestamps
sed -n '1910,1935p' params/config.go                 # IsInBSC system contract split
sed -n '1,25p' core/systemcontracts/const.go         # 17 system contracts
sed -n '1111,1130p' core/systemcontracts/upgrade.go  # statedb.SetCode at forks
sed -n '139,150p' core/vm/contracts_lightclient.go   # deprecated => error
```

```bash
B=chains/bnb/repos/bsc

# PREVRANDAO: three edits, and the third is the one that decides it
grep -n -A3 'Difficulty.Sign() == 0' $B/core/evm.go
grep -n 'always false in BSC' $B/params/config.go
grep -n 'IsInBSC()) && c.Is' $B/params/config.go
grep -n -A3 '^func newShanghaiInstructionSet' $B/core/vm/jump_table.go                          # newLondonInstructionSet()
grep -n -A3 '^func newShanghaiInstructionSet' chains/ethereum/repos/go-ethereum/core/vm/jump_table.go  # newMergeInstructionSet()
curl -s -X POST https://bsc-dataseed.bnbchain.org -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"data":"0x445f5260205ff3"},"latest"]}'   # 0x..02
curl -s -X POST https://ethereum-rpc.publicnode.com -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"data":"0x445f5260205ff3"},"latest"]}'   # 32 bytes of randomness

# mixHash carries milliseconds, and consensus checks it
sed -n '1176,1181p' $B/consensus/parlia/parlia.go
sed -n '626,635p' $B/consensus/parlia/parlia.go
sed -n '161,173p' $B/core/types/block.go
curl -s -X POST https://bsc-dataseed.bnbchain.org -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["latest",false]}' \
  | python3 -c 'import sys,json;b=json.load(sys.stdin)["result"];print({k:b[k] for k in ("difficulty","mixHash","timestamp","milliTimestamp")})'

# Pasteur: 0x64/0x65 tombstoned, 0x67 hardened, StakeHub/Governor bytecode replaced
sed -n '446,462p' $B/core/vm/contracts_lightclient.go
sed -n '1062,1076p' $B/core/systemcontracts/upgrade.go
curl -s -X POST https://bsc-dataseed.bnbchain.org -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x0000000000000000000000000000000000000064","data":"0x00"},"latest"]}'   # error "deprecated"

# row check
tools/.venv/bin/python tools/verify.py bnb
tools/.venv/bin/python tools/livecheck.py bnb
```
