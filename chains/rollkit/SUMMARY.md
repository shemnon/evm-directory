# Rollkit / Evolve — what this row teaches

**Pinned evidence.**
`evstack/ev-node` **v1.2.3**, commit `d76e0dfcb0ffa3384d875fa2538eeb9a5321b335`
(Go; sequencing, DA, the Engine-API driver) and its companion
`evstack/ev-reth` **v0.5.2**, commit `7f3e25fe756c2cc2e4e56a423a11d2e8fe299fe0`
(Rust; the actual EVM). `github.com/rollkit/rollkit` 301-redirects to
`github.com/evstack/ev-node` — the project renamed to **Evolve** and the org to
**evstack**. `rollkit/go-execution-evm` likewise redirects; its code is now the
in-tree module `execution/evm`.

Live probe: **Eden mainnet**, `https://rpc.eden.gateway.fm/`, `eth_chainId`
`0x2ca` (714), `web3_clientVersion` `reth/v2.2.0-88505c7/x86_64-unknown-linux-gnu`,
pinned at **block 182440651** (2026-08-27). Eden is operated by `celestiaorg`,
gas token TIA, 100 ms blocks, genesis 2025-12-11. It is the **only** live Evolve
EVM chain that could be identified, and it was found by searching public genesis
files for the ev-reth-specific chainspec keys `mintAdmin` and `baseFeeSink` — not
from any evstack ecosystem page, which does not exist.

Baseline fork: **prague** — by chainspec timestamp, in both ev-node's example
genesis and Eden's. Evidence path: `source` for everything the framework fixes,
`src_live` for everything Eden's chainspec chooses, because on a `template` row
those are different kinds of claim.

Role: **`template`**, not `stack`. Every EVM-visible divergence below is a
chainspec or node-config value with its own activation height, so no descendant
is describable by pointing at this row — SCHEMA.md's exact test.

**Is the framework row warranted?** Yes, narrowly. The three rows CANDIDATES.md
rejected (Frontier, Polygon CDK, BeaconKit) failed because descendants forked the
code and shared nothing runnable. Rollkit is the opposite failure mode: the
descendants *would* share a real released binary pair, published as
`ghcr.io/evstack/ev-reth` — there is simply almost nobody downstream yet. One
confirmed instance. The row is a template with a very short descendant list, and
that is stated in `deployments` rather than papered over.

---

## 1. The sequencer orders; Celestia only records the order it already chose

The single most-muddled claim about sovereign rollups, settled from source.
ev-node's sequencer drains its own queue, hands the ordered list to the EVM over
the Engine API, receives a finished block, signs a header, and *then* posts —
in two pieces, to two different Celestia namespaces: a signed header to the
header namespace and the block data to the data namespace
(`block/internal/submitting/da_submitter.go`, `SubmitHeaders` / `SubmitData`).
What reaches Celestia is a finished, signed, already-executed block. Celestia's
own ordering of those blobs is not load-bearing: the rollup's order is carried
by the signed header chain *inside* the blobs, and headers and data may land in
different Celestia blocks and are paired by hash on the way back.

The exception is real and is the interesting half — see finding 3.

## 2. A validly ordered but invalid transaction is silently erased

`EvolvePayloadBuilder::build_payload` (`crates/node/src/builder.rs`) loops the
attribute-supplied transaction list and calls `execute_transaction`. The error
arm is a `tracing::warn!` and nothing else:

```rust
Err(err) => {
    tracing::warn!(error = %err, tx_hash = %tx.tx_hash(), "transaction execution failed");
}
```

The transaction is not appended to the block. No receipt, no `status: 0`, no gas
charged, no trace — indistinguishable from never having been submitted. That
covers nonce already consumed, insufficient balance, gas price below the base
fee, and gas limit over the block's remainder. A *revert* is different and
ordinary: it returns `Ok`, is included, and gets a status-0 receipt.

This joins the "ordered then erased" class (Conflux, IOTA EVM, Artela) and sits
opposite Taraxa. The mechanism is new, though: on those chains erasure falls out
of a consensus design, whereas here the sequencer's ordering is only a
*suggestion*. The EVM is handed a list and returns a block, and the difference
between the two is discarded without being recorded anywhere.

