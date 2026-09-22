# `chain.yaml` schema (v2)

One file per chain. **Ethereum Mainnet is the Schelling point**: every other chain's
entries are stated as a *delta against mainnet*, never re-described from scratch.

## Three orthogonal axes

Earlier drafts collapsed these into one `status:` field and drifted immediately.
They are separate because a single feature can vary along all three at once.

### 1. `status:` — how this differs from mainnet

Applies to entries in `precompiles`, `tx_types`, `opcodes`, `system_contracts`, `eips`.

| status | meaning |
|---|---|
| `inherited` | identical to mainnet at the chain's `baseline_fork`. Often omitted — implied by the baseline. |
| `added` | exists here, does not exist on mainnet |
| `removed` | exists on mainnet at the baseline fork, absent here. **Also covers "never adopted."** |
| `modified` | same address/number/name as mainnet, different semantics, gas, or encoding. **Must carry a `note`.** |
| `tombstoned` | present but permanently non-functional — always reverts or errors. **Not the same as `removed`**: calling a tombstoned address fails, while calling an absent one succeeds with empty output. The address is permanently consumed. |
| `pending` | specified or merged but not yet live on this chain |
| `unrecorded` | **deliberately not established.** Renders as `?` in aggregate tables. Use this instead of omitting a fact: an omitted entry falls back to `inherited`, which would silently assert equivalence to mainnet that nobody verified. |

`removed`, `modified` and `tombstoned` are the high-value rows — they are where
integrations break. A chain that is honestly EVM-equivalent produces a nearly empty
file, and that emptiness is itself the finding.

There is no `absent`. It was a synonym for `removed` and is gone.

### 2. `availability:` — is it on for every deployment?

| availability | meaning |
|---|---|
| *(omitted)* | always present when the fork is active. The default. |
| `optional` | opt-in per deployment. Requires `activation_condition`. |

Needed because subnet-evm chains enable precompiles individually in genesis, so
`status: added` alone would overstate what any given chain actually has.

### 3. `adoption:` — for the chain's own spec series

Applies **only** to `non_eip_specs` (ACPs, BEPs, TIPs, RIPs, WIPs). Never mixed with
`status:`, because "is this spec accepted" and "how does this differ from mainnet"
are unrelated questions.

`adopted` · `optional` · `draft` · `proposed` · `withdrawn`

### `forks.timeline[].status:` — fork lifecycle

A fourth, narrower axis, valid only inside `forks.timeline`. A fork is not a feature
being compared to mainnet, so it does not use the delta vocabulary above.

