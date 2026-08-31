# Conflux eSpace — what this row teaches

Pinned: `Conflux-Chain/conflux-rust` **v3.1.0** (`6e2e837c8271695b139e491f50e586ebd8ed10c8`).
No companion repo — consensus, the two-space state transition, the EVM, the transaction
pool and the RPC layer are all in this one tree. Live probe:
`https://evm.confluxrpc.com`, chain id **1030**, block **155333000** (timestamp
1787845217, 2026-08-27 ~15:40 UTC, `baseFeePerGas` 20 gwei). A handful of claims are
pinned to nearby blocks and say so, and a few are cross-checked against the **Core
Space** RPC `https://main.confluxrpc.com` (chain id **1029**) — the same node, the same
ledger, the other space. Baseline fork **osaka**, reached **two days before this row was
written** (V3.1 at epoch 155,140,000 = 2026-08-25 02:20:38 UTC).

**Evidence path taken: source, and the pin is exact.** Mainnet answers
`web3_clientVersion` with `conflux-rust/v3.1.0-6e2e837-20260810/x86_64-linux-gnu/rustc1.94.1`
and `6e2e837` is this commit's short hash — so for once "the pinned tag" and "what
validators run" are provably the same thing. Every gas number below that could be
measured was measured live as well as read, by binary search over `eth_call` gas limits.

---

## 0. The one sentence everything else follows from

