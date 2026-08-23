# 06 — Presentation

## Register

A dense reference tool. Monospace for data, system sans for prose, tight rows, no
decorative spacing. It should read like something you scan, not something you are being
walked through.

## Colour

Define a complete light palette as tokens on bare `:root`; redefine only the tokens under
`@media (prefers-color-scheme: dark)`. Never give a colour its only definition inside a
media block, and give `body` an explicit background.

**Red means exactly one thing: an entry the schema marks `severity: high`.** It is not an
emphasis device. Callouts that are merely interesting use the neutral note style. Status
glyphs keep their own colours (added green, removed red, modified amber, tombstoned
violet) and those are vocabulary, not emphasis.

## Tables

- Sticky header row; sticky first column on grids; `overflow: auto` on the container so
  the page body never scrolls sideways.
- Long text wraps inside its cell with `overflow-wrap: anywhere` — a 40-character hex
  address must not blow out the column.
- Row hover highlights the whole row including the pinned column.
- `scroll-margin-top` on every anchorable element, large enough to clear the sticky nav
  **and** the sticky table header beneath it. Without it a linked row lands underneath
  the chrome and looks broken.

## The chain picker

A header control, right-aligned, present on every page that has chain columns and
**absent** where chains are rows — a dead control is worse than none.

- All / None buttons plus a checkbox per chain.
- Persisted in `localStorage` under one key, so a three-chain view survives navigation
  between axes. Wrap every read and write in `try`/`catch`: it throws in some contexts
  and returns nothing in others, and the page must render correctly either way.
- Hiding a column re-runs every grid's filter on the page, because
  [hide-uniform depends on which columns are visible](03-grids.md#filtering).
- The summary reads `Chains: all`, `Chains: none`, or `Chains: N of M`.

## Progressive enhancement

Every table is complete in the HTML. With JavaScript disabled the site is fully readable;
the filter, the hide-uniform checkbox and the picker simply do not appear to work. No
content is ever produced by script.

## Constraints

No webfonts, no CDN, no external images, no network at view time. Inline nothing that
needs fetching. Relative paths everywhere.

Responsive: the nav wraps, the picker menu stays on screen, and grids scroll inside their
containers on a phone.
