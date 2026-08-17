# Kaia (formerly Klaytn)

**Client:** `kaiachain/kaia` `v2.2.2` (`ac7c81f3`), Go — a go-ethereum fork
**Chain ID:** 8217 · **Baseline:** Osaka (live) · **Live probes:** block `224632605`

Kaia's EVM is one of the most faithful in this dataset: every mainnet precompile
`0x01`–`0x11` is present and unmodified at Osaka, `bigModExp{eip2565, eip7823, eip7883}`
all true, no input caps, no repricing, no custom opcodes. **Every divergence is above
the interpreter** — in the transaction envelope, the account model, the header, and a
second metering axis that has no mainnet analogue.

Note the tag is annotated, so the tag object (`801b68b0`) and the commit (`ac7c81f3`)
differ. The commit is what is pinned. `v3.0.0-rc.1/rc.2` exist upstream but are
pre-release.

---

## The tx type space, enumerated exhaustively

Not read off documentation — enumerated from the pinned source by iterating
`TxType` over `0x0000`–`0x7810`, calling `String()` and `NewTxInternalData()` on each
(command in the re-verify section). The layout is `iota << 3` with `+1` = fee-delegated
and `+2` = fee-delegated-with-ratio, so each family occupies a three-slot lane.

| byte | name | constructible |
|---|---|---|
| `0x00` | TxTypeLegacyTransaction | yes (no type prefix on the wire) |
| `0x08` `0x09` `0x0a` | ValueTransfer / FeeDelegated / …WithRatio | yes |
| `0x10` `0x11` `0x12` | ValueTransferMemo / FD / …WithRatio | yes |
| `0x18` | **TxTypeAccountCreation** | **NO — tombstoned** |
| `0x20` `0x21` `0x22` | AccountUpdate / FD / …WithRatio | yes |
| `0x28` `0x29` `0x2a` | SmartContractDeploy / FD / …WithRatio | yes |
| `0x30` `0x31` `0x32` | SmartContractExecution / FD / …WithRatio | yes |
| `0x38` `0x39` `0x3a` | Cancel / FD / …WithRatio | yes |
| `0x40` | **TxTypeBatch** | **NO — tombstoned** |
| `0x48` `0x49` `0x4a` | ChainDataAnchoring / FD / …WithRatio | yes |
| `0x78` | **EthereumTxTypeEnvelope** | prefix, not a type |
| `0x7801`–`0x7804` | EthereumAccessList / DynamicFee / Blob / SetCode | yes |

`0x18` and `0x40` are **permanently consumed**: both are named by the enum and by
`String()`, and `NewTxInternalData` has no live case for either — the `0x18` case is
literally commented out and `tx_internal_data_account_creation.go` is still in the
tree. Recorded as `tombstoned`.

### Three structural breaks

**(1) The type is a `uint16`, not a byte.** `type TxType uint16`. `0x7801`–`0x7804`
do not fit in a byte. Kaia's own JSON output calls the field `typeInt`.

**(2) The envelope is EIP-2718-*shaped* but is not EIP-2718.** A Kaia typed
transaction is `rlp(uint16 type) || rlp(body)`. An **Ethereum** typed transaction is
re-wrapped as **`0x78 || <ethType> || rlp(body)`** when stored and gossiped
(`tx_internal_data_serializer.go:EncodeRLP`). The `eth_` RPC namespace strips the `0x78`
on the way out and prepends it on the way in (`api/api_eth.go`), so
`eth_sendRawTransaction` and `eth_getRawTransactionByHash` look completely standard
while the consensus encoding is not. Anything reading block bodies, p2p traffic or the
`kaia_` namespace sees the prefix.

`0x78` also **collides with Arbitrum's `ArbitrumDepositTxType`** — the third
same-byte collision in this dataset between chains with no shared code.

**(3) The sender is a field, not a recovery.** Every Kaia-native type carries an
explicit `from`. `Transaction.ValidateSender` does *not* ecrecover an address and
compare it: it recovers **public keys** and asks whether they satisfy the `AccountKey`
registered on-chain for the declared `from`. `ecrecover(sig) == from` is **false** for
well-formed Kaia transactions.

## How a two-signer transaction is actually encoded

Answering the question directly, for `0x09` FeeDelegatedValueTransfer:

