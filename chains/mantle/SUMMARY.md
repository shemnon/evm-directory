# Mantle — findings

Chain id 5000. Client **`mantle-xyz/op-geth` v1.6.1** (`11fa8109…`), a rebase of
op-geth onto go-ethereum **v1.17.3**, with **`mantle-xyz/mantle-v2` v1.6.0**
(`710dbc40…`) as the companion for the consensus client, the fork registry and the
predeploy list. Baseline fork **osaka**. Live probes at block **99672064**
(`0x5f16800`) on `https://rpc.mantle.xyz`.

The prediction going in was: an OP Stack fork where MNT replaces ETH as the gas
token, a `tokenRatio` multiplier on gas, EigenDA instead of blobs, and an EVM
inherited wholesale. Three of those four are wrong or expired, and the ways they are
wrong are the findings.

---

## 1. Changing the gas asset required **no transaction type at all** — the cost landed on the deposit envelope instead

Mantle spends **zero** type bytes. `core/types/transaction.go` declares
`LegacyTxType` … `SetCodeTxType` and nothing else; there is no Mantle signer, no
Mantle sighash, no fork list over sender recovery. `tx_authorization.key_binding`
stays `derived` and `recoverPlain` is the only recovery path.

That is possible because **MNT *is* the native balance**. `buyGas`, `CanTransfer`,
the refund path and the 1559 burn are upstream geth's code operating on a different
asset; nothing in the client names MNT. This is the sharpest available contrast with
Celo, which reached a comparable goal — gas paid in a non-ETH asset — by spending
**two** type bytes (`0x7b`, `0x7c`), adding a `FeeCurrency` field inside the sighash,
and adding a fifth consensus field to the receipt. Celo changed the *fee currency*
and had to change the envelope. Mantle changed the *native* asset and did not.

The cost surfaced on the other side of the bridge. ETH is demoted to an ERC-20, and
the OP Stack deposit type `0x7e` grew two fields to move it
(`core/types/deposit_tx.go:DepositTx`):

```
OP Stack : SourceHash From To Mint Value Gas IsSystemTransaction Data
Mantle   : SourceHash From To Mint Value Gas IsSystemTransaction EthValue Data EthTxValue
```

`EthValue` is **inserted at RLP position 7**, exactly where an OP Stack decoder
expects `Data`; `EthTxValue` is `rlp:"optional"` on the end. On the wire this fails
loudly (ten elements where eight are expected). In JSON it does not: the live block
shows `"ethValue": "0x0"` on the L1-attributes deposit, a key OP tooling silently
drops — and the value it drops is a mint of a different asset.

Recorded as an **override** of the op-stack row's `0x7e` entry.
`0x7d` (`PostExecTx`), which the op-stack row leaves `unrecorded`, is settled here by
absence: there is no `post_exec_tx.go` in this tree at all.

## 2. `tokenRatio` is contract storage, and it stopped scaling gas *units* on 2026-04-22

`TokenRatioSlot = common.BigToHash(big.NewInt(0))` at `GasOracleAddr =
0x42…000F` — **slot 0 of the OP Stack GasPriceOracle predeploy**, an address OP
Stack uses for something else entirely. It is read with `GetState` in six places:
the state transition, the state processor, the txpool validator, `simulate.go`, the
preconf checker and the L1 cost function. It is not config and not a fork constant:
**governance can move Mantle's fee schedule with no client release and no fork.**
Live value `0x12b5` (4789) at the probed block; `0x12aa` (4778) in the receipt of a
transaction 0x100 blocks earlier. It moves continuously.

Where it enters depends on the era, and the brief's premise describes the era that
just ended:

* **Before Arsia** it multiplied *gas units*: `cost.RegularGas *= tokenRatio`, the
  EIP-7623 floor `floorDataGas *= tokenRatio`, the remaining budget
  `st.gasRemaining.RegularGas /= tokenRatio`, and the refund path had to undo it
  (`calcRefundPreArsia`, `originalGasUsed`). Mantle's historical `gasUsed` figures
  are therefore **not in the same unit** as any other chain's, and `eth_estimateGas`
  returned a scaled number.