## 3. Anyone can write to the forced-inclusion namespace, and there *is* a rule

Forced inclusion (optional, per deployment) makes Celestia the ordering
authority for one class of transactions: every non-empty blob in the rollup's
forced-inclusion namespace across a DA **epoch** is collected in DA-height
order, then blob order within a height
(`block/internal/da/forced_inclusion_retriever.go:RetrieveForcedIncludedTxs`).
Eden's ev-node genesis sets `da_epoch_forced_inclusion: 100` — roughly ten
minutes of Celestia blocks per epoch. In `--node.based_sequencer` mode this is
the *only* transaction source and the rollup is a genuinely based rollup.

Because anyone can pay for a blob in any namespace, the rollup must have a rule
for ordered bytes that are not a transaction, and it does — fixed by the
framework, not left to policy. `FilterTxs` (`execution/evm/execution.go`)
RLP-decodes each force-included blob and returns `FilterRemove` on failure; the
log line is literally *"filtering out invalid transaction (gibberish)"*. Same
verdict for a transaction whose own gas limit exceeds the block gas limit or
whose size exceeds the blob limit. Removed transactions are consumed from the
checkpoint and never retried. Valid ones that merely do not fit get
`FilterPostpone` and are retried at the next height — so "dropped" and
"postponed" are distinct outcomes with distinct retry semantics. Garbage cannot
halt the chain and cannot frame the sequencer.

**The gap, which is a consensus-split risk:** `FilterTxs` is a method on the
*execution client* (`core/execution/execution.go:FilterStatus`), not a protocol
rule. ev-node calls it both when building blocks and when auditing the sequencer
for censorship, and trusts the answer. Two execution clients that disagreed
about whether a blob decodes would disagree about whether the sequencer censored
it, and therefore about whether to halt — a liveness split driven by an EL's
decoder. Latent today, because there is one EVM execution client.

## 4. The `finalized` tag is a hard-coded height lag, not DA finality

`severity: high`, and the sharpest thing in the row. On every block it produces,
the EVM adapter calls `setFinalWithHeight`, which sets

```
safe      = head - SafeBlockLag       (2)
finalized = head - FinalizedBlockLag  (3)
```

by pure arithmetic, with no reference to Celestia. The source comment is candid:
*"This is a temporary mock value until proper DA-based finalization is wired
up."* A DA-driven `SetFinal` does exist and is called from the submitter, but it
writes the same field and is overwritten by the next block's height-lag update —
which on Eden happens ten times a second.

Observed at the probe: `finalized` was **7 blocks** behind head and `safe` **2**
— 0.7 s and 0.2 s, on a chain whose DA layer produces a block every ~6 s. An
exchange, bridge or indexer that waits for the `finalized` tag on a Rollkit chain
is waiting for almost nothing: it is confirming a block the sequencer may still
be the only holder of. The honest finality signal is ev-node's own RPC on port
7331, which the public gateway does not expose.

## 5. `PREVRANDAO` is the block number

```go
func (c *EngineClient) derivePrevRandao(blockHeight uint64) common.Hash {
	return common.BigToHash(new(big.Int).SetUint64(blockHeight))
}
```

Confirmed live at six consecutive Eden blocks: `mixHash` runs
`0x…0adfd13d` … `0x…0adfd142` for heights 182440253–182440258. It is nonzero, it
changes every block, and it passes any smoke test — while being a counter anyone
can predict arbitrarily far ahead.