`active` (default, omitted) · `pending` (scheduled or declared, not yet live) ·
`skipped` (deliberately declined — BSC's BPO forks)

## Activation

- `activation_time:` — Unix timestamp. Only ever a number.
- `activation_condition:` — free text for non-temporal activation
  (`genesis key "feeManagerConfig"`, `SR governance proposal`).
- `tombstoned_at:` — timestamp at which a live entry becomes `tombstoned`, for
  scheduled deprecations that have not happened yet.

Never overload one key with both a timestamp and a prose condition.

## `divergence:` — what kind of difference `modified` means

Optional, on `precompiles` and `system_contracts` entries whose `status` is `modified`.

| divergence | meaning |
|---|---|
| *(omitted)* | the semantics differ: different result, different acceptance, different failure. The default. |
| `gas` | **pricing only.** Identical inputs produce an identical result; only the cost differs. |

Separated because they are not the same risk. A repriced precompile returns the right
answer and costs more; a semantically modified one returns a different answer. Polygon
reprices eleven precompiles under PIP-88 and changes none of their results, and marking
those the same way as Tron's `0x03` — which does not compute RIPEMD160 — overstates them
badly in any grid that shows one symbol per cell.

Gas divergence is therefore not flagged in the aggregate grids; it is stated on the
chain's own page. **Current live pricing is the reference**, not the pricing at any
historical fork.

## `severity: high`

Mark any divergence that fails **silently** — wrong results with no revert, no error,
and no signal to the caller. These are the findings most likely to cause losses and
least likely to be caught in testing. Reserved for that class; not a general
importance rating.

## Evidence rule

Every non-obvious claim carries its **provenance**, in one of three keys. Which key a
fact uses is part of the fact, not a footnote about it.

| key | meaning | reproduced by |
|---|---|---|
| `src:` | a path and symbol inside the pinned clone, e.g. `core/vm/contracts.go:PrecompiledContractsOsaka`. | `tools/verify.py` re-extracts and diffs |
| `src_doc:` | a URL to the chain's own documentation. **Weakest kind** — docs describe intent, and lag or contradict what shipped. | nothing; a human re-reads it |
| `src_live:` | an observation of the running network: an RPC method, the address or subject, and the **block height it was observed at**. | replaying the same call against an archive node at that block |

`src_live:` is *stronger* than `src_doc:` and answers a different question than `src:`.
Source says what a client would do; a live probe says what the network actually did.
For a chain with no public client it is the only primary evidence available, and for a
chain with one it catches the gap between the pinned tag and what validators run.

**A live claim must pin its block, exactly as a source claim pins its commit.** An
unpinned RPC result is not evidence — it is unreproducible *and* unverifiable, which is
worse than a doc link. The endpoint is declared once per chain:

```yaml
live_probe:
  endpoint: https://rpc.example.org
  chain_id: 999
  observed_at_block: 12345678      # the default height for this row's src_live entries
```

```yaml
precompiles:
  "0x0000000000000000000000000000000000000800":
    name: L1 read precompile
    status: added
    src_live: "eth_call @ 12345678 -> 0x0000...002a (32-byte position)"
    src_doc: https://example.org/docs/precompiles
```

Both keys may appear on one entry, and should when both exist: the doc states intent,
the probe states behaviour, and a disagreement between them is itself a finding.

`tools/verify.py` enforces this rather than trusting it. For every `src:` it resolves
each path — **every path in a comma-separated citation, not just the first** — against
the row's clone and its companions, then checks the `:suffix`: a symbol must actually
appear in that file, a line number must fall within it. Citing a real file is not
enough. Three citations in this repo pointed at real files and still lied: a line
number that had drifted onto a different constant, a path written relative to the wrong
directory, and a sibling that was one directory up. A `src_live:` with no `@ <block>`
is rejected outright.

**`status: unrecorded` is exempt, and the exemption is the whole reason the status
exists.** Such a row asserts nothing about the chain, so there is nothing to cite; its
`note:` states what was not established and why. `verify.py`'s tally counts these in
their own `unrecorded` bucket rather than in `none`, because folding them together made
a deliberate declaration indistinguishable from a forgotten citation — the bucket could
never be driven to zero, so nobody could tell what remained in it. A nonzero `none` is
therefore a defect: a fact that asserts something and does not say how it is known.

### `live_state:` — why a row is not live

Set on `chain:`, and only meaningful when `live: false`. `live: false` alone
conflates two situations that a reader must not confuse.

| live_state | meaning |
|---|---|
| `prelaunch` | the chain has never produced a mainnet block. Facts rest on source plus, at best, a TESTNET probe — so every `src_live:` on such a row states what the testnet did. Arc. |
| `halted` | the chain produced blocks and stopped, **at an observed height**. Its `src_live:` facts are real mainnet observations, frozen at the last block. Polygon zkEVM, Moonbeam. |
| `unreachable` | no endpoint answers, so whether it runs is **unknown**. Not a claim that it stopped — nothing was observed to stop. Artela. |

The distinction is not cosmetic. A `prelaunch` row's live evidence may be
contradicted by mainnet at launch — Arc's testnet runs a fork the mainnet schedule
does not contain — while a `halted` row's live evidence can never be contradicted,
because nothing further will happen. Neither is a claim about intent: a chain may be
halted because it was sunset or because it broke, and no probe distinguishes those.

Neither value is set once and forgotten. `tools/livecheck.py` re-probes every row
that carries `src_live:` facts and tests the head against exactly this field — a
`live: true` row whose head has stopped moving is a finding, and so is a `halted`
row whose head starts moving again. Moonbeam was found that way, a month after it
stopped. Two optional `live_probe` keys support the check:

| key | meaning |
|---|---|
| `awaiting_endpoint` | for a `prelaunch` row, the URL of the network it is waiting for. The row's `endpoint` is a stand-in testnet, so nothing about the real chain can be probed; this is checked separately and reports the moment it starts answering. Arc. |
| `awaiting_chain_id` | the chain id that endpoint should answer with, for the same reason `chain_id` exists. |

A `halted` row is **not** required to pin its own last block. Moonbeam's
`observed_at_block` is the *finalized* head at probe time and production ran 5,791
blocks past it, so the halt test reads the head's **age**, never its distance from
the pin.

### `dead:` — the chain is over

Set on `chain:`. A chain that stopped does not stay a maintenance problem forever;
at some point it becomes a **historical record**, and saying so is what stops it from
rotting quietly at the bottom of every table.

The key is `dead:` rather than a word about the data — an earlier draft called this
`mothballed:`, which named what the maintainer did to the row instead of what
happened to the network. The chain is the subject. Marking it dead is a statement that
this row is **complete and closed**, not that it is wrong. Its facts were true of a real network and can never be contradicted, because
nothing further will happen — that is the property `halted` already has and
`prelaunch` does not. What changes is the maintenance contract:

- **Nothing is deleted.** The row keeps every fact, every citation and its page. A
  dead chain is the only kind of row whose facts are permanently final, which makes
  it more citable than a live one, not less.
- **The client pin stops moving.** No version bumps, no re-extraction against newer
  tags. The pin names the client the chain died running. A newer release cannot
  describe a network that no longer executes anything.
- **It is not re-probed for freshness.** `tools/livecheck.py` still checks it, but
  only to catch a restart; a frozen head is the expected result and is reported
  under `dead`, not as work outstanding.
- **The reader is told, everywhere the row appears.** Liveness is an attribute of
  the chain, like `role` or `baseline_fork` — not provenance — so unlike `src:` it
  belongs in the aggregate surfaces too. MATRIX.md carries a `Liveness` row and the
  chains index a column, both showing `dead: shutdown` or `dead: abandoned` rather
  than a bare "dead".

#### `dead.how:` — an orderly shutdown and dying in your sleep are not the same event

The primary axis. A chain that was switched off on a published schedule and a chain
whose infrastructure simply rotted away both end up at `live: false`, and **nothing
else about them is alike** — not how it was established, not what evidence exists, and
above all not what a holder can still do about it.

| how | meaning | requires |
|---|---|---|
| `shutdown` | announced, scheduled, executed. Somebody switched it off on purpose and said so. | `src_doc:`, `announced:`, `last_block:` |
| `abandoned` | it stopped answering and **nobody said anything** — endpoints, explorer and client decayed until nothing was left. | `dark_after:`, `dark_before:`, `dark_evidence:` |
| `unrecorded` | it ended; which of the two is deliberately not established. | — |

**`abandoned` is not a claim that anyone chose to walk away.** It says only that
production stopped, no announcement was located, and the infrastructure rotted. Who
decided what, and whether anyone decided anything at all, is unknown and stays
unknown — Artela's organisation was still pushing code to other repositories months
after its chain stopped answering, which fits neglect and a quiet pivot equally well.
Read the word as *the chain was abandoned*, never as *they abandoned it*.

```yaml
# an orderly shutdown: the operator says so, and there is a way out
dead:
  how: shutdown
  recourse: claims
  announced: 2026-07-03
  src_doc: https://polygon.technology/polygon-zkevm
  last_block: 33391890
  last_block_at: "2026-07-03T15:55:44Z"
  user_deadline: 2027-12-31
  successor: null

# died in its sleep: nobody announced anything, and nobody can name the last block
dead:
  how: abandoned
  recourse: none
  dark_after: 2025-09-06        # last date it was observably alive
  dark_before: 2025-10-04       # first date it was observably gone
  dark_evidence:
    - "artscan.artela.network HTTP 200 2025-08-28, 521 by 2025-12-21 (Wayback)"
    - "every published RPC fails to connect, 2026-09-09"
  last_block: null              # unknown, and now unknowable
```

**A `shutdown` can only ever rest on a `src_doc:`.** No probe returns an
intention. `eth_blockNumber` says a chain stopped; it cannot say whether that was
planned. Intent is exactly what `src_doc:` is for — a statement by the operator about
what they meant — and this is the one place in the schema where the weakest evidence
kind is the *only* admissible kind. `verify.py` rejects a `shutdown` with no document,
because it asserts an intention with nothing behind it.

**An `abandoned` ending is established by decay, not by a block.** There is usually no last
block to name: by the time anyone notices, the endpoints that could have answered are
already gone. What can be established is a *window* — the last date the chain was
observably alive and the first date it was observably gone — from whatever outlived it:
archived explorer snapshots, the project site, the client repository's last push,
directory services dropping the chain id. `dark_after:` and `dark_before:` carry that
window and are required, because "it seems dead" without a bound is not an observation.

`unrecorded` is not a third kind of ending; it is the absence of a finding about which
of the two happened. Keeping it separate from `abandoned` is the same discipline that
keeps `unrecorded` out of `none` in `status:` — "we looked and found no announcement"
and "nobody looked" must not read alike.

#### `recourse:` — the part that costs people money

| recourse | meaning |
|---|---|
| `claims` | an interface exists to recover assets. Pair with `user_deadline:`. |
| `migration` | holdings were moved to another chain or token. Pair with `successor:`. |
| `none` | there is no way to recover anything. |
| `unrecorded` | not established. |

This is the field a reader actually needs and the one a liveness probe can never
produce. It is also the sharpest expression of the `how:` split: a `shutdown` usually
has a claims window or a migration and a deadline attached to it, while an `abandoned`
chain has nobody left to ask. `verify.py` therefore rejects `how: abandoned` paired
with `recourse: claims` or `migration` — a recovery process is something an operator
announces, and an operator who announced one did not stop answering.

#### `unreachable` is a probe result; `abandoned` is a conclusion

These are different layers and a row carries both. `live_state: unreachable` says what
happens when you dial the endpoints today: nothing. `dead.how: abandoned` says what
the maintainer concluded from that plus everything around it. The first is renewable
and could be reversed by one endpoint coming back; the second closes the row.

An earlier draft of this section held that an `unreachable` row could **never** be
closed, on the grounds that doing so would assert an ending nobody observed. That was
too strict, and `abandoned` is what it was missing. The rule it was really
reaching for is that an ending must be *bounded by evidence* — and there are two
admissible ways to bound one, not one:

- **a last block**, for a chain someone was watching when it stopped; or
- **a dark window**, for a chain that was already gone when anyone looked.

Artela has no last block and never will: every published endpoint was dead before this
row existed, so it holds no `src_live:` at all. It does have a window. The explorer
answered HTTP 200 on 2025-08-28 and 521 by 2025-12-21; the project site answered on
2025-09-06 and failed by 2025-10-04; every RPC now refuses to connect; OKX and
thirdweb have both dropped chain 11820; the client's last release is 2024-09-05 with
no default-branch push since 2024-11-15, while the organisation went on pushing to
*different* repositories into 2026. No shutdown was ever announced.

That is a chain that died in its sleep, established from what outlived it, and
`abandoned` is the word for it. What the row must not do is round it up into an
orderly shutdown or invent a final height — which is why `last_block:` stays null and
`how:` is not `shutdown`.

#### The procedure, for the next one

Two rows have died since this dataset began and a third (Harmony) is in a published
sundown plan, so this is written as a runbook rather than rediscovered each time.

1. `tools/livecheck.py` reports `STALE` on a `live: true` row. That is the trigger;
   it is not yet a finding.
2. **Confirm on at least two independent endpoints.** One provider's stalled node is
   not a halted chain. Check `eth_syncing` too — a node that knows it is behind is a
   different story from one that believes it is at the head.
3. **Pin the last block and its timestamp**, and record them. Do not assume the row's
   `observed_at_block` is the last block; it usually is not. If every endpoint is
   already gone there will be no last block — that is the `abandoned` path, and a
   bounded dark window replaces the height.
4. **Separate "stopped accepting transactions" from "stopped producing blocks."**
   They are rarely the same moment and the gap is itself a finding — Moonbeam
   produced 123,773 empty blocks over 9.5 days between the two.
5. **Look for an announcement.** Found → `how: shutdown` with the URL in `src_doc:`,
   plus `announced:` and `last_block:`. Looked and found nothing → `how: abandoned`,
   with the dark window and the evidence for it. Did not look → `unrecorded`.
6. Set `live: false`, the right `live_state:`, and the `dead:` block. Leave every
   other fact exactly as it stands, and stop bumping the client pin.
7. Regenerate. `verify.py --no-clones` will check the row's internal consistency.

### `evidence:` — the row's overall footing

Set on `chain:`. Defaults to `source`.

| evidence | meaning |
|---|---|
| `source` | a client repo is pinned; `src:` is the expected default for facts. |
| `documented` | **no public client exists.** No `client.commit`, nothing to clone. Facts rest on `src_doc:` and `src_live:` only. |

A `documented` row has no clone, so `clone.sh` skips it and `verify.py` reports it as
`SKIP (documented)` rather than a failure — a permanently-red build is a build nobody
reads, which would degrade verification for the rows that *can* be checked.

### Mixing in the aggregate tables

The generated tables **merge all three kinds without distinction.** A cell in
MATRIX.md may rest on source, docs, or a live probe, and does not say which.

This is deliberate, and it is a bet: that a merged table is more useful than a
correctly-hedged one, and that the hedge can be reinstated later. It is safe to make
only because provenance is retained per-fact in `chain.yaml` — splitting the tables by
evidence kind, or filtering the weakest kind out, stays a mechanical change over data
already collected. Nothing has to be re-derived.

The cost is that a reader cannot see the mix from the table. `verify.py` prints the
per-chain tally so the ratio stays visible to anyone maintaining the dataset, and so a
row quietly drifting toward doc-only evidence is noticeable before it is load-bearing.

### Provenance is chain-page-only (hard rule)

Where a fact came from — its `src` / `src_live` / `src_doc`, the `base_map` it was
synthesized from, and *which row declared it* when a chain inherits from a stack
ancestor (the `†` mark, the `via <origin>` pill) — appears **only on that chain's own
page**. Every aggregate surface (the Markdown tables, every axis grid and its per-entry
detail, the home page) shows the fact and its `status` mark and nothing about where it
came from.

The reason is comparison: two chains that agree on a fact must read as identical in a
grid regardless of how each is evidenced or which ancestor declared it, so that "hide
rows where every chain agrees" hides them. A cell whose only difference from its
neighbour is a `†` is a false difference. `tools/generate.py:cell`, `site.py:mark`
(`aggregate=True`), `site.py:provenance` (`on_chain` defaults false) and
`site.py:entry_meta` all enforce this.

## `tx_authorization:` — what can sign a transaction

An axis of its own, independent of `precompiles`. **A precompile that verifies a
signature scheme is not the same as that scheme being able to authorize a
transaction**, and the two come apart in both directions. Eleven rows carry
P256VERIFY, and on almost all of them a P-256 key still cannot move a single wei —
the precompile is a tool for *contracts*, not an authentication method for *senders*.

```yaml
tx_authorization:
  key_binding: derived        # derived | declared | account_code
  signers_per_tx: 1
  note: >-
  schemes:
    secp256k1:
      status: inherited
      authorizes: protocol
      precompile: "0x01"
      src: ...
```

### `authorizes:` — how far the scheme reaches

| value | meaning |
|---|---|
| `protocol` | the client itself validates a signature in this scheme to authorize a transaction. Mainnet's secp256k1. |
| `account_code` | only reachable through account-abstraction code: the protocol runs the account's own validator, which decides. zkSync's `customSignature`. |
| `never` | the chain can *verify* this scheme but it can never authorize a transaction. The normal state of P-256 on a chain with P256VERIFY. |

**The value is `never`, not `no`.** YAML 1.1 parses a bare `no` as the boolean `false`,
so `authorizes: no` silently loads as `False` and any consumer comparing against a
string sees neither. `tools/verify.py` rejects the boolean form by name.

### `precompile:` — the paired verifier, or `none`

The address of the precompile that verifies this same scheme, or `none`.

**`authorizes: protocol` together with `precompile: none` is the finding to look for.**
It means the chain accepts transaction signatures that its own contracts have no way to
check — an on-chain verifier, a multisig, or an account-recovery contract cannot
validate the very signatures the protocol just accepted. Record it, and say so in the
`note`.

The reverse pairing — `authorizes: never` with a real precompile address — is ordinary and
needs no comment beyond the address.

### `key_binding:` — how the address relates to the key

| value | meaning |
|---|---|
| `derived` | the address IS the hash of the public key; `ecrecover(sig) == from` is an identity. Mainnet. |
| `declared` | the sender is an explicit field, checked against a key registered on-chain. `ecrecover(sig) != from`. Kaia's `AccountKey`, Tron's permission system. |
| `account_code` | there is no protocol-level key at all; the account's code decides what a valid signature is. zkSync. |

`signers_per_tx` is normally 1. Kaia's fee-delegated types carry two independent
signers with two different digests, and each side may itself be a weighted multisig —
so the field counts *parties*, not signatures, and the `note` carries the rest.

### Config-switchable schemes

A scheme selected by node configuration rather than by consensus rules takes
`availability: optional` with an `activation_condition`. These deserve suspicion: if
two nodes disagree on the setting they disagree on who signed what, which is a
consensus split rather than a graceful error.

## Category boundaries (these get conflated constantly)

- **precompile** — native code at an address, no bytecode in state, no `EXTCODESIZE`.
- **system_contract** — real EVM bytecode at a fixed address (predeploy, genesis
  alloc, or client-installed). Has code, is `CALL`-able normally. Ethereum's
  beacon-roots contract and OP's `0x42..` predeploys are these, *not* precompiles.
- **system_transaction** — state changes driven by the protocol rather than a user
  transaction (EIP-4788 beacon-root write, OP deposits, Parlia system calls).
- **non_evm_transactions** — protocol transactions with **no EIP-2718 type byte at
  all**: Avalanche's UTXO atomic txs, Tron's 43 protobuf contract types. They cannot
  appear in `tx_types` because they have no type byte, and omitting them entirely
  would hide all cross-chain value movement.

Keeping these separate is the difference between a table you can act on and a list of
addresses.

## `role`

- `baseline` — Ethereum Mainnet only.
- `fork` — descends from a mainnet client by code. Deltas are literal diffs.
- `stack` — **not a chain**. A shared codebase several chains inherit from (OP Stack).
  Holds its descendants' shared deltas exactly once. No `chain_id`.
- `template` — **not a chain**. A codebase instantiated per deployment with
  per-deployment configuration (subnet-evm). Differs from `stack` in that its
  features are `optional` rather than inherited wholesale, so no descendant can be
  fully described by pointing at it. No `chain_id`.
- `independent` — reimplements EVM semantics without shared ancestry (Tron). Must set
  `equivalence: behavioural` so the matrix can flag the weaker claim: deltas are
  behavioural comparisons, not code diffs.

`stack` and `template` rows are not chains; this is derivable from `role`, so there is
no separate `is_chain` field.

## The base precompile map (`0x01`–`0x11` + `0x0100`)

Mainnet's precompile range is contiguous `0x01`–`0x11` (ECRECOVER through
`BLS12_MAP_FP2_TO_G2`) plus P256VERIFY at `0x0100`. The delta convention would have a
chain that carries all of them record nothing — and "nothing recorded" is
indistinguishable from "nobody checked." For a range this load-bearing that is not good
enough: whether a chain actually has EIP-2537 BLS (`0x0b`–`0x11`), KZG at `0x0a`, or
P256VERIFY is the single most common integration question.

