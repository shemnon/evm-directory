# Gnosis Chain — the control case fails, and it fails at the fee sink

**Chain ID 100 · role: `fork` · upstream: ethereum · baseline: Osaka (Fusaka, 2026-04-14)**

Reference: [NethermindEth/nethermind `1.39.3`](https://github.com/NethermindEth/nethermind)
@ `28cbe2a0`, cross-checked against [gnosischain/reth_gnosis `v2.0.0`](https://github.com/gnosischain/reth_gnosis)
@ `5b236a06` and the normative [gnosischain/specs](https://github.com/gnosischain/specs)
@ `045d46d6`. Live probes at block **47884196**.

CANDIDATES.md nominated Gnosis as "the cleanest available *gas token is the only
delta* control case." **It is not one.** The EVM half of that prediction holds
completely — zero custom opcodes, zero custom precompiles, zero custom transaction
types, four mainnet system contracts byte-identical at their canonical addresses.
The prediction fails everywhere the *token* touches the protocol: at the base-fee
sink, at withdrawals, at the deposit address, and at the blob price floor. Swapping
the gas token turns out not to be a swap. It is a set of edits to the state
transition, and every one of them fails silently.

---

## 1. The base fee is not burned — and the 1559 parameters are mainnet's to the digit

This is the finding. `LondonGnosis.Apply` sets one field —
`spec.FeeCollector = 0x6BBe78ee9e474842Dbd4AB4987b3CeFE88426A92`
(`Nethermind.Specs/GnosisForks/12_LondonGnosis.cs`) — and Nethermind's *shared*
transaction processor does the rest: `PayFees` credits `collectedFees` to
`spec.FeeCollector` rather than dropping them
(`Nethermind.Evm/TransactionProcessing/TransactionProcessor.cs:PayFees`). From
Pectra the blob base fee joins it (`18_PragueGnosis.cs:IsEip4844FeeCollectorEnabled`).

Measured at the pinned block, exactly:

| quantity | value |
|---|---|
| `baseFeePerGas` | 13 wei |
| `gasUsed` | 2,477,810 |
| product | **32,211,530** |
| collector balance delta over the block | **32,211,530** |

Every other 1559 parameter is mainnet's: elasticity 2, base-fee change denominator
8, initial base fee 1 gwei. **That is what makes it dangerous.** A fee estimator
ported from mainnet is *correct*. A supply model, a burn dashboard, or an
"ultrasound money" analytic ported from mainnet reports a burn that never happened,
and nothing in the header, the receipt, or `eth_feeHistory` contradicts it.

The second implementation makes the point sharper than any comment could:
`reth_gnosis`'s `GnosisEvmConfig::new` reads `eip1559collector` from genesis and
**panics** if it is absent. A Gnosis node cannot start without knowing where the
base fee goes.

## 2. Withdrawals credit zero native token, and the units are off by 32

Gnosis stakes GNO and pays gas in xDAI, so EIP-4895's "mint native token to
`withdrawal.address`" is unavailable — xDAI may only be minted against bridged DAI.
`gnosischain/specs/execution/withdrawals.md` replaces it with one system transaction
per block from `0xff..fe` calling
`executeSystemWithdrawals(uint256,uint64[],address[])` on
`0x0B98057eA310F4d31F2a452B414647007d1645d9`. Nethermind's
`AuraWithdrawalProcessor.ProcessWithdrawals` packs the whole withdrawals array into
that single call; `reth_gnosis/src/gnosis.rs` states the rule in a comment: *"Do NOT
credit withdrawals as native token mint."*

Two silent consequences, both measured across block 47884196 → 47884195:

- The pinned block carries **8 withdrawals totalling 30,663,773 Gwei** to
  `0x56cf0ff0…76640`. That account's **xDAI balance delta is 0**. An indexer that
  adds `withdrawal.amount` to the recipient's native balance is wrong on every block
  Gnosis has produced since Shapella.
- `withdrawableAmount(0x56cf0ff0…)` on the deposit contract rose by
  **958,242,906,250,000 wei**. And 30,663,773 Gwei **÷ 32** = 958,242.90625 Gwei =
  958,242,906,250,000 wei — exact. The header amount is denominated in **mGNO**
  (1 GNO = 32 mGNO, mirroring mainnet's 32-ETH validator), so reading it as GNO
  overstates by 32×.

The value also accrues as a *claimable* balance rather than a push — the recipient's
GNO ERC-20 balance is unchanged over the block too.

## 3. The system-contract seam splits cleanly, and the split has a rule

This is where four preceding rows found trouble, so it was probed exhaustively. The
result is a clean law rather than a list:

| contract | address | result |
|---|---|---|
| EIP-4788 beacon roots | `0x000F3df6…0Beac02` | canonical, **byte-identical to mainnet** |
| EIP-2935 history | `0x0000F908…002935` | canonical, **byte-identical to mainnet** |
| EIP-7002 withdrawal requests | `0x00000961…007002` | canonical, **byte-identical to mainnet** |
| EIP-7251 consolidations | `0x0000BBdD…007251` | canonical, **byte-identical to mainnet** |
| EIP-6110 deposits | mainnet's `0x00000000219a…7705Fa` | **EMPTY ACCOUNT** |
| EIP-6110 deposits | Gnosis's `0x0B98057e…1645d9` | 1165 bytes; `stake_token()` → GNO |

Each of the first four was fetched from a mainnet node at `latest` and from Gnosis
at 47884196 and compared byte for byte. **The rule: the only system contract that
moved is the only one whose address is a chainspec *field*** (`depositContractAddress`).
The three whose addresses are hardcoded constants in client source are exactly where
mainnet puts them — the inverse of Linea, which relocated 7002 and 7251 off their
canonical addresses and left them empty.

The one that *did* move fails in the Taiko/Linea shape: mainnet's deposit address is
an empty account, and an empty account answers every call with **success and no
data**. Staking code that hardcodes `0x00000000219ab540356cBB839Cbe05303d7705Fa`
gets zeroes forever, not a revert.

`0x0100` was probed the hard way — a locally generated valid P-256 signature returns
`0x…01`, the same call with `s+1` returns empty — because the README's Sei/Hyperliquid
finding establishes that presence alone proves nothing. Gnosis passes.

## 4. Pre-merge headers: same item count, different shape, no error

The header *count* check that caught Sonic passes here, and something else does not.

- **Block 47884196** (post-merge): **21 RLP items**, mainnet Osaka order,
  `parentBeaconBlockRoot` and `requestsHash` included. Identical to mainnet.
- **Block 20,000,000** (post-London, pre-merge): **16 RLP items** — the same count as
  a mainnet London header. But items 14 and 15 are **`auRaStep` (4 bytes)** and
  **`auRaSignature` (65 bytes)**, where mainnet has `mixHash` (32) and `nonce` (8).
  Item 16 is `baseFeePerGas`.

`HeaderDecoder` distinguishes the two layouts by **peeking whether the next item is
exactly 32 bytes long** — that is the only signal in the encoding. A positional
mainnet decoder does not fail on these headers; it reads an AuRa step as a `mixHash`,
a 65-byte signature as an 8-byte `nonce`, and computes a wrong block hash. And the
JSON-RPC papers over it: `eth_getBlockByNumber` reports `mixHash: 0x00…00` and
`nonce: 0x00…00` for that block while adding `auraStep` and `auraSeal` as extra keys.
Only the RLP tells the truth.

`difficulty` on those blocks is `0xfffffffffffffffffffffffffffffffe` — AuRa writes a
step-derived ordering key, not work. That is where the chain's absurd terminal total
difficulty (`8626000000000000000000058750000000000000000000`) comes from.

**Gnosis is the row whose header shape *converged* on mainnet.** The hazard is
entirely historical — and it covers roughly 40 million blocks.

Checked and cleared, since four rows have now found a consensus dimension hiding in a
header field: `extraData` is 18 bytes of ASCII client version (`Nethermind v1.39.3`)
with no protocol meaning; `blobGasUsed`/`excessBlobGas` carry real blob gas for a
real market; `mixHash` post-merge carries a real RANDAO from a real beacon chain.

## 5. There is a blob market, and its floor is a billion times mainnet's

Blobs are live — 7 type-`0x03` transactions in a 200-block census — and every
constant that prices them differs:

| constant | Gnosis | mainnet |
|---|---|---|
| `MIN_BLOB_GASPRICE` | **1,000,000,000** (1 gwei) | 1 wei |
| target / max blobs | **1 / 2** | 14 / 21 (at BPO2) |
| `BLOB_GASPRICE_UPDATE_FRACTION` | 1,112,826 | 3,338,477 |

`excessBlobGas` was 0 in every block sampled and `baseFeePerBlobGas` was
`0x3b9aca00` for all 20 entries of an `eth_feeHistory` window. **The blob fee on
Gnosis has never left its floor**, so it is a constant, not a market. A blob costs at
minimum 131072 × 1 gwei = 1.31 × 10¹⁴ wei of xDAI; the same blob on mainnet at the
floor costs 131,072 wei.

The gap is also widening by default. Nethermind's `blobSchedule` for chain 100 holds
exactly **one** entry — `cancun` — and `SetBlobScheduleParameters` picks the latest
entry at or before the release timestamp, so Cancun's 1/2 is still in force at Prague
and Osaka. `reth_gnosis` says it declaratively: `cancun`, `prague` and `osaka` blob
params are all `1/2/1112826`, with `scheduled: vec![]`. **Zero BPO forks have ever
run on Gnosis.** `fusaka.md` still reads "Gnosis chain intends to sets a different
blob target and max schedule than Ethereum, TBD."

## 6. Two hard forks whose entire content is rewriting an account's bytecode

The AuRa chainspec has a first-class `rewriteBytecode` / `rewriteBytecodeTimestamp`
feature (`Nethermind.Consensus.AuRa/ContractRewriter.cs`), and Gnosis has fired it
twice:

- **GIP-31**, block 21,735,000 — replaces the code at `0xf8D1677c…59A9d9`. Named in
  Nethermind's own `ForkInfoTests`. *Not* a fork-id transition (block 21735000 keeps
  first-London's fork hash `0x018479d3`).
- **Balancer**, timestamp 1766419900 (2025-12-22) — a *named hard fork*
  (fork hash `0xd00284ad`) that changes **no EVM rule**. Its whole content is writing
  a `HardcodedForwarder` bytecode into the Balancer V2 attacker's **externally owned
  account** `0x506d1f9e…03207`, before the EIP-4788 and EIP-2935 system calls,
  leaving balance, nonce and storage untouched.

Verified end to end: the live code at `0x506d1f9e…` is byte-identical to
`BALANCER_RESCUE_BYTECODE` in the pinned spec **and** to the `rewriteBytecodeTimestamp`
entry in the pinned chainspec — all three the same 1828 bytes. The same holds for
GIP-31's 7645 bytes against the pinned `rewriteBytecode` entry.

The mechanism is worth stating plainly on the `tx_authorization` axis. The purpose of
giving an EOA code is **EIP-3607**: an account with code cannot originate a
transaction. Gnosis therefore contains an account whose private key exists, still
produces valid secp256k1 signatures, and whose signatures no Gnosis block will ever
include. The *scheme* is unchanged; a specific key's authority was revoked by
consensus. Nothing else in this dataset does that.

Practical consequence: "code at an address is immutable unless `SELFDESTRUCT`ed or
`CREATE2`-redeployed" is false on Gnosis, and it is false at a *block boundary* with
no transaction to observe.

## 7. Fork lag has no sign

The brief asked how far behind mainnet Gnosis is. The question has no answer:

| Gnosis fork | Gnosis time | vs mainnet |
|---|---|---|
| Shapella (shanghai) | 1690889660 | **110.5 days LATE** |
| Dencun (cancun) | 1710181820 | **1.81 days EARLY** |
| Pectra (prague) | 1746021820 | **6.83 days EARLY** |
| Fusaka (osaka) | 1776168380 | **131.6 days LATE** |

Two of the four post-merge upgrades shipped **before** Ethereum's. Read from the
config, not a blog post.

Two structural notes. Gnosis has **no Paris-equivalent spec object** — the ladder goes
`LondonGnosis → ShanghaiGnosis`, and `16_ShanghaiGnosis.cs` sets `IsPostMerge = true`
explicitly with a comment saying why. And the Gnosis fork ladder is a real class
hierarchy (`NamedGnosisReleaseSpec`: mainnet fork for the EIP delta, Gnosis parent for
the overrides), so the *entire* release-spec divergence at Osaka is **four fields**:
`FeeCollector`, `IsEip4844FeeCollectorEnabled`, the blob triple, and
`IsPostMerge`/`WithdrawalTimestamp`.

## 8. EIP-170 arrived in 2023, not 2016

`gnosischain/specs/network-upgrades/shapella.md` says it outright: EIP-170 "wasn't
enabled on Gnosis before the Shapella hard fork," and was enabled then only because
EIP-3860 requires it. The chainspec encodes it as `maxCodeSize: 0x6000` gated by
`maxCodeSizeTransitionTimestamp: 0x64c8edbc` rather than from genesis. For roughly
seven years Gnosis had **no contract code-size limit**, so its state may contain
deployed contracts larger than any mainnet contract can be, and they still execute.

## 9. The chain spec is not where CANDIDATES.md says it is

`gnosischain/gnosis` **does not exist** (GitHub 404). And `gnosischain/configs`, the
Gnosis-owned repo that does, holds an EL genesis that is **frozen pre-Merge**: its
`params` block has no `terminalTotalDifficulty` and not one of the twenty-eight
`eip*TransitionTimestamp` keys the live chain runs on. The authoritative live
chainspec is `src/Nethermind/Chains/gnosis.json` — **inside the client**.

This inverts the Linea precedent deliberately. Linea's row pins a Gnosis-style config
repo as `client` with the EVM as a companion, because there the config repo is live.
Doing that here would have pinned a document the network stopped following in 2022.
The `configs` clone is still pinned as a companion — to *document* the staleness, not
to source facts from it.

"No client fork of its own" is also true only of the reference client. Nethermind
carries Gnosis **in-tree** (chainspec, `GnosisSpecProvider`, `Nethermind.Consensus.AuRa`,
`Nethermind.Merge.AuRa`), which is a shape this dataset has not recorded before —
neither a fork nor a plugin layer, but upstream first-class support. Beside it,
`gnosischain/reth_gnosis` is a genuine standalone Gnosis node, and
`gnosischain/go-ethereum` ships tagged releases (`v1.17.5-gc`, 2026-08-12).

## 10. Two AuRa system objects that outlived the merge — one live, one not

- **`BlockRewardAuRa` (`0x481c034c…5d39bA`) is still called every block.** This is
  not what a reader of Nethermind's merge plugin would guess: `MergePluginModule`
  installs the `MergeRewardCalculatorSource` decorator that zeroes post-merge rewards,
  but `AuRaMergeModule` composes `BaseMergePluginModule` instead and never adds that
  decorator, so `AuRaRewardCalculator` survives. `reth_gnosis` calls it
  unconditionally in `apply_post_block_system_calls`, and
  `execution/posdao-post-merge.md` requires it. Its live purpose is minting xDAI for
  the erc-to-native bridge. (Over the pinned block it minted nothing: the
  beneficiary's balance delta equalled the sum of priority fees exactly.)
- **The transaction-permission contract (`0x7Dd7032A…9A78b`) is dormant.** Gnosis is
  the only chain here with a consensus-level *sender allowlist* in its chainspec,
  consulted per transaction at block validation as well as production
  (`AuRaBlockProcessor.ValidateTxs`). Post-merge, `AuRaMergePlugin` wraps every AuRa
  filter in `AuRaMergeTxFilter` and `CreateTxPermissionFilter` passes **no post-merge
  fallback**, so the post-merge branch is `NullTxFilter`. Corroborated by
  `reth_gnosis`, which does not implement transaction permissioning at all and could
  not follow the chain if it were live. Recorded `tombstoned`: the code is there, the
  state transition no longer consults it.

---

## What the control case actually taught

The EVM half of the prediction is confirmed, and confirmed *positively* rather than
by omission: eighteen `eth_getCode` probes returning `0x` at `0x01`–`0x11` and
`0x0100`, a working P256VERIFY proved with a real signature, four mainnet system
contracts diffed byte-for-byte against a mainnet node, a 21-item mainnet-Osaka header,
and a transaction-type census containing nothing outside `0x00`–`0x04`. Gnosis is
genuinely EVM-equivalent.

**And "the gas token is the only delta" is still false**, because a gas token is not a
parameter. It is load-bearing in the fee sink (base fee collected, not burned), in
withdrawals (system call, not mint; mGNO, not GNO), in the deposit address (moved,
canonical left empty), and in the blob price floor (1 gwei, not 1 wei). Four
divergences, none visible at the opcode or precompile layer, and **every one of them
returns success**.

## Not established here

- **Whether any contract larger than 24576 bytes actually exists on Gnosis.** EIP-170
  arrived late (finding 8), so oversized contracts are *possible*; proving one exists
  needs a state scan this row did not do. Recorded `unrecorded` on `eips.170`.
- **EIP-7910 (`eth_config`).** Implemented in the pinned client
  (`IEthRpcModule.eth_config`), but the public endpoint answers `-32601 method not
  found`. Whether that is a gateway allowlist or the chain not enabling it was not
  determined. Recorded `unrecorded`.
- **`gnosischain/go-ethereum`** (`v1.17.5-gc`) was identified but **not cloned or
  read**. A third implementation might disagree with the two pinned here; nothing in
  this row rests on it.
- **The deposit contract's internal accounting.** `withdrawableAmount` was measured
  and the ÷32 conversion proved, but whether the accrual path taken is the normal one
  or the "failed withdrawal" fallback (`MAX_FAILED_WITHDRAWALS_TO_PROCESS = 4`) was
  not distinguished. The claims made are only what was measured: native delta 0, and
  `withdrawableAmount` delta exactly `amount / 32`.
- **EIP-7928 / Amsterdam.** Unscheduled for chain 100. Nethermind already carries
  `BlockAccessListHash` in the header decoder and `ApplyAuRaPreprocessingChanges` is
  already Gnosis-aware, so the work exists; the fork does not. Recorded `pending`.
- **Type `0x01`** did not appear in the 200-block census. It is enabled by
  `eip2930Transition` at block 16101500 and is recorded from the chainspec, not from
  observation.

## Re-verify

```sh
cd chains/gnosis/repos
R=https://rpc.gnosischain.com; B=0x2daa7a4      # block 47884196

# --- pins
git -C nethermind  rev-parse HEAD    # 28cbe2a0ae28373f66abdc584f3eaf21516e84b3
git -C specs       rev-parse HEAD    # 045d46d6db96a39b4d91485f9783474c13546ac9
git -C reth_gnosis rev-parse HEAD    # 5b236a06cfa29a29060fcb3355b73fef182e6e0c
git -C configs     rev-parse HEAD    # e542d132340e68fd7922149b145a0d361e1c87d4

# --- 1. the entire Gnosis release-spec delta: four fields, five small files
cat nethermind/src/Nethermind/Nethermind.Specs/GnosisForks/*.cs
sed -n '/protected virtual void PayFees/,/ReportFees/p' \
  nethermind/src/Nethermind/Nethermind.Evm/TransactionProcessing/TransactionProcessor.cs

# base fee collected, not burned — must print equal numbers
python3 - <<'PY'
import json,urllib.request
R="https://rpc.gnosischain.com"
def rpc(m,p):
    d=json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(R,d,{'content-type':'application/json'}),timeout=60))['result']
B=47884196; FC="0x6BBe78ee9e474842Dbd4AB4987b3CeFE88426A92"
blk=rpc("eth_getBlockByNumber",[hex(B),False])
print("delta ", int(rpc("eth_getBalance",[FC,hex(B)]),16)-int(rpc("eth_getBalance",[FC,hex(B-1)]),16))
print("bf*gas", int(blk['baseFeePerGas'],16)*int(blk['gasUsed'],16))
PY

# --- 2. withdrawals: zero native credit, amount/32 in GNO
cat specs/execution/withdrawals.md
python3 - <<'PY'
import json,urllib.request
R="https://rpc.gnosischain.com"
def rpc(m,p):
    d=json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(R,d,{'content-type':'application/json'}),timeout=60))['result']
B=47884196; A="0x56cf0ff00fd6cfb23ce964c6338b228b0fa76640"
DC="0x0B98057eA310F4d31F2a452B414647007d1645d9"
blk=rpc("eth_getBlockByNumber",[hex(B),False])
tot=sum(int(w['amount'],16) for w in blk['withdrawals'])
nat=int(rpc("eth_getBalance",[A,hex(B)]),16)-int(rpc("eth_getBalance",[A,hex(B-1)]),16)
c="0xbe7ab51b"+A[2:].rjust(64,'0')          # withdrawableAmount(address)
gno=int(rpc("eth_call",[{"to":DC,"data":c},hex(B)]),16)-int(rpc("eth_call",[{"to":DC,"data":c},hex(B-1)]),16)
print("withdrawn Gwei",tot,"| native delta",nat,"| claimable delta",gno,"| /32 ==",tot*10**9//32==gno)
PY

# --- 3. system contracts: four identical, deposit moved, canonical empty
for a in 0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02 \
         0x0000F90827F1C53a10cb7A02335B175320002935 \
         0x00000961Ef480Eb55e80D19ad83579A64c007002 \
         0x0000BBdDc7CE488642fb579F8B00f3a590007251 \
         0x00000000219ab540356cBB839Cbe05303d7705Fa \
         0x0B98057eA310F4d31F2a452B414647007d1645d9; do
  printf '%s ' "$a"
  curl -s -X POST -H 'content-type: application/json' \
    --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$a\",\"$B\"]}" $R \
    | python3 -c "import sys,json;r=json.load(sys.stdin)['result'];print('len',(len(r)-2)//2)"
done
# compare the first four against a mainnet node at latest — expect byte equality

# --- 4. header shape: 21 items post-merge, 16 with a 65-byte seal pre-merge
for n in 0x2daa7a4 0x1312D00; do
  curl -s -X POST -H 'content-type: application/json' \
    --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"debug_getRawHeader\",\"params\":[\"$n\"]}" $R
  echo
done
sed -n '60,80p' nethermind/src/Nethermind/Nethermind.Serialization.Rlp/HeaderDecoder.cs

# --- 5. blob params: 1/2, 1 gwei floor, no BPO forks
cat reth_gnosis/src/blobs.rs
python3 -c "import json;d=json.load(open('nethermind/src/Nethermind/Chains/gnosis.json'));\
print(d['params']['blobSchedule'], d['params']['eip4844MinBlobGasPrice'])"
curl -s -X POST -H 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"eth_feeHistory","params":["0x14","0x2daa7a4",[]]}' $R

# --- 6. two bytecode-rewrite hard forks, live code == pinned spec
cat specs/execution/balancer_recovery.md
python3 - <<'PY'
import json,re,urllib.request
R="https://rpc.gnosischain.com"
def rpc(m,p):
    d=json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(R,d,{'content-type':'application/json'}),timeout=60))['result']
spec=open('specs/execution/balancer_recovery.md').read()
bc=re.search(r'`BALANCER_RESCUE_BYTECODE`\s*\|\s*`(0x[0-9a-fA-F]+)`',spec).group(1)
cs=json.load(open('nethermind/src/Nethermind/Chains/gnosis.json'))['engine']['authorityRound']['params']
print("balancer:", rpc("eth_getCode",["0x506d1f9efe24f0d47853adca907eb8d89ae03207","0x2daa7a4"]).lower()==bc.lower())
g=cs['rewriteBytecode']['21735000']['0xf8D1677c8a0c961938bf2f9aDc3F3CFDA759A9d9']
print("gip-31:  ", rpc("eth_getCode",["0xf8D1677c8a0c961938bf2f9aDc3F3CFDA759A9d9","0x2daa7a4"]).lower()==g.lower())
PY

# --- 7. fork schedule, from config not blog
grep -n 'Timestamp = 0x\|BlockNumber = ' \
  nethermind/src/Nethermind/Nethermind.Specs/GnosisSpecProvider.cs
python3 -c "import json;print(json.load(open('reth_gnosis/src/spec/chainspecs/gnosis.json'))['config'])"

# --- 8/9. EIP-170 late; the Gnosis-owned config repo is frozen pre-Merge
grep -n -A4 'EIP-170' specs/network-upgrades/shapella.md
python3 -c "import json;p=json.load(open('configs/mainnet/genesis.json'))['params'];\
print([k for k in p if 'Timestamp' in k or k=='terminalTotalDifficulty'])"   # -> []

# --- 10. AuRa objects across the merge
grep -n 'AddDecorator<IRewardCalculatorSource' \
  nethermind/src/Nethermind/Nethermind.Merge.Plugin/MergePlugin.cs      # in MergePluginModule
grep -n 'BaseMergePluginModule\|IRewardCalculatorSource' \
  nethermind/src/Nethermind/Nethermind.Merge.AuRa/AuRaMergePlugin.cs    # AuRa never adds it
sed -n '/public ITxFilter? CreateTxPermissionFilter/,/^        }/p' \
  nethermind/src/Nethermind/Nethermind.Consensus.AuRa/InitializationSteps/TxAuRaFilterBuilders.cs

# --- precompiles are native, and 0x0100 really verifies
for i in $(seq 1 17); do
  a=$(printf '0x%040x' $i)
  curl -s -X POST -H 'content-type: application/json' \
    --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$a\",\"$B\"]}" $R
  echo " $a"
done      # all 0x
curl -s -X POST -H 'content-type: application/json' --data '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x0000000000000000000000000000000000000100","data":"0x33e312814c04744566da589b441f5d193c7b8ac3cfcac66a125c8a6432416539f77f4c3c67be0834c8ba25d24157c68da61cb9aa1c4b634ceef8af33bf5063ad576a523698a72caa4b282a9a09791049c13012613db47705c53a1ab2ed1090006413e370318a922cecfaa94ba2188dd419f586356fa774c766cd6c450295fee95dce9ce0557b0a8f1cef5c663f362cfffc910e3094afc82bbbc7a0a92b0b6bdb"},"0x2daa7a4"]}' $R
# -> 0x00..01 (valid P-256 signature); flip one bit of s and it returns 0x
```
