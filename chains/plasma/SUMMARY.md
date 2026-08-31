# Plasma — what this row teaches

Pinned: `paradigmxyz/reth` **v1.11.3** (`d6324d63`) — upstream, unmodified — with
`PlasmaLaboratories/node-templates` (`09df1007`) as a companion for the mainnet
genesis and the pinned image digests. Live probe: `https://rpc.plasma.to`, chain id
**9745**, block **30724096** (0x1d4d000), 2026-08-25. Baseline fork **prague**.

**Evidence path taken: (a), source — but not the source anyone expected.** The gate
question was whether a public execution client exists. It does, and it is
`paradigmxyz/reth` itself: Plasma's own node template pins
`ghcr.io/paradigmxyz/reth:v1.11.3` **by digest** as the mainnet execution image. There
was no need for the `documented` path and no justification for it. The org
(`PlasmaLaboratories`, not `plasma-network` or `PlasmaNetwork` — the latter is an
unrelated 2019 account with zero repos) does keep a reth fork, but it has **no tags,
no releases, and no consensus changes**.

---

## 1. The execution layer is bit-for-bit upstream reth — three independent proofs

- **The operator config.** `config/mainnet/.env` sets
  `EXECUTION_IMAGE=ghcr.io/paradigmxyz/reth`, `EXECUTION_TAG=v1.11.3@sha256:523e5c6a…`
  — an upstream image referenced by digest, not a Plasma rebuild.
- **The blocks themselves.** Every mainnet block's `extraData` is
  `0x726574682f76312e31312e332f6c696e7578` = the ASCII string `reth/v1.11.3/linux`.
  That is exactly `default_extra_data()` in `crates/node/core/src/version.rs`
  (`format!("reth/v{}/{}", CARGO_PKG_VERSION, OS)`), unaltered by the block producer.
- **The RPC's self-report.** `web3_clientVersion` returns `reth/v1.8.3-4219741`, and
  `4219741` is the prefix of `42197415102b7a20be42e4fe919f024b81ceb55b`, which is
  precisely the commit upstream's `v1.8.3` tag points at.

The `PlasmaLaboratories/reth` fork's branches are upstream syncs, an **ExEx** that
posts XPL balance updates to a webhook (an observer, not a state-transition rule), and
one `eth_feeHistory` fix. That fix is itself the tell: it corrects
`blob_gas_used_ratio` when `max_blob_count == 0`, a bug Plasma hit *because* its own
genesis disables blobs — and it was upstreamed, co-authored by a reth maintainer. The
total EL delta of this chain against upstream is a bug fix that upstream accepted.

## 2. The zero-fee USDT paymaster is not a consensus divergence — and is not live

This was the question worth the effort, and the answer is a clean negative, argued
four ways:

