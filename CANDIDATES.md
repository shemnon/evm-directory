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

## Tier 0 — highest value: novel EVM semantics *and* high mindshare

These are the rows most likely to break an assumption the dataset currently rests on.

| Chain | Client to pin | Expected divergence | Why now |
|---|---|---|---|
| **Monad** | `category-labs/monad-execution` + `monad-bft` (verify org; was `monad-labs`) | Independent C++ EVM — **not a geth fork**. Deferred execution: consensus commits transactions before executing them, so the state root in a block lags the block. Optimistic parallel execution with conflict re-run. | The first row where the *implementation* is not shared code, so "EIP is present" and "EIP behaves identically" fully decouple. Very high mindshare. |
| **zkSync Era** / **ZK Stack** **FW** | `matter-labs/zksync-era` | EraVM is not EVM bytecode. Native account abstraction as tx type `0x71` (EIP-712 envelope). System contracts in the `0x8000`–`0x8012` range, not `0x01`–`0x11`. Different `CREATE` address derivation. Gas metering unrelated to mainnet's. | Almost certainly the largest single delta obtainable, and it absorbs Abstract, Sophon, Lens, Cronos zkEVM. |
| **HyperEVM** (Hyperliquid) | ⚠️ none public — see [Blocked](#blocked-on-evidence) | Read precompiles at `0x…0800`+ exposing L1 order-book state (positions, spot balances, oracle px). `CoreWriter` at `0x3333…3333`. Dual block schedule: fast small blocks interleaved with slow large blocks in one chain. | Top-tier mindshare, top-tier divergence, and it fails the evidence gate — which forces the repo to decide its policy on closed-source chains. |
| **Sei** | `sei-protocol/sei-chain` | Cosmos-SDK EVM with OCC parallel execution. Dual address space (`0x…` ↔ `sei1…`) reconciled by an association precompile. Custom precompile block around `0x…1001`–`0x…100C` for bank, staking, gov, oracle, wasm, IBC. | Custom precompile *addresses* at last — the current table's one universal address (`0x0100`) finding needs a counterexample to be load-bearing. |
| **Kaia** (Klaytn) | `kaiachain/kaia` | An entire parallel transaction-type space: `0x08`–`0x4x` value-transfer / fee-delegated / partial-fee-delegated variants, **two signers on one transaction**, and account-key types decoupled from the address. | The richest [TX-TYPES.md](TX-TYPES.md) row available on any chain. Mid mindshare, but the row is unique. |
| **Linea** | `Consensys/linea-besu` (+ `linea-monorepo`) | Prover constraints leaking into consensus: `MODEXP` operand caps, restricted/disabled `RIPEMD160` and `BLAKE2F`, field-size limits on precompile inputs. | Independently reproduces the OP Stack "fault-proof constraint became a consensus rule" pattern. Two instances make it a law; one makes it an anecdote. |
| **Celo** | `celo-org/op-geth` + `celo-org/optimism` | Fee-currency abstraction: gas paid in ERC-20 via a `FeeCurrencyDirectory`, carried by tx type **`0x7b`** (CIP-64). | A custom transaction type *on top of OP Stack* — a direct counterexample to "OP Stack derivatives inherit the envelope". Highest-leverage test of the `op-stack` framework row. |

## Tier 1 — high mindshare, framework representatives, or a novel fee/gas model

| Chain | Client to pin | Expected divergence |
|---|---|---|
| **Berachain** | `berachain/beacon-kit` (EL is stock geth/reth) | Predicted **near-empty delta** — and that emptiness is the finding, exactly as with World Chain. Divergence is in consensus: no beacon chain, so deposits, withdrawals, and `EIP-4788` beacon-root semantics are BeaconKit's, not Ethereum's. |
| **Tempo** | verify — Stripe/Paradigm, Reth-based | Stablecoin-denominated gas, fee-payer abstraction, payment-priority lanes. Fee model is the whole story. Confirm source availability before scheduling. |
| **Arc** | verify — Circle, Reth EL + Malachite BFT | USDC as the gas token: no native token at all. Deterministic sub-second finality, opt-in privacy. Breaks the native-cap axis by design. |
| **MegaETH** | verify — may be partly closed | ~10ms mini-blocks under ordinary blocks, in-memory state, single sequencer, heterogeneous node roles. Block/tx *envelope* and finality semantics diverge far more than the EVM does. |
| **Plasma** | verify — Reth-based | Protocol-level paymaster making USDT transfers zero-fee (a state transition with no fee payer), custom gas tokens, BTC bridge. Large cap plus stablecoin mindshare. |
| **Cosmos EVM** (`evmd`) **FW** | `cosmos/evm` | One row absorbing Cronos, XRPL EVM, ZetaChain, and much of Injective. Cosmos-SDK-module EVM: pallet-style precompiles, IBC-visible state, no uncles, instant finality. |
| **Frontier / Moonbeam** **FW** | `moonbeam-foundation/moonbeam` | Substrate EVM: precompiles in the `0x0400`/`0x0800` ranges exposing pallets (staking, governance, XCM). Represents the whole Polkadot EVM family. |
| **Polygon CDK / zkEVM** **FW** | `0xPolygonHermez/zkevm-node` | Distinct from the existing `bor` row. `forkID`-gated semantics, disabled precompiles, prover-bounded inputs. Absorbs X Layer, Astar zkEVM, Immutable. |
| **Scroll** | `scroll-tech/go-ethereum` | Disabled precompiles, restricted `MODEXP`, `SELFDESTRUCT` handling, L1-fee predeploy distinct from OP Stack's. |
| **Taiko** | `taikoxyz/taiko-geth` + `taiko-mono` | Based rollup. Every block opens with a privileged **anchor transaction** from a fixed golden-touch address with a constant signature — a system tx that is not any registered type. |
| **Mantle** | `mantlenetworkio/mantle` | OP Stack fork with MNT as gas token and a `tokenRatio` multiplier applied to gas cost; EigenDA instead of blobs. Modified fee model, inherited EVM. |
| **Sonic** | `0xsoniclabs/sonic` | Lachesis aBFT DAG, no uncles, Opera lineage diverged from geth years ago, `SFC` system contract, fee subsidies. |
| **Gnosis** | `gnosischain/gnosis` spec + Nethermind/Erigon | xDAI gas token with otherwise full Ethereum client compatibility — the cleanest available "gas token is the only delta" control case. |
| **Injective** | `InjectiveLabs/injective-core` | Native EVM alongside a frequent-batch-auction exchange module; EVM↔bank state shared. Very high mindshare. |
| **Flare** | `flare-foundation/go-flare` | FTSO and State Connector precompiles at addresses like `0x1000…0002` — far outside the mainnet or `0x0100` ranges. Directly stresses the precompile enumeration. |

## Tier 2 — clears the $100M floor; divergence likely real but narrower

`Ronin` (`ronin-chain/ronin` — Consortium DPoS, gas sponsorship, heavy gaming mindshare) ·
`Core` (`coredao-org/core-chain` — Satoshi Plus, BTC staking) ·
`Cronos` (Cosmos EVM derivative) ·
`Blast` (`blast-io/blast` — native rebasing yield changes balances with no transaction, a genuine state-transition delta) ·
`Fraxtal` · `Metis` · `Kava` · `Rootstock` (`rsksmart/rskj` — merge-mined, forked the EVM early enough that opcode-level drift is likely) ·
`Conflux eSpace` · `IoTeX` · `XDC` · `Chiliz` · `Story` (`piplabs/story` — IP-registry precompiles) ·
`ZetaChain` · `Somnia` · `0G` · `Etherlink` · `Botanix`.

## Tier 3 — do not give these rows

OP Stack derivatives with no state-transition delta: **Unichain** (Flashblocks is block
*building*, like World Chain), **Ink**, **Zora**, **Mode**, **Soneium**, **Lisk**,
**Katana**, **Codex**. Cover them as a membership list under `op-stack`, and only
promote one if it ships a custom predeploy, precompile, or tx type. ZK Stack chains
(**Abstract**, **Sophon**, **Lens**) likewise belong under the zkSync row.

Not EVM, out of scope regardless of cap: Solana, Sui, Aptos, Starknet, Fuel, Canton, TON.

## Blocked on evidence

**Hyperliquid / HyperEVM** has no public node source, and it is simultaneously one of the
most divergent and most-used EVMs in existence. **MegaETH**, **Arc**, and **Tempo** may
be in the same position depending on release state — each needs a source check before it
is scheduled, not after.

The method says pinned clones, not documentation. Excluding these chains keeps the
dataset honest and leaves its most interesting rows empty. Suggested resolution: allow a
`evidence: documented` row kind that is explicitly quarantined — findings recorded, but
never counted in any comparison that claims to be source-derived. That decision should
be made deliberately, in [SCHEMA.md](SCHEMA.md), before the first such chain is added.

## Framework coverage, current and proposed

| Framework | Row | Absorbs |
|---|---|---|
| OP Stack | ✅ `op-stack` | Base, opBNB, World Chain, Unichain, Ink, Zora, Mode, Soneium, Lisk, Celo¹, Mantle¹ |
| Avalanche subnet-evm | ✅ `avalanche-subnet` | all L1s/subnets |
| Arbitrum Nitro / Orbit | 🔄 in progress | Nova, ApeChain, Orbit chains |
| ZK Stack | ❌ proposed | Abstract, Sophon, Lens, Cronos zkEVM |
| Cosmos EVM (`evmd`) | ❌ proposed | Cronos, XRPL EVM, ZetaChain, Injective¹ |
| Frontier (Substrate) | ❌ proposed | Moonbeam, Moonriver, Astar |
| Polygon CDK | ❌ proposed | X Layer, Immutable, Astar zkEVM |
| BeaconKit | ❌ proposed | Berachain |

¹ diverges from its framework enough to likely need its own row anyway — which is
exactly the thing worth measuring.