Every chain therefore declares the range explicitly, condensed into one block:

```yaml
precompiles:
  base_map:
    status: inherited          # disposition of the present addresses: inherited | modified
    present: "0x01-0x11"       # which of 0x01-0x11 exist at the mainnet address with
                               # mainnet behaviour. A range, comma-separated ranges, or a
                               # list: "0x01-0x0a"  ·  "0x01-0x08, 0x0a"  ·  ["0x01","0x05"]
    p256verify: false          # 0x0100: true | false | pending
    src: "core/vm/contracts.go:PrecompiledContractsPrague"   # the map in THIS clone, or
                               # a prose pointer when the base set is in a dependency
    src_live: "..."            # optional
    note: "EIP-2537 BLS present via Prague; no P256VERIFY (pre-Osaka)."
```

The model expands this into per-address entries:

- an address in `present` → synthesized `inherited` (renders `=`)
- an address in `0x01`–`0x11` **not** in `present` → synthesized `removed` (renders `➖`,
  never a blank)
- `p256verify:` drives `0x0100` the same way

An **explicit** per-address entry always wins over the synthesized one — so a chain that
reprices `0x05` or caps `0x08` still lists that address with its own `note`, `src` and
`modified`/`tombstoned` status, and `present` just says the address exists at all. OP
Stack descendants inherit the stack row's `base_map` unless they declare their own.

