# Berachain — the empty delta was in the wrong column

**Chain ID 80094 · role: `fork` · upstream: ethereum · baseline: Osaka (BRIP-0010)**

Reference: [berachain/bera-reth `v1.4.4`](https://github.com/berachain/bera-reth) @ `aa9bc73f`,
with [beacon-kit `v1.4.1`](https://github.com/berachain/beacon-kit) @ `0a91d178` and
[bera-geth `v1.011608.0`](https://github.com/berachain/bera-geth) @ `e8f8f968` as companions.
Live probes at block **25264103** (`0x18183e7`) on `https://rpc.berachain.com`.

The backlog predicted a near-empty EVM delta, with the divergence living entirely in
consensus. **That is refuted, and refuted in an instructive way.** The consensus layer
does diverge — but the part of Berachain a contract author actually collides with is the
execution layer, and the part that genuinely *is* empty is the one the prediction never
mentioned: the precompile set.

**Second pass, 2026-08-28** — added the ordering/execution axis (**§11**, the headline of
this pass) and checked the row against Berachain's own BRIP series, which was not read the
first time. `web3_clientVersion` now answers
`bera-reth/v1.4.4-aa9bc73/x86_64-unknown-linux-gnu`, so the pinned commit is confirmed to
be what mainnet runs. New live probes are pinned at block **25415365**. **§12** answers
"what is Berachain v2".

---

## 1. The contract size limit is 32 KB, not 24 KB

BRIP-0010, Berachain's Osaka (2026-07-08), raises **EIP-170** from 24576 to **32768**
bytes and **EIP-3860** initcode from 49152 to **65536** bytes. It is a two-line
configuration change — `MAX_CODE_SIZE_OSAKA` and `MAX_INITCODE_SIZE_OSAKA` in
`src/node/evm/config.rs`, applied to `cfg_env.limit_contract_code_size` — and it is the
single most portable-code-breaking fact in this row.

Verified live, by binary search against the running network at the pinned block:

| create returning | Berachain @ 25264103 |
|---|---|
| 32768 bytes | **OK** |
| 32769 bytes | `EVM error: CreateContractSizeLimit` |
| 65536 bytes of initcode | **OK** |
| 65537 bytes of initcode | `max initcode size exceeded` |

Mainnet's limit is 24576. Nothing else in this dataset moves EIP-170. The failure mode
is asymmetric and quiet: a size linter that hardcodes 24576 reports a false failure on
Berachain, and a contract *developed* on Berachain against 32 KB cannot be deployed
anywhere else — it will be rejected at deploy time on mainnet with the same
`max code size exceeded` a developer has never seen locally.

## 2. Type byte `0x7E` collides with OP Stack's deposit transaction

Berachain has no OP Stack ancestry. It nonetheless allocates `0x7E` — OP's
`DepositTx` — to `PoLTx`, the BRIP-0004 Proof-of-Liquidity distribution transaction.
Both are unsigned, both are authored by the protocol, both report
`from = 0xfff…ffe`. The field lists are unrelated, so a decoder holding one global
type-byte map mis-parses one chain or the other:

```
eth_getTransactionByBlockNumberAndIndex(0x18183e7, 0x0)
  type 0x7e · from 0xfffffffffffffffffffffffffffffffffffffffe
  to   0xd2f19a79b026fb636a7c300bf5947df113940761   (PoL Distributor)
  nonce 0x18183e6                                    (= block number - 1)
  v = r = s = 0
```

The dataset's existing claim is that the type-byte space is nearly full and that chains
assign downward from `0x7f`. Berachain is the first row where two *unrelated lineages*
have landed on the same byte, rather than an ancestor and its descendants sharing one.

Three consensus rules make this transaction unusual even among protocol transactions:

- **It must be index 0 of every block, and must appear nowhere else.**
  `validate_pol_transaction` recomputes the expected transaction from (chain id,
  distributor address, block number, base fee, parent proposer key) and compares
  **hashes**. The transaction is a pure function of the header.
- **It consumes zero block gas** while running with a 30,000,000 gas limit. At the
  probed block its receipt reports `gasUsed 0` with **41 logs**, and the block's final
  `cumulativeGasUsed` (249042) is exactly the sum of the *other seven* receipts.
- **It is rejected by the transaction pool**, so it can only ever be synthesised by a
  block producer.

`ApplyPoLMessage` (bera-geth) / the executor's system-call path (bera-reth) bypass the
state transition entirely — no nonce check, no balance check, no gas purchase, no
refund — yet the result is surfaced as an ordinary typed receipt. An event indexer sees
Proof-of-Liquidity payouts; a gas accountant sees nothing.

## 3. The block header has 22 RLP fields

Established by reconstruction rather than by reading JSON keys, because the JSON keys
would not have proved it:

```
keccak256(rlp(21 mainnet fields))                       != block hash
keccak256(rlp(21 fields + 48-byte parentProposerPubkey)) == 0xd0e09c8b…2aea4  ✓
```

The 22nd field is the **BLS12-381 public key of the parent block's proposer**, appended
after `requestsHash`. It is `rlp:"optional"` in the struct, which makes *old* headers
decodable but does nothing for the reverse direction: a stock Ethereum header decoder
handed a Berachain header sees one element too many.

This is the seam the brief was looking for, and it runs the opposite way from the
expected one. Instead of consensus data staying in consensus, **the consensus layer's
proposer identity is consensus-critical execution-layer data**, written into the header
and read back by the next block's mandatory transaction.

Everything else in the header is mainnet's, with mainnet's meaning. `blobGasUsed` and
`excessBlobGas` are real blob gas — not repurposed as on OP Stack, not pinned to zero as
on Avalanche. `parentBeaconBlockRoot` and `requestsHash` are present, unlike Sonic.

## 4. The five Ethereum system contracts are byte-identical — and two of them lie

Diffed `eth_getCode` at the pinned block against an Ethereum mainnet node:

| address | EIP | code | consumed by BeaconKit? |
|---|---|---|---|
| `0x000F3df6…Beac02` | 4788 | **identical** | root of a *BeaconKit* block |
| `0x0000F908…002935` | 2935 | **identical** | n/a — fully inherited |
| `0x00000961…007002` | 7002 | **identical** | **yes** |
| `0x0000BBdD…007251` | 7251 | **identical** | **no — silently discarded** |
| `0x4242…4242` | 6110 | Berachain's own | yes, from Osaka |

**EIP-7251 is the sharpest silent failure here.** The consolidation predeploy is live:
it accepts a request, charges the excess fee, queues it, and the execution layer's
system call drains the queue into the block's requests list, committed inside
`requestsHash`. BeaconKit then decodes the type-`0x02` requests, validates their length,
and drops them. The source says it in one line —
*"ConsolidationRequest is introduced in Pectra but not used by us"* — and
`processOperations` iterates `requests.Withdrawals` and `requests.Deposits` and never
touches `requests.Consolidations`. A validator consolidation succeeds at every layer a
caller can observe and has no effect. Recorded `tombstoned`, not `removed`: the address
is occupied, callable, and takes payment.

**EIP-4788 is well-formed and points at the wrong object.** The ring buffer is correct
and the root is a genuine SSZ hash-tree-root — of a *BeaconKit* `BeaconBlockHeader`
(`payload_requests.go` passes `blk.GetParentBlockRoot()`). BeaconKit's header happens to
carry the same five fields as Ethereum's, so header-level generalized indices coincide.
Below that they do not: the `BeaconBlockBody` keeps empty compatibility stubs for
attestations, voluntary exits, the sync aggregate and BLS-to-execution changes, and the
`BeaconState` behind `state_root` is BeaconKit's. Every 4788-based proof library —
validator balance proofs, withdrawal-credential proofs, restaking oracles — reads a
well-formed 32-byte root and verifies against a different structure.

**EIP-6110 is repurposed.** Berachain's deposit contract sits at
`0x4242424242424242424242424242424242424242` — the address Ethereum uses for its
*testnet* deposit contracts — and emits `Deposit(bytes,bytes,uint64,bytes,uint64)`
(topic `0x68af7516…891d46`), not mainnet's five-`bytes` `DepositEvent`. Ethereum's own
deposit address is an **empty account** here, so a tool holding it as a constant gets
silent success with empty output, exactly as on Gnosis. And the request path is gated on
**Osaka**, not Prague: for thirteen months Prague was active while EIP-6110 emitted
nothing, deposits reaching BeaconKit through a separate log-watching store.

## 5. Withdrawals are issuance. There is one per block and no validator owns it

Every block carries **exactly one** withdrawal, with `index` and `validatorIndex` both
set to `2^64-1`:

```
withdrawals: [{ index: 0xffffffffffffffff, validatorIndex: 0xffffffffffffffff,
                address: 0x1ae7dd7ae06f6c58b4524d9c1f816094b1bccd8e,
                amount: 0x65a03c40 }]          # 1.705 BERA
```

BeaconKit *requires* it: `processWithdrawals` rejects any block whose first withdrawal
is not exactly `EVMInflationWithdrawal(timestamp)`, which also costs one slot of
`MAX_WITHDRAWALS_PER_PAYLOAD`. Validator withdrawals, when they exist, follow it — in 60
consecutive blocks to the pinned height there were none.

Unlike Gnosis, these credit **real native BERA**. The recipient's balance is a fixed
point: exactly `1705000000000000000` wei at every height sampled, delta 0 across the
pinned block. The withdrawal credits one block's inflation at the *end* of block *N*,
and the PoL transaction at index 0 of block *N+1* spends it. Two protocol mechanisms at
opposite ends of the block, forming a closed loop no user transaction touches.

The address is a consensus-layer config value and has moved twice (genesis → Deneb1
`0x656b95E5…` at 5.75 BERA/block → Fulu `0x1AE7dD7A…` at 1.705). The Deneb1 address
still holds 63.6M BERA and is no longer credited.

## 6. The base fee is burned; the tip goes to the coinbase; both have floors

Checked by balance delta rather than by reading the client, because that is the question
Gnosis got wrong:

```
coinbase 0x1daa6d6b… @ 25264102 → @ 25264103   = +6160500532907892 wei
```

— exactly the block's total priority fee. The base-fee portion
(`249042 gas × 1 gwei = 249042000000000 wei`) appears in no account's delta. Burned, as
on mainnet.

What *is* different is the shape of the curve. `next_block_base_fee` returns
`raw.max(min_base_fee)`, inside header validation, with a floor that has been switched
three times: 1 gwei at Prague1, **0** at Prague2, 1 gwei again at Osaka1 (2026-08-05,
anti-spam). It is 1 gwei at the pinned block — `baseFeePerGas` is exactly `0x3b9aca00`.
Osaka1 adds a **1 gwei minimum blob base fee** against mainnet's 1 wei, visible in
`eth_feeHistory` as `baseFeePerBlobGas: 0x3b9aca00`. And BRIP-0002 sets the base-fee
change denominator to **48** instead of 8, so the fee moves six times more slowly in
both directions.

There is also a mempool minimum-priority-fee validator, which is **not** a protocol rule
— the source is explicit that "it never changes block validity". It is recorded in
`fee_model` so it is not mistaken for one.

## 7. Prague3: nine days when transaction validity was a predicate over logs

On 2025-11-03 at 10:07:39 UTC — note the timestamp scheduled to the second — Berachain
activated **Prague3**. Its content is a list of eight blocked addresses, a BEX vault
address, and a single rescue address, all as **chain-configuration fields**. While
active, a block was invalid if any receipt in it contained:

- an ERC-20 `Transfer(address,address,uint256)` log whose `from` was a blocked address
  and whose `to` was not the rescue address, or whose `to` was a blocked address; or
- any `Transfer` touching the BEX vault; or
- any `InternalBalanceChanged` event emitted by that vault.

Nothing else in this dataset makes validity a predicate over **emitted logs**. It is not
a mempool filter and not a precompile revert: the transaction executes to completion and
is *then* rejected — in bera-geth by returning an error from `ApplyTransactionWithEVM`
after the receipt is built, in bera-reth in `validate_block_post_execution` after the
whole block has executed.

Two consequences worth stating plainly. First, it freezes an address **for a token that
has no freeze function**, because the rule is imposed on the log rather than on the
token. Second, bera-reth's payload builder simply gave up: `if prague3_active { …
building empty block }`, and the `while` loop that pulls from the pool is guarded by
`!prague3_active`. For the whole window the chain produced blocks containing nothing but
the PoL transaction.

**Prague4** (2025-11-12) exists only to switch Prague3 off:
`is_prague3_active_at_timestamp` returns false once Prague4 is live, and Prague4 has no
other content. A fork whose entire job is to end another fork.

The rule is dead at the pinned block. It is recorded because it shipped, and because the
machinery — a blocked-address list and a rescue address as first-class config — is still
in both clients.

## 8. Two execution clients, three fork generations apart

The brief assumed the execution layer was stock geth/reth. It is not: `berachain/bera-geth`
and `berachain/bera-reth` are both real forks, and **they do not agree on what chain this
is**.

- **bera-reth v1.4.4** (2026-07-29) is what runs. The pinned block's `extraData` decodes
  to `bera-reth/v1.4.4/linux`. Its chain config for 80094 has `osakaTime` and `osaka1`.
- **bera-geth v1.011608.0** (2026-01-20) is the newest bera-geth release, and
  `params/config.go:BerachainChainConfig` has **no `OsakaTime`** and no Osaka1 concept.
  It stops at Prague4 and cannot validate the current head.

Pinning "the Berachain client" without checking which one gives an answer that is wrong
about the code size limit, the base-fee floor and the blob schedule. This row pins
bera-reth as primary on that evidence and keeps bera-geth as a companion, because it is
the readable Go statement of the same rules — `tx_pol.go`, `ValidatePrague3Transaction`,
`ParentProposerPubkey` — for everything up to Prague4.

## 9. Osaka without PeerDAS, and an Engine API that is not the Engine API

BRIP-0010 activates Osaka **minus EIP-7594**. The client says so twice
(`src/engine/builder.rs:323`, `src/pool/mod.rs:75`): *"Osaka does not adopt EIP-7594
(PeerDAS); EIP-4844 sidecars remain"*. Blob target/max stays 3/6 at Cancun, Prague *and*
Osaka — mainnet went to 6/9 at Prague and higher through the BPO forks, of which
Berachain has none. Zero blobs were posted in the 60 blocks sampled.

This is the mirror image of BSC taking Prague's EVM half and dropping its beacon half:
Berachain takes Osaka's EVM half and drops its networking half. Two chains, opposite
halves, same lesson about fork names.

The **Engine API itself is forked**. Three non-standard methods —
`engine_newPayloadV4P11`, `engine_forkchoiceUpdatedV3P11`, `engine_getPayloadV4P11` —
carry the extra `proposerPubkey` argument BRIP-0004 needs, and `engine_getPayloadV5` is
implemented but deliberately **removed from the advertised capability set**
(`BERACHAIN_REMOVED_CAPABILITIES`), so Osaka payloads travel over V4P11 instead of the
standard V5. A stock consensus client cannot drive this execution layer and a stock
execution client cannot be driven by BeaconKit — a sharper statement of the split than
"BeaconKit replaces the beacon chain".

## 10. What actually is empty: the precompiles

`src/evm/mod.rs` builds the precompile set with the stock revm constructor,
`Precompiles::new(PrecompileSpecId::from_spec_id(spec))`, with no Berachain insertions
and no removals. Confirmed live: `0x01`–`0x12` all return empty code (native, not
predeploys), and `0x0100` returns `0x…01` for a valid P-256 vector and `0x` for the same
vector with one bit of `s` flipped. `CLZ(0)` returns 256.

This is worth stating because the intuition it defeats is a strong one. A chain with a
bespoke consensus layer "should" expose it through precompiles — that is what Sei, Flare,
Avalanche and Tron all do. Berachain reaches its consensus layer through an ordinary
upgradeable proxy called by a mandatory transaction, and through the withdrawals list.
**Zero custom precompiles, one custom transaction type, one extra header field.**

## 11. CometBFT does not order this chain. The execution layer does — and an invalid transaction kills the block

This is the question the first pass did not ask, and the intuitive answer is wrong.

**(a) What orders transactions.** Not CometBFT. BeaconKit's `prepareProposal` ignores
`req.Txs` — the CometBFT mempool — completely, and returns exactly two CometBFT
"transactions":

```go
// beacon-kit/consensus/cometbft/service/prepare_proposal.go
blkBz, sidecarsBz, err := s.BlockBuilder.BuildBlockAndSidecars(...)
return &cmtabci.PrepareProposalResponse{ Txs: [][]byte{blkBz, sidecarsBz} }, nil
```

The SSZ beacon block and the blob sidecars. **EVM transactions are never CometBFT
transactions**; to CometBFT they are opaque bytes inside one of those two blobs. The
transaction list is chosen by the *execution* layer:

```
BuildBlockAndSidecars  →  retrieveExecutionPayload
                       →  localPayloadBuilder.RetrievePayload / RequestPayloadSync
                       →  engine_getPayloadV4P11
                       →  bera-reth  src/engine/builder.rs:default_berachain_payload
                          best_txs = pool.best_transactions_with_attributes(base_fee, blob_gasprice)
```

That is reth's stock priority-fee-greedy iterator over bera-reth's own mempool. The
consensus layer's only ordering decision is *whether to propose the payload it was
handed*. So ordering does **not** commit before execution — the builder executes each
transaction as it appends it, and the list and the state root are fixed in one pass. The
contrast with Monad is exact and opposite: there consensus commits the transaction list at
height `N` and the state root only at `N+3`.

**(b) Parallel or optimistic? Neither.** A single-threaded
`while let Some(pool_tx) = best_txs.next()` loop, no speculation, no re-execution, no
conflict resolution — so there is no conflict rule for two implementations to disagree
about. The only optimism is at the consensus layer and is node-local: during
`ProcessProposal` of block *N*, a node that is the next proposer begins building *N+1*
(`handleOptimisticPayloadBuild`) and discards that work if *N* is rejected
(`handleRebuildPayloadForRejectedBlock`). Latency, not validity. Parallel execution exists
only in BRIP-0007's unshipped sequencer.

**(c) A transaction ordered but invalid at execution invalidates the WHOLE BLOCK.**

```
ProcessProposal → Blockchain.ProcessProposal → VerifyIncomingBlock
               → verifyStateRoot (WithVerifyPayload(true))
               → state_processor_payload.go: NotifyNewPayload
               → engine_newPayloadV4P11
INVALID → backoff.Permanent(ErrInvalidPayloadStatus)   (execution/engine/engine.go)
        → PROCESS_PROPOSAL_STATUS_REJECT                (process_proposal.go)
```

`engine_newPayload` has no per-transaction skip; its verdict is over the payload. And
beacon-kit ships a test for **precisely** the case the brief asks about — a transaction
priced below the block base fee, injected into an otherwise valid proposal:

```go
// beacon-kit/testing/simulated/malicious_proposer_test.go
// TestProcessProposal_BadBlock_IsRejected
s.Require().Equal(types.PROCESS_PROPOSAL_STATUS_REJECT, processResp.Status)
s.Require().Contains(s.LogBuffer.String(), errors.ErrInvalidPayloadStatus.Error())
s.Require().Contains(s.LogBuffer.String(),
    "max fee per gas less than block base fee: address 0x20f3…51D4, "+
    "maxFeePerGas: 10000000, baseFee: 765625000")
```

**Why it almost never arises.** The list is built by the proposer's own EL, which executes
as it appends. In `default_berachain_payload`, a nonce-too-low transaction is skipped
(`"skipping nonce too low transaction"`), any other invalidity calls `best_txs.mark_invalid`
and drops the transaction's dependents, and both paths `continue` **inside the builder** —
before anything reaches a payload. The base-fee case resolves the same way:
`best_transactions_with_attributes` is parameterised on the *new* block's base fee, so when
Osaka1 restored the 1 gwei floor on 2026-08-05, sub-floor transactions simply stopped being
selected. Only a faulty or Byzantine proposer produces the failing block.

**What an RPC client observes: nothing at all.** The rejected proposal never becomes a
block. CometBFT re-proposes the height with the next proposer, and single-slot finality
means the canonical chain never contains the rejected block — no receipt, no `status: 0`
receipt, no orphan, no reorg, nothing to poll. The transaction is not consumed; it stays in
the EL mempool and is retried at a later height or dropped. Live at 25415365, the public
RPC's `txpool_status` is `{pending: 0x0, queued: 0x0}` — nothing queues here.

Placed against the rest of this batch, Berachain is a third pole:

| chain | mechanism | what the client sees |
|---|---|---|
| Conflux · IOTA EVM · **Artela** | ordered then erased | receipt `null` forever — indistinguishable from never-submitted |
| Taraxa | no skip path | receipt, `status: 0`, full gas limit charged |
| Autonomys | poisons the bundle | operator slashed |
| RISE | cannot arise | synchronous admission, execution precedes publication |
| **Berachain** | **whole block rejected** | **no block at that round; nothing observable** |

Artela is the instructive comparison because it is *also* CometBFT. There the EVM is
in-process and the erasure is an indexing accident — the tx is provably in the block with
no index entry. Berachain's EVM is a **separate process behind the Engine API**, so the
verdict CometBFT receives is about the payload, not about a transaction. Same consensus
engine, opposite failure mode, and the Engine API boundary is the whole reason.

**The one time it really happened, the chain stopped ordering.** Every other validity rule
here is decidable at selection time — signature, nonce, balance, gas price against the base
fee. **Prague3 was not.** "Is there a receipt in this block whose logs mention one of eight
addresses" is a predicate over *execution output*, and it was evaluated in
`validate_block_post_execution`, after the entire block had run, returning a
`ConsensusError` over the **block**. For nine days in November 2025 Berachain genuinely had
the state this row otherwise reports as unreachable: a transaction validly ordered,
executed to completion, and then invalidating the block. The builder's answer was not to
skip, refund or fail the transaction — it was to stop ordering:

```rust
// src/engine/builder.rs
let prague3_active = chain_spec.is_prague3_active_at_timestamp(attributes.timestamp());
if prague3_active { debug!(target: "payload_builder", "Prague3 is active, building empty block"); }
while !prague3_active && let Some(pool_tx) = best_txs.next() { … }
```

Nine days of blocks containing nothing but the mandatory PoL transaction is what a
consensus rule keyed on execution output costs when the block builder cannot predict it.

**The PoL transaction's position is fixed, and it runs first.** `apply_pre_execution_changes`
runs the EIP-2935 blockhashes call, then the EIP-4788 beacon-root call, then
`execute_pol_transaction_with_receipt` — and only then does the builder enter the selection
loop. The verifying side enforces the position in both directions: `validate_pol_transaction`
requires `transactions[0]` to be a PoL transaction *and* walks indices `1..n` rejecting any
PoL transaction found there. So **no user transaction in a block can affect the distribution
call**, because none has executed when it runs. The coupling is across the block boundary
instead: the EIP-4895 inflation withdrawal is credited at the end of block *N* and the PoL
call at the top of *N+1* spends it. A second coupling is sharper — the expected PoL
transaction is derived from *(chain id, distributor, block number, **base fee**, parent
proposer key)* and checked by hash, so switching the base-fee floor changes the bytes of the
block's mandatory transaction. The fee floor is an input to a consensus-critical
transaction hash, not only a user-facing rule.

One thing the protocol does **not** require: that the call succeed. The executor treats only
an EVM-level `Err` from `transact_system_call` as fatal and never inspects
`result.is_success()`. A *reverting* `distributeFor` would produce a `status: 0` receipt at
index 0 inside a perfectly valid block. Missing, moved or byte-different invalidates the
block; failing does not.

**(d) Preconfirmations: nothing to report — and that is the finding.** CometBFT gives
single-slot finality, so an `eth_getTransactionReceipt` answer is already final and cannot
change. There is no early receipt and no provisional block hash — no analogue of MegaETH's
`blockHash: 0xffff…ff`. **BRIP-0007 "Berachain Preconfirmations" designs one** and it is the
MegaETH shape reached from the other direction: a single Sequencer built as a bera-reth
add-on seals a *partial block* every 200 ms, signs it, pushes it to RPC nodes over a
websocket method `preconf_newPartialBlock`, and those nodes re-execute it and then
**override** `eth_getBalance`, `eth_getTransactionCount`, `eth_estimateGas`,
`eth_getBlockByNumber`, `eth_gasPrice` and `eth_getTransactionReceipt` to serve
pre-confirmed state — held only in memory, discarded whenever a new fork-choice head
arrives, and explicitly reorg-able when fallback building triggers. It would also be the
first place Berachain executes transactions in parallel.

None of it is shipped. Status `Review` since 2025-10-22; `grep -ri preconf src/` in
bera-reth v1.4.4 finds **nothing**; the only trace in the pinned tree is a nightly Docker
job that builds the `preconf-dev` *branch*; and the public RPC answers the method with
`-32601 Method not found` at block 25415365. Recorded as `adoption: proposed` so the
negative is pinned rather than assumed — when it lands, this section needs rewriting.

BRIP-0009 (Final, 2026-01-11) closes the loop with §8: bera-geth was deprecated *because*
of this. "Future protocol enhancements — particularly the preconfirmation network described
in BRIP-0007 — will require deep integration with reth-sdk for block builder and RPC
modifications." The two-clients-three-forks divergence the first pass found empirically is
a deliberate consequence of moving block building into reth.

## 12. "Berachain v2" is not a hard fork

Asked directly, and the answer is (b): **a product name for something already in this row,
under other names.**

The chain's protocol forks are, completely: `genesis`, `prague`, `prague1`, `prague2`,
`prague3`, `prague4`, `osaka`, `osaka1`. There is no `v2` in
`src/hardforks/mod.rs:BerachainHardfork`, none in the `berachain` object of
`tests/fixtures/mainnet-genesis.json`, none in bera-geth's `params/config.go`, and no BRIP
numbered or titled "v2" in `berachain/BRIPs`. Two different things carry the name:

- **"Berachain V2"** (blog, pre-mainnet) — the architecture rewrite that produced the
  BeaconKit-plus-forked-EL design this row already describes. It predates chain 80094's
  genesis.
- **"PoL v2" / "PoL Next"** (May 2026, docs changelog) — the Proof-of-Liquidity
  *tokenomics* generation: BGT phased out, emissions consolidated. It ships as **contract
  upgrades behind the PoL Distributor proxy**, plus governance action. At the protocol
  layer it is invisible *by design*, and the reason is already recorded here: `0xD2f1…0761`
  is an upgradeable proxy whose **address** is a chain-config field (hard fork to change)
  but whose **code** is not (governance to change). What the protocol's mandatory per-block
  call actually does is governance-mutable without a client release. That is the whole
  mechanism by which a "v2" of Proof-of-Liquidity can happen with no fork at all.

The one place PoL vNext *does* reach consensus is BRIP-0010 §8, "Proof of Liquidity:
Consensus Layer Parameter Updates" — `EVMInflationAddressFulu` and `EVMInflationPerBlockFulu`
— and both values are already in this row (`0x1AE7dD7A…`, 1.705 BERA/block, replacing
Deneb1's `0x656b95E5…` at 5.75). **Nothing about "Berachain v2" is missing from the row.**

Reading the BRIP series did turn up three genuine gaps, now fixed:

- **BRIP-0010's own title is "Fusaka Hardfork Specification."** The row called it "Berachain
  Osaka". Both are right for different halves — `osakaTime` in the EL config, `fulu` in the
  CL, one timestamp — but a reader searching Berachain's own documents for "Osaka" will find
  a fork called Fusaka. Recorded in `forks.note` and in the BRIP-0010 entry.
- **EIP-7823 and EIP-7883 (MODEXP bounds and repricing) were unrecorded**, and under this
  schema an omission silently asserts `inherited`. They are named in BRIP-0010 and asserted
  by end-to-end tests in the client (`test_eip7823_modexp_oversized_input_halts_osaka`,
  `MODEXP_MIN_GAS_OSAKA = 500`). Now `inherited` with source.
- **EIP-7918 may be a second Osaka omission.** BRIP-0010's rationale says plainly that
  "EIP-7918 (blob base fee) was excluded as Berachain does not use blob transactions" —
  which would make Berachain's Osaka *mainnet Osaka minus 7594 minus 7918*. But unlike
  PeerDAS, whose exclusion is asserted twice in bera-reth's own source, nothing in the
  client confirms the reserve-price floor is off, and a Reth SDK wrapper inherits upstream
  behaviour unless it overrides it. Recorded `unrecorded`, not guessed. See *Not established*.

BRIP-0003 (**Stable Block Time**) is also now recorded: block *cadence* is a consensus rule
here, not a node setting. Vanilla CometBFT paces blocks with each validator's local
`timeout_commit`; BRIP-0003 replaces it with an algorithmic delay from an
`(InitialTime, InitialHeight)` checkpoint, gated on a consensus parameter
`Feature.SBTEnableHeight`, and a node that passes that height without the delay state
**panics**. It is why "2 s block time" is a protocol claim and not an average.

## Not established here

- **EIP-7702 (`unrecorded`).** Type `0x04` is in bera-reth's envelope and no Berachain
  fork touches delegation, but the interaction between a 7702 delegation and the PoL
  system call was not read, and no `0x04` transaction appeared in the 60 blocks sampled.
- **EIP-3529 (`unrecorded`).** No Berachain fork touches refund accounting; not read.
- **The PoL Distributor's implementation.** `0xD2f1…0761` is an upgradeable proxy. Its
  address is a chain-config field (hard-fork to change) but its *code* is behind the
  proxy (governance to change), so what the protocol's mandatory per-block call actually
  does is mutable without a client release. The implementation contract was not
  retrieved or read, and the 41 logs it emits were not decoded.
- **BeaconKit's `BeaconState` layout** was not enumerated field by field. The 4788
  finding rests on the `BeaconBlockBody` differing and on `state_root` being BeaconKit's;
  the precise set of generalized indices that a mainnet proof library would mis-resolve
  is not recorded.
- **Whether any validator withdrawal has ever appeared.** 60 consecutive blocks is a
  small sample; the claim recorded is about those blocks, not about all history.
- **A mainnet control for the EIP-170 probe.** Three public Ethereum endpoints refused
  the `eth_call` (403 / 521 / internal error), so the 24576 contrast rests on the
  protocol constant rather than on a matched live probe.
- **Precompile extraction.** `verify.py` reports `NO EXTRACTOR` for this slug; the
  "stock revm set" claim rests on reading the constructor and on the live probes above,
  not on a mechanical diff.
- **EIP-7918 (`unrecorded`).** BRIP-0010's rationale excludes it; the client neither
  confirms nor denies it, and bera-reth inherits upstream reth's Osaka unless it overrides.
  What would settle it: a read of the pinned reth dependency's Osaka blob-fee path, or an
  executed blob transaction on Berachain — none appeared in any sampled block.
- **The invalid-payload rejection was not reproduced on mainnet.** The `(c)` answer rests
  on the source path and on beacon-kit's own simulated test, not on an observed mainnet
  rejection: producing one requires being the proposer. No attempt was made to submit an
  underpriced transaction to the public RPC, so the *submission-time* rejection message a
  wallet would see is not recorded — only the consensus-time behaviour is.
- **Whether a reverting PoL call has ever occurred.** The claim that a failing
  `distributeFor` leaves the block valid is a source read of bera-reth's executor (only an
  EVM-level `Err` is fatal; `result.is_success()` is never inspected). No block with a
  `status: 0` receipt at index 0 was searched for.
- **BRIP-0005 and BRIP-0006** (validator cutting-board automation) are `Draft` and were not
  recorded: they describe off-chain strategy services and reward-allocation policy, with no
  EL or CL rule change. Named here so the omission is deliberate.

## Re-verify

```sh
git clone --depth 1 --branch v1.4.4  https://github.com/berachain/bera-reth
git clone --depth 1 --branch v1.4.1  https://github.com/berachain/beacon-kit
git clone --depth 1 --branch v1.011608.0 https://github.com/berachain/bera-geth

R=https://rpc.berachain.com
B=0x18183e7          # 25264103
call(){ curl -s -X POST -H 'content-type: application/json' -d "$1" $R; }

# --- source: the five Berachain forks and their parameters
python3 -m json.tool bera-reth/tests/fixtures/mainnet-genesis.json | sed -n '/"berachain"/,/^  }/p'
sed -n '1,25p'   bera-reth/src/hardforks/mod.rs            # Prague1-4, Osaka1
grep -n 'MAX_CODE_SIZE_OSAKA\|MAX_INITCODE_SIZE_OSAKA' bera-reth/src/node/evm/config.rs
grep -n 'raw.max(min_base_fee)' -B12 bera-reth/src/chainspec/mod.rs
grep -n 'min_blob_fee' bera-reth/src/chainspec/mod.rs      # Osaka1 blob floor
grep -n 'EIP-7594' bera-reth/src/engine/builder.rs bera-reth/src/pool/mod.rs
grep -n 'building empty block' -A6 bera-reth/src/engine/builder.rs   # Prague3 halt
sed -n '110,210p' bera-reth/src/consensus/mod.rs           # log-predicate validity
sed -n '40,55p'  bera-reth/src/engine/rpc.rs               # V4P11, removed getPayloadV5
grep -n 'DEPOSIT_EVENT_SIGNATURE' -B8 bera-reth/src/deposits.rs
grep -n 'prev_proposer_pubkey' -B6 bera-reth/src/primitives/header.rs
grep -n 'Precompiles::new(PrecompileSpecId' bera-reth/src/evm/mod.rs

grep -n 'PoLTxType = ' bera-geth/core/types/transaction.go  # 0x7E
sed -n '30,70p'  bera-geth/core/types/tx_pol.go
sed -n '/BerachainChainConfig = /,/^\t}/p' bera-geth/params/config.go | grep -c OsakaTime  # 0 — geth stops at Prague4
grep -n 'ValidatePrague3Transaction' -A28 bera-geth/core/state_processor.go

grep -rn 'not used by us' beacon-kit/consensus-types/types/consolidation_request.go
grep -rn 'which we use for withdrawals' beacon-kit/consensus-types/types/withdrawal_request.go
grep -n 'ErrFirstWithdrawalNotEVMInflation' -B8 beacon-kit/state-transition/core/state_processor_withdrawals.go
grep -n 'EVMInflationWithdrawalIndex' beacon-kit/state-transition/core/state/constants.go
grep -n 'mainnetEVMInflationAddressFulu\|mainnetEVMInflationPerBlockFulu' beacon-kit/config/spec/mainnet.go
grep -n 'parentBeaconBlockRoot = blk.GetParentBlockRoot' -B4 beacon-kit/consensus-types/types/payload_requests.go

# --- live: EIP-170 / EIP-3860 raised limits (initcode `62 <N> 6000 f3`)
for N in 32768 32769; do
  D=0x62$(printf %06x $N)6000f3
  call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"$D\"},\"$B\"]}"; echo " <- $N"
done   # 32768 OK, 32769 -> CreateContractSizeLimit
python3 - <<'PY'          # 65536 OK, 65537 -> max initcode size exceeded
import json,urllib.request
def c(n):
    d="0x62"+"%06x"%100+"6000f3"+"00"*(n-7)
    r=urllib.request.Request("https://rpc.berachain.com",
      data=json.dumps({"jsonrpc":"2.0","id":1,"method":"eth_call",
      "params":[{"data":d,"gas":"0x2255100"},"0x18183e7"]}).encode(),
      headers={"content-type":"application/json"})
    print(n, json.load(urllib.request.urlopen(r)))
c(65536); c(65537)
PY

# --- live: the 22nd header field, proved by reproducing the block hash
#   rlp(21 mainnet fields) -> wrong hash; + 48-byte parentProposerPubkey -> 0xd0e09c8b…2aea4

# --- live: system contracts byte-identical to Ethereum mainnet
for A in 0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02 \
         0x0000F90827F1C53a10cb7A02335B175320002935 \
         0x00000961Ef480Eb55e80D19ad83579A64c007002 \
         0x0000BBdDc7CE488642fb579F8B00f3a590007251; do
  P="{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$A\",\"$B\"]}"
  diff <(call "$P") <(curl -s -X POST -H 'content-type: application/json' \
        -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$A\",\"latest\"]}" \
        https://ethereum-rpc.publicnode.com) >/dev/null && echo "$A identical"
done
call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x00000000219ab540356cBB839Cbe05303d7705Fa\",\"$B\"]}"   # -> 0x  (empty)
call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x4242424242424242424242424242424242424242\",\"$B\"]}"   # -> 4190 bytes

# --- live: PoL tx, zero gas, 41 logs; withdrawals; base fee burned, tip to coinbase
call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getTransactionByBlockNumberAndIndex\",\"params\":[\"$B\",\"0x0\"]}"
call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockReceipts\",\"params\":[\"$B\"]}"        # receipt[0]: gasUsed 0, 41 logs
call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",false]}"  # withdrawals, parentProposerPubkey
for H in 0x18183e6 0x18183e7; do
  call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBalance\",\"params\":[\"0x1daa6d6b90e2375d4262cde3c5553bc31688a969\",\"$H\"]}"
done   # delta = 6160500532907892 = the block's total priority fee; base fee lands nowhere
for H in 0x18183e6 0x18183e7; do
  call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBalance\",\"params\":[\"0x1AE7dD7AE06F6C58B4524d9c1f816094B1bcCD8e\",\"$H\"]}"
done   # 1705000000000000000 at both — one block of inflation, spent and re-minted

# --- source: ORDERING. CometBFT gets two opaque blobs, the EL picks the tx list
grep -n 'Txs: \[\]\[\]byte{blkBz, sidecarsBz}' -B6 beacon-kit/consensus/cometbft/service/prepare_proposal.go
grep -n 'BuildBlockAndSidecars' -A20 beacon-kit/beacon/validator/block_builder.go | head -40
sed -n '/func (s \*Service) retrieveExecutionPayload/,/^}/p' beacon-kit/beacon/validator/block_builder.go
grep -n 'best_transactions_with_attributes\|while !prague3_active' bera-reth/src/engine/builder.rs
grep -n 'skipping nonce too low\|mark_invalid' bera-reth/src/engine/builder.rs

# --- source: (c) invalid tx -> whole block REJECTED, with beacon-kit's own test
grep -n 'NotifyNewPayload(ctx, payloadReq, true)' -B8 beacon-kit/state-transition/core/state_processor_payload.go
grep -n 'ErrInvalidPayloadStatus' -A4 beacon-kit/execution/engine/engine.go       # backoff.Permanent
grep -n 'PROCESS_PROPOSAL_STATUS_REJECT' beacon-kit/consensus/cometbft/service/process_proposal.go
sed -n '/TestProcessProposal_BadBlock_IsRejected/,/^}/p' \
  beacon-kit/testing/simulated/malicious_proposer_test.go | tail -20
#   -> asserts REJECT + "max fee per gas less than block base fee: … baseFee: 765625000"

# --- source: PoL runs BEFORE user txs, and its index is fixed in both directions
grep -n 'fn apply_pre_execution_changes' -A14 bera-reth/src/node/evm/executor.rs
sed -n '/fn validate_pol_transaction(/,/^    }/p' bera-reth/src/consensus/mod.rs
grep -n 'is_success' bera-reth/src/node/evm/executor.rs   # -> no hits: a reverting PoL call is not fatal

# --- source: (d) no preconf code in the pinned client
grep -ri preconf bera-reth/src/ || echo "no preconf code in v1.4.4"
grep -n 'preconf-dev' bera-reth/.github/workflows/docker-nightly-preconf.yml

# --- source: BRIP-0003 Stable Block Time is a consensus rule, and panics if skipped
grep -n 'SBTEnableHeight' -B3 -A12 beacon-kit/consensus/cometbft/service/finalize_block.go

# --- BRIPs (primary source for §12; not a git clone, fetch raw)
for i in 0003 0007 0009 0010; do
  curl -sL "https://raw.githubusercontent.com/berachain/BRIPs/main/meta/BRIP-$i.md" | head -12
done
#   BRIP-0010 title == "Fusaka Hardfork Specification"; §8 == the PoL vNext CL params
#   BRIP-0007 status == Review;  BRIP-0009 status == Final (bera-geth deprecated for reth-sdk)

# --- live @ 25415365: pinned commit confirmed, empty pool, no preconf namespace
call '{"jsonrpc":"2.0","id":1,"method":"web3_clientVersion","params":[]}'
#   -> bera-reth/v1.4.4-aa9bc73/x86_64-unknown-linux-gnu   (== the pinned commit)
call '{"jsonrpc":"2.0","id":1,"method":"txpool_status","params":[]}'        # {pending:0x0,queued:0x0}
call '{"jsonrpc":"2.0","id":1,"method":"preconf_newPartialBlock","params":[]}'  # -32601 Method not found
call '{"jsonrpc":"2.0","id":1,"method":"rpc_modules","params":[]}'             # -32601 (not exposed)

# --- live: Osaka EVM, stock precompiles
call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"0x60001e60005260206000f3\"},\"$B\"]}"  # CLZ(0) = 256
V=0x33e312814c04744566da589b441f5d193c7b8ac3cfcac66a125c8a6432416539f77f4c3c67be0834c8ba25d24157c68da61cb9aa1c4b634ceef8af33bf5063ad576a523698a72caa4b282a9a09791049c13012613db47705c53a1ab2ed1090006413e370318a922cecfaa94ba2188dd419f586356fa774c766cd6c450295fee95dce9ce0557b0a8f1cef5c663f362cfffc910e3094afc82bbbc7a0a92b0b6bdb
call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"$V\"},\"$B\"]}"  # -> 0x…01
for i in $(seq 1 18); do
  A=$(printf '0x%040x' $i)
  call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$A\",\"$B\"]}"
done   # all 0x — native, not predeploys
call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_feeHistory\",\"params\":[3,\"$B\",[50]]}"  # baseFeePerBlobGas 0x3b9aca00
```
