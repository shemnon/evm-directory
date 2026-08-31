# IOTA EVM — what this row teaches

Pinned: `iotaledger/wasp` **v2.0.3** (`059538bb`), with `iotaledger/go-ethereum`
**v1.15.5-wasp1** (`30f95dc4`) as a companion — the latter is the EVM itself, a fork of
upstream go-ethereum v1.15.5 whose entire history above upstream is one squashed commit
titled "changes for ISC wasp", reached from wasp's `go.mod` by a `replace` directive.
Live probe: `https://json-rpc.evm.iotaledger.net`, chain id **8822**, block
**12,793,600** (`0xc33700`, timestamp 1787844123, 2026-08-27 15:22:03 UTC). Baseline
fork **cancun**.

**Evidence path taken: source, and unusually well-anchored.** The public node answers
`GET https://api.evm.iotaledger.net/v1/node/version` with `{"version":"2.0.3"}` — the
pinned tag *is* what the network runs, which almost no other row in this dataset can
say. The same host serves `GET /v1/chain` unauthenticated, giving the live governance
parameters (gas ratio, gas price, fee share, gas limits) as first-class evidence rather
than inference. `web3_clientVersion` is useless here: it returns the constant
`wasp/evmproxy`.

The single fact everything else follows from: **IOTA EVM is not a chain.** It is the
`evm` core contract of one IOTA Smart Contracts (ISC) chain, and that ISC chain is a
Move object on the post-Rebased IOTA L1 — confirmed live, because the magic contract's
`getChainID()` returns a 32-byte object id (`0x0dc44856…409d`) rather than a number, and
`getBaseTokenInfo()` returns the Move coin type `0x00…02::iota::IOTA`. wasp's own source
calls the block store "a fake blockchain (more like a list of blocks), intended for
satisfying EVM tools that depend on the concept of a block."

---

## 1. The block hash does not commit to the block's transactions

`BlockchainDB.makeHeader` computes `transactionsRoot` and `receiptsRoot` with
`types.DeriveSha(txs, &fakeHasher{})`, and `fakeHasher.Hash()` returns
`common.Hash{}` unconditionally. `stateRoot` is worse: the stored header struct has no
`Root` field at all, so it is zero in every block including genesis.

Live, at the pinned height: block `0xc33700` carries nine transactions and reports
`transactionsRoot` = `receiptsRoot` = `stateRoot` = `0x00…00`. Block `0x1` is empty and
reports the *real* `types.EmptyRootHash` (`0x56e81f17…`) for both tx and receipt roots.
That is the mainnet signal exactly inverted: a non-empty root means the block is empty.

Because `Header.Hash()` is taken over those zeroed fields, the block hash is a function
of parent hash, number, timestamp, gas used and bloom — and of nothing else. No receipt
inclusion proof is possible, no state proof is possible, and `eth_getProof` is not
implemented (and could not be — EVM state lives in ISC's KV trie, which the Ethereum
header never references). Any bridge verifying a receipt against `receiptsRoot` is
verifying nothing.

## 2. `BLOCKHASH` is unusable for every block it is supposed to answer for

Not "returns zero" — it *panics*, in two different ways, and the two cover the whole
256-block window:

- `BLOCKHASH(number-1)`: geth's `GetHashFn` short-circuits to `header.ParentHash`, then
  calls `evm.StateDB.Witness()` — which wasp implements as `panic("should not be
  called")`. Live: `-32000 should not be called`.
- `BLOCKHASH(number-2)` … `BLOCKHASH(number-256)`: the lookup reaches
  `chainContext.GetHeader`, which is `panic("not implemented")`. Live: `-32000 not
  implemented`.
- `BLOCKHASH(number-257)` and beyond: returns `0x00…00` correctly, because the
  out-of-window branch never touches either.

Even the short-circuit would have been wrong: `GetPendingHeader` never sets
`ParentHash`, so it would have returned the zero hash. In an `eth_call` this surfaces as
a JSON-RPC error; inside a transaction `applyMessage` catches the panic and produces a
`status: 0` receipt whose revert reason is the Go panic string. After MegaETH (where
`BLOCKHASH(n-1) == parentHash` held exactly) and Polygon zkEVM (where it returns a state
root), this is the third distinct failure of the same probe — and the first where the
opcode is simply not implemented on a live mainnet.

## 3. `GASPRICE` returns zero while the receipt says 10 gwei

