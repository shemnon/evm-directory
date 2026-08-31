# Autonomys Auto EVM — what this row teaches

**Evidence.** Client `autonomys/subspace` at tag `runtime-mainnet-2026-jul-29`,
commit `f76e41c2ddcca4828c4a955ac44c7816b1bccd1b` (Rust, Substrate/FRAME). Two
companion clones supply the EVM itself: `polkadot-evm/frontier` at
`9d49e36ed5bac38241594f8ba055fdb94991483a` and `rust-ethereum/evm` at
`a656db9050c65170b050360c3fa66c0fd8bf226a` (crate `evm` 0.43.4) — both pinned to
the exact revisions the workspace `Cargo.toml` names, not to tags, because
neither dependency is consumed at a tag.

Live probe: `https://auto-evm.mainnet.autonomys.xyz/ws`, `eth_chainId` -> `0x366`
(870), `web3_clientVersion` -> `subspace-evm-domain/v4.0/fc-rpc-2.0.0-dev`. All
`src_live:` facts are pinned to **block 4,577,685** (`0x45d995`, timestamp
`1787845102` = 2026-08-27T15:38:22Z) unless the entry names a different height.
Baseline fork **osaka** — `fp_evm::EVM_CONFIG = Config::osaka()`, a compile-time
constant with no fork schedule of any kind.

Evidence path: `source`. The chain is **live** on mainnet, so this is not a
`prelaunch` row. The pinned runtime's `spec_version: 4` matches
`state_getRuntimeVersion` on the running network exactly, which is why the
*runtime* tag was pinned rather than the newer node tag (the public RPC's
`system_version` reports node build `0.1.11-b3f2859d528`, i.e.
`mainnet-2026-jun-14`).

Verifier: `citations ok — 62 symbols confirmed`, `src=37 src_live=14`.

---

## 1. Ordering commits on one chain and execution happens on another

Auto EVM is not a chain. It is **domain 0** on the Autonomys consensus chain, and
it has no block producer, no consensus and no mempool that decides ordering.

* **Ordering.** A domain **operator** wins a slot by VRF
  (`sp-domains/src/bundle_producer_election.rs`), packs already-signed domain
  extrinsics into a **`Bundle`**, and submits it to the *consensus* chain via
  `pallet_domains::submit_bundle`. The consensus chain executes **none** of them.
  It records the bundle's `extrinsics_root` in `ExecutionInbox`, and the ordering
  is then fixed by the consensus chain's own fork choice.
* **Execution.** Operators later derive domain block N deterministically from
  consensus block C: `DomainBlockPreprocessor::preprocess_consensus_block`
  (`domains/client/block-preprocessor/src/lib.rs`) concatenates the bundles in
  consensus order, executes them, and commits to the result by attaching an
  **`ExecutionReceipt`** — post-state root plus a per-extrinsic
  `execution_traces` vector — to a *later* bundle.
* **Dispute.** That receipt sits in a block tree for
  `domain_block_pruning_depth = 14_400` domain blocks
  (`crates/subspace-runtime-primitives/src/lib.rs:production_params`) during
  which anyone may unseat it with a `FraudProof`.

This is decoupled execution of a different shape from Monad's. Monad defers the
*state root* by three blocks inside one chain. Autonomys splits *ordering* and
*execution* across two chains and two actor classes, and the gap between them is
about a day, not three blocks.

## 2. A single invalid transaction destroys its entire bundle

This is the answer to "what happens to a transaction that is validly ordered but
invalid by the time it executes", and it is none of the usual answers.

`batch_check_bundle_validity` classifies a bundle with `InvalidBundleType`
(`crates/sp-domains/src/bundle.rs`), whose six variants are exactly the
invalid-at-execution taxonomy:

| variant | cause |
|---|---|
| `UndecodableTx(u32)` | extrinsic prefix failed to SCALE-decode |
| `OutOfRangeTx(u32)` | signer falls outside the bundle's VRF tx-range |
| `InherentExtrinsic(u32)` | an inherent smuggled into a user bundle |
| `InvalidXDM(u32)` | cross-domain message with a bad MMR proof |
| `IllegalTx(u32)` | **`check_extrinsics_and_do_pre_dispatch` failed** — nonce, fee, balance |
| `InvalidBundleWeight` | header's `estimated_bundle_weight` does not match |

`IllegalTx` is the ordinary "your nonce was consumed / you can no longer pay the
fee" case. And the consequence is stated in the type's own doc comment:

> `Invalid(InvalidBundleType)` — *"The invalid bundle was originally included in
> the consensus block but subsequently **excluded from execution** as invalid"*

