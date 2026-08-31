# Sonic — findings

Chain ID 146. Client `0xsoniclabs/sonic` **v2.2.1** @ `83c8c38b7779c1bac7377ad0df592a65cde7894d`,
with three pinned companions: `0xsoniclabs/go-ethereum` @ `e9dfccd4`, `0xsoniclabs/tosca`
@ `3f411928`, `0xsoniclabs/carmen` @ `2d892af3`.
Baseline fork **prague**. Live probes at block **78050451** (`0x4a6f493`) on
`https://rpc.soniclabs.com`.

The pinned tag is what mainnet runs: `web3_clientVersion` returns
`Sonic/v2.2.1-83c8c38b-…`, and `83c8c38b` is this commit. No gap between the pin and
the network.

---

## 1. The predicted lineage drift is not there — the opposite is

CANDIDATES.md expected "an Opera lineage that diverged from go-ethereum years ago (so
opcode- and gas-level drift is plausible)". Measured, that is false in the specific way
that matters.

Sonic does not fork go-ethereum's tree at all. `go.mod` **requires**
`github.com/ethereum/go-ethereum v1.17.1` and `replace`s it onto
`0xsoniclabs/go-ethereum` @ `e9dfccd4` (2026-05-07), whose `version/version.go` reads
**1.17.2-stable**. The Ethereum row in this dataset pins geth `v1.17.5`. Sonic is four
patch releases behind upstream, not four years.

And the patch fork is tiny. Grepping `Sonic|Fantom|Opera` across `core/vm/`,
`core/state_transition.go`, `core/types/` and `params/` in that fork returns **eleven
lines**, all of them marked. The whole EVM-layer delta is six flags plus one map on
`vm.Config` (`core/vm/interpreter.go:40-59`): `StatePrecompiles`,
`InterpreterForTracing`, `ChargeExcessGas`, `IgnoreGasFeeCap`,
`InsufficientBalanceIsNotAnError`, `SkipTipPaymentToCoinbase`, plus nullable
`MaxTxGas`/`MaxCodeSize`/`MaxInitCodeSize` overrides. `core/vm/contracts.go` is
untouched apart from adding the `PrecompiledStateContract` interface — no repriced
precompile, no input cap, no omission. The opcode-and-gas drift the backlog predicted
does not exist.

What *is* two-stranded is the consensus half: `Fantom-foundation/lachesis-base` is still
a direct dependency, the package holding the fork flags is still called `opera`, and the
surviving Fantom quirks are labelled as such in the geth fork ("a Fantom modification",
"unlike Ethereum, in Opera").

## 2. …but the interpreter is not geth's, and that decides `role`

`opera/vm_config.go` is the whole argument in thirty lines. Transaction processing runs
on **Tosca's LFVM** today and on **SFVM** from the Brio upgrade, both plugged into
`vm.Config.Interpreter` through `tosca/go/geth_adapter`. Geth's own interpreter is kept
and assigned to `InterpreterForTracing` — used **only for tracing**. So on Sonic a
`debug_traceTransaction` and the block containing that transaction were produced by two
different EVM implementations.

Tosca is a genuine second implementation: its own instruction dispatch, its own gas
tables, its own memory and analysis (`tosca/go/interpreter/sfvm/`), plus C++ (`evmzero`)
and Rust (`evmrs`) siblings in the same repo. It is also **BSL-1.1**, not open source —
its README states the licence "prohibits Sonic-VM (Tosca) from being used in production
by any other project". The consensus-critical EVM of a live L1 is not OSI-licensed.