`applyMessage` overwrites `msg.GasPrice`, `msg.GasFeeCap` and `msg.GasTipCap` with zero
before every execution, and sets `blockContext.BaseFee` to zero, because "gas fee is set
by ISC". So inside the EVM `tx.gasprice` is 0 and `block.basefee` is 0 — while the
receipt for the very same transaction reports `effectiveGasPrice: 0x2cb417800` and
`eth_gasPrice` returns `0x2540be400`.

On-chain and off-chain observers of one transaction disagree, silently, with no revert.
Any contract that reimburses a relayer as `tx.gasprice * gasUsed`, caps a gas price, or
meters cost on-chain computes zero. `COINBASE` and `PREVRANDAO` are zero for related
reasons — value paid to `block.coinbase` goes to the ISC agent for `0x0` and is gone,
and a contract seeding randomness from `block.prevrandao` gets a constant even though
the committee produces a real threshold-BLS common coin each round (reachable only as
`ISCSandbox.getEntropy()`, which returned `0x3e4abae4…ddaf` at the pinned block).

## 4. Ordering is randomised, and price buys nothing but a seat

Consensus decides a *set*, not a sequence. Each committee node proposes a batch; an
Asynchronous Common Subset admits a request iff at least **F+1** nodes proposed it; then
`AggregatedBatchProposals.OrderedRequests` sorts the admitted set by
`blake2b(requestID, requestHash, randomness)`, where `randomness` is the round's
threshold-BLS common coin, and makes a second pass swapping same-sender off-ledger
requests so their nonces increase.

Gas price appears exactly once, in `mempool.refsToPropose`, which decides what a node
*offers*. It has no effect on position within the block. There is no leader, no builder,
no priority auction, and no base fee to bid against — the price is a single governance
constant (`gasPerToken` A=1 B=10, i.e. 10 gwei) and a transaction below it is rejected.

## 5. Two rejection layers, and the ISC layer erases the transaction

This is the row's answer to the central question, and it needs both halves.

**Layer 1 — ISC request level, before the EVM runs.** `earlyCheckReasonToSkip` verifies
the request signature, then the nonce (for an Ethereum sender it reads the *EVM* nonce
directly), then the gas price against the governance minimum. Any failure makes
`runRequests` log `request skipped (ignored) by the VM` and `continue` — **without
incrementing the request index**. Three more conditions land in the same place as panics
from inside execution, in a list whose source comment reads "causes skipping the
request. Never appear in the receipt of the request": ISC block gas limit exhausted,
maximum L1 transaction size exceeded, and sender lacking the minimum fee.

In all of these the transaction is **erased**: no EVM receipt, no ISC blocklog receipt,
no transaction index, no log, no trace. `eth_getTransactionReceipt` returns null
forever, and the result is indistinguishable from never having submitted. That is the
same observable outcome as **Conflux's `Skipped`**, arrived at from the opposite
direction — Conflux invented a third receipt status; ISC simply has no receipt to
issue, because the EVM never ran. It is the exact inverse of **Taraxa**, which has no
skip path at all and mines every ordered transaction with `status: 0` and the full gas
limit charged, and unrelated to **Autonomys**, where one invalid transaction destroys
its whole bundle.

Two things soften it in practice, and neither is a guarantee: the RPC re-checks nonce
and balance at ingress and rejects synchronously, so the common cases fail before the
mempool; and a skipped off-ledger request is *not* marked processed, so it stays in the
pool and is retried at later heights until its nonce becomes valid or its 24-hour TTL
expires. A nonce that is too *low* is dropped from the pool outright.

**Layer 2 — EVM level.** Ordinary: `status: 0`, gas charged, state rolled back, nonce
incremented explicitly by `saveExecutedTx` even though the state reverted, and logs
**stripped** from the receipt. An ISC error raised by a magic-contract call is caught by
`applyMessage` and re-encoded as a standard `Error(string)` revert, so ISC prose reaches
the client as an ordinary Solidity revert reason.

## 6. A transaction can run out of *ISC* gas after the EVM has already succeeded

`applyTransaction` burns the ISC equivalent of the EVM's gas **after**
`emu.SendTransaction` returns. If that burn exceeds the request's ISC budget it panics,
`burnGasErr` is set, and the already-successful receipt is rewritten to `status: 0` with
its logs removed. The EVM's own meter never saw the limit that killed it.

The budget can also be smaller than the `gas` the transaction declared:
`calculateAffordableGasBudget` clamps it into `[minGasPerRequest, maxGasPerRequest]` =
`[10 000, 50 000 000]` and then reduces it to what the sender's L2 balance can pay. A
`gas` field above 50,000,000 is **silently truncated**, not rejected.

