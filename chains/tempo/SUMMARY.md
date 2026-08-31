# Tempo — the first chain in this dataset with no native token at all

Client pinned: `tempoxyz/tempo` **v1.13.1**, commit `11b2eec62345a9a045d977255a5d93f66114e9e3`,
Rust, built on `paradigmxyz/reth` git rev `10aa6a512ba7c4f5f01ff489b1f513da0745821f`.
Live-probed at mainnet block **36217459** (`0x228a273`, `finalized` at probe time),
chain id **4217**.

The public RPC reports `tempo/v1.13.1-6d9d0d5/…`. The tag we read is the tag the
network runs, so for once nothing below has to be hedged with "the pinned client
says X, but validators may run Y".

Celo, Mantle and Gnosis already taught this dataset that gas can be paid in something
other than ether. All three still have a native asset. Tempo does not, and the
interesting consequences are not the ones you would predict from "the gas token is a
stablecoin". They are unit consequences and RPC consequences.

---

## 1. `eth_getBalance` returns a fabricated number, and the EVM disagrees with it

`crates/node/src/rpc/mod.rs` overrides `EthState::balance` to return a constant:

```rust
pub const NATIVE_BALANCE_PLACEHOLDER: U256 =
    uint!(4242424242424242424242424242424242424242424242424242424242424242424242424242_U256);
```

Both arguments are discarded — `_address`, `_block_id`. Every account, every block,
the same 4.2 × 10⁷⁵. The probe confirms it: two unrelated addresses, one an active
sender and one the block's proposer, return byte-identical results.

The EVM tells the truth. Running `SELFBALANCE` and `BALANCE` through an
`eth_call` state override at the same block returns zero for both.

**So the RPC layer and the execution layer give different answers about the same
account in the same block.** This is `severity: high` in SCHEMA.md's precise sense —
it fails silently, with no revert and no error. Anything that gates on a native
balance reads 4.2e75 and concludes the account is unimaginably rich: a wallet's
"insufficient funds for gas" check, a bridge sweep threshold, an indexer's balance
column, a monitoring alert. The doc comment says the value is a placeholder "because
the native token balance is N/A on Tempo", so it is a considered decision rather than
a bug. That does not make it safe, and the dataset had no prior case of an RPC method
returning a value the EVM contradicts.

## 2. The base fee is denominated in a unit that is not a token

This is the answer to the question the assignment posed, and it is not "the gas token
has 6 decimals".

`baseFeePerGas` is in **attodollars** — 10⁻¹⁸ USD — an accounting unit with no asset
behind it. The settlement asset, a TIP-20, has **6 decimals** (microdollars). The
protocol therefore carries an explicit conversion constant:

```rust
// crates/primitives/src/transaction/mod.rs
pub const TEMPO_GAS_PRICE_SCALING_FACTOR: U256 = uint!(1_000_000_000_000_U256);   // 10^12
pub fn calc_gas_balance_spending(gas_limit: u64, gas_price: u128) -> U256 { … }
```

Fees charged are `ceil(gas_limit × gas_price / 10¹²)` token units. Any tool that reads
`baseFeePerGas` as wei of the chain's asset is off by exactly 10¹², in the direction
that makes fees look a trillion times larger than they are.

The observed base fee, `0x23c34600` = 600,000,000 attodollars, is not arbitrary: it is
`TEMPO_T7_BASE_FEE_FLOOR`, i.e. `TEMPO_T7_BASE_FEE_CAP / 20`. TIP-1067 runs EIP-1559's
integer formula against a **fixed 10,000,000 gas target** with
`BaseFeeParams::new(8, 1)` — elasticity 1, not 2, suppressing the usual target-halving
— and then clamps the result into `[600_000_000, 12_000_000_000]`. The base fee cannot
leave that band. `eth_feeHistory` shows five consecutive blocks pinned to the floor.
Nothing is burned, because there is nothing to burn.

## 3. `value` is not "always zero by convention" — it is rejected at admission

