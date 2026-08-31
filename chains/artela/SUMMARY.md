# Artela — what this row teaches

**Evidence footing.** `evidence: source`. Five repos are pinned, all at their newest
tags:

| repo | tag | commit |
|---|---|---|
| `artela-network/artela` (artelad) | `v0.4.9-rc9` | `0de86198b36e42c5442c9b059bbd10b5adc05498` |
| `artela-network/artela-evm` | `v0.4.8-rc8` | `93316786d69d0c6ab34e97e6c172ece2905c0e42` |
| `artela-network/aspect-core` | `v0.4.9-rc9` | `1e5d97e5fe6dedb64287d12c0d22fd2e3d2a7a03` |
| `artela-network/aspect-runtime` | `v0.4.8-rc8` | `9ae423f1ec4060b53a193e0fbb584c8689b9c080` |
| `artela-network/artela-cosmos-sdk` | `v0.47.4-artela-rc9` | `be1d73d660f2ee6af81182479854b2496423b27b` |

`v0.4.9-rc9` is both the newest tag and the newest GitHub *release*, and GitHub does
not mark it a prerelease. This project never shipped a tag without a `-beta` or `-rc`
suffix, so the "released tag" rule resolves to an rc here. It was published
2024-09-05; the default branch has had no push since 2024-11-15.

**No live probe was possible, and that is itself a finding.** On 2026-08-27 the only
RPC endpoint listed for chain id 11820 by *both* `chainid.network` and
`chainlist.org` — `https://node-euro.artela.network/rpc` — returned Cloudflare **522**
(origin unreachable); the testnet's single listed endpoint (11822,
`https://betanet-rpc1.artela.network`) returned **526**; `artela.network` returned
404, `docs.artela.network` 526, `artscan.artela.network` 521, and
`scan.artela.network` / `explorer.artela.network` did not resolve to a listening
service. Six community Cosmos RPCs and four commercial providers were also tried. So
there is **not one `src_live:` in this row**; every claim is source-only, and the row
records `live: false` / `live_state: halted` with the caveat, stated in
`chain.note`, that *halted* here means **unreachable** and not "observed to have
stopped at height N".

**Baseline fork: `cancun` — and the row is largely about how untrue that is.**

**Lineage: `cosmos-evm`.** Settled from the protobuf layout, not from a string search
(see finding 1). This file states only Artela's own deltas; the Cosmos-EVM shape comes
from `chains/cosmos-evm/`.

---

## 1. The lineage is Ethermint, and a grep for "ethermint" will tell you it isn't

`grep -ri ethermint` over the whole `artela` tree returns **nothing**. So does
`grep cosmos/evm go.mod`. Taken at face value that says "independent Cosmos EVM
implementation", and it is wrong.

The proof is the protobuf layout. Ethermint declares `ethermint/evm/v1`,
`ethermint/feemarket/v1`, `ethermint/types/v1` and
`ethermint/crypto/v1/ethsecp256k1`. Artela declares `artela/evm/v1`, `artela/fee/v1`,
`artela/types/v1` and `artela/crypto/v1/ethsecp256k1` — the same four packages, the
same message names (`MsgEthereumTx` with `data`/`size`/`hash`/`from`, `LegacyTx`,
`AccessListTx`, `DynamicFeeTx`, `ChainConfig`, `TxResult`), with one word swapped. The
rename is thorough enough to erase the word from comments too. The single surviving
fingerprint in 300-odd Go files is a comment in the RPC layer:

```
ethereum/rpc/blockchain.go:124:  StorageHash: common.Hash{}, // NOTE: Evmos doesn't have a storage hash.
```

