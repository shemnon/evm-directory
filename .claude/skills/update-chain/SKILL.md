---
name: update-chain
description: Bring one EVM Directory chain row up to date. It finds the newest stable client release and checks whether the chain's own mainnet hard-forked since the pinned version, or only its testnet did. It then bumps the client and companion pins and re-derives every axis of chains/<slug>/chain.yaml from the new source, regenerates, and runs the gates. Use when asked to update, refresh, re-pin, or bump a chain, or after a network upgrade.
argument-hint: <slug>
---

# Update a chain across every axis

One row, `chains/<slug>/chain.yaml`, brought up to the newest stable client release.
The steps run in order. Steps 4 and 5 can stop the run.

**Rules that apply at every step** (from SCHEMA.md; do not relearn them the hard way):
- Facts come from the pinned source. Every fact you add or change carries a `src:`
  resolving in the **new** clone, a `src_live:` with an `@ <block>`, or at worst a
  `src_doc:`. If you cannot re-establish a fact, mark it `status: unrecorded` with a `note`.
- Never hand-edit `website/` or the generated tables (`MATRIX.md`, `PRECOMPILES.md`,
  `TX-TYPES.md`, `LINEAGE.md`). Regenerate them.
- Provenance (`src`, `†`, `via` pills) renders only on chain pages. This skill edits data,
  not renderers. If you do touch a renderer, keep provenance out of aggregate surfaces.
- Read fork-gated facts from the fork that is **active on mainnet now**, not from the
  newest fork in the tree. A pending fork is recorded as `pending`, and its effects wait
  for activation (the bnb/Pasteur precedent).

## 1. Sync the repo and read the row

```bash
git -C "$ROOT" status --short          # must be clean; otherwise stop and ask
git -C "$ROOT" switch main && git -C "$ROOT" pull --ff-only
```

`$ROOT` is the repo root (`/Volumes/TendiesTown/EVM-Directory`). Then read all of
`chains/<slug>/chain.yaml` and `chains/<slug>/SUMMARY.md`. If the slug is not given or
does not exist, list `chains/` and ask.

## 2. Resolve the newest code

```bash
tools/.venv/bin/python .claude/skills/update-chain/scripts/pin_status.py <slug>
```

It reports every pin (client and companions) against upstream: the newest stable tag
of the same naming family and its peeled commit, newer unstable tags, how far a branch
pin's default branch has moved, when the row was pinned, and which of the row's own
declared forks fall between that date and now. It also lists the rows the change
reaches. Use `--json` if you want to parse it.

Triage by row kind before going further:

| The report says | Do this |
|---|---|
| `DEAD` | Stop. A dead row's pin does not move (SCHEMA.md `dead:`). Tell the user. Proceed only if they report the chain restarted, and then run `tools/livecheck.py <slug>` first. |
| `DOCUMENTED` | There is no pin. Tell the user that only `src_doc:`/`src_live:` facts can move. Offer to re-probe and re-read the docs instead. |
| `SHARED` | The pin belongs to the named row. Run this skill on that row. This row only mirrors `client.version`/`commit` and keeps its own `forks.timeline`. |
| role `stack` / `template` | Not a network. The "associated mainnet" is its flagship or reference deployment (`FLAGSHIP` in `tools/model.py`, e.g. op-stack → optimism) plus each descendant's own schedule (OP: the superchain-registry companion). Check forks there. |
| `prelaunch` | There is no mainnet, so every fork is testnet-only and that is expected. Check `live_probe.awaiting_endpoint` and follow the Arc conventions already in its row. |
| no newer stable tag, branch pins current | Nothing to bump. Still check the fork steps below: an **overdue pending** fork is a data update even at the same pin. |
| newest release is unstable only | Do not pin it. If a mainnet fork *requires* it (release notes say "mandatory for mainnet"), ask the user. |

Choose the **target**: the newest stable tag per pin. Companions move when the client
does, or when their own schedule or definitions changed.

## 3. Fetch the new code next to the old

