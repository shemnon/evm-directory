# Hedera — what this row teaches

**Client (consensus):** `hiero-ledger/hiero-consensus-node` — the org rename is real, and
`hashgraph/hedera-services` now redirects here. Pinned at `v0.76.1`, commit
`cd5a2ad0946e1950c64f5a76754a6cd3ee29793e`. **Mainnet runs a version with no public tag:**
every record file carries `hapi_version: 0.76.2` and no `v0.76.2` tag exists; `v0.76.1` is
the newest released `vX.Y.Z`.

**Companion (the entire `eth_*` API):** `hiero-ledger/hiero-json-rpc-relay` at `v0.78.4`,
commit `1701d192333ca19c3cfd630a4e6ababcdf6cd001`. The old
`hashgraph/hedera-json-rpc-relay` is a 404. This is a **separate process in a separate
repository, versioned independently**, that synthesises Ethereum JSON-RPC out of Hedera
record data fetched over HTTP from a third component (the mirror node). The live endpoint
reports `web3_clientVersion` = `relay/0.78.4` — the relay's version, from the component that
executes nothing.

**EVM:** `org.hyperledger.besu:evm:25.2.2` consumed as an **ordinary Maven dependency**.
This is the MegaETH pattern — semantics inherited as a *library*, not as a diff against a
client — with Besu instead of revm, and with no upstream chain configuration inherited at
all. `V067Module` calls `MainnetEVMs.registerCancunOperations` and
`MainnetPrecompiledContracts.populateForCancun` and constructs the EVM with
`EvmSpecVersion.CANCUN`.

**Live probe:** `https://mainnet.hashio.io/api`, `eth_chainId` → `0x127` (295), pinned at
**block 99380446** (`0x5ec6cde`), observed 2026-08-28. That block was chosen because it
contains a transaction; most Hedera blocks are EVM-empty. Secondary reference:
`https://mainnet-public.mirrornode.hedera.com/api/v1`, which is what the relay itself reads.

**Baseline fork:** `cancun`. **Role:** `independent`, `equivalence: behavioural`.
**Lineage upstream:** `ethereum` — not a fork of any Ethereum client.

**Evidence path:** `source`, with a hard split. Ordering, fees, duplicates, expiry and
opcode semantics are `src:` into the consensus node. Blocks, hashes, roots, header fields,
tag semantics and `eth_getCode` overrides are `src:` into the **relay**, because that is
where they are decided. Roughly a third of the row's live claims are cross-checked against
the mirror node's own 48-byte objects, because the `eth_*` view of them is lossy by
construction.

---

## 1. Ordering commits before execution, absolutely, and there is no block to commit it in

Nodes gossip *events* (transactions plus two parent hashes); every node independently runs
virtual voting over the resulting DAG.
`ConsensusImpl.setIsConsensusTrue` gives each event the **median** of the times the unique
famous witnesses first saw it; `ConsensusSorter.sort` totally orders the round; then
`setConsensusOrder` pushes timestamps forward so every *transaction* gets a strictly
increasing one, at least `MIN_TRANS_TIMESTAMP_INCR_NANOS` = **1000 ns** after the last.

None of that looks at the transaction's content, payer, balance, nonce or gas.
`HandleWorkflow.handleRound` then walks the ordered rounds and calls
`handlePlatformTransaction` one at a time, on one thread, using the platform-assigned
consensus time (HIP-993). **Execution is sequential and deterministic; the parallelism is
all in gossip and voting, which happen before and independent of it.**

There is no proposer, no leader, and no block. A "block" is manufactured later, while the
node is *already executing*: `BlockRecordManagerImpl.willOpenNewBlock` returns true whenever
`floor(consensusSecond / 2)` increments. `block.number` counts two-second buckets since
genesis. No quorum ever votes on one.

Contrast with Monad, the dataset's other decoupled-execution row: Monad commits a
transaction *list* and agrees its state root three heights later. Hedera has no state root
to agree — see finding 5.

## 2. The central question: billed and skipped — a fate no other row has

`DispatchProcessor.processDispatch` has exactly two arms, and the split is by **who was
negligent**, not by what failed:

```
if (!validation.creatorDidDueDiligence()) chargeCreator(dispatch, validation);
else { fees = chargePayer(...); if (!alreadyFailed(...)) tryHandle(...); }
```

- **`chargeCreator`** debits `dispatch.fees().networkFee()` from **the node account that
  submitted the transaction**, and the payer pays nothing. This arm covers a transaction
  whose valid-start window expired before it reached consensus (`getExpiryError` re-runs
  `checkTimeBox` against `consensusNow`), an invalid payer signature, and every ingest-level
  due-diligence failure. **The node eats the cost of having relayed something consensus
  found unusable.**
- Otherwise `chargePayer` runs **first**, and `alreadyFailed` then decides whether the
  handler runs at all. A duplicate, an unaffordable service fee, an unauthorised payer or a
  failed signature check all short-circuit: **fees already taken, status set, handler never
  called.**
