# Taraxa — what this row teaches

Pinned: `Taraxa-Project/taraxa-node` **v1.14.1** (`a0e85fe3`, 2026-02-16, the newest
non-prerelease GitHub release) with `Taraxa-Project/taraxa-evm` as a **git submodule**
at the commit that tag records, `6c7e5338` — whose `git describe --tags` is
**`v1.8.21-1195-g6c7e5338`**, i.e. go-ethereum **v1.8.21** (November 2018) plus 1,195
commits. Chain id **841**. Baseline fork **constantinople**, measured from the
instruction table and the gas constants, not from the chain's fork names.

**Evidence path taken: source only — 100% `src:`, 0% `src_live:`.** This is the first
row in the dataset with a pinned client and **no reachable network at all**, and that
is finding 1 rather than a footnote.

---

## 1. The mirror image of Hyperliquid: full source, no network

Hyperliquid fails the *source* gate and is answered entirely with live probes. Taraxa
fails the *network* gate and can only be answered with source. Every endpoint the
chain's own documentation still publishes is gone:

| target | result, 2026-08-27 |
|---|---|
| `rpc.mainnet.taraxa.io` (docs.taraxa.io still names it) | **SERVFAIL / no record** at 1.1.1.1, 8.8.8.8 and 9.9.9.9 |
| `ws.mainnet.taraxa.io`, `rpc.testnet.taraxa.io`, `explorer.mainnet.taraxa.io` | same — the whole `*.mainnet.taraxa.io` and `*.testnet.taraxa.io` space is unresolvable |
| `taraxa.io` itself | resolves — to `ext-sq.squarespace.com` |
| `tara.to` (the block explorer) | HTTP 301, `X-Served-By: Namecheap URL Forward`, `Location: https://yield.reviews`. A **parked redirect to an unrelated site**; its HTTPS port does not accept connections |
| `https://841.rpc.thirdweb.com` | `eth_chainId` -> `0x349`, `net_version` -> `841`, then `eth_blockNumber` / `eth_gasPrice` / `eth_getBlockByNumber` all fail with an internal error — it answers from its own chain registry and has **no upstream node** |
| `taraxa.blockpi.network` | `{"error":"unknown host"}` |
| `taraxa.drpc.org` / `rpc.ankr.com/taraxa` / `1rpc.io/tara` | 404 / 403 / `unknown network` |

The trap here is specific and worth naming: **a chain-id echo is not a liveness
probe.** thirdweb returns the right `chainId` and the right `net_version` for chain
841 and would satisfy a naive "is the endpoint up" check, while being unable to
answer a single question about state. Any future pass that tries to re-probe this row
must check a *height*, not an id.

**Is chain 841 still producing blocks? Not established.** The chain demonstrably
produced mainnet blocks — Cacti activates at period 24,350,801 and shipped in v1.14.0
in January 2026 — so it is not `prelaunch`, and nothing found says it stopped, so
calling it `halted` would claim more than the evidence supports. `chain.live: true`
in this row is an assertion from *absence of contrary evidence*, and the file says so
in `chain.note` rather than leaving it silent. What would settle it: one successful
`eth_blockNumber` against any node — a validator's own, a community endpoint, or a
node synced from the pinned client — or a second observation days apart showing the
height advancing.

Everything below is "what `taraxa-node` v1.14.1 would do". None of it has been checked
against what validators run, which is exactly the gap `src_live:` exists to close.

---

## 2. Ordering commits before execution, and the block that commits it carries the state of *five periods ago*

Three layers, and the executed chain is none of them.

- **The DAG.** Twenty eligible proposers produce blocks concurrently; each names one
  pivot parent and up to sixteen tips. `PivotTree::getGhostPath` walks the pivot tree
  by heaviest subtree, ties broken by smaller hash.
- **PBFT.** A proposer picks an **anchor** off that path —
  `ghost[ghost.size() - 1 - ghost_path_move_back]`, or `ghost[dag_blocks_size - 1]`
  when the path exceeds 50 — and `Dag::computeOrder` produces a total order over every
  non-finalized DAG block that can reach the anchor, by reverse-post-order DFS with
  children sorted by hash. The result is committed as one 32-byte `order_hash`:
  `sha3(rlp(list of DAG block hashes))`. If the order overflows the period gas limit,
  `findClosestAnchor` moves the anchor *back* along the ghost path until it fits.
