# Polygon zkEVM — a Berlin EVM on a fork axis that lives on Ethereum

**Chain ID 1101 · role: `fork` · baseline: Berlin · single trusted sequencer, SNARK-verified on L1**

Reference: [0xPolygon/cdk-erigon `v2.64.2`](https://github.com/0xPolygon/cdk-erigon) @ `03f20326`.

Live probes at block **33391890** (`0x1fd8512`) on `https://zkevm-rpc.com`.

This is **not** the `polygon` row. Chain 137 is Polygon PoS running `bor`, a go-ethereum
fork at Prague with eleven repriced precompiles and one added transaction type. Chain
1101 shares none of that: different client, different EVM implementation, different state
trie, different fork axis, and a baseline seven mainnet forks older. The two rows have
no lineage relationship beyond both descending, separately, from Ethereum.

---

## 1. The client in `CANDIDATES.md` is archived, and it was replaced rather than renamed

`0xPolygonHermez/zkevm-node` 301-redirects to `0xPolygon/zkevm-node`, which is
**archived**, last push **2025-02-11**. Two sibling repos moved further:
`0xPolygonHermez/zkevm-contracts` is now **`agglayer/agglayer-contracts`** — a different
organisation — and `zkevm-prover` is now `0xPolygon/zkevm-prover`, last touched
2025-08-29.

The replacement is not cosmetic. zkevm-node was a Go node driving a separate C++
prover-executor; the chain now runs **cdk-erigon**, an Erigon fork that implements the
zkEVM *inside* the execution client in Go. Confirmed live rather than inferred:

```
web3_clientVersion -> "cdk-erigon/v2.61.24/linux-amd64/go1.21.5"
```

That makes **three consecutive rows** where CANDIDATES.md's coordinates were stale
(gnosischain/gnosis 404s, InjectiveLabs/injective-core changed orgs, mantlenetworkio
redirects). Checking that the repo still exists at the recorded path has now been a
finding four times; it should be step zero, not a formality.

*(Pin note: the tag is `v2.64.2`, the newest non-prerelease. The public endpoint runs
`v2.61.24`. This matters more than the usual tag/deployment gap because v2.64.2 contains
`PrecompiledContractsForkID13Durian` and the Normalcy/MPT migration, neither of which any
block on chain 1101 has ever selected. Where the two could differ, the row states what the
live fork selects.)*

## 2. `forkID` is a sixth fork-activation mechanism, and the only one not in the client

The Ethereum ladder is frozen by a chainspec of sentinels:

```json
// params/chainspecs/hermez.json
"berlinBlock": 0,
"londonBlock": 9999999999999999999999999999999999999999999999999,
"shanghaiTime": 9999999999999999999999999999999999999999999999999,
"cancunTime":   9999999999999999999999999999999999999999999999999,
"pragueTime":   9999999999999999999999999999999999999999999999999,
```

Everything that actually changes is gated on **forkID**, and `hermez.json` contains not
one forkID field. `UpdateZkEVMBlockCfg` builds the node's `chain.Config` fork blocks **at
runtime**, from the node's local database of **Ethereum L1 events**. A forkID is announced
on L1, applies from a **batch** number, and becomes an L2 **block** number only inside a
node that has synced L1.

So, against the five mechanisms the dataset already had — OP Stack's timestamp equality,
Avalanche's timestamps, Arbitrum's ArbOS version, Polygon PoS's block numbers, Moonbeam's
governance-swapped WASM blob — forkID is a sixth with properties none of them share:

- the schedule is **mutable from L1** with no L2 client release;
- the canonical unit is the **batch**, and the block number is derived, so "which
  semantics applied at block N" is answerable only with an L1-synced node;
- a forkID can be **skipped**, and one was.

| forkID | first L2 block | first batch | what changed |
|---|---|---|---|
| 4 | 1 | 2 | Berlin set; SELFDESTRUCT→SENDALL; log data zero-padded; log index per-tx |
| 5 Dragonfruit | 5,575,557 | 813,267 | **PUSH0** (a Shanghai opcode); effective-gas-price byte |
| 6 IncaBerry | 7,261,581 | 1,228,917 | |
| 7 Etrog | 9,890,792 | 1,984,750 | `changeL2Block`; gas limit → 2^50; **0x03 and 0x09 disabled** |
| 8 Elderberry | 10,742,147 | 1,998,875 | **0x05 MODEXP disabled**; `applyHexPadBug`; log index per-block |
| 9 Elderberry2 | 10,985,133 | 2,001,443 | |
| **10** | **never** | **none** | *skipped — and still changed the rules* |
| 11 | 16,482,669 | 2,128,919 | prover step budget → 2^25 |
| 12 Banana | 19,175,239 | 2,150,230 | **current**; log mangling removed |
| 13 Durian | *pending* | — | coded in v2.64.2; would re-enable MODEXP and add P256VERIFY |

**forkID 10 never happened and still changed consensus.** forkID 9 ends at batch 2128918
and forkID 11 begins at 2128919 — zero batches in between. But `UpdateZkEVMBlockCfg`
assigns any unannounced forkID *the previous fork's block number* ("using last set block
number"), so every `IsForkID10()` gate in the client became true at forkID 9's block.
Two rules ride on those gates: the end of the "contract code must not end in `PUSH1`"
rejection, and a doubling of the prover step budget. A skipped fork is not a no-op.

## 3. Three tombstoned precompiles, and one of them changed status across a forkID

`precompile_zkevm` switches on exactly two conditions —
`IsForkID13Durian`, then `IsForkID8Elderberry` — with no branch for 9, 10, 11 or 12. So
**forkID 8's map has been the live map since block 10,742,147** and still is.

```go
// core/vm/contracts_zkevm.go — PrecompiledContractForkID7Etrog
{3}: &ripemd160hash_zkevm{enabled: false},
{5}: &bigModExp_zkevm{enabled: true,  eip2565: true},   // <-- working
{9}: &blake2F_zkevm{enabled: false},

// PrecompiledContractsForkID8Elderberry
{3}: &ripemd160hash_zkevm{enabled: false},
{5}: &bigModExp_zkevm{enabled: false, eip2565: true},   // <-- disabled
{9}: &blake2F_zkevm{enabled: false},
```

**MODEXP worked, then stopped.** Same address, opposite behaviour, at block 10,742,147,
with no Ethereum fork name on either side and nothing in a chainspec to read. It is
scheduled to come back at forkID 13 Durian, which has never activated — so the honest
description of `0x05` on this chain is *present → absent → (pending) present*, on an axis
no Ethereum tool models. Every archive replay and historical simulation across that height
is affected.

Live at block 33391890:

```
eth_call 0x03 -> error -32000 "unsupported precompile"
eth_call 0x05 -> error -32000 "unsupported precompile"
eth_call 0x09 -> error -32000 "unsupported precompile"
eth_call 0x0a -> 0x   (success, empty)
eth_call 0x0100 -> 0x (success, empty)
```

### The revert-vs-empty question, and a third channel: gas

`ErrUnsupportedPrecompile` is classified as a revert by name:

```go
// core/vm/errors.go
func IsErrTypeRevert(err error) bool {
	return err == ErrExecutionReverted || err == ErrUnsupportedPrecompile
}
```

and `call_zkevm` only zeroes the caller's gas `if !IsErrTypeRevert(err)`. `RequiredGas`
also returns 0 when disabled, so nothing is pre-charged. Measured with a state-override
`eth_call` that `STATICCALL`s each address forwarding 10,000 gas and returns
`GAS_before − GAS_after`:

| target | success flag | gas consumed |
|---|---|---|
| `0x02` SHA256 (works) | 1 | **182** |
| `0x03` RIPEMD160 (tombstoned) | 0 | **122** |
| `0x05` MODEXP (tombstoned) | 0 | **122** |
| `0x0a` (absent) | 1 | **2622** |

Three readings from one probe at one block:

1. **`tombstoned` vs `removed` is directly visible**: `0x05` reverts, `0x0a` succeeds
   empty — Scroll's control case, reproduced on an unrelated chain and client.
2. **The forwarded gas comes back.** 122 gas is the harness itself; the disabled
   precompile costs nothing and returns everything. This is the **opposite of Scroll**,
   whose disabled precompiles raise a non-revert error that burns all forwarded gas, and
   whose `0x03` is charged the full RIPEMD160 price before failing. Two chains, the same
   three-precompile decision, opposite gas semantics — a caller wrapping the call in a
   try/catch survives here and is drained there.
3. **A gas channel distinguishes the two even when the outcome does not.** The disable is
   a *field on the precompile object* (`&bigModExp_zkevm{enabled: false}`), not a missing
   map entry, so the address stays in the map, stays in Berlin's pre-warmed access list,
   and stays **warm** — 122 gas. An absent address is **cold** — 2622, a 2500-gas
   difference. Where a chain's tombstone were to return empty rather than revert (the
   Hyperliquid/Sei silent-failure shape), the warm/cold gas gap would still separate
   "present but dead" from "never there". That is a detection method this dataset did not
   have.

