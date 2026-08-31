# Sei

**Client:** `sei-protocol/sei-chain` `v6.6.1` (`43d1152e`), Go
**Companion:** `sei-protocol/go-ethereum` `v1.15.7-sei-17` (`929fc329`) — the EVM itself
**Chain ID:** 1329 (`pacific-1`) · **Baseline:** Prague · **Live probes:** block `226969278`

Sei is a Cosmos-SDK chain whose EVM interpreter is a maintained fork of go-ethereum.
The interpreter tracks upstream; nothing around it does. `role: fork` describes only
the part of Sei that descends from geth by code.

**One clone covers almost everything.** As of `v6.6.1` the forked SDK and the forked
consensus engine are no longer separate Go modules: `sei-cosmos/`, `sei-tendermint/`,
`sei-db/`, `sei-ibc-go/` and `sei-wasmd/` are directories *inside* the `sei-chain`
module, imported as `github.com/sei-protocol/sei-chain/sei-tendermint/...`. `go.mod`
declares no `cosmos-sdk` or `cometbft` dependency at all. Every citation below that
touches consensus, the mempool, the OCC scheduler or the multi-version store resolves
inside the single pinned `sei-chain` clone — no extra companion repo was needed, and the
one that is pinned (`go-ethereum`) is only the interpreter.

---

## The headline: `0x0100` is empty and Sei *has* P256VERIFY

The dataset's standing observation was that `0x0100` is the one address twelve of
thirteen rows agree on, and that Hyperliquid — where it is empty — is the exception
that makes it interesting. Sei is a stronger counterexample, because it is not a
chain that skipped the feature.

- Sei's secp256r1 verifier is at **`0x…1011`**.
- The geth fork's precompile switch tops out at `PrecompiledContractsPrague`. There is
  no Osaka branch, so `0x0100` is never populated by the built-in map.
- Custom precompiles are installed **only where the built-in map is empty**
  (`core/vm/evm.go:NewEVM` tests `if _, exists := evm.precompiles[addr]; !exists`), so
  Sei structurally cannot place anything at a mainnet address.
- `0x0100` is therefore an ordinary empty account. Calling it succeeds and returns
  empty output — which EIP-7951 defines as *invalid signature*.

Verified live against a *known-valid* signature (the wycheproof `CallP256Verify`
vector shipped in the Kaia repo's `p256Verify.json`), because the obvious probe cannot
distinguish "invalid" from "absent":

```
eth_call 0x0000000000000000000000000000000000000100  ->  0x
eth_call 0x0000000000000000000000000000000000001011  ->  0x…0020 0020 …0001
```

A passkey wallet ported to Sei fails closed, silently, forever — the second
independent arrival at the Hyperliquid failure mode, by a completely different route.

## Second-order: Sei's precompiles are ABI-dispatched

Not a placement difference — a **category** difference. Every one of the thirteen
custom precompiles dispatches on a 4-byte Solidity method selector and ABI-encodes its
result. `0x…1011` implements `verify(bytes)` (`0x8e760afe`), so the 160-byte RIP-7212
payload must be wrapped in an ABI `bytes` argument. Sending the bare 160 bytes
**reverts**. Gas is 300 per input byte, not a flat 3450 or 6900. `DELEGATECALL` is
refused.

They are still precompiles by SCHEMA.md's definition — native Go, no bytecode in
state, `EXTCODESIZE` 0 (verified live) — but no mainnet precompile behaves this way,
and no generic precompile prober will get a result out of one.

## The address block: `0x1001`–`0x100c`, plus `0x1011`

| addr | name | what it reaches |
|---|---|---|
| `0x…1001` | bank | Cosmos bank module: non-EVM denominations |
| `0x…1002` | wasmd | instantiate/execute/query CosmWasm — **re-enters the EVM** |
| `0x…1003` | json | JSON helpers for CosmWasm responses |
| `0x…1004` | addr | **address association**: `getSeiAddr` / `getEvmAddr` / `associate` |
| `0x…1005` | staking | delegate / undelegate / redelegate |
| `0x…1006` | gov | vote and deposit on governance proposals |
| `0x…1007` | distribution | |
| `0x…1008` | oracle | validator-voted price feed |
| `0x…1009` | ibc | initiates IBC transfers from EVM bytecode |
| `0x…100a` | pointerview | |
| `0x…100b` | pointer | deploys ERC-20/721/1155 pointer contracts |
| `0x…100c` | solo | `claim` / `claimSpecific` |
| `0x…1011` | P256VERIFY | **not contiguous** — `0x100d`–`0x1010` are unallocated |

Four orders of magnitude above every existing row's custom block (BSC/Arbitrum
`0x64`–`0x69`, Polygon/BSC `0x…1000`, Tron `0x1000001`+). The address table generalises,
but only because it was already keyed on full 20-byte addresses.

Two wiring traps found while establishing this:

