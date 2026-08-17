# `chain.yaml` schema (v1)

One file per chain. **Ethereum Mainnet is the Schelling point**: every other chain's
entries are stated as a *delta against mainnet*, never re-described from scratch.

## Delta vocabulary

Every item in `precompiles`, `tx_types`, `opcodes`, `system_contracts`, and `eips`
carries a `status` drawn from one fixed set:

| status | meaning |
|---|---|
| `inherited` | identical to mainnet at the chain's declared `baseline_fork`. Usually omitted — implied by the baseline. |
| `added` | exists here, does not exist on mainnet |
| `removed` | exists on mainnet at the baseline fork, deliberately absent here |
| `modified` | same name/address/number as mainnet, different semantics, gas, or encoding. **Must carry a `note`.** |
| `pending` | announced/merged upstream but not yet live on this chain |

`removed` and `modified` are the high-value rows — they are where integrations break.
A chain that is honestly EVM-equivalent should produce a nearly empty file, and that
emptiness is itself the finding.

## Evidence rule

Every non-obvious claim carries a `src:` pointing at a path and symbol inside the
pinned clone, e.g. `core/vm/contracts.go:PrecompiledContractsOsaka`. If a fact came
from documentation rather than source, it is `src_doc:` with a URL and is treated as
**unverified** until confirmed in code. Docs lie; shipped code does not.

## Category boundaries (these get conflated constantly)

- **precompile** — native code at an address, no bytecode in state, no `EXTCODESIZE`.
- **system_contract** — real EVM bytecode deployed at a fixed address (predeploy,
  genesis alloc, or one-off). Has code, is `CALL`-able normally. Ethereum's
  beacon-roots contract and OP's `0x42..` predeploys are these, *not* precompiles.
- **system_transaction** — state changes driven by the protocol, not by a user tx
  (EIP-4788 beacon-root write, OP deposits, Avalanche atomic imports).

Keeping these separate is the difference between a table you can act on and a list
of addresses.

## Top-level keys

```yaml
schema_version: 1
chain:        # name, slug, chain_id, role: baseline|fork|independent, live (bool)
lineage:      # upstream ancestry, each hop annotated with sync point
client:       # reference client: repo, version tag, pinned commit, language
consensus:    # engine, finality, block time — context for the EVM deltas
baseline_fork: osaka   # the mainnet fork this chain claims EVM equivalence to
forks:        # chain's own named upgrades, mapped to mainnet fork equivalence
eips:         # EIP number -> {status, note, src}. Mainnet-relative. THE core table.
non_eip_specs: # ACPs / BEPs / TIPs / RIPs — parallel namespace, never mixed with EIPs
tx_types:     # type byte -> {name, status, spec, src}
precompiles:  # address -> {name, status, spec, src}
system_contracts:
opcodes:      # {added: [], removed: [], modified: []}
fee_model:    # gas vs alternative metering, 1559 variant, extra fee components
header_fields: # {added: [], removed: [], modified: []} vs mainnet block header
gotchas:      # free-text list: things that surprise integrators
```

## `role`

- `baseline` — Ethereum Mainnet only.
- `fork` — descends from a mainnet client by code. Deltas are literal diffs.
- `independent` — reimplements EVM semantics without shared ancestry (Tron).
  Here `status` is still mainnet-relative, but `eips` describes *behavioural*
  equivalence, not adopted specs. Such chains must set
  `equivalence: behavioural` so the matrix can flag the weaker claim.
- `stack` — **not a chain**. A shared codebase that several chains inherit from
  (OP Stack). Carries `is_chain: false` and no `chain_id`. Holds the deltas its
  descendants share, exactly once.

## Stack nodes and inheritance

A chain whose `lineage.upstream` names a `stack` row states **only its own deltas**.
The OP Stack `0x7e` deposit type and `0x42..` predeploys live in `chains/op-stack/`;
World Chain's file contains only what World Chain itself adds. This keeps shared
facts from being copy-pasted per chain and drifting.

The generator resolves the chain (`ethereum → op-stack → worldchain`) so aggregate
tables still show every chain's complete effective set. Rows sourced from an ancestor
are marked with their origin, so a reader can tell "World Chain has `0x7e`" from
"World Chain *invented* `0x7e`" — a distinction the raw address list destroys.

Inheritance is override-by-key: a descendant re-declaring an address or type byte
its ancestor already declared **replaces** it and must carry a `note` explaining the
divergence.