- **The final chain.** One Ethereum-shaped block per period, derived.

The PBFT block a committee votes on contains `prev_blk_hash`, `anchor_hash`,
`order_hash`, and `final_chain_hash` — and that last field is
`blockHeader(N - delegationDelay)->hash`, with `delegation_delay: 0x5` on mainnet.
**The block that commits period N's ordering commits the executed result of period
N-5 and nothing about period N's own state.** Deferred execution, like Monad — but
Monad's three-height lag is a stated design decision, whereas Taraxa's five-height lag
*falls out of the DPoS delegation delay*: the same genesis constant that decides when a
delegation becomes effective decides how stale the state commitment is. Cornus changed
the committed value from period N-5's **state root** to its **block hash**.

The block hash a client sees is not the one consensus agreed on. `appendBlock`
computes `sha3(header->ethereumRlp())` over a **fabricated 15-field pre-London
Ethereum header** — `difficulty` 0, `mixHash` 0, `nonce` empty, no `baseFeePerGas`.
The PBFT block has a different hash over different fields, and no `eth_*` method ever
returns it. Two hashes name every height; only one is voted on.

## 3. The duplicate-transaction question, and a **third** answer

Because proposers draw from their own mempools with no coordination — `packTrxs` just
takes the top of the local pool — the same transaction sits in several DAG blocks as
the *normal* case. Taraxa resolves it **before execution, not during it**. When the
anchor is fixed, `pushCertVotedPbftBlockIntoChain_` walks the ordered DAG blocks and
builds the period's transaction list through a `std::unordered_set<trx_hash_t>`,
keeping only the first occurrence, and then asks the transaction manager for the
non-finalized subset of *that*. The duplicate is never a candidate: not skipped, not
charged, not given a receipt, not in the transactions trie twice.

Three chains, three mechanisms, and they are genuinely different:

| chain | what happens to the duplicate | who pays |
|---|---|---|
| **Conflux** | executes, hits `check_nonce` -> `TxDropError::OldNonce` -> `TransactionStatus::Skipped`, then the eSpace RPC **erases every trace** — no receipt, no index, indistinguishable from never submitted | nobody |
| **Taraxa** | **never enters the ordered list** — deduplicated at period assembly. The DAG block containing it is still fully present in the period data, so the duplicate is visible *in the DAG* and absent *from the executed list* | nobody |
| **Autonomys** | an invalid transaction **poisons the whole bundle**, dropping every valid co-passenger, and **slashes the operator** | the operator, automatically |

The observable difference between Conflux and Taraxa is small but real: Conflux hides
the duplicate at the RPC layer *after* ordering it, Taraxa declines to order it. A
DAG-block-level explorer sees the duplicate on Taraxa and an eSpace client does not
see it on Conflux.

## 4. Duplicate inclusion is paid for in *rewards*, and the rule changed at Aspen

Taraxa does have the explicit first-includer scheme, and it sits at the far mild end
of the Autonomys spectrum — the worst outcome of losing a race is forgone revenue.

`BlockStats::initFeeByTrxHash` builds `hash -> gasPrice * gasUsed` for every
transaction in the period. `addTransaction(hash, validator)` credits that fee to the
validator whose DAG block is the **first in the period's DAG order** to contain the
hash, and then **erases the map entry**, so a second claimant finds nothing and gets
nothing. Then:

- **Before Aspen part one** (`processDagBlocks`): a DAG block earned its share of the
  block reward *only if it contributed at least one unique transaction*. A block full
  of duplicates earned **nothing at all** — neither fees nor block reward.
- **From Aspen part one** (`processDagBlocksAspen`): that test was replaced. The block
  reward now goes to every DAG block whose **VDF difficulty equals the minimum
  difficulty** among the period's DAG blocks; fees still go strictly to the first
  includer. The penalty for losing a race softened from "you get nothing" to "you get
  the block share but no fees".

Nobody is slashed and nobody is charged. Note the consequence for the EVM:
**`block.coinbase` does not identify who was paid.** The PBFT beneficiary receives at
most `max_block_author_reward` = 5% of the block reward and **none** of the transaction
fees.

