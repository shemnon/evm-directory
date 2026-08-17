# Hyperliquid / HyperEVM — the first row with no source to read

**Chain ID 999 · role: `independent` · equivalence: `behavioural` · evidence: `documented`**

No public execution client. No repo, no tag, no commit, nothing to clone or diff. This
is the first row in the dataset built without a pinned source tree, and it exists to
test whether the `documented` extension actually carries weight.

The answer is that it carries more than expected — but not the same weight, and not in
the same places. **Every headline finding below came from probing the running network,
not from the documentation.** The docs corroborate three of them, are silent on four,
and enumerate almost nothing.

Probed at block **43436288** (`0x296c900`) against `https://rpc.hyperliquid.xyz/evm`,
2026-08-17. `web3_clientVersion` returns `hyperliquid evm Mainnet` — no client name, no
version. There is nothing to pin but a block height.

## Read this before trusting any number here

**The public endpoint silently ignores the block parameter on every state-reading
method.** `eth_call`, `eth_getCode`, `eth_getBalance` and `eth_getTransactionCount`
return *latest* state at any requested height, with no error and no warning:

```
eth_call NUMBER opcode, block param 0x1        -> 43436842   (the head, at request time)
eth_getCode 0x3333...3333, block param 0x1     -> 544 bytes  (months before it existed)
```

`eth_getBlockByNumber` *does* honour the parameter. So for this row `observed_at_block`
records **when**, not **at what height the result was computed** — the schema wants a
pin equivalent to a commit, and this chain cannot give one, because no public archive
node serves historical state. Replaying these probes reproduces them only while the
chain still behaves this way.

That limitation is worth stating plainly: **a `documented` row is weaker than a `source`
row in a way the provenance key alone does not express.** `src:` is reproducible
forever; `src_live:` here is reproducible only against a moving target.

It is also, itself, a finding. Any fork-test, historical simulation or archive replay
pointed at this endpoint is quietly reading the present.

## `stateRoot` is zero. Always. Everywhere.

```
stateRoot  0x0000…0000   in 120/120 blocks scanned (43436288–43436407)
           and at blocks 1, 100, 1e6, 1e7, 2e7, 3e7, 4e7
eth_getProof -> Method not found
```

HyperEVM headers commit to **no state at all**. There is no state trie to prove
against, which is presumably why `eth_getProof` is not served. Light clients, Merkle
state proofs, and trust-minimised bridges that read HyperEVM state from a header are
structurally impossible here.

The field is still present and well-formed in the JSON. Anything that reads it gets a
plausible 32-byte value that means nothing, and never errors.

## `0x0100` is empty — the universal address isn't

The dataset's standing finding is that `0x0100` is *the one universal address*: all
seven earlier rows carry P256VERIFY there, arriving through four unrelated forks.

Hyperliquid is the counterexample. Probed with a locally generated, locally verified
P-256 signature, against a live Ethereum mainnet control on byte-identical calldata:

| | `eth_call 0x…0100`, valid 160-byte vector |
|---|---|
| Ethereum mainnet | `0x0000…0001` |
| **HyperEVM** | `0x` (empty) |
| control: unallocated `0x0101` | `0x` (empty) |

`severity: high`, and for a specific reason. EIP-7951 signals *invalid signature* by
returning empty output — which is exactly what an absent precompile returns. Every P256
verification on this chain reports "invalid" forever, with no revert and no error. A
passkey or WebAuthn wallet ported here is broken and looks like it is merely rejecting
bad signatures.

## `0x0a` is a tombstone made by a build flag

```
HyperEVM  eth_call 0x…0a, 192 zero bytes -> Revm precompile error: c-kzg feature is not enabled
mainnet   eth_call 0x…0a, 192 zero bytes -> mismatched versioned hash
```

The mainnet error is *semantic* — the precompile is alive and rejecting the input.
HyperEVM's is not: the address resolves to a precompile whose implementation was
compiled out. It fails identically on a well-formed 192-byte input.

This is precisely the `tombstoned` vs `removed` line SCHEMA.md draws, and it was
established **from the outside, by behaviour alone**: a tombstone *fails*, an absent
address *succeeds with empty output*. BSC and Avalanche tombstoned addresses
deliberately. This one looks like a missing cargo feature.

The same discriminator maps the rest of the range. BLS12-381 at `0x0b`–`0x11` returns
empty success on valid-length input, byte-identical to the known-unallocated `0x12`, so
EIP-2537 is `removed`, not tombstoned.

