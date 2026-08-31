# 02 — Page contracts

Each page's sections, in the order they must appear. "Grid" always means the table
specified in [03-grids.md](03-grids.md), headed with the axis name.

## Overview — `index.html`

1. **Axes** — one card per axis plus Silent divergences and Reference. Title links,
   one-line description.
2. **Chains** — filterable table: chain, chain ID, role, client, baseline, count of
   silent divergences. A footnote that `op-stack` and `avalanche-subnet` are not chains.
3. **Notes** — an *index*, one row per note: subject (linking to the note on its axis
   page), axis, chains. Not the note text.

No summary counts, no statistics tiles. Nobody arrives wanting to know how many rows
there are.

## Axis pages

| Page | Order |
|---|---|
| **Precompiles** | grid · notes · addresses that cannot be enumerated · per address |
| **Transaction types** | grid · notes · byte-range occupancy · transactions outside EIP-2718 · per type byte |
| **Opcodes** | grid · notes · execution environments beside the EVM · per entry |
| **System contracts** | grid · bytecode that changes with no transaction · per address |
| **EIP activation set** | grid · notes · baseline fork claimed · per EIP |
| **Cryptography** | grid · notes · authorizes with no verifier · per scheme |
| **Fees & envelope** | fee-property grid · header-fields grid · notes |
| **Lineage** | code lineage · fork lineage · notes · where lineage is not a tree |

**Baseline fork claimed** groups chains by the mainnet fork they claim, most recent fork
first. Within a group, the chain with the most recent *dated* activation leads; chains
gated on something other than a timestamp — an ArbOS version, a block number — have no
date and follow, marked as such rather than shown as blank.

**Lineage** carries two independent ancestries, and says on each that it implies nothing
about the other:

- **Code lineage** — which codebase each client forks. Roots are upstream projects
  (`go-ethereum`, `hyperledger-besu`, `reth`) plus a group for implementations with no
  shared client lineage. A chain whose client is itself another row's client hangs off
  that row.
- **Fork lineage** — each chain under the most recent mainnet fork it has merged, most
  recent fork first.

A per-chain merge graph belongs on the chain page, not here. *(Not yet built.)*

## Chain pages — `chains/<slug>.html`

Identity · evidence · notes naming this chain, scoped to it · silent divergences · forks · EIP deltas ·
transaction types · transactions outside EIP-2718 · transaction authorization · repriced
precompiles · precompiles · system contracts · system transactions · opcodes · fee model ·
header fields · own spec series · gotchas · full write-up (rendered `SUMMARY.md`) ·
reproduce.

This page is the drill-down target for every grid cell, so **every entry it lists needs a
stable anchor** — `precompiles-0x64`, `opcodes-0xd0`, `eips-7702`. See
[03-grids.md](03-grids.md#cell-links).

**Evidence** is the one place methodology is allowed: which client is pinned, at which
commit, whether the row rests on source, docs or live probes, and the commands to
re-verify it. Documented rows — no public client — say so plainly at the top.

**Repriced precompiles** lists entries whose divergence is pricing only, stating that
current live pricing is the reference rather than pricing at any historical fork. These
are deliberately *not* flagged in the aggregate grids; see
[03-grids.md](03-grids.md#gas-divergence).

## Silent divergences — `silent-divergences.html`

Categorical summaries only: **by section** (entries, which chains) and **by chain**
(entries, which sections), then a compact list of every entry linking to the chain page.
No note text — detail lives in the drill-down. No statistics tiles.

## Reference — `method.html`

Renders `SCHEMA.md` and `SITE.md`, then notes tagged `axis: method`. Nothing else. This
is the only page whose subject is method, which is why the nav calls it Reference and the
data pages never discuss it.