Not the offending transaction — **the whole bundle**. In
`preprocess_consensus_block`, a `BundleValidity::Invalid` bundle contributes
**zero** extrinsics to `valid_extrinsics`. Every other transaction packed
alongside it, valid and correctly signed and already ordered by consensus, is
discarded with no receipt, no log, no trace and no block position.
`eth_getTransactionReceipt` returns `null` forever for all of them.

Conflux, landed just before this row, erases the single offending transaction
from the block. Here the blast radius is every co-passenger in the same bundle.

## 3. ...and it is a **slashable operator fault**, not a transaction failure

The part that has no analogue anywhere else in this dataset. When the domain
block is confirmed, `pallet-domains/src/block_tree.rs` walks the receipt's
`InboxedBundle` entries, collects `invalid_bundle_authors` for every bundle
marked `is_invalid()`, and `pallet-domains/src/lib.rs` calls:

```
do_mark_operators_as_slashed(
    confirmed_block_info.invalid_bundle_authors.into_iter(),
    SlashedReason::InvalidBundle(confirmed_block_info.domain_block_number),
)
```

`SlashedReason::InvalidBundle`'s own doc comment reads **"Operator produced bad
bundle."** Slashing is automatic on confirmation — no fraud proof is required for
it, because the confirmed receipt already records which bundles were invalid. (A
fraud proof is only needed for the *other* direction: `FraudProofVariant::InvalidBundles`
and `ValidBundle` exist to contest a receipt that lied about which bundles were
valid, and that path slashes the *receipt submitter* under
`SlashedReason::BadExecutionReceipt`.)