- If `tryHandle` *does* run and throws, the stack is rolled back and `chargePayer` is called
  again.

A record is always written — Hedera cannot drop a transaction that reached consensus. So
the answer is **charged a fee anyway, with a record, without executing**, which is distinct
from every existing row: not erased (Conflux, IOTA EVM, Artela, Rollkit), not
executed-and-failed-with-`status: 0` (Taraxa, Monad), not block-invalidating (Berachain),
not slashing (Autonomys). And Hedera adds a dimension none of them have: **the bill can land
on the submitting node instead of the sender.**

## 3. Duplicate transactions — the identity model is different, and the payer is billed for copies that never ran

**What makes two submissions "the same".** A HAPI transaction is identified by its
`TransactionID` = **(payer AccountID, transactionValidStart Timestamp)**. Nothing about the
contents enters the key: not the body, not the memo, not the amounts, not the signatures,
not the wrapped Ethereum payload. This is a *fundamentally different identity model* from
Ethereum's `(sender, nonce)` for replacement and `keccak(rlp(tx))` for lookup — and it cuts
both ways. Two byte-identical submissions with different valid-starts are **different**
transactions; two unrelated bodies sharing a payer and a valid-start instant are **the
same** one. Uniqueness holds only inside a sliding window:
`RecordCacheImpl.purgeExpiredReceiptEntries` drops history older than
`hedera.transaction.maxValidDuration` (**default 180 s**) behind the consensus clock.

**Duplicates are the designed-for case.** Hedera's own SDKs submit the same signed
transaction to several nodes for reliability, so a `TransactionID` reaching consensus more
than once is routine rather than exceptional.

**`RecordCacheImpl.hasDuplicate` is three-valued, and the two duplicate values behave
oppositely:**

| result | routed to | who pays | executes? |
|---|---|---|---|
| `NO_DUPLICATE` | normal path | payer, full fees | yes |
| `OTHER_NODE` | `getFinalPayerValidation(payer, DUPLICATE, …)` | **the payer**, `fees.withoutServiceComponent()` (node + network fee, service waived) | **no** |
| `SAME_NODE` | `newCreatorError(creatorId, DUPLICATE_TRANSACTION)` | **the submitting node**, `fees().networkFee()` | **no** |

**Which occurrence executes:** the first to receive a consensus timestamp. `hasDuplicate` is
evaluated during handling, in consensus order, against a cache populated by transactions
already handled. Every later occurrence is billed and skipped.

**Is the payer charged for duplicates? Yes.** `AppFeeCharging.charge` sets
`shouldWaiveServiceFee` when `result.duplicateStatus() == DUPLICATE` and charges
`fees.withoutServiceComponent()`. There is no state change, no EVM execution, no gas, and a
real HBAR debit. **`severity: high`, and silent.**

**Is the node penalised?** Only for *its own* duplicates. A node that duplicates itself is
charged the network fee (`chargeCreator`). A node that loses a race to another node is
**paid**: the `OTHER_NODE` path routes the node fee to `ctx.nodeAccountId()`, i.e. the node
that submitted the *losing* copy. Losing the race is revenue.

**Is a duplicate visible over `eth_*`? No — and this is the sharpest edge.** The Ethereum
transaction hash is written into the record **only** by `EthereumTransactionHandler.handle`
(and `handleThrottled`). A duplicate never reaches `tryHandle`, so its record carries no
`ethereum_hash`, so the mirror node has nothing to index it under, so
`eth_getTransactionByHash` and `eth_getTransactionReceipt` return **null for that occurrence
forever**. It is fully visible over HAPI and `/api/v1/transactions` with status
`DUPLICATE_TRANSACTION`, and completely invisible to every Ethereum tool. An operator
relaying Ethereum transactions sees an HBAR debit with no receipt to attribute it to.

**There are two different "duplicates" here, handled at two different layers.**
Re-broadcasting the *same signed Ethereum transaction* produces a **new** HAPI body with a
**new** valid-start, hence a **different** `TransactionID`, hence **not a Hedera duplicate at
all**. It is dispatched, reaches
`validateTrue(transaction.nonce() == parties.sender().getNonce(), WRONG_NONCE)` in
`TransactionProcessor`, and is charged there instead. So the same Ethereum transaction
submitted twice is billed twice, by two unrelated mechanisms, with two different status
codes, and only one of them knows the word "duplicate".

A node-local `DeduplicationCache` rejects duplicate IDs at ingest, but it is explicitly
**not in state** and lives on one node — it cannot touch the cross-node case, which is
precisely the case the SDKs create.

## 4. Finality: nothing to report, and that is the finding

Hashgraph is aBFT. A transaction is final the instant it receives its consensus timestamp;
there is no fork choice, no probabilistic head, no reorg, and no state that can be revisited.
There is no preconfirmation because none is needed, and nothing resembling MegaETH's
`0xffff…ff` receipt.

`finalized`, `safe`, `pending` and `latest` all returned **byte-identical** block objects at
the pinned block. For `finalized` and `safe` that is **honest** — unlike the three rows in
the last batch whose `finalized` tag misled. `pending` is the one that lies: there is no
pending-pool view.

