# MegaETH — what this row teaches

Pinned: `megaeth-labs/mega-evm` **v1.7.0** (`30ce038c`) — the EVM — with
`megaeth-labs/stateless-validator` **v2.0.16** (`11078d7b`) as a companion, which
supplies an independent re-execution client *and* the canonical mainnet genesis.
Live probe: `https://mainnet.megaeth.com/rpc` / `wss://mainnet.megaeth.com/ws`,
chain id **4326**, block **24869120** (timestamp 1787666131, 2026-08-25). Baseline
fork **prague**, reached through OP **Isthmus**. A **second probe session on
2026-08-28** added findings 13-15 (ordering, parallelism, ordered-then-invalid) and is
pinned separately: block **25149945** (`0x17fc1f9`, timestamp 1787946956) for the
admission and `eth_call` probes, and blocks **25048453-25048478** for the mini-block /
sealed-block comparison. Still Rex6; nothing new is attached to 24869120.

**Evidence path taken: (a), source.** The evidence gate was the first question, and
the answer is split. The *EVM* is public and released under tags — nine months of
them, `v1.0.0` through `v1.7.0`. The *node* is not: the live RPC identifies itself as
`mega-reth/v2.2.0-ea126e0` and no `mega-reth` repo exists under `megaeth-labs`
(`megaeth-labs/reth` is a stale July-2025 fork carrying only `perf-v0.1.0-alpha.*`
tags and no MegaETH code). So the row is `evidence: source` for everything the state
transition decides, and rigorously `src_live:`/`src_doc:` for everything the
sequencer decides. Every mini-block claim below is a live observation, not source.

---

## 1. The prediction was right about *where* the divergence is and wrong about *how*

CANDIDATES.md predicted the envelope and finality semantics would diverge far more
than the EVM does. The envelope divergence is real (findings 2-4), but the EVM
divergence turned out to be **the larger of the two** — MegaETH has a second gas
meter, a rewritten 63/64 rule, opcode costs that depend on the shape of the state
trie, and a detention mechanism that changes your gas budget because you read
`block.timestamp`. That is a bigger EVM delta than any OP Stack descendant in this
dataset, Celo included.

## 2. `BLOCKHASH` is honest — the negative result

`BLOCKHASH(number-1)` executed at block 24869120 via `eth_call` returned
`0x42c631c2...3986`, which is byte-for-byte that block's `parentHash` and the `hash`
of block 24869119. Mini-blocks are **not** addressable by `BLOCKHASH`, do not consume
block numbers, and do not appear in the EIP-2935 history contract. After Polygon
zkEVM (returns a *state root* from `BLOCKHASH`) and Monad (deferred execution), the
suspicion that a 10 ms cadence must leak into the EVM's view of blocks is worth
testing — and here it is refuted. `block.number` advanced exactly 1/second across
twelve consecutive samples; `block.timestamp` advanced exactly +1 s each.

## 3. The receipt arrives before the block exists, carrying an all-ones block hash

This is the finding that answers "can a receipt be returned for a transaction in a
state that later changes". Subscribing to `miniBlocks` over WebSocket and racing the
HTTP endpoint:

- the streamed receipt carries `blockNumber` = the EVM block **not yet sealed** and
  `blockHash` = `0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff`;
- at that instant `eth_blockNumber` still returned the *previous* block, and
  `eth_getTransactionReceipt` for the same hash returned **null**;
- ~2.5 s later the same receipt came back from `eth_getTransactionReceipt` with the
  real block hash, all other fields identical.

So the sentinel is not a placeholder for a missing field — it is a placeholder for a
block that does not exist yet. Anyone treating a streamed receipt's `blockHash` as a
block identifier indexes `0xffff...ff`.

## 4. MegaETH and Monad break the same invariant from opposite ends

Monad's consensus commits an ordering **before** execution, so a committed block's
state root lags three heights behind it: *you see a block whose state you cannot yet
trust*. MegaETH executes **first** and streams receipts, logs and state changes
before the enclosing block header exists: *you see state that does not yet have a
block*. Both destroy the mainnet identity "a receipt names a block that exists", and
the two failure modes need opposite defences — Monad's consumer must wait for a later
block, MegaETH's must wait for a hash to stop being `0xffff...ff`.