## 7. `gasUsed` is not the EVM's gas

Two meters. The EVM meters normally; the ISC sandbox meters separately (55 gas/byte of
state, 1 gas/byte of event, per-operation constants), and the magic contract returns
`remainingGas` **unchanged** — so calling ISC functionality costs zero EVM gas while
burning real ISC gas. `applyTransaction` then amends the receipt: `gasUsed` becomes
`max(evm_gas, isc_gas_burned × B/A)`. A transaction can therefore be charged for work no
EVM trace explains.

At the pinned block `evmGasRatio` is `{a:1, b:1}`, which makes the two units numerically
equal and the whole divergence invisible. That ratio is **chain governance state**: the
chain admin can change it with a transaction, no fork and no client release, and every
`gasUsed` on the chain changes meaning the moment they do. Live values from `GET
/v1/chain`: `evmGasRatio {a:1,b:1}`, `gasPerToken {a:1,b:10}`, `validatorFeeShare 0`,
`maxGasPerBlock 1 000 000 000`, `maxGasPerRequest 50 000 000`.

## 8. `finalized` and `safe` are lies, and there is no sentinel to warn you

The JSON-RPC serves `LatestState(ActiveOrCommittedState)`. wasp's own source defines
`ActiveState` as "the state the chain build next TX on, **can be ahead of
ConfirmedState**" (sic), and `ConfirmedState` as "the state confirmed on L1". So receipts,
balances and block numbers routinely come from ISC blocks whose committing IOTA L1
transaction has not been confirmed, and the node will pipeline an unbounded number of
them by default (`PipeliningLimit: -1`).

There is no MegaETH-style `0xffff…ff` marker: the receipt looks entirely ordinary. And
the block tags cannot rescue you, because `parseBlockNumber` maps **every negative tag**
to latest — verified live, `finalized`, `safe` and `pending` all returned byte-identical
head blocks. A bridge polling `finalized` on IOTA EVM is polling the unconfirmed tip.

## 9. Only legacy transactions exist, and not because of a policy

`EthService.SendRawTransaction` decodes with `rlp.DecodeBytes(txBytes, tx)` rather than
`tx.UnmarshalBinary`, so an EIP-2718 payload is read as a one-byte RLP string. Live,
well-formed type-0x01, 0x02 and 0x04 payloads all return `-32000 typed transaction too
short`, while the same fields as a legacy transaction get as far as RLP field
validation. Even past the decoder, `evmutil.Signer` is `types.NewEIP155Signer`, which
cannot recover a sender from any typed transaction.

So 2930, 1559, 4844 and 7702 transactions are all unsubmittable — and unprotected
pre-155 transactions are rejected too. Every transaction in every block sampled is
`type: 0x0`. This is not a fee-market decision that happens to exclude type 2; it is the
envelope layer never having been implemented.

## 10. The magic contract is neither a precompile nor a system contract

`0x1074000000000000000000000000000000000000` holds seven bytes of real state code,
`0x600180808053f3`, placed in the genesis alloc with the source comment: *"Dummy code,
because some contracts check the code size before calling the contract. The EVM code
itself will never get executed."* `eth_getCode` returns those bytes and `EXTCODESIZE`
returns 7 — which is why this row files it under `system_contracts`, per SCHEMA.md's
boundary.

But the bytes are a decoy. wasp's go-ethereum fork adds `vm.Config.MagicContracts`, a
map consulted in `Call`, `CallCode`, `DelegateCall` and `StaticCall` **before** the
precompile table and before any code lookup, dispatching to native Go — exactly like a
precompile. Two consequences worth stating: the handler returns `remainingGas`
unchanged, so the call costs zero EVM gas; and because it is reachable by
`DELEGATECALL`, ISC sandbox calls can run in a caller's own storage context.

Only one such address exists. The `0x1074` prefix additionally derives ERC20 wrappers
for IOTA L1 coin types — `0x1074` + kind byte `0x02` + the first 17 bytes of
`keccak256(coinType)` — and those carry genuine `ERC20Coin` runtime bytecode. Probed
live, `ERC20CoinAddress("0x00…02::iota::IOTA")` returned
`0x107402967f041f3b1d87754735e0d272d554c266`, matching the derivation exactly, but
`eth_getCode` there is empty: the address space is real, the base-coin wrapper is not
registered on mainnet.

## 11. `eth_getBalance` does not read EVM state