* **From Arsia** (`1776841200`, 2026-04-22) every one of those sites is guarded by
  `!rules.IsMantleArsia`. Gas accounting is mainnet's, and `eth_estimateGas` returns
  ordinary gas units — the estimator has no `tokenRatio` in it at all.
* **What survives** is the L1 data fee: `NewL1CostFuncArsia` computes the standard
  Fjord cost and multiplies by a `tokenRatio` **re-read from state per transaction**,
  with the source explaining why — *"because after setting the token ratio in the gas
  oracle, it needs to be updated in the rest of txs of the block"*. One transaction
  in a block can change what every later transaction in the same block pays.

It also appears on the receipt as a `tokenRatio` field — but in
`storedReceiptRLP` with `rlp:"optional"`, **not** in `receiptRLP`. Unlike Celo's
CIP-66 base fee, it is outside `receiptsRoot`: RPC surface, not consensus.

## 3. Mantle carries **none** of OP Stack's six precompile divergences — a descendant more mainnet-equivalent than its ancestor

The op-stack row's headline is "zero custom addresses, six divergent precompiles".
On Mantle the second half is false. `PrecompiledContractsMantleArsia =
PrecompiledContractsMantleLimb` is **membership- and semantics-identical to
`PrecompiledContractsOsaka`**:

| address | OP Stack | Mantle (Limb/Arsia) |
|---|---|---|
| `0x05` MODEXP | no 7823 bounds, no 7883 pricing | `bigModExp{eip2565, eip7823, eip7883}` — mainnet Osaka |
| `0x08` BN256_PAIRING | capped 81984 B | `bn256PairingIstanbul` — uncapped |
| `0x0c` / `0x0e` / `0x0f` BLS12-381 | capped | uncapped |
| `0x0100` P256VERIFY | 3450 gas | `P256VerifyGas` = **6900**, mainnet's EIP-7951 price |

The mechanism is **deletion, not override**: there is no
`PrecompiledContractsFjord/Granite/Isthmus/Jovian` in this tree, so
`activePrecompiledContracts` has no OP branch left to shadow the Ethereum ones. The
input-cap constants still exist in `params/optimism_features.go` and nothing reads
them. This is the precise inverse of the op-stack gotcha that `IsOptimismJovian` is
tested before `IsOsaka`.

Consequence for the dataset: resolving `ethereum → op-stack → mantle` and keeping the
ancestor's precompile deltas is **wrong six times**. Five of the six are recorded here
as explicit `inherited` overrides so the inheritance does not carry them through.
`0x0100` returns `0x` to `eth_getCode` — native, not a predeploy.

## 4. `sync_point`: Mantle **breaks** the "derivatives lag the stack row" pattern

opBNB is frozen three fork generations back; Celo stops at Jovian and Prague. Mantle
is on **geth v1.17.3** against the op-stack row's v1.17.5 — two patch releases, not
fork generations — and reaches **Osaka**, established behaviourally: `CLZ` (EIP-7939)
returns `0xf8` for `CLZ(0xff)` in `eth_call`, while an undefined opcode in the same
probe fails with `invalid opcode`. Its header struct even carries EIP-7928
`BlockAccessListHash` and EIP-7843 `SlotNumber`, which the op-stack row records as
*absent* from its pinned op-geth.

On the OP axis the comparison does not apply, because **Mantle does not run OP's fork
ladder**. `params/config.go` still declares `CanyonTime … JovianTime`, but nothing in
`core/vm` or the fee path reads them. The companion repo states the collapse in one
function — `ForkToMantleFork` maps **Canyon, Delta, Ecotone, Fjord, Granite,
Holocene, Isthmus and Jovian all onto the single Mantle fork Arsia**, Bedrock and
Regolith onto Skadi, and **Interop onto `MantleNoSupport`**. Eight OP forks, one
Mantle fork, one date.