Getting this wrong in either direction was the main way this row could be bad. Calling
it `independent` would have duplicated the whole Cosmos-EVM shape into Artela's file;
calling it a plain `cosmos-evm` descendant would have inherited a dozen facts that are
false here. It is a *fork of the same tree at a much earlier point*: Cosmos SDK
v0.47.4, CometBFT v0.37.2, go-ethereum v1.12.0 — roughly mid-2023, against the
framework row's v0.7.2. Five ancestor facts are overridden as a direct result: no
`x/erc20`, no Cosmos precompiles at all, no preinstalls/`MsgRegisterPreinstalls`, ABCI
0.37 instead of 0.38, and a fork schedule with no Prague or Osaka field.

## 2. Aspects: a contract's owner can revert a transaction that already succeeded

The Aspect mechanism is real, it is consensus-level, and it answers the sharp question
in the worst direction.

Five join points, a bitmask on the Aspect (`aspect-core/types/aspect_type.go`):
`VerifyTx` (1), `PreTxExecute` (2), `PreContractCall` (4), `PostContractCall` (8),
`PostTxExecute` (16). The four transaction-level ones fire inside *ordinary user
transactions*, and `transactionAdvice` looks up the Aspects bound to the **contract
being called** — `*msg.To` for the transaction-level pair, the frame's `addr` for the
call-level pair. The sender chooses none of it.

What an Aspect can do to a transaction it did not originate:

- **Abort it before it runs.** A `PreTxExecute` error short-circuits `ApplyMessage`.
- **Abort a nested call and burn the frame's gas.** `PreContractCall` runs inside
  `EVM.Call`; on error the call returns that error, and because it is not
  `ErrExecutionReverted`, `EVM.Call` sets `gas = 0`.
- **Fail a call that already succeeded, and rewrite its return data.**
  `PostContractCall` runs after `interpreter.Run` returned. On error:
  `err = postCallResult.Err; ret = postCallResult.Ret`, then revert to snapshot.
- **Fail a transaction that already succeeded.** `PostTxExecute` runs *only* when
  `vmErr == nil` — the success path — and its error overwrites `vmErr`. Back in
  `ApplyTransaction`, `commit()` is called only `if !res.Failed()`, so the whole
  transaction's state is discarded.

**Who can bind one** is the second half of the answer. `BindHandler` requires, for a
target with code, that `checkContractOwner` return true — and it establishes ownership
*by calling the target contract*: Artela's own `isOwner(address)` first, and if that
call errors, OpenZeppelin's `owner()`, compared against `msg.sender`. So the binder is
whoever the contract's own code says is its owner: **not necessarily the deployer**,
possibly an address ownership was transferred to afterwards, and — for a contract whose
`isOwner` returns true unconditionally — anyone. The contract's *users* are never
consulted, and nothing in `eth_getCode` or the bytecode records that an Aspect is
attached.

**Metering**: join-point gas is threaded out of the transaction's own remaining gas.
The sender pays for WASM the callee's owner installed. A panic inside the runtime is
recovered as `"aspect execution crashed"` and becomes a revert.

Recorded as `system_transactions.aspect_join_points`, `severity: high`.

## 3. There are three rejection layers, and only two of them look like failure

This is the ordering/execution answer, and it puts Artela in the **erasure** class
alongside Conflux and IOTA EVM — reached by a third mechanism, and with an exact,
fragile exception.

