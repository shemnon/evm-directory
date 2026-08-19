# Arbitrum One — the most divergent non-independent chain

**Chain ID 42161 · role: `fork` · upstream: go-ethereum (OffchainLabs fork) · baseline: Osaka (ArbOS 50)**

Reference: [OffchainLabs/nitro `v3.11.3`](https://github.com/OffchainLabs/nitro), with the
pinned `go-ethereum` submodule at `f3a966e6`. EVM facts come from the submodule, ArbOS
facts from nitro.

## The headline: a six-address collision with BSC

`go-ethereum/core/types/arbitrum_signer.go` places Arbitrum's system precompiles at
`0x64` upward. BSC's custom precompiles occupy the same range:

| Addr | Arbitrum | BNB Smart Chain |
|---|---|---|
| `0x64` | ArbSys | tmHeaderValidate |
| `0x65` | ArbInfo | iavlMerkleProofValidate |
| `0x66` | ArbAddressTable | blsSignatureVerify |
| `0x67` | ArbBLS | cometBFTLightBlockValidate |
| `0x68` | ArbFunctionTable | verifyDoubleSignEvidence |
| `0x69` | ArbosTest | secp256k1SignatureRecover |

**Six consecutive addresses, two of the largest EVM chains, no shared code, entirely
unrelated functions.** This was a hypothesis before batch 2 and it is now read from
source on both sides. It is a total overlap — BSC's *entire* custom precompile range
is contained in Arbitrum's.

opBNB makes it a three-way tie on two of them: it carries BSC's `blsSignatureVerify`
at `0x66` and `cometBFTLightBlockValidate` at `0x67` on top of OP Stack.

Any tool holding a single global precompile map keyed by address — a decompiler, a
trace decoder, a security scanner — is wrong on at least one major chain.

## Nineteen custom precompiles, seven custom transaction types

Both the largest counts in the dataset. Beyond `0x64`–`0x69`: `ArbOwnerPublic`
(`0x6b`), `ArbGasInfo` (`0x6c`), `ArbAggregator` (`0x6d`), `ArbRetryableTx` (`0x6e`),
`ArbStatistics` (`0x6f`), `ArbOwner` (`0x70`), `ArbWasm` (`0x71`), `ArbWasmCache`
(`0x72`), `ArbNativeTokenManager` (`0x73`), `ArbFilteredTransactionsManager` (`0x74`),
`NodeInterface` (`0xc8`), `NodeInterfaceDebug` (`0xc9`), `ArbDebug` (`0xff`).

Transaction types (`core/types/transaction.go:48-54`):

| Type | Name |
|---|---|
| `0x64` | ArbitrumDepositTx |
| `0x65` | ArbitrumUnsignedTx |
| `0x66` | ArbitrumContractTx |
| `0x68` | ArbitrumRetryTx |
| `0x69` | ArbitrumSubmitRetryableTx |
| `0x6A` | ArbitrumInternalTx |
| `0x78` | ArbitrumLegacyTx |

Note `0x67` is skipped. And note the reading hazard: **`0x64`–`0x69` are
simultaneously precompile addresses and transaction type bytes on this chain.**
Separate namespaces, so no actual conflict — but a genuine trap when reading traces.

Several of these are unsigned and protocol-inserted, so the sender-recovery
assumption breaks the same way it does for OP Stack deposits, across six more type
bytes rather than one.

## Fork mapping: a third mechanism

Arbitrum ignores fork timestamps entirely. `go-ethereum/params/config.go:837-867`:

```go
func (c *ChainConfig) IsCancun(num *big.Int, time uint64, currentArbosVersion uint64) bool {
	if c.IsArbitrum() {
		return currentArbosVersion >= ArbosVersion_20
	}
	return c.IsLondon(num) && isTimestampForked(c.CancunTime, time)
}
```

| Ethereum fork | Gate |
|---|---|
| Shanghai | ArbOS ≥ 11 |
| Cancun | ArbOS ≥ 20 |
| Prague | ArbOS ≥ 40 |
| Osaka | ArbOS ≥ 50 |

`CancunTime` is never consulted on an Arbitrum chain. Upgrades happen by ArbOS
version bump through on-chain governance, so there is no activation timestamp to
record at all. That makes four distinct fork-mapping mechanisms across the dataset:

- **OP Stack** — startup-enforced timestamp *equality* (`CancunTime == EcotoneTime`)
- **Avalanche** — direct assignment (`c.CancunTime = etna`)
- **Arbitrum** — version gate, timestamps ignored
- **Polygon** — block numbers, not timestamps

`MaxArbosVersionSupported` in this release is ArbOS 61.

## Stylus breaks the opcode axis

`chain.yaml` records zero opcode changes, which is true and misleading. Stylus
(ArbOS 30) runs **WebAssembly contracts alongside the EVM**, priced in "ink" rather
than gas. There is no second jump table to diff — there is a second virtual machine.

A survey that compares opcode sets reports "no opcode divergence" and misses an
entire execution environment. This is the clearest case yet that the axes chosen for
this dataset are mainnet-shaped, and a chain can diverge in a direction the schema
has no column for. Recorded explicitly in `opcodes.note` rather than left as a silent
zero.

## Stylus and the `0xEF` reserved byte

Stylus code is identified in state by an **`0xEF 0xF0`** prefix
(`go-ethereum/core/state/statedb_arbitrum.go:49-62`). EIP-3541 reserved a leading
`0xEF` for EOF, and mainnet's EOF format is `0xEF00`.

The offset to `0xF0` looks deliberate — Arbitrum claimed a sub-range that EOF does
not use. So this is a considered claim on reserved space rather than an accident,
which contrasts sharply with the `0x64` precompile range. As with Tron's
collision-free opcodes and colliding precompiles, **placement discipline is uneven
within a single chain**: the same team can be careful in one namespace and careless
in another.

## Fees

L2 gas pricing is ArbOS's speed-limit mechanism, plus a separate L1 data-posting
charge (`arbos/l1pricing/`). Multi-dimensional gas constraints arrived in ArbOS 50
(single) and ArbOS 60 (multi) — a metering model with no mainnet analogue. Stylus
execution is metered in ink, with activation gas charged from ArbOS 60.

## Six of the seven transaction types are not signed at all

Arbitrum has the most custom transaction types in the dataset and only **one** signature
scheme. For `0x00`–`0x04`, `arbitrumSigner` falls through to go-ethereum's `Sender` and
authorization is mainnet's exactly.

For the other six, `arbitrumSigner.Sender` returns `inner.From` **verbatim** and
`SignatureValues` returns `(0, 0, 0)`:

| Type | Sender comes from |
|---|---|
| `0x64` `ArbitrumDepositTx` | L1 inbox message header `Poster` |
| `0x65` `ArbitrumUnsignedTx` | L1 `poster` |
| `0x66` `ArbitrumContractTx` | L1 `poster` |
| `0x68` `ArbitrumRetryTx` | retryable's stored `From` |
| `0x69` `ArbitrumSubmitRetryableTx` | L1 `poster` |
| `0x6A` `ArbitrumInternalTx` | the constant `ArbosAddress` (`0xa4b05`) |

The authorization is real, it just lives **one layer down**: the L1 transaction that
produced the inbox message was authorized on Ethereum by Ethereum's own secp256k1. ArbOS
enforces the separation from the other side too — `L2MessageKind_SignedTx` rejects any
type `>= ArbitrumDepositTxType`, so the signed set and the protocol set never overlap.
Same category as OP Stack's `0x7e`; the opposite of Monad, whose system transactions carry
a real signature.

A seventh case is different again: `ArbitrumLegacyTx` (`0x78`) carries an optional
`Sender *common.Address` "only used in unsigned Txs", returned without recovery when set —
the one place on this chain where `ecrecover(sig) != from` by construction, in pre-Nitro
historical data.

### `ArbBLS` at `0x67` is an empty stub

It is described as "a registry of BLS public keys for accounts", and in the pinned tree
the struct declares **nothing but its own `Address` field** — no methods, so there is no
BLS verification reachable behind it either. Even fully implemented it would not authorize
anything: nothing in `arbitrumSigner` or ArbOS consults such a registry when deciding who
sent a transaction. Recorded as `authorizes: never` precisely because "chain has a BLS
precompile" is the observation that gets misread as "chain accepts BLS-signed
transactions".

## Re-verify

```
git clone --depth 1 --branch v3.11.3 https://github.com/OffchainLabs/nitro
cd nitro && git submodule update --init --depth 1 go-ethereum
grep "^var Arb" go-ethereum/core/types/arbitrum_signer.go     # 19 precompiles
sed -n '48,54p' go-ethereum/core/types/transaction.go          # 7 tx types
sed -n '837,867p' go-ethereum/params/config.go                 # ArbOS version gates
sed -n '45,62p' go-ethereum/params/config_arbitrum.go          # ArbOS constants
sed -n '49,62p' go-ethereum/core/state/statedb_arbitrum.go     # Stylus 0xEFF0
```