What *does* vary is availability, not validity: the relay serves receipts out of the mirror
node, which ingests record files asynchronously, so a receipt is `null` for a while after
the transaction is already irreversible. **On Hedera a null receipt means "not ingested
yet", never "gone forever"** — the exact opposite of Conflux, IOTA EVM, Artela and Rollkit.

## 5. There is no Ethereum block header; `stateRoot` is a constant and `transactionsRoot` is the block hash

`BlockFactory.createBlock` assembles the header field by field in TypeScript:

- `stateRoot: constants.DEFAULT_ROOT_HASH` — the **empty MPT root**, hardcoded, identical in
  every block since genesis. Confirmed live at both `earliest` and head. Hedera's state is a
  virtual-map Merkle tree with no MPT root to report.
- `transactionsRoot: txArray.length === 0 ? DEFAULT_ROOT_HASH : blockHash` — when a block has
  transactions, **the transactions root *is* the block hash**. Confirmed live: at 99380446
  both are `0x961c4709…1d96`.
- `receiptsRoot` is the one root actually computed, and for an **empty** block it is 32 zero
  bytes — a *different* convention for "nothing" than `transactionsRoot` uses two fields
  earlier in the same header.
- `gasLimit` is a **lookup table in the relay** keyed on the record file's `hapi_version`:
  `>= 0.69.0 → 150,000,000`, else `30,000,000`. Live: `0x8f0d180` at head, `0x1c9c380` at
  `earliest`. The real limits are gas-per-**second** throttles
  (`contracts.maxGasPerSec`, `contracts.maxGasPerTransaction`), both defaulting to 15,000,000
  at the pinned tag.
- `excessBlobGas`, `blobGasUsed`, `parentBeaconBlockRoot` and `requestsHash` are **absent
  keys**, not zeros, on a chain whose baseline is Cancun.

## 6. The block hash is 48 bytes, and `BLOCKHASH(n-1) == parentHash` anyway

The real hash is the **SHA-384** running hash of the record file. Both sides truncate it to
its first 32 bytes: the relay in `toHash32`, the EVM in `ConversionUtils.ethHashFrom`, whose
javadoc says so outright. Verified live — the `eth_*` hash at 99380446 is a byte-exact
prefix of the mirror node's 48-byte hash, and `parentHash` likewise.

**Because both truncate identically, `BLOCKHASH(n-1)` does equal `parentHash`.** That is the
negative result, and it is worth stating explicitly: the EVM and the RPC agree, and both are
lossy views of the same object. Only 256 hashes are retained
(`blockRecord.numOfBlockHashesInState`), matching mainnet's window.

## 7. HBAR has eight decimals, and the 10^10 conversion is applied inconsistently at three layers

1. **Decode.** `EthTxData.getAmount()` is `value.divide(WEIBARS_IN_A_TINYBAR)` —
   `BigInteger.divide`, integer division, **no remainder check and no error**. Any value
   below 10^10 weibar silently becomes **zero** and the transaction still succeeds. The same
   division is applied to the offered gas price.
2. **EVM.** `HederaEvmTransaction.weiValue()` is `Wei.of(value)` where `value` is *already in
   tinybars*, and `DispatchingEvmFrameState.getBalance` is `Wei.of(tinybarBalance())`. So
   `msg.value`, `CALLVALUE`, `BALANCE` and `address(x).balance` are all **eight-decimal**.
   A contract comparing `msg.value` to `1 ether` can never be satisfied.
3. **RPC.** The relay multiplies back: `BigInt(balance) * TINYBAR_TO_WEIBAR_COEF`.

Confirmed live: `eth_getBalance(0x2abe…c45b)` = `0x452217627b6f413400` =
1,275,281,881,490,000,000,000 while the mirror node reports 127,528,188,149 tinybar for the
same account. The ratio is **exactly 10^10**, and neither answer carries a unit.

## 8. Calling any address in 0x01–0x2EE that is not a precompile burns all forwarded gas and reports success

`Version038AddressChecks.isSystemAccount` returns true for every long-zero address with
entity number `<= NUM_SYSTEM_ACCOUNTS = 750`. In `CustomMessageCallProcessor.start`, such an
address that is neither a Besu precompile nor a Hedera system contract reaches
`handleNonExtantSystemAccount`, which does **`frame.clearGasRemaining()`** and then returns
`PrecompileContractResult.success(Bytes.EMPTY)`.

The call **succeeds**, returns nothing, and consumes the child frame's entire gas allowance.
On mainnet the same call to, say, `0x0b` costs 100 gas. Sending value to such an address
halts with `INVALID_CONTRACT_ID` instead of creating the account.

**This also settles the P256VERIFY probe.** `eth_call` to `0x0100` with 160 zero bytes
returned `0x` — which the standard rubric reads as "EIP-7951 semantics present". It is not:
Besu 25.2.2's Cancun map has no `0x0100` entry, and the empty answer is the sink. Source
was needed to avoid getting this backwards.