Keep the old tree so you can diff. If the row has no clone yet, run `tools/clone.sh <slug>`
first, which clones at the current pin.

```bash
C=chains/<owner>/repos/<name>          # owner = the slug, or its shared_with row
git -C $C fetch --depth 1 origin tag <new-tag>
git -C $C diff --stat <old-commit> <new-commit>
git -C $C diff <old-commit> <new-commit> -- <forks.src path and every file the row cites>
gh release view <tag> -R <repo>        # for EVERY release between the pin and the target
```

A branch pin (the superchain-registry) is fetched by commit: `git -C $C fetch --depth 1 origin <sha>`.

## 4. Did the chain's mainnet fork?

Collect evidence from four places:

1. **The row's own timeline**, as reported by `pin_status.py`: `ACTIVATED SINCE PIN` and `OVERDUE PENDING`.
   Only `activation_time` entries can be dated. For a `pending, untimed` fork keyed
   by `activation_block`, compare the block against the live head. For one keyed by
   `activation_condition` (a governance vote, a runtime `spec_version`, a forkID),
   check that condition directly.
2. **The schedule source diff** (`forks.src`, plus per-chain configs such as
   superchain-registry `configs/mainnet/*.toml` vs `configs/sepolia/*.toml`). Clients
   keep mainnet and testnet schedules side by side: BSC's `BSCChainConfig` vs
   `ChapelChainConfig`, geth's `MainnetChainConfig` vs `SepoliaChainConfig`/`HoodiChainConfig`.
   For each fork field the diff adds or changes, record its **mainnet** time and each
   **testnet** time. `nil`/absent means unscheduled.
3. **Release notes** for every intermediate release: "hard fork", "mandatory upgrade",
   fork names, "mainnet"/"testnet" activation lines.
4. **The network itself**, for any candidate mainnet activation.
   `eth_getBlockByNumber("latest")` shows whether the head timestamp is past it. Where the
   fork changes something addressable, also run one behavioural probe at a post-activation
   block, such as `eth_call` to a new or retired precompile.

Classify the outcome:

- **Mainnet fork activated since the pin**, or an overdue pending fork you confirmed
  live: go to **thorough mode** (step 6 plus step 7).
- **Mainnet fork scheduled but not yet active**: record it as `status: pending` with its
  `activation_time`. Keep reading facts from the currently active set. Tell the user the
  date. This alone is routine mode.
- **Testnet-only fork** (a testnet time, no mainnet time at the target tag): **notify
  the user**. Give the fork name, which testnet, its activation date, and "mainnet:
  unscheduled at <tag>". Ask whether to record it the way Arc does (`status: pending`
  with a note saying it is testnet-only at that tag) or to leave it out. It does not make
  this a mainnet update.
- **No mainnet fork**: go to step 5.

## 5. No network update: ask before continuing

If no mainnet fork activated since the last pin, ask with `AskUserQuestion`. Include any
testnet-only notice from step 4 in the same message. Offer:

- **Proceed with a routine bump**: move the pins and re-check each axis against the diff.
- **Stop**: change nothing. Report what you found (target tag, testnet notices, upcoming forks).

If they stop, end the run without editing anything.

## 6. Bump the pins and update every axis

1. Edit `client.version` and `client.commit` (the full 40-hex **peeled** commit from
   `pin_status.py`, never an annotated tag-object sha). Do the same for each moved
   companion. Mirror the change into every row that `shared_with`s this one (optimism
   mirrors op-stack).
2. Run `tools/clone.sh <slug>`. It must print `cloned` or `ok`. A `WARN` means the tag
   points somewhere other than the pin: stop and resolve that first.
3. Walk **all ten axes** with [axes.md](axes.md). Routine mode re-reads what the diff
   touched. Thorough mode re-derives each axis from the new fork's code path.
4. Update the prose that names the old state. `lineage.sync_point` always changes. So do
   the `SUMMARY.md` `Reference:` line and fork table, and every mention of the old tag
   or short sha:
   ```bash
   grep -rn --exclude-dir=repos --exclude-dir=website -e '<old-tag>' -e '<old-sha8>' .
   grep -n -i -e 'not yet' -e 'pending' -e 'will ' -e '<fork-name>' chains/<slug>/*
   ```
   Also check `findings.yaml` for claims about this chain that the update changes.