### How this instance of the prover-constraint pattern differs

Fourth chain, fourth mechanism:

| chain | mechanism | fails as | visible in `eth_call`? |
|---|---|---|---|
| OP Stack | caps a single call's **input size** | revert | yes |
| Linea | budgets prover **lines per block** | never selected, no receipt | **no — it succeeds** |
| Scroll | disables the precompile, non-revert error | error, **all gas burned** | yes |
| **Polygon zkEVM** | disables the precompile, revert-class error | revert, **gas returned** | yes |

And on the expiry question Scroll raised: Polygon's restrictions are **still live at the
pinned block**, not historical. Scroll lifted its 32-byte MODEXP cap at Galileo and its
BN256 pairing cap at Feynman; zkSync's cap stands; Linea's became EIP-7823. Polygon went
the other way — it *added* a restriction at forkID 8 and has not lifted it in four
forkIDs. The reversal is coded (forkID 13 Durian) and unshipped.

One respect in which Polygon's version is the **friendliest** of the four: because the
refusal lives in the precompile map rather than in a block-building budget, `eth_call`,
`eth_estimateGas` and forked-node tests all fail exactly as the chain does. Linea's
zeroed budgets let RIPEMD160 succeed in simulation and be permanently unminable. Here,
simulation and execution agree.