**Why this is `role: fork` and not `independent`, and why `equivalence: behavioural`
does not apply.** Monad (`chains/monad/`) is `independent` because the whole tree —
interpreter, state DB, scheduler, chain params — is original C++ with no shared
ancestry, so every comparison to mainnet is a behavioural claim rather than a diff.
Sonic is not that. Everything *around* the interpreter is literally go-ethereum: the
state transition, the signer, the precompile set (Tosca's `geth_adapter` decides
precompile membership by looking up geth's own `PrecompiledContractsPrague` map), RLP,
the receipt layout, the header type. Carmen's production configuration uses
`EthereumLikeHashing`, so even the state root is a mainnet-shaped MPT root. The deltas
below are code diffs against a pinned geth, which is exactly what `fork` means.

The precedent is **Base**, not Monad: `chains/base/` is `role: fork` while reimplementing
the EVM layer in Rust on reth. Substituting the interpreter under a geth state transition
is a fork with a swapped engine, not an independent chain. `chain.note` says so
explicitly, in the style `chains/linea/chain.yaml` established.

## 3. You are charged 10% of the gas you did not use

`chargeExcessGas` (`go-ethereum/core/state_transition.go:622`, comment: "a Fantom
modification") does `st.gasRemaining -= st.gasRemaining/10` before the refund, for every
transaction whose sender is not the zero address. It is enabled by
`opera/vm_config.go:sonicVmConfig`.

Verified live, arithmetically exact, on two unrelated mainnet transfers:

| tx | gas limit | true cost | receipt `gasUsed` | `21000 + (limit-21000)/10` |
|---|---|---|---|---|
| `0xc82adca9…` | 31500 | 21000 | **22050** | 22050 |
| `0xdcb55a2c…` | 23000 | 21000 | **21200** | 21200 |

The trap is the tooling. `eth_estimateGas` returns the *true* consumption — a bare
`ecrecover` call estimates at `0x5dc0` = 24000, the honest number — so the universal
practice of padding an estimate by 20–50% "for safety" is a direct transfer of value.
Nothing reverts, nothing warns, and the receipt reports the inflated figure as though it
were consumption.

This is the same failure family as Monad's `gasUsed == gasLimit`, at 10% instead of
100%, and reached from a different direction. It also **disappears the moment somebody
toggles a block-production option**: `GetVmConfig` clears `ChargeExcessGas` when
`SingleProposerBlockFormation` is set, and that flag is documented as one that "can be
enabled or disabled at any time". The receipt arithmetic above is itself the evidence
that the flag is currently off — it is not surfaced by any RPC.

## 4. The block header matches no mainnet fork — proved from the network

Reconstructing the live block hash from the RPC fields shows Sonic's header is keccak of
a **nineteen-item** RLP list, ending at `excessBlobGas`:

```
keccak(RLP(19 fields)) == 0xbc01ebf65a442adb0036f69099c827b3ea2b9e0f11bbddd0989ca16c08acd3b1
```

which is the block's actual hash at 78050451. That is Shanghai's seventeen fields plus
`blobGasUsed` and `excessBlobGas`, and then it stops. **No `parentBeaconBlockRoot`**
(mandatory on mainnet since Cancun) and **no `requestsHash`** (mandatory since Prague) —
while the EVM is at Prague. Mainnet's Cancun header has twenty items and Prague's
twenty-one.

A header verifier written against *any* mainnet fork fails on every Sonic block, and it
fails on the **field count**, not on a value. This is a different failure from Monad's,
which emits `requestsHash` as the zero hash and so mismatches on content: two chains, one
missing feature, two incompatible ways of not having it.

Corroborated at the source: `inter/block.go:GetEthereumHeader` builds a `types.Header`
with `WithdrawalsHash`, `BlobGasUsed` and `ExcessBlobGas` set and the two later optional
fields left nil, and `eth_getCode` at `0x000F3df6…Beac02` returns `0x` — no beacon-roots
contract. Notably EIP-2935's history contract **is** deployed
(`0x0000F90827F1C53a10cb7A02335B175320002935`, canonical bytecode) and
`ProcessParentBlockHash` runs on every Prague block. The two "protocol writes a ring
buffer" contracts are usually assumed to travel together; here one shipped and the other
structurally could not.

## 5. `difficulty`/`mixHash`/`nonce` are *not* repurposed — `extraData` is

The coordinator asked whether Sonic's Lachesis header rides a second metering dimension
in `difficulty`, the way Taiko's does. **It does not.** `difficulty` is `0x0` and
`totalDifficulty` is `0x0`, by two independent paths that happen to agree: the RPC
encoder hardcodes a fresh zero (`evmcore/dummy_block.go:ToJson`), and the stored block's
`Difficulty` is never set outside the disabled LLR path. `nonce` is a constant zero.
`sha3Uncles` is the `EmptyUncleHash` constant on every block, present only because the
hash needs it, and `eth_getUncleCountByBlock*` returns 0 from a hardcoded empty slice
(`api/ethapi/api.go:noUncles`). `miner` is the zero address on every block.

`mixHash` does carry meaning, but consensus meaning rather than a metering dimension:
`gossip/prevrandao.go:computePrevRandao` is sha256 of the XOR of bytes 8..31 of the
confirmed Lachesis event hashes ("the first 8 bytes should be ignored as they are not
pseudo-random"). Verified live to be byte-identical to what opcode `0x44` returns. It is
derived from data the validators themselves produced — a materially weaker randomness
assumption than a beacon RANDAO, invisible from the field.

**The field that is repurposed is `extraData`**, and it is consensus-critical.
`inter/block.go:EncodeExtraData` writes exactly twelve bytes: a big-endian `uint32` of
the timestamp's nanosecond part, then a big-endian `uint64` of the block's **duration**
in nanoseconds. At the probed block, `0x36da80c1000000007d03b07c` → 920 617 153 ns and
2 097 225 852 ns. That duration is an input to the *next* block's base fee
(`gossip/gasprice/base_fee.go:getBaseFeeForNextBlock`), so anything treating `extraData`
as an opaque vanity string is discarding a consensus input — and the fee market cannot be
reproduced from the standard header fields at all. Same move as OP Stack repurposing
`blobGasUsed` for a DA footprint, and as Taiko's second dimension in `difficulty`; a
third instance, so the pattern is worth naming.

The fee market itself is time-based rather than block-based:
`new = old * e^(((rate - targetRate)/targetRate) * duration/128)` where `rate` is **gas
per second**. Mainnet's rule has no time term. Every EIP-1559 estimator is wrong here on
every input.

## 6. A fifth fork-activation mechanism: on-chain booleans, no timestamps

README.md names four incompatible mechanisms (OP timestamp equality, Avalanche
timestamps, Arbitrum ArbOS version, Polygon block numbers). Sonic is a fifth.

Forks are **boolean flags inside on-chain network rules** (`opera/rules.go:Upgrades`:
`Sonic`, `Allegro`, `Brio`). A governed `updateNetworkRules(bytes diff)` call on the
NodeDriver flips a flag; the change takes effect at the start of the next epoch, and the
client records the **block height** at which it did. There is no fork timestamp anywhere,
and `opera/rules.go:CreateTransientEvmChainConfig` explains why in a comment: Sonic
timestamps are nanoseconds and blocks are sub-second, so seconds-granularity gating is
impossible. That function hands geth tooling a `ChainConfig` with **every fork time set
to 0** and documents it as valid for exactly one block height. Anything that reads a fork
schedule out of a Sonic `ChainConfig` reads all-zeros and concludes every fork has always
been active.

The authoritative live view is `eth_config` (EIP-7910), which Sonic ships **ahead of the
Osaka fork that introduces it on mainnet** and extends with a per-upgrade `blockHeight`.
At 78050451 it reports exactly two upgrade heights and no third:

- `last`: block `0x1`, activationTime 1733011200, precompiles `0x01`–`0x0a` — the genesis
  Sonic (Cancun) rules.
- `current`: block `0x35dc910` (56 674 576), activationTime 1764165761, precompiles
  `0x01`–`0x11` (BLS included, **no `0x0100`**), systemContracts `HISTORY_STORAGE_ADDRESS`
  **and** `GAS_SUBSIDY_REGISTRY_ADDRESS` — Allegro (Prague) **and** gas subsidies, enabled
  in one step.
- `next`: **null**.

So mainnet went Cancun → Prague in a single rules update and has nothing scheduled. The
subsidy registry's presence in that list is itself the observable for the `GasSubsidies`
flag: `api/ethapi/config.go:activeSystemContracts` only emits it when the flag is true.

## 7. Protocol transactions with no type byte and no signature

Sonic's internal transactions are the third design in this dataset and the least
announced. OP Stack marks a protocol transaction with type byte `0x7e` and reads the
sender from a dedicated `From` field. Monad signs its with a real secp256k1 key and
identifies it by the recovered address. Sonic does neither:

```go
func IsInternal(tx *types.Transaction) bool { v, r, _ := tx.RawSignatureValues(); return v.Sign() == 0 && r.Sign() == 0 }
func InternalSender(tx *types.Transaction) common.Address { _, _, s := tx.RawSignatureValues(); return common.BytesToAddress(s.Bytes()) }
```

An internal transaction is an ordinary **legacy `0x00`** transaction with `v = 0, r = 0`,
and **the sender is stored in the `s` field** — the S component of the ECDSA signature,
cast to a 20-byte address. `evmcore/state_processor.go:TxAsMessage` then builds the
message with `SkipNonceChecks: true` and `SkipTransactionChecks: true`: nonce, balance and
EOA-ness all waived, no signature checked.

Observed live at the epoch-sealing block **78050318**: two type-`0x00` transactions with
`v/r/s` all `0x0`, `from` `0x0000…0000`, `to` the NodeDriver `0xd100a01e…`, `gasPrice 0`,
`gas 500 000 000`, nonces `0x2d0de`/`0x2d0df` — inside `transactionsRoot`, next to a
normal user transaction. The only tell is a zero `from`. These carry `sealEpoch(…,
originatedTxsFee, …)`, which is how validators are actually paid: there is no coinbase
payment (`SkipTipPaymentToCoinbase`, coinbase always `0x0`), so "who was paid for this
block" has no answer at block granularity.

What keeps this safe is not a check on the transaction but a check on the envelope:
`eventcheck/heavycheck/heavy_check.go:135` recovers a sender for **every** transaction
inside **every** Lachesis event, so an internal-shaped transaction can never enter through
the DAG. Guarded — one layer away from where the forgery would happen. Note also that the
zero-address sender is exactly the case `chargeExcessGas` exempts, so the 10% surcharge
and the protocol-transaction marker are the same condition.

## 8. A precompile that rewrites arbitrary state — and breaks the category boundary

**EvmWriter**, `0xd100ec0000000000000000000000000000000000`, registered via
`vm.Config.StatePrecompiles` (`opera/vm_config.go:sonicVmConfig`). Five methods:
`setBalance(acc,value)` sets any account's balance to any number, `setStorage(acc,key,value)`
writes any slot of any contract, `incNonce(acc,diff)` bumps any nonce, and `copyCode` /
`swapCode` overwrite or **exchange** the bytecode of two accounts. Contract code on Sonic
is therefore not immutable at the protocol level. The only guard is
`caller != driver.ContractAddress → revert` (confirmed live: an `eth_call` to `setBalance`
from an arbitrary sender reverts); the only self-restraint is that `setBalance` and
`incNonce` refuse to touch `tx.origin`.

It also breaks SCHEMA.md's precompile/system-contract boundary, which says a precompile
has "no bytecode in state, no `EXTCODESIZE`". Genesis writes a single `0x00` byte there
(`integration/makefakegenesis/genesis.go:113`, under the comment *"set non-zero code for
pre-compiled contracts"* — the boundary break is intentional and documented), confirmed
live: `eth_getCode` returns
`0x00`, and `EXTCODEHASH` returns
`0xbc36789e7a1e281436464229828f817d6612f7b477d66591ff96a9e064bcc98a` = keccak256(`0x00`),
not the empty-code hash. Every "is there a contract here" probe answers **yes**; execution
is intercepted by the native handler and the stub is never run. It is both categories at
once, deliberately — presumably so Solidity's `extcodesize` guard does not reject calls to
it.

The other system contracts are placed high in the address space in leetspeak —
`0xfc00face…` (SFC), `0xd100a01e…` (NodeDriver), `0xd100ae00…` (NodeDriverAuth),
`0xd1005eed…` (NetworkInitializer) — the opposite discipline from BSC's and Arbitrum's
`0x64`–`0x69`, and immune to mainnet growing into it. SFC's `currentEpoch()` returns
`0x16866`, identical to the probed block's own `epoch` header field; `lastValidatorID()`
returns 54.

## 9. Third chain where `0x0100` silently returns empty — third cause

Calling `0x0100` at 78050451 with the **valid 160-byte P-256 vector taken from Sonic's own
test suite** (`tests/secp256r1_precompile_test.go:validInput`) returns `0x`. The identical
calldata on Ethereum mainnet returns `0x…01`.

Hyperliquid's `0x0100` is empty because nothing is there. Sei's is empty *while the chain
has P256VERIFY at another address*. Sonic's is empty because **the feature is written,
tested and shipped in the client that mainnet is running, and gated behind a fork nobody
has scheduled** — `eth_config.next` is null. Three chains, three causes, one observable,
and under EIP-7951 that observable is byte-identical to "signature invalid". A passkey
wallet deployed here verifies nothing, reports "invalid" forever, and will begin working
on a date that does not exist yet.

Sonic's own test asserts exactly this: `TestSECP256r1_VerifySignatureInBrio` expects
`ReceiptStatusFailed` for Sonic and Allegro with a valid signature. The Brio gas is 6900 —
mainnet EIP-7951's price, not RIP-7212's 3450.

Confirming the same probe from the other side: Prague's BLS precompiles `0x0b`–`0x11` are
live and computing (`0x11` returns a real MAP_FP2_TO_G2 point), so the empty `0x0100` is a
fork-level fact and not a broken node.

## 10. A third answer to blobs

`evmcore/tx_validation.go:ValidateTxForNetwork` accepts type `0x03` and rejects it with
`ErrNonEmptyBlobTx` if the blob-hash list is non-empty. The envelope is valid; the payload
is not. `TxAsMessage` additionally rewrites an empty `BlobHashes` slice to `nil` so geth's
own precheck — which forbids a blob transaction with no blobs — does not fire.

So `BLOBHASH` is live and always returns zero, `BLOBBASEFEE` is live and constant `1`
(the client derives it: excess blob gas is always 0, so `1 * e^0 = 1`), the KZG
point-evaluation precompile at `0x0a` is present and functional, and `blobGasUsed` /
`excessBlobGas` are present and pinned to zero. Everything about 4844 works except blobs.
Mainnet is `inherited`, Monad is `removed`, Sonic is `modified` — the dataset had two of
these three.

`blobGasUsed` now carries a **third** meaning across the dataset: OP Stack repurposes it
as a DA footprint, Avalanche pins it to zero and rejects anything else, Sonic pins it to
zero and derives the blob base fee from it.

## 11. The same transaction in two DAG events: deduplicated by hash, and only the first emitter is paid

Validators emit events concurrently and independently, so two of them carrying the same
transaction is normal traffic, not an attack. Sonic answers it at four layers, and only
two are consensus.

At **emission**, `gossip/emitter/txs.go:isMyTxTurn` runs a lottery — a stake-weighted
permutation seeded by `hash(sender, nonce/32, epoch)`, indexed by the 8-second round since
the transaction was first seen, skipping validators believed offline — and emits only when
the permutation names this validator. The comment says the point is to "try to not include
the same tx simultaneously by different validators". It is a heuristic: disagree about who
is offline, or straddle a round boundary, and both emit. Nothing rejects the event.

At **block derivation**, the transactions of every event in the confirmed Atropos set are
concatenated and handed to the scrambler, whose `analyseEntryList` walks the list with a
`seenHashes` set and keeps the first of each. The XOR salt that scrambles the surviving
order is computed from the *unique* hashes, so the ordering is a function of the set rather
than of arrival order — the dedup is what makes the order deterministic across nodes.

At **execution**, the cross-block case is caught: a scrambler set is per-block, so an event
confirmed into block N+1 carrying a transaction already executed in block N reaches
`applyTransaction`, fails the nonce precheck, and comes back as
`ProcessedTransaction{Receipt: nil}`. `Finalize` builds the stored block from receipt-bearing
entries only, so the duplicate is **absent from the block, has no receipt, and gets no
transaction-index entry** — the Conflux outcome. `isPermissible` states the rule outright:
"Permissible transactions may still be rejected by the block processor due to nonce or
balance issues. In such cases, the transaction is considered a skipped transaction."

And in **single-proposer mode there is no hash dedup at all**. With
`SingleProposerBlockFormation` on, the proposal never reaches the scrambler; the proposer's
`Schedule` trial-runs candidates and "will only accept the first that can be successfully
processed, ignoring the rest" — excluding the duplicate by executing it rather than by
recognising it. Two block-formation modes, two different duplicate mechanisms, selected by
an on-chain rules toggle.

**Who is paid** is decided by a five-word comment in `c_block_callbacks.go`: "If tx was met
in multiple events, then assign to first ordered event". The `EventCreator` recorded there
is the `originator` handed to `OnNewReceipt`, which credits `ValidatorStates[…].Originated`
with the whole fee for epoch settlement via `sealEpoch(…, originatedTxsFee, …)`. The second
emitter earns nothing and is **not** penalised — no slash, no cheater record, only the gas
power it spent carrying the transaction.

Unlike Conflux, though, the evidence survives one level down: the event that carried the
duplicate is stored intact, and `dag_getEventPayload(<id>, true)` still lists the
transaction inside it. Visible in the DAG, absent from the executed list — Taraxa's
outcome, reached by a different mechanism.

The nonce check is the backstop, which raises the obvious question about Sonic's nonce
waiver. `TxAsMessage` sets `SkipNonceChecks: true` for internal transactions, so a replayed
internal transaction would execute twice — it is unreachable only because internal
transactions are minted deterministically by `PopInternalTxs` during block processing rather
than carried in events. `InsufficientBalanceIsNotAnError` does not interact at all: it
removes `msg.Value` from the balance test and leaves the nonce test alone.

## 12. Smaller things that still surprise

- **`gasLimit` is 5 000 000 000 and means nothing.** It is `MinimumMaxBlockGas`, which the
  client annotates "gas is mostly governed by gas power allocation". Real capacity is a
  per-second allocation (2 × 15 MGas/s at defaults) shared among validators by stake,
  accumulable for 5 seconds. And there is **no per-transaction gas cap today**: geth
  applies EIP-7825's 16 777 216 only at Osaka. At Brio, Sonic does not adopt that constant
  either — it sets `MaxTxGas` from the on-chain `MaxEventGas` rule, making the cap
  governance-set rather than protocol-constant.
- **A transaction only has to afford its fee, not its value.**
  `InsufficientBalanceIsNotAnError` removes `msg.Value` from the balance check, with the
  comment "insufficient balance for **topmost** call isn't a consensus error in Opera,
  unlike Ethereum". Monad reached the identical rule from deferred execution — two
  unrelated chains, one deviation from Ethereum's validity rules.
- **A zero-gas-price transaction may be valid.** With `GasSubsidies` live, the node calls
  `chooseFund` on the SubsidiesRegistry *during block processing*, and the protocol may
  append a settlement transaction (`deductFees` / `track`) the user never sent. Validity
  depending on a contract's return value is a rule no other row here has.
- **Transactions can be skipped.** `evmcore/state_processor.go:Process` documents that a
  transaction which "cannot execute in the given order" is dropped with no gas, no receipt
  and no state change, and processing continues — "rules inherited from the Fantom network"
  that "future hard-forks may be used to clean up".
- **One block is special-cased in the client.** `gossip/c_block_callbacks.go` carries
  `if thisBlocksRules.NetworkID == 146 && number == 8054923` to reproduce a one-time
  gas-limit adaptation. A single-block consensus exception, hardcoded.
- **Two RPC-only header fields**: `timestampNano` (full nanosecond timestamp; consecutive
  blocks routinely share a `timestamp`) and `epoch`.

---

## Not established here

- **The live `MaxEventGas`** — and therefore the real effective per-transaction ceiling.
  It is an on-chain rule and no public RPC surfaces it; probing it would need a
  multi-megabyte `eth_estimateGas`. The formula is cited
  (`gossip/evm_state_reader.go:CurrentMaxGasLimit`); the number is not.
- **Whether `TransactionBundles` is enabled.** Not surfaced by `eth_config`, and the
  changelog ties bundles to Brio, which is not active. Recorded as `adoption: optional`
  rather than guessed.
- **Whether skipped transactions actually occur on mainnet today.** The mechanism is in
  source; no live instance was found, and finding one requires comparing event contents
  against block contents, which the public RPC does not expose.
- **Precompile gas equality between Tosca and geth.** Precompiles execute in geth, so
  their prices are upstream's; but the *call* gas Tosca charges before dispatch was not
  independently measured. `verify.py` reports `NO EXTRACTOR` for this row, so the
  precompile list is taken on trust — no extractor was written, per the brief.
- **The exact block at which Allegro alone activated.** `eth_config` reports one upgrade
  height carrying both `Allegro` and `GasSubsidies`; whether they were ever separate
  earlier cannot be recovered from the two entries the API returns.
- **Carmen's behaviour beyond its hashing configuration.** It is pinned and its production
  schema (S5) uses `EthereumLikeHashing`, which is why state roots stay mainnet-shaped.
  Nothing further was measured.
- **EIP-4788 as a header field vs. a contract.** Both were checked and both are absent, but
  no source read established whether anything else consumes `parentBeaconBlockRoot`'s slot.

---

## Re-verify

```sh
cd /Volumes/TendiesTown/EVM-intel
R=https://rpc.soniclabs.com
B=0x4a6f493            # 78050451

# --- pins ---
git -C chains/sonic/repos/sonic       rev-parse HEAD   # 83c8c38b7779c1bac7377ad0df592a65cde7894d
git -C chains/sonic/repos/go-ethereum rev-parse HEAD   # e9dfccd41dbeaafc8489794ca8e01906929f24ab
git -C chains/sonic/repos/tosca       rev-parse HEAD   # 3f4119284c421a1840b5716ce19d6eaf67e56103
git -C chains/sonic/repos/carmen      rev-parse HEAD   # 2d892af38ce4a293b0b19105a405ceffded5b903

# F1: geth is a DEPENDENCY at 1.17.2-dev, not an aged fork; the delta is 11 marked lines
grep -nE 'go-ethereum|carmen|tosca' chains/sonic/repos/sonic/go.mod
grep -A5 'const' chains/sonic/repos/go-ethereum/version/version.go
grep -rn 'Sonic\|Fantom\|Opera' chains/sonic/repos/go-ethereum/core/vm/*.go \
     chains/sonic/repos/go-ethereum/core/state_transition.go \
     chains/sonic/repos/go-ethereum/core/types/*.go \
     chains/sonic/repos/go-ethereum/params/*.go | grep -v _test

# F2: the interpreter is Tosca's; geth's is used only for tracing
cat chains/sonic/repos/sonic/opera/vm_config.go
grep -n 'newestSupportedRevision' chains/sonic/repos/tosca/go/interpreter/sfvm/sfvm.go
head -5 chains/sonic/repos/tosca/README.md            # BSL, not open source

# F3: the 10% excess-gas surcharge, live
grep -n 'chargeExcessGas' -A8 chains/sonic/repos/go-ethereum/core/state_transition.go
for h in 0xc82adca9c78a606feb1b0571bfcd808d5ed9ff366e1218bd2a370f52cd8b0dc3 \
         0xdcb55a2c56509f69c8b4a91fc8c41592d5ae9164827623b57f84fcfcd3032cea; do
  curl -s -X POST $R -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getTransactionByHash\",\"params\":[\"$h\"]}" \
    | tr ',' '\n' | grep '"gas"'
  curl -s -X POST $R -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getTransactionReceipt\",\"params\":[\"$h\"]}" \
    | tr ',' '\n' | grep gasUsed
done            # 31500 -> 22050 ; 23000 -> 21200
curl -s -X POST $R -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_estimateGas","params":[{"to":"0x0000000000000000000000000000000000000001"}]}'
                # 0x5dc0 = 24000, the TRUE cost — padding it costs money

# F4: the header is a 19-field RLP list (no parentBeaconBlockRoot, no requestsHash)
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",false]}"
grep -n 'GetEthereumHeader' -A30 chains/sonic/repos/sonic/inter/block.go
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02\",\"$B\"]}"   # 0x
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x0000F90827F1C53a10cb7A02335B175320002935\",\"$B\"]}"   # EIP-2935 present
# The absence is directly visible above: the returned object has no `parentBeaconBlockRoot`
# and no `requestsHash` key, and GetEthereumHeader leaves both nil.
# The hash confirmation: keccak256(RLP(L)) equals the block's `hash`, where L is the
# 19-item list, quantities minimally encoded and byte-strings verbatim:
#   [parentHash, sha3Uncles, miner, stateRoot, transactionsRoot, receiptsRoot, logsBloom,
#    difficulty, number, gasLimit, gasUsed, timestamp, extraData, mixHash, nonce,
#    baseFeePerGas, withdrawalsRoot, blobGasUsed, excessBlobGas]
# Reproduce with any RLP + keccak-256 pair, e.g.
#   python -c "import rlp,json;from eth_hash.auto import keccak; ..."   (rlp + eth-hash)
# Appending a 20th item (parentBeaconBlockRoot) or a 21st (requestsHash) does NOT match:
# that is the claim.

# F5: extraData is 12 bytes of (nanos, duration) and feeds the base fee
grep -n 'EncodeExtraData' -A18 chains/sonic/repos/sonic/inter/block.go
grep -n 'getBaseFeeForNextBlock' -A45 chains/sonic/repos/sonic/gossip/gasprice/base_fee.go
cat chains/sonic/repos/sonic/gossip/prevrandao.go
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"0x445f5260205ff3\"},\"$B\"]}"   # PREVRANDAO == mixHash

# F6: forks are on-chain booleans; eth_config is the only honest schedule
grep -n 'CreateTransientEvmChainConfig' -A40 chains/sonic/repos/sonic/opera/rules.go
cat chains/sonic/repos/sonic/opera/hardforks.go
curl -s -X POST $R -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_config","params":[]}'      # next: null

# F7: unsigned protocol transactions, sender in the `s` field
cat chains/sonic/repos/sonic/utils/signers/internaltx/internaltx.go
grep -n 'TxAsMessage' -A20 chains/sonic/repos/sonic/evmcore/state_processor.go
sed -n '130,140p' chains/sonic/repos/sonic/eventcheck/heavycheck/heavy_check.go
curl -s -X POST $R -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["0x4a6f40e",true]}'

# F8: EvmWriter — arbitrary state writes, and a 1-byte code stub
cat chains/sonic/repos/sonic/opera/contracts/evmwriter/evm_writer.go
sed -n '110,116p' chains/sonic/repos/sonic/integration/makefakegenesis/genesis.go
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0xd100ec0000000000000000000000000000000000\",\"$B\"]}"   # 0x00
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"0x73d100ec00000000000000000000000000000000003f5f5260205ff3\"},\"$B\"]}"  # keccak(0x00)
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0xd100ec0000000000000000000000000000000000\",\"data\":\"0xe30443bc000000000000000000000000dead00000000000000000000000000000000beef0000000000000000000000000000000000000000000000000de0b6b3a7640000\"},\"$B\"]}"  # reverted
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0xfc00face00000000000000000000000000000000\",\"data\":\"0x76671808\"},\"$B\"]}"  # currentEpoch == block.epoch

# F9: 0x0100 empty for a signature mainnet accepts
P=0xbb5a52f42f9c9261ed4361f59422a1e30036e7c32b270c8807a419feca605023000000000000000000000000000000004319055358e8617b0c46353d039cdaabffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc63254e0ad99500288d466940031d72a9f5445a4d43784640855bf0a69874d2de5fe103c5011e6ef2c42dcd50d5d3d29f99ae6eba2c80c9244f4c5422f0979ff0c3ba5e
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"$P\"},\"$B\"]}"          # 0x
curl -s -X POST https://ethereum-rpc.publicnode.com -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"$P\"},\"latest\"]}"      # 0x..01
grep -n 'validInput' -A12 chains/sonic/repos/sonic/tests/secp256r1_precompile_test.go
# CLZ (Osaka) is absent; Cancun ops and Prague BLS are present:
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"0x60011e5f5260205ff3\"},\"$B\"]}"     # execution unsuccessful
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"0x60075f5d5f5c5f5260205ff3\"},\"$B\"]}" # TSTORE/TLOAD -> 0x..07
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000011\",\"data\":\"0x$(python3 -c 'print("00"*128)')\"},\"$B\"]}"  # BLS present

# F10: type 0x03 accepted only with an empty blob list
grep -n 'ErrNonEmptyBlobTx' -B12 chains/sonic/repos/sonic/evmcore/tx_validation.go

# row check
tools/.venv/bin/python tools/verify.py 2>&1 | sed -n '/^sonic/,/^$/p'
```
