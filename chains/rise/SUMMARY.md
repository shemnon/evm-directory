# RISE — what this row teaches

Pinned: `risechain/rise-node` **v0.6.0** (`27cd88b1`, released 2026-06-29), with
`risechain/risechain` (`0f53132e`, **main, untagged**) and `risechain/pevm`
(`e94b0e3d`, **main, untagged**) as companions.
Live probe: `https://rpc.risechain.com` / `wss://rpc.risechain.com/ws`, chain id
**4153**, block **20239360** (timestamp 1787845119, 2026-08-27 15:38:39 UTC).
Baseline fork **prague**, reached through OP **Jovian**. Mainnet has been live since
2026-01-05 and produces a 1-second, 1.5-gigagas block.

**Evidence path taken: source — with a caveat larger than the pin.** The gate was
tested by cloning, not estimated, and the answer splits in a way this dataset has not
seen before. `rise-node` is a genuine released tag and the *only* tagged repo in the
org — but it is a **deployment** repo: a docker-compose that pins two prebuilt images
by digest (`rise-exec/replica:sha-bb10092`, `rise-op-node:sha-b1f242d`), plus the
canonical mainnet `genesis.json` and `rollup.json`. It is real, verifiable evidence
for chain *parameters* and for the deployment topology, and no evidence whatsoever
for the state transition. The execution client is **closed**: the live RPC identifies
itself as `rise-replica/sha-80d9780/linux`, and no repo under `risechain` builds it.
So `evidence: source` here means "a real released tag is pinned and every `src:` below
resolves inside it", **not** "the state transition is auditable". It is not. Every
claim about the EVM, about shreds, and about block production on this row is
`src_live:`.

---

## 1. The parallel-EVM claim is refuted as shipped

RISE is widely described as running `pevm`, a Block-STM–lineage parallel EVM. The
repo is public and the design is real — but **it is not what runs the network at the
pinned commit, and it says so on its own front page**: *"This repository is a work in
progress and is not production ready"*. Its TODO list still contains "Implement an
inline parallel-optimal EVM to replace `revm`", "Committing and broadcasting shreds",
and — decisively — **"Integration into RISE nodes"**. There is no tag, no release, no
version. Whatever `rise-exec` does inside its container, the published pevm is not it.

The second half of the answer matters as much: **even when it ships, the parallelism
is by design not consensus-visible.** pevm's own design section states that
"blockchain execution must be deterministic... parallel execution must arrive at the
same outcome as sequential execution. Having race conditions that affect execution
results would break consensus." Conflicts are detected against a multi-version memory
and resolved by **re-execution inside one node**. Two implementations, one sequential
and one parallel, cannot disagree. That places RISE with Sei and Monad rather than
anywhere new — the interesting parallelism on this chain is not in the executor, it is
in what the executor is allowed to *publish* while it works.

The other open Rust repo is a similar shape of disappointment: `risechain/risechain`
is billed as "the monorepo of RISE Chain" and contains **one crate, 353 lines**
(`crates/primitives`: the RPC and IPC wire types). Its README says "We're in a gradual
process of open-sourcing the whole stack." Those 353 lines turn out to be
disproportionately valuable — see finding 4 — but they are not a client.

## 2. A shred is one transaction, and it has no identity of its own

RISE's sub-block unit is finer than anything else in this dataset and structurally
*simpler* than MegaETH's mini-block. The payload is

```
{ blockNumber, shredIdx, blockTimestamp, startingLogIndex, transactions[], stateChanges? }
```

and **every coordinate in it is a block coordinate.** `blockNumber` is the enclosing
L2 block. `startingLogIndex` is the log index *within that block*. And `shredIdx` was
measured to be the transaction's index in the block: block 20277530 was streamed as 98
shreds with `shredIdx` 0..97 and sealed with exactly 98 transactions, and the receipts
for shreds 0, 1, 2 carried `transactionIndex` 0, 1, 2. Every shred observed across four
capture runs carried **exactly one transaction**.

So there is no second height space to reconcile. MegaETH's `mini_block_number` was
**2,439,447,937** at EVM block 24,869,417 — a disjoint, monotone, global sequence that
no standard RPC exposes. RISE's counter **resets to 0 every second** and is just the
transaction index. Between 55 and 478 shreds per block were observed, 2–18 ms apart.

