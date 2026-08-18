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
| `no` | the chain can *verify* this scheme but it can never authorize a transaction. The normal state of P-256 on a chain with P256VERIFY. |

### `precompile:` — the paired verifier, or `none`

The address of the precompile that verifies this same scheme, or `none`.

**`authorizes: protocol` together with `precompile: none` is the finding to look for.**
It means the chain accepts transaction signatures that its own contracts have no way to
check — an on-chain verifier, a multisig, or an account-recovery contract cannot
validate the very signatures the protocol just accepted. Record it, and say so in the
`note`.

The reverse pairing — `authorizes: no` with a real precompile address — is ordinary and
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
tx_types:     # type byte -> {name, status, spec, src}
tx_authorization:  # what can SIGN a tx — independent of precompiles
non_evm_transactions:  # protocol txs with no type byte
precompiles:  # address -> {name, status, availability, spec, src}
system_contracts:
system_transactions:
opcodes:      # {added: [], removed: [], modified: []}
fee_model:    # metering, fee_market, extra_components
header_fields: # {added: [], removed: [], modified: []} vs mainnet
gotchas:      # free text: what surprises integrators
```
