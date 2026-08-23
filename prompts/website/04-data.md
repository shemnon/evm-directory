# 04 — Data model

Everything that interprets the dataset lives in `tools/model.py`, shared by
`tools/generate.py` and `tools/site.py`. The rules below are the reason it is shared:
each one is a place the two renderers could silently disagree.

## Ordering and naming

`ORDER` is the display order: baseline first, then the geth-line forks, then the OP
Stack node ahead of its descendants, then the independents. New rows go next to their
family, not at the end. `SHORT` gives every slug a column-width name.

Both are used by the Markdown tables and the site. Forking them is a defect.

## Address canonicalisation

`canon()` normalises an address to minimal even-length hex. Rows write the same address
at different widths — `0x0100` and `0x0000…0100` are both P256VERIFY — and keying on the
raw string splits one address into two rows, so a chain's *absence* never lines up with
the address it is absent from.

## Stack inheritance

A chain whose `lineage.upstream` is a `role: stack` row states **only its own deltas**.
Resolution is **override-by-key**: take the ancestor's entries, then let the descendant's
replace them. Applies to `precompiles`, `tx_types`, `system_contracts`, `eips` and
`tx_authorization`.

Every resolved value carries its **origin**, so the site can mark inherited cells `†` and
link them to the declaring row. "World Chain has `0x7e`" and "World Chain invented
`0x7e`" are different facts and the grid must not destroy the difference.

`tx_authorization` is the trap. OP Mainnet declares nothing but a note saying it has no
delta; reading the raw row renders it as though **no signature can authorize a
transaction on OP Mainnet**. Resolve fields (`key_binding`, `signers_per_tx`) and schemes
through the ancestor, marking what was inherited.

## Derived indexes

| helper | gives |
|---|---|
| `effective(chains, slug, section)` | one chain's complete set for an address-keyed section, with origins |
| `addr_rows(chains, section)` | address → {slug: entry}, across all chains |
| `eip_entry` / `eip_status` | one EIP on one chain, resolved; `unrecorded` → `?` |
| `tx_auth(chains, slug)` | resolved authorization fields, schemes and origins |
| `schemes` / `unpaired` | scheme → rows; and `authorizes: protocol` with `precompile: none` |
| `silent(chains)` | every `severity: high` entry, across all seven sections |
| `evidence_tally(chains, slug)` | counts of `src` / `src_live` / `src_doc` |
| `by_baseline(chains)` | chains grouped by claimed fork, newest first, then by most recent dated activation |
| `code_parent(chains, slug)` | the code-lineage parent, and whether it is another row or an upstream project |
| `baseline_opcodes(chains)` | the mainnet instruction set at the baseline fork |
| `entry_label(entries)` | display name for an address several chains declare |

Two rules inside these that are easy to break:

**`silent()` iterates address keys only** in the address-keyed sections. `mutable_bytecode`
and `dynamic_range` sit in the same mapping and are collected by name; iterating
everything counts them twice.

**`unpaired()` credits the row that declares a scheme**, not every descendant that
inherits it. Otherwise one finding on the OP Stack row is reported five more times.

## Provenance

Every non-obvious fact carries `src:`, `src_live:` or `src_doc:`, and which key it uses is
part of the fact. The site surfaces provenance **only** on chain pages and in per-entry
detail rows — never as prose on an axis page. See [07-voice.md](07-voice.md).

## Changing the schema

Adding a field to `SCHEMA.md` is a dataset change, not a site change, and it needs a
reason the grid cannot express otherwise. `divergence: gas` earned its place because
without it the grid had no way to tell "costs more" from "returns something else".
Document it in `SCHEMA.md`, and expect `verify.py` to have no extractor for it until one
is written.
