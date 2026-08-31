# Moonbeam

**Role:** `independent` (`equivalence: behavioural`) · **Upstream:** none · **Chain ID:** 1284 · **Baseline:** Osaka
**Client:** [`moonbeam-foundation/moonbeam`](https://github.com/moonbeam-foundation/moonbeam) `runtime-4401`
(`c6d58748be27e40126788c3eca48234e85a6e6ec`), Rust
**Companions:** [`moonbeam-foundation/frontier`](https://github.com/moonbeam-foundation/frontier)
`0d6d5b8fed14f70216ddd8dd7823c30510460f47` ·
[`Moonsong-Labs/moonkit`](https://github.com/Moonsong-Labs/moonkit) `8fae4417637f8e55ea04b3548809d7f1c22daf64`
**Live probes:** `https://moonbeam.api.onfinality.io/public` @ block `16790908`

Moonbeam is a Polkadot parachain whose EVM is a module inside a WASM state machine.
`pallet-evm` embeds the `evm` (rust-evm) interpreter, `pallet-ethereum` *synthesises*
an Ethereum block from the extrinsics that executed, and the JSON-RPC layer serves
that synthetic block. Nothing here descends from an Ethereum client.

---

## 0. The framing decision, and why the brief's two options were both declined

The brief offered (a) one `moonbeam` row with `role: fork` folding Frontier in, or
(b) a `frontier` row with `role: template` plus a `moonbeam` row inheriting from it.
This row is neither: it is **one row with `role: independent`**. Three findings drove
that, and each is a fact about the code rather than a preference.

**Moonbeam does not use `polkadot-evm/frontier`.** Every Frontier crate in
`Cargo.toml` — `pallet-evm`, `pallet-ethereum`, `fp-evm`, `fp-rpc`, `precompile-utils`,
the whole `fc-*` client stack — points at `github.com/moonbeam-foundation/frontier`,
branch `moonbeam-polkadot-stable2512`, which `Cargo.lock` resolves to
`0d6d5b8fed14f70216ddd8dd7823c30510460f47`. A `template` row pinned to upstream
Frontier would be evidence for a codebase this chain does not run; a `template` row
pinned to Moonbeam's private fork would be a shared node with exactly one descendant.

**The fork is where Moonbeam's own framework lives, not a rebase with patches.**
`precompiles/src/precompile_set.rs` in that fork — the `PrecompileSetBuilder`, the
`AcceptDelegateCall` / `CallableByContract` / `CallableByPrecompile` checks,
`RemovedPrecompileAt` — carries `Copyright (c) Moonsong Labs` and has no upstream
counterpart. Astar and other upstream-Frontier chains do not have it. "Frontier" is
not one shared artefact that several rows could point at.

**Every value that produces a delta is in `runtime/moonbeam/src/`, not in the pallet.**
The precompile address map, the Weight↔gas ratio, `IdentityAddressMapping` (Frontier's
own default is the 32-byte-hashing `HashedAddressMapping`), the runtime call filter,
the fee handler, the per-transaction gas cap. Frontier supplies mechanism; Moonbeam
supplies the numbers. A `template` node would hold almost nothing.

And `role`: the dataset's own line is that `fork` means *the EVM interpreter is a fork
of a mainnet client* — Sei and Kaia fork geth and are `fork`; Monad, zkSync Era,
Hyperliquid and Tron reimplement and are `independent`. Moonbeam's interpreter is
`rust-evm`, shared with no Ethereum client. Its EIP set is asserted by a constant
(`Config::osaka()`) in a crate that is not even in the tree, so it can only be checked
behaviourally — which is exactly what `equivalence: behavioural` is for. Note this
also makes Moonbeam the fifth `independent` row and the first that got there by
*embedding* an EVM library rather than by writing one.

Revisit if a second Frontier chain lands **and** shares an upstream with this one.
Astar currently would not.

---

## 1. The EVM was switched off at the observed block, by a Substrate call filter

The runtime's `BaseCallFilter` is `MaintenanceMode`. Its maintenance variant returns
`false` for `RuntimeCall::Ethereum(_)` and `RuntimeCall::EVM(_)`, and the runtime's
`validate_transaction` rejects filtered calls *before they reach the pool*
(`runtime/moonbeam/src/lib.rs:MaintenanceFilter`, and the filter gate inside
`impl_runtime_apis_plus_common!`). At block `16790908` the chain was in that state.

Three independent live observations, none of which requires trusting the other two:

| probe | result |
|---|---|
| block scan, the 40 blocks ending at the pinned block `16790908` | **zero transactions, `gasUsed 0x0` in every one** |
| `eth_getLogs` over three separate 500-block windows | **zero logs** |
| last block carrying any transaction | `16672926`; block `16672927` has timestamp `2026-08-01T00:01:30Z` |

And a discriminator that rules out "the chain is merely idle": dispatching through the
precompiles reproduces `MaintenanceFilter`'s block-list **exactly**.

```
0x0802 transfer(address,uint256)  -> revert "... Some(\"CallFiltered\")"   # Balances: blocked
0x0800 goOffline()                -> revert "... Some(\"CallFiltered\")"   # ParachainStaking: blocked
0x0812 removeVote(uint32)         -> revert "... Some(\"ClassNeeded\")"    # ConvictionVoting: reaches pallet
0x0813 unnotePreimage(bytes32)    -> revert "... Some(\"NotNoted\")"       # Preimage: reaches pallet
0x0807 removeKeys()               -> revert "... Some(\"OldAuthorIdNotFound\")"
0x0810 close(...)                 -> revert "... Some(\"ProposalMissing\")"
```

Under `NormalFilter` both Balances and ParachainStaking are permitted (`_ => true`),
so this pattern has exactly one explanation. The last EVM activity stops on a round
UTC midnight, which is not what congestion looks like.

**Why this matters beyond Moonbeam:** `eth_call`, `eth_getCode`, `eth_estimateGas`,
`eth_chainId`, `eth_blockNumber` and `eth_getBalance` all answer normally throughout,
because they go through the runtime API rather than through the extrinsic filter. A
monitor that polls RPC health sees a perfectly healthy chain producing blocks while
**no transaction can be included at all**. The dataset has liveness failures
elsewhere; it does not yet have a *governance-flippable EVM kill switch whose
off-state is invisible to the Ethereum RPC surface*.

## 2. `eth_getCode` is wrong in **both** directions, and the code is written by anyone

The dataset already knows that code at a precompile address does not disprove
precompile-ness (Flare's `0x01`, Sonic, Cosmos EVM's 24KB ERC-20 runtime). Moonbeam
adds the converse and a mechanism nobody else has.

`PrecompileRegistry` at `0x0815` exposes `updateAccountCode(address)`, which writes
`DUMMY_CODE = [0x60, 0x00, 0x60, 0x00, 0xfd]` (`PUSH1 0 PUSH1 0 REVERT`) into the
account of any address that is a precompile — **permissionlessly, from any caller**
(`precompiles/precompile-registry/src/lib.rs:DUMMY_CODE`). The code is never executed;
the precompile intercepts first. What it changes is everything *observed from outside
the call*:

```
eth_getCode(0x01) @ 16790908       -> 0x60006000fd        # mainnet returns 0x
EXTCODESIZE(0x01)                  -> 5                   # mainnet returns 0
EXTCODEHASH(0x01)                  -> 0x9c8d1cd1...4051 = keccak(0x60006000fd)
```

Because it is opt-in per address and permissionless, the set that carries it is
**historical accident, not protocol**:

| carries dummy code | empty (`0x`) despite being a precompile |
|---|---|
| `0x01`–`0x09`, `0x0400`–`0x0402`, `0x0800`–`0x0815`, `0x0817`, `0x081a` | `0x0b`–`0x11` (BLS12-381), `0x0100` (P256VERIFY), `0x0816`, `0x0818`, `0x0819` |

and the **tombstoned** addresses `0x0401`, `0x0803`, `0x080e`, `0x080f` carry code
*and* revert. So: nine of mainnet's own precompiles report as contracts; seven
genuine EIP-2537 precompiles report as EOAs; four dead addresses report as contracts
that always fail. Every `addr.code.length == 0` EOA guard, `isContract()` check and
`extcodehash == 0` test gives the opposite answer to mainnet for some of these, with
no revert and no signal. The reliable oracle is `0x0815`'s `isActivePrecompile`,
which is also the only way to tell a tombstone from a live precompile without calling
it: `isPrecompile(0x0401) -> true`, `isActivePrecompile(0x0401) -> false`.

## 3. Precompiles that change consensus state — and a caller-class dimension the schema has not met

`0x0800` (ParachainStaking) is the strongest instance of the "stateful precompile"
theme so far. `joinCandidates`, `delegateWithAutoCompound`, `candidateBondMore`,
`goOffline` and eighteen other selectors build a `pallet_parachain_staking::Call`,
wrap the EVM caller in `RawOrigin::Signed`, and dispatch it
(`precompiles/parachain-staking/src/lib.rs:join_candidates` →
`frontier/precompiles/src/substrate.rs:try_dispatch`). A `CALL` from a Solidity
contract bonds stake, changes the collator set and alters who may author blocks —
**consensus-level, non-EVM state**. Nineteen more precompiles do the equivalent for
governance (`0x0811`, `0x0812`, `0x0813`), for cross-chain messaging (`0x0804`,
`0x0806`, `0x080d`, `0x0817`, `0x081a`), for block-author key registration
(`0x0807`), and for the native token's balance ledger (`0x0802`).

**STATICCALL safety holds, structurally.** `#[precompile::view]` is the only thing
that permits execution in a static context; `check_function_modifier` rejects
everything else. Verified in both directions live: `round()` returns under
STATICCALL, while `goOffline()` and `candidateBondMore(uint256)` revert with exactly
`Can't call non-static function in static context` — and the *same* selectors under
`CALL` get past the modifier and reach the Substrate dispatcher. Unlike Cosmos EVM, no
view-shaped method was found misclassified as a transaction.

**Two access dimensions mainnet has no concept of**, both enforced in
`frontier/precompiles/src/precompile_set.rs:common_checks` before any input parsing:

- **DELEGATECALL is refused** by the whole Moonbeam band. `DELEGATECALL` to `0x0800`
  reverts `Cannot be called with DELEGATECALL or CALLCODE`; `DELEGATECALL` to `0x04`
  and `0x0100` succeeds, because only the Ethereum band carries `AcceptDelegateCall`.
- **Callers are filtered by class.** `Batch` (`0x0808`) has no `CallableByContract` at
  all and `CallableByPrecompile<OnlyFrom<0x0808>>` — an EOA-only precompile that the
  only precompile allowed to call is itself. `GMP` (`0x0816`) is likewise EOA-only.
  A contract calling either gets `Function not callable by smart contracts`.

Neither is expressible in the current schema (`status`/`availability`/`adoption` have
no axis for "who may call"), so both are recorded in prose on the entries.

## 4. Four meters, one of which is gas; and the ratio is a compile-time constant

Two meters was the expectation. There are four.

| meter | budget | source |
|---|---|---|
| EVM gas | 35,000,000 per tx, 60,000,000 per block | `TX_MAX_GAS_LIMIT`, `BlockGasLimit` |
| Substrate `ref_time` | gas × 25,000 ps | `WEIGHT_PER_GAS = WEIGHT_REF_TIME_PER_SECOND / GAS_PER_SECOND = 1e12 / 40e6` |
| PoV proof size | gas ÷ 8 | `GasLimitPovSizeRatio` |
| storage growth | gas ÷ 366 | `GasLimitStorageGrowthRatio`, MBIP-5 |

The Weight↔gas ratio the brief asked about is **a compile-time constant, not an
on-chain parameter**: `FixedGasWeightMapping::weight_to_gas` is literally
`ref_time / 25_000`. It is load-bearing — the observed header `gasLimit` is
`0x3938700` = 60,000,000 = `0.75 × 2e12 / 25_000`, exactly.

Consequences for `eth_estimateGas`. Meters 3 and 4 are charged separately by
`record_external_operation` (account reads, code reads, writes) and fail as
`ExitError::OutOfGas`. A transaction can therefore abort "out of gas" **with EVM gas
remaining**, because it exhausted proof size or storage-growth budget instead, and
nothing in the receipt distinguishes the three cases. Estimation must satisfy the
*binding* meter, so two contracts with identical EVM gas profiles can differ by an
order of magnitude in what estimation returns.

And every dispatching precompile charges the pallet's **benchmarked weight** back to
the EVM through that ratio, so its gas price is a wall-clock measurement divided by a
constant. `P256VERIFY` shows the size of the effect on a non-dispatching precompile:
`P256VerifyGas = weight_to_gas(p256_verify())` where the benchmark records
`1_773_662_000` ps, giving **70,946 gas** — about 10× EIP-7951's 6,900 and 20×
RIP-7212's 3,450. Measured live and it agrees:

```
eth_estimateGas(0x0100, RIP-7212 vector)  = 94812
  minus intrinsic (21000 + 16*158 + 4*2)  = 23536   ->  71276
  minus the 330-gas estimator constant measured on an identity control  ->  70946
```

## 5. Transactions with no signature that can be recovered, and value that moves with no log

**`tx_authorization`.** The 20-byte account claim is true and stronger than advertised:
`AccountId` is `AccountId20`, keccak-derived from a secp256k1 key exactly as on
Ethereum, and pallet-evm uses `IdentityAddressMapping` — the H160 *is* the AccountId,
no hashing step, so Frontier's usual hazard (a 32-byte account holding funds the EVM
cannot see) does not exist here. sr25519 and ed25519 cannot authorise anything, and
the code says so by **panicking**: `EthereumSignature`'s `From<MultiSignature>` impl
has `panic!("Ed25519 not supported")` and `panic!("Sr25519 not supported")` arms.
Both are `authorizes: never, precompile: none` — and there is not even a verifier,
since Moonbeam does not install Frontier's ed25519 precompile.

Two consequences, one in each direction:

- **One key, two envelopes, one nonce.** The same secp256k1 key signs Ethereum
  transactions *and* Substrate extrinsics, and because pallet-evm is configured with
  `FrameSystemAccountProvider` the EVM nonce **is** the `frame_system` account nonce.
  A staking extrinsic bumps the number `eth_getTransactionCount` returns.
- **`xcm_origin`: `authorizes: protocol` with `precompile: none`** — the pairing
  SCHEMA.md names as the finding to look for. `pallet-ethereum-xcm` turns a message
  from another parachain into an `EIP1559Transaction` with
  `r = s = H256::from_low_u64_be(1)` — a fixed, deliberately invalid signature
  (`primitives/xcm/src/ethereum_xcm.rs:rs_id`) — and stores it in the Ethereum block.
  Over JSON-RPC it is an ordinary type-`0x02` transaction with a `from`, an `r` and an
  `s`; `ecrecover` over it does not yield `from` and never can. Its `nonce` is a
  chain-global counter, not the sender's. `transact_through_proxy` widens it: the XCM
  origin may execute as any *local* account that granted it a zero-delay
  `ProxyType::Any` proxy, so `msg.sender` becomes an address that signed nothing.
  `force_transact_as` lets Root do it with no proxy at all.

**`non_evm_transactions`, and which shape.** Moonbeam has **both** precedents at once.
`Ethereum::transact` is the cosmos-evm shape — an EIP-2718 payload surviving
byte-exact inside a SCALE extrinsic, signature-checked by `check_self_contained` — and
it is not an edge case, it is how 100% of Ethereum traffic arrives. `EthereumXcm::transact`
is the Tron shape: a native non-Ethereum call (`gas_limit`, `action`, `value`, `input`,
`access_list`; no signature field to omit, because there never was one) that produces
EVM execution. The textbook third path is **closed**: `pallet_evm::Call::call` is
unreachable by anyone, because `NormalFilter` has `RuntimeCall::EVM(_) => false`
unconditionally with a comment citing re-entrancy.

**Value that moves with no transaction, receipt or log.** When XCM delivers a foreign
asset, the runtime executes `mintInto(address,uint256)` on that asset's ERC-20
contract through `EvmRunner::call` (`pallets/moonbeam-foreign-assets/src/evm.rs:erc20_mint_into`).
This is real EVM execution — it runs bytecode and the contract genuinely emits a
`Transfer` event. But `pallet_ethereum::store_block` builds receipts only from the
`Pending` map, which holds transactions that came through `Ethereum::transact`. A call
that never went through that path has **no receipt**, so its logs cannot appear in
`eth_getLogs` or in any receipt. A balance changes, a `Transfer` is emitted, and a
log-following indexer sees nothing. `erc20_transfer`, `erc20_approve` and
`erc20_create` run through the same door.

Those foreign assets are also **system contracts, not precompiles**: real ERC-20
bytecode deployed by the runtime with `EvmRunner::create_force_address` — a CREATE at
a chosen address, bypassing both CREATE and CREATE2 derivation — at
`0xffffffff ++ asset_id`. On the same chain, then, two token interfaces of opposite
kinds: foreign assets are contracts with full bytecode, while the *native* token's
ERC-20 face at `0x0802` is a precompile with five bytes of dummy code.

## 6. Smaller things that contradict or extend existing claims

- **A fifth fork-activation mechanism**, and it defeats all four in README. Moonbeam
  has no fork names, no `*Time` fields, no `*Block` numbers and no client-side fork
  gate. `fp-evm` hardcodes `pub static EVM_CONFIG: Config = Config::osaka()`, and the
  ruleset changes only when governance replaces the WASM runtime — *which is a value
  in state*. A node that never updates its binary follows the new rules. The only
  fork identifier is `spec_version`, and it is not exposed over the Ethereum RPC
  namespace at all.
- **Osaka minus all of 4844, minus the whole system-contract half of Cancun/Prague.**
  PUSH0, TLOAD/TSTORE, MCOPY, BASEFEE, BLS12-381 and EIP-7702 all verified live.
  `BLOBHASH` and `BLOBBASEFEE` are **invalid opcodes**, not zero-returning stubs
  (`InvalidCode(Opcode(73))` / `(74)`), there is no `0x03` transaction type, and
  `0x0a` is absent. All four of `0x000F3df6…Beac02` (4788), `0x0000F908…2935`,
  `0x00000961…7002` and `0x0000BBdD…7251` return `0x`.
- **`0x0a` fails in the opposite direction to the P256VERIFY trap the dataset already
  tracks.** With no precompile at `0x0a`, a call *succeeds* with empty output. On
  mainnet, KZG point evaluation **reverts** for an invalid proof. So a contract that
  checks only the success flag concludes that every proof verifies — absence
  masquerading as *acceptance*, where the P256 case is absence masquerading as
  *rejection*.
- **EIP-7825 is present but re-parameterised.** Frontier's default `TransactionGasLimit`
  is `MAX_TRANSACTION_GAS_LIMIT` = 2^24, exactly EIP-7825; Moonbeam overrides it with
  `TX_MAX_GAS_LIMIT = 35_000_000`. Transactions between 16.78M and 35M gas are valid
  here and invalid on mainnet.
- **EIP-155 is mandatory.** `AllowUnprotectedTxs = false`, so a legacy transaction with
  no chain id is rejected outright. Mainnet still accepts them.
- **`baseFeePerGas` is not a 1559 base fee.** It is Substrate's transaction-payment
  congestion multiplier re-denominated into wei/gas, updated by `TargetedFeeAdjustment`
  against a **35%** fullness target with `AdjustmentVariable` 4/1000 — not 1559's
  ±12.5% step against 50%. It also responds to *total* block weight, so non-EVM
  Substrate traffic moves the EVM base fee. Any estimator predicting the next base fee
  from parent `gasUsed` is wrong on every block, silently.
- **There is no Ethereum header.** `pallet_ethereum::store_block` builds one at the end
  of each block and stores it in state. `stateRoot` is `sp_io::storage::root(...)` —
  the **Substrate storage root**, useless with any Ethereum state proof — and the
  `parentHash` chain is a second, independent hash chain unrelated to the Substrate
  block hashes that actually secure the chain. The RPC block has no `mixHash`,
  `withdrawalsRoot`, `blobGasUsed`, `excessBlobGas`, `parentBeaconBlockRoot` or
  `requestsHash`, and adds a non-standard `author`.
- **Moonbeam runs its own spec series, the MBIPs, in-tree.** One accepted (MBIP-5, the
  storage-growth meter), five rejected. Recorded under `non_eip_specs`.
- **The pin is the runtime, not the client.** The newest *client* tag `v0.52.3` carries
  `spec_version: 4400`; the live chain reports `4401`, which is the `runtime-4401`
  tag. On this chain the client tag and the consensus rules are separate release
  series, and pinning the client would have pinned rules the network is not running.

## Not established here

- **Fork timeline.** Only the current `spec_version` (4401) is pinned. Which EVM
  ruleset each earlier runtime carried, and the block at which each was enacted, is
  `unrecorded` — deriving it means bisecting `spec_version` across ~16.8M blocks.
- **EIP-7623.** The identity-precompile estimate matches the 7623 calldata floor plus a
  constant, but the floor was not isolated from the estimator's own 330-gas constant.
  Left `unrecorded` rather than asserted.
- **The invisible-log claim is source-derived, not probed.** `store_block` demonstrably
  builds receipts only from `Pending`, but no XCM mint could be observed live: the EVM
  has been quiescent since block 16672926.
- **Precompile-level detail** for Randomness (`0x0809`), GMP (`0x0816`), CallPermit
  (`0x080a`) and RelayDataVerifier (`0x0819`) is recorded as presence and access
  rules only; their semantics were not read in depth.
- **`Erc20XcmBridge`** (XCM transferring ordinary ERC-20s by calling them) is
  configured and referenced but not analysed.
- **The documented endpoint `https://rpc.api.moonbeam.network` was unreachable** from
  this environment (repeated TCP connect timeouts while other hosts answered). Two
  independent providers — onfinality and `1rpc.io/glmr` — agreed on chain id, head
  height, head timestamp and finalized height, so every probe below reproduces on
  either; but nothing here was taken from the official endpoint.

## Re-verify

```sh
# from the repo root
tools/.venv/bin/python tools/verify.py 2>&1 | sed -n '/^moonbeam/,/^$/p'
# -> pin ok c6d58748 / citations ok / "! NO EXTRACTOR" is expected for a new slug

R=https://moonbeam.api.onfinality.io/public     # 1rpc.io/glmr works too, minus state_*
B=0x100357c                                     # 16790908

# the pin is the runtime the network is actually running
curl -s -X POST $R -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"state_getRuntimeVersion","params":[]}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["specVersion"])'
# -> 4401     ... and:
grep -n 'spec_version' chains/moonbeam/repos/moonbeam/runtime/moonbeam/src/lib.rs | head -1

# Frontier is Moonbeam's OWN fork, at the revision Cargo.lock resolves
grep -n 'moonbeam-foundation/frontier' chains/moonbeam/repos/moonbeam/Cargo.lock | sed 's/.*source = //' | sort -u
# -> "git+https://github.com/moonbeam-foundation/frontier?branch=moonbeam-polkadot-stable2512#0d6d5b8..."

# the baseline is a constant, not a schedule
grep -rn 'EVM_CONFIG: Config' chains/moonbeam/repos/frontier/primitives/evm/src/lib.rs
# -> pub static EVM_CONFIG: Config = Config::osaka();

# --- the dummy code, and that it is written by a permissionless precompile ---
grep -n 'DUMMY_CODE' chains/moonbeam/repos/moonbeam/precompiles/precompile-registry/src/lib.rs
for a in 0000000000000000000000000000000000000001 \
         000000000000000000000000000000000000000b \
         0000000000000000000000000000000000000100 \
         0000000000000000000000000000000000000401 \
         0000000000000000000000000000000000000816 ; do
  printf '%s ' $a
  curl -s -X POST $R -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x$a\",\"$B\"]}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"])'
done
# -> 0x01 0x60006000fd | 0x0b 0x | 0x0100 0x | 0x0401 0x60006000fd | 0x0816 0x

# the registry tells live from tombstoned where getCode cannot
# isPrecompile(0x0401) / isActivePrecompile(0x0401)
curl -s -X POST $R -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x0000000000000000000000000000000000000815","data":"0x446b450e0000000000000000000000000000000000000000000000000000000000000401"},"0x100357c"]}'
curl -s -X POST $R -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x0000000000000000000000000000000000000815","data":"0x6f5e23cf0000000000000000000000000000000000000000000000000000000000000401"},"0x100357c"]}'
# -> ...0001 (is a precompile)  then  ...0000 (is not ACTIVE)

# --- opcode probes. eth_call with no `to` runs the payload as initcode and
# --- returns whatever it RETURNs, so arbitrary bytecode can be executed read-only.
probe () { curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"$1\"},\"$B\"]}"; echo; }
probe 0x602a5f5260206000f3                      # PUSH0            -> 0x..2a
probe 0x602a60005d60005c60005260206000f3        # TSTORE/TLOAD     -> 0x..2a
probe 0x602a6000526020600060205e60206020f3      # MCOPY            -> 0x..2a
probe 0x60004960005260206000f3                  # BLOBHASH         -> error InvalidCode(Opcode(73))
probe 0x4a60005260206000f3                      # BLOBBASEFEE      -> error InvalidCode(Opcode(74))
probe 0x60013b60005260206000f3                  # EXTCODESIZE(0x01)-> 5

# --- STATICCALL protection on a state-writing precompile.
# calldata = selector<<224 at mem[0]; STATICCALL(gas,0x0800,0,4,0x40,0x20);
# returns 32-byte success flag followed by the returndata.
probe 0x63a6485ccd60e01b60005260206040600460006108005afa608052 3d6000 60a03e 3d6020016080f3
# (whitespace above is for reading only — concatenate before sending)
# STATICCALL goOffline() -> success 0, revert string "Can't call non-static function in static context"
# swap `fa` for `f1` (adding a 6000 value push before the address) to see the CALL
# path instead: "Dispatched call failed ... Some(\"CallFiltered\")"

# --- the maintenance-mode finding: filtered vs unfiltered pallets ---
grep -n -A16 'pub struct MaintenanceFilter' chains/moonbeam/repos/moonbeam/runtime/moonbeam/src/lib.rs
# Balances / ParachainStaking / Ethereum / EVM => false
curl -s -X POST $R -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x0000000000000000000000000000000000000800","data":"0xa6485ccd"},"0x100357c"]}'
# -> revert ... Some("CallFiltered")            (ParachainStaking, blocked in maintenance)
curl -s -X POST $R -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x0000000000000000000000000000000000000813","data":"0x02e71b450000000000000000000000000000000000000000000000000000000000000000"},"0x100357c"]}'
# -> revert ... Some("NotNoted")                (Preimage, NOT blocked)

# no EVM traffic at all since 16672926
curl -s -X POST $R -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getLogs","params":[{"fromBlock":"0x10031f0","toBlock":"0x10033e4"}]}' \
  | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["result"]),"logs")'
# -> 0 logs   (blocks 16790000-16790500, ~117k blocks after the cutoff)

# tx-type census in the last window that had traffic
python3 - <<'EOF'
import json,urllib.request
from collections import Counter
R="https://moonbeam.api.onfinality.io/public"
def c(m,p):
    r=urllib.request.Request(R,data=json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),
                             headers={"content-type":"application/json"})
    return json.load(urllib.request.urlopen(r,timeout=30))["result"]
n=Counter()
for b in range(16672830,16672960):
    blk=c("eth_getBlockByNumber",[hex(b),True])
    if blk: n.update(t.get("type") for t in blk["transactions"])
print(n)     # -> Counter({'0x0': 70, '0x2': 34, '0x4': 1})
EOF

# the EIP-7702 transaction, and the Weight->gas constants
curl -s -X POST $R -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getTransactionByHash","params":["0x7d35d07aa06b004099fe18da475c741dd3ce25e8543cfc2a094ac2b82b2db2a8"]}' \
  | python3 -c 'import json,sys; t=json.load(sys.stdin)["result"]; print(t["type"], t["authorizationList"])'
grep -n 'GAS_PER_SECOND\|WEIGHT_PER_GAS\|GasLimitPovSizeRatio\|GasLimitStorageGrowthRatio' \
  chains/moonbeam/repos/moonbeam/runtime/moonbeam/src/lib.rs | head
grep -n 'TX_MAX_GAS_LIMIT' chains/moonbeam/repos/moonbeam/runtime/common/src/lib.rs
grep -n -A8 'fn p256_verify' chains/moonbeam/repos/moonbeam/runtime/moonbeam/src/weights/pallet_precompile_benchmarks.rs
# 1_773_662_000 / 25_000 = 70_946 gas

# sr25519/ed25519 cannot sign anything here — the code panics rather than erroring
grep -n 'not supported for EthereumSignature' chains/moonbeam/repos/moonbeam/primitives/account/src/lib.rs

# the XCM path's fixed invalid signature, and the closed EVM::call path
grep -n -A3 'pub fn rs_id' chains/moonbeam/repos/moonbeam/primitives/xcm/src/ethereum_xcm.rs
grep -n 'RuntimeCall::EVM(_) => false' chains/moonbeam/repos/moonbeam/runtime/moonbeam/src/lib.rs

# value moving with no receipt: the runtime calls mintInto directly
grep -n -A6 'fn erc20_mint_into' chains/moonbeam/repos/moonbeam/pallets/moonbeam-foreign-assets/src/evm.rs
grep -n -A6 'fn store_block' chains/moonbeam/repos/frontier/frame/ethereum/src/lib.rs
```