**An eSpace block does not exist.** Conflux is one ledger with two spaces: Core Space
(chain id 1029, `cfx:` base32 addresses, Conflux's own nine-field transaction) and
eSpace (chain id 1030, `0x` addresses). They share one block DAG, one consensus, one PoW
and **one block body** — and have disjoint account trees with separate nonces.

`eth_getBlockByNumber(N)` therefore does not read a block. It calls
`get_phantom_block_by_number`, which walks every Core-Space block in **epoch N**'s
ordered block set, keeps the eSpace transactions, **silently drops the skipped ones**,
**injects synthesised transactions** for cross-space calls, and then dresses the result
in the epoch's **pivot block's** header with several fields substituted and several
invented. Four of the five roots in that header are stale, wrong, or fabricated. That is
the row.

## 1. Ordering commits five epochs before execution — and the header lies about it, where Monad's does not

`DEFERRED_STATE_EPOCH_COUNT = 5`. The pivot header at height H commits
`deferred_state_root` / `deferred_receipts_root` for epoch **H-5**. The eSpace RPC
republishes those two values under Ethereum's `stateRoot` and `receiptsRoot` keys
verbatim. Verified by reading the same epoch from both spaces:

```
eth_getBlockByNumber(0x94230d0).stateRoot     = 0x24f37b5a0cecb93611e7f2ab57dea8db...9109
cfx_getBlockByEpochNumber(0x94230d0)
        .deferredStateRoot                    = 0x24f37b5a0cecb93611e7f2ab57dea8db...9109
```

**This is the same invariant break as Monad and the opposite failure.** Monad's header
carries a *genuine* post-state root for its own block; what lags is the *agreement*
(block N+3 carries the executed header). Conflux's header carries an *agreed* root that
belongs to *a different block*. Monad's field is right and early; Conflux's is wrong and
on time. A bridge proving an account against `eth_getBlockByNumber(N).stateRoot` is
proving against state five epochs stale, and fails on any account touched since — with
no signal in the JSON that anything is unusual.

The deferral is visible from outside without any source at all:

```
cfx_getStatus  epochNumber 155333043   latestState 155333039 (-4)
eth_blockNumber            155333039
eth_getBlockByNumber(155333043) -> null
```

`BlockId::Latest` maps to `EpochNumber::LatestState`, so **`eth_blockNumber` is not the
tip** — it is the last *executed* epoch, four to five behind a chain height that is
already committed and ordered. `pending` maps to the same executed epoch (so it is not
pending), `safe` to latestConfirmed (~46 back) and `finalized` to the PoS-finalised
epoch (~200-240 back).

## 2. `transactionsRoot` does not commit to the transactions in the same response

The strongest possible demonstration, live:

```
eth_getBlockByNumber(0x94230d0, true)   # epoch 155332816
  transactions:     [ one type-0x02 transfer ]
  transactionsRoot: 0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470
                    ^ that is keccak256("")
```

`Header::from_phantom` sets `transactions_root` to the **pivot block's own**
`transactions_root`, which covers only the pivot block's body — while the transaction
*list* is gathered from **every** block in the epoch. The transaction above lived in a
non-pivot block. When the epoch has no eSpace transactions at all the serialiser
substitutes the empty-trie constant `0x56e81f17...b421` outright, for both roots. There is
no value of `transactionsRoot` from which an eSpace block's transaction list can be
verified, and no value of `receiptsRoot` from which its receipts can.

## 3. The central question: a transaction ordered but invalid at execution is *erased*

Conflux has a **third receipt outcome** that Ethereum does not:
`TransactionStatus::{Success, Failure, Skipped}`. `Skipped` is produced by
`ExecutionOutcome::NotExecutedDrop` and `NotExecutedToReconsiderPacking` in
`fresh_executive.rs`, and it covers exactly the brief's list:

| condition | variant | repackable? |
|---|---|---|
| nonce already consumed (**incl. the same tx packed in two DAG blocks**) | `TxDropError::OldNonce` | no, dropped forever |
| nonce too high | `ToRepackError::InvalidNonce` | **yes, retried at a later height** |
| gas price below the base-fee threshold *at the pivot block* | `ToRepackError::NotEnoughBaseFee` | yes |
| sender account does not exist | `ToRepackError::SenderDoesNotExist` | yes |
| sender has code (CIP-152 / EIP-3607) | `TxDropError::SenderWithCode` | no |
| Core-Space only: `epoch_height` window expired | `ToRepackError::EpochHeightOutOfBound` | yes |

For a skipped transaction `gas_used()` and `gas_fee()` return zero, the nonce is not
bumped, and no state changes. Then the RPC layer removes every trace of it:

- the phantom-block builder skips it — *"we do not return non-executed transaction"* —
  so it is **not in `eth_getBlockByNumber`**;
- `block_data_manager` writes a transaction index only for `Success | Failure`, so
  **`eth_getTransactionByHash` returns null**;
- `eth.rs:transaction_receipt` explicitly re-checks and bails —
  *"a skipped transaction is not available to clients if accessed by its hash"* — so
  **`eth_getTransactionReceipt` returns null, forever**.

So the answer to (c) is the first bullet on the brief's list, and it is total: **silently
dropped, no receipt, no trace, indistinguishable from never having been submitted** —
even though the transaction is sitting in a Core-Space block body that is part of the
committed total order. The DAG makes duplicate inclusion *normal*: two miners packing
the same transaction is expected, the first occurrence executes, and the second is
skipped and erased.

There is one important exception, and it is the opposite extreme (section 4).

## 4. Insufficient balance is not a skip — it takes the sender's entire balance

The EVM's "balance must cover gas + value" precheck (`check_enough_balance`) runs **only
if `spec.align_evm`**, which is a devnet-only flag defaulting to `u64::MAX` on mainnet.
So on Conflux mainnet an underfunded eSpace transaction *executes*:

```rust
// pre_checked_executive.rs:charge_gas
let actual_gas_cost = if insufficient_sender_balance {
    U512::min(gas_cost, sender_balance)   // take everything they have
} else { gas_cost };
// executed.rs:not_enough_balance_fee_charged
gas_used: *tx.gas(),          // the full LIMIT
fee: *actual_gas_cost,
```

The nonce is bumped, the sender's **whole remaining balance** is confiscated as a partial
fee, `gasUsed` in the receipt is the *gas limit*, and `status` is `0`. That is the
"charged a partial/penalty fee" outcome from the brief, reachable on mainnet, in a state
Ethereum's validity rules make unreachable. Monad reaches a neighbouring state (fee-only
precheck, then `EVMC_INSUFFICIENT_BALANCE`); Conflux goes further and takes the dust.

## 5. Preconfirmations: Conflux is MegaETH run backwards