## Cancun, measured rather than claimed

The docs say "the HyperEVM implements the Cancun hardfork without blob support." For
once the probe agrees — and the probe is what makes it a measurement:

| Evidence | Result |
|---|---|
| Cancun opcodes | `PUSH0`, `MCOPY`, `TLOAD`/`TSTORE`, `BLOBHASH`, `BLOBBASEFEE` all execute |
| Cancun header fields | `withdrawalsRoot`, `blobGasUsed`, `excessBlobGas`, `parentBeaconBlockRoot` present |
| **`requestsHash` (EIP-7685)** | **absent from every header, block 1 to head** — not Prague |
| BLS12-381 (EIP-2537) | absent — not Prague |
| EIP-2935 history contract | no code — not Prague |
| P256VERIFY (EIP-7951) | absent — not Osaka |
| EIP-4788 beacon-roots contract | no code |

Cancun's *opcodes*, without Cancun's beacon half and without blobs.

## Dual blocks, one chain, one timestamp

Two block kinds interleave in a single strictly-increasing number sequence, drawn from
two independent mempools. Over 120 consecutive blocks:

```
gasLimit histogram:  {3,000,000: 197,  30,000,000: 3}     (over a 200-block scan)
large blocks at:     43436329,  43436390,  43436451
gaps:                61 blocks,  60 seconds
```

And the part the docs do not mention:

```
43436388  ts=1786980420  gasLimit= 3,000,000
43436389  ts=1786980420  gasLimit= 3,000,000     <-- same timestamp
43436390  ts=1786980420  gasLimit=30,000,000     <-- same timestamp, LARGE block
43436391  ts=1786980421  gasLimit= 3,000,000
```

**Timestamps are not strictly increasing.** Every large block shares its timestamp with
the small block before it — 2 of 119 transitions in the scanned window, matching exactly
the 2 large blocks it contained. Mainnet requires `timestamp[n] > timestamp[n-1]`.

Any elapsed-time delta across that boundary is zero, and anything dividing by it
reverts. The dual-block documentation promises "a unique increasing sequence of EVM
block numbers" and says nothing whatsoever about timestamps.

The small-block limit has also moved: **2,000,000** at blocks 1 through 10,000,000,
**3,000,000** by block 20,000,000. A live parameter change with no fork name attached.

## Precompiles vs system contracts — the distinction this chain is built on

`eth_getCode` settles the category that SCHEMA.md says gets conflated constantly:

| Address | Code | Category |
|---|---|---|
| `0x…0800`–`0x…0814` | **none** | precompile (21 of them) |
| `0x3333…3333` CoreWriter | **544 bytes** | system contract |
| `0x2222…2222` native bridge | **122 bytes** | system contract |

Hyperliquid's own docs get this right — "a system contract is available at
0x3333…" — even though third-party write-ups routinely call CoreWriter a precompile.

The read-precompile block's boundaries were probed in both directions:

```
0x07fd, 0x07fe, 0x07ff  ->  0x (empty success)      not precompiles
0x0800 … 0x0814         ->  EVM error: PrecompileError    21 live precompiles
0x0815, 0x0816, 0x0817, 0x0820  ->  0x (empty success)    range ends at 0x0814
```

17 of the 21 returned real data once given the right input width; `0x0802`, `0x080f`,
`0x0811` and `0x0813` are demonstrably live but rejected every encoding tried, so their
signatures are recorded as unrecorded. The docs name exactly **one** of these 21
addresses (`0x…0807`, as an example) and enumerate none of the rest — the enumeration in
`chain.yaml` is the probe's, not the documentation's.

`0x…0809` takes no arguments and returns HyperCore's own block height: **1,113,794,421**
against an EVM block number of **43,436,288** at the same moment. Two clocks, ~25x
apart, visible inside one EVM.

## Both system contracts are a gas burn and a log

CoreWriter's 544 bytes disassemble to the entire contract: one selector, an empty
400-iteration loop, one event, return.

```
selector  0x17938e13                      = keccak("sendRawAction(bytes)")
loop      PUSH2 0x0190                    = 400 iterations, pure gas burn
LOG2      0x8c7f585f…12e3                 = keccak("RawAction(address,bytes)")
```

Both hashes recomputed locally and matched against the constants in the bytecode *and*
against 27 live `RawAction` logs. The measured cost agrees with the disassembly:
`eth_estimateGas` gives **47042** against a 21000 baseline.

