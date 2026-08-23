# 00 — Brief

Build a static reference site for a dataset of EVM chain differences. Render it into
`website/` from `chains/*/chain.yaml`, `chains/*/SUMMARY.md` and `findings.yaml`.

## What this is

A **reference tool**. Someone arrives with a question — *does Polygon reprice BN256?*,
*can a P-256 key sign on Base?*, *which chains put something at `0x64`?* — and the site
answers it in one screen and one click. It is not a report, not an argument, and not a
demonstration that the data is correct.

Ethereum Mainnet is the reference point. Every other chain is described as a delta
against it, in the fixed vocabulary [`SCHEMA.md`](../../SCHEMA.md) defines.

## Rules that override everything else

1. **Every page opens on its grid.** The rolled-up chain × entry table is the first
   thing below the page title. Nothing precedes it — no preamble, no summary tiles, no
   methodology. The grid is where investigations start.

2. **The grid is named for its axis.** `Precompiles`, `Transaction types`, `Opcodes` —
   never "The grid", never "Overview", never "Summary".

3. **Chains are columns; the thing being compared is the row.** Precompile addresses,
   type bytes, opcodes, EIPs and algorithms are rows. This holds for every axis.

4. **Below the fold is for caveats.** Notes, per-entry detail, occupancy charts and
   anything hedged sits under the grid, never above it.

5. **Dry.** No methodology, no evidence rules, no argument for correctness on any data
   page. The single exception is the per-chain page, which states where that chain's
   data came from. See [07-voice.md](07-voice.md).

6. **Self-contained and portable.** No external requests of any kind. Every link and
   asset path is relative, so the site works identically from `file://`, from GitHub
   Pages at a subpath, and from `python3 -m http.server -d website`.

7. **Nothing in `website/` is hand-edited.** It is a pure function of the dataset plus
   the generator. If output needs to change, change an input or the generator.

8. **As-shipped.** Cells describe what each chain's pinned client does now. Scheduled
   and in-flight forks are not modelled; where a page could be misread as forecasting,
   say so once, plainly.

## Stack

Python 3 with `pyyaml` and `markdown`, in `tools/.venv`. No Node, no bundler, no build
step beyond running the generator. Two entry points share one data model:

```
tools/model.py      the dataset: loading, ordering, inheritance, derived indexes
tools/generate.py   the four top-level Markdown tables
tools/site.py       website/
```

`generate.py` and `site.py` **must** read the dataset through `model.py`. Duplicating an
ordering rule, an address-canonicalisation rule or an inheritance rule in both is a
defect even when the two copies currently agree.