```
0x09 || rlp([ nonce, gasPrice, gas, to, value, from,
              txSignatures,          # LIST of (v,r,s) — multisig
              feePayer,
              feePayerSignatures ])  # LIST of (v,r,s) — multisig
```

Both signature fields are **lists of triples**, not single triples, because either
party may be a weighted-multisig account. The two parties sign **different digests over
the same body**:

```
inner      = rlp([ type, nonce, gasPrice, gas, to, value, from ])
sender     = keccak( rlp([ inner, chainId, 0, 0 ]) )
fee payer  = keccak( rlp([ inner, feePayer, chainId, 0, 0 ]) )
```

The fee payer's digest commits to **its own address**, so a fee-payer signature cannot
be lifted onto a different transaction or a different payer.

This produces **three distinct hashes per transaction**:

- `Hash()` — the canonical Kaia hash
- `SenderTxHash()` — the body *without* the fee payer's address and signature; this is
  what the sender knows before a payer exists, and the only handle it has on a
  transaction it signed but did not broadcast
- `EthTxHash()` — for `0x78`-wrapped types, the hash *without* the `0x78` prefix, so
  Ethereum tooling agrees with the chain

A transaction-tracking system keyed on one of the three will lose transactions.

## Account keys decouple keys from addresses — and can lock out Ethereum tooling

Six `AccountKeyType` values (`account_key.go`): `Nil`, `Legacy`, `Public`, **`Fail`**,
`WeightedMultiSig`, `RoleBased`. `RoleBased` splits an account into three independent
keys by role: `RoleTransaction`, `RoleAccountUpdate`, `RoleFeePayer`.

The integrator-breaking consequence:

> **Ethereum-format transactions — legacy *and* `0x78`-wrapped typed, including
> EIP-7702 `SetCode` — are only executable if the sender's `AccountKey` is still
> `AccountKeyLegacy`.** `ValidateSender` rejects the rest with
> `ErrLegacyTransactionMustBeWithLegacyKey`.

So a single `TxTypeAccountUpdate` (`0x20`) can make an account **permanently unusable
from MetaMask, ethers or viem**, and `AccountKeyFail` can freeze it outright. The
failure surfaces as a validation error, not a signature mismatch, so it reads like a
node problem.

Kaia therefore has **two mutually exclusive** mechanisms for decoupling keys from
addresses on one chain — its own account-key system and EIP-7702 — and using the first
disables the second.

## Precompiles: a collision, resolved the opposite way to Tron

Three custom precompiles at **`0x03fd` `0x03fe` `0x03ff`**:

- `0x03fd` **vmLog** — writes to the *node's log file or stdout*, gated on the
  node-local `params.VMLogTarget` flag, returns nil. Consensus-safe (no state change)
  but the only precompile in this dataset whose entire effect is a side effect outside
  the state machine, and whose behaviour depends on how the operator started the binary.
- `0x03fe` **feePayer** — returns `contract.FeePayerAddress`, the **second sender**, as
  20 raw bytes. The only way a contract can see who is actually paying; no mainnet
  equivalent exists because mainnet has no such party. Under `eth_call` it returns the
  zero address (verified live: 20 bytes, not empty).
- `0x03ff` **validateSender** — validates signatures against an account's on-chain
  `AccountKey`; the account-abstraction primitive exposed to bytecode. It **swallows
  its errors deliberately**, returning `0x00` rather than reverting, so a caller that
  ignores the return value treats every failure as a pass.

**Before the Istanbul fork (block 86816005), these three sat at `0x09`, `0x0a` and
`0x0b`** — head-on with mainnet's BLAKE2F, KZG point evaluation and BLS12_G1ADD. Kaia
resolved it by **moving its own three** to `0x03fd`–`0x03ff` and restoring the Ethereum
semantics. Tron faced the identical collision and made the **opposite** choice, relocating
the *Ethereum* implementations into a `0x02xxxx` shadow range. `PrecompiledContractsByzantium`
is still compiled in and governs replay of pre-Istanbul history, so a node syncing from
genesis executes both maps.

## Two meters, and no block gas limit

**Kaia's header has no `gasLimit` field at all.** `block.gaslimit`, and the `gasLimit`
`eth_getBlockByNumber` reports, are both the compile-time constant
`params.UpperGasLimit = 500000000` (`0x1dcd6500`) — verified live on every block. It is
not a consensus quantity and it limits nothing.