Related: op-geth's `CheckConfigForkOrder` — which the op-stack row credits with
*enforcing* `ShanghaiTime == CanyonTime` and `PragueTime == IsthmusTime`, making the
fork mapping a verified fact — contains **no OP forks at all** here and returns `nil`
for any chain with `Optimism != nil`. On Mantle the Ethereum↔Mantle fork
correspondence is a claim in a Go comment (`MantleLimbTime` — *"ensuring osaka
upgrade"*), not something the client refuses to start over.

## 5. There was no base fee market until 2026-04-22

`CalcBaseFee` returns `parent.BaseFee` **verbatim** when `IsMantleBaseFee` is on and
`IsMantleArsia` is not, and `VerifyEIP1559Header` **skips the base-fee check
entirely** on the same condition. `miner/worker.go` takes `genParams.baseFee`
straight from the payload attributes. For its first three and a half years, Mantle's
`baseFeePerGas` was a number the sequencer chose, unvalidated by consensus.

Arsia turns on the real thing: the check is enforced, the 1559 parameters move into
`extraData` as a 17-byte MinBaseFee-versioned Holocene record, and the base fee is
metered against `max(parent.GasUsed, *parent.BlobGasUsed)` — where `blobGasUsed`
holds the DA footprint. Live: `extraData 0x0100000032000000040000000ba43b7400` →
denominator 50, elasticity 4, minBaseFee 50 gwei; `baseFeePerGas` is exactly 50 gwei,
i.e. **pinned at its floor**. `extraData` is consensus-checked in both directions —
required *empty* before Arsia, required to be exactly this record after.

## 6. A retired feature left a permanently forbidden 32-byte calldata prefix

MetaTx was a real **two-signer** scheme with no envelope footprint. Any type-`0x02`
transaction whose `data` began with the 32-byte constant `MetaTxPrefix`
(`…4D616E746C654D6574615478507265666978`, ASCII `MantleMetaTxPrefix`) was re-read:
the remainder RLP-decoded into `MetaTxParams{ExpireHeight, SponsorPercent, Payload,
GasFeeSponsor, V, R, S}`, `checkSponsorSignature` recovered a **second** secp256k1
address over a Mantle-specific digest (`MetaTxSignDataV2`, binding sender, chain id,
nonce, fee caps and sponsor percent), `buyGas` debited that share of the gas cost
from the **sponsor**, and `st.msg.Data` was rewritten to the inner `Payload`. Two
parties, two digests, one type byte — the second signature lived where an indexer
expects ABI arguments.

Everest (2025-03-19) disabled it. But the ban is enforced at **two different scopes**:

* at consensus, `DecodeAndVerifyMetaTxParams` returns `ErrMetaTxDisabled` only for
  type `0x02`;
* at the mempool and over RPC, `core/txpool/validation.go` and
  `internal/ethapi/api.go` both call `MetaTxCheck(tx.Data())`, which checks **every
  type byte**, on raw calldata, forever.

Confirmed live: `eth_estimateGas` with calldata beginning with the prefix returns
`meta tx is disabled`; the same call with the **last prefix byte changed** proceeds
to an ordinary execution revert. Those 32 bytes are unusable as a calldata prefix on
Mantle for all time, and the error message will mean nothing to whoever hits it.

## 7. BVM_ETH's balances change without its code running

ETH lives at `0xdEAddEaDdeadDEadDEADDEAddEADDEAddead1111` as an ERC-20 (`symbol()`
returns `"WETH"`, 3.5 KB of bytecode). The client **does not call it**.
`mintBVMETH`/`transferBVMETH` compute `keccak(pad32(addr) ‖ pad32(0))` for the
`balanceOf` mapping and slot 2 for `totalSupply`, write them with
`st.state.SetState`, and then **fabricate** the matching
`Transfer(address,address,uint256)` and `Mint(address,uint256)` logs with
`StateDB.AddLog`.

So any transfer hook, pause flag, allowance check or transfer restriction in that
token is bypassed on the deposit path, and no `CALL` frame appears in a trace. A
balance reconstructed from `Transfer` events happens to stay right — because the
client forges the events too — but a balance reconstructed by *simulating the token's
code* does not.

A smaller sibling: from the ProxyOwner upgrade the client force-writes slot 0 of the
ProxyAdmin predeploy `0x42…0018` to a fixed address at the top of **every** state
transition — not once at a fork boundary. Any change to the L2 ProxyAdmin owner is
silently reverted by the next transaction executed.

## 8. EigenDA is no longer a client divergence, and three OP predeploys are tombstoned

The EigenDA expectation has expired. `op-node/rollup/types.go` still declares
`MantleDaSwitch` and `DataLayrServiceManagerAddr` — under a comment reading
**"Mantle features: Legacy fields"** — and a repo-wide grep finds **no reader for
either**. The live path is upstream OP's `op-alt-da` with a `GenericCommitment` (the
same abstraction Celo uses), fed by the separate `mantle-xyz/eigenda-proxy` sidecar.
The execution layer sees nothing of it.