`transaction_receipt` returns `None` while
`epoch_num > best_executed_state_epoch_number` — *"the receipt is only visible to
optimistic execution"*. There is no early receipt and no changeable receipt. Where
MegaETH hands you a receipt whose `blockHash` is `0xffff...ff` because the block does not
exist yet, Conflux hides a block that *does* exist until its state does. Both destroy
"a receipt names a block that exists"; the defences are opposite (MegaETH: wait for the
hash to stop being a sentinel; Conflux: the RPC already waited for you, and understated
the chain height while waiting).

## 6. `blockhash(block.number)` is non-zero, and returns a *different* non-zero value under `eth_call`

CIP-133 moved BLOCKHASH into state: epoch hashes go into a **65,536-slot ring buffer**
(`epoch_hash_slot(h) = base | (h & 0xffff)`), read back under
`env.epoch_height - 65536 < number <= env.epoch_height`. Two consequences, both verified
live at the pinned block.

**The window is 256x mainnet's.** `BLOCKHASH(n)` returned the true hash for every
`n` from 155333000 down to **155267466** (65,534 back, ~18 hours) and zero from
155267465 down — both boundaries confirmed. A contract using `blockhash(n) == 0` as
"older than 256 blocks", a standard idiom, never takes that branch for eighteen hours.

**The upper bound is inclusive, which mainnet's is not.** `before_epoch_execution` writes
the pivot block's own hash into its slot *before* the epoch's transactions run —
something only deferred execution makes possible — so inside a mined transaction
`blockhash(block.number)` returns **the hash of the block the transaction is in**.
Mainnet defines that to be zero.

And under `eth_call` it is a *third* value. A call pinned at block B runs with
`block.number = B+1` (`NUMBER` returned `0x9423189` for a call pinned at `0x9423188`)
against the state after epoch B, where slot `(B+1) & 0xffff` still holds a hash from
65,536 epochs earlier:

```
eth_call @ 0x9423188 : BLOCKHASH(155333001) = 0xd6dbfdfbfce50426...2243
eth_getBlockByNumber(155267465).hash        = 0xd6dbfdfbfce50426...2243   # 155333001 - 65536
```

One expression, three answers: zero on mainnet, the current block's hash in a Conflux
transaction, an 18-hour-old hash in a Conflux simulation. **Simulation does not predict
execution**, which is the worst possible property for a commit-reveal or lottery
contract.

Historical footnote that names the hazard: CIP-98 (v2.1) exists because eSpace's
BLOCKHASH originally compared against `env.number` — the **DAG block number** — while
eSpace's `block.number` is the **epoch height**. The two differ by ~2.42x, so
`blockhash(block.number - 1)` returned zero.

## 7. `block.prevrandao` is always zero — on a proof-of-work chain with a real nonce

Opcode `0x44` reads `env.difficulty`, which the eSpace environment leaves at its default,
and the RPC hardcodes `mix_hash: H256::default()`. Meanwhile the same header reports a
**real** PoW `difficulty` (`0x417b1f0be9`) and a **real** PoW `nonce` (truncated from
Conflux's U256 to Ethereum's H64, so it is lossy and cannot re-verify the proof of work).
eSpace exposes the two PoW fields that are useless as entropy and zeroes the one field
every contract reads for entropy. It is neither pre-Merge Ethereum nor post-Merge
Ethereum; there is no randomness of any kind, and nothing reverts.

## 8. Every state-growth price is doubled by one integer, and it is measurable from outside

`Spec::evm_gas_ratio = 2`, applied **only** on eSpace paths (Core Space uses 1). It
multiplies `sstore_set_gas`, `create_data_gas`, `call_new_account_gas`,
`suicide_to_new_account_cost` and EIP-7702's `per_empty_account_cost`. Binary search over
`eth_call` gas limits at the pinned block:

| measurement | observed | mainnet |
|---|---|---|
| min gas to deploy 1,000 bytes | 453,194 | ~253,000 |
| min gas to deploy 2,000 bytes | 853,292 | ~453,000 |
| => code deposit | **400.1 gas/byte** | 200 |
| noop CREATE | 53,064 | 53,000 |
| noop CREATE + one 0->non-zero `SSTORE` | 95,238 | ~75,100 |
| => `SSTORE` set | **40,000** (+2,100 cold) | 20,000 |

