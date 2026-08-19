# Avalanche C-Chain — Cancun-equivalent, with P256 borrowed out of order

**Chain ID 43114 · role: `fork` · upstream: go-ethereum (via libevm) · baseline: Cancun**

Reference: [ava-labs/coreth `v0.16.0`](https://github.com/ava-labs/coreth) @ `64c271b4`.

## Headline: no Prague, no Osaka

`params/config_extra.go:82-89` assigns exactly two Ethereum fork times:

```go
c.ShanghaiTime = utils.NewUint64(*durango)
c.CancunTime   = utils.NewUint64(*etna)
```

There is **no `PragueTime` or `OsakaTime` assignment anywhere in the tree**. The
C-Chain is Cancun-equivalent. Consequences:

- **No EIP-7702.** Tx type `0x04` does not exist. The most consequential absence
  here for wallets and account-abstraction tooling.
- **No BLS12-381.** Precompiles `0x0b`–`0x11` are absent.
- No EIP-2935 history, no EIP-7002/7251 queues, no deposit contract — all Prague,
  and all meaningless without a beacon chain anyway.

## …yet P256VERIFY is present, via a different fork entirely

`PrecompiledContractsGranite` (`params/hooks_libevm.go:81-86`) adds P256VERIFY at
`0x0100` — through **Granite**, an Avalanche upgrade, not through Osaka.

So the C-Chain has `0x0100` but **not** `0x0b`–`0x11`, inverting mainnet's order:
mainnet shipped BLS12-381 at Prague, two forks *before* P256VERIFY at Osaka.
Inferring fork level from precompile presence fails in both directions on this chain.
This is the second chain in the dataset (after OP Stack) to hold `0x0100` under a
non-Osaka fork, which retires the idea that `0x0100` implies anything about lineage.

## Cancun adopted structurally, then hollowed out

Block validation (`plugin/evm/wrapped_block.go:478-487`) requires, once Cancun is active:

| Field | Constraint | Effect |
|---|---|---|
| `blobGasUsed` | must be `0` | `errBlobsNotEnabled` |
| `excessBlobGas` | must be `0` | no blob fee market |
| `parentBeaconRoot` | must be the **empty hash** | no beacon chain to root |

The header conforms to Cancun's shape while every Cancun-specific field is pinned to
a constant. Blob transactions (`0x03`) exist as a libevm type but can never be
included.

Worth contrasting with OP Stack, which took the *same* field, `blobGasUsed`, and
**repurposed** it to mean DA footprint. Two chains, one field, three meanings across
the dataset. Anyone reading `blobGasUsed` cross-chain needs a per-chain decoder.

## Three tombstoned precompile addresses

| Address | Was | Now |
|---|---|---|
| `0x0100…0000` | GenesisContract | always reverts |
| `0x0100…0001` | NativeAssetBalance | always reverts |
| `0x0100…0002` | NativeAssetCall | always reverts |

Live in Apricot Phase 2, again in Phase 6, tombstoned at Banff. `DeprecatedContract`
returns `vm.ErrExecutionReverted` unconditionally (`nativeasset/contract.go:167-171`).

These addresses are **permanently consumed** — they can be neither reused nor
removed, only made to fail. And they fail *differently* from an empty account:
calling an address with no code succeeds and returns nothing; calling these reverts.
A contract probing for feature support gets opposite answers.

## Warp: a precompile with no mainnet analogue

`0x0200…0005` is the Avalanche Warp Messaging precompile (Durango). It reads **block
predicates** via `GetPredicateResults` — results computed outside normal EVM
execution and made available to the precompile. There is no mainnet equivalent to
this mechanism, so it is not expressible as a delta on any Ethereum concept.

Note the two separate custom ranges — `0x0100…00-02` and `0x0200…05` — both far from
mainnet's `0x01`–`0x11`. Avalanche followed the placement convention.

## Atomic transactions live outside the envelope

`UnsignedImportTx` and `UnsignedExportTx` (`plugin/evm/atomic/`) move value between
the C-Chain and Avalanche's X/P chains. They are **UTXO-based, serialised with
Avalanche's own codec, not RLP**, and registered in a separate codec namespace
(`codec.go:33-34`) — entirely outside EIP-2718 while still included in C-Chain blocks.

They have no type byte, so they cannot be represented in `tx_types` at all. This
forced a new `non_evm_transactions` section in the schema. An indexer that enumerates
"all transactions in a block" through the EVM envelope silently misses **all
cross-chain value movement on the C-Chain**.

## Architecture note

coreth v0.16.0 is **not** a whole-repo geth fork. It consumes `ava-labs/libevm` — a
geth fork published as a library with explicit extension hooks — and layers Avalanche
behaviour through `RulesExtra` hooks in `params/hooks_libevm.go`. This is the
cleanest fork relationship in the dataset: divergence is concentrated in hook
implementations rather than scattered through a patched tree, which is why the
precompile deltas above could be read off a single 90-line file.

## Fees

London is active (`LondonBlock = 0` from Apricot Phase 3), so 1559-shaped fields
exist, but the base-fee update rule is Avalanche's own ACP-176 target-gas-excess
mechanism (`consensus/dummy/consensus.go:79`), not mainnet's.

## Two authorization models, one chain

The C-Chain is the only row in this cluster where *how a transaction is authorized*
depends on which kind of transaction it is.

**EVM transactions** are mainnet's: `TransactionToMessage` → libevm's `types.Sender`,
secp256k1, one signer, address = hash of the recovered key.

**Atomic transactions** — the import/export pair already recorded in
`non_evm_transactions` — use the same *curve* and nothing else in common:

| | EVM transaction | atomic transaction |
|---|---|---|
| signed payload | RLP, EIP-155/2718 envelope | Avalanche codec, unsigned-tx bytes |
| digest | keccak256 | `hashing.ComputeHash256` |
| signature block | one `(v, r, s)` | `Tx.Creds` — a **list of credentials**, one per input, each a list of signatures |
| signers | 1 | one per input, and *m* per m-of-n threshold UTXO |
| key binding | derived | derived on export, **declared** on import |

On **export**, each `EVMInput` carries its own `Address` and needs exactly one signature,
recovered against `utx.Bytes()` and matched with `pubKey.EthAddress()`. Five inputs owned
by five accounts is one transaction with five independent signers — something the EVM
envelope cannot express at all.

On **import**, credentials are checked by `Fx.VerifyTransfer` against the source-chain
UTXO's own `secp256k1fx` output owners: an **m-of-n threshold multisig declared on the X-
or P-Chain**, not derived from any C-Chain address.

### Not an unpaired scheme — stated so nobody has to re-derive it

The scheme is still secp256k1 ECDSA and `0x01` still verifies secp256k1 ECDSA, so this is
*not* the `authorizes: protocol` + `precompile: none` case. The catch is the digest: a
contract wanting to check an atomic credential has to reconstruct Avalanche codec bytes
and hash them with `ComputeHash256` (in avalanchego, outside the pinned clone) rather than
keccak an RLP envelope.

### Warp's BLS is consensus signing

The aggregated BLS12-381 signature on a Warp message is verified by
`Config.VerifyPredicate` — a **block predicate evaluated outside EVM execution**. The
precompile at `0x0200…05` only reads the result. It authorizes a *message*, never a
transaction, and it is not a general-purpose BLS verifier a contract can point at
arbitrary signatures.

## Re-verify

```
git clone --depth 1 --branch v0.16.0 https://github.com/ava-labs/coreth
sed -n '55,110p' params/hooks_libevm.go              # precompile sets + Granite
sed -n '80,92p' params/config_extra.go               # Shanghai=Durango, Cancun=Etna
grep -rn "PragueTime\|OsakaTime" --include="*.go" .  # (empty)
sed -n '165,172p' nativeasset/contract.go            # DeprecatedContract reverts
sed -n '475,490p' plugin/evm/wrapped_block.go        # blob/beacon-root constraints
sed -n '20,26p' precompile/contracts/warp/module.go  # warp address
```
