# Taiko Alethia

**Role:** `fork` · **Upstream:** `ethereum` · **Chain ID:** 167000 · **Baseline:** Osaka
**Client:** [`taikoxyz/taiko-geth`](https://github.com/taikoxyz/taiko-geth) `v2.6.0`
(`ca164c06e00ceb2b1cc25ae2a141ee57b6a1cd18`) ·
**Companion:** [`taikoxyz/taiko-mono`](https://github.com/taikoxyz/taiko-mono)
`taiko-alethia-client-v2.6.0` (`c84c333e6a819062b9017f925882ca28b9969fe7`)
**Live probes:** `https://rpc.mainnet.taiko.xyz` @ block `10471924` (`0x9fc9f4`)

Taiko is a **based rollup**: it has no sequencer of its own. L1 proposers submit L2
blocks; a driver re-derives each one from L1 and drives taiko-geth over an extended
Engine API. The client is a direct go-ethereum fork — no OP Stack, no Arbitrum, no
Cosmos anywhere in the tree — which is now unusual for an L2 of this size.

---

## 1. The anchor transaction, and which box it goes in

Every L2 block opens with a mandatory protocol transaction — the **anchor** — that
writes the L1 checkpoint into an L2 contract. It is what makes a based rollup know
about L1. The brief asked which of the schema's three categories it belongs to. The
answer is **two of them, and emphatically not the third**, and the reason is worth
more than the answer.

**It is not `non_evm_transactions`.** That category is defined by the *absence* of an
EIP-2718 type byte (Avalanche's UTXO atomic txs, Tron's protobuf contracts). The
anchor has a type byte: `0x02`. An unmodified EIP-2718 decoder parses it into an
unmodified `DynamicFeeTx`. Every field an RPC client sees is ordinary. Putting it here
would be wrong in the one way the category exists to prevent.

**It belongs in `tx_types`, as `0x02: modified`.** Not as a new byte — Taiko allocated
none. At index 0 the state-transition rules for type `0x02` change:
`core/state_transition.go` skips the balance check, sets the up-front gas debit to
zero, skips the `gasFeeCap >= baseFee` check, skips `returnGas`, and skips the base-fee
split. Anywhere else in the block, `0x02` is exactly mainnet's. This is a **positional
override of a mainnet type byte** — a shape the type-byte axis has no vocabulary for,
and the reason the entry needs a long note rather than a new address.

**It belongs in `system_transactions`.** Protocol-constructed, mandatory, fee-exempt,
never user-submitted, and validated by the consensus engine rather than the txpool. It
meets every criterion in SCHEMA.md's definition except "has no type byte", which is
not one of the criteria — that clause belongs to `non_evm_transactions`.

So the row declares it in both, and says so. The dataset's three-way split has a
fourth case it did not anticipate: **a protocol transaction wearing a registered
mainnet type byte.** OP Stack's `0x7e` deposit is self-describing; Taiko's anchor is
not.

### It is identified by its index, not by its bytes

This is the sharpest single fact in the row:

```go
// core/state_processor.go
for i, tx := range block.Transactions() {
    // CHANGE(taiko): mark the first transaction as anchor transaction.
    if i == 0 && config.Taiko {
        if err := tx.MarkAsAnchor(); err != nil { ... }
```

`i == 0`. Nothing else. There is no flag in the envelope, no reserved type, no
distinguishing field. An indexer that classifies transactions by type byte will bill
users for ~112,000 gas per block that nobody paid, rank the golden-touch account as
the chain's busiest EOA, and record a mandatory system call as user activity.

`consensus/taiko/consensus.go:ValidateAnchorTx` is where the real check lives, and it
is an equality test on six things at once: type == `0x02`; recipient == the
chain-id-derived Anchor address; calldata prefix == the fork's anchor selector
(`0xda69d3db` / `0xfd85eb2d` / `0x48080a45` / `0x523e6854` for `anchor` / V2 / V3 / V4);
value == 0; gas == **exactly** 250,000 pre-Pacaya and **exactly** 1,000,000 after;
`gasFeeCap` == the header base fee; and the recovered sender == the golden-touch
account. Note *exactly* on the gas: it is an equality, not a ceiling.

Worth recording where that function is *called from*: `FinalizeAndAssemble` — the
block-**building** path — and nowhere else. That is the path every node takes when it
derives a block from L1, so in normal operation every node runs it. The block-**import**
path marks index 0 as the anchor with no validation at all and relies on the state root
diverging if the producer did anything else.

### Live, at block 10471924

```
tx[0]  type 0x2   from 0x0000777735367b36bC9B61C50022d9D0700dB4Ec
                  to   0x1670000000000000000000000000000000010001
       gas 0xf4240 (1,000,000)   value 0x0   maxPriorityFeePerGas 0x0
       maxFeePerGas 0x989680 == header baseFeePerGas
       r 0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798
       input 0x523e6854…  (anchorV4)
```

---

## 2. `tx_authorization`: the axis has no value for "the key is published"

The brief asked whether `key_binding: derived | declared | account_code` covers a
transaction signed with a compile-time-constant signature. **Mechanically, `derived`
is correct** — and that is the finding.

`ValidateAnchorTx` recovers the sender with plain `types.MakeSigner(...).Sender(tx)`
over the ordinary `0x02` sighash and compares it to a hardcoded address. The identity
`ecrecover(sig) == from` holds. Nothing is declared on-chain; no account code decides.
So `derived` it is, and `signers_per_tx: 1`.

What the axis cannot say is that **the private key is published**:

- `taiko-mono/packages/taiko-client/bindings/encoding/struct.go` —
  `GoldenTouchPrivKey = "92954368afd3caa1f3ce3ead0069c1af414054aefe1ef9aeacc1bf426222ce38"`,
  and the same constant again in the Rust driver as `GOLDEN_TOUCH_PRIVATE_KEY`.
- The driver signs with a **fixed ECDSA nonce**: `signTxPayload` tries `k = 1`, falling
  back to `k = 2` only if `s` would be zero (`FixedKSigner.SignWithK`).

With `k = 1`, `r = (1·G).x` — the **x-coordinate of the secp256k1 generator**, a
constant published in the curve parameters. It is the same on every anchor transaction
ever produced, on every Taiko network. Twelve consecutive anchors at blocks
10471913–10471924 carry twelve distinct `s` values, both parities, and one `r`.

Deliberate k-reuse across two different digests is the textbook way to *leak* an ECDSA
private key. That is precisely why the key was published rather than protected: the
goal is determinism, so a prover can rebuild the anchor's exact bytes from L1 data
alone. Secrecy was never available, so it was never attempted.

The consequence for the axis: **`key_binding: derived` records a key-to-address
relation that is real and carries no authority**, and `signers_per_tx: 1` counts a
party that is not a party. All three legal values answer "which key authorizes"; none
can say "the key authorizes nothing, and the gate is elsewhere". The row keeps
`derived` and puts the argument in the `note` rather than forcing a wrong value — a
fourth value (`constant`, or `none`) is what this case wants.

Two corroborating details:

- **The client budgets for the key being public.** `miner/taiko_worker.go` has
  `removeGoldenTouchPendingTxs`, which deletes the golden-touch account from pending
  transaction lists before block building. It exists because anyone can sign as that
  account and put a transaction in the pool.
- **Nothing ever checks `r`.** Neither taiko-geth, nor the Go driver's
  `anchor_tx_validator`, nor the Rust reimplementation verifies that `r` equals the
  generator's x-coordinate. All three check only the recovered sender. The constant
  signature is a **producer convention**, reproducible by anyone — not a consensus
  rule. Saying "the anchor has a hardcoded signature" overstates what the protocol
  enforces.

---

## 3. Cancun, Prague and Osaka arrived at the same instant

`core/taiko_genesis.go`:

```go
chainConfig.UnzenTime = &MainnetUnzenTime          // 1786021200 — 2026-08-06 13:00 UTC
if MainnetUnzenTime != math.MaxUint64 {
    chainConfig.CancunTime = &MainnetUnzenTime
    chainConfig.PragueTime = &MainnetUnzenTime
    chainConfig.OsakaTime  = &MainnetUnzenTime
}
```

Taiko ran on **Shanghai** from genesis until 2026-08-06, then took three mainnet forks
in one step. This is the largest single fork transition in the dataset, and the row's
best live evidence is a one-block control:

```
eth_call 0x0100, valid P-256 vector @ 0x944b7a (9718650) -> 0x            (absent)
eth_call 0x0100, valid P-256 vector @ 0x944b7b (9718651) -> 0x…0000000001 (present)
```

The same call, one block apart. Same probe with a byte flipped at the pinned block
returns `0x`, so the "empty means invalid" ambiguity that defeats Sei and Hyperliquid
probes is resolved here by a valid vector plus a control.

Two consequences that matter more than the trivia:

1. **There are no `cancunTime` / `pragueTime` / `osakaTime` keys to read.** They are
   computed inside the client from `unzenTime`. Any tool that determines a chain's fork
   level by reading a genesis config finds nothing and concludes Taiko is pre-Cancun.
2. **The Cancun/Prague system contracts were never deployed.** EIP-4788, EIP-2935,
   EIP-6110, EIP-7002 and EIP-7251 are all **empty accounts** at their canonical
   addresses. Every one answers a call with success and no data. `BLOCKHASH` still
   works — taiko-geth carries upstream's `opBlockhash`, which resolves through the
   chain context — but the 2935 *contract* path returns `bytes32(0)` forever, and
   `parentBeaconBlockRoot` is written as zero by `Finalize` and only checked for
   non-nil-ness. The client acknowledges this in a comment about witnesses needing "an
   EIP-4788 / EIP-2935 system call to a system contract that is not deployed on the
   chain".

This is a **fifth flavour** of same-address divergence, next to README's four (cap,
omit, reprice, replace): the address is *canonical, empty, and semantically load-bearing*.
Linea reaches the same failure by relocating those contracts; Taiko reaches it by never
deploying them. Neither reverts.

---

## 4. There is a second gas, and it is enforced in `header.difficulty`

From Unzen, every opcode and every precompile call is charged a second time against a
per-block **zk-gas** budget: `rawGas × multiplier`, 100,000,000 per block, plus 243,000
charged per transaction before execution begins (`TxIntrinsicZkGas`, the proving cost
of sender recovery).

- **It truncates blocks.** When a transaction would exceed the budget, that transaction
  *and every one after it* is dropped, and the block is still valid
  (`core/state_processor.go`, `ErrZkGasLimitExceeded`). A transaction can be
  well-formed, funded, comfortably inside the gas limit, first in the queue, and simply
  not be in the block. `eth_estimateGas` expresses none of it; there is no
  `eth_estimateZkGas`.
- **The anchor is exempt from truncation** but not from metering: `i > 0` guards the
  truncation branch, and if the anchor alone exceeded the budget the whole block fails.
- **`header.difficulty` carries the block's zk gas**, and import *recomputes* it and
  rejects a mismatch. Live: `0x0` at block 9718650, `0x11b632` (1,160,754) at 9718651
  and at the pinned block. Post-merge tooling universally reads `difficulty == 0` as
  "this is a PoS chain"; on Taiko that test has been false since 2026-08-06 and means
  something unrelated. The dataset already has OP Stack repurposing `blobGasUsed`; this
  is the same move applied to the one header field everybody treats as dead.
- **The multiplier table is a forward-compatibility trap.** Any precompile address
  *absent* from `unzenPrecompileMultipliers` resolves to `FailsafeMultiplier = 65535`,
  which against a 100,000,000 budget allows roughly 1,500 units of raw gas for the whole
  block. A precompile added by a future upstream geth rebase, but not added to that
  table, becomes unusable — and fails as a truncated block, not as a revert.
- **Relative opcode cost differs from mainnet even though absolute gas does not.**
  `SLOAD` is 3 in zk gas and `TLOAD` is 1 — inverting their gas relationship. Recorded
  as an empty `opcodes.modified` with a loud note rather than 140 rows, because no
  opcode's result or gas differs.

---

## 5. The fee model diverges in four places at once

- **EIP-4396**, which mainnet has *not* adopted, replaces the base-fee formula at
  Shasta: the parent's gas target is scaled by the parent's actual block time.
  `VerifyEIP4396Header` recomputes it at import, so it is a consensus rule.
- **The base fee is capped.** Floor 0.01 gwei on mainnet, **ceiling 1 gwei**
  (`maxBaseFeeShasta`). No other row in this dataset caps its base fee. A ceiling means
  the 1559 feedback loop saturates: past 1 gwei the market cannot price congestion at
  all. The pinned block sits exactly on the floor (`0x989680`).
- **The base fee is not burnt.** `gasUsed × baseFee` is split between `block.coinbase`
  (the L1 proposer) and a treasury, by a percentage read out of **the block's own
  extraData byte 0** — 75% at the pinned block. So the fee split is a per-block,
  proposer-supplied, consensus-visible parameter. "Base fee burnt, tips to the
  sequencer" is wrong in both halves. This makes Taiko the second chain here to turn
  `extraData` into a pricing channel, after Linea, independently.
- **The header `gasLimit` overstates user-available gas by exactly 1,000,000**, the
  anchor's allowance, which is *added* to `MaxBlockGasLimit` rather than taken out of
  it. Live: `0x2bde780` = 46,000,000 against a protocol maximum of 45,000,000. A
  `gasUsed / gasLimit` utilisation metric is wrong in the denominator and counts ~112,000
  of unpaid anchor gas in the numerator.

The anchor's own receipt is the sharpest small trap: `status 0x1`, `gasUsed 0x1b5c4`,
**`effectiveGasPrice 0x989680`** — while the sender's balance never moves, because
`buyGas` zeroes `mgval` and `returnGas` is skipped. Multiply the two receipt fields and
you invent revenue that nobody paid.

---

## 6. Smaller findings

- **Zero custom precompile addresses, zero repriced.** `core/vm/contracts.go` is
  upstream's; grepping it for `taiko` returns nothing. For a chain this divergent that
  is a finding: Taiko put none of its protocol surface at a precompile address, using a
  predeploy contract instead. The whole EVM-gas schedule is stock Osaka — *every* Taiko
  cost change lives in the zk-gas dimension.
- **System-contract addresses are computed from the chain id**, not fixed: decimal chain
  id, zero padding, suffix `10001`. Two independent functions in the client do this
  derivation, and on Taiko mainnet they produce the **same** address — so the Anchor
  contract *is* the fee treasury, which is why `Anchor.sol` carries a `withdraw`
  function. The two derivations differ on a chain id with a leading zero (the consensus
  engine strips one, the treasury function does not); no live Taiko network hits that.
- **The genesis alloc uses two prefixes for one family**: proxies at `0x1670…`,
  implementations at the transposed `0x0167…`, every predeploy appearing twice. 22
  accounts total.
- **Blob transactions can never be included.** The builder skips `BlobTxType`
  unconditionally at every fork; from Unzen `FinalizeAndAssemble` rejects a body
  containing one. Meanwhile the KZG point-evaluation precompile at `0x0a` is installed
  and works — a precompile for a transaction type the chain will not carry.
- **Live traffic is thin and conventional.** 201 consecutive blocks ending at the pinned
  block held 216 transactions: 202 of type `0x02` (201 of them anchors) and 14 of type
  `0x00`. No `0x01`, `0x03` or `0x04` observed.

---

## What contradicts, or extends, existing claims

Nothing in this row **contradicts** another row. Three things extend README's framing,
for whoever owns that prose:

1. **"Two allocation frontiers are closing on each other."** Taiko is a counter-example
   to the premise, not the arithmetic: a top-tier L2 with a *mandatory protocol
   transaction in every block* that allocated **no type byte at all** and hid it inside
   mainnet's `0x02`, distinguished only by position. The type-byte census is not a
   census of protocol transactions.
2. **"Same-address divergence comes in four flavours."** Taiko adds a fifth:
   *canonical, empty, and load-bearing* — five Cancun/Prague system contracts that were
   never deployed, each answering calls with success and no data.
3. **"Watch the fields that survive their feature."** `header.difficulty` joins
   `blobGasUsed` on that list, and is the more dangerous of the two, because
   `difficulty == 0` is a near-universal post-merge test.

---

## Not established here

- **`opcodes` extractor / precompile cross-check.** `verify.py` reports
  `! NO EXTRACTOR` for taiko; the precompile list is taken from a source read
  (`PrecompiledContractsOsaka`, unmodified) and not machine-diffed.
- **EIP-3529** — `unrecorded`. The refund path is upstream's, but the anchor skips
  `returnGas` entirely and no source read was done on how the zk-gas meter composes with
  a refunded `SSTORE` (which flows through a Taiko-added `errSStoreSentry` branch).
- **EIP-7928 / Amsterdam** — `unrecorded`. No Amsterdam timestamp is set for any Taiko
  network and no intent was established from source.
- **EIP-7702 live half.** Source is definite (nothing filters `SetCodeTx`; the builder's
  only type rejection is `BlobTxType`), but no `0x04` transaction was observed in the
  201-block sample, so the live confirmation is missing.
- **Pre-Pacaya anchor shapes.** `anchor`, `anchorV2` and `anchorV3` are recorded from
  the client's selector constants; only `anchorV4` was observed live.
- **The prover and the L1 contracts.** Only the execution layer and the anchor
  construction path were read. How proposals are proved, how the whitelist/preconf
  proposer set is authorised on L1, and what the zk circuits actually charge are
  outside this row.
- **Whether a golden-touch transaction can be included at index > 0.** The builder
  removes the account from the pool, and such a transaction would not be marked anchor
  (so it would pay gas normally), but no test or probe was run.

---

## Re-verify

```sh
# from the repo root
tools/clone.sh                                  # re-fetches every pinned clone
tools/.venv/bin/python tools/verify.py          # expect: pin ok, citations ok, exit 0
                                                # "! NO EXTRACTOR" for taiko is expected

G=chains/taiko/repos/taiko-geth
M=chains/taiko/repos/taiko-mono
R=https://rpc.mainnet.taiko.xyz
rpc() { curl -s -X POST $R -H 'content-type: application/json' \
        -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}"; }

# --- the anchor: address, selectors, gas equality, and the positional marking
git -C $G grep -n 'GoldenTouchAccount\|AnchorV4Selector\|AnchorV3V4GasLimit' -- consensus/taiko/consensus.go
git -C $G grep -n -A3 'mark the first transaction as anchor' -- core/state_processor.go
git -C $G grep -n 'IsAnchor' -- core/state_transition.go     # balance check, fee cap, returnGas, base-fee split
git -C $G grep -rn 'ValidateAnchorTx' -- '*.go' | grep -v _test  # one caller: FinalizeAndAssemble

# --- the published key and the fixed k
git -C $M grep -n 'GoldenTouchPrivKey =' -- packages/taiko-client/bindings/encoding/struct.go
git -C $M grep -n -A6 'Try k = 1' -- packages/taiko-client/driver/anchor_tx_constructor/anchor_tx_constructor.go
git -C $M grep -n 'GOLDEN_TOUCH_ADDRESS' -- packages/protocol/contracts/layer2/core/Anchor.sol
# and that nothing checks r:
git -C $G grep -rn 'GoldenTouch' -- '*.go' | grep -v _test    # only address comparison
git -C $M grep -n 'goldenTouchAddress' -- packages/taiko-client/prover/anchor_tx_validator/anchor_tx_validator.go

# --- live: tx[0] is the anchor, r is the generator x, and it paid nothing
rpc eth_getBlockByNumber '["0x9fc9f4",true]' | python3 -c '
import json,sys; t=json.load(sys.stdin)["result"]["transactions"][0]
print({k:t[k] for k in ("type","from","to","gas","value","maxFeePerGas","maxPriorityFeePerGas","r","nonce")})
print("selector",t["input"][:10])'
# -> type 0x2, from 0x0000777735367b36bc9b61c50022d9d0700db4ec,
#    to 0x1670000000000000000000000000000000010001, gas 0xf4240, value 0x0,
#    r 0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798, selector 0x523e6854
# r is the secp256k1 generator x-coordinate:
python3 -c 'print(hex(0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798))'

# constant r, varying s, across 12 consecutive blocks
python3 - <<'PY'
import json,urllib.request
R="https://rpc.mainnet.taiko.xyz"
def rpc(m,p):
    q=urllib.request.Request(R,data=json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),
                             headers={"content-type":"application/json"})
    return json.load(urllib.request.urlopen(q))["result"]
a=[rpc("eth_getBlockByNumber",[hex(i),True])["transactions"][0] for i in range(10471913,10471925)]
print("distinct r:",{t["r"] for t in a}); print("distinct s:",len({t["s"] for t in a}))
print("senders:",{t["from"] for t in a})
PY

# the anchor's receipt claims a price it never paid
rpc eth_getTransactionReceipt '["0x778dd9ca01933a65f07ece9d8922af257796f27b161e1df33fd64d1980a0561c"]' \
  | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print("gasUsed",r["gasUsed"],"effectiveGasPrice",r["effectiveGasPrice"])'
# -> gasUsed 0x1b5c4 effectiveGasPrice 0x989680   (sender balance unchanged)

# --- Cancun+Prague+Osaka at one timestamp
git -C $G grep -n -B2 -A6 'MainnetUnzenTime$' -- core/taiko_genesis.go
git -C $G grep -n 'MainnetUnzenTime uint64\|MainnetShastaTime uint64\|MainnetOntakeBlock\|MainnetPacayaBlock' -- core/taiko_genesis.go

# P256VERIFY: valid vector, corrupted control, and one block before Unzen
V=202691bb2e65710683fede2836abc14d284a96751a591e97521aa4b6fb7cd03cf3ac8061b514795b8843e3d6629527ed2afd6b1f6a555a7acabb5e6f79c8c2ac6aac8b25d9564d65fd873396b9b31f54c9a407f893790b540d7c0b8aecdea2f71ccbe91c075fc7f4f033bfa248db8fccd3565de94bbfb12f3c59ff46c271bf83ce4014c68811f9a21a1fdb2c0e6113e06db7ca93b7404e78dc7ccd5ca89a4ca9
rpc eth_call "[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"0x$V\"},\"0x9fc9f4\"]"
# -> 0x00..01
rpc eth_call "[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"0xdf2691bb${V:8}\"},\"0x9fc9f4\"]"
# -> 0x            (corrupted digest: invalid, not absent)
rpc eth_call "[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"0x$V\"},\"0x944b7a\"]"
# -> 0x            (block 9718650: the precompile did not exist yet)

# the Cancun/Prague system contracts were never deployed
for a in 0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02 0x0000F90827F1C53a10cb7A02335B175320002935 \
         0x00000000219ab540356cBB839Cbe05303d7705Fa 0x00000961Ef480Eb55e80D19ad83579A64c007002 \
         0x0000BBdDc7CE488642fb579F8B00f3a590007251; do
  echo -n "$a "; rpc eth_getCode "[\"$a\",\"0x9fc9f4\"]"; echo
done
# -> all "0x"

# --- zk gas in header.difficulty, before and after Unzen
git -C $G grep -n 'BlockZkGasLimit\|TxIntrinsicZkGas\|FailsafeMultiplier' -- core/vm/taiko_zk_gas_unzen.go core/vm/taiko_zk_gas.go
git -C $G grep -n -A6 'zk gas difficulty mismatch' -- core/state_processor.go
for b in 0x944b7a 0x944b7b 0x9fc9f4; do
  echo -n "$b "; rpc eth_getBlockByNumber "[\"$b\",false]" \
    | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print("difficulty",r["difficulty"],"requestsHash",r.get("requestsHash"),"gasLimit",r["gasLimit"],"extraData",r["extraData"])'
done
# -> 0x944b7a difficulty 0x0    requestsHash None
#    0x944b7b difficulty 0x11b632 requestsHash 0xe3b0c4…  (first Unzen block)
#    0x9fc9f4 difficulty 0x11b632 gasLimit 0x2bde780 extraData 0x4b000000007746

# --- fee model: 4396, the 1 gwei ceiling, the extraData fee split, the +1M gas limit
git -C $G grep -n 'maxBaseFeeShasta\|minBaseFeeShastaMainnet\|blockTimeTarget' -- consensus/misc/taiko_eip4396.go
git -C $G grep -n -A10 'basefee is not burnt' -- core/state_transition.go
git -C $M grep -n 'MaxBlockGasLimit =' -- packages/taiko-client/bindings/manifest/manifest.go
git -C $M grep -n 'meta.GasLimit += consensus.AnchorV3V4GasLimit' -- packages/taiko-client/driver/chain_syncer/event/blocks_inserter/common.go
python3 -c 'print(0x2bde780, 0x2bde780-1_000_000)'   # 46000000 45000000

# --- the Anchor contract is also the treasury, and its address is chain-id-derived
git -C $G grep -n -A12 'TaikoTreasuryAddress derives' -- core/state_transition.go
rpc eth_call '[{"to":"0x1670000000000000000000000000000000010001","data":"0x9ee512f2"},"0x9fc9f4"]'
# -> 0x0000000000000000000000000000777735367b36bc9b61c50022d9d0700db4ec  (GOLDEN_TOUCH_ADDRESS())
rpc eth_getBalance '["0x1670000000000000000000000000000000010001","0x9fc9f4"]'
# -> 0x4227759dc288f00dd  (~76.5 ETH of accrued base fee)

# --- blob transactions are unmineable; live type census
git -C $G grep -n -B1 -A3 'Skip a blob transaction' -- miner/taiko_worker.go
python3 - <<'PY'
import json,urllib.request
from collections import Counter
R="https://rpc.mainnet.taiko.xyz"
def rpc(m,p):
    q=urllib.request.Request(R,data=json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),
                             headers={"content-type":"application/json"})
    return json.load(urllib.request.urlopen(q))["result"]
c=Counter(); n=0
for i in range(10471724,10471925):
    for t in rpc("eth_getBlockByNumber",[hex(i),True])["transactions"]:
        c[t["type"]]+=1; n+=1
print(n, dict(c))
PY
# -> 216 {'0x2': 202, '0x0': 14}
```