And the size limit moves with it: `create_data_limit = 49152`, **exactly 2x EIP-170**,
confirmed at the boundary — a 49,152-byte deployment succeeds and 49,153 fails with
`execution reverted: Out of gas`, not a distinct size error, so tooling cannot tell an
oversized contract from a genuinely underfunded one. eSpace holds contracts no
mainnet-equivalent chain can hold, and charges twice to deploy any of them.

The client itself concedes the gap: `align_evm_transition_height` would set the ratio to
1, the code limit to 24,576, `per_auth_base_cost` to EIP-7702's 12,500 and the BLOCKHASH
window to 256 — and the docs say it is **devnet only**. Its default is `u64::MAX`.

## 9. Two base fees in one block, and the advertised one is not the threshold

`base_price` in a Conflux header is a `SpaceMap<U256>` — one base fee per space, updated
independently, in the same block. Live, same epoch, two RPCs:

```
eth_getBlockByNumber(155333000).baseFeePerGas       = 0x4a817c800  (20 gwei, eSpace)
cfx_getBlockByEpochNumber(155333000).baseFeePerGas  = 0x3b9aca00   ( 1 gwei, Core)
```

Four independent breaks from EIP-1559: the update input is the **sum of packed
transaction gas *limits***, not gas used (as on Monad); each space's target is its own
share of the block limit / 2, and the shares are 50% for eSpace and 90% for Core, which
sum to 140% — they are caps on a shared budget, not a partition; there is a per-space
**floor** (20 gwei for eSpace, and mainnet sits exactly on it at every block sampled);
and the base fee is computed per DAG block against *that block's* parent while execution
uses the *pivot* block's, so a transaction validated at its packing block's base fee can
be executed against a higher one — and is then skipped and erased (section 3).

**The inclusion threshold is not `baseFeePerGas`.** CIP-137 burns only part of the base
fee, governed by an on-chain DAO parameter, and `check_base_price` compares the
transaction's gas price against the **burnt part alone**. The receipt exposes both
numbers in a non-standard `burntGasFee` key, so the current parameter is readable from
outside:

```
gasUsed 0xa1a60 . effectiveGasPrice 0x4a817c800 . gasFee 0x2f0bbf433b0000
burntGasFee 0x115537232a33c0  ->  36.84% of the fee  ->  7.368 gwei burnt of 20 gwei
```

The initial parameter was a half-burn; governance has moved it. So the real minimum gas
price on eSpace today is about **one third** of the number every Ethereum client reads as
the base fee, and it changes without a fork.

## 10. Blocks contain transactions nobody signed, and a block with two transactions can report `gasUsed: 0x0`

Cross-space calls originate in Core Space. eSpace never sees the Core transaction — it
sees **phantom transactions** manufactured by replaying that transaction's logs
(`recover_phantom`). A `CallEvent`/`CreateEvent` produces a *pair*: a funding transfer
**from the zero address** carrying `abi.encode(coreTxHash, crossSpaceNonce)` as calldata,
then the real call from the mapped sender. A `WithdrawEvent` produces one transfer to the
zero address. All are legacy **type 0x00**, `gas: 0`, `gasPrice: 0`, consume no gas.
Observed at epoch 155332825:

```
transactions: 2      gasUsed: 0x0
tx0  type 0x0  from 0x0000...0000  to 0x86e7e8a9...8b73  gas 0x0  gasPrice 0x0
     input = 0x5ef751cd...81a + 32 zero bytes            v 0x82f  r 0x406  s 0x406
tx1  type 0x0  from 0x86e7e8a9...8b73  -> the actual call
receipt(tx0): gasUsed 0x0, gasFee 0x0, effectiveGasPrice 0x0, status 0x1, no `type` key
```

Three separate traps in that dump.

