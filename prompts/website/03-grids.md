# 03 — Grids

The grid is the site. Everything else supports it.

## Shape

Rows are the thing being compared. Columns are chains, in `model.ORDER`. The first
column is sticky, the header row is sticky, and the whole thing scrolls inside its own
container — the page body never scrolls sideways.

Above every grid: a filter box, a **hide rows where every chain agrees** checkbox, and a
row count. Below it: the legend for whatever vocabulary that grid uses.

## Cell vocabulary

Address-keyed grids (precompiles, transaction types, system contracts) and the EIP grid
use the schema's own delta vocabulary:

| glyph | meaning |
|---|---|
| `=` | same as mainnet |
| `=ᵍ` | same behaviour, different gas — see [gas divergence](#gas-divergence) |
| `➕` | added |
| `➖` | removed, or never adopted |
| `⚠️` | modified — same address, different behaviour |
| `⊘` | tombstoned — present but always reverts |
| `◌` | pending · `◐` opt-in per deployment · `⏳` tombstoning scheduled |
| `†` | inherited from a stack ancestor |
| `?` | not recorded |
| *(blank)* | this chain has no entry at this address |

`?` means **deliberately not established**. It must never be rendered as a positive
claim, and an omitted entry must never silently become one.

Two grids use their own vocabulary because the delta words do not fit:

**Opcodes** — `✓` present with mainnet semantics · `★` present and divergent · `–` not
present. Rows are the full mainnet instruction set at the baseline fork, plus every
instruction any chain adds. Without the full set the grid can only show deltas, every
row is divergent by construction, and the hide-uniform control has nothing to hide. The
instruction set is recorded in `chains/ethereum/chain.yaml` under
`opcodes.baseline_set`, read from the pinned jump table — not hardcoded in the renderer.

**Cryptography** — the principal axis is the algorithm, and each algorithm gets **two
rows**, because the two questions come apart in both directions:

- *authorizes a transaction* — the client will accept a signature in this scheme
- *verifiable by a precompile* — contract code can check one

`✓` yes · `–` no · `ᴬᶜ` only through account-abstraction code, where the protocol runs
the account's own validator. A chain can carry P256VERIFY while a P-256 key cannot move
a wei, and the reverse also occurs; the grid must make both readable at a glance.

## Row identity

One row per **distinct feature**, not per address and not per spelling.

Splitting on the name string over-splits: `BN256_SCALAR_MUL` and `BN256_MUL` are one
precompile written two ways, as are `KZG_POINT_EVALUATION` and `KZG point evaluation`.
Use the schema's vocabulary instead:

- At an address **mainnet occupies**, `inherited`, `modified`, `tombstoned`, `removed`,
  `pending` and `unrecorded` all mean *this is mainnet's feature, possibly diverging*.
  One row, marked.
- A **separate row** is warranted only where the address genuinely carries unrelated
  features: an entry `added` at an address mainnet does not use, or an entry flagged
  `conflict`, which is how the dataset records a contested allocation.

Both rows show the same address. That is the point: `0x64` is ArbSys **and**
tmHeaderValidate.

Today this yields eight splits — `0x64`–`0x69` (BSC vs Arbitrum), `0x1001` (Sei vs
Monad), and World Chain's `0x0100` (P-256 vs proposed EdDSA, the one entry in the data
carrying `conflict: True`). Row anchors must be unique when two groups slugify the same.

## Gas divergence

A `modified` entry carrying `divergence: gas` returns the right answer and costs more.
That is a different class of problem from one that returns a different answer, and one
warning symbol for both overstates it badly — Polygon reprices eleven precompiles under
PIP-88 and changes none of their results.

Render those as `=ᵍ`, not `⚠️`. State the pricing on the chain page under **Repriced
precompiles**, where current live pricing is the reference.

## Cell links

Every cell backed by an actual entry links to that chain's page at that entry's anchor:
`../chains/tron.html#opcodes-0xd0`. A cell with no entry is not a link.

**Link to the row that declares the entry, not the row that inherits it.** OP Mainnet
inherits EIP-7702 from the OP Stack row and has no row of its own for it; linking to
`chains/optimism.html#eips-7702` lands on an anchor that does not exist. Resolve the
declaring chain first. This is the single easiest thing to get wrong here, and
[08-acceptance.md](08-acceptance.md) catches it.

Cell links carry no underline or colour — an underline in every cell turns the grid into
noise. Hover and keyboard focus get an outline.

## Filtering

**Text filter** — substring match over the row's text, updating the row count.

**Hide rows where every chain agrees** — "every chain" means every **visible** chain. If
a reader has narrowed to three columns, a row those three share is uniform even if a
hidden fourth differs. Compute it in the browser from visible cells. A server-computed
`data-uniform` attribute is the no-JS fallback and must not be the live definition.

`?q=` in the query string pre-fills the filter, so a filtered view can be linked.

A row addressed by `#hash` must be revealed even when a filter is hiding it.
