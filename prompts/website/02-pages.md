# 02 — Page contracts

Each page's sections, in the order they must appear. "Grid" always means the table
specified in [03-grids.md](03-grids.md), headed with the axis name.

## Overview — `index.html`

1. **Axes** — one card per axis plus Silent divergences. Title links,
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
| **Opcodes** | grid · notes · execution environments beside the EVM (enumerated sets, then named-but-not-enumerated) · PREVRANDAO derivation · per entry |
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

Evidence also carries two fixed, data-generated sentences when they apply: the operator's
**current** affiliation with this chain (from `operators.yaml`), and a credit for merged
corrections supplied by contributors affiliated with this chain
(`affiliated_contributions:`, linking each issue). Both are facts about who touched the
row, so they sit with its provenance — on the chain page only, never on an axis page, an
index or a grid.

**Repriced precompiles** lists entries whose divergence is pricing only, stating that
current live pricing is the reference rather than pricing at any historical fork. These
are deliberately *not* flagged in the aggregate grids; see
[03-grids.md](03-grids.md#gas-divergence).

## Silent divergences — `silent-divergences.html`

Categorical summaries only: **by section** (entries, which chains) and **by chain**
(entries, which sections), then a compact list of every entry linking to the chain page.
No note text — detail lives in the drill-down. No statistics tiles.

## Ordering & execution — `axes/ordering.html`

One row per lifecycle question, chains as columns, each cell a `verdict:` from
`tx_lifecycle:`. The `ethereum` column is the baseline — mainnet reaches none of these
states, because validation precedes ordering — and every other column is a delta against
it. An empty cell is `—` ("not established"), never `=` ("as mainnet"): silence here is
absence of evidence, and the two must not look alike.

## Proofs — `axes/proofs.html`

Two banded grids, not one, because the axis asks two questions and a reader arrives
with only one of them. **Proving the state transition** carries `state_transition`,
`proving_live`, `settlement` and `prover_constraints`; **Proving state to a caller**
carries `state_proof` and `proof_root`. Chains are rows, questions are columns, each
cell a `verdict:` from `proofs:`.

`consensus` must not render as a deficiency. It is the correct answer for every L1 —
the validator set IS the settlement layer — and a design that greys it out, sorts it
last or pairs it with a warning colour is making a claim the dataset does not.
`proving_live` is the column that keeps a roadmap from reading as a fact, so it is never
collapsed into `state_transition` even though four rows in five make it redundant.

An empty cell is `—` ("not established"), never `=` ("as mainnet"), as everywhere else.

## Instruction sets that are not the EVM

A set with no 256-entry byte table renders on the **chain page**, whole, one table per
opcode family — not as rows in the opcodes grid, which is keyed by mainnet's byte table
and has nothing to align them against. The opcodes axis page carries a summary line per
set (dispatch, role, size) linking to it, and lists separately the rows that NAME another
VM without enumerating it, because that gap is a fact about the dataset and should be
visible rather than absent.

Privilege is marked per instruction, inline, not as a footnote listing kernel-only names
under the table. The reader's question is "may my contract issue this one", and a
footnote answers it only after they have matched two lists by eye.

## Method is not a page

The site carries no page about itself. `SCHEMA.md`, `SITE.md` and `METHOD.md` are
repo-only documents: useful to someone reading or extending the dataset, noise to
someone who arrived with a question about a chain. Every note in `findings.yaml`
therefore names one of the eleven axes and renders on that axis page; a note with no
axis page is a build error, not a note that lands on a method page.

The one repo document the site links to is `CONTRIBUTING.md`, and it does not render it.
Every page's footer carries **Report an inaccuracy**, opening the repository's issue form
— the correction form pre-filled with the chain on a chain page, the form chooser
elsewhere — and the operator line on a chain page links to the disclosure.