```rust
// crates/revm/src/handler.rs, validate_env
// All accounts have zero balance so transfer of value is not possible.
if !evm.ctx.tx.value().is_zero() {
    return Err(TempoInvalidTransaction::ValueTransferNotAllowed.into());
}
```

This runs *before* `validation::validate_env`, so a value-bearing transaction never
enters a block and produces no receipt — it fails the way a bad nonce does, not the way
a revert does. `eth_call` with a `value` field errors with
`Revm error: value transfer not allowed`. Inside a `0x76` batch each call is checked
separately and rejected with `ValueTransferNotAllowedInAATx`.

The practical consequence: the `to` + `value` transfer that most tooling treats as the
primitive operation of an EVM chain is unreachable here. Asset movement is a
`transfer(address,uint256)` call to a precompile.

## 4. A second protocol-validated signer — `signers_per_tx: 2`

Tempo's `0x76` carries `feePayerSignature`, and it is real protocol machinery, not a
contract-level paymaster. `fee_payer_signature_hash` is a **different digest** from the
sender's:

```rust
// crates/primitives/src/transaction/tempo_transaction.rs
pub const FEE_PAYER_SIGNATURE_MAGIC_BYTE: u8 = 0x78;
// … buf.put_u8(FEE_PAYER_SIGNATURE_MAGIC_BYTE);
// encode the SENDER's address in place of the fee-payer field
// skip_fee_token = FALSE - fee payer commits to fee_token!
```

So the sponsor commits to *who* they are sponsoring and to *which token* they will be
billed in; the signature cannot be lifted onto another transaction or another payer.
`validate_env` recovers it before execution and, from T2, rejects a self-sponsored
transaction (`SelfSponsoredFeePayer`). The receipt exposes the result as a `feePayer`
field — visible on the live probe.

This is Kaia's fee-delegation shape, reached independently, compressed into one type
byte instead of a dozen. Unlike Kaia, each party is a single key rather than a
weighted multisig, so `signers_per_tx: 2` counts parties and there is no per-party
signature count to qualify. Sponsors must be secp256k1; a passkey cannot sponsor.

## 5. P-256 and WebAuthn authorize transactions — and WebAuthn has no verifier

The dataset carries P256VERIFY on eleven rows, and on almost all of them a P-256 key
still cannot move anything. Tempo is the counterexample. `SignatureType` is
`{Secp256k1, P256, WebAuthn}`, the client dispatches on a leading type byte, and the
address is `keccak256(pubKeyX ‖ pubKeyY)[12:]` — mainnet's own construction applied to
a P-256 point, so these are `key_binding: derived` in exactly the usual sense.

**A live block proves it.** The sampled `0x76` transaction at block 36217459 carries:

```json
"signature": { "type": "webAuthn", "r": "0x5470…", "s": "0x480c…",
               "pubKeyX": "0x94b8…", "pubKeyY": "0xf5af…",
               "webauthnData": "…\"origin\":\"https://wallet.tempo.xyz\"…" }
```

That is a raw browser passkey assertion, used as a transaction signature, on mainnet.

The WebAuthn scheme is `authorizes: protocol` with `precompile: none` — the pairing
SCHEMA.md singles out. The protocol validates a composite: authenticator-data flags
(UP/UV), the clientDataJSON challenge binding, base64url decoding, *then* the inner
P-256 ECDSA. A contract can call `0x0100` on the inner signature but cannot reproduce
the authenticator-data and challenge checks, so an on-chain recovery or multisig
contract cannot re-verify a signature its own chain just accepted. The
SignatureVerifier precompile at `0x5165300…` may narrow this gap; whether it covers the
full composite check was **not established** and is recorded as such.

`key_binding` is `declared` overall, because of a fourth scheme: a `KeychainSignature`
carries an explicit `user_address` and signs `keccak256(sigHash ‖ user_address)`. The
recovered address is an *access key*, looked up in the AccountKeychain precompile to
see whether it may act for that account and under what spending limit. The sender is
the declared address, not the recovered one. TIP-1045's `keyAuthorization` field goes
further and lets a transaction provision the very access key it is signed with.

