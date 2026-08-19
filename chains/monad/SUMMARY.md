# Monad

**Role:** `independent` · **Equivalence:** `behavioural` · **Chain ID:** 143 · **Baseline:** Osaka (opcode set only)
**Client:** [`category-labs/monad`](https://github.com/category-labs/monad) `v0.16.0`
(`e81ffe31cd30fe3455d1233e4ee6c9b3f017bad0`, C++) ·
**Companion:** [`category-labs/monad-bft`](https://github.com/category-labs/monad-bft) `v0.16.0`
(`c616743d1358186605e1c1b74a3d6c4fdd9dd48c`, Rust)
**Live probes:** `https://rpc.monad.xyz` @ block `96823552`

### Repo names, resolved

CANDIDATES.md flagged `category-labs/monad-execution` and the `monad-labs` org as
unconfirmed. Both are wrong now:

- `category-labs/monad-execution` → **404**. The execution client is
  `category-labs/monad` (its README still says "Monad Execution").
- `monad-labs/*` → **404** for every candidate name.
- `category-labs/monad-bft` exists and is on the **same release train** —
  `v0.16.0`, committed the same day as the execution repo. An earlier pass at
  `v0.9.3` looked like the latest tag only because `git ls-remote` sorts
  lexicographically; it was fifteen months stale and carried a *constant* 50 gwei
  base fee that no longer matches the chain. Both repos are pinned at `v0.16.0`.

## The headline: an EIP can be present and still not behave

This is the first row where implementation is not shared code, and the decoupling is
total. Monad implements the **Osaka opcode set faithfully** — `make_opcode_table` for
every Monad revision delegates to the Ethereum table, so an opcode diff finds
**nothing**. Then it changes gas at four independent points underneath.

### 1. `gasUsed` is the gas *limit*. Every transaction. (`severity: high`)

`compute_gas_refund` returns `0` unconditionally from `MONAD_ONE` onwards
(`category/execution/monad/monad_transaction_gas.cpp`). This is not EIP-3529 — it is
the Yellow Paper's `g*` itself. `execute_final` then computes:

```
gas_used = tx.gas_limit - gas_refund      // gas_refund is always 0
```

so **`gas_used` is identically `tx.gas_limit`**. The sender is charged for gas they
never spent; the receipt's `gasUsed` reports the *limit*; `block.gasUsed` is the sum of
limits; and the base-fee update rule takes the sum of limits as its input, which is at
least self-consistent. SSTORE still accumulates `ctx->gas_refund` — it is simply
discarded at the transaction boundary.

Confirmed live on two unrelated user transactions in block 96823552:

| tx | `gas` (limit) | receipt `gasUsed` |
|---|---|---|
| `0xc37f4106…` | `0xafc8` | `0xafc8` |
| `0x0d69a1e8…` | `0xdad08` | `0xdad08` |

Nothing reverts and nothing errors. Gas profiling, refund patterns, cost analytics, and
"what did this actually consume" all silently report the wrong number.

### 2. Memory is linear and hard-capped at 8 MB (MIP-3, live at `MONAD_NINE`)

`memory_cost_from_word_count` returns `word_count >> 1` instead of `3c + c²/512`. The
quadratic term is gone, so large memory is orders of magnitude cheaper. In exchange,
total memory across the whole call stack is capped at 8 MB, and
`is_memory_size_in_bound` exits with **OutOfGas regardless of the gas supplied**.

Two opposite-direction breaks in one change: code mainnet prices out runs cheaply here,
and code mainnet would happily run for enough gas **cannot run here at all**.

### 3. Cold access costs 4× mainnet from `MONAD_SEVEN`

`monad_pricing_version() >= 1` sets `cold_account_cost` 2500 → **10000** and
`cold_storage_cost` 2000 → **8000**. Every cold `SLOAD`, `BALANCE`, `EXTCODE*`, `CALL`
and `SELFDESTRUCT`. Same opcodes, same results, four times the gas.

### 4. EIP-1559 is replaced outright (Monad TFM)

`monad-bft/monad-tfm/src/base_fee.rs:compute_base_fee_math`. Target is **80%** of the
gas limit, not 50%. The update is an adaptive exponential whose step size is damped by
an EWMA `trend` and variance `moment` carried in the **consensus** header
(`MonadConsensusBlockHeaderV2`) and *not derivable from the Ethereum header at all*.
Clamped to `[100 gwei, 1e17 wei]`. The execution client never recomputes it — it only
checks `consensus_header.base_fee == execution_inputs.base_fee_per_gas`. Any "next base
fee" estimator ported from Ethereum is wrong on every input.

Live: `baseFeePerGas` `0x174876e800` = exactly `MIN_BASE_FEE`.

### Also nominally-present-but-different

- **EIP-7702**: accepted, but `can_create_inside_delegated()` is **false** on Monad and
  **true** for plain Ethereum traits. `CREATE`/`CREATE2` inside a delegated account is
  an error where mainnet Prague permits it.
- **EIP-170 / EIP-3860**: max code size **128 KiB** (vs 24 KiB), max initcode **256 KiB**
  (vs 48 KiB). Contracts exist here that no other EVM chain can hold.
- **EIP-4844**: `eip_4844_active()` is hardcoded false for every revision; type `0x03`
  is rejected with `TypeNotSupported`. `blobGasUsed`/`excessBlobGas` are present and
  pinned to zero.

## What the block header actually commits to

**The `stateRoot` is real.** `TrieDb::state_root()` is a genuine merkle root of that
block's post-state, and the probed block returned `0xb434912729…1239`. Monad does *not*
put a zero hash there, and it does not carry the parent's root forward. The
Hyperliquid-style "the field survived its feature" trap does not apply to `stateRoot`.

**What lags is agreement, not the value.** Consensus commits a block's transaction list
before any node executes it. A proposal carries `execution_inputs` (a pre-execution
header) plus `delayed_execution_results` — the *fully executed* header, state root
included, of the block `EXECUTION_DELAY = 3` seq-numbers earlier
(`monad-bft/monad-node/src/main.rs:EXECUTION_DELAY`,
`monad-eth-block-policy/src/lib.rs:get_expected_execution_results`). Live validation of
the proposal checks only `ommers_hash`, `transactions_root` and `withdrawals_root`
(`validate_live_execution_outputs`); `state_root` and `receipts_root` are not in the
proposal to check.

> Ordering is agreed at height N. The state root for height N is agreed at height N+3.

An indexer that treats a committed block as having a settled state root is reading a
value no quorum has voted on yet.

**One header field *is* a survivor, and it is worse than absence:** `requestsHash` is
present on every Prague-and-later Monad block and is **always the zero hash**, never the
`0xe3b0c442…b855` empty-request-list hash that mainnet emits for a block with no
requests. `eip_7685_active()` is false and the in-source comment confirms monad-bft
proposes and validates it as zero. A Prague header verifier recomputes the empty hash
and mismatches on every block. This is the second field in the dataset whose presence is
worse than its absence (after OP Stack's repurposed `blobGasUsed`).

**And one that is invisible:** `slot_number` (EIP-7843, the consensus round) is in the
`BlockHeader` struct **deliberately not RLP-encoded** — encoding it would change every
block hash with no fork gate. It is populated *only* on the consensus execution path, so
RPC and trace re-execution leave it `nullopt` and read `0`. An opcode reading the round
can return a different value under `eth_call` than it did in the block.

## System transactions with no type byte

Monad's protocol-driven state changes are **not** a distinct transaction type and **not**
unsigned. They are ordinary EIP-155-signed **legacy (`0x00`)** transactions from a fixed
key, `0x6f49a8F621353f12378d0046E7d7e4b9B249DC9e`, addressed to the staking precompile,
with `gas_limit 0` and `gasPrice 0`. `static_validate_monad_body` requires every system
transaction to precede every user transaction in the block.

Live, tx index 0 of block 96823552:

```
type 0x0  from 0x6f49a8f6…dc9e  to 0x1000  gas 0x0  gasPrice 0x0
value 0xf9ccd8a1c5080000 (≈18 MON)  v 0x141 (EIP-155, chainId 143)  status 0x1
```

Contrast OP Stack's `0x7e`, which announces itself. Monad's is distinguishable from a
user transaction **only by sender address**, and it is inside `transactionsRoot`. A tool
classifying protocol-vs-user by type byte books an 18-MON zero-gas-price transfer as
organic activity.

## A three-way address collision, and a new kind

Two added precompiles: **`0x1000` StakingContract** (from `MONAD_FOUR`) and **`0x1001`
ReserveBalanceContract** (from `MONAD_NINE`). Both return `0x` from `eth_getCode`, so
both are genuine precompiles.

`0x…1000` is where **BSC and Polygon both put a `ValidatorContract`** — as *system
contracts*, with bytecode. Monad puts validator staking at the same address as a
*precompile*, with none. Three chains, staking logic at one address, and `EXTCODESIZE`
answers `0` on one and non-zero on the other two. This is a sharper case than the
`0x64`–`0x69` collisions already in the dataset, because the *category* differs, not
just the function.

The staking precompile exposes 15 selector-dispatched methods — `addValidator`,
`delegate`, `undelegate`, `compound`, `withdraw`, `claimRewards`, `changeCommission`,
`externalReward`, plus getters — each with a fixed gas cost and a 40000-gas fallback.

## The reserve balance: transaction validity that depends on other accounts

Deferred execution needs a guarantee that a committed transaction can pay. Monad's
answer has no mainnet analogue. Every EOA (and every 7702-delegated account) has a
reserve of up to **10 MON** that consensus treats as available for fees.
`dipped_into_reserve` walks **every account the transaction touched** and reverts the
transaction if any of them ends below its threshold — so a transaction can fail because
of a balance change to an account it merely *paid*. The staking precompile is explicitly
exempt because it cannot send transactions.

Related: from `MONAD_FOUR` a transaction is valid when `balance >= gas_limit *
gas_price`, **without covering `tx.value`** (`InsufficientBalanceForFee`). It is
included, charged, and then fails inside execution with `EVMC_INSUFFICIENT_BALANCE` —
`execute_create_message` even increments the sender's nonce by hand for the depth-0 case
Ethereum's validity rules make unreachable.

## Two fork ladders that do not line up

- `monad_revision` (`MONAD_ZERO`…`MONAD_NEXT`) — **timestamp**-gated, in the C++ client.
  Mainnet is on `MONAD_NINE` since 2026-03-19, and **skips `MONAD_FOUR` and
  `MONAD_FIVE` entirely** (THREE → SIX).
- `MonadChainRevision` (`V_0_7_0`…`V_0_12_0`) — **consensus-round**-gated, in monad-bft.
  Mainnet reached `V_0_12_0` at round 89,758,000 (~2026-07-23): tx limit 3750, proposal
  gas limit 150M, vote pace 300 ms.

"Which fork is Monad on" has two correct answers, and only one of them is in the EVM.

## Recorded as `unrecorded`

- **EIP-4788** — `parentBeaconBlockRoot` is present and was `0x00…00` at the probed
  block, but whether the `0x000F3df6…` beacon-roots contract is installed or the ring
  buffer written was not established. Monad has no beacon chain, so the field's meaning
  is genuinely undetermined.
- **EIP-2935** — a `monad_block_hash_history` test exists in the tree, but
  `BLOCKHASH`/history-contract semantics under deferred execution were not read.
- **EIP-3529 refund cap composition** is *not* unrecorded — it is `removed`, because the
  refund is discarded wholesale.
- **`0x0100` P256VERIFY gas** was not read from source; the entry is `modified` on
  activation timing (`MONAD_FOUR`, before Osaka) alone.

## A note on citation checking

This row is the dataset's first C++ client, so its citations are the first to exercise
`verify.py` outside the Go/Java/Rust/Solidity set. At the time this row was written
`verify.py`'s `CITE` regex used an extension allowlist that did not include `.cpp`,
`.hpp` or `.h`, so all forty C++ `path:symbol` pairs were skipped and the row reported
"5 symbol(s) confirmed" — the five Rust citations from monad-bft. Every C++ pair was
checked by hand against the pinned clone before being written.

`3a39571 verify.py: check citations in ANY language, not an extension allowlist` landed
while this row was in progress and closed the gap: the row now reports **42 symbols
confirmed**, machine-checked, with the same content. Nothing here was changed to make
that pass.

## System transactions are signed — with a real key

Monad rewrites gas refunds, memory pricing, cold-access pricing and the fee market, and
changes **nothing** about what can authorize a transaction: `recover_sender` RLP-encodes
for signing and recovers a secp256k1 address, and the address is the hash of that key.

The interesting part is the system transaction, which is on the *opposite* side of this
axis from OP Stack's and Polygon's. `system_sender.hpp` says it outright:

> This address is derived from a known key. Consensus will sign all system transactions
> with this key.

**The key is not special-cased; the recovered address is.** `recover_senders` runs over
every transaction in the block uniformly, with no branch for system transactions — so a
system transaction with a bad signature simply recovers to the wrong address and stops
being one. Only afterwards does `dispatch_transaction` compare the recovered sender to
`SYSTEM_SENDER` and route it to a separate executor, and only then does
`static_validate_system_transaction` impose the rest of the shape: legacy type,
destination exactly `0x1000`, `gas_limit` zero, both fee fields zero, empty authorization
list.

So the authority behind a Monad system transaction is **possession of one private key** —
the same kind of secret that authorizes any other account, held by consensus.

Monad closed the obvious consequence explicitly: `validate_transaction` rejects any
transaction whose EIP-7702 authority list contains `SYSTEM_SENDER`
(`MonadTransactionError::SystemTransactionSenderIsAuthority`). Without that rule a user
could delegate code to the privileged sender's address. No mainnet analogue — mainnet has
no privileged sender to protect.

### The BLS that is not transaction authorization

Monad's consensus runs on aggregated BLS signatures, and the staking precompile really
does verify a BLS signature — in `precompile_add_validator`, over a fixed 165-byte
message, as a proof of possession alongside a secp256k1 signature. That registers a
*validator*. The `addValidator` call itself arrives inside an ordinary secp256k1-signed
transaction, and no BLS key is ever consulted when deciding who sent one.

## Re-verify

```sh
# from the repo root
tools/clone.sh                             # re-fetches every pinned clone
tools/.venv/bin/python tools/verify.py     # expect: pin ok, citations ok, exit 0
                                           # "! NO EXTRACTOR" for monad is expected

# gasUsed == gas limit, in source
git -C chains/monad/repos/monad grep -n -A 6 'uint64_t compute_gas_refund' \
  -- category/execution/monad/monad_transaction_gas.cpp
git -C chains/monad/repos/monad grep -n 'gas_used = tx_.gas_limit - gas_refund' \
  -- category/execution/ethereum/execute_transaction.cpp

# gasUsed == gas limit, live
for T in 0xc37f4106ca347673ab4de12abe4ab741ccc86418c612e0f00598455e50112d10 \
         0x0d69a1e8a1c740cfe89e8e14b050aa2ce8a2694d38a3221e52208aab30cef621; do
  curl -s -X POST https://rpc.monad.xyz -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getTransactionByHash\",\"params\":[\"$T\"]}" \
    | python3 -c 'import json,sys; print("limit  ", json.load(sys.stdin)["result"]["gas"])'
  curl -s -X POST https://rpc.monad.xyz -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getTransactionReceipt\",\"params\":[\"$T\"]}" \
    | python3 -c 'import json,sys; print("gasUsed", json.load(sys.stdin)["result"]["gasUsed"])'
done

# the header: real stateRoot, zero requestsHash, zero blob fields
curl -s -X POST https://rpc.monad.xyz -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["0x5c56b00",false]}' \
  | python3 -c 'import json,sys; b=json.load(sys.stdin)["result"]; print({k:b[k] for k in ("stateRoot","requestsHash","blobGasUsed","excessBlobGas","baseFeePerGas","gasUsed")})'

# the system transaction: legacy type, protocol sender, zero gas, to 0x1000
curl -s -X POST https://rpc.monad.xyz -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getTransactionByHash","params":["0x51f9db7f0b7416df61685735db5cc79947080660ba83d89322b1c6611745820b"]}' \
  | python3 -c 'import json,sys; t=json.load(sys.stdin)["result"]; print({k:t[k] for k in ("type","from","to","gas","gasPrice","value","transactionIndex")})'

# both added precompiles have no bytecode
for A in 0x0000000000000000000000000000000000001000 0x0000000000000000000000000000000000001001; do
  curl -s -X POST https://rpc.monad.xyz -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$A\",\"0x5c56b00\"]}"; echo
done

# deferred execution: the delay constant and where the delayed header comes from
git -C chains/monad/repos/monad-bft grep -n 'const EXECUTION_DELAY' -- monad-node/src/main.rs
git -C chains/monad/repos/monad-bft grep -n -A 20 'fn get_expected_execution_results' \
  -- monad-eth-block-policy/src/lib.rs
git -C chains/monad/repos/monad grep -n 'delayed_execution_results' \
  -- category/execution/monad/core/monad_block.hpp

```
