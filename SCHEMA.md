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

Every non-obvious claim carries a `src:` pointing at a path and symbol inside the
pinned clone, e.g. `core/vm/contracts.go:PrecompiledContractsOsaka`. If a fact came
from documentation rather than source, it is `src_doc:` with a URL and is treated as
**unverified** until confirmed in code. Docs lie; shipped code does not.

`tools/verify.py` re-extracts what it can from the pinned clones and diffs against
these files, so the evidence rule is enforced mechanically rather than by good
intentions.

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
chain:        # name, slug, chain_id, role, live
lineage:      # upstream, ancestry, fork_of, sync_point
client:       # reference client: repo, version tag, pinned commit, language
consensus:    # engine, finality, block time
baseline_fork: osaka      # the mainnet fork this chain claims equivalence to
forks:        # src, note, timeline[] with activation_time / mainnet_equivalent
eips:         # EIP number -> {status, note, src}. Mainnet-relative. THE core table.
non_eip_specs: # chain's own spec series, keyed by adoption:
tx_types:     # type byte -> {name, status, spec, src}
non_evm_transactions:  # protocol txs with no type byte
precompiles:  # address -> {name, status, availability, spec, src}
system_contracts:
system_transactions:
opcodes:      # {added: [], removed: [], modified: []}
fee_model:    # metering, fee_market, extra_components
header_fields: # {added: [], removed: [], modified: []} vs mainnet
gotchas:      # free text: what surprises integrators
```