## 6. Every stablecoin is a precompile, and every precompile has one byte of code

`extend_tempo_precompiles` installs a `set_precompile_lookup` predicate rather than a
map. Any address with the 12-byte prefix `20C000000000000000000000` is a TIP-20 token
precompile — 2⁶⁴ addresses, recorded as `precompiles.dynamic_range`. This is the second
non-enumerable precompile set in the dataset after Base's `PrecompileLookup`, arrived at
for an entirely different reason: Base resolves B-20 tokens, Tempo resolves *the money*.
`pathUSD` at `0x20C0…0000` returns `decimals() == 6`, `symbol() == "pathUSD"`, and a
totalSupply of 31,297,377,265,117 microdollars.

**`eth_getCode` at a Tempo precompile returns `0xef`, not `0x`.** At each activation
fork boundary the block executor writes a one-byte marker:

```rust
// crates/evm/src/block.rs, deploy_precompile_at_boundary
let code = Bytecode::new_legacy([0xef].into());
```

Measured: `EXTCODESIZE(pathUSD) == 1`, `EXTCODEHASH(pathUSD) ==
0x309b8896ee4c1ff7ec1966155373dee42663b6b40c3fedc70ba501684848d2a3` (= keccak of the
single byte `0xef`), while `EXTCODESIZE(0x01) == 0`. So the usual "empty code means
native" test **inverts** here: Tempo's own precompiles look like contracts and the
inherited Ethereum ones look empty. `0xef` is the EOF-reserved prefix, so the marker is
not deployable bytecode and cannot be executed. This is a fifth distinct shape in the
family the dataset has been collecting (Flare, Sonic, Cosmos EVM, Moonbeam) — and the
first where the fake code is a deliberate *marker* rather than an ABI stub.

## 7. Two gas limits in one header, and a consensus allow-list decides which one you get

The header carries `gasLimit` = 500,000,000 **and** `mainBlockGeneralGasLimit` =
30,000,000. The block executor initialises `non_payment_gas_left` to the smaller one and
decrements it only for transactions that fail the payment predicate. Payment traffic may
use the full 500M; everything else shares 30M.

From T5 the classification is consensus, not a builder heuristic. `is_payment_v2`
requires that **every** call match an allow-list of (target, selector) pairs — TIP-20
`transfer`, `transferFrom`, `approve`, `mint`, `burn`, their `WithMemo` variants, and
the TIP20ChannelReserve channel operations — with exact ABI-encoded calldata length, an
**empty** access list, empty EIP-7702 and Tempo authorization lists, and any key
authorization under 1024 RLP bytes. Adding a single access-list entry to an otherwise
identical transfer moves it into a budget sixteen times smaller.

## 8. A consensus rule keyed to a string in another account's storage

A `0x76` transaction may name any `feeToken`. The client checks the TIP-20 address
prefix and then reads the token's `currency` **storage field**, requiring it to be
exactly the three bytes `"USD"`:

```rust
// crates/revm/src/common.rs, ensure_tip20_usd
if currency.as_str() != "USD" {
    return Ok(Err(EVMError::Transaction(
        TempoInvalidTransaction::FeeTokenNotUsdCurrency { address: fee_token, currency })));
}
```

Transaction validity therefore depends on a string stored in another account's state.
Payer and validator need not agree on the token either: the validator declares a
preference in TipFeeManager and the protocol routes the fee through an enshrined AMM,
so a transaction can be rejected for `InsufficientAmmLiquidity` — a liquidity failure
surfacing as a transaction validity error. Legacy/2930/1559 transactions carry no
`feeToken` field and fall back to `DEFAULT_FEE_TOKEN`, which is why the live type-`0x2`
receipt shows `feeToken: 0x20c0…0000`. **A legacy transaction on Tempo is billed in a
stablecoin.**

## 9. An opcode that was invented and then withdrawn