5. For each row in the report's `reaches` line, check that the row's inherited facts
   still hold. For OP Stack, re-read each descendant's fork times from the
   superchain-registry at the new companion pin.

## 7. Thorough mode: when mainnet forked

In addition to step 6:

- **Activation.** Flip the timeline entry from `pending` to active and set its exact
  `activation_time` from the mainnet config. Add any fork first declared after the pin,
  and set `mainnet_equivalent`. If the fork raises the row's Ethereum equivalence, update
  `baseline_fork` and re-examine every `removed` EIP and every fork-gated opcode.
- **The basics, re-derived rather than diffed:**
  - the active precompile map, which gives `base_map.present`, `p256verify`, and each custom address
  - `tombstoned_at` entries that have now passed, which become `status: tombstoned`
  - the tx envelope the network accepts
  - the jump table
  - header fields
  - the fee function
  - fork-installed system contracts
  - block time
- **Live confirmation.** Choose a block after activation and set
  `live_probe.observed_at_block` to it. Replay every existing `src_live:` at that height
  and update the results and `@ <block>`. Add a probe for each addressable change the
  fork made. Run `tools/livecheck.py <slug> --deep`. `fork ok … unchanged since the pin`
  across a fork you just recorded means the re-pin did not take. Remember that Osaka-style
  forks add no header marker (see SITE.md).
- **Check the checker.** Open this row's extractor in `tools/verify.py` (`EXTRACT`). If it
  names a fork's map literally (`"var PrecompiledContractsOsaka = "`), it checks the old
  map from the day the fork lands, and still passes because the addresses rarely change.
  Switch it to `geth_active`, and return tombstoned stubs as `Found(..., dead)` (see
  `ex_scroll`, `ex_bnb`). Otherwise a correct `tombstoned` reads as `ALIVE`.
- **Cross-check `chain_id`.** Check `eth_chainId` against both `chain.chain_id` and
  `live_probe.chain_id`.
- **Descendants.** Every row that inherits from this one inherits the fork's changes. For
  each, confirm whether it activated the same fork, and at what time.

## 8. Regenerate and gate

```bash
tools/.venv/bin/python tools/verify.py <slug> <each reached row>   # source cross-check, needs clones
tools/.venv/bin/python tools/verify.py --no-clones                 # whole dataset, internal consistency
tools/.venv/bin/python tools/livecheck.py <slug>                   # rows with src_live: facts
tools/.venv/bin/python tools/generate.py
tools/.venv/bin/python tools/site.py
tools/.venv/bin/python tools/generate.py --check && tools/.venv/bin/python tools/site.py --check
```

`verify.py` must end `clean`, with no `UNLISTED`, `MISSING`, `BAD SRC`, or `PIN
MISMATCH`, and an evidence `none` count of 0. When a gate fails, fix the data. Never
weaken the check. Report any failure you could not fix verbatim.

## 9. Report and hand off

Tell the user:
- the pins, old → new, for the client and each companion
- the fork classification, with the evidence for it
- testnet-only notices
- upcoming forks and their dates
- per axis, what changed, or "unchanged, the diff did not touch its sources"
- facts downgraded to `unrecorded`, and why
- descendants affected
- each gate's result

Then ask whether to commit and open a PR. Do not do either unasked. If they say yes:
- Branch: `chains/<slug>-<new-tag>`.
- Commit subject: `<slug>: <what changed, stated as the finding>`, following the style
  in `git log`, e.g. `bnb: Pasteur is live — 0x64/0x65 tombstoned, precompile map moves`.
- Commit body: prose saying what the new source showed, then the `Co-Authored-By` trailer.
- Stage `chains/`, the regenerated tables, `website/`, and `findings.yaml` together, so
  that CI's `--check` gates pass on the commit itself.