So on Auto EVM, "your transaction had a stale nonce" is not an outcome a
transaction can have. It is a protocol violation attributed to the operator who
accepted it, priced in staked AI3, with `MinOperatorStake = 100 AI3` at risk.
Every other chain in this dataset treats an ordered-but-invalid transaction as a
transaction-level event (drop, `status: 0`, or Conflux's `Skipped`). This one
treats it as misbehaviour by a validator.

The consequence for users is unpleasant and quiet: because operators are punished
for including a transaction that turns out invalid, they have a direct economic
incentive to be conservative about what they bundle, and a transaction that
becomes marginal between submission and bundling is simply never included.

## 3a. ...but the same transaction in two bundles is **not** a fault, and that is the surprise

Given §3, the obvious guess is wrong. Operators build bundles independently from their own
view of the pool, so two of them bundling the same transaction into one consensus block is
a routine race — and on a chain where a stale nonce inside a bundle is a *slashable
protocol violation*, it would have been entirely consistent for a duplicate to be one too.
It is not.

The resolution comes **after** bundle validity, not during it, and the ordering is the whole
finding. `preprocess_consensus_block` first runs `compile_bundles_to_extrinsics`, which
classifies each bundle on its own: `check_extrinsics_and_do_pre_dispatch` is evaluated
against the **parent domain block** state and maintains its storage-buffer side effects only
*within* one bundle. Both bundles therefore see the same parent nonce, both pass, and both
are recorded as `InboxedBundle::valid`. Only then is `deduplicate_and_shuffle_extrinsics`
applied to the concatenation of every valid bundle's extrinsics — a `seen` list walked in
bundle order, dropping anything equal to something already kept, before the
randomness-seeded shuffle. **The first occurrence in bundle order executes; the second never
enters the domain block's extrinsic list.**

`InvalidBundleType` has exactly six variants — `UndecodableTx`, `OutOfRangeTx`, `IllegalTx`,
`InvalidXDM`, `InherentExtrinsic`, `InvalidBundleWeight` — and none of them is duplication.
The bundle is never marked invalid, so its author never reaches `invalid_bundle_authors` and
`do_mark_operators_as_slashed` is never called for it.

What a client sees is the Conflux outcome by a completely different route: the losing copy
is indistinguishable from never submitted, not because it was executed and erased, and not
because a nonce check rejected it, but because a byte-equality filter removed it before the
domain block existed. One receipt, one hash, one fee.

Who pays is small and worth naming. `charge_bundle_storage_fee` burns from the operator's
bundle storage fund in proportion to `bundle.size()` **at submission**, before any
deduplication, so the duplicate's bytes are paid for. But `refund_storage_fee` returns each
operator a share of the block's collected storage fees in proportion to **bytes submitted**
rather than extrinsics that survived, and `do_reward_operators` pays the set of operators
that submitted bundles for the confirmed domain block without reference to how much of their
payload was deduplicated. The duplicate is close to cost-neutral for its author and mildly
dilutive for everyone else — the exact inverse of Taraxa, where pre-Aspen a DAG block earned
nothing at all unless it contributed a unique transaction. Autonomys pays for the bundle,
not for the contribution.

One limit: the filter is `seen.contains(uxt)` on the *encoded extrinsic*, so it catches only
byte-identical repeats. Two different transactions from the same sender at the same nonce,
bundled by two operators, are not duplicates by this test and both reach the domain block.
What the domain runtime does with the second is left `unrecorded`.

## 4. `eth_getBlockByNumber("finalized")` is about a day behind `"latest"`

Measured live at the same instant: `latest` = **4,580,360**, `finalized` =
**4,565,366** — a lag of **14,994 domain blocks**. That is
`domain_block_pruning_depth = 14_400` (the fraud-proof challenge window) plus the
consensus chain's own `confirmation_depth_k = 100`. `"safe"` returns the *same
block as* `"finalized"`, so there is no intermediate tier.

Answering the (d) question precisely: a client **does** see receipts long before
finality — the operator's `fc-rpc` serves them from its own database as soon as it
derives the block, roughly one consensus slot after ordering. Whether that receipt
can change has two answers, and the intuitive one is wrong:

* A **successful fraud proof does not change it.** The domain block's *content*
  is a deterministic function of the consensus block that ordered it, so every
  honest operator derives the same block. A fraud proof removes a receipt that
  *lied* about executing that block; it does not re-order or re-execute anything.
  `HeadReceiptNumber` is reverted and the block tree pruned back, but an honest
  node's local chain is untouched.
* A **consensus-chain reorg does.** The domain chain is re-derived from whatever
  the consensus chain settles on, so any reorg within `confirmation_depth_k = 100`
  consensus blocks (~10 minutes) re-derives the domain blocks above it. That, not
  fraud proofs, is what can retract a receipt a client has already seen.

There is no early/optimistic receipt with a fake block hash a la MegaETH; the
receipt looks completely ordinary and the uncertainty is invisible in it.

## 5. Autonomys runs **stock Frontier** — the first row here that does

`CANDIDATES.md` records that a Frontier framework row is *not warranted* because
"Moonbeam forks every Frontier crate and shares the fork with nobody, so a
template row would pin code no chain runs." Autonomys is the counter-example that
was missing. Every Frontier crate in the workspace — `fc-consensus`, `fc-db`,
`fc-mapping-sync`, `fc-rpc`, `fc-rpc-core`, `fc-storage`, `fp-account`, `fp-evm`,
`fp-rpc`, `fp-self-contained`, `pallet-ethereum`, `pallet-evm`,
`pallet-evm-chain-id`, the three precompile crates, `precompile-utils` — is a
plain git dependency on `https://github.com/polkadot-evm/frontier` at
`rev = 9d49e36...`, and the workspace's `[patch]` block redirects **only the
polkadot-sdk crates underneath** Frontier (to `autonomys/polkadot-sdk`), with the
in-file comment *"We need to patch substrate dependency of frontier to our fork."*
Substrate is forked; Frontier is not.

That matters for the dataset's framework policy in both directions. Auto EVM's EVM
semantics genuinely are upstream Frontier's, so a future stock-Frontier chain
would share them — but the divergences that make this row worth reading (the
precompile set, the fee model, the block gas limit, contract-creation permission,
the whole ordering story) are all in Autonomys' own code, not Frontier's. A
Frontier row would still not absorb this chain.

## 6. Twelve of mainnet's seventeen precompiles are absent, and absent means *succeeds*

The precompile set is eight entries
(`domains/primitives/evm-precompiles/src/lib.rs:PrecompilesAt`), inside
`PrecompilesInRangeInclusive<(0x01, 0x0FFF)>`:

```
0x01 ECRecover   0x02 Sha256   0x03 Ripemd160   0x04 Identity   0x05 Modexp
0x0400 Sha3FIPS256   0x0401 ECRecoverPublicKey   0x0800 TransporterPrecompile
```

Everything from **0x06 upward is gone**: BN254 add/mul/pairing, BLAKE2F, KZG
point-evaluation, all seven EIP-2537 BLS12-381 addresses, and P256VERIFY at
0x0100. Absent here means *empty account*, so the CALL **succeeds and returns
nothing** — verified live for every one of them.

The sharpest case is `0x08`. Every deployed Groth16 or PLONK verifier ends in a
pairing check. Mainnet returns 32 bytes ending `0x01` for success. Here the call
returns zero-length data, so:

* a verifier that reads the returned word rejects **every valid proof**;
* a verifier that only checks the `success` flag accepts **every proof**.

Both idioms exist in shipped verifier code, and neither produces a revert, an
error, or any signal at all. No zk system, no BLS aggregate-signature scheme, and
no passkey wallet can work on this chain, and nothing tells you so.

`0x0100` joins the `p256-silent-invalid` class as its sixth member, by a fifth
distinct cause: the precompile map simply stops at `0x05`.

## 7. `eth_getCode` behaves here in a way it does on no other row

Genesis writes a five-byte revert stub `0x60006000fd` (`PUSH1 0 PUSH1 0 REVERT`)
at exactly `0x01`-`0x05`, `0x0400` and `0x0401` — and nowhere else. So:

* `EXTCODESIZE(0x01) == 5` where mainnet says `0`;
* `EXTCODESIZE(0x08) == 0` and `0x08` really is absent — correct, by accident;
* `EXTCODESIZE(0x0800) == 0` and `0x0800` is a **live precompile** — wrong.

Seven of eight classified correctly, the eighth wrong, and the whole pattern is a
dating artefact: the genesis alloc stubbed the precompiles that existed when the
domain was instantiated, and the Transporter was added later. This is the Moonbeam
revert-stub shape arriving from stock Frontier tooling rather than from a
Moonbeam-specific registry.

## 8. There is no EIP-1559 base fee, and `eth_feeHistory` invents one

Frontier ships `pallet-base-fee`, which implements 1559's elasticity. **This
runtime does not include it** — `construct_runtime!` has `Ethereum = 80`,
`EVM = 81`, `EVMChainId = 82`, `EVMNoncetracker = 84`, and no base-fee pallet.
What fills `baseFeePerGas` is `pallet_evm::FeeCalculator::min_gas_price()`, here
`pallet_evm_tracker::fees::EvmGasPriceCalculator`:

```
min_gas_price = next_fee_multiplier * (TransactionWeightFee * WEIGHT_PER_GAS)
              + consensus_chain_byte_fee / GasPerByte
```

The multiplier is Substrate's `SlowAdjustingFeeUpdate` over domain-block **Weight**
fullness; the second term comes from the **consensus chain's** per-byte storage
price. So the target is not 50% of gas, the step is not capped at 12.5%, the
input is not gas used, and part of the price is set by a different chain. Two
consecutive *empty* blocks moved the base fee **up** (`0x2c1bfedd4` ->
`0x2c1bfee06`) where 1559 mandates -12.5%.

And `eth_feeHistory`'s trailing element — the projected next-block base fee — is
computed by `fc-rpc` with the 1559 formula. At block 4,580,343 it reported
`0x26987f045`, a clean 12.5% drop that this chain will never take. Every 1559 fee
estimator is wrong here, in both directions, silently.

## 9. BLOCKHASH reaches back 2400 blocks, not 256

Frontier resolves `BLOCKHASH` through `pallet_ethereum::BlockHash`, a storage map
pruned in `on_finalize` at `frame_system::BlockHashCount` — which this runtime
sets to **2400** — and `SubstrateStackState::block_hash` applies no 256-block
clamp of its own. Probed to the exact boundary:

```
BLOCKHASH(n-256)  -> 0x6fc65707...
BLOCKHASH(n-257)  -> 0x29ecca7b...      (zero on mainnet)
BLOCKHASH(n-2400) -> 0xa8f0a15f...
BLOCKHASH(n-2401) -> 0x0000...0000
```

`blockhash(n) == 0` is a common cheap test for "older than 256 blocks" — a
freshness guard, and the classic weak-randomness idiom. It gives the wrong answer
for 2,144 blocks' worth of history here. No other row in this dataset *widens*
this window.

## 10. Two Osaka opcodes are `InvalidCode`, not zero-returning

`Config::osaka()` in `rust-ethereum/evm` has flags for PUSH0, MCOPY,
TLOAD/TSTORE, EIP-6780, EIP-7702, EIP-7623 and EIP-7939 — and **no flag for
BLOBHASH or BLOBBASEFEE**, because that interpreter never implemented them:

```
0x49 BLOBHASH    -> evm error: InvalidCode(Opcode(73))
0x4a BLOBBASEFEE -> evm error: InvalidCode(Opcode(74))
```

Contrast Monad, which keeps `blobGasUsed`/`excessBlobGas` in the header pinned to
zero and the opcodes working. Here a contract compiled for Cancun+ that reads
`block.blobbasefee` does not merely misbehave — it is **undeployable**, and the
error surfaces as an EVM-level invalid-opcode rather than anything a Solidity
developer would recognise. CLZ (EIP-7939) *is* live and returns 255 for `CLZ(1)`,
which is the one thing making the "Osaka" claim more than a Prague claim.

## 11. PREVRANDAO is 0 and COINBASE is the zero address, forever

`FindAuthorTruncated::find_author` returns `None` unconditionally, with an
in-source TODO to return the executor reward address "once we start collecting
them". Every block header carries `author`/`miner` = `0x0000...0000`, and
`COINBASE` returns it. Warm-coinbase pricing is active, so the zero address is
the warm one, and a fee-splitting contract that `transfer(block.coinbase, x)`
burns.

`PREVRANDAO` (0x44) is a valid opcode returning the zero word on every block —
there is no beacon randomness, and the header does not even have a `mixHash`
field for it to read. Any lottery, shuffle or commit-reveal tiebreak ported here
is deterministic and free to grind, with no revert and no error.

## 12. Substrate's account model leaks through: existential deposit and reaping

`EXISTENTIAL_DEPOSIT = 1_000_000_000_000` wei (10^-6 AI3). Balances live in
`pallet-balances`, and:

* an account whose balance falls below the deposit is **reaped** — the residue
  goes to `DustRemovalHandler`, which **burns** it
  (`BlockFees::note_burned_balance`);
* symmetrically, `pallet-balances` refuses a transfer that would leave the
  **recipient** below the deposit, so a `CALL` with `value` under 10^12 wei to a
  fresh address **fails** where mainnet succeeds.

EIP-161's rule is that an account is deleted only when it is empty *and* touched.
Here it is deleted for being merely poor, and the residue is destroyed rather
than kept. Neither rule is expressible in the EVM's account model, and neither
produces a distinguishable error.

## 13. Cross-domain AI3 arrives with no transaction

Money bridged into Auto EVM from the consensus chain or another domain does
**not** arrive as an Ethereum transaction. It arrives as a `pallet_messenger`
Substrate extrinsic in the same domain block, is dispatched to
`pallet_transporter`'s endpoint handler, and credits the recipient through
`pallet-balances`. `eth_getBlockByNumber` returns only what `pallet_ethereum`
recorded, so the block shows an EVM balance change with **no transaction, no
receipt and no log**.

This is the third independent route to the `no-type-byte` problem — Avalanche's
UTXO atomic transactions, Tron's protobuf contracts, and now a Substrate pallet
call — and it breaks the same thing each time: an indexer reconstructing balances
from `eth_*` transactions misses every inbound bridge transfer. Two more protocol
paths mutate EVM state with no Ethereum envelope: `pallet_domain_sudo` (the
consensus chain injecting an arbitrary domain call) and the `dmnevmtr` inherent.

## 14. Gas is a conversion, the gas limit is advisory, and there is a second meter

* `GAS_PER_SECOND = 40_000_000`, so `WEIGHT_PER_GAS = 25,000` picoseconds/gas,
  applied by `pallet_evm::FixedGasWeightMapping`. Gas is a unit of accounted
  *time* at a fixed exchange rate; the resource actually limited is Weight.
* `GasLimitPovSizeRatio = 4`: a transaction's gas limit also buys it
  `gas_limit / 4` bytes of proof-of-validity, and exceeding it fails as
  **OutOfGas with EVM gas remaining** (Frontier's `handle_storage_oog`). This
  joins the `second-meter-failures` class. Moonbeam's ratio is 8 (tighter) and
  Moonbeam also meters storage growth; this row explicitly does not —
  `type GasLimitStorageGrowthRatio = ()` with an in-source *"TODO: re-check this
  value mostly from moonbeam."*
* `BlockGasLimit = 52,000,000` on every block, and the source says outright that
  this value *"does not serve as a limit of the total weight of a domain block,
  which is `max_bundle_weight * number_of_bundle` and bundle production is
  probabilistic."* `block.gaslimit` and the header's `gasLimit` are a fixed
  constant that neither bounds nor describes the block they appear in.
* 30% of every gas fee (`StorageFeeRatio`) is booked as a **consensus-chain
  storage fee** and 70% as domain execution fee; both are carried back to the
  consensus chain inside the execution receipt to pay operators.

## 15. Contract deployment can be switched off from the parent chain

`pallet_evm_tracker::ContractCreationAllowedBy` defaults to `Anyone`, but the
consensus chain can set it to `Accounts(vec![...])` through
`pallet_domains::send_evm_domain_set_contract_creation_allowed_by_call` (domain
owner or root) delivered as the `dmnevmtr` inherent. When it is not `Anyone`, a
`CREATE` from any other signer is rejected in **`validate_self_contained`** with
`InvalidTransaction::Custom(ERR_CONTRACT_CREATION_NOT_ALLOWED)` — refused at
admission, so there is no receipt and no revert reason, just a rejected send. The
check walks nested calls (`maybe_nested_call` over `pallet_utility` batches) to
catch a `CREATE` hidden in a batch.

Auto EVM (domain 0) is a `Public` domain at the default today, but this is a
state-transition rule that can be turned on by a different chain, without a
runtime upgrade, leaving no EVM-visible trace.

---

## Does this chain earn a row? — against `CANDIDATES.md`'s own criteria

`CANDIDATES.md` does not list Autonomys anywhere, in any tier. Judged on the
file's four criteria, honestly:

1. **Mindshare — fails, clearly.** This is the weakest part of the case and it
   should be stated plainly. Sampling **160 consecutive blocks** (4,580,200 ->
   4,580,360) at the probed height found **zero transactions**; spot checks at
   4,570,000 / 4,575,000 / 4,578,000 / 4,579,000 likewise found zero. Every block
   in the sample was empty, `gasUsed: 0x0`, `eth_maxPriorityFeePerGas: 0x0`. There
   is essentially no contract deployment for the delta to protect.
2. **Expected divergence — passes, and by a wide margin.** Twelve missing
   precompiles that fail silently, no EIP-1559, two invalid Osaka opcodes, a 2400-
   block BLOCKHASH window, a fabricated block gas limit, existential-deposit
   reaping, and an ordering model in which an invalid transaction is a *slashable
   operator fault*. That last one is unique in this dataset.
3. **Evidence availability — passes comfortably.** Full public source, released
   tags, a public RPC, and the enacted runtime version verifiable against the
   pinned clone.
4. **Cap floor >= $100M — not established here**, and criterion 4 is explicitly
   the fallback "for anything that fails 1 and 2." This chain does not fail 2.

**Verdict: it earns a row, but for exactly one reason.** Not because anyone needs
the delta to ship on Auto EVM — nobody is shipping on Auto EVM — but because the
ordering/execution model is a shape the dataset does not otherwise contain, and
because it settles the Frontier-framework question left open in `CANDIDATES.md`
in the direction Moonbeam could not. If the row is ever cut for mindshare,
findings 2, 3 and 5 above are the ones worth relocating rather than losing. A
reader looking for "which chains should I test my contract against" gains little;
a reader looking for "how many different things can 'ordered but invalid' mean"
gains a case no other row supplies.

---

## Not established here

* **MODEXP bounds and pricing.** `0x05` is Frontier's own
  `pallet-evm-precompile-modexp`, a separate implementation from geth's. Whether
  it matches EIP-198, 2565, 7823 or 7883 was not read, and `eips.2565` is
  `unrecorded` rather than guessed. Settle it by reading
  `frontier/frame/evm/precompile/modexp/src/lib.rs` and by probing a 1024-byte
  modulus against a mainnet control.
* **Whether reaping resets an EOA's nonce.** The existential deposit and the dust
  burn are established from source. Whether `frame_system` removing a reaped
  account's `AccountInfo` also zeroes its EVM nonce — which would allow replay of
  old signed transactions and `CREATE` address reuse — depends on
  provider/sufficient reference counting in the `autonomys/polkadot-sdk` Substrate
  fork, which was not cloned. Frontier's
  `FrameSystemAccountProvider::create_account` calls `inc_sufficients`, but only
  for accounts created *with code*, so contracts are protected and plain EOAs may
  not be. This is the single most consequential open question on the row.
* **Whether a dropped transaction is retried.** When a bundle is invalidated, its
  valid co-passengers vanish from the block. Whether the operator's Substrate
  transaction pool re-proposes them in a later bundle is a node-local pool
  behaviour, not a consensus rule, and was not traced. Two operator
  implementations could differ.
* **Live behaviour of any transaction at all.** No transaction was submitted (no
  funded key) and none was observed in the sampled blocks, so `tx_types` `0x01`,
  `0x02` and `0x04` are recorded from source only, the receipt shape for a
  reverted transaction was not seen, and no `status: 0` receipt was inspected.
* **The exact fraud-proof verification cost and the slash fraction.**
  `SlashedReason::InvalidBundle` is established; what proportion of an operator's
  stake (and of its nominators' stake) is actually removed was not read out of
  `staking.rs`.
* **The `0x0800` Transporter ABI.** Only that it exists, reverts on short
  calldata, and exposes `transfer_to_consensus_v1`. Selectors and gas were not
  enumerated.

---

## Re-verify

### Clone pins

```sh
git clone --depth 1 --branch runtime-mainnet-2026-jul-29 --single-branch \
    https://github.com/autonomys/subspace chains/autonomys/repos/subspace
git -C chains/autonomys/repos/subspace rev-parse HEAD
# f76e41c2ddcca4828c4a955ac44c7816b1bccd1b

# companions are pinned to revisions, not tags — fetch the exact rev
git init chains/autonomys/repos/frontier && \
  git -C chains/autonomys/repos/frontier remote add origin https://github.com/polkadot-evm/frontier && \
  git -C chains/autonomys/repos/frontier fetch --depth 1 origin 9d49e36ed5bac38241594f8ba055fdb94991483a && \
  git -C chains/autonomys/repos/frontier checkout FETCH_HEAD

git init chains/autonomys/repos/rust-evm && \
  git -C chains/autonomys/repos/rust-evm remote add origin https://github.com/rust-ethereum/evm && \
  git -C chains/autonomys/repos/rust-evm fetch --depth 1 origin a656db9050c65170b050360c3fa66c0fd8bf226a && \
  git -C chains/autonomys/repos/rust-evm checkout FETCH_HEAD
```

### Source

```sh
cd chains/autonomys/repos

# stock Frontier, not a fork: every crate at one upstream rev, no [patch] for it
grep -c 'polkadot-evm/frontier' subspace/Cargo.toml
sed -n '/paritytech\/polkadot-sdk.git/,+4p' subspace/Cargo.toml

# the whole precompile set — eight entries
sed -n '/precompile_name_from_address/,/^);/p' subspace/domains/primitives/evm-precompiles/src/lib.rs

# the fork is a constant
grep -n 'EVM_CONFIG' frontier/primitives/evm/src/lib.rs
# 43: pub static EVM_CONFIG: Config = Config::osaka();
sed -n '/const fn osaka() -> Self/,/^	}/p' rust-evm/runtime/src/lib.rs   # no blob-opcode flags

# ordering: the bundle validity taxonomy
sed -n '/^pub enum InvalidBundleType/,/^}/p' subspace/crates/sp-domains/src/bundle.rs
grep -n 'excluded from execution' subspace/crates/sp-domains/src/bundle.rs

# ordering: an invalid bundle contributes zero extrinsics
grep -n 'BundleValidity::Invalid' -A3 subspace/domains/client/block-preprocessor/src/lib.rs

# execution: the slash
grep -n 'SlashedReason::InvalidBundle' subspace/crates/pallet-domains/src/lib.rs
sed -n '/pub enum SlashedReason/,/^    }/p' subspace/crates/pallet-domains/src/lib.rs
grep -n 'invalid_bundle_authors.push' -B3 subspace/crates/pallet-domains/src/block_tree.rs

# fraud-proof variants
sed -n '/pub enum FraudProofVariant/,/^}/p' subspace/crates/sp-domains-fraud-proof/src/fraud_proof.rs

# challenge window
grep -n 'domain_block_pruning_depth: 14_400' subspace/crates/subspace-runtime-primitives/src/lib.rs

# no pallet-base-fee; the fee calculator instead
sed -n '/^construct_runtime!/,/^);/p' subspace/domains/runtime/evm/src/lib.rs | grep 'pallet_'
grep -n 'fn min_gas_price' -A15 subspace/domains/pallets/evm-tracker/src/fees.rs

# coinbase, gas mapping, blockhash window, existential deposit
grep -n 'FindAuthorTruncated' -A8 subspace/domains/runtime/evm/src/lib.rs
grep -n 'GAS_PER_SECOND\|WEIGHT_PER_GAS\|GasLimitPovSizeRatio\|StorageFeeRatio' subspace/domains/primitives/evm-tracker/src/lib.rs
grep -n 'BlockHashCount: BlockNumber' subspace/domains/runtime/evm/src/lib.rs      # 2400
grep -n 'move block hash pruning window' -A8 frontier/frame/ethereum/src/lib.rs
grep -n 'EXISTENTIAL_DEPOSIT' subspace/domains/primitives/runtime/src/lib.rs       # 1_000_000_000_000
grep -n 'does not serve as a limit' -B2 -A4 subspace/domains/primitives/runtime/src/lib.rs
```

### Live probes

All against `R=https://auto-evm.mainnet.autonomys.xyz/ws` (note the `/ws` path —
the bare host 404s; it accepts ordinary HTTP POSTs).

```sh
R=https://auto-evm.mainnet.autonomys.xyz/ws
rpc(){ curl -s -X POST -H 'content-type: application/json' \
  --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}" $R; echo; }

rpc eth_chainId '[]'                 # 0x366  (870)
rpc web3_clientVersion '[]'          # subspace-evm-domain/v4.0/fc-rpc-2.0.0-dev
rpc system_chain '[]'                # "Autonomys Mainnet Domain 0"  <- Substrate RPC, same port
rpc state_getRuntimeVersion '[]'     # specName subspace-evm-domain, specVersion 4
rpc eth_getProof '["0x0000000000000000000000000000000000000001",[],"latest"]'   # Method not found
```

**Finality lag** (finding 4) — run both in the same second:

```sh
rpc eth_blockNumber '[]'
rpc eth_getBlockByNumber '["finalized",false]' | python3 -c \
  'import sys,json;print(int(json.load(sys.stdin)["result"]["number"],16))'
# observed: latest 4580360, finalized 4565366  ->  14,994 blocks
```

**Precompiles** (findings 6, 7) — `B=0x45d995`:

```sh
B=0x45d995
call(){ curl -s -X POST -H 'content-type: application/json' \
  --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"$1\",\"data\":\"$2\"},\"$B\"]}" $R; echo; }
code(){ curl -s -X POST -H 'content-type: application/json' \
  --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$1\",\"$B\"]}" $R; echo; }

call 0x0000000000000000000000000000000000000004 0xdeadbeef   # 0xdeadbeef      (present)
call 0x0000000000000000000000000000000000000008 0x           # 0x  <- mainnet returns 32 bytes ending 01
call 0x0000000000000000000000000000000000000006 0x$(printf '0%.0s' $(seq 256))   # 0x  <- mainnet: 64 zero bytes
call 0x0000000000000000000000000000000000000100 0x$(printf '0%.0s' $(seq 320))   # 0x  (P256VERIFY absent)
call 0x0000000000000000000000000000000000000400 0x           # 0xa7ffc6f8...8434a  (SHA3-256 of "")
call 0x0000000000000000000000000000000000000800 0x           # revert "Tried to read selector out of bounds"

for a in 01 02 03 04 05 06 07 08 09 0a 0b 0c 0d 0e 0f 10 11; do
  code 0x00000000000000000000000000000000000000$a; done
# 01-05 -> 0x60006000fd ;  06-11 -> 0x
code 0x0000000000000000000000000000000000000400   # 0x60006000fd
code 0x0000000000000000000000000000000000000800   # 0x            <- live precompile, no stub
code 0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02   # 0x  (EIP-4788 absent)
code 0x0000F90827F1C53a10cb7A02335B175320002935   # 0x  (EIP-2935 absent)
```

**Opcodes** (findings 9, 10, 11) — `eth_call` with no `to` runs the payload as
init code and returns what it `RETURN`s. Tail `5f5260205ff3` =
`PUSH0 MSTORE PUSH1 0x20 PUSH0 RETURN`:

```sh
mk(){ curl -s -X POST -H 'content-type: application/json' \
  --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"0x$1\"},\"$B\"]}" $R; echo; }

mk 465f5260205ff3            # CHAINID     -> ...0366
mk 445f5260205ff3            # PREVRANDAO  -> 0x00...00      (always)
mk 415f5260205ff3            # COINBASE    -> 0x00...00      (always)
mk 485f5260205ff3            # BASEFEE     -> 0x2c1bfe804    (== eth_gasPrice)
mk 60011e5f5260205ff3        # CLZ(1)      -> 0xff           (EIP-7939 live)
mk 5f5c5f5260205ff3          # TLOAD       -> 0x00...00      (executes)
mk 495f5260205ff3            # BLOBHASH    -> InvalidCode(Opcode(73))
mk 4a5f5260205ff3            # BLOBBASEFEE -> InvalidCode(Opcode(74))

# BLOCKHASH window: PUSH3 d, NUMBER, SUB, BLOCKHASH, then the tail
for d in 000100 000101 000960 000961; do mk "62${d}4303405f5260205ff3"; done
# n-256  -> 0x6fc65707...      n-257  -> 0x29ecca7b...   (mainnet: zero)
# n-2400 -> 0xa8f0a15f...      n-2401 -> 0x00...00
```

**Base fee is not 1559** (finding 8):

```sh
rpc eth_feeHistory '["0x2","latest",[50]]'
# oldestBlock 0x45d9b6, baseFeePerGas [0x2c1bfedd4, 0x2c1bfee06, 0x26987f045],
# gasUsedRatio [0.0, 0.0]
#   -> two EMPTY blocks and the base fee ROSE; the trailing element is fc-rpc's
#      1559 projection (-12.5%) and is not what the chain will use
rpc eth_maxPriorityFeePerGas '[]'    # 0x0
```

**Header shape** (finding 11, header_fields):

```sh
rpc eth_getBlockByNumber '["0x45d995",false]' | python3 -c \
  'import sys,json;print(sorted(json.load(sys.stdin)["result"]))'
# no withdrawalsRoot, blobGasUsed, excessBlobGas, parentBeaconBlockRoot,
# requestsHash or mixHash;  author == miner == 0x0000...0000;  gasLimit 0x3197500
```

**Mindshare** (the `CANDIDATES.md` verdict) — reproduce the empty-chain sample:

```sh
for n in $(seq 4580200 4580360); do
  curl -s -X POST -H 'content-type: application/json' \
    --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$(printf '0x%x' $n)\",true]}" $R \
  | python3 -c 'import sys,json;t=json.load(sys.stdin)["result"]["transactions"];print(len(t)) if t else None'
done | wc -l          # 0 — no block in the range carried a transaction
```

### Validate

```sh
tools/.venv/bin/python -c "import yaml;yaml.safe_load(open('chains/autonomys/chain.yaml'))"
tools/.venv/bin/python tools/verify.py 2>&1 | sed -n '/^autonomys/,/^$/p'
# autonomys  (subspace (Auto EVM domain runtime) runtime-mainnet-2026-jul-29)
#   pin ok  f76e41c2
#   ! NO EXTRACTOR — precompile list NOT cross-checked against source
#   citations ok    62 symbol(s) confirmed, 0 line ref(s) in range
#   evidence  src=37  src_live=14  none=6
```