**Nothing distinguishes them from user transactions.** No type byte, a normal-looking
`from`, a real hash, a receipt, logs, an index, and they answer
`eth_getTransactionByHash`. An indexer books zero-gas-price value transfers as organic
activity. (Compare Monad, whose system transactions are also type-0x00 but are
distinguishable by a fixed sender address; here the sender is a *different* mapped
address per Core account.)

**The zero address has unboundedly many nonce-0 transactions**, because the funding
phantom is always emitted with `nonce: 0` — *"zero address always has nonce 0"*.
Transaction-per-sender-per-nonce uniqueness does not hold.

**The JSON `r`/`s` are the chain id, deliberately.** `fake_sign_phantom` sets
`r = s = sender address`; when the sender is the zero address that is zero, so
`Transaction::from_signed` substitutes `chain_id` — *"some txs r and s to 0 which is not
valid in some ethereum tools, so we set them to chain_id"*. The `raw` field in the same
object still RLP-encodes zeros (`...82 08 2f 80 80`). Re-deriving the hash from the JSON
fields, or running `ecrecover` on them, contradicts the response that supplied them.

**And a failed cross-space call is invisible.** A Core-Space transaction that reverts
produces *no* phantom transactions at all — *"failing transactions will not produce any
phantom txs or traces"* — so a cross-space call that was ordered, executed and charged
leaves nothing in eSpace.

## 11. The internal contracts are not precompiles and not system contracts — from eSpace they are not there

The brief asked which side of SCHEMA.md's boundary Conflux's internal contracts fall on.
Neither, and the source settles it in one line:

```rust
// contract_map.rs:InternalContractMap::contract
if address.space != Space::Native { return None; }
```

Probed live at the pinned block, `eth_getCode` returns `0x` for **all eight** — AdminControl
`0x0888...0000`, SponsorWhitelistControl `...0001`, Staking `...0002`, Context `...0004`,
PoSRegister `...0005`, **CrossSpaceCall `...0006`**, ParamsControl `...0007`, SystemStorage
`...000a` — and `eth_call` to CrossSpaceCall returns empty output, exactly like an empty
account. There is **no eSpace-callable cross-space surface at all**: value moves Core->eSpace
only by a *Core* transaction calling `transferEVM`/`callEVM`, and back only by
`withdrawFromMapped`, which sweeps `keccak256(coreAddress)[12..]`. Only 1/10 of remaining
gas crosses into eSpace (`CROSS_SPACE_GAS_RATIO = 10`), against the EVM's 63/64.

Two negatives fall out of the same place, and they are findings: **storage collateral and
gas sponsorship — Conflux's two most distinctive economic mechanisms — do not exist in
eSpace.** `compute_cost_info` short-circuits for Ethereum-space senders with
`assert_eq!(storage_cost, U256::zero())` and `gas_sponsored: false, storage_sponsored:
false, storage_sponsor_eligible: false`. `Transaction::storage_limit()` is `None` for
every Ethereum transaction. Nothing an eSpace contract does can touch either.

## 12. The precompile set is mainnet-Osaka-equivalent and tells you nothing