## 4. `BLOCKHASH` returns the state root

The sharpest silent divergence on this chain, and it is not a precompile.

```go
// core/vm/instructions_zkevm.go
func opBlockhash_zkevm(...) {
	num := scope.Stack.Peek()
	num.Set(ibs.GetBlockStateRoot(num))     // storage read, not a header lookup
}
```

`GetBlockStateRoot` reads `keccak256(blockNumber, 1)` from the storage of
`0x000000000000000000000000000000005ca1ab1e`, which the protocol populates each block
with that block's **state root**. Proven at the pinned height:

```
eth_call BLOCKHASH(33391889)          -> 0x02df6fea936e2d0ca3472d7082de46dfbee2e32963aff33cb691c74354f5e67d
eth_getBlockByNumber(0x1fd8511).stateRoot -> 0x02df6fea936e2d0ca3472d7082de46dfbee2e32963aff33cb691c74354f5e67d
eth_getBlockByNumber(0x1fd8511).hash      -> 0xeae67882ae615883e1f2b20a98478a709976c42ec4e99d57389f5f262c604731
```

Both values are 32 bytes, neither reverts, and the wrong one is entirely plausible. Every
commit-reveal scheme, randomness beacon and L1-anchoring contract that compares
`BLOCKHASH` against a hash fetched over JSON-RPC is silently wrong. There is also no
visible 256-block window — it is a storage read, so arbitrarily old heights answer.