## 5. Ordered-but-invalid: included, charged, `status: 0` — and it can take your whole balance

There is no skip path. `EVM.Main` returns a `ConsensusErr` for nonce-too-low,
insufficient balance for gas, uncovered intrinsic gas, and insufficient balance for the
top-level transfer, and `finalize_` turns
`r.code_err.empty() && r.consensus_err.empty()` straight into the receipt's status bit.
All four land in the block, the transactions trie, the receipts trie and
`eth_getTransactionReceipt`. Three of them are charged the **full gas limit**
(`consensusErr(ret, gas_cap, err)`).

The fourth is worse. If the sender cannot cover `gas_limit * gas_price`, Taraxa does
not reject — it computes `available_funds_gas = balance / gas_price`, subtracts
`available_funds_gas * gas_price` (everything but sub-gas-price dust), reports
`gasUsed = available_funds_gas`, and from Cornus bumps the nonce to `tx.nonce + 1`.
**An underfunded transaction is executed and confiscates essentially the sender's
entire balance.** Mainnet's validity rules make this state unreachable. Conflux arrives
at the same place by a different route (`actual_gas_cost = min(gas_cost, balance)`), so
this is now a two-chain class: *DAG chains that decide inclusion before balances are
known end up confiscating rather than rejecting.*

And the nonce rule is not mainnet's at all. The nonce-too-high check is present in the
source but **commented out**, above the line "Nonce skipping is permanently enabled
now. Uncomment this part to have strict nonce ordering". Only `tx.nonce <
account.nonce` is rejected, and on success the account nonce is **set to
`tx.nonce + 1`, not incremented**. A transaction with nonce 1,000,000 from an account
at nonce 3 executes, and nonces 3 through 999,999 are burned forever. "An account's
nonce equals the number of transactions it has sent" is false here, and because
`create_1` derives the address from `tx.Nonce`, **a deployer can choose its contract
address by choosing a nonce**.

## 6. EIP-1283 without EIP-1706 — the 2,300-gas stipend can write storage

The single most dangerous fact in the row. `gasSStore` is EIP-1283 net gas metering
verbatim, comment block and all: a no-op SSTORE costs 200, a write to an
already-dirty slot costs 200, refunds are 15,000 / 4,800 / 19,800. Ethereum **removed
EIP-1283** in the Petersburg emergency fork (EIP-1716), two days before Constantinople
was due, precisely because 200-gas SSTOREs make the CALL stipend state-modifying, and
replaced it at Istanbul with EIP-2200 and its `gas <= 2300` sentry.

That sentry is not here, and `CallStipend` is still 2,300. So on Taraxa the invariant
every Solidity reentrancy audit rests on — *"a `transfer()` or `send()` recipient
cannot change state"* — is **false**. It fails silently: no revert, no error, no signal
to the caller. Taraxa is running an EIP that Ethereum mainnet never shipped.

## 7. Transient storage lives at four opcodes, two of which are `INVALID` on mainnet

The base Californicum table binds `opTload`/`opTstore` to **`0xb3` and `0xb4`** — the
numbers from the abandoned 2020 draft of EIP-1153. Cacti's `fixEIP1153` **adds** `0x5c`
and `0x5d`; it does not remove the draft pair, and `opcodes.go` still lists both under
the display names `TLOAD`/`TSTORE`. From Cacti onward all four are live and aliased
onto the same transient store. On mainnet `0xb3`/`0xb4` are invalid: a disassembler
prints `INVALID`, a static analyser treats the block as unreachable, and a contract
carrying `0xb3` in a data region behaves differently here. (`TSTORE`'s gas function is
literally `gasTLoad`.)

The same pattern hits BLS12-381 harder. Ficus installed the **pre-2024 draft**
EIP-2537 layout (`0x0b` G1ADD, `0x0c` G1MUL, `0x0d` G1MULTIEXP, `0x0e` G2ADD, `0x0f`
G2MUL, `0x10` G2MULTIEXP, `0x11` PAIRING, `0x12`/`0x13` the map-to-curve pair). Cacti
replaced it with the **final** layout and deleted `0x12`/`0x13`. So a contract deployed
before Cacti that calls `0x0f` expecting G2MUL now reaches PAIRING_CHECK; `0x11`
expecting PAIRING now reaches MAP_FP2_TO_G2; and `0x12`/`0x13` are now empty accounts,
so calls to them **succeed with no output**. Gas throughout is the draft schedule —
pairing 115,000 + 23,000/pair against mainnet's 37,700 + 32,600.

## 8. A post-quantum precompile that returns **zero for valid** and wants an ABI selector

`0x...fa1c` is FN-DSA-512 (Falcon-512) verification — the only post-quantum signature
verifier in this dataset. Two things make it unlike every other precompile anywhere:

1. **It returns `bytes32(0)` for a VALID signature and `bytes32(1)` for an invalid
   one.** The source comment says so. `success && result != 0` accepts forgeries and
   rejects valid signatures — the exact inverse of `ecrecover`, `P256VERIFY` and every
   other verifier on every chain here.
2. **It requires a 4-byte function selector**, `0xde8f50a1` for
   `verify(bytes,bytes,bytes)`, followed by standard ABI head/tail encoding. No
   mainnet precompile parses a selector.

Failure is signalled two different ways depending on how you got it wrong: a bad
selector **errors** (the CALL returns 0), a bad signature **succeeds** and returns 1.
Gas is 1,465 + 6/word — roughly 1,760 gas for a 666-byte signature and an 897-byte
key, cheaper than `ecrecover`, for a lattice verification.

## 9. A precompile and a system contract at the same address, and the bytecode never runs

`0x...00FE` is the DPoS contract. The logic is native Go registered through
`RegisterPrecompiledContract` — and from Aspen part one, `applyHFChanges` **also writes
real EVM bytecode into that account** (`AspenDposImplBytecode`, then
`CornusDposImplBytecode`). So `EXTCODESIZE(0xFE)` is non-zero and `EXTCODEHASH(0xFE)`
is a real hash, while `EVM.Call` dispatches `if precompiled != nil {...} else if
len(code) != 0 {...}` — the precompile always wins and the bytecode is decoration for
explorers and ABI tooling.

This is a direct counterexample to SCHEMA.md's precompile/system-contract boundary: the
usual test, *"does EXTCODESIZE return non-zero"*, gives the **wrong answer** here. The
slashing contract at `0x...00EE` is the control — same mechanism, no bytecode.

And the slashing contract is itself unusual: `commitDoubleVotingProof` takes two
conflicting PBFT votes and jails a validator for `jail_time` periods (163,459 at
Magnolia, 252,000 from Cacti), and `getJailBlock` / `getJailedValidators` are readable
by **any contract** for 5,000 gas. Consensus misbehaviour is an EVM-visible, queryable
fact — the opposite end of the spectrum from Autonomys, where slashing is automatic and
invisible to the EVM. Note it is a *jailing*, not a stake burn.

## 10. Cornus installed thirteen third-party contracts as protocol bytecode

`OpPrecompiles` — the file's own comment calls it "OP Stack Specification", borrowed
from OP's preinstalls list — maps address to hex bytecode, and `applyHFChanges` does
`SetCode` on each at the Cornus fork: Safe, SafeL2, MultiSend, MultiSendCallOnly,
SafeSingletonFactory, Multicall3, Create2Deployer, CreateX, Arachnid's deterministic
deployment proxy `0x4e59b448...956C`, Permit2, and ERC-4337 v0.6.0 and v0.7.0
EntryPoint + SenderCreator. These are normally deployed *by users* through a
deterministic factory; here their code is a consensus fact that no transaction paid for
and no receipt records. Their nonces are **not** set, so unlike OP's preinstalls they
remain nonce-0 accounts with code.

## 11. A gas *estimate* is a block-validity rule

`DagManager::verifyBlock` rejects a DAG block unless its declared `gas_estimation`
field **exactly equals** `trx_mgr_->estimateTransactions(block_txs, proposal_period)`.
For a transaction whose gas limit is at most `kEstimateGasLimit` (200,000) the estimate
is just its declared limit; above that it is the `gas_used` of a **speculative
execution** against the state at the proposal period. So the output of an
`eth_call`-style dry run is consensus-critical: two implementations that disagree about
how much gas a speculative execution consumes reject each other's DAG blocks. Most
chains treat estimation as a convenience API with no consensus weight at all.

## 12. Smaller things that will still bite

- **`block.gaslimit` has been wrong since Cornus.** `finalize_` and `appendBlock` use
  `kBlockGasLimit`, initialised once from `genesis.pbft.gas_limit` = **315,000,000**,
  while block packing since Cornus uses `cornus_hf.pbft_gas_limit` =
  **2,100,000,000**. The header under-reports the real limit by 6.7x, and
  **`gasUsed > gasLimit` is a reachable state** in a Taraxa header.
- **`block.prevrandao` is a constant zero.** `0x44` is DIFFICULTY, not PREVRANDAO, and
  `BlockHeader::difficulty()` is a static `ZeroU256`. Any contract using it for entropy
  reads 0, silently.
- **`BLOCKHASH` is honest** — the negative result. `opBlockhash` is unmodified geth 1.8
  and its `get_hash` is `FinalChain::blockHash`, so `BLOCKHASH(number-1) ==
  parentHash`. The DAG is entirely invisible to it: DAG block hashes are not
  addressable and never enter the 256-block window.
- **`block.number` counts PBFT periods.** A period anchoring 50 DAG blocks and 900
  transactions is one `block.number`; a period whose proposer found no new DAG blocks
  proposes a **null anchor** and still produces a block, empty, with an unchanged state
  root. Empty blocks mean "the DAG produced nothing new", not "nobody transacted".
- **`eth_getTransactionByHash` has no null guard for the DAG-but-not-finalized case.**
  `get_transaction_receipt` correctly returns null (so there is *no* early receipt, the
  opposite of MegaETH's `0xffff...ff` sentinel). But `get_transaction` calls
  `get_trx(h)` first — which reads the `transactions` column where DAG-included and
  pooled transactions live — and on a hit dereferences `*loc` and
  `*final_chain->blockHash(loc->period)` with no check, while `transactionLocation`
  returns `std::nullopt` for anything not yet finalized. This is a **source reading
  only**; with no reachable RPC, what a release build actually returns is unspecified.
- **`v` is returned raw.** `Transaction::toJSON` emits the recovery id (`0x0`/`0x1`)
  where the signed RLP carries 1717/1718. Any client that rebuilds the transaction from
  RPC fields and re-hashes it gets a **different hash**.
- **Receipts carry no `effectiveGasPrice` and no `type`.**
- **No EIP-2718 at all**, and the source says so: the RLP parse failure message reads
  "Use legacy transactions because typed transactions aren't supported yet."
- **Reward minting moves balances with no transaction, receipt, log or trace**, and
  exposes the amount as a non-standard `totalReward` header field. An indexer
  reconstructing balances from receipts will drift from `eth_getBalance` every block.
- **A failed precompile keeps its remaining gas.** `EVM.Call` zeroes gas on error only
  when `precompiled == nil`; upstream geth zeroes it for any non-revert error.
- **Gas is Constantinople-era.** Non-zero calldata 68 (not 16), bn256 at Byzantium
  prices (500 / 40,000 / 100,000+80,000), MODEXP at EIP-198 pricing, no EIP-2929
  warm/cold anywhere, refund cap `gas_used / 2`, SELFDESTRUCT still refunds 24,000, and
  **no EIP-3541** — runtime code beginning with `0xEF` deploys here and nowhere else in
  this dataset.

---

## Not established here

- **Whether chain 841 is producing blocks.** See finding 1. No probe succeeded; the row
  says so rather than asserting it quietly.
- **Whether validators run v1.14.1.** The whole point of `src_live:` is to catch the
  gap between the pinned tag and the deployed one, and this row cannot. In particular
  the Cacti activation period (24,350,801) is read from the repo's mainnet genesis, not
  from a chain that confirmed it.
- **Whether `eth_getTransactionByHash` actually crashes, returns garbage, or is saved
  by hardened-libstdc++ assertions** for a DAG-but-unfinalized transaction. The missing
  null check is plain in the source; the observable behaviour is not.
- **Whether a below-floor-gas-price transaction can reach execution.**
  `verifyTransaction` enforces the 1 gwei floor and the 31.5M gas cap at the *network*
  admission layer (`transaction_packet_handler`, `dag_sync_packet_handler`), and
  neither check is inside the deterministic state transition — so the consensus
  consequence of a DAG block that somehow contains one is not settled here.
- **Whether the Cacti BLS12-381 renumbering broke a deployed contract.** No mainnet
  contract inventory was possible without an RPC.
- **The Aspen part-two yield curve and the supply cap.** Recorded as fork notes only;
  the economics were not traced through `yield_curve.go`.
- **`taraxa-vdf` and `taraxa-vrf`.** The two other submodules were not cloned; VDF
  difficulty appears in this row only where the reward rule reads it.

---

## Re-verify

```sh
# The pins. taraxa-evm is a SUBMODULE, not an independently released tag —
# the correct pin is the commit the node's release tree records.
git clone --depth 1 --branch v1.14.1 --single-branch \
    https://github.com/Taraxa-Project/taraxa-node chains/taraxa/repos/taraxa-node