## 9. `eth_getCode` at `0x167` returns `0xfe`, and the relay invented it

`ContractService.getCode` short-circuits on `address === constants.HTS_ADDRESS` and returns
`constants.INVALID_EVM_INSTRUCTION` = `0xfe`, **"before consulting nodes"**. One INVALID
opcode byte, fabricated in TypeScript. No such byte exists in consensus state and nothing
ever executes it.

The other five Hedera system contracts — `0x168` (exchange rate), `0x169` (PRNG), `0x16a`
(Hedera Account Service), `0x16b` (Hedera Schedule Service), `0x16c` (HTS v2) — return `0x`
from the same call, because the relay's short-circuit knows only about `0x167`. All six are
dispatched natively by `CustomMessageCallProcessor.start` **before** the Besu precompile
registry is consulted and have **no bytecode in state**, so by SCHEMA.md's boundary all six
are *precompiles*. Contract detection by `eth_getCode != "0x"` is wrong in both directions
here. This is the Taraxa "precompile shadowing bytecode" pattern, except the bytecode does
not exist and only one of six addresses has it.

`0x168` is live and working: `tinycentsToTinybars(1e8)` → `0xc8c184` = 13,157,252 tinybar,
i.e. the HBAR/USD oracle **that prices gas**, readable by contracts, at an address
`eth_getCode` calls empty.

## 10. An account's code depends on the calldata used to call it

`ProxyEvmAccount.getEvmCode(functionSelector, codeFactory)` takes **the call's function
selector as a parameter** and sets the account's address field — and hence returns
account-proxy bytecode — only when the selector is one of `hbarAllowance(address)`,
`hbarApprove(address,int256)` or `setUnlimitedAutomaticAssociations(bool)`. Otherwise the
same account has empty code.

Separately, every HTS **token** has an EVM address whose code is generated on demand by
`RedirectBytecodeUtils.tokenProxyBytecodeFor(address)` — a proxy that delegate-calls `0x167`
with the token address spliced in — so a native Hedera token that was never deployed
presents as an ERC-20/721 contract with a deterministic, address-dependent `EXTCODEHASH`.
The relay reproduces the identical bytes in `CommonService.redirectBytecodeAddressReplace`.
Schedules get the same treatment via `ScheduleEvmAccount`.

There is no expressible Ethereum account state that behaves like either, and no static
analysis over `eth_getCode` can predict it.

## 11. Gas is priced in dollars; `block.basefee` is zero while the RPC says 1.11e12

`TinybarValues.topLevelTinybarGasPrice` = the fee schedule's **tinycent** price for a gas
unit × a congestion multiplier, converted to tinybars at the network's HBAR/USD
`ExchangeRate`. Consequences: the HBAR-denominated gas price moves when the **HBAR price**
moves with no change in demand; it is network-wide rather than per-block, which is why the
relay reports the *identical* `baseFeePerGas` (`0x1027127dc00` = exactly 111 tinybar) at
`earliest` and at head; and there is no auction —
`eth_maxPriorityFeePerGas` returns `0x0`.

Meanwhile `HevmBlockValues.getBaseFee()` returns `Optional.of(Wei.ZERO)` **unconditionally**.
A contract reading `block.basefee` gets zero; the wallet that built the transaction used
1.11e12. Same shape as IOTA EVM's zero `GASPRICE`, one field over.

`HevmBlockValues` is also constructed with **the transaction's own gas limit**, so
`block.gaslimit` varies between transactions inside one block. And `COINBASE` returns the
long-zero address of `ledger.fundingAccount` (entity 98, `0x…0062`) while the block's `miner`
field is the zero address — the EVM and the RPC disagree about who mined it.

## 12. One Ethereum transaction, two payers; success is refunded and failure is not

HIP-410 wraps a signed Ethereum transaction in a HAPI `EthereumTransactionBody`. That gives
it **two economic parties**: the HAPI payer (the "relayer") and the EVM sender recovered from
the inner signature. `max_gas_allowance` lets the relayer subsidise the sender;
`CustomGasCharging.chargeForGas` charges the sender first and the relayer for the remainder;
and on an **aborted** Ethereum transaction `chargeGasForAbortedTransaction` charges the
**relayer** the intrinsic gas outright. Two accounts debited by one transaction, and the
receipt names one.

On top of gas, every transaction pays a three-part HAPI fee (node + network + service) that
no Ethereum receipt field can express — `gasUsed × effectiveGasPrice` does not equal what
left the account. And `contracts.evm.ethTransaction.zeroHapiFees.enabled` defaults **true**,
so `tryHandle` **refunds** the HAPI fee when an Ethereum transaction *succeeds*. A failed one
keeps it. The surcharge for failing is invisible in the receipt.

There is also a second execution meter: ops-duration units
(`contracts.opsDurationThrottleCapacity`, default 5e8, refilled at 5e8/s). Exhausting it
aborts with `CONSENSUS_GAS_EXHAUSTED` while gas remains.

