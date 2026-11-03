# Cronos — findings

Chain ID 25. Client `crypto-org-chain/cronos` **v1.8.1** @ `616274a7`, with one pinned
companion, `crypto-org-chain/ethermint` @ `e874216e` — the go.mod replace target that
holds the EVM. Baseline fork **osaka**. Live probes at block **103699610**
(`0x589966d`) on `https://evm.cronos.org`.

`web3_clientVersion` returns `Version dev ()` with an empty commit stamp, so the pin
cannot be confirmed from the RPC. Fork level was established by capability probe
instead (§4).

---

## 1. The framework row does not absorb it — the premise was wrong

CANDIDATES.md's framework table lists Cronos under `cosmos-evm`. It does not belong
there.

```
$ grep -c cosmos/evm chains/cronos/repos/cronos/go.mod chains/cronos/repos/cronos/go.sum
0
0
```

Cronos imports `github.com/evmos/ethermint/x/evm` and `.../x/feemarket`, replaced onto
`crypto-org-chain/ethermint`, and replaces go-ethereum itself onto
`crypto-org-chain/go-ethereum v1.10.20-0.20250815065500-a4fbafcae0dd`. cosmos/evm's
EVM module is `x/vm`, not `x/evm`; its geth is `cosmos/go-ethereum v1.17.2-cosmos-0`.

Both trees descend from Evmos's Ethermint, but Cronos forked before the donation to
the Cosmos SDK org and has carried its own copy since. That is the third proposed
framework relationship in this dataset to fail on inspection — after Frontier/Moonbeam
and Polygon CDK — and it fails the *first* way: the code was forked per chain.

Four differences that are measurable rather than nominal:

| | cosmos-evm | Cronos |
|---|---|---|
| EVM module | `x/vm` | `x/evm` (Ethermint) |
| geth | `cosmos/go-ethereum v1.17.2-cosmos-0` | `crypto-org-chain/go-ethereum` @ `a4fbafca` |
| module precompiles | `0x0400`, `0x0800`–`0x0807` | `0x64`, `0x65`, `0x66` — and off (§2) |
| tx-type allowlist | `ante/evm/mono_decorator.go:AcceptedTxType` | **none** (§3) |

`role: fork` with `upstream: cosmos-evm` keeps the shared Ethermint ancestry visible in
LINEAGE.md, exactly as Injective and Artela do, while the `sync_point` says what the
edge does and does not mean.

## 2. Its three custom precompiles are defined and not registered

`x/cronos/keeper/precompiles/` implements a Bank precompile at
`common.BytesToAddress([]byte{100})` = `0x64`, a Relayer at `0x65` and an ICA at
`0x66`. The Bank one is the interesting piece of code — `mint(address,uint256)` and
`burn` over Cosmos bank denominations in an `evm/<caller>` namespace, flat 200,000
gas — a precompile that would let any contract mint unbounded supply of its own
namespaced Cosmos denom.

It is not wired up. The registration path in this fork is the `CustomContractFn` slice
handed to the EVM keeper, and there is exactly one occurrence of that type in the
repository:

```go
// app/app.go:803
[]evmkeeper.CustomContractFn{},
```

Empty. Confirmed live: `eth_getCode` on `0x64`, `0x65` and `0x66` all return `0x`, and
an `eth_call` to `0x64` succeeds with empty output — the signature of an empty
account, not of a precompile that rejected the input.

**So a survey that greps for precompile address constants reports three custom
precompiles on Cronos, and the chain has zero.** This is the mirror image of Flare,
where the predicted custom precompiles turned out to be system contracts with real
bytecode; here they are neither.

The row records all three as `status: removed` with the constant cited, rather than
omitting them, because the constant is what a reader will find and the absence is the
finding. `tools/verify.py`'s extractor asserts the registration site rather than the
address list: it raises if the slice ever stops being empty.

## 3. There is no transaction-type allowlist

cosmos-evm's row cites `AcceptedTxType`, which ORs in `0x00`/`0x01`/`0x02`/`0x04` and
lets geth's txpool validator reject anything else. In this fork:

```
$ grep -rn AcceptedTxType chains/cronos/repos/ethermint --include=*.go
$
```

`EthereumTx.Validate` checks the gas limit and the bit-lengths of the fee fields, and
nothing about the type. `MsgEthereumTx.ValidateBasic` rejects the four deprecated
protobuf fields and requires `Raw` + `From`, again with no type check.

What happens to a blob transaction end to end is therefore **not established**, and
the row says so: `tx_types."0x03"` is `status: unrecorded` with a note stating exactly
what was and was not looked at. Establishing it would mean submitting a blob
transaction to a live mainnet, which this pass does not do. The legacy converter
`NewTxDataFromTx` *would* fall a type-`0x03` transaction through to `newLegacyTx`, but
that function is not on the accepted path — `AsTransaction()` carries the raw geth
transaction — so the tempting conclusion is unsupported and is not drawn.

This is the distinction SCHEMA.md draws between `removed` and `unrecorded`: "we found
no rejection" and "the chain rejects it" are different claims.

