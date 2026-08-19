# Avalanche subnet-evm — a chain *template*, not a chain

**No fixed chain ID · role: `fork` · sibling of coreth · baseline: Cancun**

Reference: [ava-labs/subnet-evm `v0.8.0`](https://github.com/ava-labs/subnet-evm) @ `44b20d21`.

## The central caveat

subnet-evm is instantiated per Avalanche L1/Subnet, and **its custom precompiles are
opt-in through genesis config keys**. Two chains running subnet-evm can present
entirely different EVMs. "Runs subnet-evm" therefore tells you very little — the
genesis config is the actual specification.

This is a category the matrix has to represent honestly: every precompile below is
`status: added, activation: opt-in`, never simply "present."

## The EVM can be permissioned

This is subnet-evm's sharpest divergence from every other chain in the dataset, and
it isn't a precompile or an opcode — it's a pair of hooks that change whether
operations **succeed**:

- **`CanCreateContract`** (`params/hooks_libevm.go:44-56`) — with
  `ContractDeployerAllowList` enabled, `CREATE`/`CREATE2` fail for unauthorised
  callers, gas zeroed. Permission is keyed on **`tx.origin`**, not `msg.sender`, so
  a factory contract's ability to deploy depends on who *initiated* the transaction.
- **`TxAllowList`** (`core/state_transition.go:361`) — gates transaction execution
  on the sender.

Mainnet has no concept of either. Both live outside the jump table and outside the
precompile map, which is why an audit that diffs only opcodes and precompile
addresses would miss them entirely — the same lesson OP Stack taught from a
different direction.

## Six stateful precompiles, contiguous at `0x0200…`

| Address | Name | Effect |
|---|---|---|
| `0x0200…0000` | ContractDeployerAllowList | gates `CREATE` on `tx.origin` |
| `0x0200…0001` | ContractNativeMinter | **mints native coin** via `stateDB.AddBalance` |
| `0x0200…0002` | TxAllowList | gates tx execution on sender |
| `0x0200…0003` | FeeManager | rewrites the fee config at runtime |
| `0x0200…0004` | RewardManager | redirects or burns fee rewards |
| `0x0200…0005` | Warp Messenger | cross-L1 messaging (same address as C-Chain) |

`ContractNativeMinter` (`contract.go:125`) lets allowlisted accounts mint native coin
arbitrarily. Together with OP Stack's `DepositTx.Mint`, that's two of the six rows in
this dataset where native supply moves outside block rewards — worth a dedicated
column in the matrix.

`FeeManager` means the **fee model is not a fixed property of the chain**: allowlisted
accounts rewrite the fee schedule mid-flight. `chain.yaml`'s `fee_model` section
describes a default, not an invariant.

## Cleaner than its sibling

subnet-evm has **no** `0x0100…0000-02` native-asset precompiles. It never carried
that legacy, so it avoids the three tombstoned always-reverting addresses the C-Chain
is stuck with — the more configurable of the two siblings has the tidier address map.

Otherwise the two match: same libevm base, same `RulesExtra` hook architecture, same
`ShanghaiTime = durango` / `CancunTime = etna` mapping, same absent Prague and Osaka,
and the same P256VERIFY at `0x0100` delivered by **Granite** rather than Osaka.

So: no EIP-7702, no tx type `0x04`, no BLS12-381 at `0x0b`–`0x11`.

## Why this is a separate row from the C-Chain

They are siblings, not parent and child. Shared base, shared fork mapping, shared
`0x0200…` range — but disjoint precompile sets in both directions (C-Chain has the
tombstoned legacy trio; subnet-evm has the six stateful modules). Merging them would
force every precompile row to carry a second "which one?" axis, exactly the overload
the delta vocabulary is meant to avoid.

## Configurable everywhere except in the signing path

A `template` row invites the question "which of these is per-deployment?" — and on
`tx_authorization` the answer is **none of it**. No genesis key selects a signature
scheme, no opt-in precompile adds one, and every subnet-evm chain recovers senders
through libevm's `types.Sender` exactly as mainnet does. Compare Tron, where a node-config
key really does swap the curve out from under `ecrecover`.

What *is* per-deployment is **who** may transact, not **what** may sign. With
`txAllowListConfig` in genesis, `state_transition` rejects a transaction whose
already-recovered `msg.From` is not allowlisted (`ErrSenderAddressNotAllowListed`). That
is an authorization *restriction* applied after recovery, in the same place a nonce or
balance check happens — not an authorization *method*.

Two absences worth stating explicitly, because the sibling row has both:

- **No atomic transactions.** There is no `plugin/evm/atomic` tree here, so none of the
  C-Chain's UTXO-credential multi-signer model exists.
- **Warp's BLS12-381 is consensus signing**, opt-in per deployment (`warpConfig`), and
  verified in a block predicate outside EVM execution. It authorizes a *message*.

## Re-verify

```
git clone --depth 1 --branch v0.8.0 https://github.com/ava-labs/subnet-evm
grep -rn "ContractAddress = common.HexToAddress" precompile/contracts/*/module.go
sed -n '44,62p' params/hooks_libevm.go               # CanCreateContract allowlist
sed -n '358,366p' core/state_transition.go           # TxAllowList
sed -n '120,128p' precompile/contracts/nativeminter/contract.go   # native mint
sed -n '73,84p' params/config_extra.go               # Shanghai=Durango, Cancun=Etna
```