## 13. Every receipt claims a `contractAddress`, including reverted plain calls

`TransactionReceiptFactory.getContractAddressFromReceipt` returns `receiptResponse.address`
whenever the call was not an HTS token creation — i.e. for **every ordinary CALL**. Observed
live on a reverted transaction: `contractAddress` = the callee, `status: 0x0`. Any tool that
treats a non-null `contractAddress` as "this was a deployment" misreads every transaction on
this chain. The same receipts carry **both** a pre-Byzantium `root` (hardcoded to the
empty-trie constant) **and** a `status`, plus a non-standard `revertReason` field.

## 14. `eth_getBlockByNumber` shows a minority of the block and invents some of what it shows

Record file 99380446 contains **7** HAPI transactions (`count: 7` from the mirror node);
`eth_getBlockByNumber` reported **1**. The other six are native Hedera transactions with no
EIP-2718 envelope and no Ethereum representation.

In the other direction, `blockWorker` **fabricates** legacy transactions for logs whose
transaction is not an Ethereum transaction: `from` = `to` = the log's contract address,
`input = 0x0000000000000000`, `gasPrice = 0xfe` (the INVALID-opcode byte used as a sentinel),
`nonce`/`r`/`s`/`v` all zero. They cannot be RLP-re-encoded to their own hash and they never
existed.

## 15. 56 of 59 HAPI transaction types are invisible to Ethereum tooling, and some of them move your money

`TransactionBody`'s `oneof data` has **59** protobuf types in field slots 7–72 (sparse).
Exactly one, `EthereumTransactionBody ethereumTransaction = 50`, carries an EIP-2718
envelope; two more (`contractCall = 7`, `contractCreateInstance = 8`) reach the EVM without
one, authorised by the HAPI payer's Hedera key rather than by any Ethereum signature.

Of the remaining 56: `CryptoTransfer` moves HBAR that `BALANCE` reads; `CryptoUpdateAccount`
can **replace the key controlling an account** without changing its address; `TokenWipe`
destroys a holder's balance with no ERC-20 event a token contract could have emitted;
`ContractDeleteInstance` deletes a contract and sweeps its balance with no `SELFDESTRUCT` in
any trace; `TokenAssociate` means a transfer to an unassociated account fails for a reason
ERC-20 has no word for; `ScheduleCreate` arranges a transaction to execute later, which
`HandleWorkflow.executeScheduledTransactions` can run **in an otherwise empty round** — state
changing in a block containing no submitted transaction at all.

Comparable in kind to Tron's 43 protobuf contract types, but with a much larger fraction of
the network's actual traffic (`ConsensusSubmitMessage` is the highest-volume type) outside
the EVM entirely.

## 16. `authorizes: protocol` with `precompile: none` — ED25519

ED25519 is Hedera's original and still most common key type. It can pay for and authorise any
HAPI transaction, including one carrying an EVM call. Besu's Cancun precompile set has **no
ED25519 verifier**, so an on-chain multisig, guardian or recovery contract written in
Solidity **cannot verify the signatures the protocol just accepted**. The only in-EVM path is
`isAuthorizedRaw` on the Hedera Account Service at `0x16a` — a Hedera-specific native
dispatch, not a precompile — which `CustomGasCalculator.getEdSignatureVerificationSystemContractGasCost`
prices at the ECRECOVER rate. The same holds for threshold keys, key lists and
`contractID` keys (protocol-level account abstraction where the "signature" is satisfied by a
contract being the active frame).

`key_binding` is `declared`: a Hedera account is `shard.realm.num` and receives a 20-byte EVM
address either as an ECDSA-derived alias or as a **long-zero** address whose last 8 bytes are
the entity number. `ecrecover(sig) == from` is not an identity here.

## 17. Does it earn a row in `CANDIDATES.md`? Yes, on all four criteria

`CANDIDATES.md` does not list Hedera. Against its own criteria:

1. **Mindshare** — mid-to-high. A long-lived permissioned-governance L1 with an enterprise
   user base, real HTS token volume, and a Solidity developer surface that people write
   contracts against.
2. **Expected divergence** — very high, and *not where a reader would guess*. The EVM itself
   is stock Besu Cancun (`populateForCancun`, no precompile added, removed or repriced), so
   the naive "the EVM is different" prediction would be **refuted**. Everything diverges
   *around* the EVM: the identity model, the unit system, the header, the account model, the
   fee model, and the fact that the RPC layer is a different program.
3. **Evidence availability** — passes cleanly. Both components are public, tagged, and
   Apache-2.0; the pinned tag is one patch behind mainnet's `hapi_version`.
4. **Native token cap** — comfortably above the $100M floor.

It also supplies something no existing row does: a chain where **the `eth_*` API is a
translation shim maintained in a different repository at a different version**, so "what the
network does" and "what the RPC says" are separately citable and repeatedly disagree.

---

## Not established here