Two coexisting height spaces make this concrete: at EVM block 24,869,417 the global
`mini_block_number` was **2,439,447,937**. Mini-block timestamps are in
**microseconds** (deltas of ~9.3 ms observed), are signed by the sequencer with
secp256k1 over `keccak256(rlp(header))` of eight fields (Rex5+), and most mini-blocks
are empty — seven of eight consecutive ones observed had `gas_used: 0x0` and the
empty transaction/receipt roots. They are still numbered and still signed.

## 5. Because `block.timestamp` cannot express the chain's own clock, the chain shipped a second one

`block.timestamp` has 1-second resolution while the sequencer seals ~100 mini-blocks
per second, so the EVM structurally cannot see time at the granularity the chain runs
at. MegaETH's answer is a **system contract**: `HighPrecisionTimestamp` at
`0x6342...0002` returns microseconds since the epoch — the moment the transaction
began executing on the sequencer — non-decreasing within a block and capped at
`block.timestamp x 1,000,000`. Probed at the pinned block it returned
`0x659df74b620a3`, whose second-part matches that block's timestamp exactly. It is a
*sequencer-attested* clock, not a consensus one, and reading it costs you the 20M
compute-gas detention.

## 6. A dual gas meter, and a fifth distinct shape of "failed with gas remaining"

