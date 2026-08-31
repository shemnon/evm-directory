# Cosmos EVM (`evmd`)

**Role:** `template` · **Upstream:** `ethereum` · **Chain ID:** *none — not a chain* ·
**Baseline:** Prague
**Client:** [`cosmos/evm`](https://github.com/cosmos/evm) `v0.7.2`
(`ef11f63c087b4c859b1e8eddc823f7cf2113a50a`) ·
**Companion:** [`cosmos/go-ethereum`](https://github.com/cosmos/go-ethereum)
`v1.17.2-cosmos-0` (`d99d6fa2c8d98b7cd653de4a9386d2da3db8f25c`)
**Live probes:** none. This row is not a chain, so it rests on `src:` alone.

`cosmos/evm` is the Cosmos SDK's EVM framework: three modules (`x/vm`, `x/erc20`,
`x/feemarket`), an ante chain, a precompile kit and a JSON-RPC shim, plus `evmd`,
which the repo itself labels "the example chain implementation". The Injective row
([`chains/injective/`](../injective/chain.yaml)) is the first deployment measured
against it.

## Why `template`, not `stack`

SCHEMA.md separates the two on whether descendants inherit wholesale. Here they
cannot, and the decisive line is one word long:

```go
// x/vm/types/params.go
DefaultStaticPrecompiles []string      // declared with NO value — nil
```

Out of the box **zero** custom precompiles are active. What turns them on is the
deployment's genesis assigning `Params.ActiveStaticPrecompiles`, and `evmd` does that
only as an example (`evmd/genesis.go:NewEVMGenesisState`). Registration is
deliberately two-step — a precompile must be *both* built into the keeper's map at
app-wiring time *and* named in the module param — and the param is subsequently
governance-mutable. The same is true of the EVM denom and its decimals, the EVM chain
id, the fork schedule, the opcode access-control policy, the extra-EIP opcode
repricings and the entire fee market (which `evmd`'s own genesis *disables*).

There is no canonical mainnet here whose deltas a descendant simply inherits — which
is exactly the distinction SCHEMA.md draws against `stack`. So the row is `template`
and almost every entry carries `availability: optional`. It is the second template in
the dataset after subnet-evm, and it varies strictly more: subnet-evm lets a
deployment choose *what exists at an address*; Cosmos EVM additionally lets it choose
*what an opcode costs and whether it runs at all*.

## 1. The `non_evm_transactions` category, inverted

SCHEMA.md defines that section as "protocol transactions with **no EIP-2718 type byte
at all**". Cosmos EVM turns it inside out: an EIP-2718 transaction that is itself
wrapped in something with no type byte.

```protobuf
// proto/cosmos/evm/vm/v1/tx.proto
message MsgEthereumTx {
  reserved 1, 2, 3, 4;
  bytes from = 5;
  bytes raw  = 6 [ (gogoproto.customtype) = "EthereumTx", (gogoproto.nullable) = false ];
}
```

A user signs an ordinary RLP `0x02`. A node wraps it in `MsgEthereumTx`, inside a
Cosmos SDK `TxBody`; **that** is what CometBFT hashes and orders. Two hashes exist for
one transaction — keccak of the inner bytes, sha256 of the outer wrapper — and the
proto's own comment says so.

**How this differs from the two existing precedents, which matters:**

| | encoding that reaches consensus | is the Ethereum envelope recoverable? |
|---|---|---|
| Tron | protobuf, 43 contract types | no — there is no RLP anywhere |
| Sei | protobuf `MsgEVMTransaction` with the fields **re-encoded** as protobuf `TxData` | no — the RLP bytes do not survive |
| **Cosmos EVM v0.7** | protobuf `MsgEthereumTx` with `raw` = **the untouched envelope** | **yes, byte-exact** |

`x/vm/types/eth.go:EthereumTx.Unmarshal` is literally geth's
`Transaction.UnmarshalBinary`. The `reserved 1, 2, 3, 4` in the proto records that the
older Sei-style field-by-field encoding was *removed* to get here. So this is the same
family as Tron and Sei and a genuinely different point in it: the envelope survives,
one protobuf field down.

A consequence worth stating plainly: the outer Cosmos transaction carries its own fee,
gas limit and signer list, all filled in from the inner transaction by
`x/vm/types/msg.go:BuildTxWithEvmParams`, **none** of them covered by the Ethereum
signature. Authorization is entirely the inner envelope's.

## 2. EIP-2935 is written at 8192 and read at 8191

The framework preinstalls mainnet's history contract — same address, same bytecode,
copied from `params.HistoryStorageAddress` / `params.HistoryStorageCode`
(`x/vm/types/preinstall.go:DefaultPreinstalls`). That bytecode indexes its ring buffer
with the constant `0x1fff` = **8191**.

It is never invoked. `BeginBlock` writes the slot itself:

```go
// x/vm/keeper/keeper.go:SetHeaderHash
window := uint64(types.DefaultHistoryServeWindow)   // 8192, commented "same as EIP-2935"
ringIndex := uint64(ctx.BlockHeight()) % window
k.SetState(ctx, ethparams.HistoryStorageAddress, key, ctx.HeaderHash())
```

Geth's own constant is 8191
(`go-ethereum/params/protocol_params.go:HistoryServeWindow`). `BLOCKHASH` is
self-consistent because `GetHeaderHash` reads back through the same 8192 window — but
a **contract** that calls the history contract, the portable way to read block hashes
deeper than 256, computes `n % 8191` and reads a slot written for a different height.
It gets a real, wrong, 32-byte hash with no revert and no error.

Two further deltas on the same entry: the stored value is a CometBFT header hash, not
an Ethereum block hash; and the window is a governance parameter, so `BLOCKHASH`
reaches 32× further back than a ported contract expects and the reach can change.

## 3. `eth_getCode` is not evidence here — and it is worse than a stub

The Flare and Sonic rows established that a client may write a 1-byte code stub so a
Solidity `extcodesize` guard passes. Cosmos EVM does the same thing one step further:

```go
// x/erc20/keeper/dynamic_precompiles.go:RegisterERC20CodeHash
bytecode = common.FromHex(types.Erc20Bytecode)   // ~24KB of real compiled ERC-20
k.evmKeeper.SetCode(ctx, codeHash, bytecode)
acc.CodeHash = codeHash
```

Every token-pair precompile gets a **full, real, plausible ERC-20 runtime** stored at
its address, and it is **never executed** — the call hook installs the native Go
precompile for that address first (`x/vm/keeper/precompiles.go:GetPrecompileInstance`).
A 1-byte stub at least looks implausible to a careful reader. This returns something
that decompiles cleanly into the contract it is impersonating.

`eth_getCode == 0x` still proves *native*. Non-empty code proves **nothing** on this
framework. The source map is the only sound test, and both tests are recorded
separately in the yaml.

## 4. The precompile set is not enumerable — and not a predicate either

Base's `PrecompileLookup` answers membership from the address bytes, which is why
SCHEMA.md gained `dynamic_range` with a `pattern`. Cosmos EVM breaks that too:

- Membership is a **state lookup** in the `x/erc20` prefix store, not a function of
  the address (`x/erc20/keeper/precompiles.go:GetERC20PrecompileInstance`).
- The addresses are the last 20 bytes of an IBC denomination's sha256 hash
  (`utils/utils.go:GetIBCDenomAddress`) — deterministic, unpredictable, unpatterned.
- **The set grows on its own.** An inbound ICS-20 packet for a denomination the chain
  has never seen registers a new precompile *and installs its bytecode*
  (`x/erc20/keeper/ibc_callbacks.go:OnRecvPacket` → `RegisterERC20Extension`).

So the only way to know whether an address is a precompile is to query the chain at a
height. The `dynamic_range` entry records the rule; its `pattern` is honestly written
as a state-membership rule rather than an address predicate.

## 5. Seven precompiles write state, and two of them are called `verify*`

Mainnet has zero precompiles with side effects. Here, of the nine implemented static
precompiles, seven write:

| address | writes |
|---|---|
| `0x…0800` staking | `createValidator`, `editValidator`, `delegate`, `undelegate`, `redelegate`, `cancelUnbondingDelegation` |
| `0x…0801` distribution | six reward/commission/community-pool methods |
| `0x…0802` ICS-20 | `transfer` — escrows value into an IBC packet |
| `0x…0805` gov | `vote`, `voteWeighted`, `submitProposal`, `deposit`, `cancelProposal` |
| `0x…0806` slashing | `unjail` |
| `0x…0807` ICS-02 | `updateClient`, **`verifyMembership`, `verifyNonMembership`** |
| dynamic ERC-20 | `transfer`, `approve`, `deposit`, `withdraw` |

**STATICCALL safety holds** — `precompiles/common/precompile.go:SetupABI` returns
`vm.ErrWriteProtection` when `readOnly` and the method is a transaction — but the
boundary is drawn by a hand-written per-precompile `IsTransaction` method, and ICS-02
puts both of its `verify*` methods on the writing side. Two methods whose names promise
a pure predicate revert under `STATICCALL`. A view function wrapping them is not a view
function, and nothing in the ABI says so.

The inversion is worth flagging too: **the `bank` precompile is query-only**
(`precompiles/bank/bank.go`: `IsTransaction` returns `false` unconditionally). The
brief expected a precompile that performs a bank transfer; there isn't one. Bank
exposes every Cosmos denomination to EVM callers — assets with no ERC-20 anywhere —
and cannot move a single unit.

## 6. `0x…0803` is active, empty, and panics

`VestingPrecompileAddress` is declared, is a member of `AvailableStaticPrecompiles`,
and `evmd`'s genesis assigns that whole list to `ActiveStaticPrecompiles`. There is no
`precompiles/vesting` package in the tree and no `WithVestingPrecompile` builder, so
the keeper's map never contains it. That is exactly the branch marked "memory
corruption":

```go
// x/vm/keeper/static_precompiles.go:GetStaticPrecompileInstance
if k.IsAvailableStaticPrecompile(params, address) {      // true — it's in the param
    precompile, found := k.precompiles[address]          // false — never registered
    if !found { panic(...) }
```

`ValidatePrecompiles` checks duplicates, address syntax and sort order, and never
cross-checks the param against the registered map, so nothing catches it at genesis.
Recorded as `tombstoned`. Whether a given deployment inherits it depends on whether it
copied `evmd`'s genesis — the Injective row probes exactly this, live, and answers it.

## 7. Two gas meters, and one of them is deliberately infinite

The Sei row recorded a "dual gas meter"; here it is three-layer and stranger:

1. `ante/evm/01_setup_ctx.go` installs a plain **infinite** Cosmos gas meter.
2. `ante/evm/08_gas_consume.go:CheckBlockGasLimit` replaces it with
   `NewInfiniteGasMeterWithLimit(gasWanted)` — a meter that *records* the Ethereum gas
   limit as its `limit` and never enforces it, because its `ConsumeGas` cannot fail.
   The real metering is EVM gas; the EVM's gas used is written back as the Cosmos
   `GasUsed` afterwards.
3. Inside any stateful precompile a **third**, genuine Cosmos meter appears:
   `storetypes.NewGasMeter(contract.Gas)` — seeded with the EVM's *remaining gas* as
   if the units were the same. Cosmos KV-store gas consumed during the call is then
   charged straight back to the EVM one-for-one
   (`precompiles/common/precompile.go:runNativeAction`).

There is no conversion factor anywhere because none is intended. `RequiredGas` is
likewise a Cosmos KV gas-config expression (`WriteCostFlat + WriteCostPerByte·len`), so
a precompile's price is a function of how many store bytes the module happened to
touch. An out-of-gas inside a precompile arrives as a Go panic and is converted to
`vm.ErrOutOfGas` by a deferred recover.

## 8. PREVRANDAO is a constant

```go
// x/vm/keeper/state_transition.go:NewEVMWithOverridePrecompiles
Random: &common.MaxHash,   // "need to be different than nil to signal it is after the merge"
```

Not weak randomness, not predictable randomness: the literal value `0xffff…ff`, in
every block, on every Cosmos EVM chain. Sei's `keccak256(timestamp)` at least varies.
Meanwhile the RPC block reports `mixHash` as the **zero** hash
(`rpc/types/utils.go:MakeHeader`), so the two places an integrator would look disagree
and neither is the value the EVM saw.

## 9. Governance is a fork mechanism

One `MsgUpdateParams` against `x/vm` can:

- change the **active precompile set** (including removing P256VERIFY from `0x0100`,
  at which point it becomes an empty account returning empty output — which EIP-7951
  defines as "signature invalid": the Sei/Hyperliquid silent-failure shape, reachable
  by a parameter change);
- reprice `SSTORE`, `CREATE`, `CREATE2` and `CALL` through the `ExtraEIPs` jump-table
  mutators;
- switch `CREATE` or `CALL` to permissioned, or to `restricted` — which returns
  `false` unconditionally (`x/vm/types/permissions.go:getCanCallFn`);
- move the EIP-2935 window; rewrite the whole `ChainConfig` fork schedule.

None of it needs a client release and none of it is a fork in any Ethereum sense.

A smaller finding inside this one: **the "EIP" numbers in `ExtraEIPs` are not EIPs.**
The three shipped mutators are numbered `0000`, `0001`, `0002` — the integers 0, 1 and
2 — and each deployment registers its own into geth's *global, per-process* activator
map via `x/vm/types/configurator.go:WithExtendedEips`. "EIP 3 is enabled on this
chain" names a private mutator that collides with the real registry.

## 10. `tx_authorization`: one address space, two derivations, `ed25519: never`

The brief asked whether an ed25519 key can authorize an EVM transaction. **No, and it
cannot authorize any transaction here** — `ante/sigverify.go:SigVerificationGasConsumer`
has an ed25519 case that *consumes* `SigVerifyCostED25519` and then returns
`ErrInvalidPubKey("ED25519 public keys are unsupported")`. It charges for the
verification it refuses. No config or governance parameter opens it; multisig recurses
through the same switch and cannot launder it in. The ed25519 that *is* live on a
Cosmos EVM chain is the CometBFT validator consensus key, which is consensus signing,
not transaction authorization. Recorded `authorizes: never` — the same result Sei
reached, in independent code.

Two things this row adds that Sei's does not:

**The bech32 address is not a second address.** `encoding/address/address_codec.go`'s
codec accepts hex *or* bech32 and returns the same 20 bytes; `BytesToString` bech32-
encodes them back. There is no association step, no `AssociateTx`, no byte-cast alias.
Every stranded-balance hazard in the Sei row is **absent** here — worth knowing
precisely because the two chains look so alike from outside.

**But the key derivation does come apart.** The ante switch admits two secp256k1
pubkey types: `ethsecp256k1.PubKey`, whose address is the keccak of the uncompressed
key, and Cosmos `secp256k1.PubKey`, whose address is `ripemd160(sha256(compressed))`.
Same curve, same 20-byte space, two incompatible derivations. An account created from a
Cosmos-style key holds and spends an EVM-visible balance through Cosmos messages and
can *never* sign an Ethereum transaction for that address. `0x01` can verify the
signature but cannot reproduce the address, so `ecrecover(sig) == from` — the identity
mainnet contracts rely on — is simply false for those accounts while the signature is
perfectly valid. Recorded as its own scheme (`secp256k1_cosmos`) because treating it as
ordinary secp256k1 is exactly the mistake that makes it dangerous.

`signers_per_tx` stays 1. The one path that would make it 2 — the EIP-712 `Web3Tx`
extension's fee-payer signature — is fully implemented in `ante/cosmos/eip712.go` and
**unreachable**: `ante/ante.go:NewAnteHandler` accepts exactly two extension-option
type URLs and rejects everything else. Dead code in the reference node; a live
second-signer path for any deployment that re-enables it. Recorded
`adoption: withdrawn`.

## Smaller findings

- **`x/vm` reaches Prague and *can* reach Osaka.** The `replace` in `go.mod` pulls
  `cosmos/go-ethereum v1.17.2-cosmos-0`, which implements Osaka; `OsakaTime` exists in
  the ChainConfig and defaults nil. Contrast Sei, whose geth fork has no Osaka branch
  — "not activated" versus "not representable". But the precompile map is hard-wired to
  Prague by `WithPraguePrecompiles()`, independent of the config, so activating Osaka
  would move the opcode rules without moving the precompiles.
- **P256VERIFY sits at the canonical `0x0100`, with raw RIP-7212 input, at Prague** —
  a fork generation before mainnet. It is the only raw-input precompile in the custom
  set; the other nine are ABI-dispatched Solidity interfaces implemented in Go, like
  Sei's. Two calling conventions in one map.
- **The base fee is not burned** — `x/vm/keeper/fees.go:DeductFees` bank-sends base fee
  *and* tip to the `FeeCollector` module account — and it is computed from the parent
  block's **gas wanted** (summed transaction gas *limits*), not gas used, against a
  target of `consensusParams.Block.MaxGas / ElasticityMultiplier`. The whole mechanism
  is optional and `evmd`'s example genesis turns it off.
- **EVM balances are reconciled by replaying Cosmos events.**
  `precompiles/common/balance_handler.go:AfterBalanceChange` reads the bank module's
  `coin_spent`/`coin_received` events emitted since the precompile call began, parses
  addresses and amounts out of event attribute *strings*, and calls
  `StateDB.AddBalance`/`SubBalance`. Events involving `BlockedAddr` accounts — every
  module account and every precompile address — are deliberately **skipped**, so for
  those addresses the multistore and the EVM StateDB knowingly disagree.
- **The header does not hash to the hash.** `rpc/types/utils.go:RPCMarshalHeader`
  substitutes the CometBFT block hash for `hash` ("use cometbft header hash"). That is
  the right call — it makes `hash` agree with `BLOCKHASH` — and it means
  `keccak256(rlp(header))` is not the reported hash, so any header-verifying light
  client or bridge fails on every block. `stateRoot` is the CometBFT app hash, a
  commitment to the whole multistore; no `eth_getProof` result can verify against it.
- **Governance can install bytecode anywhere.** `MsgRegisterPreinstalls` takes
  `{name, address, code}` under the `x/gov` authority. The shipped five are ordinary
  mainnet ecosystem addresses (Create2 deployer, Multicall3, Permit2, Safe factory,
  the 2935 contract) chosen so mainnet tooling works — none of them namespaced, none
  reserved. A contract can appear at an address someone was using as an EOA.
- **Sub-unit scaling.** The EVM insists on 18 decimals; a Cosmos denom usually has 6.
  The framework defines an extended denom and multiplies
  (`x/vm/types/scaling.go`), and `DeductFees` **panics outright** if virtual fee
  collection is on for a display denom whose exponent is not 18.

## Not established here

- **`BLOBBASEFEE` (`0x4a`).** `BlockContext.BlobBaseFee` is never assigned in
  `NewEVMWithOverridePrecompiles`, so it is nil, and geth's `opBlobBaseFee` calls
  `uint256.FromBig` on it. Whether that yields zero or panics was not established from
  source and is recorded as `unrecorded`. The Injective row probes the deployed answer.
- **EIP-3529 refunds.** `RefundGas` credits the refund as a bank send rather than
  through geth's `returnGas`; whether the SSTORE refund cap composes correctly with the
  Cosmos-side accounting and the precompile meter was not read. `unrecorded`.
- **EIP-2200 / opcode pricing per deployment.** Any chain may reprice `SSTORE`,
  `CREATE`, `CREATE2` and `CALL` via `ExtraEIPs`; whether a given one does is live
  module state. `unrecorded` on this row by construction — it is a template.
- **No live probe.** This is not a chain; there is nothing to query. Every headline
  above rests on `src:` at the pinned commits, and the Injective row is where several
  of them get their first live test.
- **The `x/erc20` `ConvertCoin`/`ConvertERC20` round trip** is recorded as a
  `non_evm_transaction` but its precision and failure behaviour under the 6→18 decimal
  scaling were not read.

## Re-verify

```sh
# from the repo root
tools/clone.sh                                  # re-fetches every pinned clone
tools/.venv/bin/python tools/verify.py          # expect: pin ok, citations ok
                                                # "! NO EXTRACTOR" for cosmos-evm is expected

E=chains/cosmos-evm/repos/evm
G=chains/cosmos-evm/repos/go-ethereum

# --- role: template. The framework's own default is NO active precompiles.
git -C $E grep -n 'DefaultStaticPrecompiles \[\]string' -- x/vm/types/params.go
git -C $E grep -n 'ActiveStaticPrecompiles = evmtypes.AvailableStaticPrecompiles' -- evmd/genesis.go

# --- the precompile addresses, exactly
git -C $E show HEAD:x/vm/types/precompiles.go

# --- 0x0803 is in the active list and has no implementation
git -C $E grep -rn 'VestingPrecompileAddress' -- x/vm/types/precompiles.go
git -C $E grep -rn 'WithVestingPrecompile' || echo 'NOT FOUND — no vesting precompile exists'
ls $E/precompiles/                              # no vesting/ directory
git -C $E grep -n 'precompiled contract not stored in memory' -- x/vm/keeper/static_precompiles.go

# --- EIP-2935: 8192 here, 8191 in the contract that is preinstalled
git -C $E grep -n 'DefaultHistoryServeWindow = 8192' -- x/vm/types/params.go
git -C $E grep -n 'ringIndex := uint64(ctx.BlockHeight()) % window' -- x/vm/keeper/keeper.go
git -C $G grep -n 'HistoryServeWindow = 8191' -- params/protocol_params.go
git -C $G grep -n 'HistoryStorageCode' -- params/protocol_params.go | head -1
# the bytecode contains 611fff (PUSH2 0x1fff = 8191) on both its read and write paths

# --- PREVRANDAO is the constant MaxHash
git -C $E grep -n 'Random:      &common.MaxHash' -- x/vm/keeper/state_transition.go

# --- the dual encoding: the raw EIP-2718 envelope survives inside protobuf
git -C $E grep -n -A2 'bytes raw = 6' -- proto/cosmos/evm/vm/v1/tx.proto
git -C $E grep -n 'reserved 1, 2, 3, 4' -- proto/cosmos/evm/vm/v1/tx.proto
git -C $E grep -n 'return tx.UnmarshalBinary(dst)' -- x/vm/types/eth.go

# --- tx types: 0x03 is not in the accepted mask
git -C $E grep -n -A5 'const AcceptedTxType' -- ante/evm/mono_decorator.go

# --- ed25519 is charged gas and then refused
git -C $E grep -n -B2 'ED25519 public keys are unsupported' -- ante/sigverify.go

# --- bech32 and hex are the same 20 bytes (no association step)
git -C $E grep -n -A12 'func (bc evmCodec) StringToBytes' -- encoding/address/address_codec.go

# --- the bank precompile cannot write
git -C $E grep -n -A3 'func (Precompile) IsTransaction' -- precompiles/bank/bank.go

# --- ICS-02 classifies its verify* methods as transactions (they revert under STATICCALL)
git -C $E grep -n -A9 'func (Precompile) IsTransaction' -- precompiles/ics02/ics02.go
git -C $E grep -n 'vm.ErrWriteProtection' -- precompiles/common/precompile.go

# --- dynamic ERC-20 precompiles get REAL bytecode that never runs
git -C $E grep -n -A6 'func (k Keeper) RegisterERC20CodeHash' -- x/erc20/keeper/dynamic_precompiles.go
git -C $E grep -c . x/erc20/types/constants.go     # one very long line: the ERC-20 runtime
git -C $E grep -n 'RegisterERC20Extension' -- x/erc20/keeper/ibc_callbacks.go

# --- three gas meters
git -C $E grep -n 'NewInfiniteGasMeter()' -- ante/evm/01_setup_ctx.go
git -C $E grep -n 'NewInfiniteGasMeterWithLimit(gasWanted)' -- ante/evm/08_gas_consume.go
git -C $E grep -n 'ctx.WithGasMeter(storetypes.NewGasMeter(contract.Gas))' -- precompiles/common/precompile.go

# --- base fee: not burned, computed from gas WANTED
git -C $E grep -n 'SendCoinsFromAccountToModuleVirtual' -- x/vm/keeper/fees.go
git -C $E grep -n 'parentGasUsed := k.GetBlockGasWanted(ctx)' -- x/feemarket/keeper/eip1559.go

# --- the RPC block's hash is CometBFT's, so the header does not hash to it
git -C $E grep -n 'use cometbft header hash' -- rpc/types/utils.go

# --- the EVM is a dependency, replaced with a geth that HAS Osaka
git -C $E grep -n 'go-ethereum =>' -- go.mod
git -C $E grep -n 'OsakaTime:           nil' -- x/vm/types/chain_config.go
git -C $E grep -n 'WithPraguePrecompiles' -- precompiles/types/defaults.go

# --- the ExtraEIPs "EIP" numbers
git -C $E grep -n 'func Enable000' -- eips/eips.go
```