It fails together with the other two entropy sources. `parentBeaconBlockRoot` is
hard-coded to the zero hash on both sides (ev-node's payload attributes and
ev-reth's payload builder), and the EIP-4788 contract is not deployed at all.
`block.timestamp` repeats. **A Rollkit chain has no randomness source**, only
`BLOCKHASH` over ~25 seconds of history chosen by a single sequencer.

## 6. `block.timestamp` is non-decreasing, not increasing

ev-node passes seconds to the Engine API while producing blocks far faster than
1 Hz, so ev-reth ships a *custom consensus rule* to accept it
(`crates/evolve/src/consensus.rs:EvolveConsensus`): `header.timestamp >=
parent.timestamp` instead of `>`. On Eden, ten consecutive blocks share one
timestamp — verified: 182440253/254/255 all carry `0x6a91e1ab`, and 256/257/258
all carry `0x6a91e1ac`. Any contract using `block.timestamp` as a unique key, a
monotonic clock, a rate limiter or a per-block nonce is wrong here, silently.

## 7. Prague is claimed by timestamp and its system contracts are missing

`pragueTime: 0` and `cancunTime: 0`, yet `eth_getCode` at the beacon-roots
(`0x000F3df6…Beac02`), history-storage (`0x0000F908…002935`), withdrawal-request
(`…007002`) and consolidation-request (`…007251`) addresses all return `0x`.
Neither Eden's genesis alloc nor ev-node's own example genesis contains them.
The consequence with teeth: **`BLOCKHASH` keeps its 256-block window**, which at
100 ms blocks is *twenty-five seconds* of history rather than mainnet's ~54
minutes, and EIP-2935's extension is unavailable to close the gap.

This generalises past Rollkit: a chain can declare a fork by chainspec timestamp
while omitting the genesis state the fork assumes, and the documented genesis
here omits it by default.

## 8. The base fee is credited, not burned — verified to the wei

`crates/ev-revm/src/base_fee.rs:BaseFeeRedirect` intercepts `reward_beneficiary`
and credits `base_fee_per_gas * gas_used` to a chainspec-configured sink. At Eden
block 182440651: `gasUsed` 127872, `baseFeePerGas` 1480, and the sink's balance
rose by exactly **189 250 560** = 1480 × 127872. The sink is also the block
`miner` (ev-reth defaults `suggestedFeeRecipient` to it), so `COINBASE` is a
constant contract address and both halves of the fee land in the same place.

The EIP-1559 *update rule* is configurable too: Eden runs
`baseFeeMaxChangeDenominator: 5000` and `baseFeeElasticityMultiplier: 10`
against mainnet's 8 and 2 — a base fee that moves roughly 625× more slowly per
block.

## 9. Transaction type `0x76`: atomic batches and a second signer

ev-reth adds an EIP-2718 type `0x76` that replaces `to`/`value`/`input` with a
`Vec<Call>` executed atomically (any revert rolls the whole batch back; only the
first call may be a creation), plus an optional `fee_payer_signature`. Two
parties sign two different digests: the executor over domain byte `0x76`, the
sponsor over domain byte `0x78` with the executor's address bound in so the
sponsor's signature cannot be replayed under a different executor. The sponsor
pays `max_fee_per_gas * gas_limit` and **receives the gas refund**. RPC exposes an
extra `feePayer` field on transactions *and receipts* that no standard decoder
knows about.

This is the second lineage in the dataset with protocol-level fee delegation and
two signers on one transaction, arrived at independently of Kaia and encoded
completely differently. It is also the counter-example to Plasma, whose
"gasless" path turned out to be ERC-4337: this one is consensus.

## 10. Two precompiles that are not quite precompiles

`0x…F100` mints and burns native token directly into account balances, callable
by a chainspec `mintAdmin` and by anyone that admin allowlists on the precompile
itself. **No event, no log** — total native supply on a Rollkit chain is neither
conserved nor auditable from logs. Active on Eden from genesis, with the admin
set to an upgradeable proxy at `0x…Ad00`.

`0x…F101` stores the ev-node signer that must sign the *next* block — execution
state selecting consensus leadership, so an EVM transaction rotates the
sequencer (ADR-023). Not active on Eden. Its sharp edge is documented in
ev-reth's own README: *before* the activation height a call to `0xF101` is an
ordinary call to an empty account, which **succeeds and writes nothing** — a
rotation sent one block early gets a status-1 receipt and has no effect.

Both install a **one-byte `0xFE` bytecode** at their address so `EXTCODESIZE` is
1 and Solidity's extcode guard on a typed external call passes. Confirmed live:
`eth_getCode(0x…F100)` → `0xfe`, while `0x01`, `0x04`, `0x0a`, `0x0b`, `0x11` all
return `0x`. They satisfy neither of SCHEMA.md's category definitions cleanly —
native code at a fixed address, with code in state.

## 11. Censorship enforcement is a halt and a social restart

If the sequencer omits a force-included transaction past its grace window (base
1 epoch, extended up to 4 when DA blocks run full), DA-following full nodes tag
it malicious and stop, with the message: *"sequencer malicious. Restart the node
with `--node.aggregator --node.based_sequencer` or keep the chain halted"*. No
slashing, no proof, no automatic fork — a local halt and a human decision to
restart the network as a based rollup.

Two caveats make it weaker than it reads. First, **the check runs only on blocks
obtained from DA**; the syncer's own comment says a P2P-following node cannot
perform it, "a known limitation described in the ADR". Two honest full nodes of
the same chain therefore apply *different acceptance rules* depending on how they
happened to receive a block. Second, **Eden declares the epoch but the published
node config has no forced-inclusion namespace** — with none configured,
`HasForcedInclusionNamespace()` is false and `VerifyForcedInclusionTxs` returns
`nil`, so a node started from the published artifacts performs no censorship
check at all.

## 12. The client string does not identify the chain

ev-reth reports itself as `reth/vX` — the fork does not rename the client. None
of the divergences above are visible from `web3_clientVersion`, and ev-reth's own
RPC namespaces (`txpoolExt_`, `evolve_`) are filtered out by the public gateway.
The only reliable fingerprint from outside is behavioural: `mixHash` equal to the
block number, plus a one-byte `0xfe` at `0x…F100`.

## Not established here

- **Whether any other live Evolve EVM chain exists.** Forma was checked and
  refuted (`Geth/v1.14.3-stable`, chain 984122 — Astria, not Rollkit);
  "EVOLVE Mainnet" on chainlist (chain 3424, EVO) is an unrelated project. A
  GitHub code search for the ev-reth-only chainspec keys found exactly one
  public mainnet genesis. Absence of evidence, not evidence of absence.
- **Whether tx type `0x76` is enabled on Eden.** The public RPC returns the same
  generic `failed to decode signed transaction` for a stub `0x76`, `0x7e` and
  `0x04` payload, so the probe cannot distinguish supported from unsupported.
  Recorded as `availability: optional`. A correctly-signed `0x76` transaction
  would settle it.
- **EIP-3860.** Whether raising `contractSizeLimit` also raises the initcode cap
  (revm normally derives it as 2x the code limit) was not established from
  source. Deploying a >49152-byte initcode against Eden would settle it.
- **P256VERIFY.** Osaka is scheduled at `osakaTime: 97000000` and unreached.
  `eth_call` to `0x0100` with 160 zero bytes returned empty output, which does
  not distinguish EIP-7951-invalid from address-is-empty. Recorded `pending`.
- **What Eden's operators actually run** for forced inclusion, as distinct from
  what the published `.env` configures.
- **Whether an ev-node full node exposes a DA-inclusion height publicly.** The
  gateway exposes only the Ethereum JSON-RPC; port 7331 would give the real
  finality signal.

## Re-verify

```bash
# clones (both are released tags)
git clone --depth 1 --branch v1.2.3 --single-branch \
    https://github.com/evstack/ev-node chains/rollkit/repos/ev-node
git -C chains/rollkit/repos/ev-node rev-parse HEAD   # d76e0dfcb0ffa3384d875fa2538eeb9a5321b335
git clone --depth 1 --branch v0.5.2 --single-branch \
    https://github.com/evstack/ev-reth chains/rollkit/repos/ev-reth
git -C chains/rollkit/repos/ev-reth rev-parse HEAD   # 7f3e25fe756c2cc2e4e56a423a11d2e8fe299fe0

# the rename
curl -sI https://github.com/rollkit/rollkit | grep -i location
#   location: https://github.com/evstack/ev-node

# (2) invalid tx dropped without a trace
sed -n '186,190p' chains/rollkit/repos/ev-reth/crates/node/src/builder.rs

# (3) gibberish rule for force-included blobs
grep -n 'gibberish' chains/rollkit/repos/ev-node/execution/evm/execution.go
grep -n 'FilterRemove\|FilterPostpone' chains/rollkit/repos/ev-node/core/execution/execution.go

# (4) finalized is a height lag, and says so
grep -n 'FinalizedBlockLag\|temporary mock' chains/rollkit/repos/ev-node/execution/evm/execution.go

# (5) prevRandao
grep -n -A2 'func (c \*EngineClient) derivePrevRandao' \
    chains/rollkit/repos/ev-node/execution/evm/execution.go

# (6) equal-timestamp consensus rule
grep -n -B2 -A6 'TimestampIsInPast' chains/rollkit/repos/ev-reth/crates/evolve/src/consensus.rs

# (11) the halt message and the grace window
grep -n 'sequencer malicious' chains/rollkit/repos/ev-node/block/internal/syncing/syncer.go
grep -n 'baseGracePeriodEpochs uint64\|maxGracePeriodEpochs uint64' \
    chains/rollkit/repos/ev-node/block/internal/syncing/syncer.go

# Eden's genesis (the chainspec that chooses every optional feature)
gh api repos/celestiaorg/eden-docs/contents/public/eden-artifacts/mainnet/ev-reth.genesis.json \
   --jq '.content' | base64 -d | jq '.config.evolve'
gh api repos/celestiaorg/eden-docs/contents/public/eden-artifacts/mainnet/ev-node.genesis.json \
   --jq '.content' | base64 -d
```

Live probes (Eden), with observed answers:

```bash
R=https://rpc.eden.gateway.fm/
q(){ curl -s -X POST -H 'content-type: application/json' -d "$1" $R; echo; }

q '{"jsonrpc":"2.0","id":1,"method":"web3_clientVersion","params":[]}'
#   reth/v2.2.0-88505c7/x86_64-unknown-linux-gnu   <- NOT "ev-reth"
q '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}'          # 0x2ca

# (5)+(6) prevRandao == block number, and three blocks share one timestamp
for n in 182440253 182440254 182440255 182440256 182440257 182440258; do
  q "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$(printf '0x%x' $n)\",false]}" \
    | python3 -c "import json,sys;d=json.load(sys.stdin)['result'];print(d['number'],d['mixHash'],d['timestamp'])"
done
#   0xadfd13d 0x...0adfd13d 0x6a91e1ab
#   0xadfd13e 0x...0adfd13e 0x6a91e1ab
#   0xadfd13f 0x...0adfd13f 0x6a91e1ab
#   0xadfd140 0x...0adfd140 0x6a91e1ac
#   0xadfd141 0x...0adfd141 0x6a91e1ac
#   0xadfd142 0x...0adfd142 0x6a91e1ac

# (4) finalized/safe are a height lag, not DA finality
q '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["finalized",false]}'  # head-7 at probe
q '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["safe",false]}'       # head-2 at probe

# (7) Prague/Cancun system contracts absent
for a in 0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02 \
         0x0000F90827F1C53a10cb7A02335B175320002935 \
         0x00000961Ef480Eb55e80D19ad83579A64c007002 \
         0x0000BBdDc7CE488642fb579F8B00f3a590007251; do
  q "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$a\",\"0xadfd2cb\"]}"
done
#   all -> 0x

# (10) 0xF100 has code, real precompiles do not; 0xF101 is off on Eden
q '{"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":["0x000000000000000000000000000000000000f100","0xadfd2cb"]}'  # 0xfe
q '{"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":["0x000000000000000000000000000000000000f101","0xadfd2cb"]}'  # 0x
q '{"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":["0x0000000000000000000000000000000000000001","0xadfd2cb"]}'  # 0x
q '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x000000000000000000000000000000000000f100","data":"0xa7cd52cb0000000000000000000000000000000000000000000000000000000000000000"},"0xadfd2cb"]}'
#   0x0000...0000  (selector decoded -> mint precompile is live)

# (8) base fee credited to the sink, exactly
S=0x0337d738074c83B6133940051490c7c6080a5094
q "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBalance\",\"params\":[\"$S\",\"0xadfd2ca\"]}"  # 0x2c6984933f8c568e2
q "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBalance\",\"params\":[\"$S\",\"0xadfd2cb\"]}"  # 0x2c6984934040d24e2
python3 -c "print(0x2c6984934040d24e2 - 0x2c6984933f8c568e2, 1480*127872)"
#   189250560 189250560
```