Worse, the value is not even the same *kind* of hash. The state trie is a **Poseidon
sparse Merkle tree** (`smt/`), not a Keccak MPT — which is why observed state roots begin
with a low byte, they are field elements. `eth_getProof` does not return an
Ethereum-verifiable proof, and no mainnet light client or storage-proof verifier can check
one.

`NUMBER` reads slot 0 of the same account and `DIFFICULTY` is hardcoded to zero.

## 5. A category the schema does not have: a storage-only protocol account

`0x…5ca1ab1e` has **no bytecode** — `eth_getCode` returns `0x` — and holds consensus-critical
state that three opcodes read:

```
slot 0 -> 0x1fd8512   (= the head block number)
slot 2 -> 0x6a47db80  (= the head timestamp)
```

It is not a precompile (no native dispatch, absent from all four forkID maps) and not a
`system_contract` in this schema's sense (no EVM bytecode). It is a third thing, and it is
recorded under `system_contracts` with the caveat stated, because omitting it would hide
the mechanism behind two silent opcode redefinitions.

**On the classification test**: the dataset has established that `eth_getCode` does not
decide precompile-vs-contract — Flare, Sonic, Cosmos EVM and Moonbeam all write decoy code
at precompile addresses. Here the classification is made from the **source map**
(`precompile_zkevm`'s four forkID maps); the probe only confirms it. `0x…5ca1ab1e`
returning `0x` is evidence of the third category, *not* evidence that it is a precompile —
which is exactly the inference the getCode-only test would make.

## 6. Event log data was corrupted by consensus for 8.4 million blocks

`ApplyPaddingToLogsData` has three regimes, on a forkID axis:

- **forkID 4–7**: `data` zero-padded at the end to a multiple of 32.
- **forkID 8–11** (blocks 10,742,147 – 19,175,238): `applyHexPadBug` — hex-encode the last
  32-byte word, right-pad the *string* to 64 characters, **strip leading `'0'` characters**,
  re-prepend zeros, truncate. A nibble-level shift that mangles the tail of any log whose
  data length is not a multiple of 32.
- **forkID 12**: `if isForkId12 { return }` — no transformation. The bug is gone.

The function is named `applyHexPadBug`. It is a bug the chain froze into consensus for
four forkIDs and then dropped. An indexer re-deriving logs across that range must
*reproduce* the bug to match the chain. Log **indexing** changed too: forkID 4–7 restart
`logIndex` at zero per transaction rather than per block.

A related receipt divergence with the same shape: before forkID 8,
`CreateReceiptForBlockInfoTree` **forces `status = 1`** on any receipt whose execution
error was `ErrUnsupportedPrecompile` — a transaction that reverted on a disabled
precompile was recorded as successful in the proven block-info tree. The comment reads
`// [hack]TODO: remove this after bug is fixed`.

## 7. A Berlin envelope in 2026

`baseline_fork: berlin`, derived from the chainspec, not from a blog post. Live-verified,
opcode by opcode, at the pinned block:

```
PUSH0        -> executes            (EIP-3855, Shanghai, arrived at forkID 5)
BASEFEE      -> invalid opcode
TSTORE       -> invalid opcode
MCOPY        -> invalid opcode
BLOBHASH     -> invalid opcode
BLOBBASEFEE  -> invalid opcode
0x1e (CLZ)   -> opcode 0x1e not defined
GASLIMIT     -> 0x4000000000000  (2^50)
```

The header has **no `baseFeePerGas` key at all** — absent, not zero — and no
`withdrawalsRoot`, `blobGasUsed`, `excessBlobGas`, `parentBeaconBlockRoot` or
`requestsHash`. It is a pre-London Ethereum header: `difficulty`, `mixHash`, `nonce`,
`sha3Uncles`, `totalDifficulty` all present and all constant. A parser written against a
2020 header works; one written against a 2026 header finds five fields missing.

Transaction types follow: `!isLondon && txn.Type == 0x2` is rejected as `UnsupportedTx`,
blob and set-code types as `TypeNotActivated`. **Chain 1101 accepts exactly `0x00` and
`0x01`** — zero added type bytes, three removed. It took nothing from the `0x7f` ceiling
that Arbitrum, Base, OP Stack and Polygon PoS have been consuming downward.

One London EIP *is* live, by accident of code shape: `createZkEvm` rejects returned code
beginning `0xEF` **unconditionally**, where upstream Erigon guards the same check with
`IsLondon`. The zkEVM copy dropped the guard, so the chain enforces EIP-3541 without ever
activating London.

The batch encoding has its own, incompatible one-byte type space: legacy transactions are
written as bare concatenated fields with no envelope, `fullRlpTxType = 15` prefixes a
typed transaction, and `11` introduces a 9-byte `changeL2Block` record that creates block
boundaries. Those bytes are not EIP-2718 types; the L1 batch data cannot be parsed with an
Ethereum transaction decoder.

## 8. Two meters, and the fee you sign is not the fee you pay

**Effective gas price.** The sequencer attaches a one-byte percentage to every transaction
and the state transition rewrites `gasPrice`, `feeCap` *and* `tip` to
`signed × (ep+1) / 256` before execution, from forkID 5 onward
(`CalculateEffectiveGas`, `GetTxContext`). `ep = 0` charges 1/256 of the signed price. The
byte travels in the L1 batch data, so it is consensus, not policy. **A signature over a
`gasPrice` is not a commitment to that `gasPrice` here**; read `effectiveGasPrice` from the
receipt rather than computing it.

**Eight zk counters.** `totalSteps, arith, binary, memAlign, keccaks, padding, poseidon,
sha256`, budgeted **per batch**, with the budget a function of forkID: `totalSteps` is
2^23 below forkID 10, 2^24 at 10, 2^25 from 11, minus 200 and then minus a safety margin.
The margin is 5% by default, 2.5% at forkID 10, 1.25% at forkID 11 — and
`safetyPercentages` has **no entry for forkID 12**, so the live fork falls back to the 5%
default. The margin tightened at 11 and loosened again at 12, silently, because a map was
not updated. The other seven limits are fixed ratios of `totalSteps`
(`arith = steps>>5`, `keccaks = floor(steps/155286)*44`, `poseidon = floor(steps/31)`…).

**How the second meter fails**, characterised against the other rows that have one:

A transaction that overflows counters is **not reverted, not charged, and gets no
receipt.** `CheckForOverflow` returns true, the sequencer discards the attempted counters,
marks the sender skipped for the rest of the batch, and moves on.
`SingleTransactionOverflowCheck` then re-runs it alone against an empty batch; if it still
overflows, `handleBadTxHashCounter` increments a persistent per-hash counter and the
transaction is discarded from the pool.

That is **Linea's shape** (unminable, cached as bad) rather than **Taiko's** (block
truncated, stays valid) or **Moonbeam's** (surfaces as `OutOfGas` with EVM gas left). It
differs from Linea's in the resource — Linea budgets arithmetization *lines per block*,
Polygon budgets prover *steps per batch* — and in one way that matters practically: Linea
uses zeroed budgets as a feature switch, making specific precompiles permanently unminable
while they still work in `eth_call`. Polygon put its permanent refusals in the precompile
map instead, so its counters are purely a **size limit**. Gas is irrelevant to the outcome
either way: a perfectly funded transaction simply never appears.

## 9. `SELFDESTRUCT` does not destroy anything

```go
// core/vm/instructions_zkevm.go — "removed the actual self destruct at the end"
func opSendAll_zkevm(...) {
	if beneficiaryAddr != callerAddr {
		AddBalance(beneficiaryAddr, balance); SubBalance(callerAddr, balance)
	}
	return nil, errStopToken
}
```

Balance moves, then STOP. No deletion mark, no code clearing, no storage clearing, no
nonce reset. This is neither mainnet's pre-Cancun `SELFDESTRUCT` nor EIP-6780's
same-transaction form — it is a third behaviour at `0xff`, live since forkID 4, and
`enable6780` is *explicitly commented out* in the Cancun instruction-set builder with the
reason given. A self-destructing proxy ported here keeps its code and keeps answering
calls after "destruction".

Related trap: cdk-erigon **defines** opcode `0xfb` as `SENDALL` in the disassembler and
then wires it to `INVALID` in the live instruction set. The mnemonic exists; the opcode
does not. A tracer will label an invalid opcode as a valid one.

`EXTCODEHASH` is redefined too: it returns the **zero hash** for any account with no code,
where EIP-1052 returns `keccak256("")` for an *existing* codeless account and zero only
for a non-existent one. Proven on a funded account at the pinned block — `BALANCE` returns
`0x10470379026fd4e7`, `EXTCODEHASH` returns zero. Every "is this a contract?" and "does
this account exist?" check inverts, silently.

## 10. The chain appears to have stopped

Recorded as an observation with the evidence attached, not as an editorial. At probe time:

```
eth_blockNumber            -> 0x1fd8512  (33,391,890)
that block's timestamp     -> 1783094144  = 2026-07-03 15:54:44 UTC   (52 days stale)
eth_syncing                -> false
finalized block            -> 0x1a67ec0  (27,688,640), timestamp 2025-12-03
zkevm_batchNumber          -> 0x222f44   (2,240,324)   trusted
zkevm_virtualBatchNumber   -> 0x21b7c3   (2,209,731)   sequenced to L1
zkevm_verifiedBatchNumber  -> 0x21b7c3   (2,209,731)   proved on L1
```

The head did not move across 24 hours, and `polygon-zkevm.drpc.org` reports the identical
head — two independent endpoints. **30,593 batches were produced and never posted to L1**,
and 5,703,250 blocks — 17% of the chain's history — sit above the last finalized block
with no proof behind them.

`chain.live` is therefore set to `false`, the only row in the dataset with that value.
Whether this is a permanent sunset or a long outage is **not established here**; the
observation is pinned and reproducible either way.

## One row, not two: why there is no `role: template` CDK row

The case *for* one existed and is real. `params/chainspecs/xlayer-mainnet.json` is
byte-identical to `hermez.json` except for `ChainName` and `chainId`; `zk_chain_config.go`
hardcodes eight chain IDs (195, 196, 1101, 2440, 2442, 10010, 999999, 123) that make
`IsZk()` true; and the forkID axis is per-deployment by construction — two CDK chains on
one client version at different forkIDs genuinely have different precompile sets. That is
`template` shape: optional-per-deployment rather than inherited wholesale.

It was rejected for one reason: **a template row would assert facts about chains from
which nothing was established.** Emitting `role: template` for CDK would put X Layer,
Immutable and Astar zkEVM under a node claiming a disabled MODEXP, a state-root
`BLOCKHASH` and a Berlin baseline, and every one of those is a function of *that chain's
own forkID and its own L1 rollup contract*, neither of which was read. X Layer runs its
own fork of this client (the repo ships `xlayerconfig-mainnet.yaml.example` alongside
`hermezconfig-mainnet.yaml.example`, and the OKX fork is not public at the coordinates
tried).

And "CDK" is no longer one codebase. `0xPolygon/cdk` is an orchestrator, not an EVM;
`0xPolygon/cdk-validium-node` is a separate node; `0xPolygon/cdk-op-reth` (pushed
2026-08-10) puts CDK on the OP Stack with reth. A template row would have to describe a
family that no longer shares an EVM — precisely the overstatement `role: template` exists
to prevent.

What a future CDK template row would need: one live probe of X Layer's `zkevm_getForks`
and `eth_call 0x05`, to establish whether the forkID axis moves independently per
deployment. If it does, the shared node holds the *mechanism* (forkID gating, counters,
SENDALL, the scalable account) and each chain holds its own forkID — which is exactly the
`template` contract. The evidence for that is one probe away and was not gathered here.

## Not established here

- **Whether the chain is sunset or merely stalled.** Section 10 states what was observed
  and stops. No L1 archive access was available to date the last `sequenceBatches`.
- **EIP-7823 / MODEXP operand bounds.** Marked `unrecorded` rather than guessed. MODEXP is
  disabled outright, so there is no width cap to compare against 1024 bytes. If forkID 13
  ever activates, `bigModExp_zkevm.Run` has no width check and this becomes `removed` —
  but that is a prediction, not a measurement.
- **Whether type-0x01 (access list) transactions actually appear on chain.** The pool
  accepts them and the source path exists; the block census at the pinned height found
  only type `0x0`.
- **The precompile extractor.** `verify.py` reports `! NO EXTRACTOR` for this slug — the
  precompile list is taken from a hand-read of four Go maps and confirmed by probe, not
  cross-checked mechanically.
- **`CREATE2` address derivation.** `opCreate2_zkevm` differs from upstream only in gas
  bookkeeping and revert-data handling; the derivation itself was not traced to
  `crypto.CreateAddress2`, so it is stated nowhere in the row rather than asserted as
  inherited.
- **Whether forkIDs 1–3 existed on mainnet.** `ForkID4` is the lowest constant the client
  knows and `zkevm_getForks` starts at 4.

---

## Re-verify

```sh
git clone --depth 1 --branch v2.64.2 https://github.com/0xPolygon/cdk-erigon
cd cdk-erigon && git rev-parse HEAD    # 03f20326c5ae5acf8cac32159dd03aeb244d6913

# the repo moves — both 301 to a different org, one to an archived repo
curl -sI https://api.github.com/repos/0xPolygonHermez/zkevm-node | grep -i location
curl -sL https://api.github.com/repos/0xPolygonHermez/zkevm-node  | grep -E '"full_name"|"archived"'
curl -sL https://api.github.com/repos/0xPolygonHermez/zkevm-contracts | grep '"full_name"'

# baseline: Berlin at 0, everything after London a sentinel
cat params/chainspecs/hermez.json

# the four forkID precompile maps — note enabled:true at Etrog, enabled:false at Elderberry
sed -n '48,99p' core/vm/contracts_zkevm.go
sed -n '29,50p'  core/vm/evm_zkevm.go          # precompile_zkevm: only 13 and 8 are tested

# disabled precompiles raise a REVERT-class error, so gas is returned
grep -n -A 3 "func IsErrTypeRevert" core/vm/errors.go
grep -n -B 2 -A 4 "IsErrTypeRevert(err)" core/vm/evm_zkevm.go

# the fork axis is built at runtime from L1, and skipped forks inherit a block
sed -n '112,143p' zk/utils/utils.go
cat erigon-lib/chain/zk_constants.go

# BLOCKHASH, NUMBER, DIFFICULTY, EXTCODEHASH, SELFDESTRUCT
sed -n '/func opExtCodeHash_zkevm/,/^}/p;/func opBlockhash_zkevm(/,/^}/p;/func opNumber_zkevm/,/^}/p;/func opDifficulty_zkevm/,/^}/p;/func opSendAll_zkevm/,/^}/p' core/vm/instructions_zkevm.go
sed -n '/func (sdb \*IntraBlockState) GetBlockStateRoot/,/^}/p' core/state/intra_block_state_zkevm.go
grep -n "enable6780" core/vm/jump_table_zkevm.go        # commented out, with the reason

# the enshrined log bug and the forced status=1 receipt
sed -n '39,92p' core/types/log_zkevm.go
sed -n '294,302p' core/blockchain_zkevm.go

# two meters
sed -n '/func CalculateEffectiveGas/,/^}/p' core/state_transition.go
sed -n '9,32p;82,120p' core/vm/zk_counters_limits.go
sed -n '653,676p' zk/stages/stage_sequence_execute.go   # overflow -> discarded, never mined

# no 1559, no blobs, no 7702 in the pool
sed -n '837,842p;896,900p' zk/txpool/pool.go
cat zk/utils/gas_limit.go
```

Live probes, all at block `33391890` (`0x1fd8512`) on `https://zkevm-rpc.com`:

```sh
R=https://zkevm-rpc.com; B=0x1fd8512
c(){ curl -s -X POST $R -H 'content-type: application/json' -d "$1"; echo; }

c '{"jsonrpc":"2.0","id":1,"method":"web3_clientVersion","params":[]}'   # cdk-erigon, not zkevm-node
c '{"jsonrpc":"2.0","id":1,"method":"zkevm_getForks","params":[]}'       # forkID 10 is missing
c '{"jsonrpc":"2.0","id":1,"method":"zkevm_getForkId","params":[]}'      # 0xc
c '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}'      # frozen at 0x1fd8512
c '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["finalized",false]}'
c '{"jsonrpc":"2.0","id":1,"method":"zkevm_batchNumber","params":[]}'
c '{"jsonrpc":"2.0","id":1,"method":"zkevm_verifiedBatchNumber","params":[]}'

# tombstoned (error) vs removed (success, empty) — one block, one probe
for a in 01 02 03 04 05 06 07 08 09 0a; do
  c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x00000000000000000000000000000000000000$a\",\"data\":\"0x\"},\"$B\"]}"
done
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"0x\"},\"$B\"]}"

# gas channel: STATICCALL forwarding 10000 gas, returns GAS_before - GAS_after
# 0x05 -> 122 (warm, revert, gas returned) | 0x02 -> 182 | 0x0a -> 2622 (cold, absent)
A=0x00000000000000000000000000000000deadbeef
probe(){ c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"$A\",\"gas\":\"0x100000\"},\"$B\",{\"$A\":{\"code\":\"$1\"}}]}"; }
probe 0x5a60006000600060006005612710fa505a900360005260206000f3   # 0x05
probe 0x5a60006000600060006002612710fa505a900360005260206000f3   # 0x02
probe 0x5a6000600060006000600a612710fa505a900360005260206000f3   # 0x0a

# BLOCKHASH returns the STATE ROOT
probe 0x6301fd85114060005260206000f3
c '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["0x1fd8511",false]}'

# EXTCODEHASH is zero for a funded, codeless account
probe 0x73d6f0feeaab8eac205b182d51ae05b588a132be5a3f60005260206000f3   # -> 0x00..00
probe 0x73d6f0feeaab8eac205b182d51ae05b588a132be5a3160005260206000f3   # BALANCE -> non-zero

# Berlin envelope
probe 0x5f60005260206000f3           # PUSH0        -> executes
probe 0x4860005260206000f3           # BASEFEE      -> invalid opcode
probe 0x600160005d5f5c60005260206000f3  # TSTORE     -> invalid opcode
probe 0x5e60005260206000f3           # MCOPY        -> invalid opcode
probe 0x4a60005260206000f3           # BLOBBASEFEE  -> invalid opcode
probe 0x1e60005260206000f3           # CLZ          -> not defined
probe 0x4560005260206000f3           # GASLIMIT     -> 0x4000000000000

# the storage-only protocol account
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x000000000000000000000000000000005ca1ab1e\",\"$B\"]}"
for s in 0x0 0x2; do c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getStorageAt\",\"params\":[\"0x000000000000000000000000000000005ca1ab1e\",\"$s\",\"$B\"]}"; done
```