- **The live mainnet value of `contracts.maxRefundPercentOfGasLimit`.** The pinned default is
  100 (floor = 0, rule inert) and live sampling shows charges as low as 6.25% of the gas
  limit, so it is not currently binding. The property is network-governed and Hedera
  historically ran it at 20 (an 80% minimum charge). Recorded `unrecorded` on EIP-3529.
  Settled by reading file 0.0.121 from the mirror node.
- **`BLOCKHASH` executed directly.** Hashio rejects `eth_call` with no `to` (returns `0x`),
  so no ad-hoc bytecode could be run. `BLOCKHASH(n-1) == parentHash` rests on source
  (`ethHashFrom` vs `toHash32`, provably the same truncation) plus a live byte-for-byte check
  that the `eth_*` hash is a prefix of the mirror node's 48-byte hash. Settled by deploying a
  three-opcode probe contract.
- **Whether `EXTCODESIZE(0x167)` inside the EVM returns 1 or 0.** The `0xfe` is a relay
  fabrication and `0x167` has no state bytecode, so the EVM should see 0 — but this was not
  executed, only reasoned from `CustomMessageCallProcessor.start` dispatching before the code
  is fetched. Settled by the same probe contract.
- **The live value of `contracts.maxGasPerSec`.** The relay's 150,000,000 implies mainnet
  raised it at HAPI 0.69, but the pinned tag defaults to 15,000,000 and
  `configuration/mainnet/application.properties` sets only `ledger.id`. The real value is in
  on-chain file 0.0.121 / throttle definitions 0.0.123.
- **Whether `contracts.evm.nonExtantContractsFail` is non-empty on mainnet.** It is a
  per-entity grandfather set that makes `BALANCE`/`EXTCODESIZE` halt for specific addresses.
  Default is `{0}`. A non-default value would be a consensus-relevant per-address exception
  list.
- **The `BonnevilleEVM`.** `contracts.evm.UseBonnevilleEVM` defaults false and selects an
  alternative interpreter (`BEVM`/`BonnevilleEVM`) in `V067Module`. Not analysed; if it is
  ever switched on, whether it is bit-identical to `HederaEVM` is an open consensus question.
- **A live duplicate observation.** The duplicate mechanism is established entirely from
  source. Producing one requires submitting the same `TransactionID` to two nodes, which
  needs a funded mainnet account and the HAPI SDK, not JSON-RPC.

---

## Re-verify