`verify.py` cross-checks `present` against the precompile map extracted from the pinned
clone for every row that has an extractor; a chain with no `base_map` at all is a build
error. Chains whose base set comes from an unvendored dependency (coreth/subnet-evm on
`ava-labs/libevm`) carry a prose `src` and are checked by citation only.

## The transaction envelope (`0x00`–`0x04`)

The same problem for `tx_types`: mainnet's EIP-2718 envelope is `0x00` LegacyTx, `0x01`
AccessListTx (EIP-2930), `0x02` DynamicFeeTx (EIP-1559), `0x03` BlobTx (EIP-4844), `0x04`
SetCodeTx (EIP-7702). A chain that drops EIP-1559 or never shipped blob transactions —
common — would record nothing, leaving a blank that reads as a difference next to a
chain that did record it.

Every chain declares the envelope, condensed:

```yaml
tx_types:
  envelope:
    status: inherited
    present: "0x00-0x02, 0x04"   # which of 0x00-0x04 the network accepts in mainnet
                                 # shape. "" means none (Tron — no EIP-2718 envelope).
    src: "derived from the eips map (2930 / 1559 / 4844 / 7702); see those entries"
    note: "no blob transactions (EIP-4844)."
```

Expansion, precedence, and the `verify.py` cross-check are the same as `base_map`
(0x00–0x04 instead of 0x01–0x11, no `p256verify` tail). `present` states what the
network *accepts*, not merely what type constant the client defines — a byte present in
source but absent from `present` is the "defined, but rejected" case (`0x03` on most OP
Stack chains) and is not an error. OP Stack descendants inherit the stack row's
`envelope` unless it would differ.