What actually bounds a transaction is a **second, independent meter**: every opcode and
every precompile has a *computation cost* alongside its gas cost, capped per transaction
at `OpcodeComputationCostLimit` = 100,000,000 units ("100ms"), raised to 150,000,000
from Cancun. A transaction can fail with plenty of gas remaining, and it is not an
out-of-gas. Gas estimation ported from mainnet does not predict it.

The precompile interface itself differs to carry this:
`GetRequiredGasAndComputationCost(input)` and `Run(input, contract, evm)` rather than
geth's `RequiredGas(input)` and `Run(input)`.

## The fee model changed silently at the Kaia fork

`EffectiveGasPrice` before the Kaia fork (block 162900480) returns the **base fee and
nothing else** — a 1559 transaction's `maxPriorityFeePerGas` was charged for in the fee
cap check and then **discarded**. From the Kaia fork the tip is finally added.

Before Magma (block 99841497) there was no auction at all: `ValidateTx` rejected any
transaction whose gasPrice was not **exactly equal** to the governance `UnitPrice`
(25 gkei) — `==`, not `>=`, returning `ErrInvalidUnitPrice`.

Only **half** the fee is burned even now (`getBurnAmountMagma` = `totalFee/2`); Kore
burns half plus the remainder capped at the proposer's minting reward. KIP-71's base fee
is bounded, not exponential: floor 25 gkei, ceiling 750 gkei, denominator 20, gas target
30M.

And fees are **deferred** — `DeferredTxFee: true` in the genesis governance config, so
they are accumulated and settled at block end rather than credited per transaction.

## The header, and what `eth_` fabricates

Six fields are Kaia's own (`BlockScore`, `Rewardbase`, `TimeFoS`, `Governance`, `Vote`,
`RandomReveal`); eight of Ethereum's are absent (`UncleHash`, `GasLimit`, `Difficulty`,
`Nonce`, `MixDigest` pre-Randao, `WithdrawalsHash`, `ParentBeaconRoot`, `RequestsHash`).

The `eth_` namespace papers over the gap with constants: `sha3Uncles` = the constant
`EmptySha3Uncles`, `nonce` = an empty `BlockNonce`, `gasLimit` = `UpperGasLimit`,
`difficulty` = `BlockScore`.

The nastiest is **`extraData`, which is always `0x` by design**. The real field carries
the Istanbul BFT validator set, validator seals and proposer seal; the `eth_`
marshaller replaces it with empty bytes, with an in-source comment saying the real value
"cannot be used as meaningful way". It is not truncated or re-encoded — it is a lie of
omission, and the only way to read the field is Kaia's own `kaia_` namespace. Confirmed
live: `extraData` is `0x` on a block that certainly has consensus data.

## Fork names, measured

Activation is by **block number** (`<Fork>CompatibleBlock`) — a fifth incompatible
activation mechanism in this dataset. A tool looking for `cancunTime` finds nothing.

Unusually, **Kaia is not behind**: Prague at block 190670000 and Osaka at 213333000,
both already past (observed 224632605). Verified independently by probing `0x0100` with
a valid RIP-7212 vector and getting `0x…01`, and by `blobGasUsed`/`excessBlobGas`
appearing in block headers.

One fork-name lie in the other direction: **blob transactions arrived at Osaka, not
Cancun.** `tx_pool.go` rejects `TxTypeEthereumBlob` unless `rules.IsOsaka`. A chain that
was "Cancun-equivalent" by fork name had no blobs for two fork generations.

## Where the schema strained

- **`tx_types` keys are byte-shaped.** Kaia's are `uint16`. Recorded `0x7801`–`0x7804`
  as four-digit keys with `0x78` listed separately as the envelope prefix. The keys
  parse and sort correctly, but a consumer treating `tx_types` keys as `uint8` will
  truncate them. **This is the one place worth a schema conversation** — not a new
  top-level key, but a documented statement that a type key may exceed one byte.
- **`tx_types` assumes one sender.** There is no field for a second signer, a second
  signature list, a fee ratio, or the three-hash situation. Recorded in `fields:` and
  the section `note`. A `signers:` or `second_signer:` sub-key would express it
  properly — proposed, not invented.