What the EL *does* see is Arsia's DA footprint, which is OP Jovian's mechanism on a
Mantle fork gate: `blobGasUsed` carries the block's DA footprint (`0xa0f0` in a
two-transaction block, `excessBlobGas 0x0`) and, unlike on OP, that number **drives
the base fee** through `CalcBaseFee`. Mantle's L1-attributes selector is its own —
`0x49e72383`, `setL1BlockValuesArsia()` — and `ExtractDAFootprintGasScalar` rejects
any other selector, so an OP Jovian attributes transaction is not decodable here and
vice versa. The per-block scalar is read from the last two bytes of that calldata
(`0x0190` = 400 live).

Finally, Mantle's `Predeploys.sol` declares **twenty** entries where op-stack's has
thirty. `0x42…0020` (SchemaRegistry), `0x42…0021` (EAS) and `0x42…0022`
(CrossL2Inbox) hold proxies with **no implementation** and revert with
`Proxy: implementation not initialized` — `tombstoned`, not `removed`: an absent
address returns success with empty output, these revert. For `0x42…0022` the fork
registry says why in one line: `Interop → MantleNoSupport`.

---

## Not established here

* **`eips.7702`** — `unrecorded`. `SetCodeTx` `0x04` is decoded and
  `applyAuthorization` runs under `rules.IsPrague`, but no source read was done on
  how a 7702 delegation interacts with the pre-Arsia gas rescaling or with the
  removed MetaTx path.
* **The live DA backend.** Neither clone contains a mainnet `rollup.json`, so which
  alt-DA commitment Mantle mainnet actually posts today rests on the code path being
  the generic one, not on a config read. `eigenda-proxy` under `mantle-xyz` was last
  pushed 2025-02.
* **The `preconf/` package.** The client carries a preconfirmation FIFO tx set,
  preconf deposit sources, a preconf miner config and a separate
  `miner/preconf_checker.go` that upstream op-geth does not have. Not exercised; its
  consensus effect is unrecorded.
* **`v1.6.1` has no GitHub Release.** The newest published Release is `v1.5.5`
  (2026-04-21). `v1.6.1` is pinned anyway because `web3_clientVersion` on the public
  RPC returns `Geth/v1.17.3-stable-11fa8109/…` — the running network *is* this
  build. That is a stronger pin than a release tag, but it is a deviation from the
  method and is called out here rather than hidden.
* **No precompile extractor** exists for this row, so `verify.py` reports
  `! NO EXTRACTOR` and the precompile list is taken on trust from
  `core/vm/contracts.go`.
* **Pre-Everest history.** Whether any MetaTx transaction is actually present in
  Mantle's chain history was not measured; the scheme is recorded from source and
  from its live rejection, not from a historical census.

## Contradicts existing claims

* **README.md, "Runs the OP Stack constrains almost nothing"** — this row supplies
  the missing direction. Base *adds* to the stack; opBNB *lags* it; Mantle
  **subtracts** from it, reverting all six of OP Stack's precompile divergences back
  to mainnet.
* **`chains/op-stack/chain.yaml` precompiles `0x05`, `0x08`, `0x0c`, `0x0e`, `0x0f`,
  `0x0100`** — all six inherited as `modified`; all six overridden to `inherited`
  here.
* **`chains/op-stack/chain.yaml` `tx_types."0x7d"` (`unrecorded`)** — settled as
  `removed` for Mantle: the type does not exist in this tree.