**Layer 1 — AnteHandler, during `DeliverTx`: no Ethereum receipt at all.** The
`ethereum_tx` event carrying `ethereumTxHash` is emitted by `EthEmitEventDecorator`,
deliberately the *last* ante decorator ("emit eth tx hash and index at the very last
ante handler"). Any earlier failure — stale nonce, insufficient balance, gas price
below the now-current minimum, bad signature — returns from `runTx` *before*
`msCache.Write()` and *before* `anteEvents = events.ToABCIEvents()`, so neither state
nor events survive. The CometBFT indexer therefore has no `ethereum_tx.ethereumTxHash`
entry; `GetTxByEthHash` errors, and `GetTransactionReceipt` returns `nil, nil` →
JSON-RPC `null`. Independently, `EthMsgsFromCosmosBlock` filters the block through
`TxSuccessOrExceedsBlockGasLimit`, so the transaction is also missing from
`eth_getBlockByNumber`. The transaction *is* in the CometBFT block and provably so.

**The one exception is a substring match.** `TxExceedBlockGasLimit` is
`strings.Contains(res.Log, "out of gas in location: block gas meter; gasWanted:")`. A
transaction that busted the *block* gas limit is kept and surfaced with `status: 0`.
Every other non-zero code is erased.

**Layer 2 — EVM revert:** ordinary `status: 0`.

**Layer 3 — Aspect:** also `status: 0`, but the error string in `res.VmError` is the
Aspect's own, there is no `REVERT` opcode anywhere in the trace, and the state
rollback happened because `commit()` was skipped rather than because a snapshot was
reverted. A client reading only `receipt.status` cannot distinguish layers 2 and 3;
a client that trusts `eth_getTransactionReceipt` cannot see layer 1 at all.

## 4. PREVRANDAO does not return a wrong value — it deletes the transaction

Three lines, in three repos.

1. `x/evm/keeper/evm.go`: `Random: nil, // not supported`.
2. `artela-evm/vm/jump_table.go`: `newMergeInstructionSet` installs `opRandom` at
   `PREVRANDAO` **unconditionally**, and the Cancun table is built from it.
3. `artela-evm/vm/instructions.go`:
   `new(uint256.Int).SetBytes(interpreter.evm.Context.Random.Bytes())`.

`Context.Random` is a `*common.Hash`, and `func (h Hash) Bytes() []byte` has a **value
receiver**, so calling it on a nil pointer dereferences nil.

The near-miss worth recording: `NewEVM` computes
`chainRules = chainConfig.Rules(num, blockCtx.Random != nil, time)`, so `IsMerge` is
false — but go-ethereum **v1.12.0** gates `IsShanghai`/`IsCancun` on `IsLondon(num)`
*alone* (later versions added the merge gate), so both are true and the interpreter
selects the Cancun table anyway. Had this been a slightly later geth, the table would
have fallen back to London and `0x44` would have been a harmless `DIFFICULTY`
returning 0. The panic exists because the fork-rule derivation and the jump-table
construction disagree about what "merge" means.

The panic unwinds into the SDK's `runTx` recovery middleware. The resulting log is a
Go runtime message, which does not contain the block-gas sentinel — so the transaction
takes the layer-1 erasure path of finding 3, except that here the ante handler
*succeeded*: the fee is deducted and the nonce incremented, and nothing at all is
visible over JSON-RPC. `0x44` is also `DIFFICULTY`, so pre-merge bytecode hits it too.

Compare Cosmos EVM (constant `0xffff…ff`) and Sei (a function of the timestamp). This
is a third answer, and the only one that is not a value.

## 5. A Cancun that is four different kinds of not-Cancun

`newCancunInstructionSet` carries its own FIXME:

```go
// FIXME: enable the following later, since:
//        1. blob tx is not supported yet
//        2. selfdestruct requires a lot of modifications, ...
//enable4844(&instructionSet) // EIP-4844 (BLOBHASH opcode)
//enable7516(&instructionSet) // EIP-7516 (BLOBBASEFEE opcode)
//enable6780(&instructionSet) // EIP-6780 SELFDESTRUCT only in same transaction
enable1153(&instructionSet) // EIP-1153 "Transient Storage"
enable5656(&instructionSet) // EIP-5656 (MCOPY opcode)
```

So on a chain that reports Cancun: `TSTORE`/`TLOAD` and `MCOPY` work; `BLOBHASH` and
`BLOBBASEFEE` are **undefined opcodes** that abort the frame and burn all its gas; and
`SELFDESTRUCT` **still really destroys** — the silent one, because the contract does
the *old* thing rather than failing. Fourth: `evm.precompile()` switches on
`IsBerlin`, so there is no point-evaluation precompile at `0x0a`.

And the fork boundary itself is a **block number**. `ChainConfig` has `shanghai_block`
and `cancun_block`; `EthereumConfig()` manufactures the timestamps go-ethereum wants as
either `0` or `MaxUint64` by comparing the current *height*, under the comment "use
height instead of time to determine if the fork has been applied". Ethereum made both
of these timestamp forks; Artela un-made that decision. Prague and Osaka have no field
at all — not unscheduled, unrepresentable.

## 6. A transaction with v = r = s = 0 is valid, and it wears an ordinary type byte

`IsCustomizedVerification` returns true when the signature values are nil or all zero,
`to` is non-nil and non-zero, and the calldata begins with the literal four bytes
**`0xCAFECAFE`** followed by a four-byte keccak checksum of the remainder. The keeper
additionally requires the target to have code.

The rest of the calldata is `abi.encode(validationData, callData)`. The protocol looks
up the verifier Aspects bound to the **callee**, requires exactly one, runs it at the
`VerifyTx` join point, and takes the 20 bytes it returns as the sender — then checks
that the claimed sender has itself bound the *same* Aspect as a verifier. That
two-sided opt-in is the only thing between this and arbitrary impersonation.

Consequences: the transaction hash is the hash of an *unsigned* transaction, so replay
protection is whatever the Aspect implements rather than EIP-155; `MakeSigner` returns
an `aspectSigner` whose `SignatureValues()` errors; and verification costs a flat,
non-refundable **150,000 gas** added to *intrinsic* gas whether it is used or not. The
in-source comment claims value transfers must be signed, but the predicate never
examines `value` — the comment is stricter than the code.

There is no new type byte. Every Ethereum tool parses this as an ordinary `0x00` or
`0x02` transaction with a broken signature. Recorded as the `aspect_verifier` scheme,
`authorizes: account_code` — with the note that, unlike zkSync, the validator is not
the *sender's* code but the callee's Aspect.

## 7. Two Aspect addresses that lie to `eth_getCode` in opposite ways

**`0x…A27E14` (AspectCore) is native at depth 0 and empty at depth 1.** `ApplyMessage`
intercepts by comparing `msg.To` against the address *before any call frame is built*.
The forked EVM's own `precompile()` is stock go-ethereum's Berlin map and does not
contain it. So a `CALL` to `0xA27E14` from inside contract bytecode reaches an account
with no code, which go-ethereum's `Call` reports as **success with empty output**. A
contract that tries to bind, unbind or query an Aspect gets a successful-looking call
that did nothing.

**Deploying an Aspect mints a contract address with no code.** The aspect id is
`crypto.CreateAddress(ctx.from, ctx.nonce)` — the same derivation `CREATE` uses, out
of the same 20-byte space — and `ApplyTransaction` sets `receipt.contractAddress` to it
whenever `IsAspectDeploy` holds. The WASM lives in a separate store, so `eth_getCode`
at an address a receipt says was just created returns `0x`, permanently. Anyone may
deploy; it is not permissioned.

## 8. Every transaction is billed for at least half its gas limit

`ApplyMessage` ends with
`gasUsed = max(gasLimit × MinGasMultiplier, temporaryGasUsed)`, and
`DefaultMinGasMultiplier` is `0.5`. The receipt reports the floor, not the
measurement. Padding a gas limit — the standard defensive habit everywhere else — is a
direct loss here, and any estimator that learns from receipts learns the padded number.
Governance can move the multiplier through `x/fee` `MsgUpdateParams`.

## 9. What Artela is *not*: three refuted claims

- **No parallel / "elastic" execution.** The pinned SDK fork's `DeliverTx` calls
  `runTx` once per transaction against a single `deliverState`. There is no scheduler,
  no optimistic execution, no conflict detection and no re-run path in any of the five
  repos. This is ABCI **0.37** — `BeginBlock`/`DeliverTx`/`EndBlock`/`Commit` — not
  ABCI++ 0.38, so there is no `FinalizeBlock` on this chain at all.
- **No Aspect involvement in block building.** `app.go` constructs an
  `ArtelaProposalHandler` and then leaves *both* `SetPrepareProposal` and
  `SetProcessProposal` **commented out**. The stock SDK defaults apply: the proposer
  drains its own mempool in that mempool's order re-running the AnteHandler, and
  `ProcessProposal` accepts unconditionally. A proposer may reorder freely and insert
  its own transactions. The dead handler in `x/evm/artela/handle/prepare.go` is a
  verbatim copy of the SDK default with no join point in it.
- **No module precompiles, and no second secp256k1 derivation.** There is no
  `precompiles/` package, no `ActiveStaticPrecompiles` param, and the whole
  `0x0100`/`0x0400`/`0x0800`–`0x0807` block the `cosmos-evm` and `sei` rows document is
  empty. A contract ported from another Cosmos EVM chain does not revert when it calls
  one — it succeeds with empty output. Likewise the ancestor's `secp256k1_cosmos`
  hazard is absent: Artela's ante switch has cases for `ethsecp256k1`, `ed25519` and
  `multisig` only, and its `default:` rejects everything else.

## 10. A blob transaction is not rejected, it is demoted

go-ethereum v1.12.0's `decodeTyped` *does* handle `BlobTxType`. Artela's
`NewTxDataFromTx` then switches on the type with cases for only `0x02` and `0x01` and a
`default:` that calls `newLegacyTx`. So a `0x03` transaction is decoded, stripped of
its type byte, blob hashes, blob-gas fee cap and access list, and re-packed as a
protobuf `LegacyTx`, while `MsgEthereumTx.Hash` keeps the original `0x03` hash. Nothing
validates the type anywhere.

This is downstream of an encoding choice: Artela kept Ethermint's *old*
`MsgEthereumTx`, which stores the transaction field-by-field in a protobuf `Any`.
`cosmos/evm` v0.7 replaced that with a verbatim `raw` envelope and `reserved 1,2,3,4`.
On Artela the RLP bytes do not survive, so the original cannot be recovered to check.

---

## Not established here

- **Whether Artela mainnet is still producing blocks.** Every published endpoint is
  unreachable; no last block was observed. `live_state: halted` in this row means
  *unreachable*, not *observed stopped*. A single successful `eth_blockNumber` against
  any Artela node would settle it.
- **Everything a live probe would have settled.** No `src_live:` exists in this row.
  In particular: whether the deployed genesis actually contains the ERC-4337 EntryPoint
  bytecode at `0x…AAEC` (`init.sh` is a devnet script), what the live `x/evm` and
  `x/fee` params are (`ExtraEIPs`, `MinGasMultiplier`, `NoBaseFee`, the ChainConfig
  fork heights are all module state and governance-mutable), whether any Aspect was
  ever deployed or bound on mainnet, and the observed behaviour of `0x44`.
- **The end-to-end fate of a submitted blob transaction.** The demotion to `LegacyTx`
  is established from source. Whether the reconstructed transaction then fails
  signature recovery, or is attributed to a recovered garbage address, depends on the
  interaction of `AsTransaction()` with the ante chain and was not traced to a
  conclusion; it needs a probe.
- **Whether `PostContractCall` can substitute return data on the *success* path.** It
  cannot in the pinned code — `ret` is only replaced when the Aspect returns an error —
  but `runAspect`'s comment says "revert scope is not fully supported yet", which
  suggests this is intended to change.
- **The Aspect state/property/transient-storage stores' gas accounting.** The host
  interfaces are enumerated in `aspect-core/types/hostapi_interface.go` and the
  StateDB one is read-only (`Get*` only), but the Cosmos-store gas charged by the
  Aspect KV stores back into the EVM meter was not traced the way the ancestor's
  `dual_gas_meter` entry traces it.
- **`x/aspect`'s cuckoo filter.** `x/aspect/cuckoofilter` gates whether an account has
  any Aspect bound at all, i.e. it is on the hot path of every call. Its false-positive
  behaviour (a filter hit that resolves to no Aspect) was not examined.

## Re-verify

```sh
cd /Volumes/TendiesTown/EVM-intel/chains/artela/repos

# --- pins -------------------------------------------------------------------
for d in artela artela-evm aspect-core aspect-runtime artela-cosmos-sdk; do
  echo "$d $(git -C $d rev-parse HEAD) $(git -C $d describe --tags)"; done
# artela            0de86198b36e42c5442c9b059bbd10b5adc05498  v0.4.9-rc9
# artela-evm        93316786d69d0c6ab34e97e6c172ece2905c0e42  v0.4.8-rc8
# aspect-core       1e5d97e5fe6dedb64287d12c0d22fd2e3d2a7a03  v0.4.9-rc9
# aspect-runtime    9ae423f1ec4060b53a193e0fbb584c8689b9c080  v0.4.8-rc8
# artela-cosmos-sdk be1d73d660f2ee6af81182479854b2496423b27b  v0.47.4-artela-rc9

# --- 1. lineage: Ethermint, renamed ----------------------------------------
grep -ri ethermint artela/ | wc -l                    # -> 0
grep -r 'cosmos/evm' artela/go.mod | wc -l            # -> 0
find artela/proto -name '*.proto' | sort              # artela/{evm,fee,types,crypto}/v1
grep -rn 'Evmos' artela/ethereum/rpc/blockchain.go    # the one surviving fingerprint
grep -n 'go-ethereum\|cosmos-sdk\|cometbft' artela/go.mod | head -4
#   -> ethereum/go-ethereum v1.12.0, cosmos-sdk v0.47.4, cometbft v0.37.2

# --- 2. Aspect join points, and who can bind one ---------------------------
grep -n 'JoinPointRunType_' aspect-core/types/aspect_type.go | head
grep -n 'PreContractCall\|PostContractCall' artela-evm/vm/evm.go
sed -n '369,382p' artela-evm/vm/evm.go        # postCallResult overwrites err AND ret
grep -n 'PostTxExecute' artela/x/evm/keeper/evm.go
sed -n '445,475p' artela/x/evm/keeper/evm.go  # runs only when vmErr == nil
sed -n '222,232p' artela/x/evm/keeper/evm.go  # commit() skipped when res.Failed()
grep -n -A20 'func checkContractOwner' artela/x/evm/artela/contract/handlers.go
grep -n 'isOwner' aspect-core/djpm/contract/onwer.sol

# --- 3. ordering / execution ------------------------------------------------
grep -n 'SetPrepareProposal\|SetProcessProposal' artela/app/app.go   # both COMMENTED OUT
grep -n 'func (app \*BaseApp) DeliverTx' artela-cosmos-sdk/baseapp/abci.go
sed -n '697,735p' artela-cosmos-sdk/baseapp/baseapp.go   # ante error returns before msCache.Write()
grep -n 'emit eth tx hash and index at the very last' artela/app/ante/decorator.go
grep -n 'ExceedBlockGasLimitError\s*=' artela/ethereum/rpc/types/utils.go
#   -> "out of gas in location: block gas meter; gasWanted:"   (a SUBSTRING match)
grep -n 'TxSuccessOrExceedsBlockGasLimit' artela/ethereum/rpc/blockchain.go \
                                          artela/ethereum/rpc/tx.go
grep -n 'return nil, nil' artela/ethereum/rpc/tx.go | head -3   # receipt -> JSON null

# --- 4. PREVRANDAO panics ---------------------------------------------------
grep -n 'Random:' artela/x/evm/keeper/evm.go             # -> nil, // not supported
grep -n -A4 'func opRandom' artela-evm/vm/instructions.go
grep -n 'chainRules:' artela-evm/vm/evm.go               # Rules(num, Random != nil, time)
curl -sL https://raw.githubusercontent.com/ethereum/go-ethereum/v1.12.0/params/config.go \
  | grep -A2 'func (c \*ChainConfig) IsCancun'           # gated on IsLondon ALONE
curl -sL https://raw.githubusercontent.com/ethereum/go-ethereum/v1.12.0/common/types.go \
  | grep 'func (h Hash) Bytes'                           # VALUE receiver

# --- 5. the partial Cancun --------------------------------------------------
sed -n '84,96p' artela-evm/vm/jump_table.go              # the FIXME and the three //enable*
grep -n -A12 'func (evm \*EVM) precompile' artela-evm/vm/evm.go   # switch stops at IsBerlin
grep -n 'ShanghaiBlock\|CancunBlock\|shanghaiTime\|epochInfinite' \
  artela/x/evm/txs/support/chain_config.go

# --- 6. unsigned transactions ----------------------------------------------
grep -n 'CustomVerificationPrefix' aspect-core/djpm/aspect_impl.go   # 0xCAFECAFE
grep -n -A25 'func IsCustomizedVerification' artela/ethereum/utils/utils.go
grep -n -A45 'func (aspect Aspect) GetSenderAndCallData' aspect-core/djpm/aspect_impl.go
grep -n 'MaxTxVerificationGas' aspect-core/djpm/aspect_impl.go artela/x/evm/keeper/meter.go

# --- 7. the two lying addresses --------------------------------------------
grep -n 'aspectCoreAddr' aspect-core/types/controller.go     # 0x…A27E14
grep -n 'IsAspectContractAddr' artela/x/evm/keeper/evm.go     # intercepted on msg.To only
grep -n 'aspectId = crypto.CreateAddress' artela/x/evm/artela/contract/handlers.go
grep -n 'IsAspectDeploy' artela/x/evm/keeper/evm.go artela/ethereum/rpc/tx.go
grep -n 'EntryPointContract' aspect-core/chaincoreext/account_abstraction/types.go
grep -o 'add-genesis-contract 0x[0-9a-fA-F]\{40\}' artela/init.sh

# --- 8. the gas floor -------------------------------------------------------
grep -n 'minimumGasUsed\|MinGasMultiplier' artela/x/evm/keeper/evm.go
grep -n 'DefaultMinGasMultiplier' artela/x/fee/types/params.go     # -> 0.5

# --- 9/10. refutations and the blob demotion --------------------------------
grep -rn 'Parallel\|parallel' artela-cosmos-sdk/baseapp/*.go | grep -v _test  # nothing
grep -n -A14 'func NewTxDataFromTx' artela/x/evm/txs/tx_wrapper.go   # default -> newLegacyTx
grep -n -A16 'func SigVerificationGasConsumer' artela/app/ante/validator.go
grep -n -A24 'message MsgEthereumTx' artela/proto/artela/evm/v1/tx.proto

# --- liveness (all of these failed on 2026-08-27) --------------------------
curl -s -m 15 -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId"}' \
  https://node-euro.artela.network/rpc          # -> "error code: 522"
curl -s -m 15 -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId"}' \
  https://betanet-rpc1.artela.network           # -> "error code: 526"
curl -s -o /dev/null -w '%{http_code}\n' https://artela.network       # -> 404
curl -s -o /dev/null -w '%{http_code}\n' https://docs.artela.network  # -> 526
curl -s -o /dev/null -w '%{http_code}\n' https://artscan.artela.network # -> 521

# --- validate ---------------------------------------------------------------
cd /Volumes/TendiesTown/EVM-intel
tools/.venv/bin/python -c "import yaml;yaml.safe_load(open('chains/artela/chain.yaml'))"
tools/.venv/bin/python tools/verify.py 2>&1 | sed -n '/^artela/,/^$/p'
#   pin ok  0de86198
#   ! NO EXTRACTOR — precompile list NOT cross-checked against source
#   citations ok    119 symbol(s) confirmed, 0 line ref(s) in range
```