- **`non_evm_transactions` is empty and that is correct.** Unlike Tron, Avalanche or
  Sei, every Kaia transaction carries a leading type number and is RLP-encoded. The
  divergence is in the *shape* of the type space, not in transactions escaping it.
- **`system_contracts` doesn't quite fit.** KIP-113/103/160 are not predeploys: they
  are contract *addresses baked into the chain config*, at which the client executes
  privileged logic at a fixed block. Recorded there with a `note`.

## Deliberately not established

- **The full on-chain governance / staking / registry contract set.** Only the three
  addresses named in `params/config.go` are recorded. The rest live in the
  `kaia-contracts` repo, which is **not pinned**, so enumerating them would be an
  inference. Stated in the `system_contracts.note` rather than guessed.
- **Per-opcode computation costs.** Established that the second meter exists and what
  its per-transaction limit is; the full opcode→cost table in
  `params/computation_cost_params.go` is not transcribed into `chain.yaml`.
- **Whether the `kaiax/gasless` module changes fee semantics on mainnet.** The module
  exists and prepends the `0x78` envelope on its own path; its activation state is not
  established from source.
- **Precompile extractor.** `verify.py` reports `! NO EXTRACTOR` for this row; the
  address list is taken on trust from `blockchain/vm/contracts.go:PrecompiledContractsOsaka`.

---

## Re-verify

```bash
# 1. Re-fetch the pinned evidence  (annotated tag: tag object != commit)
git clone --depth 1 --branch v2.2.2 https://github.com/kaiachain/kaia chains/kaia/repos/kaia
git -C chains/kaia/repos/kaia rev-parse HEAD   # ac7c81f3a9759704b5ce77b42ae91851ce45a9c3

# 2. Re-check every citation in chain.yaml
tools/.venv/bin/python tools/verify.py

# 3. ENUMERATE THE TX TYPE SPACE FROM SOURCE — this is how the table above was built.
#    Requires Go. Writes a temporary test into the clone and removes it again.
cd chains/kaia/repos/kaia
cat > blockchain/types/zz_dump_test.go <<'GOEOF'
package types

import "testing"

func TestDumpTxTypes(t *testing.T) {
	for i := 0; i <= 0x7810; i++ {
		tt := TxType(i)
		s := tt.String()
		if s == "" || s == "UndefinedTxType" {
			continue
		}
		_, err := NewTxInternalData(tt)
		t.Logf("0x%02x  %-60s  constructible=%v", i, s, err == nil)
	}
}
GOEOF
go test ./blockchain/types/ -run TestDumpTxTypes -v 2>&1 | grep 0x
rm blockchain/types/zz_dump_test.go
cd -

# 4. The 0x78 Ethereum-envelope wrapping, and the eth_ namespace stripping it
sed -n '/^func (serializer \*TxInternalDataSerializer) EncodeRLP/,/^}/p;/^func (serializer \*TxInternalDataSerializer) DecodeRLP/,/^}/p' \
  chains/kaia/repos/kaia/blockchain/types/tx_internal_data_serializer.go
grep -n "EthereumTxTypeEnvelope" chains/kaia/repos/kaia/api/api_eth.go

# 5. Two signers: the struct, and the two digests
sed -n '/^type TxInternalDataFeeDelegatedValueTransfer struct/,/^}/p' \
  chains/kaia/repos/kaia/blockchain/types/tx_internal_data_fee_delegated_value_transfer.go
sed -n '/^func (t \*TxInternalDataFeeDelegatedValueTransfer) SerializeForSignToBytes/,/^}/p;/SigHash/,/^}/p' \
  chains/kaia/repos/kaia/blockchain/types/tx_internal_data_fee_delegated_value_transfer.go
grep -n "func sigHashKaia" -A 12 chains/kaia/repos/kaia/blockchain/types/tx_internal_data.go
grep -n "func feePayerSigHash" -A 14 chains/kaia/repos/kaia/blockchain/types/tx_internal_data.go

# 6. Sender is a FIELD; signatures validated against the on-chain AccountKey
sed -n '/^func (tx \*Transaction) ValidateSender/,/^}/p;/^func (tx \*Transaction) ValidateFeePayer/,/^}/p' \
  chains/kaia/repos/kaia/blockchain/types/transaction.go

# 7. Account key types and roles
grep -n "AccountKeyType\w* AccountKeyType = iota" -A 8 \
  chains/kaia/repos/kaia/blockchain/types/accountkey/account_key.go
grep -n "RoleTransaction RoleType = iota" -A 5 \
  chains/kaia/repos/kaia/blockchain/types/accountkey/account_key_role_based.go

# 8. The precompile collision and its resolution at Istanbul
sed -n '/^var PrecompiledContractsByzantium/,/^}/p;/^var PrecompiledContractsIstanbul/,/^}/p;/^var PrecompiledContractsOsaka/,/^}/p' \
  chains/kaia/repos/kaia/blockchain/vm/contracts.go
sed -n '/^func (c \*feePayer) Run/,/^}/p;/^func (c \*validateSender) Run/,/^}/p;/^func (c \*vmLog) Run/,/^}/p' \
  chains/kaia/repos/kaia/blockchain/vm/contracts.go

# 9. No header gasLimit; the constant that replaces it; the blanked extraData
sed -n '/^type Header struct/,/^}/p' chains/kaia/repos/kaia/blockchain/types/block.go
grep -n "UpperGasLimit = " chains/kaia/repos/kaia/params/config.go
grep -n "extraData always return empty" -B 2 -A 4 chains/kaia/repos/kaia/api/api_eth.go

# 10. The second meter
grep -n "OpcodeComputationCostLimit" chains/kaia/repos/kaia/params/computation_cost_params.go

# 11. Fee model: exact-price rule, tip discarded pre-Kaia, half burn
grep -n "ErrInvalidUnitPrice" -B 6 chains/kaia/repos/kaia/blockchain/tx_pool.go
sed -n '/^func (tx \*Transaction) EffectiveGasPrice/,/^}/p' \
  chains/kaia/repos/kaia/blockchain/types/transaction.go
sed -n '/func getBurnAmountMagma/,/^}/p;/func getBurnAmountKore/,/^}/p' \
  chains/kaia/repos/kaia/kaiax/reward/impl/getter.go

# 12. Fork schedule (block numbers, not timestamps)
sed -n '/MainnetChainConfig = &ChainConfig{/,/UnitPrice:/p' chains/kaia/repos/kaia/params/config.go

# 13. Blobs gated on Osaka, not Cancun
grep -n "IsOsaka && tx.Type() == types.TxTypeEthereumBlob" -B 2 \
  chains/kaia/repos/kaia/blockchain/tx_pool.go
```