`StateDB.GetBalance`, `AddBalance` and `SubBalance` all forward to the ISC `accounts`
core contract through the sandbox. Balances are kept in 9-decimal base-token units plus
a per-account 18-decimal `weiRemainder`, so wei precision *is* preserved on L2 — unlike
Arc, no dust is destroyed. But any ISC request that credits or debits an
Ethereum-address agent — an L1 deposit, a withdrawal, a governance payout — changes an
EVM balance with **no transaction, no receipt, no log and no trace**. Same shape as
Injective's batch auction, reached by a different route: here the ledger is simply not
the EVM's.

## 12. Small structural facts that break tools

- **The EVM chain id is a `uint16`.** It is typed that way in `BlockchainDB.GetChainID`,
  `emulator.Init` and `EthService.ChainId`. No ISC chain can have an EVM chain id above
  65535.
- **`BLOBBASEFEE` crashes.** Cancun enables opcode `0x4A`, but the block context never
  sets `BlobBaseFee`, so executing it dereferences a nil pointer. Live: `-32000 runtime
  error: invalid memory address or nil pointer dereference`. A contract compiled for
  Cancun that reads `block.blobbasefee` is un-executable here.
- **`eth_call` at a historical block uses the current clock.** State resolves correctly,
  but the pending header's timestamp comes from `sandbox.Timestamp()`. At block `0x1`,
  `TIMESTAMP` returned the wall clock of the probe and `NUMBER` returned 2.
- **One EVM block per ISC block, always.** `extractBlock` calls `MintBlock`
  unconditionally, and EVM block number equals ISC block index. Cadence is irregular —
  4 s, 5 s, 24 s, 60 s, 25 s across `0xc33700`–`0xc33705` — with a 500 ms floor
  (`ConsensusDelay`) and no empty-block production when idle. The timestamp is a
  committee order statistic (~66th percentile of node clocks), not a proposer's choice.
- **Blocks can be pruned.** `BlockchainDB.prune` deletes headers, transactions and
  receipts older than `blockKeepAmount`, wasp default **10 000**. IOTA EVM mainnet keeps
  everything (block 1 is still retrievable) but that is governance state, not a
  protocol guarantee.
- **Fees are neither burned nor paid to a producer.** `validatorFeeShare` is **0** live,
  so 100% of EVM gas fees accrue to one ISC agent, the chain admin
  (`0x8779ca52…fc5e`).

## 13. Does it earn a row in CANDIDATES.md?

`CANDIDATES.md` does not list IOTA EVM anywhere — not in Tier 0/1, not in Tier 2's
$100M-floor list, not in Tier 3, not under Blocked on evidence. Judged honestly against
that file's own criteria:

- **Mindshare (criterion 1): weak.** Few auditors and tooling maintainers are asked
  about IOTA EVM, and it absorbs no family — ShimmerEVM is the only sibling, and it is a
  separate ISC chain (id 1073) that this row deliberately does not cover.
- **Expected divergence (criterion 2): very strong, and this is the whole case.** Zero
  state root, a block hash that does not commit to its transactions, `BLOCKHASH`
  panicking on the entire valid window, `GASPRICE` returning 0 against a non-zero
  receipt, `finalized` meaning latest, and an ordered-but-invalid transaction erased
  without any receipt. That is more high-severity material than most Tier 1 rows
  produced.
- **Evidence (criterion 3): passes cleanly**, and better than most — the live node
  reports the exact pinned tag.
- **Cap floor (criterion 4): the criterion is a floor for chains that fail 1 and 2.**
  This one fails 1 and passes 2 decisively.

Verdict: **it earns a row, on divergence alone, and it would be a mistake to promote it
on mindshare.** Its real value to the dataset is as a limit case — the row where the
Ethereum interface is a compatibility shim over a foreign execution model, and where the
question "which of these header fields actually means anything?" has the answer
"almost none of them." It also independently reproduces Conflux's erasure outcome from a
completely unrelated cause, which is what turns that finding from an anecdote into a
class.

---

## Not established here

- **Whether an observed receipt can ever be *contradicted*.** Receipts are demonstrably
  served pre-L1-confirmation (finding 8), and wasp has recovery machinery
  (`PostponeRecoveryMilestones`, `cmt_log`, chain-manager rollback) that implies an
  active state can be abandoned. Whether a *published* EVM receipt has ever changed, or
  can, was not established — it needs either a rollback event to observe or a testnet
  the committee can be perturbed on. Left unrecorded rather than guessed.