`0x4F` — `MILLIS_TIMESTAMP`, pushing `block.timestamp` in milliseconds for 2 gas —
existed from genesis and was **removed at T1C** (2026-03-12):

```rust
// crates/revm/src/instructions.rs
if !spec.is_t1c() {
    instructions.insert_instruction(MILLIS_TIMESTAMP, …);
}
```

No other row in this dataset records a chain adding an opcode and then taking it away.
Contracts deployed before that date which used it now hit an undefined opcode. The
millisecond timestamp survives as a header field (`timestampMillisPart`, plus a
synthesised `timestampMillis` on the RPC), which is presumably why the opcode was no
longer needed — block time is ~200ms, so a second-resolution timestamp is ambiguous
across five blocks.

## 10. The chain's own specification repository lies about what is live

`tips/` holds 47 numbered specifications, each with a `status:` field on the ladder
Draft → … → Mainnet. **That field lags the chain badly.** TIP-1060 (Storage Credits)
reads `Draft` and has been live since T7 on 2026-07-09, where it replaced the SSTORE
instruction and zeroed the clearing refund. TIP-1070 reads `Draft` and shipped at T8.
TIP-1091 reads `Draft` and shipped at T10, three days before the probe. TIP-1067 reads
`Approved` and has been setting the base fee since T7.

The reverse also happens: TIP-1016's gas split is fully implemented as
`amsterdam_gas_params` and gated behind `cfg.enable_amsterdam_eip8037`, which is set
only in tests. Its status reads `Backlog`, which is the honest one.

This is the SCHEMA.md warning about `src_doc:` — docs describe intent and lag what
shipped — appearing *inside the client repository*, in files that ship alongside the
code that contradicts them. The `adoption:` values in `non_eip_specs` are recorded as
the documents state them; every `status:` elsewhere in the row comes from source.

## Smaller findings worth the line

- **The KZG precompile works on a chain with no blobs.** `0x0a` is present and
  reverts with `PrecompileError` on garbage — the Osaka built-in set is installed
  wholesale (from T1C; Prague before it) while type `0x03` is rejected at the envelope
  with an explicit `UnsupportedTransactionType::new(TxType::Eip4844)`. Verifier without
  payload. `blobGasUsed`, `excessBlobGas` and `baseFeePerBlobGas` survive as vestigial
  fields.
- **EIP-4788 is tombstoned, EIP-2935 is not.** `parentBeaconBlockRoot` is in the header
  and always zero, and the beacon-roots address holds no code, so the ring-buffer write
  is a no-op. The history-storage contract at `0x0000F908…2935`, by contrast, holds the
  standard runtime — the one Prague system contract Tempo keeps.
- **Withdrawals are rejected, not empty.** `apply_pre_execution_changes` errors with
  "withdrawals are not permitted" on a non-empty list. No 7002 or 7251 predeploy;
  `requestsHash` is the empty-list hash.
- **SSTORE creation costs 250,000 gas** under TIP-1000 — 12.5× mainnet — and CREATE
  costs 500,000. At T7 the SSTORE *instruction itself* is replaced in the table, the
  gas function charges a 5,000 residual, and clearing a slot yields **no refund at all**
  (`sstore_clearing_slot_refund = 0`); its replacement is a storage *credit* redeemable
  only against a future creation by the same account. That is a materially different
  economic object from a gas refund and it is not transferable to the fee.
- **Twelve mainnet hardforks in six months**, T0 through T10 with T11 declared and
  unscheduled, activation timestamps hardcoded per chain id in the client rather than
  read from genesis. Roughly one fork every two to three weeks.
- **Subblocks are not a transaction type.** A `SubBlock` is a signed validator-scoped
  bundle with no type byte; its contents are ordinary `0x76` transactions whose
  `nonceKey` carries a `0x5b`-prefixed partial validator key. Its header budget,
  `sharedGasLimit`, has been **zero since T4** — the lane exists and is allocated
  nothing.

## Not established here

- **Whether SignatureVerifier closes the WebAuthn gap.** Recorded as a note on the
  precompile and on the `webauthn` scheme rather than resolved. It is the single
  highest-value follow-up: it decides whether `precompile: none` is correct.
