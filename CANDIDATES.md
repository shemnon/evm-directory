# Candidate chains

A backlog, not a dataset. Nothing here is verified — every "expected divergence" below
is a **claim to be measured**, in the sense [SCHEMA.md](SCHEMA.md) uses the word. The
point of the column is to predict which clones will pay for themselves.

## Selection criteria, in priority order

1. **Mindshare.** Where builders, auditors, and tooling authors actually have to care
   about the delta. A chain nobody writes contracts for produces a row nobody reads.
2. **Expected divergence.** A chain that reproduces mainnet exactly is worth one line in
   MATRIX.md, not a clone. Rank by *how much the row would teach*, not by TVL.
3. **Evidence availability.** No public execution client pinned to a released tag → no
   row, under the current method. Several high-mindshare chains fail this gate; they are
   listed under [Blocked on evidence](#blocked-on-evidence) rather than dropped, because
   the gap is itself a finding.
4. **Native token cap ≥ $100M** as a floor for anything that fails 1 and 2.

Caps are *tiered*, never quoted — this file would rot in a week otherwise. Chains whose
gas token is a stablecoin (Arc, Tempo, Plasma's USDT path) have no meaningful native cap
and qualify on mindshare alone.

Frameworks are marked **FW**. One framework row absorbs a dozen chains, the way
`op-stack` already absorbs Ink, Zora, Mode, Lisk, Soneium, and Unichain. Prefer them.

---

## Tier 0 — **complete**

All seven landed. Kept here as the record of what was predicted and why; each row's
SUMMARY.md states what it actually found.

| Chain | Client to pin | Expected divergence | Why now |
|---|---|---|---|
| **Monad** | `category-labs/monad-execution` + `monad-bft` (verify org; was `monad-labs`) | Independent C++ EVM — **not a geth fork**. Deferred execution: consensus commits transactions before executing them, so the state root in a block lags the block. Optimistic parallel execution with conflict re-run. | The first row where the *implementation* is not shared code, so "EIP is present" and "EIP behaves identically" fully decouple. Very high mindshare. |
| **zkSync Era** / **ZK Stack** **FW** | `matter-labs/zksync-era` | EraVM is not EVM bytecode. Native account abstraction as tx type `0x71` (EIP-712 envelope). System contracts in the `0x8000`–`0x8012` range, not `0x01`–`0x11`. Different `CREATE` address derivation. Gas metering unrelated to mainnet's. | Almost certainly the largest single delta obtainable, and it absorbs Abstract, Sophon, Lens, Cronos zkEVM. |
| **HyperEVM** (Hyperliquid) | ⚠️ none public — see [Blocked](#blocked-on-evidence) | Read precompiles at `0x…0800`+ exposing L1 order-book state (positions, spot balances, oracle px). `CoreWriter` at `0x3333…3333`. Dual block schedule: fast small blocks interleaved with slow large blocks in one chain. | Top-tier mindshare, top-tier divergence, and it fails the evidence gate — which forces the repo to decide its policy on closed-source chains. |
| **Sei** | `sei-protocol/sei-chain` | Cosmos-SDK EVM with OCC parallel execution. **OCC confirmed shipped and default-on, and refuted as the divergence** — it is node-local and provably sequential-equivalent (`occ_tests` asserts identical state both ways). The consensus-visible parallelism is the *Giga* executor, which sets `SkipLastResultsHashValidation` because it "may produce different gas used values". Dual address space (`0x…` ↔ `sei1…`) reconciled by an association precompile. Custom precompile block around `0x…1001`–`0x…100C` for bank, staking, gov, oracle, wasm, IBC. | Custom precompile *addresses* at last — the current table's one universal address (`0x0100`) finding needs a counterexample to be load-bearing. |
| **Kaia** (Klaytn) | `kaiachain/kaia` | An entire parallel transaction-type space: `0x08`–`0x4x` value-transfer / fee-delegated / partial-fee-delegated variants, **two signers on one transaction**, and account-key types decoupled from the address. | The richest [TX-TYPES.md](TX-TYPES.md) row available on any chain. Mid mindshare, but the row is unique. |
| **Linea** | `Consensys/linea-besu` (+ `linea-monorepo`) | Prover constraints leaking into consensus: `MODEXP` operand caps, restricted/disabled `RIPEMD160` and `BLAKE2F`, field-size limits on precompile inputs. | Independently reproduces the OP Stack "fault-proof constraint became a consensus rule" pattern. Two instances make it a law; one makes it an anecdote. |
| **Celo** | `celo-org/op-geth` + `celo-org/optimism` | Fee-currency abstraction: gas paid in ERC-20 via a `FeeCurrencyDirectory`, carried by tx type **`0x7b`** (CIP-64). | A custom transaction type *on top of OP Stack* — a direct counterexample to "OP Stack derivatives inherit the envelope". Highest-leverage test of the `op-stack` framework row. |

## Tier 1 — **complete**

All fifteen scheduled chains landed; the table below records what each turned out to
be, against what this file predicted. **Four of the fifteen client coordinates in the
original table were wrong** — see [Stale coordinates](#stale-coordinates).

| Chain | Row | What the prediction got wrong |
|---|---|---|
| **Berachain** | [`berachain`](chains/berachain/SUMMARY.md) | Predicted a near-empty EVM delta. **Refuted**: it raises EIP-170 to 32768 and EIP-3860 to 65536 — the only row here that moves the contract size limit — and its PoL transaction claims `0x7E`, colliding with OP Stack's DepositTx across unrelated lineages. |
| **Tempo** | [`tempo`](chains/tempo/SUMMARY.md) | Source was public after all. Goes further than "stablecoin gas": the native asset is **deleted**, and `eth_getBalance` returns a fabricated constant that contradicts the EVM. |
| **Arc** | [`arc`](chains/arc/SUMMARY.md) | Source public; **mainnet not launched** (`live_state: prelaunch`), so the row is source + testnet probe. USDC is native, at the cost of a duplicated unit and unspendable dust. |
| **MegaETH** | [`megaeth`](chains/megaeth/SUMMARY.md) | Predicted the envelope would diverge more than the EVM. **Backwards**: `BLOCKHASH` is honest and mini-blocks are invisible to the EVM, while the EVM has dual gas and `SSTORE` priced by state layout. |
| **Plasma** | [`plasma`](chains/plasma/SUMMARY.md) | The zero-fee USDT paymaster is **not consensus** — it is ERC-4337, and 0 of 274 sampled transactions paid zero gas price. The EL is *upstream reth, unmodified*, pinned by digest. |
| **Cosmos EVM** **FW** | [`cosmos-evm`](chains/cosmos-evm/SUMMARY.md) | Confirmed, as `role: template`. EIP-2935 is written at 8192 and read at 8191. |
| **Frontier / Moonbeam** **FW** | [`moonbeam`](chains/moonbeam/SUMMARY.md) | Moonbeam does **not use `polkadot-evm/frontier`** — every Frontier crate is its own fork, so no framework row was warranted. Recorded `role: independent`. |
| **Polygon CDK / zkEVM** **FW** | [`polygon-zkevm`](chains/polygon-zkevm/SUMMARY.md) | Client was archived and replaced. Chain is **halted** since 2026-07-03. No CDK template row: "CDK" is no longer one EVM. |
| **Scroll** | [`scroll`](chains/scroll/SUMMARY.md) | Confirmed and dated: the prover restrictions were **lifted** at Galileo, so the leak-into-consensus claim needs a date, not just a chain name. |
| **Taiko** | [`taiko`](chains/taiko/SUMMARY.md) | Confirmed. The anchor is identified by **index, not by bytes**, wears mainnet's `0x02`, and its signing key is published with fixed k=1. |
| **Mantle** | [`mantle`](chains/mantle/SUMMARY.md) | Confirmed, and the interesting half is the negative: MNT-as-gas needed **no new transaction type**. |
| **Sonic** | [`sonic`](chains/sonic/SUMMARY.md) | Predicted years-old opcode/gas drift. **Refuted**: it tracks geth v1.17.1 and the EVM-layer delta is eleven lines. The divergence is a 10% charge on gas you did not use. |
| **Gnosis** | [`gnosis`](chains/gnosis/SUMMARY.md) | Predicted the cleanest "gas token is the only delta" control. **Refuted**: the base fee is not burned, and withdrawals credit zero native token. |
| **Injective** | [`injective`](chains/injective/SUMMARY.md) | Confirmed and sharper: the batch auction moves EVM-visible balances with no transaction, receipt, log or trace. |
| **Flare** | [`flare`](chains/flare/SUMMARY.md) | Predicted custom precompiles at `0x1000…0002`. **Refuted**: those are system contracts with real bytecode; Flare adds **zero** precompile addresses. |

### Stale coordinates

`gnosischain/gnosis` 404s · `InjectiveLabs/injective-core` moved to `InjectiveFoundation`
· `mantlenetworkio` redirects to `mantle-xyz` · `0xPolygonHermez/zkevm-node` is archived
and superseded by `0xPolygon/cdk-erigon`. In three of those the running client was
identified only by asking the network (`web3_clientVersion`), not by reading a
document. Treat every "Client to pin" below as a lead, not a fact.

## Tier 1b — the ordering/execution pass

Seven rows added in one pass, selected for **how they order and execute** rather than for
cap or mindshare. Five of the seven fail criterion 1 outright; they are here because the
question "what happens to a transaction that is ordered and then turns out to be invalid"
had no portable answer, and these are the chains that answer it differently. The result is
[`ordered-then-invalid`](findings.yaml) — seven distinct fates across ten rows.

| Chain | Row | What it turned out to be |
|---|---|---|
| **Conflux eSpace** | [`conflux`](chains/conflux/SUMMARY.md) | Was **Tier 2**; the ranking measured the wrong axis and is **refuted**. Tx types and precompiles are byte-for-byte mainnet — zero added addresses, zero installed bytecode — while the row carries eight `severity: high` silent divergences. `stateRoot` is the deferred root of epoch N−5 republished under Ethereum's key, and a third receipt outcome (`Skipped`) erases ordered-but-invalid transactions entirely. |
| **Taraxa** | [`taraxa`](chains/taraxa/SUMMARY.md) | A **methodology row**. Ships EIP-1283 *without* EIP-1706's sentry — an EIP mainnet emergency-forked away — so a 2,300-gas `transfer()` stipend can write storage and every "only 2,300 gas, no state change" audit premise is false here. Also the mirror of Hyperliquid: full source at a released tag, **no reachable network**. |
| **Autonomys (Auto EVM)** | [`autonomys`](chains/autonomys/SUMMARY.md) | Decoupled execution: consensus orders bundles, operators execute later. An invalid transaction poisons its whole bundle and **slashes the operator** — the only row where an ordinary EVM validity failure is a protocol violation attributed to a validator. Also the counter-example to the Frontier ruling below: Frontier is consumed **upstream and unmodified**. |
| **IOTA EVM** | [`iota-evm`](chains/iota-evm/SUMMARY.md) | An EVM *contract* inside an ISC chain. Two rejection layers with different observables; the block hash does not commit to the block's transactions (`fakeHasher` returns zero, so an *empty* block reports the real `EmptyRootHash` and a full one reports zero); `GASPRICE` and `BASEFEE` return 0 inside the EVM while the receipt reports the real price. |
| **Artela** | [`artela`](chains/artela/SUMMARY.md) | A **cautionary specimen on a dormant chain**, not an integration target. Aspects are WASM hooks bound by whoever a contract's own `isOwner`/`owner()` names — third-party code that can discard a transaction the EVM completed, with `status: 0` and no `REVERT` in the trace. Opens the `third-party-code-in-your-transaction` class. |
| **RISE** | [`rise`](chains/rise/SUMMARY.md) | The EVM is **stock**; the entire delta is the RPC surface. Preconfirmed receipts reach unmodified HTTP clients with `blockHash: 0x00…00`, and `eth_subscribe(["logs"])` is replaced rather than extended. The parallel-EVM claim is **refuted as shipped** — `pevm` is untagged and lists "Integration into RISE nodes" as TODO. Audience is indexer and library maintainers, not auditors. |
| **Rollkit / Evolve** **FW** | [`rollkit`](chains/rollkit/SUMMARY.md) | Framework row **warranted, narrowly** — and by a fourth failure mode: *shared binary, no ecosystem*. Exactly one live EVM deployment found. Celestia records an order the sequencer already chose; only the optional forced-inclusion namespace is genuinely based. The EL is **not** stock reth despite reporting `reth/v2.2.0` — `PREVRANDAO` is the block number. |

| **Hedera** | [`hedera`](chains/hedera/SUMMARY.md) | Added after the pass, for hashgraph's ordering/execution split. The naive prediction — "the EVM is different" — would be **refuted**: it is stock Besu Cancun consumed as a library, with no precompile added, removed or repriced. The divergence is that the `eth_*` API is a **translation shim in a different repo at a different version**, so "what the network does" and "what the RPC says" are separately citable and repeatedly disagree. Transaction identity is *(payer, valid-start)*, not (sender, nonce). |

Two rows already in the dataset were revisited in the same pass. **Berachain**: "Berachain v2"
is *not a fork* — the fork list is `genesis, prague, prague1–4, osaka, osaka1`, and the name
belongs to a pre-mainnet architecture post and to a PoL tokenomics generation that ships
behind a proxy. **MegaETH**: the ordered-but-invalid case exists, is tested in-tree, and is
structurally unobservable, because the receipt is built downstream of the check that drops it.

### What this pass says about the selection criteria

Criterion 3 (**evidence availability**) has two halves, and the file only stated one. Taraxa
has full source and no reachable network; Artela the same; RISE has a *released tag* that is
a deployment repo while the execution client is closed. "Is there a public client" and "is the
state transition auditable" are different questions, and three of seven rows separate them.

## Tier 2 — clears the $100M floor; divergence likely real but narrower

`Ronin` (`ronin-chain/ronin` — Consortium DPoS, gas sponsorship, heavy gaming mindshare) ·
`Core` (`coredao-org/core-chain` — Satoshi Plus, BTC staking) ·
`Cronos` (Cosmos EVM derivative) ·
`Blast` (`blast-io/blast` — native rebasing yield changes balances with no transaction, a genuine state-transition delta) ·
`Fraxtal` · `Metis` · `Kava` · `Rootstock` (`rsksmart/rskj` — merge-mined, forked the EVM early enough that opcode-level drift is likely) ·
`IoTeX` · `XDC` · `Chiliz` · `Story` (`piplabs/story` — IP-registry precompiles) ·
`ZetaChain` · `Somnia` · `0G` · `Etherlink` · `Botanix`.

## Tier 3 — do not give these rows

OP Stack derivatives with no state-transition delta: **Unichain** (Flashblocks is block
*building*, like World Chain), **Ink**, **Zora**, **Mode**, **Soneium**, **Lisk**,
**Katana**, **Codex**. Cover them as a membership list under `op-stack`, and only
promote one if it ships a custom predeploy, precompile, or tx type. ZK Stack chains
(**Abstract**, **Sophon**, **Lens**) likewise belong under the zkSync row.

Not EVM, out of scope regardless of cap: Solana, Sui, Aptos, Starknet, Fuel, Canton, TON.

## Blocked on evidence

**Resolved, and mostly in the other direction.** Of the four chains listed here as
possibly unreadable, **three had public source all along**: `tempoxyz/tempo`,
`circlefin/arc-node` and `megaeth-labs/mega-evm` all clone and pin to released tags.
Plasma needed no documented row either — its execution layer is *upstream reth,
unmodified*, pinned by digest in the chain's own `.env`, so the only closed component is
its consensus client. The lesson is that the evidence gate must be tested by cloning,
not estimated from reputation: the chains assumed closed were open, and the one assumed
Reth-based was Reth **exactly**.

**Hyperliquid** remains the only genuinely blocked chain, and the `evidence: documented`
row kind proposed here was adopted in [SCHEMA.md](SCHEMA.md) and used for it. It is
quarantined as intended: `clone.sh` skips it, `verify.py` reports `SKIP (documented)`,
and `tools/verify.py` prints the per-chain provenance tally so a row drifting toward
doc-only evidence stays visible.

Two rows now fail a *different* gate, which the schema gained a field for
(`chain.live_state`): **Arc** has never produced a mainnet block (`prelaunch`, launch
announced for 2026-09-16, so its live facts are testnet facts), and **Polygon zkEVM**
produced its last block on 2026-07-03 and has not advanced since (`halted`). Neither is
an evidence problem — both have source — but a reader must not mistake either for a
running chain.

## Framework coverage, current and proposed

| Framework | Row | Absorbs |
|---|---|---|
| OP Stack | ✅ `op-stack` | Base, opBNB, World Chain, Unichain, Ink, Zora, Mode, Soneium, Lisk, Celo¹, Mantle¹, MegaETH¹ |
| Avalanche subnet-evm | ✅ `avalanche-subnet` | all L1s/subnets |
| Cosmos EVM (`evmd`) | ✅ `cosmos-evm` (`role: template`) | Cronos, XRPL EVM, ZetaChain, Injective¹ |
| Arbitrum Nitro / Orbit | 🔄 in progress | Nova, ApeChain, Orbit chains |
| ZK Stack | ❌ proposed | Abstract, Sophon, Lens, Cronos zkEVM |
| Frontier (Substrate) | ⛔ **not warranted** | — Moonbeam forks every Frontier crate and shares the fork with nobody, so a template row would pin code no chain runs. Recorded as `role: independent` instead. Astar/Moonriver would each need their own read. **Amended:** [`autonomys`](chains/autonomys/SUMMARY.md) consumes `polkadot-evm/frontier` upstream and unmodified (it patches *polkadot-sdk* beneath it instead), so the "everyone forks it" premise is false in general — but a Frontier row still would not absorb Autonomys, whose divergences are all in its own code. |
| Polygon CDK | ⛔ **not warranted yet** | — "CDK" is no longer one EVM: `cdk-erigon` and `cdk-op-reth` put descendants on different stacks. A template row would assert Polygon zkEVM's disabled MODEXP and Berlin baseline for X Layer and Immutable from zero evidence. [`polygon-zkevm`](chains/polygon-zkevm/SUMMARY.md) names the single probe that would settle it. |
| Rollkit / Evolve | ✅ `rollkit` (`role: template`) | Eden (chain 714) — the only confirmed instance. Passes on shared code, nearly fails on descendants: a fourth outcome, *shared binary, no ecosystem*. |
| BeaconKit | ⛔ **not warranted** | — Berachain's EL fork (`bera-reth`) carries the divergence; BeaconKit is pinned as its companion. |

¹ diverges from its framework enough to need its own row anyway — which is
exactly the thing worth measuring. Three of the eight proposed framework rows turned
out **not to be frameworks in practice**: the code was forked per-chain, or the family
had already split across incompatible stacks. Prefer a framework row, but verify that
descendants actually share the pinned code before writing one.