## Non-enumerable precompiles

Base (from its Beryl upgrade) installs a `PrecompileLookup` that resolves precompiles
**by predicate over the address** rather than from a fixed map. Roughly 2^72 addresses
are precompiles. No address-keyed table can represent this.

Such a chain records a `precompiles.dynamic_range` entry instead of address keys:

```yaml
precompiles:
  dynamic_range:
    name: B-20 token precompiles
    status: added
    pattern: "byte[0] == 0xb2 AND bytes[1..10] == 0 AND byte[10] in {0x00, 0x01}"
    src: ...
```

The generator emits these in a dedicated section, and `verify.py` skips them — there
is nothing to enumerate. Any consumer building a fixed precompile set must treat a
`dynamic_range` as a membership test, not a list.

## Lineage that is not a tree

`lineage.upstream` assumes each chain has one parent. opBNB does not: its code is
op-geth, but two precompiles and two fork names come from BSC. Such rows add
`lineage.second_heritage: <slug>` — a documented escape hatch, so the fact is recorded
rather than dropped to fit the model.

Related caveat: inheritance resolves a descendant against the ancestor's **current**
file, but a descendant pinned to an older client inherits the ancestor's **past**.
opBNB's op-geth v0.5.10 stops at Fjord while the op-stack row pins a Jovian/Karst
client, so opBNB has none of OP Stack's later changes. Record this in
`lineage.sync_point`; the generated tables do not yet model it.

## Evidence that lives in another row