```bash
# =====================================================================
# --- pins
git clone --depth 1 --branch v0.76.1 --single-branch \
  https://github.com/hiero-ledger/hiero-consensus-node chains/hedera/repos/hiero-consensus-node
git -C chains/hedera/repos/hiero-consensus-node rev-parse HEAD
#   -> cd5a2ad0946e1950c64f5a76754a6cd3ee29793e
git clone --depth 1 --branch v0.78.4 --single-branch \
  https://github.com/hiero-ledger/hiero-json-rpc-relay chains/hedera/repos/hiero-json-rpc-relay
git -C chains/hedera/repos/hiero-json-rpc-relay rev-parse HEAD
#   -> 1701d192333ca19c3cfd630a4e6ababcdf6cd001

# --- the org rename and the dead relay repo
git ls-remote --tags https://github.com/hashgraph/hedera-services | head -3      # redirects, identical tags
git ls-remote --tags https://github.com/hashgraph/hedera-json-rpc-relay          # -> "Repository not found"

# --- mainnet runs a version with no public tag
curl -s "https://mainnet-public.mirrornode.hedera.com/api/v1/blocks?limit=1&order=desc" | jq -r .blocks[0].hapi_version
#   -> 0.76.2      (no v0.76.2 tag exists; newest vX.Y.Z is v0.76.1)

cd chains/hedera/repos/hiero-consensus-node

# --- source: Besu as a LIBRARY, pinned at Cancun
grep -n 'val besu\|org.hyperledger.besu:evm' hiero-dependency-versions/build.gradle.kts
grep -n 'registerCancunOperations\|populateForCancun\|EvmSpecVersion.CANCUN' \
  hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/exec/v067/V067Module.java
grep -n 'CancunGasCalculator' \
  hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/exec/gas/CustomGasCalculator.java
grep -n 'evm.version' hedera-node/hedera-config/src/main/java/com/hedera/node/config/data/ContractsConfig.java

# --- source: ordering (finding 1)
sed -n '826,875p' platform-sdk/consensus-hashgraph-impl/src/main/java/org/hiero/consensus/hashgraph/impl/consensus/ConsensusImpl.java
grep -n 'MIN_TRANS_TIMESTAMP_INCR_NANOS' platform-sdk/consensus-model/src/main/java/org/hiero/consensus/model/hashgraph/ConsensusConstants.java
grep -n 'willOpenNewBlock' -A 15 hedera-node/hedera-app/src/main/java/com/hedera/node/app/records/impl/BlockRecordManagerImpl.java
grep -n 'getBlockPeriod' -A 3 hedera-node/hedera-app/src/main/java/com/hedera/node/app/records/impl/BlockRecordManagerImpl.java

# --- source: billed-and-skipped (finding 2)
sed -n '130,145p;248,260p' hedera-node/hedera-app/src/main/java/com/hedera/node/app/workflows/handle/DispatchProcessor.java
grep -n 'creatorErrorIfKnown' -A 10 hedera-node/hedera-app/src/main/java/com/hedera/node/app/workflows/handle/dispatch/DispatchValidator.java

# --- source: DUPLICATES (finding 3) — the whole chain of custody
grep -n 'hasDuplicate' -A 10 hedera-node/hedera-app/src/main/java/com/hedera/node/app/state/recordcache/RecordCacheImpl.java
#   -> NO_DUPLICATE / SAME_NODE / OTHER_NODE
sed -n '99,110p' hedera-node/hedera-app/src/main/java/com/hedera/node/app/workflows/handle/dispatch/DispatchValidator.java
#   -> SAME_NODE -> newCreatorError(..., DUPLICATE_TRANSACTION); OTHER_NODE -> payer, DUPLICATE
sed -n '96,104p' hedera-node/hedera-app/src/main/java/com/hedera/node/app/fees/AppFeeCharging.java
#   -> shouldWaiveServiceFee when duplicateStatus() == DUPLICATE; charge(payerId, feesToCharge, ctx.nodeAccountId(), null)
grep -n 'transaction.maxValidDuration' -A 2 hedera-node/hedera-config/src/main/java/com/hedera/node/config/data/HederaConfig.java
#   -> defaultValue = "180"
grep -n 'ethereumHash' hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/handlers/EthereumTransactionHandler.java
#   -> only inside handle() and handleThrottled(): a duplicate has no ethereum_hash, so eth_* never sees it
grep -n 'WRONG_NONCE' hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/exec/TransactionProcessor.java

# --- source: units (finding 7)
grep -n 'WEIBARS_IN_A_TINYBAR\|getAmount' hedera-node/hapi-utils/src/main/java/com/hedera/node/app/hapi/utils/ethereum/EthTxData.java
grep -n 'weiValue' -A 3 hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/hevm/HederaEvmTransaction.java
grep -n 'public Wei getBalance' -A 3 hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/state/DispatchingEvmFrameState.java

# --- source: the 750-address gas sink (finding 8)
grep -n 'NUM_SYSTEM_ACCOUNTS' hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/exec/processors/ProcessorModule.java
grep -n 'isSystemAccount' -A 6 hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/exec/v038/Version038AddressChecks.java
grep -n 'handleNonExtantSystemAccount' -A 6 hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/exec/processors/CustomMessageCallProcessor.java

# --- source: block/EVM values (findings 5, 6, 11)
sed -n '40,64p' hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/hevm/HevmBlockValues.java
grep -n 'ethHashFrom' -B 6 -A 8 hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/utils/ConversionUtils.java
grep -n 'nominalCoinbase\|miningBeneficiary' hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/exec/utils/FrameBuilder.java
grep -n 'topLevelTinybarGasPrice' -A 8 hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/exec/gas/TinybarValues.java

# --- source: synthesised code (finding 10)
grep -n 'ACCOUNT_PROXY_FUNCTION_SELECTOR' -A 22 hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/state/ProxyEvmAccount.java
grep -n 'PROXY_PRE_BYTES\|tokenProxyBytecodeFor' hedera-node/hedera-smart-contract-service-impl/src/main/java/com/hedera/node/app/service/contract/impl/utils/RedirectBytecodeUtils.java

# --- source: 59 HAPI transaction types (finding 15)
grep -n 'oneof data' -A 400 hapi/hedera-protobuf-java-api/src/main/proto/services/transaction.proto | grep -cE '= [0-9]+;'
#   -> 59
grep -n 'ethereumTransaction = 50' hapi/hedera-protobuf-java-api/src/main/proto/services/transaction.proto

# --- source: only three Ethereum tx types (tx_types)
grep -n 'enum EthTransactionType' -A 5 hedera-node/hapi-utils/src/main/java/com/hedera/node/app/hapi/utils/ethereum/EthTxData.java
sed -n '75,86p' hedera-node/hapi-utils/src/main/java/com/hedera/node/app/hapi/utils/ethereum/EthTxData.java
#   -> case 3 -> null; // We don't currently support Cancun "blob" transactions

cd ../hiero-json-rpc-relay

# --- relay: the header is fabricated (finding 5)
sed -n '35,58p' src/relay/lib/factories/blockFactory.ts
grep -n 'BLOCK_GAS_LIMIT_BY_HAPI_VERSION' -A 5 src/relay/lib/config/blockGasLimit.ts
# --- relay: the 0xfe lie and the token redirect (findings 9, 10)
sed -n '193,215p' src/relay/lib/services/ethService/contractService/ContractService.ts
grep -n 'redirectBytecodeAddressReplace' -A 6 src/relay/lib/services/ethService/ethCommonService/CommonService.ts
# --- relay: contractAddress on every receipt (finding 13)
grep -n 'getContractAddressFromReceipt' -A 14 src/relay/lib/factories/transactionReceiptFactory.ts
# --- relay: fabricated transactions (finding 14)
sed -n '100,135p' src/relay/lib/services/ethService/blockService/blockWorker.ts

# =====================================================================
# --- live: identity and the pinned block
R=https://mainnet.hashio.io/api
q(){ curl -s -X POST -H 'content-type:application/json' --data "$1" $R; echo; }
q '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}'          # -> 0x127
q '{"jsonrpc":"2.0","id":1,"method":"web3_clientVersion","params":[]}'   # -> relay/0.78.4

# --- live: the fabricated header (finding 5) — block 99380446 = 0x5ec6cde, which HAS a tx
q '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["0x5ec6cde",true]}'
#   -> stateRoot      0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421 (empty-trie constant)
#      transactionsRoot 0x961c4709699645d815396c31dc2aec6120921195a558fefc99eea6f730de1d96 == hash
#      gasLimit 0x8f0d180, baseFeePerGas 0x1027127dc00, miner 0x00..00, 1 transaction, type 0x0, v 0x272
#      no excessBlobGas / blobGasUsed / parentBeaconBlockRoot / requestsHash keys at all
q '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["earliest",false]}'
#   -> SAME baseFeePerGas 0x1027127dc00, gasLimit 0x1c9c380 (30M), same stateRoot constant

# --- live: 48-byte hash truncation (finding 6)
curl -s "https://mainnet-public.mirrornode.hedera.com/api/v1/blocks/99380446" \
  | jq -r '.hash, .previous_hash, .count, .name'
#   -> 0x961c4709699645d815396c31dc2aec6120921195a558fefc99eea6f730de1d968191fdcff7664d2d3f4b2e6e4b572a8a
#      0x514380435be71ecf6d8788477db1d07cf0643144f0b41244e94c3eb9701f79da0470dd3f40797dc90dba8b5a3983e99c
#      7                       <-- seven HAPI transactions; eth_* showed ONE (finding 14)
#      2026-08-28T22_09_53.481359104Z.rcd.gz
# the eth_* hash/parentHash are byte-exact 32-byte PREFIXES of these.

# --- live: units, exactly 10^10 (finding 7)
q '{"jsonrpc":"2.0","id":1,"method":"eth_getBalance","params":["0x2abefbbb0b1b18a180dfa5887b31f3929dc2c45b","latest"]}'
#   -> 0x452217627b6f413400 = 1275281881490000000000
curl -s "https://mainnet-public.mirrornode.hedera.com/api/v1/accounts/0x2abefbbb0b1b18a180dfa5887b31f3929dc2c45b" \
  | jq -r '.account, .balance.balance'
#   -> 0.0.7644395 / 127528188149      (127528188149 * 10^10 == 1275281881490000000000)

# --- live: system contracts (finding 9)
for a in 0167 0168 0169 016a 016b 016c 0100 0001; do
  q "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x00000000000000000000000000000000000$a\",\"latest\"]}"
done
#   -> 0x167 gives 0xfe (relay fabrication); every other one gives 0x
q '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x0000000000000000000000000000000000000168","data":"0x2e3cff6a0000000000000000000000000000000000000000000000000000000005f5e100"},"latest"]}'
#   -> 0x00..c8c184 = 13157252 tinybar per 1e8 tinycent — the live HBAR/USD oracle

# --- live: the P256 probe is a FALSE POSITIVE (finding 8)
q '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x0000000000000000000000000000000000000100","data":"0x'"$(printf '0%.0s' {1..320})"'"},"latest"]}'
#   -> 0x  — empty output, but from handleNonExtantSystemAccount, NOT EIP-7951

# --- live: Cancun system contracts absent
q '{"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":["0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02","latest"]}'   # -> 0x (4788)
q '{"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":["0x0000F90827F1C53a10cb7A02335B175320002935","latest"]}'   # -> 0x (2935)

# --- live: every tag is the same block (finding 4)
for t in latest safe finalized pending; do
  q "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$t\",false]}"
done
#   -> byte-identical objects

# --- live: contractAddress on a reverted plain CALL (finding 13)
q '{"jsonrpc":"2.0","id":1,"method":"eth_getTransactionReceipt","params":["0xc83b4a1920e45fac569e693acdf6b5385c109e9b6d0c390702ed62885b92de05"]}'
#   -> status 0x0, contractAddress 0xf09afe78d3c7d359b334d7cb88995751f7ec5e13 (== to),
#      root 0x56e81f17..b421 alongside status, non-standard revertReason 0x22611167

# --- live: no minimum-gas floor today (EIP-3529 note)
curl -s "https://mainnet-public.mirrornode.hedera.com/api/v1/contracts/results?limit=25&order=desc" \
  | jq -r '.results[] | select(.gas_limit) | "\(.gas_limit) \(.gas_used) \(.result)"'
#   -> e.g. 4000000 249802 SUCCESS  (6.25% of the limit charged)
#           500000   38457 CONTRACT_REVERT_EXECUTED
```