`new_builtin_map` is called twice — once per space — and the two differ in exactly one
entry (`ecrecover` vs `ecrecover_evm`, because Core Space coerces the recovered address
into Conflux's typed-address format). eSpace gets 0x01-0x11 plus 0x0100, all confirmed
live: 0x0b-0x11 are real BLS12-381, 0x0a is KZG point-evaluation, and 0x0100 returns
**empty output** for 160 zero bytes, i.e. EIP-7951 semantics. `0x12` and `0x0101` behave
like empty accounts. **Conflux adds no precompile of its own to eSpace and installs no
bytecode at any address.**

Two things worth saying anyway. KZG at `0x0a` is present at the mainnet price (50,000) on
a chain with **no blob transactions, no `BLOBHASH`, no blob gas market** — CIP-144
imported the precompile alone, so a contract can verify a proof about a blob the chain
can never carry. And `0x0000F90827F1C53a10cb7A02335B175320002935` (EIP-2935) is a live
trap: `set_eip2935_storage` writes the parent hash into slot `(h-1) % 8191` at the start
of every epoch — but only `if` the address has code, and it has none. Deploy anything
there and the client silently starts writing into its storage. Recorded as
`tombstoned`, not `removed`, for that reason.

## 13. CANDIDATES.md put Conflux eSpace in Tier 2 — "divergence likely real but narrower". That ranking is wrong

Narrower than what? The row has **eight `severity: high` entries**: a `stateRoot` that
belongs to another block, a `transactionsRoot` that commits to nothing, a `PREVRANDAO`
pinned to zero, a `BLOCKHASH` with a 65,536-block window and an inclusive upper bound
that differs between `eth_call` and execution, an `SSTORE` and a code-deposit price at
2x mainnet, a 48 KiB code limit, an insufficient-balance path that confiscates the
sender's whole balance, and a class of unsigned transactions with fabricated signature
fields. Every one of them is *silent*: no revert, no error, no flag in the JSON.

Meanwhile the two things a survey would normally measure — the **type-byte set**
(0x00/0x01/0x02/0x04, no additions, no 0x03) and the **precompile address set**
(0x01-0x11 + 0x0100, no additions) — are byte-for-byte Prague/Osaka mainnet. Conflux
eSpace is the cleanest example in this dataset of a chain that passes every envelope- and
address-diffing check and diverges everywhere those checks cannot see. Tier 1 on impact;
the "narrower" prediction measured the wrong axis.

---

## Not established here

- **What a skipped transaction looks like on the wire.** Every claim in section 3 is from
  source. Producing one requires submitting a transaction that becomes invalid between
  packing and execution, which needs a funded key and a race. No skipped transaction was
  caught live — by construction, because the RPC is designed so that you cannot.
- **Whether `gasPrice` below `baseFeePerGas` is actually accepted in practice.** The
  source is unambiguous (`check_base_price` compares against `burnt_gas_price`) and the
  live `burntGasFee` pins the ratio at 36.84%, but a 120-block scan found no transaction
  priced below the advertised base fee — every wallet sets >= base fee. The claim rests on
  source plus arithmetic, not on a counterexample.
- **CIP-175's phantom-transaction shape.** Whether a cross-space call into a 7702-delegated
  eSpace account reports the delegator or the delegate as `to` in the phantom transaction
  was not established. Left `unrecorded`.
- **Exact eSpace `EXTCODEHASH` / SELFDESTRUCT refund behaviour** under CIP-645's
  `fix_extcodehash` and CIP-151 was read but not measured.
- **Whether the DAG can order the *same* transaction into two blocks in the *same*
  epoch** (as opposed to two epochs). The nonce check makes the outcome identical either
  way, so the distinction was not chased.
- **Reorg depth.** `latestFinalized` was observed 183-239 epochs behind the tip across
  three samples; whether that is a bound or a coincidence of load was not established.
- **The Core-Space `epoch_height` window as seen from eSpace.** It is `None` for every
  Ethereum transaction (`epoch_height` and `storage_limit` are Native-only), so the
  brief's question — what a client observes when a packed transaction's window expires —
  has no eSpace answer. It is recorded under `non_evm_transactions`.
- **Whether any mainnet contract actually exceeds 24,576 bytes.** The 49,152 limit is
  proven; that someone used it is not.

---

## Re-verify

```sh
cd /Volumes/TendiesTown/EVM-intel
R=https://evm.confluxrpc.com; C=https://main.confluxrpc.com; B=0x9423188   # 155333000
rpc(){ curl -s -X POST -H 'content-type: application/json' \
       -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}" "${3:-$R}"; }

# --- pin: the tag IS what mainnet runs
git -C chains/conflux/repos/conflux-rust describe --tags     # v3.1.0
git -C chains/conflux/repos/conflux-rust rev-parse HEAD      # 6e2e837c8271695b...
rpc web3_clientVersion '[]'   # conflux-rust/v3.1.0-6e2e837-20260810/...
rpc eth_chainId '[]'          # 0x406 = 1030

# --- source: deferred execution, the 1-in-5 rule, the space gas shares, the burn
grep -n 'DEFERRED_STATE_EPOCH_COUNT\|EVM_TRANSACTION_BLOCK_RATIO\|CIP1559_ESPACE_TRANSACTION_GAS_RATIO\|CROSS_SPACE_GAS_RATIO\|INITIAL_1559_ETH_BASE_PRICE\|CIP137_BASEFEE_PROP_INIT' \
  chains/conflux/repos/conflux-rust/crates/parameters/src/lib.rs
# --- source: the header is the pivot's, with deferred roots
sed -n '/fn from_phantom(pb: &PhantomBlock) -> Self/,/^        }$/p' \
  chains/conflux/repos/conflux-rust/crates/rpc/rpc-eth-types/src/block.rs
# --- source: Skipped is erased from the block, the index, and the receipt
grep -n 'we do not return non-executed transaction' \
  chains/conflux/repos/conflux-rust/crates/cfxcore/core/src/consensus/consensus_graph/rpc_api/phantom_block_provider.rs
grep -n 'A skipped transaction is not available' \
  chains/conflux/repos/conflux-rust/crates/rpc/rpc-eth-impl/src/eth.rs
grep -n 'TransactionStatus::Success | TransactionStatus::Failure' \
  chains/conflux/repos/conflux-rust/crates/cfxcore/core/src/block_data_manager/mod.rs
# --- source: which invalidity is a drop, which is a repack, and what align_evm gates
sed -n '/fn check_nonce/,/fn check_from_eoa_with_code/p' \
  chains/conflux/repos/conflux-rust/crates/execution/executor/src/executive/fresh_executive.rs
grep -n 'if self.context.spec.align_evm' \
  chains/conflux/repos/conflux-rust/crates/execution/executor/src/executive/fresh_executive.rs
# --- source: insufficient balance takes everything
grep -n 'U512::min(gas_cost, sender_balance)' \
  chains/conflux/repos/conflux-rust/crates/execution/executor/src/executive/pre_checked_executive.rs
# --- source: evm_gas_ratio = 2 and its call sites
grep -rn 'evm_gas_ratio' chains/conflux/repos/conflux-rust/crates/execution/
# --- source: BLOCKHASH from state, 65536 ring buffer, inclusive upper bound
sed -n '/fn blockhash_from_state/,/^    }$/p' \
  chains/conflux/repos/conflux-rust/crates/execution/executor/src/context.rs
grep -n -A7 'pub const fn epoch_hash_slot' \
  chains/conflux/repos/conflux-rust/crates/execution/executor/src/internal_contract/impls/context.rs
grep -n -A4 'fn before_epoch_execution' \
  chains/conflux/repos/conflux-rust/crates/cfxcore/core/src/consensus/consensus_inner/consensus_executor/epoch_execution.rs
# --- source: internal contracts are Native-only; no collateral / sponsor in eSpace
grep -n 'address.space != Space::Native' \
  chains/conflux/repos/conflux-rust/crates/execution/executor/src/internal_contract/components/contract_map.rs
grep -n -A3 'if sender.space == Space::Ethereum' \
  chains/conflux/repos/conflux-rust/crates/execution/executor/src/executive/fresh_executive.rs
# --- source: phantom transactions and their fake signature
sed -n '/pub fn recover_phantom/,/^}/p' \
  chains/conflux/repos/conflux-rust/crates/execution/execute-helper/src/phantom_tx/recover.rs
grep -n -B2 -A4 'we set them to chain_id' \
  chains/conflux/repos/conflux-rust/crates/rpc/rpc-eth-types/src/transaction.rs
# --- source: CIP-130, EIP-2935 gated on has_no_code, mainnet fork heights
grep -n -A14 'fn check_gas_limit_with_calldata' \
  chains/conflux/repos/conflux-rust/crates/cfxcore/core/src/verification.rs
grep -n -A8 'pub fn set_eip2935_storage' \
  chains/conflux/repos/conflux-rust/crates/execution/executor/src/state/state_object/storage_entry.rs
grep -n 'osaka_opcode_transition_height\|eoa_code_transition_height\|base_fee_burn_transition_height\|align_evm_transition_height' \
  chains/conflux/repos/conflux-rust/crates/config/src/configuration.rs

# --- live: deferred execution, visible without source
rpc cfx_getStatus '[]' $C     # epochNumber vs latestState (-4/-5) vs latestFinalized (-200ish)
rpc eth_blockNumber '[]'      # == latestState, NOT epochNumber
# --- live: stateRoot / receiptsRoot are the DEFERRED roots (finding 1)
rpc eth_getBlockByNumber '["0x94230d0",false]' | grep -o '"stateRoot":"[^"]*"'
rpc cfx_getBlockByEpochNumber '["0x94230d0",false]' $C | grep -o '"deferredStateRoot":"[^"]*"'
# --- live: one transaction, transactionsRoot = keccak256("") (finding 2)
rpc eth_getBlockByNumber '["0x94230d0",true]' | python3 -c \
  'import sys,json;b=json.load(sys.stdin)["result"];print(len(b["transactions"]),b["transactionsRoot"])'
#   -> 1 0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470
# --- live: two base fees in one block (finding 9)
rpc eth_getBlockByNumber "[\"$B\",false]" | grep -o '"baseFeePerGas":"[^"]*"'          # 0x4a817c800
rpc cfx_getBlockByEpochNumber "[\"$B\",false]" $C | grep -o '"baseFeePerGas":"[^"]*"'  # 0x3b9aca00
# --- live: the burn share, straight out of a receipt (finding 9)
rpc eth_getTransactionReceipt '["0x8afdf9bde251215b905cd5e10b60a316f167c4a46671ad9e099c6f0a117a0205"]' \
  | python3 -c 'import sys,json;r=json.load(sys.stdin)["result"];print(int(r["burntGasFee"],16)/int(r["gasFee"],16))'
#   -> 0.3684248213
# --- live: opcode environment (findings 6, 7)
for d in 435f5260205ff3 425f5260205ff3 445f5260205ff3 485f5260205ff3 465f5260205ff3 60011e5f5260205ff3; do
  rpc eth_call "[{\"data\":\"0x$d\"},\"$B\"]"; done
#   NUMBER=0x9423189 (B+1!)  TIMESTAMP=0x6a905a61  PREVRANDAO=0x0  BASEFEE=0x4a817c800
#   CHAINID=0x406  CLZ(1)=0xff
# --- live: BLOCKHASH window and the stale current-height read (finding 6)
for n in 155333001 155333000 155267466 155267465; do
  rpc eth_call "[{\"data\":\"0x63$(printf '%08x' $n)405f5260205ff3\"},\"$B\"]"; done
#   -> hash(155267465) ; hash(155333000) ; hash(155267466) ; 0x00..00
# --- live: 48 KiB code limit and 400 gas/byte deposit (finding 8)
for s in 00c000 00c001; do
  rpc eth_call "[{\"data\":\"0x62${s}6000f3\",\"gas\":\"0x1312d00\"},\"$B\"]" | head -c 70; echo; done
#   49152 -> 49152 bytes returned ; 49153 -> "execution reverted: Out of gas"
#   slope: binary-search the `gas` field -> 453194 for 1000 bytes, 853292 for 2000
# --- live: no code anywhere it matters (findings 11, 12)
for a in 0888000000000000000000000000000000000006 0000F90827F1C53a10cb7A02335B175320002935 \
         000F3df6D732807Ef1319fB7B8bB8522d0Beac02; do rpc eth_getCode "[\"0x$a\",\"$B\"]"; done   # all 0x
# --- live: phantom transactions, gasUsed 0x0 with 2 txs (finding 10)
rpc eth_getBlockByNumber '["0x94230d9",true]' | python3 -c \
  'import sys,json;b=json.load(sys.stdin)["result"];print(b["gasUsed"],[(t["from"],t["type"],t["r"],t["v"]) for t in b["transactions"]])'

# --- schema
tools/.venv/bin/python -c "import yaml;yaml.safe_load(open('chains/conflux/chain.yaml'))"
tools/.venv/bin/python tools/verify.py 2>&1 | sed -n '/^conflux/,/^$/p'
```