- `client.shared_with: <slug>` — this row has no clone; its evidence is another row's
  (OP Mainnet shares op-stack's op-geth). `clone.sh` and `verify.py` follow it.
- `client.companion_repos[]` — additional pinned repos supplying facts the main client
  does not contain (OP Stack's predeploy definitions and per-chain fork schedules).

## Stack nodes and inheritance

A chain whose `lineage.upstream` names a `stack` row states **only its own deltas**.
The OP Stack `0x7e` deposit type and `0x42..` predeploys live in `chains/op-stack/`;
World Chain's file contains only what World Chain itself adds.

The generator resolves the chain (`ethereum → op-stack → worldchain`) so aggregate
tables show every chain's complete effective set. Inherited rows are marked with
their origin, so a reader can tell "World Chain has `0x7e`" from "World Chain
*invented* `0x7e`" — a distinction the raw address list destroys.

Inheritance is override-by-key: a descendant re-declaring an address or type byte its
ancestor already declared **replaces** it and must carry a `note` explaining why.

## The transaction lifecycle (`tx_lifecycle:`)

Mainnet checks nonce, balance and gas price **before** a transaction can be ordered, so
"ordered but invalid" is not a state it can reach. Every chain that separates ordering
from execution has to invent an answer, and they do not agree. `tx_lifecycle:` holds
those answers, one key per question, each with its own `verdict:` and evidence:

```yaml
tx_lifecycle:
  ordered_then_invalid:
    verdict: erased          # erased | charged | block_rejected | escalated
                             # | billed | unreachable
    severity: high
    src: ...
    note: >-
      ...
  nonce_on_failure:
    verdict: burned          # preserved | burned | split
  duplicate_inclusion:
    verdict: deduplicated    # benign | deduplicated | rejected
```

`verdict:` is the closed vocabulary the axis grid renders; `note:` (or `answer:`) is the
prose the chain page renders. Other keys in the same shape: `insufficient_balance`,
`ordering`, `parallel_execution`, `preconfirmation`.

**The `ethereum` row states the baseline once**, exactly as `opcodes.baseline_set` does:
`ordered_then_invalid: unreachable`, `nonce_on_failure: preserved`. Every other row is a
delta against that. An **absent** key means the question is not established for that
chain — it does **not** mean the chain behaves like mainnet, and the grid renders it
`—` rather than `=`.

These facts were previously scattered: `nonce on failure` and `duplicate inclusion` sat
in `fee_model.extra_components` (they are not fee components), and two rows had grown
ad-hoc `consensus.*` keys for the same question under **different names**
(`ordered_then_invalid` on one, `ordered_but_invalid` on the other). That divergence is
what the axis exists to prevent.

## The p2p axis (`p2p:`)

"How big can a transaction be?" has no single answer, and the ways it is wrong are
instructive. Mainnet's famous 128 KiB is **not a rule** — it is one client's DoS policy
that the others copied so the mempool would not fragment. A 300 KiB transaction is
perfectly valid in a block; it simply cannot reach one through the public mempool. Until
Fusaka there was no consensus size limit at all.

So every size on this axis carries a **`tier:`**, and the tier is part of the fact:

| tier | who rejects | consequence of exceeding |
|---|---|---|
| `consensus` | every validating node | the **block** is invalid |
| `policy` | the local mempool | the transaction does not propagate; a block containing it is still valid |
| `transport` | the wire | the peer connection errors; the message never forms |

Without `tier:` the axis would publish "131072" next to "8388608" as though they were the
same kind of claim, and the gap between them — valid but unroutable, where private
orderflow lives — would vanish from the dataset.

```yaml
p2p:
  max_tx_bytes:
    verdict: 131072                 # raw bytes; the grid formats them
    tier: policy
    scope: non_blob                 # optional: which txs the number governs
    src: "core/txpool/legacypool/legacypool.go:txMaxSize"
    note: >-
      ...
  max_block_bytes: {verdict: 8388608, tier: consensus, src: "..."}
  fragmentation:
    verdict: none                   # none | muxer-only | app-chunking | erasure-coded
  transports:
    verdict: "devp2p + libp2p"      # the scalar the grid renders
    stack:                          # the detail the chain page renders
      - {layer: execution, protocol: devp2p, purpose: tx + block gossip}
      - {layer: consensus, protocol: libp2p, purpose: block + blob gossip}
```

Keys: `max_tx_bytes`, `max_blob_tx_bytes`, `max_block_bytes`, `max_message_bytes`,
`fragmentation`, `transports`. `verdict:` is what the grid renders; `note:` is the prose
the chain page renders. Sizes are **raw byte integers**, never "128KB" — a string cannot
be compared, and the two clients that write it differently would read as divergent when
they agree.

### `fragmentation:` is an enum because a boolean loses the answer

Four transports in this dataset answer "can a message exceed one packet" differently, and
three of the four would collapse to "no" under a boolean:

- `none` — RLPx. Multi-frame chunking was cut from the spec; the frame cap is hard.
- `muxer-only` — libp2p. The stream muxer frames the bytes, but the application message
  is atomic, so the payload cap is equally hard for a different reason.
- `app-chunking` — CometBFT, which really does split messages into fixed-size packets.
- `erasure-coded` — Monad's RaptorCast, which chunks to an MTU *and* Raptor10-encodes with
  a redundancy factor, so a receiver reconstructs from a subset of chunks. Not a bigger
  pipe: a different delivery guarantee.

### Same number, different cause

`max_tx_bytes` is the axis's trap. Mainnet's 128 KiB is propagation DoS policy. Arbitrum's
default 95,000 is **L1 data-availability economics** — 95% of the batch-poster limit, with
5 KB left for headers — and is *smaller* than mainnet's. Polygon zkEVM-class chains derive
theirs from prover constraints. The number is comparable across rows; the reason is not, so
`note:` states the reason and is not optional on this key.

### Why consensus limits are restated here rather than only in `eips:`

`max_block_bytes` (EIP-7934) and the per-transaction gas cap (EIP-7825) are consensus facts
with a home in `eips:`. They are **restated** here, tagged `tier: consensus`, because a
reader asking "how big can this get" should get one table rather than three. The duplication
is deliberate; `eips:` remains the authority on activation, and this axis on magnitude.

EIP-7825 also implies a byte cap nobody writes down. With a per-tx limit of 16,777,216 gas
and EIP-7623's floor of 10 gas per token (4 tokens per non-zero byte), the largest
transaction mainnet can contain is roughly **1.6 MB of zero bytes, or ~419 KB of non-zero
bytes** — over twelve times what the mempool will carry. EIP-8037 moves intrinsic gas inside
the cap at Amsterdam, so the figure is fork-dependent.

### Not tracked here

Post-quantum readiness. Transport handshake KEX and peer-identity signatures are p2p
questions, but consensus and transaction signatures are not, and splitting one PQC story
across two axes would serve neither. It belongs to the cryptography axis; this note exists
so the next person does not add `pqc_*` keys here by default.

## The proofs axis (`proofs:`)

Two questions that look unrelated and are the same question: **what can be proven about
this chain, and to whom.** One half asks how the chain's own state transition is proven
to whoever settles it; the other asks whether the chain can prove a single account or
storage slot to a caller. They share an axis because one design decision routinely lands
in both halves — a chain that commits state under a non-Keccak hash has both an exotic
prover and an `eth_getProof` nobody can verify, and recording those in two places would
split one fact in two.

`proofs:` is keyed by question, each key carrying its own `verdict:` and evidence, in
the same shape as `tx_lifecycle:` and `p2p:`:

```yaml
proofs:
  state_transition:
    verdict: fault          # validity | fault | consensus | none
    severity: high          # optional, as elsewhere
    src: ...
    note: >-
      ...
  proving_live:
    verdict: permissioned   # live | permissioned | staged | halted | n/a
  settlement:
    verdict: ethereum       # self | own-l1 | ethereum | celestia | bitcoin | none
  prover_constraints:
    verdict: binding        # binding | lifted | none
  state_proof:
    verdict: served         # served | partial | absent
  proof_root:
    verdict: canonical      # canonical | deferred | foreign-hash | no-commitment
```

### Half one — proving the state transition

`state_transition:` names what actually backs the transition. `validity` is a succinct
proof verified by a settlement contract; `fault` is an assertion anyone may challenge
within a window; `consensus` is a chain whose own validator set is the only attestation
there is, which is the honest answer for every L1 and is **not** a lesser one; `none` is
a chain that publishes data and adjudicates nothing.

`proving_live:` is the key that stops a roadmap from reading as a fact. A proof system
that exists in a repository, on a testnet, or behind a permissioned prover set is not
the same claim as one adjudicating mainnet today, and the distinction is invisible in
every other field. `permissioned` means proofs are produced and accepted but only a
whitelisted party may produce them; `staged` means live on a testnet or shadow-proving
mainnet without enforcement; `halted` means a system that once ran and no longer does.
`n/a` belongs to `consensus` and `none` rows, where nothing is being proven.

`settlement:` names the layer, not the object it accepts — which proof or root a
settlement contract takes is `note:` material. `self` is a chain that settles itself;
`own-l1` is a chain settled by a separate chain of the same protocol rather than by
Ethereum, which is how an Autonomys domain relates to the Subspace consensus chain.

`prover_constraints:` is where this axis earns its place in a dataset about EVM
semantics. A prover is a circuit, a circuit has bounds, and those bounds leak upward
into rules the EVM is supposed to guarantee. The result is a chain where a precompile
is present, correct in `eth_call`, and cannot be mined. `binding` means at least one
such constraint is live; `lifted` means the row carried one and no longer does — which
is why Scroll's entry has a date on it, and Linea's does not; `none` means the question
was asked and the answer is that no prover bound reaches EVM semantics.

`lifted` exists so that a fixed constraint stays in the dataset. Deleting the key when
a chain lifts its cap would make "never had one" and "had one until last December"
identical, and contracts deployed under the old rule are still deployed.

### Half two — proving state to a caller

`state_proof:` is EIP-1186 `eth_getProof`, as actually served: `served`, `absent` (the
method is not implemented), or `partial` — the method answers, and what comes back is
not a conforming EIP-1186 account. `partial` is the one worth having. Blast returns
`flags`, `fixed`, `shares` and `remainder` in place of `balance`, so `result.balance` is
`undefined` rather than an error, and every verifier that decodes a four-item account
fails silently against a seven-item one.

`proof_root:` asks the question underneath: does what comes back verify against the
state root in the block header? `canonical` is mainnet's answer. The three ways to fail
it are all in this dataset and are **not** the same failure:

| verdict | what is wrong | rows |
|---|---|---|
| `deferred` | the root is real and belongs to a **different block** | conflux (epoch N−5) |
| `foreign-hash` | the root commits under another hash or another trie | polygon-zkevm (Poseidon SMT), cosmos-evm (CometBFT app hash) |
| `no-commitment` | the header commits to no state at all | iota-evm, hyperliquid (zero root, every block) |

A boolean here would render all four as "no" and lose the only thing a bridge author
needs to know, which is *what to do instead*. `no-commitment` has no workaround;
`foreign-hash` has one if you can verify that hash; `deferred` needs only patience and
an offset.

**The `ethereum` row states the baseline**, as it does for `tx_lifecycle:` and
`opcodes.baseline_set`: `consensus` / `n/a` / `self` / `none` / `served` / `canonical`.
Every other row is a delta against that. An **absent** key means the question is not
established for that row — it does **not** mean the chain answers as mainnet does, and
the grid renders `—` rather than `=`.

Inheritance is the same override-by-key walk the address sections use: a row whose
`lineage.upstream` names a stack node inherits that node's answers key by key and
overrides the ones it states itself. Blast inherits all of `op-stack`'s half-one answers
and overrides `state_proof:` alone.

## Opcodes

`opcodes:` holds `added` / `removed` / `modified` / `pending` / `tombstoned` lists of
per-instruction deltas against **mainnet's Osaka jump table**. Every entry is keyed
`op:` (a `"0xNN"` string) — the grid, the chain-page anchors and the silent-divergence
index all read that key and nothing else; `opcode:` is not accepted and `verify.py`
flags it. Fields: `name` (mnemonic), `note` (**required** for `modified`), optional
`severity: high` (renders a `silent` pill), an informational `fork:` (which of the
chain's own forks introduced it), and one of `src:` / `src_live:` / `src_doc:`.
`pending` = merged upstream but not live on the network; `tombstoned` = the byte is
defined but wired to INVALID (calling it always fails).

Mainnet's own instruction set is enumerated once, on the `ethereum` row, so the grid
can render "this chain has ADD, unremarkably" instead of a blank:

```yaml
opcodes:
  baseline_set:
    src: core/vm/jump_table.go:newOsakaInstructionSet
    opcodes:
      "0x01": ADD                          # plain string: a frontier-era opcode,
                                            # present at every baseline fork
      "0x5f": {name: PUSH0, fork: shanghai} # {name, fork}: fork = the MAINNET fork
      "0x1e": {name: CLZ, fork: osaka}      # that introduced it
```

The grid gates a `{name, fork}` opcode **out** of any chain whose `baseline_fork`
predates `fork` (via `model.fork_rank`) — the cell renders **blank**, not `–`, since
the opcode simply postdates the chain. A chain that carries the opcode anyway (a
back-port) records an explicit `opcodes.added` entry, which always wins. An explicit
`opcodes.removed` renders `–` ("removed, or never adopted").

### PREVRANDAO (`0x44`) — the derivation, not the value

`opcodes.prevrandao` is **required on every row** and records *how* `0x44` gets its
value. It is a keyed block, not a list, because there is exactly one answer per chain:

```yaml
opcodes:
  prevrandao:
    source: difficulty        # the mechanism class (enumerated, below)
    value: "the constant 1"   # what a contract actually reads off the stack
    chooser: >-               # who fixes the value, and at what point
      nobody — the header field it reads is a constant written by the block builder
    known_at: always          # when it first becomes knowable (enumerated, below)
    note: >-                  # the mechanism, in source terms
      ...
    src: core/evm.go:NewEVMBlockContext
```

`source:` is one of `beacon-randao` (this chain's own beacon chain RANDAO mix),
`l1-randao` (an L1 block's RANDAO, read across the bridge), `consensus-randao` (a
randomness the chain's own consensus derives — a BLS reveal, a DAG fold, a running
hash), `difficulty` (the byte is still, or again, bound to a difficulty field),
`timestamp`, `block-number`, `constant`, `nil` (reading it faults), or `unrecorded`.

`known_at:` is one of `execution` (nobody can know it before the block is executed),
`proposal` (the proposer can compute its own future values), `l1-epoch` (public one L1
block ahead, and constant for every L2 block in that epoch), or `always` (a constant, or
a pure function of something already public).

**Why the value alone is not enough.** Recording only what `0x44` pushes puts BSC's
Parlia difficulty, Arbitrum's ArbOS `1` and Avalanche's dummy-engine `1` in the same
cell, when they arrive by three unrelated edits; and it puts mainnet, Gnosis, Base and
Monad in the same cell, when one is a beacon mix, one is another chain's beacon mix
arriving 12 seconds stale, and one is a signature over a round number that its proposer
could have computed a week earlier. `known_at:` is the column a contract author is
actually asking about.

Rendering: the block gets an anchor `#prevrandao` on the chain page, under the Opcodes
heading, and the opcodes axis page carries one row per chain linking at that anchor —
the same shape as a per-opcode anchor. Per the provenance hard rule the axis table
carries no citations; those live on the chain page.

## Affiliated contributions

`affiliated_contributions:` credits merged corrections that came from contributors who
disclosed an affiliation with **this** chain — its team, foundation, contractors,
grantees or investors. It is a list, one entry per issue:

```yaml
affiliated_contributions:
  - issue: 12            # required: the public issue the correction came from
    date: 2026-09-20     # when the change merged
    note: >-             # optional: what it corrected
      0x0100 gas cost
```

When the list is non-empty the chain page's Evidence section carries one line naming the
chain and linking each issue. Nothing else reads it: no grid, axis page or index shows
it. Contributions from unaffiliated filers or from competing chains are **not** recorded
here — the re-derivation against public evidence is the safeguard for those, and the
credit exists so a reader knows when a row's own team shaped it. `verify.py` requires an
integer `issue:` on every entry. See [CONTRIBUTING.md](CONTRIBUTING.md#credit-on-the-chain-page).

The operator's own affiliations are not per row. They live in
[`operators.yaml`](operators.yaml), which names rows by slug; a *current* affiliation
puts one line on each named row's chain page, and `verify.py` rejects a slug that does
not exist.

## Top-level keys

```yaml
schema_version: 2
chain:        # name, slug, chain_id, role, live, evidence
lineage:      # upstream, ancestry, fork_of, sync_point
client:       # reference client: repo, version tag, pinned commit, language
              # omitted entirely when chain.evidence is `documented`
live_probe:   # endpoint, chain_id, observed_at_block — pins src_live claims
consensus:    # engine, finality, block time
baseline_fork: osaka      # the mainnet fork this chain claims equivalence to
forks:        # src, note, timeline[] with activation_time / mainnet_equivalent
eips:         # EIP number -> {status, note, src}. Mainnet-relative. THE core table.
non_eip_specs: # chain's own spec series, keyed by adoption:
tx_types:     # envelope (the 0x00-0x04 EIP-2718 range, condensed); then
              # type byte -> {name, status, spec, src} for divergences and additions
tx_authorization:  # what can SIGN a tx — independent of precompiles
non_evm_transactions:  # protocol txs with no type byte
precompiles:  # base_map (the 0x01-0x11 + 0x0100 range, condensed); then
              # address -> {name, status, availability, spec, src} for divergences
              # and additions; optional dynamic_range for predicate-resolved sets
system_contracts:
system_transactions:
opcodes:      # {added/removed/modified/pending/tombstoned: []}, entries keyed op:;
              # plus baseline_set on the ethereum row, and prevrandao (required on
              # every row: how 0x44 gets its value). See "Opcodes" above.
tx_lifecycle: # ordering/execution answers, keyed by question, each with a verdict
p2p:          # wire-level limits and transports, keyed by question; every size
              # carries a tier: consensus | policy | transport
proofs:       # what can be proven about this chain and to whom, keyed by question:
              # state_transition / proving_live / settlement / prover_constraints
              # (half one) and state_proof / proof_root (half two)
fee_model:    # metering, fee_market, extra_components
header_fields: # {added: [], removed: [], modified: []} vs mainnet
gotchas:      # free text: what surprises integrators
affiliated_contributions: # merged corrections from people affiliated with THIS chain;
                          # chain page only. See "Affiliated contributions" above.
```