## 4. Osaka arrived with v1.8, and the header stopped being evidence

The fork schedule is a `ChainConfig` parameter in module state, changeable by governance
without a client release. Before v1.8 `EthereumConfig` had no `OsakaTime` field, so Osaka
could not be scheduled at all. Ethermint's `migrations/v8` now sets it to 0, and governance
proposal 30 ran that at block **101485000** (2026-10-22 07:52:24 UTC).

Time 0 would suggest Osaka had always been on, so the fork is dated by differential:

| probe | block 101484999 | block 101485000 |
|---|---|---|
| CLZ, `eth_call 0x60015f1e5f5260205ff3` | error | `0x…0100` |
| `osaka_time` in `/ethermint/evm/v1/params` | absent | `0` |

At the head, `0x0100` verifies a valid P-256 vector and MODEXP rejects inputs over 1024
bytes.

**One conflict is open.** `CheckMaxTxGas` enforces the 16,777,216 EIP-7825 cap whenever Osaka
rules apply. The project's migration guide says the cap is "not at the upgrade height" and
"needs a separate governance change". Testing it means submitting a transaction to mainnet,
so `eips.7825` stays `unrecorded`.

**The header cannot date anything.** This row used to record `withdrawalsRoot`,
`blobGasUsed`, `excessBlobGas`, `parentBeaconBlockRoot` and `requestsHash` as absent at block
92902237. That same block now returns all five. The chain did not rewrite history; the RPC
renders blocks differently. The values are constants: `parentBeaconBlockRoot` is the
empty-trie root on a chain with no beacon chain, and `requestsHash` is the SHA-256 of nothing.

v1.8 also removed Interchain Accounts and limited `SendCroToIbc` to two authorized contracts.
Its release notes say libp2p replaced the legacy networking stack, but the CometBFT fork's
config calls it experimental and opt-in, and what mainnet validators run was not established.

## 5. What is inherited and deliberately not restated

The Cosmos-EVM shape — the `MsgEthereumTx` protobuf wrapper, the fact that CometBFT
orders protobuf rather than EIP-2718 envelopes, the dual address space, the fabricated
Ethereum block — is stated in full on `chains/cosmos-evm/` and is not duplicated here.
What Cronos adds to that axis is `x/cronos`'s CRC-20 conversion messages, which mint
and burn ERC-20 balances from a Cosmos message.

The four preinstalls (Create2 deployer, Multicall3, Permit2, Safe singleton factory)
are byte-identical to cosmos-evm's at the same addresses, in a fork that shares no
module path with it — convergent porting, not shared code.

---

## Re-verify

```bash
R=https://evm.cronos.org
B=0x62e549a     # 103699610
C=chains/cronos/repos/cronos
E=chains/cronos/repos/ethermint

# F1: not cosmos/evm
grep -c 'cosmos/evm' $C/go.mod $C/go.sum          # 0 0
grep -n 'evmos/ethermint\|crypto-org-chain/go-ethereum\|crypto-org-chain/ethermint' $C/go.mod
grep -n 'evmos/ethermint' $C/app/app.go | head
ls $E/x/                                          # x/evm, x/feemarket — not x/vm

# F2: the precompiles are defined and NOT registered
grep -rn 'BytesToAddress(\[\]byte{10[012]})' $C/x/cronos/keeper/precompiles/
sed -n '99,140p' $C/x/cronos/keeper/precompiles/bank.go
grep -rn 'CustomContractFn' $C --include=*.go     # the registration site is app/app.go:803
sed -n '643,652p' $C/app/app.go
for a in 64 65 66; do
  printf '0x%s code -> ' $a
  curl -s -X POST $R -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x00000000000000000000000000000000000000$a\",\"$B\"]}"
  echo
done                                              # all 0x

# F3: no tx-type allowlist
grep -rn 'AcceptedTxType' $E --include=*.go       # nothing
sed -n '74,102p' $E/x/evm/types/eth.go
sed -n '159,186p' $E/x/evm/types/msg.go
grep -n 'AcceptedTxType' chains/cosmos-evm/repos/*/ante/evm/mono_decorator.go   # the contrast

# F4: fork level by probe, and the header that disagrees
grep -n 'func (cc ChainConfig) EthereumConfig' -A28 $E/x/evm/types/chain_config.go
for p in '{"to":"0x000000000000000000000000000000000000000a","data":"0x00"}' \
         '{"to":"0x000000000000000000000000000000000000000b","data":"0x00"}' \
         '{"data":"0x60015f1e5f5260205ff3"}' \
         '{"data":"0x60ff5f5260015f60015e60205ff3"}'; do
  curl -s -X POST $R -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[$p,\"latest\"]}"; echo
done
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x0000F90827F1C53a10cb7A02335B175320002935\",\"latest\"]}" | head -c 60
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"latest\",false]}" \
  | python3 -c 'import sys,json;print(sorted(json.load(sys.stdin)["result"]))'

# F5: the preinstalls
sed -n '13,35p' $E/x/evm/types/preinstall.go

# row check
tools/.venv/bin/python tools/verify.py cronos
```