git -C chains/taraxa/repos/taraxa-node rev-parse HEAD
# -> a0e85fe31eb03573cd92c165a5f81035cec9907e
git -C chains/taraxa/repos/taraxa-node ls-tree HEAD submodules/taraxa-evm
# -> 160000 commit 6c7e5338b22d5e596cc2365a88d1f94840e1ee1b  submodules/taraxa-evm

git clone --filter=blob:none --no-checkout \
    https://github.com/Taraxa-Project/taraxa-evm chains/taraxa/repos/taraxa-evm
git -C chains/taraxa/repos/taraxa-evm checkout 6c7e5338b22d5e596cc2365a88d1f94840e1ee1b
git -C chains/taraxa/repos/taraxa-evm describe --tags
# -> v1.8.21-1195-g6c7e5338     <- the go-ethereum fork point
```

```sh
cd chains/taraxa/repos

# The network is gone. This is the finding, so reproduce it.
dig +short @1.1.1.1 rpc.mainnet.taraxa.io          # -> (empty)
dig +short @8.8.8.8 rpc.mainnet.taraxa.io          # -> (empty)
dig +short @1.1.1.1 taraxa.io                      # -> ext-sq.squarespace.com. 198.185.159.144 ...
curl -sI -m 15 http://tara.to | head -8            # -> 301, X-Served-By: Namecheap URL Forward,
                                                   #    Location: https://yield.reviews
