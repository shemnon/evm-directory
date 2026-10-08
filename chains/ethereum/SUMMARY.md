# Ethereum Mainnet — the baseline

**Chain ID 1 · role: `baseline` · live fork: Osaka (+BPO1, +BPO2)**

Reference client: [go-ethereum `v1.17.8`](https://github.com/ethereum/go-ethereum)
@ `a5790770`. All facts below were read out of that pinned tree, not from docs.

## Why geth and not execution-specs

`ethereum/execution-specs` is the normative spec and is the more honest citation,
but its default branch is `forks/amsterdam` — a fork **unshipped on mainnet** (it runs
on Sepolia as of 2026-10-06) — and its only
release tags are test-fixture bundles (`tests-zkevm@v0.8.0`, etc.). There is no
"latest mainnet spec" tag to pin. geth is used as the verification surface because
it is pinnable to a released version whose mainnet config is unambiguous. Where the
two could disagree, the spec wins; nothing here is close enough to that line to matter.

## Live fork state (verified, not assumed)

`params/config.go:MainnetChainConfig` gives activation timestamps:

| Fork | Activated | Notes |
|---|---|---|
| Shanghai | 2023-04-12 | |
| Cancun | 2024-03-13 | |
| Prague | 2025-05-07 | |
| **Osaka** | **2025-12-03** | current named fork |
| BPO1 | 2025-12-09 | blobs target 10 / max 15 |
| BPO2 | 2026-01-06 | blobs target 14 / max 21 — **current** |
| Amsterdam | `nil` on mainnet | **Sepolia only**, at `1791294816` (2026-10-06 13:53:36 UTC) |
| Bogota | `nil` | not scheduled on any network |

Fork ordering in geth is now `… Osaka → BPO1…BPO5 → Amsterdam → Bogota`
(`params/forks/forks.go`). Mainnet's spec carries no `amsterdamTime` and no
`bogotaTime`; Sepolia's carries `amsterdamTime`. So Amsterdam is implemented, running,
and **not a mainnet fact** — which is why it appears in this row's `forks.timeline` as
`pending` and nowhere in its `eips:` or `header_fields:`.

`BPO3` and `BPO4` blob configs exist in `params` and are on no mainnet schedule, and
`BPO5` is in the fork ordering with no blob config at all — a live-config trap for
anyone reading the constants rather than the schedule.

As of **v1.17.8 the mainnet and testnet schedules are no longer Go literals**: they
moved to `params/chainspecs/*.json`, loaded by `params/chainspecs.go:readChainSpec`.
`MainnetChainConfig` still exists as a symbol, but it is now a binding, not the data.

## The five counts

- **5 transaction types** — `0x00`–`0x04`, ending at EIP-7702 SetCode.
- **18 precompiles** — `0x01`–`0x11` contiguous, then `0x0100`.
- **5 system contracts** — real bytecode, not precompiles.
- **0 custom opcodes** — by definition.
- **1 metering unit** — gas.

## Findings that shape the rest of the dataset

**1. P256VERIFY arrived at mainnet last, not first.** `0x0100` (EIP-7951) went live
with Osaka in Dec 2025, but OP-Stack chains have shipped the identical precompile as
RIP-7212 at the identical address for much longer. So `0x0100` present on a chain
proves nothing about its fork level, and a contract that feature-detects secp256r1
support gets different answers on chains that are otherwise equivalent. Any chain
in this dataset with `0x0100` needs its *fork attribution* recorded, not just the address.

**2. The `0x11 → 0x0100` gap is load-bearing.** Mainnet's own jump from `0x11` to
`0x0100` established the convention that custom precompiles live far from the
mainnet range. Most forks follow it (Avalanche at `0x02..`, BSC at `0x64+`). Chains
that placed custom precompiles *inside or adjacent to* `0x01–0x11` are on a
collision course with future mainnet EIPs — that is a finding worth flagging loudly
per chain, not a stylistic note.

**3. "Prague-equivalent" is not a fact.** Prague bundled EIP-7702, EIP-2537,
EIP-2935, EIP-6110, EIP-7002 and EIP-7251. Downstream chains routinely adopt a
subset. This is precisely why `chain.yaml` carries an `eips:` map and why fork names
alone are recorded as *claims*, not measurements. Recording only "Prague" would
lose the actual differences this project exists to capture.

**4. Type byte `0x7e` is not arbitrary.** Typed envelopes are legal in `0x00–0x7f`
(`0x80+` collides with RLP list prefixes). OP Stack put deposits at `0x7e` — the top
of the legal range — to maximise distance from future mainnet allocations that grow
upward from `0x04`. Expect other forks to have been less careful.

## Open question

**Partly answered by v1.17.8.** This row used to note that geth defined `UBTTime`
after Bogota, with `IsUBT` described in comments as "the Verkle fork". That entry is
**gone**: the fork ordering now ends `Amsterdam, Bogota`, with no UBT. Whether Bogota
and Glamsterdam are the same upgrade under two names is still not resolvable from this
tree, and remains irrelevant to mainnet-today facts — flagged so it isn't silently
guessed at later.

## Re-verify

```
git clone --depth 1 --branch v1.17.8 https://github.com/ethereum/go-ethereum
grep -n 'TxType' core/types/transaction.go              # tx types
sed -n '/PrecompiledContractsOsaka = /,/^}/p' core/vm/contracts.go   # precompiles
cat params/chainspecs/mainnet.json                      # forks (moved here in v1.17.8)
grep -n 'Address = common.HexToAddress' params/protocol_params.go   # system contracts
```