A shred is also **already-executed state, not a commitment to order**: it carries a
receipt with `status`, `cumulativeGasUsed` and logs, and optionally the post-state diff
(`stateChanges`: per address, `{nonce, balance, storage{slot->value}, newCode}`). The
sequencer never publishes an order it has not yet run.

## 3. The receipt arrives over **plain HTTP**, for a block that does not exist, with `blockHash: 0x00…00`

This is the finding. MegaETH's `0xffff…ff` sentinel only reaches a client that opts
into the WebSocket mini-block stream; over HTTP MegaETH returns `null` until the block
exists. **RISE hands the preconfirmed receipt to an unmodified HTTP client.** Racing
the shred stream against the HTTP endpoint at block 20239693:

- `eth_blockNumber` returned **20239692** — the block in the receipt did not exist;
- `eth_getTransactionReceipt` returned a fully populated receipt with
  `blockNumber: 0x134d51a` (20239693), `status: 0x1`, real `gasUsed`, real
  `effectiveGasPrice`, real `transactionIndex`, and
  `blockHash: 0x0000000000000000000000000000000000000000000000000000000000000000`;
- at the same instant `eth_getTransactionByHash` for the **same hash** returned
  `blockHash: null, blockNumber: null`.

Reproduced at block 20277529. Three consequences: every "wait for a non-null receipt"
loop fires a block early; the zero hash is a plausible-looking `bytes32` that indexers
will store, key on, and never match; and the receipt and the transaction contradict
each other in the same instant without either being an error.

The published wire type intends `null` here —
`RiseRpcTransactionReceipt.block_hash: Option<BlockHash>`, commented *"None for pending
/ shred receipts"*. **The live network and the published source disagree about which
sentinel is used**, and the live one is the more dangerous of the two.

## 4. The same node uses two different sentinels for the same missing hash

A log delivered by `eth_subscribe(["logs", {}])` for a not-yet-sealed transaction
carries `blockHash: null` with a real `blockNumber`, `logIndex` and `transactionIndex`.
The *same log*, read back inside `eth_getTransactionReceipt` at the same moment,
carries `blockHash: 0x00…00`. A consumer that special-cases one still breaks on the
other.

## 5. `eth_subscribe(["logs"])` was not extended — it was **replaced**

RISE does not add a parallel log channel. The chain's own client library states that
"the standard `["logs"]` subscription is **patched to broadcast events from shreds
instead of blocks**", and it was confirmed live. So a stock viem/ethers/web3
application, written for Ethereum and deployed unmodified against RISE, **is already
consuming preconfirmations**: it receives events for transactions whose block does not
exist, with `blockHash: null` and `removed: false`, and there is no flag to turn it
off. Nothing in the subscription request distinguishes the two behaviours.

This is the widest blast radius on the row, because it requires the integrator to have
done nothing at all. The shred stream proper (`eth_subscribe(["shreds", <bool>])`) at
least announces itself — and it is the *only* way to see a shred: there is no
`rise_` namespace, no `eth_getShredByNumber`, no archive access, and no way to ask for
one you missed. `["shred"]` (singular) is rejected outright.

**And a shred is not signed.** No signature, no sequencer key, no hash of its own.
MegaETH signs each mini-block with secp256k1 over `keccak256(rlp(header))` precisely so
that a contradicted preconfirmation is *provable* by a third party. RISE's
preconfirmation is the sequencer's unattributable word over a socket. Which matters,
because of finding 6.

## 6. A shred *is* routinely contradicted — on the one transaction that writes L1 state

Collecting every shred for 24 consecutive complete blocks and comparing hash-by-hash
against the sealed blocks: the transaction lists have the **same length** and match
exactly at every position **except 0**, and at position 0 the streamed transaction is
the type-`0x7e` L1-attributes deposit that the canonical chain placed in block **N−1**.
22 of 24 blocks showed it; in every mismatching case the streamed deposit hash for
block N equals the sealed deposit hash for block N−1 (ten consecutive blocks checked
individually). Every *user* transaction — positions 1..n−1 — matched in hash **and**
order, so shred ordering is otherwise faithful.