* **`chains/op-stack/chain.yaml` forks note** — "CheckConfigForkOrder ENFORCES
  equality … this makes the fork mapping a verified fact" is **not** true of Mantle's
  op-geth, which has no OP forks in that function.
* **SCHEMA.md's `sync_point` caveat** ("a descendant pinned to an older client
  inherits the ancestor's past") holds for opBNB and Celo but **not** for Mantle,
  which inherits its ancestor's *present* on the Ethereum axis and none of it on the
  OP axis.

---

## Re-verify

```sh
cd /Volumes/TendiesTown/EVM-intel
G=chains/mantle/repos/op-geth
V=chains/mantle/repos/mantle-v2

# --- pins -------------------------------------------------------------------
git clone --quiet --depth 1 --branch v1.6.1 --single-branch \
  https://github.com/mantle-xyz/op-geth $G
git clone --quiet --depth 1 --branch v1.6.0 --single-branch \
  https://github.com/mantle-xyz/mantle-v2 $V
git -C $G rev-parse HEAD    # 11fa8109ad7eb177c05c4007f0bd410b93edcbdb
git -C $V rev-parse HEAD    # 710dbc40b295a93e0c7eb474615faa1c3b8ae368
sed -n '18,25p' $G/version/version.go                  # geth Major 1 Minor 17 Patch 3

# the org moved: mantlenetworkio -> mantle-xyz (301)
curl -sL https://api.github.com/repos/mantlenetworkio/op-geth | grep '"full_name"'

# 1 — no added type bytes; deposit envelope grew two fields
sed -n '/^const (/,/^)/p' $G/core/types/transaction.go   # 0x00..0x04 only
sed -n '29,50p' $G/core/types/deposit_tx.go              # EthValue at position 7
ls $G/core/types/ | grep -c post_exec                    # 0 -> no 0x7d

# 2 — tokenRatio: slot 0 of the GasPriceOracle predeploy, read from state
grep -n 'TokenRatioSlot\|GasOracleAddr' $G/core/types/rollup_cost.go | head -3
grep -rn 'GetState(types.GasOracleAddr, types.TokenRatioSlot)' $G --include='*.go' | grep -v _test
grep -n 'tokenRatio' $G/core/state_transition.go         # all sites !rules.IsMantleArsia
grep -n 'NewL1CostFuncArsia' -A 10 $G/core/types/rollup_cost.go
grep -n 'TokenRatio' $G/core/types/receipt.go            # line 154: storedReceiptRLP only

# 3 — precompiles are mainnet Osaka's, not OP Stack's
sed -n '214,237p' $G/core/vm/contracts.go                # MantleLimb == Osaka map
sed -n '288,300p' $G/core/vm/contracts.go                # no Fjord/Granite/Jovian branch
grep -c 'PrecompiledContractsJovian\|PrecompiledContractsGranite' $G/core/vm/contracts.go   # 0
grep -n 'P256VerifyGas ' $G/params/protocol_params.go    # 6900

# 4 — one fork axis; eight OP forks collapse onto Arsia
grep -n 'ForkToMantleFork' -A 10 $V/op-core/forks/mantle_forks.go
sed -n '1132,1145p' $G/params/config.go                  # CheckConfigForkOrder: no OP forks
sed -n '15,30p'    $G/params/mantle.go                   # mainnet fork timestamps

# 5 — no base fee market before Arsia
sed -n '65,95p' $G/consensus/misc/eip1559/eip1559.go
sed -n '30,63p' $G/consensus/misc/eip1559/eip1559.go     # VerifyEIP1559Header
grep -n 'extraData must be empty before Arsia' $G/consensus/misc/eip1559/eip1559_optimism.go

# 6 — MetaTx: second signer, then a banned calldata prefix
sed -n '122,175p' $G/core/types/meta_transaction.go
grep -rn 'MetaTxCheck' $G --include='*.go' | grep -v _test   # txpool + ethapi, all types

# 7 — BVM_ETH written by the client, logs fabricated
sed -n '1258,1300p' $G/core/state_transition.go
sed -n '1345,1380p' $G/core/state_transition.go

# 8 — EigenDA fields are dead; predeploy list is 20 long
grep -rn 'MantleDaSwitch\|DataLayrServiceManagerAddr' $V --include='*.go'   # declared, never read
grep -c 'address internal constant' $V/packages/contracts-bedrock/src/libraries/Predeploys.sol   # 20

# --- live, all at block 0x5f16800 (99672064) --------------------------------
RPC=https://rpc.mantle.xyz
P() { curl -s -X POST $RPC -H 'content-type: application/json' -d "$1"; echo; }

# the pinned tree IS the running build
P '{"jsonrpc":"2.0","id":1,"method":"web3_clientVersion","params":[]}'
# -> Geth/v1.17.3-stable-11fa8109/linux-amd64/go1.26.6
P '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}'          # 0x1388

# header: DA footprint in blobGasUsed, 17-byte 1559 extraData, ethValue on the 0x7e
P '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["0x5f16800",true]}'
# -> blobGasUsed 0xa0f0, excessBlobGas 0x0,
#    extraData 0x0100000032000000040000000ba43b7400, baseFeePerGas 0xba43b7400,
#    tx[0] type 0x7e with "ethValue":"0x0", input starting 0x49e72383 ending 0x0190

# receipt: tokenRatio + daFootprintGasScalar are RPC fields
P '{"jsonrpc":"2.0","id":1,"method":"eth_getTransactionReceipt","params":["0x182caf2e5f9d612656f6646ad9e99996a25a4a3730424900543e5894fb2a19fd"]}'
# -> tokenRatio 0x12aa, daFootprintGasScalar 0x190, operatorFeeScalar 0x5f5e100

# tokenRatio lives in contract storage
P '{"jsonrpc":"2.0","id":1,"method":"eth_getStorageAt","params":["0x420000000000000000000000000000000000000F","0x0","0x5f16800"]}'
# -> 0x…12b5 (4789)

# baseline = Osaka: CLZ (EIP-7939) executes, an undefined opcode does not
P '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"input":"0x60ff1e60005260206000f3"},"0x5f16800"]}'   # 0x…f8
P '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"input":"0x60ff0c60005260206000f3"},"0x5f16800"]}'   # invalid opcode

# 0x0100 is native, not a predeploy
P '{"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":["0x0000000000000000000000000000000000000100","0x5f16800"]}'   # 0x

# BVM_ETH is a real ERC-20 called WETH
P '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0xdEAddEaDdeadDEadDEADDEAddEADDEAddead1111","data":"0x95d89b41"},"0x5f16800"]}'   # "WETH"

# the banned calldata prefix, and the control that differs by one byte
PFX=0x00000000000000000000000000004D616E746C654D6574615478507265666978
P "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_estimateGas\",\"params\":[{\"to\":\"0x4200000000000000000000000000000000000015\",\"input\":\"${PFX}deadbeef\"},\"0x5f16800\"]}"
# -> "meta tx is disabled"
P '{"jsonrpc":"2.0","id":1,"method":"eth_estimateGas","params":[{"to":"0x4200000000000000000000000000000000000015","input":"0x00000000000000000000000000004D616E746C654D6574615478507265666979deadbeef"},"0x5f16800"]}'
# -> ordinary "execution reverted"

# three OP predeploys: present, callable, empty
for a in 0x4200000000000000000000000000000000000020 \
         0x4200000000000000000000000000000000000021 \
         0x4200000000000000000000000000000000000022; do
  P "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"$a\",\"data\":\"0x54fd4d50\"},\"0x5f16800\"]}"
done
# -> execution reverted: Proxy: implementation not initialized

# --- the row itself ---------------------------------------------------------
tools/.venv/bin/python tools/verify.py 2>&1 | sed -n '/^mantle/,/^$/p'
# mantle  (op-geth (Mantle fork) v1.6.1)
#   pin ok  11fa8109
#   ! NO EXTRACTOR — precompile list NOT cross-checked against source
#   citations ok    53 symbol(s) confirmed, 0 line ref(s) in range
```
