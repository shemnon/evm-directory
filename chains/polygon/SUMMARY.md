# Polygon PoS — zero custom precompiles, eleven repriced ones

**Chain ID 137 · role: `fork` · upstream: go-ethereum · baseline: Prague**

Reference: [0xPolygon/bor `v2.10.0`](https://github.com/0xPolygon/bor) @ `82d3b610`.
Heimdall (consensus/checkpointing) is a separate component, not cloned.

## PIP-88: a systematic gas surcharge

Polygon adds **no precompile addresses**. It reprices eleven of mainnet's, at the same
addresses, with identical semantics. From `params/protocol_params.go:76-204`, with the
multipliers taken from the source's own comments:

| Precompile | Multiplier |
|---|---|
| BN256 add | ×3.6 (540 vs 150) |
| BN256 scalar mul | ×2.1 (12600 vs 6000) |
| BN256 pairing | ×1.5 base and per-point |
| BLS12-381 G1 add | ×2.8 |
| BLS12-381 G1 mul | ×6.1 (k=1) |
| BLS12-381 G2 add | ×2.7 |
| BLS12-381 G2 mul | ×6.4 (k=1) |
| BLAKE2F | **GFROUND 22 vs 1 — ×22 per round** |
| COLD_SLOAD | ×2.6 (5460 vs 2100) |
| COLD_SSTORE | ×1.4 |

Calls succeed, return identical results, and cost up to 22× more. Gas benchmarks, DoS
models and proof-cost estimates calibrated on mainnet are simply wrong here, and
nothing reverts to signal it.

This is the third distinct flavour of same-address divergence in the dataset: OP Stack
**caps inputs** (changing whether a call succeeds), Avalanche **omits features**
(changing what exists), Polygon **reprices** (changing only cost). The third is the
hardest to notice.

## `0x0a` is absent

The Chicago precompile set has no KZG point evaluation — the address is simply not in
the map. Contrast Avalanche, which *keeps* Cancun's blob machinery and pins blob gas
to zero. Two chains, both without blobs, two different absences.

## Two system-contract collisions with BSC

| Address | Polygon | BNB Smart Chain |
|---|---|---|
| `0x…1000` | **ValidatorContract** | **ValidatorContract** |
| `0x…1001` | StateReceiverContract | SlashContract |

`0x…1000` is called `ValidatorContract` on **both chains**, with different code and
different ABIs. That is the most confusing possible collision: an address-and-name
match that is not a behaviour match. Anything resolving contracts by name-plus-address
across chains gets it wrong in the direction of appearing correct.

## `0x7f` — the last type byte

`StateSyncTxType = 0x7f` (`core/types/transaction.go:54`) bridges L1 state into
Polygon. `0x7f` is the **final legal EIP-2718 type byte** — `0x80`+ collides with RLP
list prefixes — directly adjacent to OP Stack's `0x7e`.

Across the dataset the top of the type space is being consumed downward — Arbitrum
`0x78`, Base `0x79`, OP Stack `0x7e`, Polygon `0x7f` — while mainnet grows upward from
`0x04`. Two allocation frontiers moving toward each other, with no registry between them.

## Fork mapping: a fourth mechanism

Polygon gates Ethereum forks on **block numbers**: `ShanghaiBlock` 50523000,
`CancunBlock` 54876000, `PragueBlock` 73440256. Its own Bor forks are block-numbered
too — Jaipur, Delhi, Indore, Ahmedabad, Bhilai, Rio, Madhugiri(+Pro), Dandeli,
Lisovo(+Pro), Giugliano, Chicago, Valencia, Austin.

That makes four mechanisms across nine chains: OP Stack enforces timestamp equality,
Avalanche assigns timestamps, Arbitrum gates on ArbOS version, Polygon uses block
numbers. Any tool that assumes "fork activation is a timestamp" fails on two of them.

No `OsakaBlock` is set for mainnet — yet the **Chicago** set enables EIP-7823/7883
MODEXP and EIP-7951 P256VERIFY. Osaka-era precompile behaviour without the Osaka fork,
the same out-of-order adoption as Avalanche's Granite.

## Re-verify

```
git clone --depth 1 --branch v2.10.0 https://github.com/0xPolygon/bor
sed -n '274,295p' core/vm/contracts.go        # Chicago set; note no 0x0a
sed -n '74,90p;190,206p' params/protocol_params.go   # PIP-88 multipliers
sed -n '405,440p' params/config.go            # mainnet blocks + system contracts
sed -n '49,55p' core/types/transaction.go     # StateSyncTx 0x7f
```
