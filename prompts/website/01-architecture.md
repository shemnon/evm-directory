# 01 — Architecture

## URL map

```
website/
  index.html                    Overview
  method.html                   Reference — the schema, and how the site is built
  silent-divergences.html       every severity: high entry, summarised
  chains/index.html             the chain list
  chains/<slug>.html            one per row in chains/ (19 today)
  axes/eips.html                EIP activation set
  axes/precompiles.html         Precompiles
  axes/tx-types.html            Transaction types
  axes/cryptography.html        Cryptography
  axes/opcodes.html             Opcodes
  axes/system-contracts.html    System contracts
  axes/fees-envelope.html       Fees & envelope
  axes/lineage.html             Lineage
  assets/site.css, site.js
  .nojekyll                     GitHub Pages: do not eat paths beginning with _
  .manifest.json                build state — committed, see 05-build.md
```

Depth is at most one directory. Asset and cross-page links are resolved from the page's
own depth, never from a site root, because there may not be one.

## The three kinds of page

**Axis pages** answer one question across all chains. Each leads with its grid and is
the destination for notes tagged with that axis. Wide layout.

**Chain pages** answer every question about one chain. This is the only place
provenance, evidence footing and long prose belong. Normal width.

**Index pages** — Overview, Chains, Silent divergences, Reference — route and summarise.
They hold no per-entry detail.

## Adding an axis

1. Add `(slug, Title, one-line description)` to the `AXES` list. This drives the nav,
   the Overview cards, and the `axis:` values `findings.yaml` may use.
2. Write `page_<slug>(chains)` returning a full page, leading with its grid.
3. Register it with the input files it reads (see [05-build.md](05-build.md)).
4. Nav order follows `AXES` order; put the new axis where a reader would look for it,
   not at the end.

## Navigation

One row: `Overview · Chains · <every axis in AXES order> · Silent divergences ·
Reference`, then the chain picker pushed to the right. The current page is marked. The
bar is sticky; anchored elements carry enough `scroll-margin-top` to clear it and the
sticky table header beneath it.