Every transaction pays **compute gas** (identical to Ethereum's) plus **storage gas**,
both from one `gas_limit`. Intrinsic cost is **60,000** (21,000 + 39,000). Storage gas
prices code deposit at 10,000/byte, `LOG` topics at 3,750, calldata at 40/160 per byte
— and `SSTORE` zero-to-non-zero at `20,000 x (m-1)` where *m* is the **SALT bucket
multiplier**, a property of the current state trie rather than of the transaction. No
other row in this dataset prices an opcode by state layout.

On top of the gas limit sit four resource dimensions — compute gas (200M/tx), data
size (12.5 MB), KV updates (500,000), state growth (1,000) — enforced *during*
execution. Exceeding one halts immediately, **preserves and refunds the remaining
gas**, and includes the transaction in the block with `status: 0` and no state
changes. Placed against the four shapes already recorded: Taiko truncates the block,
Linea and Polygon zkEVM discard with no receipt, Moonbeam surfaces it as OutOfGas.
MegaETH is the only one that gives you a mined, failed receipt *and* your gas back.
At block level the *last* transaction may exceed the limit and is still included.

## 7. The 63/64 rule is 98/100

`forward_gas_ext` caps forwarded gas at 98% of the parent's remaining gas, so the
parent retains 2% rather than ~1.6%. This is a change to a rule stable since EIP-150
in 2016 and hard-coded in deployed contracts. Its knock-on is visible in the source:
because MegaETH's 10x `LOG` storage gas makes a single `LOG1` cost ~4,500 gas —
exceeding the EVM's 2,300 `CALL_STIPEND` — Rex4 had to add a separate 23,000-gas
`STORAGE_CALL_STIPEND` on value-transferring `CALL`/`CALLCODE`, spendable only on
storage gas and **burned if unused**, purely to keep `transfer()` to an
event-emitting `receive()` working.

## 8. A legacy transaction whose meaning depends on its sender

`check_if_mega_system_transaction` classifies a **type-0x00** transaction as an OP
deposit when its caller is the current system address *and* its callee is on a
one-entry whitelist (the Oracle at `0x6342...0001`). Signature validation, nonce
verification and fee deduction are all bypassed; the nonce still bumps; a
non-whitelisted callee halts with `SystemTxInvalidCallee`. Observed live: a receipt
from `0xa887dcb9...bd1d` to `0x6342...0001`, `type 0x0`, `effectiveGasPrice 0x0`.
**Nothing in the envelope distinguishes it from a user transaction** — this is the
first case in the dataset where the type byte is not sufficient to classify a
protocol transaction. From Rex5 the privileged address is read out of the
`SequencerRegistry` contract, so it is mutable on-chain state rather than a client
constant.

## 9. A hardfork that *removed* semantics, live, for 71 minutes

`MegaHardfork::MiniRex1.spec_id()` returns `MegaSpecId::EQUIVALENCE`: at
1764845637 mainnet **de-activated** the dual gas model, the resource limits, gas
detention and 98/100 forwarding, reverting to plain OP Isthmus. `MiniRex2` restored
them 4,295 seconds later. No reorg, no state rollback; contracts deployed under the
old rules stayed. Every other fork in this dataset only ever adds.

## 10. A descendant re-adding what its stack removed

`mini_rex()` builds the precompile set from op-revm's Isthmus table and extends it
with `revm::precompile::modexp::OSAKA` — so MODEXP runs the **EIP-7883 (Osaka)** gas
schedule on a Prague-based chain, while the op-stack row records 7883 as *removed* on
OP Stack's own Jovian client. KZG point evaluation at `0x0a` is wrapped to a flat
**100,000 gas** (2x mainnet). Those are the only two precompile divergences: **zero
added addresses**. Everything MegaETH adds is a system *contract* with real bytecode
at `0x6342...0001`-`0006` — a namespace that is MegaETH's **testnet** chain id (6342)
used as an address prefix on mainnet (chain id 4326). All six were confirmed to carry
code by `eth_getCode` at the pinned block, but the classification as contracts rather
than precompiles rests on the **source map** (`transact_deploy_*` installing real
bytecode with a checked code hash), not on the probe.

## 11. `sync_point` matters more here than for most descendants

All nine MegaETH specs map to `OpSpecId::ISTHMUS`. The op-stack row pins a
Jovian/Karst client, so inheriting it wholesale would credit MegaETH with Jovian's
`blobGasUsed` repurposing and BLS12-381 input caps that it does not have. Recorded in
`lineage.sync_point`; `blobGasUsed` here still means blob gas, and means zero.

## 12. A pinned-genesis/live-network divergence, caught the day it opened

The mainnet genesis shipped in stateless-validator v2.0.16 stops at `rex5Time`. Rex6
activated on mainnet at 1787626800 — 03:00 UTC on the day this row was written, about
11 hours before the pinned probe. mega-evm v1.7.0 implements Rex6 and the docs
schedule it, but a validator started from the repo's own genesis file would have
diverged from mainnet that morning. The row records Rex6's activation from the docs
and says so.

## 13. A mini-block is a *result*, not a plan — and the order it shows you is final

The question the `0xffff…ff` sentinel raises but does not answer is whether a mini-block
fixes an *order* that will be executed later, or streams state that has already been
computed. It is the second. The payload's `receipts` array carries `status`, `gasUsed`,
`cumulativeGasUsed` and `transactionIndex` — the transaction's **final index in the
enclosing EVM block** — under a `receipt_root` computed over them. A receipt root cannot
exist before execution, and `cumulativeGasUsed` is block-level running state that only
exists once a transaction has been *committed* into the block under construction. In the
published EVM both are produced inside `MegaBlockExecutor::commit_transaction_outcome`.
So the sentinel is not a promise about a future execution; it is a finished result
missing only its container.

Measured over a 25-second WebSocket capture (blocks 25,048,453–25,048,478; 24 fully
observed; 2,384 mini-blocks, 99 or 100 per EVM block, 2,059 of them empty), the
concatenated mini-block transaction sequence equalled the sealed block's transaction
list **exactly — same hashes, same positions, nothing added, removed or reordered — in
24 blocks out of 24, across 577 transactions**. Comparing each streamed receipt against
the final one from `eth_getBlockReceipts`: `blockHash` differed in all 577, `logs` in
262, `l1Fee` in 244; **every other field was identical, and the key sets are identical
too**. The `logs` difference is the sentinel again — each log carries its own copy of it.

**`l1Fee` is the one that matters.** In a second 13-block capture it differed in 131
receipts, and the streamed value was the *constant* `0x2db0cccd` (766,561,485 wei) for
every transaction regardless of calldata, against sealed values of 1,533,118,371 /
1,597,241,240 / 1,610,065,813 wei — roughly double, and per-transaction.
`l1GasPrice`, `l1GasUsed`, `l1BaseFeeScalar` and `l1BlobBaseFee` all match; only the
derived total is a placeholder. So the preconfirmed receipt is not merely missing a block
hash: **it under-reports what the transaction cost**, on the one fee component an OP
Stack user cannot predict. Note also that the two halves of the same payload disagree
about the missing hash: the streamed *receipt* says `blockHash: 0xffff…ff` while the
streamed *transaction* object in the same message says `blockHash: null`.

This puts MegaETH exactly where RISE is — a shred is likewise published only after
execution — and at the opposite pole from Monad, where consensus commits the transaction
*list* at height N and agrees the state root only at N+3.

## 14. The parallel EVM did not change the *executor*; it changed the *state transition*

`stateless-validator`'s README names "the hyper-optimized, **parallel**, JIT-compiled
executor on sequencer nodes" as one of three MegaETH client implementations, and
mega-evm's `AGENTS.md` says flatly that "MegaETH incorporates parallel EVM". None of that
is consensus-visible in the ordinary sense: mega-evm's state transition is sequential and
deterministic, the stateless validator replays sealed blocks single-threaded on vanilla
revm, and nothing in the published EVM re-runs, aborts or retries a transaction on
conflict. On that axis MegaETH lands where Sei, Monad and RISE's pevm already are —
conflicts are a node-local concern and two implementations cannot disagree.

**What is new is the other half.** Every other parallel chain in this dataset leaves the
state transition alone and pays for conflicts by re-executing. MegaETH instead **rewrote
the gas rules so conflicts are rarer**, and the tree says so in as many words: detention
"forces transactions that touch volatile data to terminate quickly, reducing parallel
execution conflicts without banning the access outright." The 20,000,000 compute-gas cap
a contract incurs for reading `block.timestamp` is a *consensus rule whose only purpose
is sequencer throughput*, mandatory for every client. Even `EQUIVALENCE` — the spec that
claims Optimism Isthmus equivalence — already carries block-environment access tracking
for the same reason. This is the first row where a scheduler optimisation was promoted
into the state transition function.

And the endpoint's own simulator does not model it. Calling MegaETH's `MegaLimitControl`
contract from inside `eth_call`, `remainingComputeGas()` returned **59,943,828** with no
block-environment read and **59,943,792** after `TIMESTAMP; POP` — a 36-gas difference,
not the cap to 20,000,000 the rule requires. A ~29M-gas loop placed after a `TIMESTAMP`
read completed successfully. `eth_call` *is* running the MegaETH spec (it charges the
60,000 intrinsic), so this is a deliberate omission on the simulation path — and it means
the one failure mode with no mainnet analogue is invisible to the estimator the chain's
own docs tell you is the only correct one. The same probe incidentally shows the compute
meter in `eth_call` is a fixed 60,000,000 budget that ignores the request's `gas` field.

## 15. Ordered-then-invalid: three answers, and the interesting one you can never see

The row already records the per-transaction case (finding 6): exhaust a *resource*
dimension during execution, or get your budget cut by the detention penalty, and you are
**included with `status: 0` and your remaining gas refunded**. The dual meter and the
detention penalty genuinely make a transaction's cost undeterminable at submission time,
but they never produce an unincludable transaction — they produce an ordinary failed
receipt with an unusual gas line, and the receipt cannot say which meter failed.

The genuine ordered-then-invalid case is elsewhere, and it is a real, tested code path.
`commit_transaction_outcome` **re-runs** `BlockLimiter::pre_execution_check` after
execution, because "between `run_transaction()` and `commit_transaction_outcome()`, other
transactions may have been committed, potentially exceeding block limits." On failure the
receipt is never built and the transaction is simply absent. The tree's own test —
`test_commit_time_pre_execution_check_parallel_simulation` — runs three transactions,
commits two of them out of order, and the third, which passed every check when it ran, is
refused at commit with `TransactionGasLimitMoreThanAvailableBlockGas`; `finish()` returns
**two** receipts, not three. The transaction is invalidated by *other* transactions, not
by anything about itself, and it is **erased**: no receipt, no gas, no trace.

Then the same function means the opposite thing one hop away. During block *building* an
error from `pre_execution_check` means "skip this transaction" — the module docs say so.
During block *validation* the stateless validator replays the sealed block's transactions
strictly in order and maps any error from that function to
`ValidationError::BlockReplayFailed`, **rejecting the whole block**. MegaETH holds
Conflux-style erasure and Berachain-style whole-block rejection in one mechanism,
separated only by which side of the sequencer is running it.

**And the erasure is structurally unobservable.** The receipt is constructed *inside*
`commit_transaction_outcome`, after the re-check passes, so a transaction dropped at
commit has no receipt to stream and the mini-block preconfirmation is post-commit state
by construction. A client cannot see a transaction appear in a mini-block and then vanish
from the block; 0 of 577 did. MegaETH therefore reaches the same user-visible place as
RISE — the ordered-but-invalid state cannot be observed — by the opposite route: RISE's
admission is synchronous so the state never arises at all, while MegaETH's state *does*
arise, inside the block builder, and is resolved before anything is published.

Admission is synchronous here too, and the fast path is not a laxer path. With correctly
signed transactions from a fresh zero-balance key at block 25,149,945:

| condition | answer | receipt |
|---|---|---|
| insufficient balance | `-32003 insufficient funds for gas * price + value: have 0 want 100000000000000` — **identical** from `eth_sendRawTransaction`, `eth_sendRawTransactionSync` *and* `realtime_sendRawTransaction` | null |
| wrong chain id | `-32000 RLP decoding failed: Common chain ID chainId() { return BigInt(this._chainParams.chainId); } not matching the derived chain ID 1` | null |
| gas limit 20,000,000,000 | `-32000 exceeds max transaction gas limit` | null |
| gas limit 50,000 | `-32000 Gas limit too low. Intrinsic: 60000` | null |

Two things fall out of that table beyond the answer. The last row is a live pin of the
dual gas model at the *admission* boundary: a 50,000-gas transaction that mainnet accepts
without comment is refused outright here. And the chain-id error leaks a **JavaScript
source fragment** from an ethereumjs `Common` object — so error *strings* on this endpoint
come from a gateway in front of `mega-reth`, not from the Rust client, and should not be
pattern-matched as if they did.

Placed against the batch: Conflux, IOTA, Artela and Rollkit erase; Taraxa includes and
charges the full gas limit; Autonomys drops the bundle and slashes; Berachain rejects the
whole block; RISE says the state cannot arise. MegaETH is **all three of the first, third
and fifth at once** — erasure inside the builder, whole-block rejection inside the
validator, and nothing observable at the client.

---

## Not established here

- **Whether the live network runs exactly mega-evm v1.7.0.** `mega-reth` is closed;
  the tag pins what the EVM library does, not what the sequencer binary contains.
- **EIP-7823 MODEXP input bounds.** revm's `modexp::OSAKA` is the vehicle for both the
  7883 repricing and the 7823 bounds, but revm 27.1.0 is an external crate not in the
  pinned tree and the docs mention only the gas schedule. Left `unrecorded` rather
  than guessed.
- **`extraData`.** Nine constant bytes (`0x00000000fa00000001`) in every mainnet block
  sampled, `0x00000000fa00000006` in genesis. Non-empty extraData is itself a
  departure from OP Stack; mega-evm does not parse it and no doc defines it.
  `unrecorded`.
- **Mini-block reorg behaviour.** Narrowed, not closed, by finding 13: over 24
  consecutive blocks and 577 transactions no mini-block was contradicted by the EVM
  block that followed it, and the streamed order matched the sealed order exactly. That
  is a bounded observation of ordinary traffic, not a guarantee. The docs assert the
  signature makes such misbehaviour *provable*, not impossible. What would settle it:
  nothing observational can — only the `mega-reth` source, or a deliberately induced
  block-limit race.
- **Nonce and balance invalidation between mini-block and seal.** The commit-time
  re-check covers only the seven `BlockLimiter` dimensions; it does **not** re-validate
  nonce or balance, and revm's own nonce/balance validation happens at
  `run_transaction()` time, against whatever state that (possibly speculative) execution
  saw. Whether `mega-reth`'s scheduler guarantees that two transactions from one sender
  are never executed concurrently, or re-validates the sender before commit, is in no
  published repository. **What would settle it:** (i) the `mega-reth` source; or (ii) a
  funded key submitting, within one 1-second block, two transactions with the same nonce
  and a third that drains the balance the first two depend on, then checking whether more
  than one receives a mini-block receipt. That needs funds on mainnet and was not done.
- **The scheduler itself.** How `mega-reth` partitions transactions across threads, what
  it does on a genuine read/write conflict, and whether any transaction is executed
  speculatively and discarded, are all closed. The published EVM contains no re-run,
  abort or retry path, so whatever the scheduler does is invisible to a contract — but
  "invisible" is inferred from the EVM's absence of such a path, not observed.
- **Whether detention ever actually halts a transaction on mainnet.** The rule is
  established from source (`BLOCK_ENV_ACCESS_COMPUTE_GAS`,
  `MegaHaltReason::VolatileDataAccessOutOfGas`), and finding 14 establishes live that
  `eth_call` does **not** enforce it — but the endpoint's refusal to simulate the halt is
  precisely what makes the on-chain behaviour unobservable from outside. **What would
  settle it:** a funded transaction that reads `block.timestamp` and then burns >20M
  compute gas, and its receipt.
- **Whether the commit-time drop has ever fired on mainnet.** Blocks observed used
  ~7.7M–9.8M of a 10,000,000,000 gas limit, so the block-level dimensions are nowhere
  near binding under current load. The code path is tested in-tree; it may never have
  executed in production.
- **Realtime submission semantics.** `realtime_sendRawTransaction` and
  `eth_sendRawTransactionSync` were confirmed to *exist* on the gateway (they reject
  malformed params rather than returning "not supported"), but were not exercised;
  that needs a funded key.
- **Per-dimension gas in receipts.** There is none: `gasUsed` is compute + storage
  combined, so the split cannot be measured from outside.
- **DA size limit.** Documented as adaptive, following OP's DA footprint mechanism.
  Not in the pinned source and not observable.

---

## Re-verify

```sh
cd /Volumes/TendiesTown/EVM-intel
R=https://mainnet.megaeth.com/rpc; B=0x17b7900   # 24869120

# --- pins
git -C chains/megaeth/repos/mega-evm describe --tags            # v1.7.0
git -C chains/megaeth/repos/mega-evm rev-parse HEAD             # 30ce038c...
git -C chains/megaeth/repos/stateless-validator describe --tags # v2.0.16

# --- source: the spec ladder maps to OP Isthmus / Ethereum Prague
sed -n '/pub const fn into_op_spec/,/^    }/p' \
  chains/megaeth/repos/mega-evm/crates/mega-evm/src/evm/spec.rs
# --- source: MiniRex1 is a ROLLBACK to EQUIVALENCE
grep -n 'MiniRex1 => MegaSpecId::EQUIVALENCE' \
  chains/megaeth/repos/mega-evm/crates/mega-evm/src/block/hardfork.rs
# --- source: dual gas, 98/100, resource limits, detention
grep -n 'TX_INTRINSIC_STORAGE_GAS\|SSTORE_SET_STORAGE_GAS_BASE\|BLOCK_ENV_ACCESS_COMPUTE_GAS\|STORAGE_CALL_STIPEND\|MAX_CONTRACT_SIZE' \
  chains/megaeth/repos/mega-evm/crates/mega-evm/src/constants.rs
grep -n '98/100' chains/megaeth/repos/mega-evm/crates/mega-evm/src/evm/instructions.rs | head
# --- source: precompile overrides (Osaka modexp + 100k KZG)
grep -n 'modexp::OSAKA\|GAS_COST: u64 = 100_000' \
  chains/megaeth/repos/mega-evm/crates/mega-evm/src/evm/precompiles.rs
# --- source: the type-0x00 system transaction
sed -n '/pub fn check_if_mega_system_transaction/,/^}/p' \
  chains/megaeth/repos/mega-evm/crates/mega-evm/src/system/tx.rs
# --- source: fork schedule (note: stops at rex5Time)
jq '.config | {chainId, isthmusTime, miniRex1Time, rexTime, rex5Time, rex6Time, blockTime}' \
  chains/megaeth/repos/stateless-validator/test_data/mainnet/genesis.json

# --- live: chain id, client, and the pinned block
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' $R
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"web3_clientVersion","params":[]}' $R
# --- live: BLOCKHASH(number-1) == parentHash (finding 2)
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"0x4360019003405f5260205ff3\"},\"$B\"]}" $R
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",false]}" $R \
  | jq -r '.result.parentHash, .result.baseFeePerGas, .result.gasLimit, .result.extraData'
# --- live: microsecond clock at 0x6342..02 (finding 5)
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x6342000000000000000000000000000000000002\",\"data\":\"0xb80777ea\"},\"$B\"]}" $R
# --- live: all six system contracts carry code
for a in 1 2 3 4 5 6; do curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x634200000000000000000000000000000000000$a\",\"$B\"]}" $R \
  | jq -r '.result|length'; done
# --- live: tx type census at the pinned block
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",true]}" $R \
  | jq -r '[.result.transactions[].type]|group_by(.)|map({(.[0]):length})|add'

# --- live: mini-blocks and the 0xffff..ff receipt (findings 3, 4)
#     needs a minimal WebSocket client; subscribe to "miniBlocks" on
#     wss://mainnet.megaeth.com/ws and print each payload's mini_block_number,
#     mini_block_timestamp, signature, and receipts[0].blockHash, then immediately
#     call eth_blockNumber and eth_getTransactionReceipt over HTTP.
#     Observed 2026-08-25: mini 0x91611854 claimed enclosing block 0x17b7a7a while
#     eth_blockNumber was 0x17b7a79, receipt blockHash 0xffff..ff, and
#     eth_getTransactionReceipt returned null until ~2.5s later.

# =====================================================================
# --- SECOND SESSION (2026-08-28): ordering and execution, findings 13-15
# =====================================================================
R=https://mainnet.megaeth.com/rpc; B2=0x17fc1f9   # 25149945, ts 1787946956

# --- source (b): the sequencer executes in parallel; the EVM does not
grep -n 'JIT-compiled executor on sequencer nodes' \
  chains/megaeth/repos/stateless-validator/README.md
grep -n 'MegaETH incorporates parallel EVM' chains/megaeth/repos/mega-evm/AGENTS.md
grep -n 'reducing parallel execution conflicts without banning' \
  chains/megaeth/repos/mega-evm/AGENTS.md

# --- source (c): the commit-time re-check, and its two meanings
grep -n -A6 'Re-validate limits at commit time' \
  chains/megaeth/repos/mega-evm/crates/mega-evm/src/block/executor.rs
sed -n '/fn test_commit_time_pre_execution_check_parallel_simulation/,/^}/p' \
  chains/megaeth/repos/mega-evm/crates/mega-evm/tests/block_executor/block_limits.rs \
  | tail -30          # 3 run, 2 commit, 3rd refused, finish() -> 2 receipts
grep -n 'Transaction is \*\*skipped\*\*\|rejected permanently' \
  chains/megaeth/repos/mega-evm/crates/mega-evm/src/block/limit.rs
grep -n 'BlockReplayFailed' \
  chains/megaeth/repos/stateless-validator/crates/stateless-core/src/executor.rs
# --- source (a): the receipt is built INSIDE commit, after the re-check
sed -n '/pub fn commit_transaction_outcome/,/self.evm.db_mut().commit(state)/p' \
  chains/megaeth/repos/mega-evm/crates/mega-evm/src/block/executor.rs

# --- live (c): admission is synchronous, and the fast path is not laxer
#     (a fresh zero-balance key; nothing can be spent)
PK=$(cast wallet new --json | jq -r '.[0].private_key')
T=$(cast mktx --private-key $PK --chain 4326 --nonce 0 --gas-limit 100000 \
      --gas-price 1000000000 --priority-gas-price 1000000 --value 0 \
      0x0000000000000000000000000000000000000000 | tail -1)
for m in eth_sendRawTransaction eth_sendRawTransactionSync realtime_sendRawTransaction; do
  curl -s -X POST -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$m\",\"params\":[\"$T\"]}" $R; echo
done
#  -> all three: -32003 insufficient funds for gas * price + value: have 0 want 100000000000000
# same construction with --chain 1        -> -32000 RLP decoding failed: Common chain ID ... (a JS fragment)
# same with --gas-limit 20000000000       -> -32000 exceeds max transaction gas limit
# same with --gas-limit 50000             -> -32000 Gas limit too low. Intrinsic: 60000

# --- live (b/detention): eth_call does NOT apply gas detention
#     P = STATICCALL 0x6342..0005 remainingComputeGas(); Q = TIMESTAMP;POP;then P
P=0x6302be4d8460e01b5f526020602060045f7363420000000000000000000000000000000000055afa5060206020f3
Q=0x4250${P#0x}
for D in $P $Q; do curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"$D\",\"gas\":\"0x1C9C380\"},\"$B2\"]}" $R \
  | jq -r '.result'; done
#  -> 0x..0392ab94 = 59943828   (no block-env read)
#  -> 0x..0392ab70 = 59943792   (after TIMESTAMP)  -- 36 gas apart, NOT capped to 20,000,000
# the same two values come back for "gas":"0x186A00" (1.6M), so the compute meter is a
# fixed 60,000,000 budget independent of the request's gas field.
# A ~983,040-iteration loop (25M-30M gas) succeeds at gas 0x1C9C380 with or without the
# TIMESTAMP prefix, and fails at 0x17D7840 (25M) either way:
#   loop      0x620F00005b60019003806004575f5260205ff3
#   TS+loop   0x4250620F00005b60019003806006575f5260205ff3

# --- live (a): mini-block order == sealed order, over 24 consecutive blocks
#     Needs a minimal WebSocket client (stdlib sockets + ssl are enough; note the
#     endpoint 403s a default python User-Agent, so set one). Subscribe to
#     eth_subscribe("miniBlocks") for ~25 s, bucket payloads by `block_number`, sort
#     each bucket by `index`, concatenate (receipts[i].transactionIndex, tx[i].hash),
#     and compare with eth_getBlockByNumber(bn, true) for every block except the first
#     and last of the capture. Then diff each streamed receipt against
#     eth_getBlockReceipts.
#     Observed 2026-08-28 over blocks 25048453..25048478:
#       24 blocks fully observed | 2384 mini-blocks (99 or 100 per EVM block, 2059 empty)
#       577 transactions | streamed order == sealed order in 24/24
#       receipt field diffs: {blockHash: 577, logs: 262, l1Fee: 244}, all else identical
#       streamed receipt blockHash = 0xffff..ff; streamed TRANSACTION blockHash = null
#     A second 13-block capture, comparing l1* fields and the first log of each receipt:
#       l1Fee differed in 131 receipts; streamed value was the CONSTANT 0x2db0cccd
#       (766,561,485 wei) every time, final values 1533118371 / 1597241240 / 1610065813.
#       l1GasPrice, l1GasUsed, l1BaseFeeScalar, l1BlobBaseFee, gasUsed,
#       cumulativeGasUsed and effectiveGasPrice all matched; the only differing log
#       field was blockHash (149).

# --- schema
tools/.venv/bin/python tools/verify.py 2>&1 | sed -n '/^megaeth/,/^$/p'
```
