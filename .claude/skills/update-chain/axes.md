# Per-axis update checklist

Each of the site's ten axes (`tools/site.py:AXES`) reads specific `chain.yaml` keys.
Walk every axis for the row, including axes the row currently leaves empty. A new
release can add a fact where there was none.

For every entry you touch: keep its `status` vocabulary (SCHEMA.md), re-point `src:` at
the symbol **in the new clone** (prefer `file:Symbol` to `file:line`, because line
numbers drift on every bump), and never drop a citation because it got harder to find.
If you cannot re-establish a fact, change it to `status: unrecorded` with a `note:`
saying why. Do not leave the old claim standing.

**Routine** = a client bump with no mainnet fork. For each axis, check whether the
old→new diff touched the files its entries cite. If it did, re-read those symbols; if it
did not, the entry stands.
**Fork** = a mainnet network upgrade activated since the pin. Re-derive the whole axis
from the code path the new fork selects (its precompile map, jump table, signer, fee
function), not only the files that are already cited.

| Axis (`axes/<key>.html`) | `chain.yaml` keys | Routine | Fork: also |
|---|---|---|---|
| **precompiles** | `precompiles.base_map`, per-address entries, `dynamic_range`; `eips` 2537 / 7951 / 7823 / 7883 | Check that the `base_map.src` symbol still names the **active** map. Look for new or removed custom addresses. | Point `base_map.src` at the new fork's map (e.g. `PrecompiledContractsPasteur`). Recompute `present` and `p256verify`. When `tombstoned_at:` has passed, set the status to `tombstoned`. Re-check gas `divergence:` on every `modified` entry. |
| **tx-types** | `tx_types.envelope`, per-byte entries, `non_evm_transactions` | New type constants, and whether the txpool/signer accepts them | Recompute `envelope.present` from what the network **accepts**, not what the client defines. For a new type, probe it live if you can. |
| **opcodes** | `opcodes.added/removed/modified/pending/tombstoned` (keyed `op:`); `baseline_set` on `ethereum` only | Diff the jump-table file | Take the fork's instruction-set constructor and diff it against mainnet's Osaka table. Move `pending` entries that went live into `added`/`modified`. On `ethereum`, extend `baseline_set` with `{name, fork}` for the new opcodes. |
| **cryptography** | `tx_authorization` (`key_binding`, `signers_per_tx`, `schemes.*`) | Diff the signer / `transaction_signing` code | A new tx type or AA feature can add an `authorizes: protocol` scheme. Watch for `precompile: none` paired with `protocol`. Use `authorizes: never`, never `no`. |
| **system-contracts** | `system_contracts`, `system_transactions` | Predeploy address lists; genesis allocs | Fork-gated installs (`ActiveSystemContracts`-style branches, BSC's per-fork bytecode dirs, OP predeploy upgrades). Run `livecheck.py --deep` for code-hash changes. |
| **eips** | `eips`, `non_eip_specs`, `baseline_fork`, `forks.timeline` | New fork fields in `forks.src`; the release notes' EIP list | Flip `pending` → active and add `activation_time`. Set `mainnet_equivalent`. If the fork brings the row up to a newer mainnet fork, raise `baseline_fork` and re-examine every `removed` EIP. Add the fork's EIPs/BEPs/RIPs. |
| **fees-envelope** | `fee_model` (metering, fee_market, extra_components), `header_fields` | Base-fee / L1-fee functions; the header struct | New header fields, and repurposed ones (the `blobGasUsed` pattern). Changed fee parameters, where current **live** pricing is the reference. |
| **lineage** | `lineage.sync_point`, `fork_of`, `second_heritage`; `client.*` | **Always** rewrite `sync_point`: it names upstream versions (e.g. "tracks go-ethereum v1.17.5 through Osaka") and goes stale on every bump. | Name the new upstream sync; say so if the fork diverges from its ancestor. |
| **ordering** | `tx_lifecycle.*` (`verdict:` + `note:`) | Mempool / ordering / execution changes in the diff | Re-check every verdict. Forks often change inclusion and failure handling. |
| **p2p** | `p2p.max_tx_bytes`, `max_blob_tx_bytes`, `max_block_bytes`, `max_message_bytes`, `fragmentation`, `transports` | The txpool size constant; the transport message caps | EIP-7934-style consensus caps and blob limits. Every size stays a raw integer with a `tier:`, and `max_tx_bytes` keeps its reason in `note:`. |

## Not an axis, still in scope

| Key | Update when |
|---|---|
| `client` (+ `companion_repos`) | Always: the new `version` and the full 40-hex `commit`, peeled from the tag. |
| `live_probe.observed_at_block` | On a fork, re-pin it to a block **after** activation and replay every `src_live:` on the row at the new height. Each `src_live:` keeps its own `@ <block>`. |
| `consensus` (`block_time`, `block_time_history`) | Forks often change the block time (BSC halves it every few forks). |
| `gotchas` | Remove any that the fork fixed, and add any it created. |
| `recorded_at` / `stale_after` | Only if the row already carries them. Set them to now and to the next pending activation. |
| `chains/<slug>/SUMMARY.md` | Always update the `Reference:` line. Update fork tables, "not yet live" prose, and anything that quotes a now-stale symbol. |
| `findings.yaml` | If a finding's text states a fact this update changed, correct the finding. |

## verify.py covers some of this, not all

`tools/verify.py <slug>` catches: a pin that does not match the clone, a `src:` symbol or
line that no longer resolves, `base_map`/`envelope` `present:` against the extractor
(on rows that have one, see `EXTRACT` in `tools/verify.py`), and precompiles or tx types
that are **UNLISTED** in the yaml.

It does **not** catch a symbol that still exists but now means something else, a new
fork that selects a different map than the one cited, `sync_point` prose, SUMMARY.md,
or any `tx_lifecycle` / `p2p` / `fee_model` semantics. That part is your job.