A consumer replaying `stateChanges` to build state therefore applies the wrong
`L1Block` update — stale L1 block number, timestamp, basefee, batcherHash — one block
late, forever, at 1 Hz. Whether this is a labelling bug in the broadcaster or a real
mid-flight replacement of the payload attributes cannot be told from outside, and with
no signature on the shred there is nothing to escalate with.

## 7. There is no ordered-but-invalid state, because admission is synchronous

RISE lands at the **opposite pole** from the three rows that converged before it.
Conflux (`Skipped`), IOTA EVM (rejected at the ISC request layer) and Artela (the
indexing event is emitted by the last ante decorator, so an ante failure leaves no
index entry) all order a transaction and then **erase** it, leaving a null receipt
indistinguishable from never having submitted. Taraxa is the counter-pole: included,
charged the full gas limit, `status: 0`. Autonomys poisons the whole bundle and slashes
the operator.

RISE never orders an invalid transaction at all. Because a shred is published only
*after* execution, and admission is synchronous at the RPC boundary, the
ordered-but-unevaluated window does not exist. Tested live with freshly generated,
correctly signed transactions from an empty account:

| condition | answer | receipt |
|---|---|---|
| insufficient balance | `-32003 insufficient funds for gas * price + value: have 0 want 1000009876132000` | null forever |
| gas price below base fee | `-32000 max fee per gas less than block base fee` | null forever |
| wrong chain id | `-32000 invalid chain ID` | null forever |

— and `eth_sendRawTransactionSync` returns **the identical errors** as
`eth_sendRawTransaction`, so the fast path is not a laxer path. A transaction that *is*
admitted and then reverts gets the ordinary treatment: 103 of 2,452 sampled shred
receipts carried `status: 0x0` with gas charged.

So RISE's answer to the central question is the *mainnet* answer, arrived at by a
different route — and the interesting risk moved somewhere else entirely: not "can an
ordered transaction be invalidated" but "can a published *result* be contradicted"
(finding 6: yes).

## 8. MegaETH and RISE spent their divergence budget in opposite places

Two OP Stack L2s, both chasing single-digit-millisecond preconfirmation, both with a
closed sequencer, both streaming sub-block units over WebSocket. Everything else is
inverted.

|  | MegaETH | RISE |
|---|---|---|
| EVM | rewritten: dual gas meter, 98/100 forwarding, 512 KiB code limit, state-layout-priced `SSTORE` | **stock**, as far as every probe reaches |
| own forks | eleven (MiniRex…Rex6), including a *rollback* | **zero** |
| sub-block unit | mini-block: global height space (2.4×10⁹), many txs, mostly empty | shred: one tx, `shredIdx` = tx index, resets each block |
| signed? | yes, secp256k1 over the header | **no** |
| preconf over plain HTTP | no — `null` until sealed | **yes**, with `blockHash: 0x00…00` |
| standard `logs` subscription | unchanged | **repurposed to shreds** |
| receipt shape | OP-standard | **L1 fee fields removed** |
| DA | EigenDA | AltDA server (`da.risechain.com`) |

MegaETH rewrote the EVM and kept the RPC recognisable. RISE kept the EVM and rewrote
the RPC. A contract auditor has almost nothing to learn from the RISE row; a tooling
maintainer has more to learn from it than from any other OP Stack descendant here.

## 9. The receipt has no OP L1 fee fields at all — marked `severity: high`

Every other OP Stack chain returns `l1Fee`, `l1GasPrice`, `l1GasUsed`, `l1FeeScalar`
(and from Isthmus `operatorFeeScalar`/`operatorFeeConstant`) on every receipt. RISE
returns **none** of them. The key set at the pinned block is exactly `blockHash,
blockNumber, contractAddress, cumulativeGasUsed, effectiveGasPrice, from, gasUsed,
logs, logsBloom, status, to, transactionHash, transactionIndex, type` — plus
`depositNonce`/`depositReceiptVersion` on deposits. The published wire type says why:
`RiseRpcTransactionReceipt` is documented as *"RISE transaction receipt without OP L1
fee fields (always zero on RISE)"*.

This fails silently in the direction accounting code does not check: an OP-aware
indexer computing `gasUsed * effectiveGasPrice + l1Fee` reads `undefined`/`nil` for
the last term and gets NaN, zero, or a throw depending on the language — never a signal
that the field was never there.