- **The behaviour of ISC-level skipping under live load.** Every claim in finding 5
  rests on source; none of it was exercised, because provoking an erased transaction
  needs a funded key and a deliberately bad nonce or gas price. What an *ingress*
  rejection looks like is known (synchronous RPC error); what a *consensus* skip looks
  like from the client side is inferred from `runRequests`, not observed.
- **The ISC blocklog's view of a skipped request.** Source says skipped requests never
  reach `results` and so are never written to the blocklog. The blocklog endpoints on
  the public node require a JWT, so this was not confirmed from outside.
- **Whether `EVMGasRatio` has ever been non-1:1 on this chain.** It is 1:1 now. The
  governance history that would settle it is behind the authenticated API.
- **The IOTA L1 client.** `iotaledger/iota` was deliberately *not* added as a companion
  repo. Nothing in this row's claims derives from L1 source: the post-Rebased Move L1 is
  established from the live coin type and object-id chain id, and the L1's own
  consensus is not an EVM fact. Adding it would have pinned ~1 GB of Rust that no
  citation needs.
- **`extraData`.** Empty (`0x`) in every block sampled and never written by wasp.
  Recorded as constant, not investigated further.
- **Whether any deployed contract on the chain calls `BLOCKHASH` or reads
  `tx.gasprice`.** Both would fail or silently misbehave; no census was run.

---

## Re-verify