- **EIP-7623 calldata floor.** AA transactions compute a floor via
  `tx_floor_cost_with_tokens`, but whether the T1/T7 gas tables leave the floor rule at
  Osaka values was not traced. `unrecorded`.
- **Delegation targets.** Whether a `0x04` delegation may point at a precompile address
  is unresolved; TIP-1047 ("Revert code creation and set code at addresses with TIP-20
  prefix") is `Draft` and suggests the answer is about to change. `unrecorded`.
- **The zone system (TIP-1091).** Installed at T10 three days before the probe;
  ZonePortal addresses are recorded from the address-prefix constant only, not probed.
- **Gas-cost verification.** No transaction was submitted, so every gas figure is read
  from source, not measured. The `!NO EXTRACTOR` line from `verify.py` is expected for a
  new slug and the precompile list is not cross-checked mechanically.
- **The tx-type census covers 58 blocks, not 100** — the public endpoint rate-limited
  the scan. 7 transactions, `{0x2: 3, 0x76: 4}`. Blocks are frequently empty at ~200ms.

## What this contradicts elsewhere in the dataset

Nothing directly, but two framings need widening:

1. **"Gas token is the only delta" is not available as a category here.** Gnosis is the
   clean control case for that; Tempo is the opposite pole, where removing the native
   asset propagates into `value`, `BALANCE`, `SELFBALANCE`, `CALL`, `eth_getBalance`,
   the base-fee unit, the withdrawal path and the receipt layout.
2. **`eth_getCode` returning non-empty at a precompile now has a fifth shape.** Flare,
   Sonic, Cosmos EVM and Moonbeam write fake code of various sizes; Tempo writes exactly
   one byte, `0xef`, as a marker rather than as a stub. Any consumer classifying
   precompile-vs-system-contract from `eth_getCode` alone is wrong on this chain in both
   directions at once.

---

## Re-verify

```sh
cd /Volumes/TendiesTown/EVM-intel/chains/tempo/repos/tempo
git rev-parse HEAD          # 11b2eec62345a9a045d977255a5d93f66114e9e3
git describe --tags         # v1.13.1

# 1. the RPC placeholder balance, in source
grep -n -A3 'NATIVE_BALANCE_PLACEHOLDER' crates/node/src/rpc/mod.rs
sed -n '/async fn balance/,/^    }/p' crates/node/src/rpc/mod.rs

# 2. attodollars, the 10^12 scale, the clamped base fee
grep -n 'attodollar\|TEMPO_T7_BASE_FEE_CAP\|TEMPO_T7_BASE_FEE_FLOOR\|BaseFeeParams::new' \
     crates/hardfork/src/constants.rs
grep -n -B6 'TEMPO_GAS_PRICE_SCALING_FACTOR' crates/primitives/src/transaction/mod.rs

# 3. value rejected at admission, before standard validation
grep -n -B3 -A3 'ValueTransferNotAllowed' crates/revm/src/handler.rs

# 4. the fee payer's separate digest
grep -n -A20 'fn fee_payer_signature_hash' crates/primitives/src/transaction/tempo_transaction.rs

# 5. three protocol signature schemes + keychain; P-256 address derivation
grep -n -A8 'pub enum SignatureType' crates/primitives/src/transaction/tempo_transaction.rs
grep -n -A9 'pub fn derive_p256_address' crates/primitives/src/transaction/tt_signature.rs
grep -n 'SIGNATURE_TYPE_P256\|SIGNATURE_TYPE_WEBAUTHN\|SIGNATURE_TYPE_KEYCHAIN' \
     crates/primitives/src/transaction/tt_signature.rs

# 6. dynamic TIP-20 precompile range + the 0xef marker
grep -n -A6 'set_precompile_lookup' crates/precompiles/src/lib.rs
grep -n 'TIP20_TOKEN_PREFIX' crates/primitives/src/address.rs
grep -n -A6 'fn deploy_precompile_at_boundary' crates/evm/src/block.rs

# 7. the payment lane
grep -n -A12 'fn is_payment_v2' crates/primitives/src/transaction/envelope.rs
grep -n 'non_payment_gas_left' crates/evm/src/block.rs

# 8. the "USD" currency string as a consensus rule
grep -n -A22 'fn ensure_tip20_usd' crates/revm/src/common.rs

# 9. opcode 0x4F added then removed
grep -n -B2 -A4 'MILLIS_TIMESTAMP' crates/revm/src/instructions.rs

# 10. tips/ status vs reality
for f in tips/tip-1060.md tips/tip-1070.md tips/tip-1091.md tips/tip-1067.md tips/tip-1016.md; do
  echo "$f $(grep -m1 '^status:' $f)"; done
grep -n 'MAINNET_T7_TIMESTAMP\|MAINNET_T8_TIMESTAMP\|MAINNET_T10_TIMESTAMP' \
     crates/hardfork/src/constants.rs

# no blob type; Osaka everywhere
grep -n 'Eip4844' crates/primitives/src/transaction/envelope.rs
grep -n -A4 'impl From<TempoHardfork> for SpecId' crates/hardfork/src/lib.rs
```

```sh
RPC=https://rpc.tempo.xyz
B=0x228a273          # 36217459
call() { curl -s -X POST $RPC -H 'Content-Type: application/json' \
         -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}"; echo; }

# identity — the running client is the pinned tag
call eth_chainId '[]'                # -> 0x1079 (4217)
call web3_clientVersion '[]'         # -> tempo/v1.13.1-6d9d0d5/x86_64-unknown-linux-gnu

# THE headline: same absurd balance for two unrelated accounts, at a pinned block
call eth_getBalance '["0x7a19d6086c5dc88f2755d82efda69d62bf2336e7","0x228a273"]'
call eth_getBalance '["0xe3add088abba28ee91cdc92e4b280bebf0c6c7c7","0x228a273"]'
#   both -> 0x9612084f0316e0ebd5182f398e5195a51b5ca47667d4c9b26c9b26c9b26c9b2
#   python3 -c "print(0x9612…9b2)"  ->  4242…42  (38 repetitions of '42')

# …and the EVM says zero.  SELFBALANCE = 47 5f 52 60 20 5f f3
call eth_call '[{"to":"0x00000000000000000000000000000000000face7","data":"0x"},
                "0x228a273",{"0x00000000000000000000000000000000000face7":{"code":"0x475f5260205ff3"}}]'
# BALANCE(calldata addr) = 5f 35 31 5f 52 60 20 5f f3
call eth_call '[{"to":"0x00000000000000000000000000000000000face7",
                 "data":"0x0000000000000000000000007a19d6086c5dc88f2755d82efda69d62bf2336e7"},
                "0x228a273",{"0x00000000000000000000000000000000000face7":{"code":"0x5f35315f5260205ff3"}}]'
#   both -> 0x00…00

# value is refused, not reverted
call eth_call '[{"to":"0x7a19d6086c5dc88f2755d82efda69d62bf2336e7","value":"0x1"},"0x228a273"]'
#   -> error -32603 "Revm error: value transfer not allowed"

# header: two gas limits, ms timestamp, consensus context, zero beacon root
call eth_getBlockByNumber '["0x228a273",false]'
#   gasLimit 0x1dcd6500 (500,000,000) vs mainBlockGeneralGasLimit 0x1c9c380 (30,000,000)
#   sharedGasLimit 0x0, timestampMillisPart 0x195, consensusContext {epoch,view,parentView,proposer}
#   baseFeePerGas 0x23c34600 == 600,000,000 attodollars == TEMPO_T7_BASE_FEE_FLOOR

# base fee pinned to the floor across the window
call eth_feeHistory '["0x4","0x228a273",[10,50]]'
call eth_gasPrice '[]'                     # -> 0x23c34600
call eth_maxPriorityFeePerGas '[]'         # -> 0x0

# tx type census (rate-limited; 36217459..36217516 gave 7 txs {0x2:3, 0x76:4})
for n in 228a273 228a274 228a275 228a276; do call eth_getBlockByNumber "[\"0x$n\",true]"; done
#   the 0x76 sample carries feeToken, calls[], nonceKey, feePayerSignature, validBefore/After,
#   keyAuthorization, aaAuthorizationList and signature.type == "webAuthn"

# receipts gain feeToken + feePayer — on an ORDINARY type-0x2 transaction
call eth_getTransactionReceipt '["0x265549d2d9e57364682a4b6cbf6364de4e721a0850ffb8cbf0c22d8eb2bf1d2f"]'
#   -> feeToken 0x20c0000000000000000000000000000000000000, feePayer == from

# precompiles carry one byte of code; inherited Ethereum ones carry none
for a in 20C0000000000000000000000000000000000000 20FC000000000000000000000000000000000000 \
         403C000000000000000000000000000000000000 feec000000000000000000000000000000000000 \
         dec0000000000000000000000000000000000000 AAAAAAAA00000000000000000000000000000000 \
         5165300000000000000000000000000000000000 1060000000000000000000000000000000000000 \
         C077E00000000000000000000000000000000000; do
  call eth_getCode "[\"0x$a\",\"0x228a273\"]"; done          # all -> 0xef
call eth_getCode '["0x0000000000000000000000000000000000000001","0x228a273"]'   # -> 0x
call eth_getCode '["0x0000000000000000000000000000000000000100","0x228a273"]'   # -> 0x

# EXTCODESIZE / EXTCODEHASH prove it from inside the EVM
call eth_call '[{"to":"0x00000000000000000000000000000000000face8",
                 "data":"0x00000000000000000000000020C0000000000000000000000000000000000000"},
                "0x228a273",{"0x00000000000000000000000000000000000face8":{"code":"0x5f353b5f5260205ff3"}}]'
#   -> 1     (…:{"code":"0x5f353f5f5260205ff3"} gives EXTCODEHASH 0x309b8896…d2a3 = keccak(0xef))
call eth_call '[{"to":"0x00000000000000000000000000000000000face8",
                 "data":"0x0000000000000000000000000000000000000000000000000000000000000001"},
                "0x228a273",{"0x00000000000000000000000000000000000face8":{"code":"0x5f353b5f5260205ff3"}}]'
#   -> 0     (ecrecover has no code)

# pathUSD is a precompile with 6 decimals and is the default fee token
call eth_call '[{"to":"0x20C0000000000000000000000000000000000000","data":"0x313ce567"},"0x228a273"]'  # 6
call eth_call '[{"to":"0x20C0000000000000000000000000000000000000","data":"0x95d89b41"},"0x228a273"]'  # "pathUSD"
call eth_call '[{"to":"0x20C0000000000000000000000000000000000000","data":"0x18160ddd"},"0x228a273"]'

# KZG present on a chain with no blobs; P256VERIFY present and native
call eth_call '[{"to":"0x000000000000000000000000000000000000000a","data":"0x'$(printf '00%.0s' {1..192})'"},"0x228a273"]'
#   -> error "EVM error: PrecompileError"   (present, rejecting garbage)
call eth_call '[{"to":"0x0000000000000000000000000000000000000100","data":"0x'$(printf '00%.0s' {1..160})'"},"0x228a273"]'
#   -> 0x   (EIP-7951 empty-on-invalid)

# 4788 dead, 2935 alive, 7002/7251 absent
call eth_getCode '["0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02","0x228a273"]'   # -> 0x
call eth_getCode '["0x0000F90827F1C53a10cb7A02335B175320002935","0x228a273"]'   # -> standard runtime
call eth_getCode '["0x00000961Ef480Eb55e80D19ad83579A64c007002","0x228a273"]'   # -> 0x
call eth_getCode '["0x0000BBdDc7CE488642fb579F8B00f3a590007251","0x228a273"]'   # -> 0x
```