The reason it is zero is structural, not a scalar set to 0: **DA is an AltDA server,
not Ethereum blobs.** `rollup.json` carries `alt_da` with
`da_commitment_type: GenericCommitment`, and the node distribution points op-node at
`--altda.da-server=https://da.risechain.com`. The `da_challenge_contract_address` is
the zero address and both windows are 1, so the on-chain challenge mechanism is not
configured — availability rests on one HTTPS endpoint the chain operates, with the
commitment batched to L1 at `0x00bb2bf8…cdc9d4a`.

## 10. Everything else in the derivation pipeline is stock — a clean negative

The L1-attributes deposit calls `0x4200…15` with selector **`0x3db6be2b`**, which is
op-reth's `L1_BLOCK_JOVIAN_SELECTOR` verbatim. `0x4200…11` is the beneficiary of every
header. `withdrawalsRoot` (Isthmus) and the 17-byte Jovian `extraData` are both present
and well-formed. Every OP fork Regolith→Jovian is at time 0, RISE has scheduled no fork
of its own, and `karst_time` is absent. `lineage.sync_point` is therefore **not needed**
— unusual for this dataset: RISE sits at exactly the fork level the `op-stack` row's
pinned client does, so it inherits that row wholesale and correctly, where MegaETH
needs a sync_point to avoid being credited with Jovian it does not have.

## 11. The fee market is a constant with a 1559-shaped header

Live `extraData` decodes to denominator **1**, elasticity **1**, minBaseFee **415,300
wei** — which is exactly `chain_id × 100`. Elasticity 1 means the target equals the
gas limit, so with blocks running at 24–44% of a **1,500,000,000** gas limit the base
fee always wants to fall and Jovian's floor catches it: six consecutive blocks all
carry `baseFeePerGas: 0x65644`. Genesis shipped the OP defaults (250 / 6 / 0) and a
250,000,000 gas limit, so both the 1559 parameters and the gas limit were changed after
launch through L1 `SystemConfig` — parameter changes invisible to anyone reading the
repo, and the closest thing this chain has to a fork schedule.

## 12. A bincode Unix-socket side channel, for co-located parties only

The 353 published lines also define an IPC protocol: *"RISE nodes can expose a
Unix-socket for co-located services to read chain state and submit transactions rapidly
without paying JSON and network costs"* — `GetBaseFee`, `GetPendingNonce(address)`,
`SubmitRawTx(bytes)` returning a compact receipt, length-delimited bincode rather than
JSON-RPC. Recorded because it means the fastest path onto this chain is one only a
co-located party can take, a latency asymmetry the public RPC does not reveal.

---

## Not established here

With no execution-client source, the list of things that cannot be enumerated is
itself part of the row's shape.

- **Gas schedules — the biggest gap.** No precompile repricing, no opcode repricing,
  no intrinsic-cost change could be measured. `eth_estimateGas` binary-searches and
  adds a buffer, so it cannot resolve a repricing, and with no source and no funded key
  there is no other instrument. Recorded as `precompiles.gas_schedule: unrecorded`
  rather than asserted inherited. Settling it needs either the client source or a
  funded key plus differential gas accounting against a reference node.
- **EIP-170 / EIP-3860 limits.** Whether the 24,576-byte code limit is raised is
  `unrecorded`. MegaETH raises it to 512 KiB, so the question is live for a chain
  chasing gigagas. A single funded deploy settles it.
- **What `rise-exec` actually is.** It is invoked with reth's CLI grammar
  (`node --chain --datadir --txpool.pending_max_count …`), which makes a reth
  derivative overwhelmingly likely, but `risechain/reth` is an untagged fork whose
  relationship to the shipped digest is unverifiable. Not claimed.
- **Whether the deposit-shred mismatch (finding 6) is a broadcaster labelling bug or a
  real payload-attributes replacement.** Both produce the same observation from
  outside. The client source would settle it in one read.
- **Whether a *user* transaction's shred can ever be contradicted.** 24 blocks is
  evidence of practice, not a bound. Nothing observed contradicted a user transaction;
  nothing observed rules it out either, and with no signature there is no protocol-level
  guarantee to appeal to.
- **`eth_sendRawTransactionSync` with a valid, funded transaction.** Confirmed to
  exist and to apply the same validity checks; never exercised end-to-end.