# A chain-id echo is NOT a liveness probe:
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
  https://841.rpc.thirdweb.com                     # -> {"result":"0x349"}
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' \
  https://841.rpc.thirdweb.com                     # -> internal error: no upstream
```

```sh
# EIP-1283 with no EIP-1706 sentry. The grep that returns NOTHING is the finding.
sed -n '/^func gasSStore/,/^}/p' taraxa-evm/core/vm/gas.go | grep -c 2300   # -> 0
grep -n 'NetSstoreDirtyGas\|CallStipend' taraxa-evm/core/vm/constants.go
# -> NetSstoreDirtyGas uint64 = 200 ; CallStipend uint64 = 2300

# Transient storage at four opcodes.
grep -n 'TLOAD_OLD\|TSTORE_OLD\|TLOAD \|TSTORE ' taraxa-evm/core/vm/opcodes.go
# -> TLOAD_OLD 0xb3, TSTORE_OLD 0xb4, TLOAD 0x5c, TSTORE 0x5d
grep -n 'TLOAD_OLD\|TSTORE_OLD' taraxa-evm/core/vm/jump_table.go   # base table binds the DRAFT pair
sed -n '1,17p' taraxa-evm/core/vm/eips.go                          # fixEIP1153 ADDS, never removes

# The BLS12-381 renumbering, side by side.
sed -n '/PrecompiledContractsFicus = /,/^}/p' taraxa-evm/core/vm/contracts.go
sed -n '/PrecompiledContractsCacti = /,/^}/p' taraxa-evm/core/vm/contracts.go

