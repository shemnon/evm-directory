# The website build

The site's structure is specified in [`prompts/website/`](prompts/website/); this file
covers only how the build runs.

`website/` is **generated output**. Nothing in it is hand-edited; every file there is a
function of the dataset plus `tools/site.py`. Edit the data, re-run the build.

```
tools/site.py                    # incremental — rebuild only what changed
tools/site.py --all              # rebuild every page
tools/site.py --check            # exit 1 if website/ is stale, write nothing
tools/site.py --list             # every page, and the inputs it reads
tools/site.py base               # just chains/base.html
tools/site.py axes/precompiles.html
tools/site.py chains/            # every chain page
tools/site.py --clean            # delete website/ and rebuild from scratch
```

Open it with any static server, or straight off disk — every link and asset path is
relative, so `file://`, GitHub Pages at a subpath, and `python3 -m http.server` all work
unchanged.

```
python3 -m http.server -d website 8000     # then http://localhost:8000
```

## Inputs

| Input | Feeds |
|---|---|
| `chains/<slug>/chain.yaml` | that chain's page, and every axis page |
| `chains/<slug>/SUMMARY.md` | the "Full write-up" section of that chain's page |
| `findings.yaml` | the home page, the axis pages, and every chain a finding names |
| `SCHEMA.md` | `method.html` |
| `SITE.md` | `method.html` (this file) |
| `tools/assets/site.css`, `site.js` | copied to `website/assets/` |

`findings.yaml` is the one **content** file in the pipeline — the place where a human
says what the dataset means. Everything else on the site is derived. A finding is
written once and surfaces in three places, in two voices: the home page and its `axis:`
page carry the full cross-chain survey, while each chain in its `chains:` mapping gets
only its own slice — the note's `lede`, that chain's gloss, and a link to the survey.

## Regenerating after a change

The build is dependency-tracked, so the honest answer to "what do I re-run" is almost
always just `tools/site.py`. It hashes every page's declared inputs into
`website/.manifest.json` and rebuilds only the pages whose inputs actually moved.

| You changed | Run | What rebuilds |
|---|---|---|
| one `chains/<slug>/chain.yaml` | `tools/site.py` | 13 pages: that chain page, all 8 axis pages, home, both indexes, `method.html` — **not** the other 18 chain pages |
| one `chains/<slug>/SUMMARY.md` | `tools/site.py` | that chain page only |
| `chains/op-stack/chain.yaml` | `tools/site.py` | the above, **plus its five descendants** (Base, Celo, opBNB, OP Mainnet, World Chain), since they inherit its entries |
| `findings.yaml` | `tools/site.py` | home, axis pages, and every chain page |
| `SCHEMA.md` or `SITE.md` | `tools/site.py` | `method.html` only |
| `tools/site.py`, `model.py`, or an asset | `tools/site.py` | **everything** — the HTML is a function of the code too |

`findings.yaml` is an input to *every* chain page, not only the ones currently named in
a finding. Narrowing it to the named chains would be more precise and would be wrong:
adding a finding that names a chain for the first time has to rebuild that chain's page,
and a dependency set that only lists today's matches cannot know that. The build errs
toward rebuilding.

To force a page regardless of whether its inputs moved, name it:
`tools/site.py base`, `tools/site.py axes/cryptography.html`, `tools/site.py chains/`.

`tools/site.py --list` prints the full dependency table if you want to check what a
given page actually reads.

## Full regeneration

```
tools/.venv/bin/python tools/generate.py    # the four top-level Markdown tables
tools/.venv/bin/python tools/site.py --all  # the website
```

`generate.py` and `site.py` read the dataset through the same `tools/model.py` — the
same ordering, the same address canonicalisation, the same stack-inheritance and
EIP-resolution rules — so the Markdown tables and the website cannot drift apart on
what a row says.

## The manifest

`website/.manifest.json` records, per page, the content hash of every input it read,
plus a hash of the renderer itself. It holds content hashes and no timestamps, so it is
byte-identical for the same inputs on any machine — which is why it is **committed**
rather than ignored. Without it in the tree, `--check` on a fresh clone would report
every page stale and be useless as a CI gate.

Because the hashes are over content, `touch` does nothing: only a real edit triggers a
rebuild.

## Keeping it honest in CI

```
tools/verify.py                 # re-extract facts from source, diff against chain.yaml
tools/site.py --check           # fail if website/ does not match the dataset
```

`--check` writes nothing and exits non-zero with the list of pages that would change,
so a commit that edits `chain.yaml` without rebuilding the site is caught rather than
silently shipping a stale page.

## Dependencies

Python 3 with `pyyaml` and `markdown`:

```
python3 -m venv tools/.venv
tools/.venv/bin/pip install pyyaml markdown
```

No Node, no bundler, no external network at build or view time. The pages embed no
webfonts, scripts or images from other hosts, so they render identically offline.