- `precompiles/setup.go` contains **two disagreeing lists**. `InitializePrecompiles`
  (which mutates geth's global maps) omits `solo` and is only ever called with
  `dryRun=true` to harvest ABIs. `GetCustomPrecompiles` is the live path
  (`app/app.go` → `Keeper.SetCustomPrecompiles` → `vm.NewEVM`) and has all thirteen.
  The row cites the live path.
- Each address carries a **per-upgrade version map** keyed by Sei's own named software
  upgrades, selected by the height at which that governance upgrade completed
  (`x/evm/keeper/keeper.go:GetCustomPrecompilesVersions`). "The precompile at `0x1001`"
  is a family, not a contract.

## The dual address space *does* change `CALLER` / `ORIGIN`

Yes — and worse than expected.

An unassociated Cosmos account's EVM address is `common.BytesToAddress(seiAddress)`:
a **raw byte-cast of its bech32 payload**, unrelated to its public key
(`x/evm/keeper/address.go:GetEVMAddressOrDefault`). After it associates, it resolves to
the real secp256k1-derived address. So `msg.sender` and `tx.origin` for the *same*
Cosmos account are **two different addresses before and after association**.

`utils/helpers/associate.go:MigrateBalance` moves native balances (and the sub-`usei`
"wei" remainder) from the cast address to the sei address at association time. It does
**not** move ERC-20 balances, allowances, or any contract storage keyed on the old cast
address. Those are stranded at an address nobody controls, with no event a contract can
react to.

The reverse edge also bites: `CanAddressReceive` returns false for a cast address whose
EVM counterpart has already associated — the same 20 bytes are a valid bank recipient
before association and an invalid one after.

## The other headline: an sr25519 signature can move money the EVM watches

`tx_authorization` was added to answer one question — *what can sign a transaction* —
and Sei is the row where the answer is not "secp256k1".

An Ethereum transaction on Sei is secp256k1 and nothing else: `PreprocessUnpacked`
recovers from `(V, R, S)` and unconditionally stamps a `secp256k1.PubKey`. But that
transaction is a `MsgEVMTransaction` riding inside a Cosmos SDK transaction, and every
*other* Cosmos message — bank, staking, gov, wasm — takes the SDK ante chain instead.
There, the accepted key set is decided by one switch,
`DefaultSigVerificationGasConsumer`, which admits **secp256k1, sr25519, secp256r1**, and
multisigs over them.

A bank send authorized by an **sr25519** signature moves a balance the EVM reads
directly: `GetBalance` resolves an EVM address to its Cosmos counterpart through
`GetSeiAddressOrDefault`, which for an unassociated account is the same 20 bytes,
byte-cast. And **nothing on this chain can verify an sr25519 signature** — not Sei's own
`0x1001`–`0x1011` block, not the geth fork's `0x01`–`0x11`. Grep both; there is no hit.

That is `authorizes: protocol` with `precompile: none`: the protocol authorizes a state
change that no contract on the same chain can audit. An on-chain multisig or a recovery
module on Sei cannot check the very signature that just moved the balance it is reading.

**The ed25519 lead is refuted, and the refutation matters.** ed25519 *is* registered as
an account pubkey type and has a working ZIP-215 verifier in the tree — and the same
switch rejects it before verifying: `"ED25519 public keys are unsupported"`, with no
config or governance parameter guarding it, and the multisig path recurses through the
same function so it cannot be laundered in. The ed25519 that *is* live on Sei is the
CometBFT **validator consensus key** (`ToTmProtoPublicKey` converts to it and refuses
secp256k1 — exactly inverting the account rule). Conflating the two would have produced
a false finding.

The residue is a real hazard anyway: an ed25519 account still has a byte-cast `0x…`
address with an EVM-visible balance it can **receive into and never spend from**.
Association — `AssociateTx`, the `addr` precompile's `associate` / `associatePubKey`,
and the implicit `EVMAddressDecorator` path — is secp256k1-only in all four routes
(`btcec.ParsePubKey`, plus a `0x04`-prefix check), so no 25519-family account can ever
escape its cast address.

One more: **secp256r1 is a real transaction signer here**, admitted by the same switch —
one of the few rows in this dataset where that is true. Nominally paired, but not
portably: the verifier is at `0x1011`, not `0x0100`, and it is ABI-dispatched as
`verify(bytes)` with per-byte gas rather than taking RIP-7212's raw 160-byte input.

## Ordering and execution: what orders, what executes, and what survives

This section is the answer to the four questions this dataset asks of every chain.
All four are established from source in the pinned clone; none needed a live probe.

**(a) Ordering commits before execution, and the application never sees the choice.**
Sei's consensus engine is `sei-tendermint` — a fork of **Tendermint v0.35**, not
CometBFT 0.37 and not CometBFT 0.38. `sei-tendermint/version/version.go` declares
`TMVersionDefault = "0.35.0-unreleased"` and `ABCISemVer = "0.17.0"`. The ABCI
`Application` interface (`sei-tendermint/abci/types/application.go`) is both **smaller**
and **larger** than stock: it has `FinalizeBlock` and `ProcessProposal` but **no
`PrepareProposal`**, no `ExtendVote` and no `VerifyVoteExtension` — and it adds three
methods no other Cosmos chain has, `GetTxPriorityHint`, `EvmNonce(common.Address)` and
`EvmBalance(common.Address, []byte)`. Because there is no `PrepareProposal`, the
application cannot reorder, insert or drop anything: block contents are chosen entirely
by the proposer's mempool, which is itself EVM-aware. `sei-tendermint/internal/mempool/tx.go`
indexes transactions by `(sender, nonce)` and by EVM hash, calls back into the app for
the sender's live EVM nonce and balance, and documents its own policy in a comment:

> tx is ready if all txs with lower nonces are ready or executed AND balance >=
> tx.requiredBalance · we keep at most 1 tx per nonce · we don't store txs below account
> nonce · we reap by highest prio, while respecting nonces

`ProcessProposal` (`app/app.go:ProcessProposalHandler`) then applies exactly two
whole-block consensus checks and can `REJECT`: a protobuf decode failure on any
transaction, and `sum(GasWanted)` over the block exceeding the consensus-params block
max gas (`checkTotalBlockGas`). Everything else is decided at execution time.

**(b) Execution is parallel and optimistic, and it is node-local.** See the next
section.

**(c) A transaction that is ordered and then invalid: Sei ties the receipt to the
nonce, and that is the finding.** Two outcomes, and which one you get depends on
*which* validity check failed:

| failure at execution | nonce | receipt |
|---|---|---|
| insufficient funds, fee below minimum, init-code over limit, gas limit over block max — **at the correct nonce** | **burned** | **stub receipt written** |
| nonce too low or too high | **preserved** | **none, forever** |

The mechanism is a callback. `app/ante/evm_delivertx.go:DecorateNonceCallback` reads the
account's nonce *before* any check runs, and if it equals the transaction's nonce it
registers a `DeliverTxCallback`. `sei-cosmos/baseapp/baseapp.go` fires that callback in a
`defer`, against the **parent** multistore rather than the ante handler's discarded cache
branch — so it lands even though the ante handler failed and its writes were thrown away.
The in-source comment is blunt: *"bump nonce if it is for some reason not incremented
(e.g. ante failure)"*. The same code appears twice, in the fast `app/ante` path and in the
decorator chain at `x/evm/ante/basic.go`.

Then `x/evm/keeper/abci.go` EndBlock walks the deferred-info list and, for every EVM
transaction whose result carried an error, writes a stub receipt **if and only if**
`GetNonceBumped(ctx, deferredInfo.TxIndex)` is true — otherwise `continue`, and no
receipt is ever written. Sei therefore does **not** reproduce Artela's trap. On Artela a
transaction can burn a nonce and leave no receipt, so the user resubmits at the same
nonce and is stuck behind an invisible gap. On Sei the two are gated on the same
condition: if your nonce was spent, there is a receipt at that hash saying so; if there
is no receipt, your nonce was not spent.

A wrong-nonce transaction is genuinely erased in the Artela sense — it is in the
Tendermint block, `eth_getTransactionReceipt` returns `null` forever, and it consumed
nothing. But because the nonce is preserved, resubmission works. This is the Conflux
`Skipped` shape, not the Artela shape.

**(d) No preconfirmations, no early receipts — but there is optimistic block
processing.** `ProcessProposalHandler` launches a full `ProcessBlock` in a goroutine
against the *proposal*, before the block is committed, and stores the events, tx results
and EndBlock response. `FinalizeBlocker` reuses that result only if the run was not
aborted **and** `bytes.Equal(finalHash, req.Hash)`; on any mismatch it discards the
speculative work and re-executes from scratch. Nothing is published from the speculative
run: the block-header notifier `Stash`es only inside `FinalizeBlock` and publishes at
`Commit`. There is no MegaETH-style receipt carrying a `blockHash` for a block that does
not exist yet, and no receipt or block ever changes after it is returned. The one
observable trace is an operator metric, `app_optimistic_processing_total{enabled=...}`.

## OCC: shipped, on by default, and deliberately invisible

`CANDIDATES.md` predicted "OCC parallel execution" for Sei. **Confirmed, and it is real
production code, not a dormant flag.** It is also, in the terms this dataset cares about,
a *non-event*: a node-local optimisation whose contract is exact equivalence to
sequential execution.

The scheduler is `sei-cosmos/tasks/scheduler.go` — a Block-STM. Each transaction is a
`deliverTxTask` executing against a `VersionIndexedStore` layered over a
`MultiVersionStore` (`sei-cosmos/store/multiversion/`). Reads are tracked; a task whose
read set is invalidated by a lower-indexed task's write is reset, has its `Incarnation`
incremented, and re-executes. A task that aborts mid-flight publishes its writes as
**estimates** (`mvkv.go:WriteEstimatesToMultiVersionStore`) so dependents block instead of
thrashing. `ProcessAll` loops execute → validate-all → re-execute until every task
validates.

What happens on conflict, precisely:

- **Re-run, not abort.** There is no per-transaction retry cap.
- **The cap is on the block.** After `maximumIterations = 10` whole-block passes the
  scheduler sets `synchronous = true` and finishes the remainder strictly sequentially,
  starting at the first non-validated index. That fallback is deterministic.
- **No gas is charged for a discarded incarnation.** `Reset()` clears the response, and
  `ProcessAll` collects only the surviving responses; the block gas meter sees the final
  incarnation only.
- **The equivalence is tested, not assumed.** `occ_tests/occ_test.go` runs every
  scenario — bank transfers, wasm instantiate, gov proposals, EVM transfers both
  conflicting and non-conflicting, pointer creation — sequentially and in parallel and
  requires identical store state, identical events and identical `ExecTxResult`s.

Both knobs are node-local `app.toml` settings (`occ-enabled`, default **true** at
`sei-cosmos/server/config/config.go:DefaultOccEnabled`; `concurrency-workers`), which is
only sound *because* the results are required to match. One deterministic bypass exists
and is a function of block contents alone, so every node takes it identically: ≥ 64
transactions that are all plain value transfers to the **same** recipient run
sequentially (`app/app.go:shouldProcessSingleRecipientEVMTransfersSynchronously`).

**OCC does not interact with the dual address space.** Association writes go through the
same versioned store as any other write and conflict-resolve the same way; there is no
special casing of the association precompile in the scheduler, and nothing a contract
author can observe. `EstimateWritesets` / `EstimatedWritesets` — the ante-handler-based
write-set prediction the brief asked about — **does not exist in v6.6.1**. The only
estimates are the abort-time ones described above.

## The parallelism that *is* consensus-visible is not OCC

v6.6 ships a **second** EVM execution path, "Giga" — its own OCC scheduler under
`giga/`, its own keeper and state layer, and an optional `evmone` shared library loaded
best-effort at startup. `giga/executor/config/config.go` declares
`DefaultConfig = Config{Enabled: true, OCCEnabled: true}`, and `ReadConfig` only
overrides those when the operator's `app.toml` actually contains the keys — so on a node
whose config predates v6.6, Giga is **on**.

Enabling it executes one line in `app/app.go`:

```go
tmtypes.SkipLastResultsHashValidation.Store(gigaExecutorConfig.Enabled)
```

which turns off Tendermint's check that a proposed block's `LastResultsHash` matches the
results the node computed itself
(`sei-tendermint/internal/state/validation.go`, guarded again in
`internal/state/execution.go` and `types/evidence.go`). The declaration comment in
`sei-tendermint/types/block.go` says why, verbatim:

> This is set to true when the Giga executor is enabled, since it may produce different
> gas used values.

That is the finding. Every other parallel row in this dataset resolves scheduler
conflicts *below* consensus and leaves the state transition untouched; MegaETH is the one
exception, and it went the other way — it promoted the scheduler's needs *into* consensus
via gas detention. **Sei is a third shape: it removed a consensus check to accommodate
its executor.** Per-transaction results — gas used, result codes, response data — are no
longer cross-validated between nodes; only the app hash still binds. Giga also falls back
to the OCC-V2 path mid-block whenever a block is not "all EVM transactions, then all
Cosmos transactions" (`app/app.go:ProcessTXsWithOCCGiga`), and on execution or validation
errors — both fixes landed during the v6.6 release candidates.

## The stub receipt is a receipt shape Ethereum does not have

The receipt EndBlock writes for a nonce-burning ante failure has four fields:
`TxHashHex`, `TransactionIndex`, `VmError` and `BlockNumber`. `VmError` is the **Cosmos
ABCI error log string**, not an EVM revert reason — `DeferredInfo.Error` is assigned
`txRes.Log` in `x/evm/keeper/deferred.go:GetAllEVMTxDeferredInfo`. `GasUsed` and
`EffectiveGasPrice` are both zero, and the client treats that pair as its own
discriminator: `evmrpc/utils.go:isReceiptUntraceable` documents it as *"the tx bumped its
nonce in ante but never reached the VM"*, and notes that any executed transaction —
including reverts and out-of-gas — sets both fields above zero.

Sei ships an entire parallel RPC namespace whose job is to hide these from callers that
cannot cope: `sei_getBlockByHashExcludeTraceFail`, `sei_getBlockByNumberExcludeTraceFail`,
`sei_getTransactionReceiptExcludeTraceFail` and their `sei2_` twins. The in-tree test
`evmrpc/tests/block_test.go:TestGetBlockByHashExcludeTraceFail_AnteStub` pins both halves:
the regular `eth_getBlockByHash` **keeps** an insufficient-funds stub, the
`ExcludeTraceFail` variant **drops** it. The two namespaces disagree about whether the
transaction is in the block. (These `sei_*` methods are not whitelisted on the public
`evm-rpc.sei-apis.com` gateway — `"rpc method is not whitelisted"`, observed
@ block `228728016` — so this is a source finding, not a live one.)

A separate, narrower heuristic (`evmrpc/utils.go:isReceiptFromAnteError`) filters
nonce-error receipts out of the regular endpoints, and switches behaviour on
`ctx.ClosestUpgradeName()` versus `"v5.8.0"` — so what a Sei node returns for a
historical block depends on which named governance upgrade was live at that height. The
in-source label for that is *"hacky heuristic"*.

## An EVM account on Sei has two independent nonces

The EVM nonce is stored by `x/evm` under `NonceKeyPrefix`, keyed by the 20-byte EVM
address (`x/evm/keeper/nonce.go`). The Cosmos account sequence lives in the `auth`
module and is bumped by the SDK signature decorator. EVM transactions are routed to a
completely separate ante chain by `x/evm/ante/router.go:EVMRouterDecorator` and never
touch the auth sequence; Cosmos transactions never touch the EVM nonce. For an
*associated* account — one identity, two addresses — the two counters drift apart
permanently, and nothing reconciles them. `eth_getTransactionCount` reports the first; a
Cosmos SDK client reports the second.

The mempool's nonce-gap handling is node-local admission policy, not consensus: in
`CheckTx` the EVM ante rejects only `txNonce < nextNonce` and lets a *gap* through
(`x/evm/ante/sig.go`), while the mempool parks the gapped transaction as "pending" and
refuses to reap it until every lower nonce is ready or executed. At `DeliverTx` the same
decorator hardens to `txNonce != nextNonce`. So the gap tolerance exists only in the
mempool; consensus is exact-match.

**Duplicate transactions** (one line, as asked): the mempool rejects a second copy by EVM
hash on insert (`errDuplicateTx` against the `byEvmHash` index) — node-local. If a
duplicate is nevertheless ordered into a block, the second copy fails `ErrWrongSequence`
because the first already bumped the nonce, so it takes the no-receipt/no-nonce path
above. Not established: whether any node-level replay-protection cache spans heights.

## A failed transaction is given exactly one second chance

`sei-tendermint/internal/mempool/tx.go` caches a *successfully* executed transaction as
permanently invalid, but a transaction whose `ExecTxResult.Code != 0` is pushed to a
`failedTxs` LRU rather than the reject cache — the comment reads *"Failed txs are given a
second chance."* Only on a second failure does it become permanently invalid. The same
transaction hash can therefore be ordered into two different blocks at two different
heights, which matters for anyone deduplicating by hash across blocks.

## Other integrator-breaking findings

- **The base fee is not burned.** `baseFee + tip` is credited in full to the fee
  collector as the coinbase reward, with an in-source comment saying so
  (`core/state_transition.go`). Sei's fee market is also not EIP-1559: ±1.89% / −0.39%
  per block toward a 250k-gas target, clamped between governance floor and ceiling.
- **`PREVRANDAO` is `keccak256(block timestamp)`.** Fully predictable. Contracts using
  it for randomness are exploitable and show no outward sign.
- **Receipts with `type: 0xffffffff` exist.** Cosmos/CosmWasm transactions emitting
  EVM-shaped logs get a synthetic receipt whose type is `math.MaxUint32` — outside the
  legal EIP-2718 range by a factor of 2^25. `eth_getLogs` returns their logs.
- **Blob transactions are registered then refused.** `0x03` is in `AllowedTxTypes` from
  Cancun on and unconditionally rejected by the ante handler → recorded `tombstoned`.
- **`AssociateTx` is a free, nonce-less, type-less state-changing transaction.** Its
  `TxType()`, `GetNonce()`, `GetGas()`, `GetValue()` and `GetTo()` all *panic*.
- **The Ethereum block is a fiction, and `stateRoot` is the worst field in it.** It
  carries the Tendermint app hash — a commitment to the whole Cosmos multistore — under
  the name and shape of an Ethereum state root. No Ethereum state proof against it can
  verify. `mixHash` is the zero hash, not the value `PREVRANDAO` returned.
- **`SeiSstoreSetGasEIP2200`** is a `params.ChainConfig` field in the fork that
  overrides the clean-zero→nonzero `SSTORE` cost in both the EIP-2200 and EIP-2929 gas
  paths, refunds included. Default 20000 = mainnet. The mechanism has no mainnet
  analogue; whether `pacific-1` runs the default is a live value, not a source fact.

## Where the schema strained

- **`role`.** Sei is a code fork of geth *in the interpreter only*. Everything else —
  envelope, accounts, fees, blocks, addresses — is a rewrite. `fork` overstates
  equivalence; `independent` would understate the literal shared code. Recorded as
  `fork` with a `chain.note` saying which half it applies to. No new key proposed.
- **`header_fields`.** The section assumes a header exists to diff. Sei's consensus
  block is a Tendermint block; the Ethereum header is *assembled at RPC time* and is
  not hashed, signed or committed to. Recorded under `header_fields` anyway, with a
  section `note` saying so, because an integrator reading those fields cannot tell.
- **`system_contracts`.** Sei's pointer contracts are real EVM bytecode installed by
  the chain rather than by a user — but at addresses derived per asset at registration
  time. Neither a predeploy set nor a `dynamic_range` predicate. Recorded as a note.
- **Two upgrade axes.** `forks.timeline` models one sequence. Sei has two that do not
  line up: Ethereum fork level (all at genesis) and Sei's own governance-scheduled
  software upgrades (which are what actually gate precompile semantics). Recorded in
  `forks.note`; the timeline shows only the Ethereum axis.

## Deliberately not established

Nothing is marked `status: unrecorded` in this row, but these are *not* established and
are called out rather than guessed:

- **Whether `pacific-1` currently runs the default `SeiSstoreSetGasEIP2200` (20000).**
  It is a live chain-config value; source gives only the default. Recorded as
  `eips.2200: modified` with the uncertainty stated in the note, rather than as
  `inherited` (which would assert equivalence) or `unrecorded` (which would hide that
  the mechanism exists).
- ~~**The exact `usei` ↔ EVM-gas conversion multiplier.**~~ **Now established.**
  `sei-cosmos` is inside the pinned clone, so this resolved: the EVM→Cosmos gas
  conversion factor is `PriorityNormalizer`, an `x/evm` governance parameter that
  defaults to `1` (`x/evm/types/params.go:DefaultPriorityNormalizer`), applied at
  `x/evm/keeper/msg_server.go:158`. It is the *same* coefficient Sei uses to normalise
  EVM gas-limit priority into Cosmos mempool priority, reused as a unit conversion — so
  a governance vote aimed at repricing EVM priority would also change how much of the
  block gas limit every EVM transaction consumes. Recorded in `fee_model`.
- **The full Cosmos-SDK message set.** `non_evm_transactions` lists Sei's own
  `x/evm` messages exhaustively. Standard bank/staking/gov/IBC/wasm messages are noted
  as a population but not enumerated — they are stock Cosmos SDK, and their EVM-visible
  effects are reachable through `0x1001`–`0x100c`.
- **Whether `includeSyntheticTxs` defaults on or off per RPC method.** Established that
  the flag exists and gates the `0xffffffff` receipts differently on different paths.
- **Precompile extractor.** `verify.py` reports `! NO EXTRACTOR` for this row; the
  address list is taken on trust from `precompiles/setup.go:GetCustomPrecompiles`.
- **Whether `pacific-1` validators actually run with the Giga executor enabled.** The
  *default* is established from source (`DefaultConfig{Enabled: true, OCCEnabled: true}`)
  and the consequence of enabling it is established
  (`SkipLastResultsHashValidation`). What is **not** established is the operator
  reality: an `app.toml` that explicitly sets `giga_executor.enabled = false` overrides
  the default, and there is no RPC that reports which executor a node used. Settling it
  needs either a validator's `app.toml` or a node log line (`"benchmark: Giga Executor
  is ENABLED"` / `"... is DISABLED"`), neither reachable from a public endpoint.
- **Whether a live Sei node has ever actually served a stub receipt on `pacific-1`.**
  The path is established from source and pinned by the in-tree RPC test, and the
  stub-receipt filter machinery would not exist if the case were unreachable. But
  producing one requires sending a correct-nonce transaction with a deliberately
  unpayable fee from a funded account, which this pass did not do (the row is
  read-only against a public endpoint). Settling it needs a funded key.
- **Whether a duplicate transaction hash is blocked across heights.** Established that
  the mempool rejects duplicates by EVM hash on insert, and that a duplicate ordered
  anyway fails `ErrWrongSequence`. Not established whether any node-level cache prevents
  the *same* hash being re-gossiped and re-ordered at a later height — the `failedTxs`
  LRU explicitly permits exactly that for a once-failed transaction.
- **Whether the `sei_*ExcludeTraceFail` namespace is reachable on any public endpoint.**
  `evm-rpc.sei-apis.com` answers `"rpc method is not whitelisted"` for the whole `sei_`
  namespace (and for `rpc_modules`), observed @ block `228728016`, so the
  two-namespaces-disagree finding is a source finding only. Settling it needs a self-hosted node or a permissive provider.

---

## Re-verify

```bash
# 1. Re-fetch the pinned evidence (both repos)
git clone --depth 1 --branch v6.6.1 \
  https://github.com/sei-protocol/sei-chain chains/sei/repos/sei-chain
git -C chains/sei/repos/sei-chain rev-parse HEAD   # 43d1152e06ed9020d39e10da706451718b66c804

git clone --depth 1 --branch v1.15.7-sei-17 \
  https://github.com/sei-protocol/go-ethereum chains/sei/repos/go-ethereum
git -C chains/sei/repos/go-ethereum rev-parse HEAD # 929fc329f2a82d97c51a97233f394f8d66d9cfc5

# 2. Re-check every citation in chain.yaml
tools/.venv/bin/python tools/verify.py

# 3. The thirteen custom precompile addresses (the live registration path)
sed -n '/^func GetCustomPrecompiles/,/^}/p' chains/sei/repos/sei-chain/precompiles/setup.go

# 4. Confirm the built-in map has no 0x0100 — the fork stops at Prague
sed -n '/^var PrecompiledContractsPrague/,/^}/p' \
  chains/sei/repos/go-ethereum/core/vm/contracts.go
grep -n "case rules.Is" chains/sei/repos/go-ethereum/core/vm/contracts.go

# 5. Confirm custom precompiles cannot shadow a built-in
sed -n '/^func NewEVM/,/^}/p' chains/sei/repos/go-ethereum/core/vm/evm.go

# 6. Base fee is credited, not burned
grep -n "burn the base fee" -A 2 \
  chains/sei/repos/go-ethereum/core/state_transition.go

# 7. PREVRANDAO = keccak256(timestamp); BLOBBASEFEE = 1; GASLIMIT = consensus MaxGas
sed -n '/^func (k \*Keeper) GetVMBlockContext/,/^}/p' \
  chains/sei/repos/sei-chain/x/evm/keeper/keeper.go

# 8. Dual address space: cast-vs-derived, and what migrates
sed -n '/^func (k \*Keeper) GetEVMAddressOrDefault/,/^}/p;/^func (k \*Keeper) CanAddressReceive/,/^}/p' \
  chains/sei/repos/sei-chain/x/evm/keeper/address.go
sed -n '/^func (p AssociationHelper) MigrateBalance/,/^}/p' \
  chains/sei/repos/sei-chain/utils/helpers/associate.go

# 9. Blob txs: permitted by the type table, refused by the ante handler
grep -n "AllowedTxTypes" -A 5 chains/sei/repos/sei-chain/x/evm/ante/preprocess.go
grep -n "ErrUnsupportedTxType" chains/sei/repos/sei-chain/x/evm/ante/basic.go

# 10. AssociateTx: every envelope accessor panics
cat chains/sei/repos/sei-chain/x/evm/types/ethtx/associate_tx.go

# 11. The 0xffffffff synthetic receipt type
grep -n "ShellEVMTxType" chains/sei/repos/sei-chain/x/evm/types/constants.go \
                          chains/sei/repos/sei-chain/app/receipt.go

# 12. The RPC-synthesised "Ethereum" block
sed -n '/^func EncodeTmBlock/,/^}/p' chains/sei/repos/sei-chain/evmrpc/block.go | tail -40

# 13. Consensus engine identity: Tendermint v0.35, ABCI 0.17.0, no PrepareProposal
sed -n '8,25p' chains/sei/repos/sei-chain/sei-tendermint/version/version.go
sed -n '14,38p' chains/sei/repos/sei-chain/sei-tendermint/abci/types/application.go
grep -rn "PrepareProposal" chains/sei/repos/sei-chain/app/ \
     chains/sei/repos/sei-chain/sei-cosmos/baseapp/    # -> only an unrelated comment
grep -n "cosmos-sdk\|cometbft" chains/sei/repos/sei-chain/go.mod   # -> no dependency

# 14. OCC is shipped and on by default; the fallback is sequential after 10 passes
grep -n "maximumIterations\|s.synchronous = true\|WriteEstimatesToMultiVersionStore" \
     chains/sei/repos/sei-chain/sei-cosmos/tasks/scheduler.go
grep -n "DefaultOccEnabled\|OccEnabled bool" \
     chains/sei/repos/sei-chain/sei-cosmos/server/config/config.go   # -> = true
grep -n "assertEqualState\|assertEqualExecTxResults\|func TestParallel" \
     chains/sei/repos/sei-chain/occ_tests/occ_test.go   # parallel == sequential, tested
grep -rn "EstimateWritesets\|EstimatedWritesets" chains/sei/repos/sei-chain --include=*.go
# -> no matches: the ante-based writeset estimator does not exist in v6.6.1

# 15. Giga executor: default ON, and it disables LastResultsHash validation
sed -n '16,32p' chains/sei/repos/sei-chain/giga/executor/config/config.go   # DefaultConfig
grep -n "SkipLastResultsHashValidation" chains/sei/repos/sei-chain/app/app.go
sed -n '25,32p' chains/sei/repos/sei-chain/sei-tendermint/types/block.go    # the comment
sed -n '68,77p' chains/sei/repos/sei-chain/sei-tendermint/internal/state/validation.go

# 16. The nonce is burned on ante failure — but only at the matching nonce
sed -n '100,116p' chains/sei/repos/sei-chain/app/ante/evm_delivertx.go   # DecorateNonceCallback
sed -n '29,41p'   chains/sei/repos/sei-chain/x/evm/ante/basic.go         # the same, in the decorator chain
sed -n '940,948p' chains/sei/repos/sei-chain/sei-cosmos/baseapp/baseapp.go  # fired in a defer, on the PARENT store

# 17. ...and the stub receipt is written iff the nonce was burned
sed -n '122,135p' chains/sei/repos/sei-chain/x/evm/keeper/abci.go
sed -n '20,40p'   chains/sei/repos/sei-chain/x/evm/keeper/deferred.go     # Error = txRes.Log
sed -n '69,82p'   chains/sei/repos/sei-chain/x/evm/ante/sig.go            # CheckTx allows a gap, DeliverTx does not
sed -n '360,380p' chains/sei/repos/sei-chain/evmrpc/utils.go              # isReceiptUntraceable
sed -n '120,140p' chains/sei/repos/sei-chain/evmrpc/tests/block_test.go   # the two namespaces disagree

# 18. Two independent nonces
sed -n '12,24p' chains/sei/repos/sei-chain/x/evm/keeper/nonce.go          # x/evm NonceKeyPrefix
sed -n '25,33p' chains/sei/repos/sei-chain/x/evm/ante/router.go           # EVM txs bypass the SDK ante chain entirely

# 19. Optimistic block processing, and that nothing is published from it
sed -n '1287,1345p' chains/sei/repos/sei-chain/app/app.go   # ProcessProposalHandler starts it
sed -n '1371,1405p' chains/sei/repos/sei-chain/app/app.go   # FinalizeBlocker reuses iff hash matches

# 20. The mempool: EVM-aware, nonce-gapping, one second chance
sed -n '148,158p' chains/sei/repos/sei-chain/sei-tendermint/internal/mempool/tx.go  # the policy comment
sed -n '581,592p' chains/sei/repos/sei-chain/sei-tendermint/internal/mempool/tx.go  # "Failed txs are given a second chance"
```

### The `sei_*` namespace negative (public gateway, block 228728016)

```bash
SEI=https://evm-rpc.sei-apis.com
curl -s -X POST $SEI -H 'content-type: application/json' -d \
 '{"jsonrpc":"2.0","id":1,"method":"sei_getBlockByNumberExcludeTraceFail","params":["0xda580d0",false]}'
# -> {"error":{"code":-32601,"message":"rpc method is not whitelisted"}}
curl -s -X POST $SEI -H 'content-type: application/json' -d \
 '{"jsonrpc":"2.0","id":1,"method":"rpc_modules","params":[]}'
# -> {"error":{"code":-32601,"message":"rpc method is not whitelisted"}}
```

### Replay the live probes

Any archive node at block `226969278` (`0xd867abe`) or later. `V` is the wycheproof
`CallP256Verify` vector shipped in
`chains/kaia/repos/kaia/blockchain/vm/testdata/precompiles/p256Verify.json` (entry 0),
which the Kaia row independently confirms is **valid**.

```bash
SEI=https://evm-rpc.sei-apis.com
V=4cee90eb86eaa050036147a12d49004b6b9c72bd725d39d4785011fe190f0b4da73bd4903f0ce3b639bbbf6e8e80d16931ff4bcf5993d58468e8fb19086e8cac36dbcd03009df8c59286b162af3bd7fcc0450c9aa81be5d10d312af6c66b1d604aebd3099c618202fcfe16ae7770b0c49ab5eadf74b754204a3bb6060e44eff37618b065f9832de4ca6ca971a7a1adc826d0f7c00181a5fb2ddf79ae00b4e10e

# 0x0100 is an empty account, and a VALID signature there returns empty output
curl -s -X POST $SEI -H 'content-type: application/json' -d \
 '{"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":["0x0000000000000000000000000000000000000100","0xd867abe"]}'
curl -s -X POST $SEI -H 'content-type: application/json' -d \
 "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"0x$V\"},\"0xd867abe\"]}"
# -> "0x"  and  "0x"

# 0x1011, ABI-wrapped as verify(bytes) — selector 8e760afe, offset 0x20, length 0xa0
curl -s -X POST $SEI -H 'content-type: application/json' -d \
 "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000001011\",\"data\":\"0x8e760afe00000000000000000000000000000000000000000000000000000000000000200000000000000000000000000000000000000000000000000000000000000a0$V\"},\"0xd867abe\"]}"
# -> 0x...0020 ...0020 ...0001   (valid)

# the same vector sent raw to 0x1011 reverts — the precompile is ABI-dispatched
curl -s -X POST $SEI -H 'content-type: application/json' -d \
 "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000001011\",\"data\":\"0x$V\"},\"0xd867abe\"]}"
# -> error: execution reverted
```

The `verify(bytes)` selector is derivable from the pinned source rather than assumed:

```bash
cd chains/sei/repos/sei-chain
cat > precompiles/p256/zz_sel_test.go <<'GOEOF'
package p256

import "testing"
import pcommon "github.com/sei-protocol/sei-chain/precompiles/common"

func TestZZSel(t *testing.T) {
	a := pcommon.MustGetABI(f, "abi.json")
	for n, m := range a.Methods {
		t.Logf("SELECTOR %s = %x", n, m.ID)
	}
}
GOEOF
go test ./precompiles/p256/ -run TestZZSel -v 2>&1 | grep SELECTOR   # verify = 8e760afe
rm precompiles/p256/zz_sel_test.go
```