`0x2222…2222` is the same shape, smaller: revert if `calldatasize != 0`, otherwise emit
`Received(address,uint256)` (`0x88a5966d…5874`, likewise verified against live logs)
with `msg.value`.

**Neither touches EVM state.** The real effect is produced off-EVM, asynchronously, by
HyperCore reading those logs. So `sendRawAction` has no return value and cannot revert
on a rejected action: a contract that places an order, cancels one, or bridges funds
gets a **successful call whether HyperCore accepts or rejects it**. Every EVM-level
guarantee stops at the log boundary, and checking the return value does not help,
because there is none.

## What HyperEVM did *not* need

- **No custom opcodes.** 24 unallocated opcodes probed by executing them as init code —
  `0x0c`, `0x0d`, `0x0e`, `0x0f`, `0x1e`, `0x1f`, `0x21`, `0x4b`–`0x4f`, `0xa5`, `0xa6`,
  `0xb0`, `0xb1`, `0xc0`, `0xd0`, `0xe0`, `0xee`, `0xf6`–`0xf8`, `0xfc` — all return
  `OpcodeNotFound`. The jump table is stock.
- **No custom transaction type.** Only `0x00` and `0x02` observed across ~450
  transactions. No type byte was burned.
- **All of `0x01`–`0x09` match mainnet**, each checked against a known vector or a live
  mainnet control. Notably `0x03` really is RIPEMD160 here — contrast Tron.

This chain reaches an entire order book from inside the EVM using nothing but 21 read
precompiles and two log-emitting contracts. Tron needed 16 opcodes at `0xd0`–`0xdf` for
less; Arbitrum, Base, OP and Polygon each spent a type byte. **The divergence is not in
the instruction set at all** — it is in the block schedule, the header, and the
asynchronous boundary between the EVM and HyperCore.

## Fee model

EIP-1559, with three twists. Priority fees are **burned** rather than paid to a proposer
(docs attribute this to HyperBFT; `miner` is the zero address in 120/120 headers and
`eth_maxPriorityFeePerGas` returns 0). The base fee has a **hard floor at 100,000,000
wei** — unmoved across 13 consecutive blocks whose gas used ranged 0 to 1,067,253
against a 3,000,000 limit, far under target, where stock 1559 would have decayed it
~12.5% per block. And the controller spans two block kinds 10x apart in gas limit, so
"the" target is not one number.

Receipts carry only the standard fields — **no `l1Fee`, no DA component** — which
separates this cleanly from every OP Stack row.

## Where the evidence runs out

The row is deliberately `unrecorded` in nine places, and it is worth being explicit
about why, because the temptation on a source-less chain is to fill the table from the
baseline:

- **tx types `0x01`, `0x03`, `0x04`** and **EIP-7702, EIP-2930** — the
  `eth_sendRawTransaction` decoder returns *the same* message for every type byte tried
  (`0x01/0x02/0x03/0x04/0x05/0x7e/0x7f` and legacy all give `failed to decode signed
  transaction`), so it cannot distinguish supported from unsupported. Absence from a
  ~450-transaction sample is not absence from the protocol. Blob transactions are
  *unusable* here — no KZG, blob gas pinned to zero — but the type byte itself was never
  tested, and this row does not launder inference into measurement.
- **EIP-6780, 3529, 7823, 7883** — would need a funded key and a deployed contract.
- **`0x5555…5555`** has 2041 bytes of code, but nothing in the RPC distinguishes a
  protocol-installed predeploy from an ordinary contract at a mined vanity address. That
  distinction *is* the category, so it stays unrecorded.
- **Core→EVM system transactions** — `0x2222…2222` reports a nonce of **1,015,323**,
  which no ordinary contract accumulates (a contract nonce only moves on `CREATE`). The
  natural reading is that HyperCore originates protocol transactions from that address.
  None was found in the sampled blocks, no receipt field marks one, and `debug_` tracing
  is not exposed. Suspected, not established.

Nine of the row's facts carry no provenance at all, and every one of them is
`unrecorded` — which is the honest pairing. `verify.py` reports the row as
`SKIP (documented)` with `src_live=52`, and the run stays green.

## Re-verify

There is no clone to grep. The doc-row analogue is the probe itself — these are the
literal calls, pinned to the block height in `live_probe.observed_at_block`.