- **Shred delivery guarantees.** Whether the stream is lossless, whether shreds can
  arrive out of `shredIdx` order, and what happens across a reconnect. The captures were
  contiguous, but the API offers no cursor, no resume and no gap signal, so a consumer
  cannot detect a loss.
- **EIP-7702 in practice.** Type `0x04` is supported by Prague and has an explicit
  branch in the shred formatter, but none appeared in the sampled blocks.
- **Fault proofs.** A `protocol_versions_address` and a dispute-game deployment are
  configured, but whether the fault-proof system is active for an AltDA chain with an
  unconfigured challenge contract was not investigated.

---

## Re-verify

```sh
cd /Volumes/TendiesTown/EVM-intel
R=https://rpc.risechain.com; B=0x134d400          # 20239360

# --- pins (rise-node is the only TAGGED repo in the org)
git -C chains/rise/repos/rise-node  rev-parse HEAD   # 27cd88b171000a08a92d2c65358a2d3b84f423d8
git -C chains/rise/repos/rise-node  describe --tags  # v0.6.0
git -C chains/rise/repos/risechain  rev-parse HEAD   # 0f53132e...  (main, UNTAGGED)
git -C chains/rise/repos/pevm       rev-parse HEAD   # e94b0e3d...  (main, UNTAGGED)
git ls-remote --tags https://github.com/risechain/pevm       # empty
git ls-remote --tags https://github.com/risechain/risechain  # empty
git ls-remote --tags https://github.com/risechain/reth       # empty

# --- source: the client is two container digests, not code (finding 1)
grep -n 'image:\|altda.da-server' chains/rise/repos/rise-node/docker-compose.yml
# --- source: chain parameters
python3 -m json.tool chains/rise/repos/rise-node/chain/mainnet/rollup.json \
  | grep -E 'l2_chain_id|block_time|jovian_time|karst|batch_inbox|da_commitment_type|eip1559'
python3 -c "import json;print(json.load(open('chains/rise/repos/rise-node/chain/mainnet/genesis.json'))['config'])"
# --- source: pevm is NOT production (finding 1)
grep -n 'not production ready\|Integration into RISE nodes\|Committing and broadcasting shreds' \
  chains/rise/repos/pevm/README.md
grep -n 'must arrive at the same outcome as sequential' chains/rise/repos/pevm/README.md
# --- source: the receipt wire type (findings 3, 9) and the IPC channel (finding 12)
grep -n 'without OP L1 fee fields\|None for pending / shred receipts\|block_hash' \
  chains/rise/repos/risechain/crates/primitives/src/rpc.rs
grep -n 'RiseIpcRequest' -A 10 chains/rise/repos/risechain/crates/primitives/src/ipc.rs

# --- live: identity
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' $R          # 0x1039
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"web3_clientVersion","params":[]}' $R   # rise-replica/sha-80d9780/linux

# --- live: header, fee floor, gas limit (finding 11)
for i in 0 1 2 3 4 5; do n=$(python3 -c "print(hex(0x134d400+$i))"); curl -s -X POST \
  -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$n\",false]}" $R \
  | python3 -c "import json,sys;d=json.load(sys.stdin)['result'];e=d['extraData'];print(d['number'],d['baseFeePerGas'],int(d['gasUsed'],16),int(d['gasLimit'],16),'v%s denom %d elas %d minBaseFee %d'%(e[2:4],int(e[4:12],16),int(e[12:20],16),int(e[20:36],16)))"; done
# 0x134d400 0x65644 654381583 1500000000 v01 denom 1 elas 1 minBaseFee 415300   (and x5 more)

# --- live: baseline fork markers (Prague, not Osaka)
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x0000F90827F1C53a10cb7A02335B175320002935\",\"$B\"]}" $R   # 84 bytes
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02\",\"$B\"]}" $R   # has code
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"0x60011e5f5260205ff3\"},\"$B\"]}" $R
#   -> {"error":{"code":-32003,"message":"EVM error: NotActivated"}}   (CLZ absent => not Osaka)
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"0x$(printf '00%.0s' $(seq 1 160))\"},\"$B\"]}" $R
#   -> "0x"   (P256VERIFY, RIP-7212 empty-output-on-failure)

# --- live: BLOCKHASH is honest — shreds do not consume block numbers (finding 2)
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"0x4360019003405f5260205ff3\"},\"$B\"]}" $R
#   -> 0x381b2539b4e614c13c5c787fa2eeacd62e038e5450030295cdcb17f112b2dfac == parentHash of 20239360

# --- live: the receipt has NO L1 fee fields (finding 9)
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockReceipts\",\"params\":[\"$B\"]}" $R \
  | python3 -c "import json,sys;print(sorted(json.load(sys.stdin)['result'][1].keys()))"
#   -> ['blockHash','blockNumber','contractAddress','cumulativeGasUsed','effectiveGasPrice',
#       'from','gasUsed','logs','logsBloom','status','to','transactionHash','transactionIndex','type']

# --- live: stock Jovian L1 attributes selector, tx-type census (finding 10)
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",true]}" $R \
  | python3 -c "import json,sys;from collections import Counter;t=json.load(sys.stdin)['result']['transactions'];print(t[0]['type'],t[0]['to'],t[0]['input'][:10]);print(Counter(x['type'] for x in t))"
#   -> 0x7e 0x4200000000000000000000000000000000000015 0x3db6be2b
#      Counter({'0x0': 379, '0x2': 2, '0x7e': 1})

# --- live: custom RPC surface (finding 5)
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_sendRawTransactionSync","params":["0xdeadbeef"]}' $R
#   -> -32602 "failed to decode signed transaction"   (method EXISTS)
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"rise_getShred","params":[]}' $R
#   -> -32601 "Method not found"                      (no custom namespace)

# --- live: shreds, the preconfirmed receipt, the two sentinels, the stale deposit
#           (findings 2, 3, 4, 6) — needs a minimal WebSocket client.
#     Connect to wss://rpc.risechain.com/ws  (the bare host with NO /ws path returns
#     HTTP 403 on the upgrade), then:
#       eth_subscribe ["shreds", false]   -> shred stream
#       eth_subscribe ["shreds", true]    -> shred stream WITH stateChanges
#       eth_subscribe ["shred"]           -> -32602 "data did not match any variant of
#                                            untagged enum AllSubscriptionKind"
#       eth_subscribe ["logs", {}]        -> SHRED logs, blockHash NULL
#     and the instant a shred arrives, call over HTTP:
#       eth_blockNumber   and   eth_getTransactionReceipt(<the shred's tx hash>)
#
#   Observed 2026-08-27:
#     shred blk=20239693 idx=88  ->  eth_blockNumber = 20239692   (block does not exist)
#         eth_getTransactionReceipt -> blockNumber 0x134d51a, blockHash 0x00..00,
#                                      status 0x1, transactionIndex 0x58
#         eth_getTransactionByHash  -> blockHash null, blockNumber null
#     eth_subscribe ["logs",{}] @ 20277529 -> blockHash null, blockNumber 0x1356919,
#                                      logIndex 0x2be..0x2c1, removed false
#     block 20277530: 98 shreds, shredIdx 0..97, ntx=1 each; sealed block has 98 txs;
#                     shredIdx 0/1/2 -> receipt transactionIndex 0/1/2
#     24 consecutive blocks: 22 mismatch the sealed block at position 0 ONLY, and the
#                     streamed shredIdx-0 deposit for block N is the sealed deposit of
#                     block N-1 (e.g. streamed[0] of 20277749 == sealed[0] of 20277748)
#     shred receipt status census over ~14 s: 2349 status 0x1, 103 status 0x0

# --- live: admission is synchronous, nothing is ordered-then-erased (finding 7)
#     sign a legacy tx from a FRESH EMPTY account (chainId 4153) and submit it:
#       insufficient balance -> -32003 "insufficient funds for gas * price + value: have 0 want ..."
#       gasPrice 1 wei       -> -32000 "max fee per gas less than block base fee"
#       chainId 1            -> -32000 "invalid chain ID"
#     eth_getTransactionReceipt for all three -> null, permanently.
#     eth_sendRawTransactionSync returns the IDENTICAL errors as eth_sendRawTransaction.

# --- schema
tools/.venv/bin/python -c "import yaml;yaml.safe_load(open('chains/rise/chain.yaml'))"
tools/.venv/bin/python tools/verify.py 2>&1 | sed -n '/^rise/,/^$/p'
```