# Falcon-512: zero means VALID.
grep -n 'returns bytes32(0) if signature is valid' -A 6 taraxa-evm/core/vm/contracts.go
grep -n 'falcon512MethodSignature' taraxa-evm/core/vm/contracts.go   # -> 0xde8f50a1

# Nonce skipping and balance confiscation.
grep -n 'Nonce skipping is permanently enabled' -B 8 taraxa-evm/core/vm/evm.go
grep -n 'available_funds_gas' taraxa-evm/core/vm/evm.go

# Constantinople-era gas.
grep -n 'TxDataNonZeroGas\|Bn256AddGas\|Bn256PairingPerPointGas\|ModExpQuadCoeffDiv' \
    taraxa-evm/core/vm/constants.go
sed -n '/GasTableCalifornicum = GasTable{/,/}/p' taraxa-evm/core/vm/gas_table.go
grep -n 'func gasSLoad' -A 3 taraxa-evm/core/vm/gas.go     # no warm/cold anywhere

# Precompile shadows bytecode at 0xFE.
grep -n 'dpos_contract_address' taraxa-evm/taraxa/state/contracts/dpos/precompiled/dpos_contract.go
grep -n 'SetCode(dpos_sol' taraxa-evm/taraxa/state/state_transition/state_hardforks.go
grep -n 'if precompiled != nil' -A 10 taraxa-evm/core/vm/evm.go