### Replay the live probes

Any archive node at block `224632605` (`0xd65ef1d`) or later. `V` is entry 0 of
`chains/kaia/repos/kaia/blockchain/vm/testdata/precompiles/p256Verify.json`, whose
expected output in the pinned repo is `0x…01` — i.e. a **valid** signature.

```bash
KAIA=https://public-en.node.kaia.io
V=4cee90eb86eaa050036147a12d49004b6b9c72bd725d39d4785011fe190f0b4da73bd4903f0ce3b639bbbf6e8e80d16931ff4bcf5993d58468e8fb19086e8cac36dbcd03009df8c59286b162af3bd7fcc0450c9aa81be5d10d312af6c66b1d604aebd3099c618202fcfe16ae7770b0c49ab5eadf74b754204a3bb6060e44eff37618b065f9832de4ca6ca971a7a1adc826d0f7c00181a5fb2ddf79ae00b4e10e

# Osaka is live: P256VERIFY at the mainnet address returns a valid result
curl -s -X POST $KAIA -H 'content-type: application/json' -d \
 "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"0x$V\"},\"0xd65ef1d\"]}"
# -> 0x0000...0001

# the feePayer precompile exists: 20 bytes back, not empty (zero under eth_call)
curl -s -X POST $KAIA -H 'content-type: application/json' -d \
 '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x00000000000000000000000000000000000003fe","data":"0x"},"0xd65ef1d"]}'
# -> 0x0000000000000000000000000000000000000000

# the synthesised header: gasLimit is the constant 0x1dcd6500, extraData is blank,
# sha3Uncles is the empty-uncles constant, and blob fields prove Osaka
curl -s -X POST $KAIA -H 'content-type: application/json' -d \
 '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["0xd65ef1d",false]}'
# gasLimit 0x1dcd6500 · extraData 0x · difficulty 0x1 · nonce 0x0…0
# sha3Uncles 0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347
# blobGasUsed 0x0 · excessBlobGas 0x0
```