- **Structural.** Unmodified reth has nowhere to put a fee rule keyed to an ERC-20
  address. There is no fee-currency transaction field (Celo's `0x7b`), no client-driven
  debit/credit calls (Celo), no ProtocolConfig read (Arc), no `currency == "USD"` check
  (Tempo). A transaction must satisfy `max_fee_per_gas >= base_fee` and its sender pays.
- **Empirical.** 274 transactions across 40 consecutive blocks from 30724096: **zero**
  with `gasPrice: 0x0`. Minimum effective price 8 wei; 133 of the 274 were ERC-20
  `transfer(...)` calls, including calls to USDT0 (`0xb8ce59fc…625ebb`, symbol `USDT`,
  6 decimals), and they paid gas like everything else.
- **Documented.** Plasma's own mainnet page lists exactly one fee token — "Native
  Plasma Mainnet Token XPL, Live" — under the line "*Plasma will support fee payments
  in multiple tokens soon.*" Custom gas tokens appear only in the future tense
  ("Plasma is building support…", "Developers **will be able** to register…") and
  zero-fee USD₮0 transfers are marked "**currently in development**".
- **What actually exists.** All three canonical ERC-4337 EntryPoints are deployed as
  ordinary contracts — v0.6 (`0x5FF137D4…`, 47,380 bytes), v0.7 (`0x00000000717 27De2…`,
  32,072 bytes), v0.8 (`0x4337084D…`, 43,478 bytes) — none in the genesis alloc, and the
  v0.7 EntryPoint took traffic in the sampled window. So gas sponsorship on Plasma is
  bundler machinery available on every EVM chain.

Recording this as a consensus feature would have put a fabricated fee-model divergence
into the dataset next to the real ones on Celo, Arc and Tempo. It belongs in none of
those comparisons.

## 3. The precompile delta is empty, and for once that is *measured*, not inferred

The endpoint supports EIP-7910 `eth_config`, so the node enumerates itself: exactly
the seventeen Prague precompiles at `0x01`–`0x11`, no `0x0100`, nothing in any custom
range, plus the four Prague system contracts at their **mainnet** addresses and
`blobSchedule {max: 0, target: 0}`. This sidesteps the trap the dataset has hit six
times — that `eth_getCode` cannot distinguish a precompile from a predeploy, and an
address scan cannot see a predicate-based lookup like Base's. Here the client's own
active-config enumeration is the evidence, which is strictly stronger than either.

## 4. The one real EVM-visible divergence is a genesis constant, not code

`blobSchedule.max = 0` for both Cancun and Prague. Blob transactions are encodable but
unusable: upstream reth's pool rejects them with `TooManyEip4844Blobs { permitted: 0 }`.
`eth_blobBaseFee` still returns 1 and the header still carries zeroed
`blobGasUsed`/`excessBlobGas`. EIP-4844 is therefore `removed` — the whole of the
chain's mainnet-relative EIP delta.

## 5. Where Plasma's divergence actually lives: the closed consensus client

Everything distinctive about Plasma — PlasmaBFT (a pipelined Fast HotStuff),
sub-second deterministic finality, the validator/observer split — is in
`ghcr.io/plasmalaboratories/plasma-consensus-public:1.0.0`, a container image with no
source repo. The EL is a plain Engine-API follower, which is exactly why an unmodified
reth works. This makes Plasma the dataset's cleanest instance of a chain whose
consensus layer is novel and whose execution layer is *literally* Ethereum's — a
sharper version of the "gas token is the only delta" control case that Gnosis provides,
because here even the gas token is native.

Two live oddities came out of that split. `finalized` trailed the head by ~2,662 blocks
(~44 minutes) despite BFT finality, so whatever sets the finalized tag over the Engine
API lags the consensus commit badly. And the block `miner` is not a validator key: it
is one of five **Gnosis Safe proxies** allocated at `0x…0a11b001`–`005` in genesis
(172-byte Safe proxy bytecode, eleven storage slots each), four of which hold the entire
initial XPL supply. Blocks alternate between `…0a11b004` and `…0a11b005`, so the
coinbase field tells you nothing about who proposed the block.

## 6. A curiosity worth a `unrecorded`

Genesis sets `depositContractAddress` to **Ethereum mainnet's** beacon deposit contract
(`0x00000000219ab540…7705fa`) and allocates its full 12,718-byte bytecode and 31 storage
slots; live `eth_config` reports the same address as the chain's DEPOSIT_CONTRACT_ADDRESS.
On a chain whose validators are chosen by PlasmaBFT, what consumes the resulting EIP-6110
deposit requests cannot be established from the EL alone. Left `unrecorded`.

---

## Not established here

- **PlasmaBFT's actual rules.** No source, only a container image. Finality,
  committee formation, slashing, and the fork-choice fed to the EL are all outside
  reach; the docs are the only account of them.
- **EIP-6110 deposit handling** (finding 6).
- **Whether the reth version skew matters.** Producers are on v1.11.3 (per extraData)
  while the public RPC answers as v1.8.3. Both are upstream tags and neither carries a
  Plasma patch, so the state transition is the same; but the row is pinned at v1.11.3
  because that is what the mainnet node template pins.
- **Future paymaster semantics.** If Plasma later ships protocol-level custom gas
  tokens, they cannot ship in an unmodified reth — the appearance of a Plasma-patched
  EL image in `config/mainnet/.env` is the signal to re-open this row.
- **Millisecond timestamps.** Documented as a planned additional field. Not present in
  any header observed.
- **Confidential payments module.** Documented as in development; nothing on chain.

---

## Re-verify

```sh
cd /Volumes/TendiesTown/EVM-intel
R=https://rpc.plasma.to; B=0x1d4d000   # 30724096

# --- pins
git -C chains/plasma/repos/reth rev-parse HEAD             # d6324d63… = upstream v1.11.3
gh api repos/paradigmxyz/reth/git/ref/tags/v1.11.3 --jq '.object.sha'
git -C chains/plasma/repos/node-templates rev-parse HEAD   # 09df1007…

# --- the EL is upstream: image pinned by digest, and reth's own extraData format
grep -E 'EXECUTION_IMAGE|EXECUTION_TAG|CONSENSUS_IMAGE|CONSENSUS_TAG' \
  chains/plasma/repos/node-templates/config/mainnet/.env
sed -n '/pub fn default_extra_data/,+3p' \
  chains/plasma/repos/reth/crates/node/core/src/version.rs
# --- the fork has no releases and no consensus changes
gh api repos/PlasmaLaboratories/reth/releases --jq 'length'   # 0
gh api repos/PlasmaLaboratories/reth/tags --jq 'length'       # 0
gh api repos/paradigmxyz/reth/commits/4219741 --jq '.sha'     # == upstream v1.8.3

# --- genesis: prague at 0, blobs disabled, mainnet deposit contract
jq '.config | {chainId, pragueTime, osakaTime, blobSchedule, depositContractAddress}' \
  chains/plasma/repos/node-templates/config/mainnet/genesis.json

# --- live: client, header, extraData
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"web3_clientVersion","params":[]}' $R
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",false]}" $R \
  | jq -r '.result | {extraData, miner, baseFeePerGas, gasLimit, requestsHash, blobGasUsed}'
python3 -c "print(bytes.fromhex('726574682f76312e31312e332f6c696e7578').decode())"

# --- live: the node enumerates its own precompiles and system contracts (finding 3)
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_config","params":[]}' $R \
  | jq -r '.result.current | {chainId, forkId, activationTime, blobSchedule, systemContracts,
           precompiles:(.precompiles|keys|sort)}'

# --- live: NO zero-fee transactions (finding 2) — 40 blocks, 274 txs
python3 - <<'PY'
import json,urllib.request
def rpc(m,p):
    b=json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode()
    r=urllib.request.Request("https://rpc.plasma.to",data=b,
        headers={"content-type":"application/json","user-agent":"curl/8.7.1"})
    return json.load(urllib.request.urlopen(r,timeout=20))["result"]
n=z=0; types={}; mn=None
for i in range(40):
    for t in rpc("eth_getBlockByNumber",[hex(0x1d4d000+i),True])["transactions"]:
        n+=1; gp=int(t["gasPrice"],16); z+= gp==0
        mn = gp if mn is None else min(mn,gp)
        types[t["type"]]=types.get(t["type"],0)+1
print("txs",n,"zero-price",z,"min gasPrice(wei)",mn,"types",types)
PY

# --- live: the ERC-4337 EntryPoints exist as ordinary contracts (finding 2)
for a in 0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789 \
         0x0000000071727De22E5E9d8BAf0edAc6f37da032 \
         0x4337084D9E255Ff0702461CF8895CE9E3b5Ff108; do
  curl -s -X POST -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$a\",\"$B\"]}" $R \
    | jq -r '.result|length'; done
# ...and that none of them is in the genesis alloc
jq -r '.alloc|keys[]' chains/plasma/repos/node-templates/config/mainnet/genesis.json | grep -i '4337\|71727de2\|5ff137d4' || echo "not in genesis alloc"

# --- live: finalized lag, and the Safe at the coinbase (finding 5)
curl -s -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["finalized",false]}' $R \
  | jq -r '.result.number'
curl -s -X POST -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x000000000000000000000000000000000a11b005\",\"$B\"]}" $R \
  | jq -r '.result'     # Gnosis Safe proxy: masterCopy() short-circuit a619486e + DELEGATECALL

# --- docs: one live fee token, everything else future tense
curl -s https://docs.plasma.to/llms-full.txt | grep -n -i \
  'will support fee payments\|currently in development\|is building support'

# --- schema
tools/.venv/bin/python tools/verify.py 2>&1 | sed -n '/^plasma/,/^$/p'
```