# Thirteen protocol-installed third-party contracts.
grep -n 'common.HexToAddress\|^\s*//' \
    taraxa-evm/taraxa/state/state_transition/op_stack/precompiles.go | cut -c1-70
```

```sh
# Ordering: anchor selection, total order, order hash, and the N-5 state commitment.
grep -n 'getGhostPath\|findClosestAnchor\|calculateOrderHash' \
    taraxa-node/libraries/core_libs/consensus/src/pbft/pbft_manager.cpp | head
sed -n '/^bool Dag::computeOrder/,/^}/p' \
    taraxa-node/libraries/core_libs/consensus/src/dag/dag.cpp
sed -n '/FinalChain::finalChainHash/,/^}/p' \
    taraxa-node/libraries/core_libs/consensus/src/final_chain/final_chain.cpp
grep -n 'delegation_delay' \
    taraxa-node/libraries/cli/include/cli/config_jsons/mainnet/mainnet_genesis.json   # -> 0x5

# Duplicate dedup happens BEFORE execution.
grep -n 'trx_set.insert' -B 6 -A 6 \
    taraxa-node/libraries/core_libs/consensus/src/pbft/pbft_manager.cpp

# First-includer fee, and the Aspen rule change.
sed -n '/void BlockStats::processDagBlocks(/,/^}/p' \
    taraxa-node/libraries/core_libs/consensus/src/rewards/block_stats.cpp
sed -n '/void BlockStats::processDagBlocksAspen(/,/^}/p' \
    taraxa-node/libraries/core_libs/consensus/src/rewards/block_stats.cpp

# Ordered-but-invalid gets a receipt: status is (no code error AND no consensus error).
grep -n 'r.code_err.empty() && r.consensus_err.empty()' -B 4 \
    taraxa-node/libraries/core_libs/consensus/src/final_chain/final_chain.cpp

# The stale gasLimit.
grep -n 'kBlockGasLimit(config.genesis.pbft.gas_limit)\|header->gas_limit = kBlockGasLimit' \
    taraxa-node/libraries/core_libs/consensus/src/final_chain/final_chain.cpp
grep -n 'pbft_gas_limit\|"gas_limit"' \
    taraxa-node/libraries/cli/include/cli/config_jsons/mainnet/mainnet_genesis.json
# -> pbft.gas_limit 0x12C684C0 (315,000,000) vs cornus_hf.pbft_gas_limit 0x7d2b7500 (2,100,000,000)

# A gas estimate is a block-validity rule.
grep -n 'IncorrectTransactionsEstimation' -B 6 \
    taraxa-node/libraries/core_libs/consensus/src/dag/dag_manager.cpp

# Legacy-only envelope, in the client's own words.
grep -n 'typed transactions' \
    taraxa-node/libraries/types/transaction/src/system_transaction.cpp

# The missing null guard.
sed -n '/optional<LocalisedTransaction> get_transaction(const h256& h)/,/^  }/p' \
    taraxa-node/libraries/core_libs/network/rpc/eth/Eth.cpp
```

```sh
# Validate the row.
tools/.venv/bin/python -c "import yaml;yaml.safe_load(open('chains/taraxa/chain.yaml'))"
tools/.venv/bin/python tools/verify.py 2>&1 | sed -n '/^taraxa/,/^$/p'
```
