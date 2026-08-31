# Celo

**Role:** `fork` · **Upstream:** `op-stack` · **Chain ID:** 42220 · **Baseline:** Prague
**Client:** [`celo-org/op-geth`](https://github.com/celo-org/op-geth) `celo-v2.2.4`
(`aee04e0b41af645723e1debc833469ca2a3ae54a`) ·
**Companion:** [`celo-org/optimism`](https://github.com/celo-org/optimism) `celo-v2.2.1`
(`a590fbdcfdf3b7132ef0f974ecc341a963343d07`)
**Live probes:** `https://forno.celo.org` @ block `74884096`

Celo was a standalone L1 until the **Cel2** transition on 2025-03-26 (L2 block
31056500) and carried its fee-currency abstraction across the migration. This file
records only Celo's own deltas; everything else resolves through
[`chains/op-stack/`](../op-stack/chain.yaml).

## The headline: OP Stack derivatives do not inherit the envelope

The `op-stack` row is built on the premise that a stack node holds its descendants'
shared deltas **exactly once**, and that a descendant therefore inherits the
transaction envelope. Celo falsifies that.

- **Tx type `0x7b` (CIP-64)** — a 1559 transaction with one extra field,
  `FeeCurrency`, naming an ERC-20 that pays for gas. Source:
  `core/types/celo_dynamic_fee_tx_v2.go:CeloDynamicFeeTxV2Type`.
- It is **not a curiosity**: at block 74884096, **12 of 19 transactions were type
  `0x7b`** — the majority type on the chain, against 5 `0x2`, 1 `0x7e` and 1 `0x0`.
- `FeeCurrency` is inside the **signature hash**, so a `0x7b` cannot be re-encoded as
  a `0x02`. A signer, txpool, or indexer written to OP Stack's `0x00`-`0x04` + `0x7e`
  set fails on most Celo traffic.
- The **receipt** diverges too (CIP-66): `0x7b` receipts carry a **fifth consensus
  field**, `baseFee`, denominated in the fee currency, and it is inside
  `receiptsRoot`. Live: receipt `baseFee` `0x2c567f0d0` against header
  `baseFeePerGas` `0x2e90edd000` — same block, different assets.
- Two more envelope shapes survive from the L1 era: `0x7c` (deprecated at Cel2, still
  in history) and a **12-field variant of the untyped legacy transaction**, told apart
  from Ethereum's 9-field one *only by counting RLP elements*
  (`core/types/celo_tx_legacy.go:ethCompatibleTxNumFields`).

Four envelope shapes where OP Stack has two.

### What this means for the `op-stack` row

**No edit is required to `chains/op-stack/`** — its claims remain true of OP Stack
itself. What needs changing is the *framing*, and that belongs to whoever owns the
repo's prose:

1. `chains/op-stack/chain.yaml`'s `tx_types.note` says `0x7e` was placed at the top of
   the legal range "to maximise distance from mainnet's allocations growing upward
   from 0x04". That is now a **two-sided** frontier: Arbitrum `0x78`, Base `0x79`,
   Celo `0x7b`, Celo `0x7c`, OP `0x7e`, Polygon `0x7f`. The top of the range is
   **half-consumed and two of the six entries are on the same stack**. `0x7d` is the
   only byte left between `0x7c` and `0x7e`.
2. README.md's "**'Runs the OP Stack' constrains almost nothing**" paragraph cites
   Base, opBNB and World Chain. Celo is the strongest instance yet and the only one
   that breaks the *envelope*: Base added `0x79` for native AA, but Celo's custom type
   is the chain's dominant traffic and changes the *receipt* format as well.
3. The stack-node contract in SCHEMA.md ("A chain whose `lineage.upstream` names a
   `stack` row states **only its own deltas**") holds and worked. What does **not**
   hold is any downstream consumer's assumption that resolving `ethereum -> op-stack ->
   X` yields the full type-byte set without reading `X`.

## Second finding: a descendant pinned to its ancestor's past

`lineage.sync_point` in the schema exists for exactly this, and Celo is a sharper case
than opBNB's:

| | op-stack row | Celo |
|---|---|---|
| go-ethereum base | v1.17.5 | **v1.16.9** |
| newest OP fork | Karst | **Jovian** |
| baseline | Osaka | **Prague** |

Karst is not "not activated" — it is **not representable**. `params/config.go` has no
`KarstTime` and the embedded superchain-registry schema (`superchain/types.go`) has no
`karst_time` field. Likewise there is no `osaka_time` for chain 42220. Every claim the
`op-stack` row records at Osaka or Karst simply does not describe Celo.

## Third finding: the fee path is a client-driven EVM call

Paying gas in an ERC-20 is not a bookkeeping trick. Per transaction the client makes
**two EVM calls from the zero address** into the fee-currency contract, outside the
transaction's own call tree:

- `DebitFees` -> `debitGasFees(from, value)` before execution
  (`contracts/fee_currencies.go:DebitFees`)
- `CreditFees` -> `creditGasFees(...)` after, which also mints the **gas refund** back —
  `returnGas` does nothing for a fee-currency transaction.

Both are **hidden from tracers** unless `Tracer.TraceDebitCredit` is set
(`disableTracer`), so `debug_traceTransaction` does not show the user's gas being
taken. In the probed CIP-64 transaction the fee-currency contract emitted **no log at
all**, so an ERC-20 balance reconstructed from `Transfer` events drifts from the real
balance for every account that pays gas in that token.

Three further consequences:

- **Intrinsic gas is read from contract storage.** `IntrinsicGas` adds a per-currency
  surcharge from `FeeCurrencyDirectory.getCurrencyConfig`. The same calldata has a
  different intrinsic cost depending on which token pays, and governance can change it
  with no fork and no client release.
- **The block gas limit is subdivided per currency.** `MultiGasPool` gives each
  allowlisted fee currency its own pool sized as a fraction of the block limit. A block
  can be full for one currency and open for another. Disabled when deriving from L1.
- **The base fee does not go to `BaseFeeVault`.** From Cel2 it goes to the FeeHandler at
  `0xcD437749E43A154C07F3553504c68fBfD56B8778`. OP-chain revenue tooling reading
  `0x42..19` gets zero and no error.

## Fourth finding: a custom precompile at `0x00...fd`

`op-stack` has **zero** added precompile addresses. Celo has one:
`0x00000000000000000000000000000000000000fd`, a native `transfer` that moves CELO so the
CELO ERC-20 can be both the token and the gas asset. It is permissioned — it reverts
unless the immediate caller is the CeloToken address — and returns `ErrWriteProtection`
under `STATICCALL`.

Verified to be a **precompile, not a predeploy**: `eth_getCode` returns `0x` at block
74884096, while the FeeCurrencyDirectory at the same height returns proxy bytecode.

Placement is the concern. Every other custom precompile in this dataset sits at `0x0100`
or far above (Tron `0x1000001+`, Monad `0x1000`, Sonic `0xd100ec...`). Celo parked one
at `0xfd`, **three addresses below `0x0100`**, inside the range mainnet is growing into.

(Flare was cited here as `0x1000...0002` in an earlier pass. The `flare` row establishes
that those addresses hold real genesis bytecode — they are system contracts, and Flare
adds no precompile addresses at all. The point stands on Tron, Monad and Sonic.)

## Fifth finding: the contracts repo does not describe mainnet

`CeloPredeploys.sol` in `celo-org/optimism` lists ten addresses. Live probing at block
74884096 shows:

- `FEE_CURRENCY_DIRECTORY = 0x9212Fb...11BF` — that is the **Sepolia** directory. The
  client's `contracts/addresses/addresses.go` puts mainnet's at `0x15F344b9...6276`, and
  only the latter has code on mainnet.
- `FEE_CURRENCY = 0x4200...1022` — **empty on mainnet**. It also sits far above OP's
  highest real predeploy (`0x42..2d`).

Trust `addresses.go`, not the contracts repo. Note also that Celo's real system
contracts are **not in the `0x42..` namespace** at all — they are L1-era addresses
carried through the migration, three of which are hardcoded in the client and switched
on chain id.

## Recorded as `unrecorded`

Two EIP entries, deliberately:

- **EIP-3529** — how the SSTORE refund cap composes with `CreditFees` handling refunds
  for fee-currency transactions was not read from source.
- **EIP-7702** — `SetCodeTx` is in the legacy pool's accept set, but the interaction
  between a delegation on the *sender* and the client-driven debit/credit calls against
  that sender was not established.

Both are real gaps, not formalities: each sits exactly where Celo's fee path crosses a
mainnet rule.

## Not established here

- **Fee-currency `Transfer` events**: the "no logs" observation is `n = 1`. Only one
  distinct fee currency appeared in the probed block. The *source* fact (debit/credit
  are client-driven EVM calls hidden from tracers) is solid; the *event* behaviour
  depends on each registered token's implementation and was checked once.
- **Pre-Gingerbread header decoding** is recorded from source
  (`core/types/celo_block.go:BeforeGingerbreadHeader`) but was not probed live — the
  public RPC does not retain that state.

## Transaction authorization: the fee currency changes the payer, not the signer

The obvious question for this row is whether CIP-64 (`0x7b`), which pays gas in an
ERC-20, changes *who can authorize* a transaction. It does not. `dynamicTxSender` is
plain `recoverPlain` over the type's own sighash; `FeeCurrency` is inside that sighash
but outside the authorization decision; and the sender is still the payer, so
`signers_per_tx` stays 1. Contrast Kaia, where fee delegation genuinely adds a second
party. Nothing survives from Celo's L1 validator or attestation machinery either — that
was authorized-signer state inside `Accounts.sol`, contract-level and never a protocol
signature path, and the client's entire Celo fork list is `{cel2, celoLegacy}` with no
attestation entry.

What *did* cross the Cel2 transition is a modified sender-**recovery** overlay.
`celoSigner` wraps the upstream signer and picks a per-type recovery routine from a fork
list before upstream ever sees the transaction, and four things differ from mainnet —
all of them about *when* a signature is accepted, none about what a signature is:

1. **Two transaction hashes are hard-coded carve-outs.** `isChainIDException` names
   `mainnetChainIDExceptionHash` (block 53619115) and `sepoliaChainIDExceptionHash`
   (block 12531083) and recovers those two transactions against the *transaction's*
   chain ID instead of the signer's, because they were accepted with the wrong chain ID
   before a validation fix. Sender recovery is therefore **not a pure function of the
   envelope**: two specific hashes take a different code path. Any independent
   implementation replaying Celo history without this table derives a different sender
   for those blocks.
2. **Unprotected signatures are still recoverable** on the 12-field celo-legacy layout.
   `celoLegacyTxFuncs.sender` branches on `tx.Protected()` and, when unprotected,
   recovers over a pre-EIP-155 digest with no chain ID in it, computed over Celo-only
   fields (`FeeCurrency`, `GatewayFeeRecipient`, `GatewayFee`).
3. **Two type bytes can no longer authorize anything.** From Cel2 the celo-legacy
   `LegacyTx` shape and `0x7c` map to `deprecatedTxFuncs`, whose sender returns
   `ErrDeprecatedTxType`. They stay decodable and stay in history, but no signature over
   them is accepted going forward — a removed *authorization path*, not a removed
   encoding.
4. The historical DynamicFee and AccessList paths are handled by the `celoLegacy` fork
   rather than by London/Berlin, because Celo enabled them in Espresso, which has no
   op-geth analogue.

None of it reaches the curve: every live branch ends in `recoverPlain`, `0x01` is
untouched, and the scheme stays paired with its precompile. Recorded as
`secp256k1: status: modified`.

## Re-verify

```sh
# from the repo root
tools/clone.sh                                 # re-fetches every pinned clone
tools/.venv/bin/python tools/verify.py        # expect: pin ok, citations ok, exit 0
                                              # "! NO EXTRACTOR" for celo is expected

# the custom transaction types
git -C chains/celo/repos/op-geth grep -n 'TxV2Type = 0x7b' -- core/types/celo_dynamic_fee_tx_v2.go
git -C chains/celo/repos/op-geth grep -n 'CeloDynamicFeeTxType = 0x7c' -- core/types/celo_dynamic_fee_tx.go

# the added precompile, and that it really is a precompile
git -C chains/celo/repos/op-geth grep -n 'TransferPrecompileAddress' -- core/vm/celo_contracts.go
curl -s -X POST https://forno.celo.org -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":["0x00000000000000000000000000000000000000fd","0x479ae00"]}'
# -> {"result":"0x"}   (no bytecode: native precompile)

# the FeeCurrencyDirectory is a contract, and how many currencies it holds
curl -s -X POST https://forno.celo.org -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":["0x15F344b9E6c3Cb6F0376A36A64928b13F62C6276","0x479ae00"]}'
curl -s -X POST https://forno.celo.org -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x15F344b9E6c3Cb6F0376A36A64928b13F62C6276","data":"0x61c661de"},"latest"]}'
# -> ABI-encoded address[]; 20 entries at the time of writing

# 0x7b is the majority tx type, and its receipt carries a baseFee field
curl -s -X POST https://forno.celo.org -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["0x479ae00",true]}' \
  | python3 -c 'import json,sys,collections; print(collections.Counter(t["type"] for t in json.load(sys.stdin)["result"]["transactions"]))'
# -> Counter({'0x7b': 12, '0x2': 5, '0x7e': 1, '0x0': 1})
curl -s -X POST https://forno.celo.org -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getTransactionReceipt","params":["0x85c22ae8785cb009441299451ee2807a9a36b787ad3b3ef0218693ec89d901c6"]}' \
  | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print("type",r["type"],"baseFee",r["baseFee"])'
# -> type 0x7b baseFee 0x2c567f0d0

# the sync point: no Karst, no Osaka
git -C chains/celo/repos/op-geth grep -n 'Karst' -- params/config.go superchain/types.go; echo "grep exit=$? (1 == no matches anywhere)"
tools/.venv/bin/python -c "import zipfile; print(zipfile.ZipFile('chains/celo/repos/op-geth/superchain/superchain-configs.zip').read('configs/mainnet/celo.toml').decode())"
# -> [hardforks] ends at jovian_time; cel2_time = 1742957258; no karst_time, no osaka_time
```
