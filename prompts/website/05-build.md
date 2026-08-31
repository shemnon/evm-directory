# 05 — Build

## CLI

```
tools/site.py                    incremental — rebuild only what changed
tools/site.py --all              rebuild every page
tools/site.py --check            exit 1 if stale; write nothing
tools/site.py --list             every page and the inputs it reads
tools/site.py --clean            delete website/ and rebuild
tools/site.py base               force one page (chain slug, axis name, path, or prefix)
tools/site.py chains/            force a directory
```

## Dependency tracking

Every page **declares the input files it reads**. The build hashes those inputs, plus a
hash of the renderer itself, into `website/.manifest.json`, and rebuilds only pages whose
inputs actually moved.

Hashes are over **content**, not mtime: `touch` correctly does nothing.

The renderer hash covers `site.py`, `model.py` and the assets. Changing any of them
rebuilds everything, which is the correct semantics — the HTML is a function of the code
as well as the data.

Expected scope, and worth asserting after changes:

| changed | rebuilds |
|---|---|
| one `chains/<slug>/chain.yaml` | that chain page, all axis pages, Overview, both indexes, Reference — **not** the other 18 chain pages |
| one `chains/<slug>/SUMMARY.md` | that chain page only |
| `chains/op-stack/chain.yaml` | the above, plus its five descendants |
| `findings.yaml` | Overview, axis pages, and every chain page (chain-scoped there) |
| `SCHEMA.md` / `SITE.md` | `method.html` only |
| generator or assets | everything |

`findings.yaml` is an input to *every* chain page, not only the ones a note currently
names. Narrowing it would be more precise and would be wrong: adding a note that names a
chain for the first time must rebuild that chain's page, and a dependency set listing
only today's matches cannot know that. **The build errs toward rebuilding.**

## The manifest

`website/.manifest.json` is **committed**. It holds content hashes and no timestamps, so
it is byte-identical for the same inputs on any machine. Without it in the tree,
`--check` on a fresh clone reports every page stale and is useless as a CI gate.

## Output

`--check` is the CI gate: it catches a commit that edits `chain.yaml` without rebuilding.
Pair it with `tools/verify.py`, which checks the dataset against pinned source.

The footer of every page reads `Generated <date>` — no rebuild instructions, no links to
methodology. Those live in `SITE.md`, rendered on the Reference page.