```sh
cd /Volumes/TendiesTown/EVM-intel
R=https://json-rpc.evm.iotaledger.net; A=https://api.evm.iotaledger.net; B=0xc33700   # 12793600

# --- pins
git -C chains/iota-evm/repos/wasp describe --tags          # v2.0.3
git -C chains/iota-evm/repos/wasp rev-parse HEAD           # 059538bb...
git -C chains/iota-evm/repos/go-ethereum describe --tags   # v1.15.5-wasp1
git -C chains/iota-evm/repos/go-ethereum log --oneline -1  # 30f95dc changes for ISC wasp
grep -n 'go-ethereum =>' chains/iota-evm/repos/wasp/go.mod

# --- the network runs exactly the pinned tag
curl -s $A/v1/node/version                                  # {"version":"2.0.3"}
curl -s $A/v1/chain | python3 -m json.tool                  # evmChainId, gasFeePolicy, gasLimits, chainAdmin

# --- source: fork stops at Cancun, no fork schedule
sed -n '/^func getConfig/,/^}/p' chains/iota-evm/repos/wasp/packages/vm/core/evm/emulator/emulator.go
# --- source: gas price / base fee zeroed on every message; NoBaseFee
grep -n 'NoBaseFee\|msg.GasPrice = big.NewInt(0)\|blockContext.BaseFee' \
  chains/iota-evm/repos/wasp/packages/vm/core/evm/emulator/emulator.go
# --- source: fake roots, no state root, pruning
grep -n 'fakeHasher\|DeriveSha\|func (bc \*BlockchainDB) prune' \
  chains/iota-evm/repos/wasp/packages/vm/core/evm/emulator/blockchaindb.go
# --- source: BLOCKHASH's two panics
grep -n 'should not be called' chains/iota-evm/repos/wasp/packages/vm/core/evm/emulator/statedb.go
grep -n 'not implemented' chains/iota-evm/repos/wasp/packages/vm/core/evm/emulator/emulator.go
grep -n 'StateDB.Witness()' chains/iota-evm/repos/go-ethereum/core/vm/instructions.go
# --- source: the ordering is a hash of the common coin, not a fee sort
sed -n '/func (abp \*AggregatedBatchProposals) OrderedRequests/,/^}/p' \
  chains/iota-evm/repos/wasp/packages/chain/cons/bp/aggregated_batch_proposals.go
# --- source: the two rejection layers
sed -n '/func (reqctx \*requestContext) checkReasonToSkipOffLedger/,/^}/p' \
  chains/iota-evm/repos/wasp/packages/vm/vmimpl/skipreq.go
grep -n 'Never appear in the receipt' chains/iota-evm/repos/wasp/packages/vm/vmexceptions/exceptions.go
grep -n 'request skipped (ignored)' chains/iota-evm/repos/wasp/packages/vm/vmimpl/runtask.go
# --- source: gasUsed amended from ISC gas; ISC burn can fail a successful EVM run
sed -n '/^func applyTransaction/,/^}/p' \
  chains/iota-evm/repos/wasp/packages/vm/core/evm/evmimpl/impl.go
# --- source: RPC serves the unconfirmed active state; every negative tag == latest
grep -n 'ActiveState\s*//\|ConfirmedState\s*//' chains/iota-evm/repos/wasp/packages/chain/chain.go
sed -n '/^func parseBlockNumber/,/^}/p' chains/iota-evm/repos/wasp/packages/evm/jsonrpc/types.go
# --- source: typed transactions are undecodable; EIP155-only signer
grep -n 'rlp.DecodeBytes(txBytes, tx)' chains/iota-evm/repos/wasp/packages/evm/jsonrpc/service.go
grep -n 'NewEIP155Signer' chains/iota-evm/repos/wasp/packages/evm/evmutil/signer.go
# --- source: magic contract dummy code + native dispatch ahead of precompiles
grep -n '600180808053f3' -B3 -A3 chains/iota-evm/repos/wasp/packages/vm/core/evm/evmimpl/impl.go
grep -n 'MagicContracts' chains/iota-evm/repos/go-ethereum/core/vm/evm.go

# --- live: identity
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' $R          # 0x2276
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"web3_clientVersion","params":[]}' $R   # wasp/evmproxy
# --- live: fake roots (finding 1) — 9 txs, all roots zero; block 1 empty, roots non-zero
for b in $B 0x1; do curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$b\",false]}" $R \
  | python3 -c "import sys,json;r=json.load(sys.stdin)['result'];print(r['number'],len(r['transactions']),r['transactionsRoot'],r['receiptsRoot'],r['stateRoot'])"; done
# --- live: BLOCKHASH's three regimes (finding 2)
for d in 4360019003405f5260205ff3 4360029003405f5260205ff3 436101009003405f5260205ff3 436101019003405f5260205ff3; do
  curl -s -X POST -H 'content-type: application/json' \
   -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"0x$d\"},\"$B\"]}" $R; echo; done
#   -> "should not be called" / "not implemented" / "not implemented" / 0x00..00
# --- live: GASPRICE 0 vs eth_gasPrice 10 gwei (finding 3); BASEFEE, COINBASE, PREVRANDAO
for d in 3a5f5260205ff3 485f5260205ff3 415f5260205ff3 445f5260205ff3 4a5f5260205ff3; do
  curl -s -X POST -H 'content-type: application/json' \
   -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"0x$d\"},\"$B\"]}" $R; echo; done
#   -> 0, 0, 0, 0, nil-pointer-dereference (0x4a = BLOBBASEFEE, finding 12)
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_gasPrice","params":[]}' $R          # 0x2540be400
# --- live: finalized == safe == pending == latest (finding 8)
for t in latest finalized safe pending; do curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$t\",false]}" $R \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['number'])"; done
# --- live: typed transactions are undecodable (finding 9)
curl -s -X POST -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"eth_sendRawTransaction","params":["0x02f86d82227680843b9aca008502540be4008252089411111111111111111111111111111111111111118080c080a00000000000000000000000000000000000000000000000000000000000000001a00000000000000000000000000000000000000000000000000000000000000002"]}' $R
#   -> -32000 "typed transaction too short"  (same for the 0x01 and 0x04 analogues)
# --- live: the magic contract (finding 10) — 7 bytes of code, native dispatch
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x1074000000000000000000000000000000000000\",\"$B\"]}" $R   # 0x600180808053f3
for sel in 564b81ef 2386557b 5404bbf7; do curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x1074000000000000000000000000000000000000\",\"data\":\"0x$sel\"},\"$B\"]}" $R; echo; done
#   -> getChainID() 0x0dc44856..409d ; getBaseTokenInfo() decimals 9 "0x..02::iota::IOTA" ; getEntropy()
# --- live: fork boundary — Cancun yes, Prague no, 4788/2935 absent
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x000000000000000000000000000000000000000a\",\"data\":\"0x00\"},\"$B\"]}" $R  # invalid input length
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x000000000000000000000000000000000000000b\",\"data\":\"0x00\"},\"$B\"]}" $R  # 0x (absent)
for a in 0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02 0x0000F90827F1C53a10cb7A02335B175320002935; do
  curl -s -X POST -H 'content-type: application/json' \
   -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$a\",\"$B\"]}" $R; echo; done   # both 0x
# --- live: historical eth_call uses the current clock (finding 12)
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"data":"0x425f5260205ff3"},"0x1"]}' $R

# --- schema
tools/.venv/bin/python -c "import yaml;yaml.safe_load(open('chains/iota-evm/chain.yaml'))"
tools/.venv/bin/python tools/verify.py 2>&1 | sed -n '/^iota-evm/,/^$/p'
```