```sh
RPC=https://rpc.hyperliquid.xyz/evm
B=0x296c900          # 43436288
call() { curl -s -X POST $RPC -H 'Content-Type: application/json' \
         -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}"; echo; }

# identity of the endpoint
call eth_chainId '[]'                                   # -> 0x3e7 (999)
call web3_clientVersion '[]'                            # -> "hyperliquid evm Mainnet"

# the block parameter is ignored for state — run this FIRST, it bounds everything below
call eth_call '[{"data":"0x4360005260206000f3"},"0x1"]' # NUMBER at "block 1" -> the head
call eth_getCode '["0x3333333333333333333333333333333333333333","0x1"]'   # 544 bytes

# stateRoot is zero, requestsHash is absent
call eth_getBlockByNumber '["0x296c966",false]'         # large block 43436390
call eth_getBlockByNumber '["0x296c965",false]'         # small block, SAME timestamp
call eth_getProof '["0x3333333333333333333333333333333333333333",[],"latest"]'  # Method not found

# dual block schedule: gasLimit 3,000,000 vs 30,000,000, 61 blocks / 60 s apart
for n in 296c929 296c966 296c9a3; do call eth_getBlockByNumber "[\"0x$n\",false]"; done

# precompile range boundaries: empty success outside, PrecompileError inside
call eth_call '[{"to":"0x00000000000000000000000000000000000007ff","data":"0x"},"0x296c900"]'  # 0x
call eth_call '[{"to":"0x0000000000000000000000000000000000000800","data":"0x"},"0x296c900"]'  # PrecompileError
call eth_call '[{"to":"0x0000000000000000000000000000000000000814","data":"0x"},"0x296c900"]'  # PrecompileError
call eth_call '[{"to":"0x0000000000000000000000000000000000000815","data":"0x"},"0x296c900"]'  # 0x

# HyperCore read precompiles returning live data
call eth_call '[{"to":"0x0000000000000000000000000000000000000809","data":"0x"},"0x296c900"]'  # L1 height
call eth_call '[{"to":"0x0000000000000000000000000000000000000807","data":"0x0000000000000000000000000000000000000000000000000000000000000000"},"0x296c900"]'  # oraclePx(0)

# 0x0a is tombstoned by a build flag — compare against mainnet on identical bytes
Z192=0x$(printf '0%.0s' $(seq 1 384))
call eth_call "[{\"to\":\"0x000000000000000000000000000000000000000a\",\"data\":\"$Z192\"},\"0x296c900\"]"
curl -s -X POST https://ethereum-rpc.publicnode.com -H 'Content-Type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x000000000000000000000000000000000000000a\",\"data\":\"$Z192\"},\"latest\"]}"; echo

# BLS12-381 absent: valid-length input, empty on HyperEVM, 128 bytes on mainnet
Z256=0x$(printf '0%.0s' $(seq 1 512))
call eth_call "[{\"to\":\"0x000000000000000000000000000000000000000b\",\"data\":\"$Z256\"},\"0x296c900\"]"

# P256VERIFY absent at 0x0100 — a VALID vector, and the mainnet control that proves it valid
V=0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa339118eab84d4d7b9adfadf908eea6fc4844ef55380886877139a061c1e41dc36b8fea91bab95124fd712102cb932a44ecce92035747caa2476dea1e4f74c198471c3e758c4904285bba7e53118ed0f524adeb0757d25bd2f8e7b0d76dfa714cdd520f7aca8a8b917acc37f51de8f0c9bbe3ad858382e702dc25a12d09f7a858
call eth_call "[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"$V\"},\"0x296c900\"]"   # 0x
curl -s -X POST https://ethereum-rpc.publicnode.com -H 'Content-Type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"$V\"},\"latest\"]}"; echo   # 0x..01

# no custom opcodes: <opcode> PUSH1 0 MSTORE PUSH1 32 PUSH1 0 RETURN, run as init code
for op in 0c 21 4b a5 b0 d0 f6 fc; do
  call eth_call "[{\"data\":\"0x${op}60005260206000f3\"},\"0x296c900\"]"      # OpcodeNotFound
done
call eth_call '[{"data":"0x4460005260206000f3"},"0x296c900"]'   # PREVRANDAO -> 0, always

# system contracts have code; the two log topics are the whole story
call eth_getCode '["0x3333333333333333333333333333333333333333","0x296c900"]'
call eth_getCode '["0x2222222222222222222222222222222222222222","0x296c900"]'
call eth_getLogs '[{"address":"0x3333333333333333333333333333333333333333","fromBlock":"0x296ca80","toBlock":"0x296ca90"}]'   # 4 RawAction logs
```

Verifier:

```sh
tools/.venv/bin/python tools/verify.py     # hyperliquid -> SKIP (documented), exit 0
```
