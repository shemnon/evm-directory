# opBNB — the chain with two parents

**Chain ID 204 · role: `fork` · upstream: [op-stack](../op-stack/SUMMARY.md) · baseline: Cancun**

Reference: [bnb-chain/op-geth `v0.5.10`](https://github.com/bnb-chain/op-geth) @ `1b995c36`.

This row exists to test whether a single-parent `upstream` field can describe a chain
shaped by two ecosystems. It cannot.

## BSC precompiles on an OP Stack chain

opBNB's codebase is op-geth. But its precompile map carries:

- `0x66` — **`blsSignatureVerify`**
- `0x67` — **`cometBFTLightBlockValidate`**

Those are BSC's precompiles, at BSC's addresses, with BSC's implementations. Its fork
names are BSC's too: **Fermat** and **Haber**, sitting alongside OP Stack's Canyon and
Ecotone in the same config.

So `upstream: op-stack` is true by code and incomplete in substance. The row records a
non-standard `second_heritage: bnb` key rather than silently dropping the fact — the
schema's lineage model assumes a tree, and this is a graph.

**These two addresses are now three-way collisions.** Arbitrum uses `0x66` for
`ArbAddressTable` and `0x67` for `ArbBLS`. Three chains, three unrelated meanings, two
shared addresses.

## A stale descendant

More consequential than the borrowed precompiles: opBNB is **far behind its own
upstream**. This client's newest OP branch is `IsOptimismFjord`. The op-stack row pins
op-geth `v1.101702.2`, which reaches Jovian and Karst.

opBNB therefore has **none** of OP Stack's Granite, Isthmus or Jovian changes — no
BN256 pairing cap, no BLS12-381 input caps, no Isthmus BLS variants, no repurposed
`blobGasUsed`. Two chains that both declare `upstream: op-stack` can be years apart in
actual behaviour.

This is a real limitation of the stack-node inheritance model: it resolves a
descendant against the *current* ancestor file, but a descendant pinned to an older
client inherits the ancestor's *past*. The row's `sync_point` says so explicitly; the
generated tables cannot yet express it, which is worth fixing before more OP-Stack
descendants are added.

## No Prague

`PragueTime` is `nil` in every opBNB config, and `SetCodeTxType` does not appear in
`core/types/transaction.go` at all — grep returns zero matches. So:

- **No EIP-7702**, no tx type `0x04`
- **No BLS12-381** at `0x0b`–`0x11`

opBNB is Cancun-equivalent, like Avalanche, and unlike its BSC cousin — which shipped
Prague *before Ethereum did*. Two chains in the same ecosystem, three fork generations
apart.

Fork times: Shanghai/Canyon and Cancun/Ecotone both activated 2024-06-20, twenty
minutes apart, alongside Haber.

## Transaction authorization: same answer, different fork

opBNB runs a *different* op-geth fork, so the authorization story is re-established from
its own clone rather than assumed — and it comes out identical. `recoverPlain` is the
only recovery routine, `londonSigner` short-circuits `DepositTxType` to the stored
`From` exactly as upstream does, and the txpool rejects deposits so they can only arrive
through the authenticated engine API. secp256k1 and the unsigned `0x7e` path are
inherited from op-stack verbatim and are not restated in the row.

Being stuck before Prague **narrows** this row rather than widening it: EIP-7702 is
absent from the client, so not even delegated account code can sit behind a signature
here.

The one opBNB-specific fact on the axis is the BSC-inherited `blsSignatureVerify` at
`0x66` — recorded as `authorizes: no` with a real precompile address. That is the
ordinary pairing: BLS signatures can be *verified* by contracts and can never authorize
a transaction. Same shape as P256VERIFY on mainnet, arrived at through a different
heritage.

## Re-verify

```
git clone --depth 1 --branch v0.5.10 https://github.com/bnb-chain/op-geth
grep -n "case rules.Is" core/vm/contracts.go          # newest OP branch is Fjord
grep -n "102\}\|103\}" core/vm/contracts.go           # 0x66, 0x67
sed -n '176,212p' params/config.go                    # chain 204, Fermat/Haber
grep -c SetCodeTxType core/types/transaction.go       # 0
```
