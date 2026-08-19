# zkSync Era — not an EVM, wearing an EVM's RPC

**Chain ID 324 · role: `independent` · equivalence: `behavioural` · no upstream**

Reference: [matter-labs/zksync-era `core-v31.5.0`](https://github.com/matter-labs/zksync-era)
@ `fa3a9b94`, plus two companions the node pins itself:
[era-contracts](https://github.com/matter-labs/era-contracts) @ `101ab952` (the exact
`contracts` submodule commit) and
[zksync-protocol](https://github.com/matter-labs/zksync-protocol) `v0.153.14` @
`4b2c1e61` (the exact `zk_evm_1_5_2` Cargo tag).

The node repository alone establishes almost nothing about EVM semantics. The
instruction set lives in `zksync-protocol`; the semantics an Ethereum client hardcodes —
nonces, code storage, deployment, balances, events, and the EVM itself — live in
`era-contracts` as Solidity and Yul. Three clones or no row.

## The four that break integrators, in order

### 1. CREATE2 addresses are different, and depend on different inputs

`ContractDeployer.getNewAddressCreate2`:

```solidity
keccak256(CREATE2_PREFIX || sender(32) || salt || bytecodeHash || keccak256(constructorInput))
// CREATE2_PREFIX = keccak256("zksyncCreate2")
```

Two changes, and the second is the dangerous one. Mainnet's CREATE2 address does **not**
depend on constructor arguments — they are baked into the initcode being hashed. zkSync
hashes them *separately and additionally*, so two deployments with the same salt and the
same contract but different constructor arguments land at **different addresses**.

`CREATE` is `keccak256(keccak256("zksyncCreate") || sender || nonce)` — not RLP.

Every counterfactual-address pattern breaks: Safe/AA wallet address precomputation,
deterministic deployers, cross-chain "same address everywhere" deployments, any off-chain
`getCreate2Address` helper.

### 2. …and there are **two** derivation schemes live at once

`Utils.getNewAddressCreate2EVM` and `Utils.getNewAddressCreateEVM` implement **mainnet's**
rules — `0xff || sender || salt || bytecodeHash`, and `keccak(RLP(sender, nonce))` — for
contracts deployed through the EVM emulator.

So on one chain, at one block, the address a factory produces depends on whether that
factory is EraVM bytecode (zksolc) or EVM bytecode (solc, run under the emulator). No
other chain in this dataset has two live address-derivation rules, and `chain.yaml` has
no field that expresses "the rule depends on which VM the caller is".

The emulator is live on mainnet: `zks_getProtocolVersion` @ 71584105 reports a non-zero
`evm_emulator` base-system-contract hash.

### 3. There is no EOA. Every account is a contract.

`IAccount` requires `validateTransaction`, `executeTransaction`, `payForTransaction` and
`prepareForPaymaster`; plain addresses run `DefaultAccount`. Signature verification is
the account's own code and **need not be secp256k1** — tx type `0x71` carries a
`customSignature` field for exactly that.

Code that assumes a recoverable ECDSA sender, or that a codeless address cannot originate
a transaction, is wrong at every address on the chain.

The dark-mirror of this: EIP-7702 is absent, so the `0xef0100` delegation prefix that
tooling now uses to *detect* smart accounts finds nothing here — and concludes every
account is an EOA, on the one chain where none is.

**Is the scheme set self-limiting? No — and it was worth checking.** The bootloader's
`accountValidateTx` verifies *nothing* cryptographic: it calls `validateTransaction` on
the sender's account and accepts the transaction if that call returns the magic
selector. There is no protocol-level signature check anywhere on the path, for `0x00`,
`0x01`, `0x02` or `0x71` alike. Even the secp256k1 "EOA" rule is supplied by
`DefaultAccount._isValidSignature` — replaceable Solidity, not consensus. On `0x71` the
sender is an explicit unsigned RLP field and `customSignature` overrides `v/r/s`
entirely; on the untyped paths the node's `recover_default_signer` only *selects* which
account gets asked.

An account validator is ordinary bytecode, so the reachable set is bounded by **gas, not
by the precompile set** — a validator may implement a curve with no precompile behind it
at all. Two soft bounds were checked and neither closes the set:

1. The sequencer's `ValidationTracer` caps validation work
   (`TookTooManyComputationalGas`) against a **node-configured**
   `validation_computational_gas_limit` — 300,000 in one shipped config, 10,000,000 in
   another. Its own doc comment says it exists *"to prevent DDoS attacks on the
   server"*: an admission policy, not a consensus rule, and one two nodes can disagree
   on.
2. The precompile set decides only what is *cheap*. secp256k1 (`0x01`) and secp256r1
   (`0x0100`) are one call each; MODEXP's 32-byte operand cap forecloses the cheap RSA
   route; there is no ed25519 verifier at any address.

So `tx_authorization.schemes` on this row lists what is *practically reachable today*,
not a closed enumeration — and the row says so rather than implying otherwise. Worth
noting in passing: because an account can call `0x0100` from `validateTransaction`,
zkSync is one of the few rows where **a P-256 key can actually authorize a
transaction**, against the usual pattern where `P256VERIFY` is a contract tool only.

### 4. `eth_getCode` and `EXTCODESIZE` disagree, on purpose

`Constants.sol`, `CURRENT_MAX_PRECOMPILE_ADDRESS = 0xff`:

> The maximal possible address of an L1-like precompile. These precompiles maintain the
> following properties: Their `extcodehash` is `EMPTY_STRING_KECCAK`, their
> `extcodesize` is 0 **despite having a bytecode formally deployed there**.

`AccountCodeStorage.getCodeHash` implements the mask. So inside the EVM, `0x01`–`0xff`
look codeless exactly as mainnet's precompiles do. But over JSON-RPC:

```
eth_getCode(0x01) @ 71584105  -> 608 bytes of EraVM bytecode
eth_getCode(0x05) @ 71584105  -> 1184 bytes
eth_getCode(0x08) @ 71584105  -> 800 bytes
```

The in-chain view and the off-chain view of the same address are deliberately different.
Any indexer, explorer or wallet that classifies addresses via `eth_getCode` gets an answer
the EVM disagrees with.

**And the mask stops at `0xff`.** P256VERIFY sits at `0x0100` = 256, above it — so on
zkSync `0x0100` has a real `EXTCODESIZE` (480 bytes) and a real `EXTCODEHASH`, where
mainnet's `0x0100` is codeless. `EXTCODEHASH(0x0100) == keccak256("")` is true on mainnet
and false here.

## Did proof constraints leak into consensus? Yes, and the source admits it

`EvmEmulator.yul`:

```
/// @dev This restriction comes from circuit precompile call limitations
function MAX_MODEXP_INPUT_FIELD_SIZE() -> ret {
    ret := 32 // 256 bits
}
```

and at the call site:

```
// The current value (32 bytes) violates EVM equivalence.
// This value comes from circuit limitations.
```

**MODEXP operands — base, exponent and modulus alike — are capped at 32 bytes.** Mainnet's
own bound, EIP-7823 at Osaka, is 1024 bytes; zkSync is **32× tighter**, and was tighter
years before mainnet had any bound at all. 2048-bit RSA verification, the overwhelmingly
common real use of MODEXP, is impossible on zkSync Era.

The failure mode is the interesting part. Over the cap the emulator sets
`gasToCharge := MAX_UINT64()` — "Skip calculation, not supported or **unpayable**" — so
the sub-call runs out of gas and `CALL` returns 0. It does not revert. A caller using the
common Solidity low-level pattern that ignores the return value proceeds with empty
output.

That is a third distinct mechanism for the same underlying cause:

| Chain | Cause | Mechanism | Signal to caller |
|---|---|---|---|
| OP Stack | fault-proof VM gas ceiling | per-call **input size** cap | revert |
| Linea | prover per-block line budget | per-block **work** budget | transaction never included |
| zkSync Era | modexp **circuit width** | per-operand **bit width** cap | sub-call OOG, `CALL` returns 0 |

Three independent proving systems, three consensus rules, no shared code and no shared
mechanism. The pattern OP Stack showed is a **law**, not an anecdote — but "proof
constraints leak into consensus" says nothing about *how*, and the three ways fail
differently enough that no single detection strategy finds all of them.

## EraVM is not the EVM

`zkevm_opcode_defs::Opcode` has **17 variants** — `Invalid, Nop, Add, Sub, Mul, Div,
Jump, Context, Shift, Binop, Ptr, NearCall, Log, FarCall, Ret, UMA` — over 16 registers.
There is no 256-entry byte jump table, no stack machine, and no correspondence to
Ethereum opcode numbers.

Things that are opcodes on mainnet and are **contract calls** here:

- **KECCAK256** → precompile at `0x8010`. EraVM has no hashing instruction.
- **LOG0–LOG4** → `EventWriter` at `0x800d`.
- **CALL with value** → `MsgValueSimulator` at `0x8009`; EraVM far-calls carry no value.
- **Balance** → `L2BaseToken` at `0x800a`; the native balance is ERC-20-like contract
  state, not an account field.
- **Nonce** → `NonceHolder` at `0x8003`, with deployment nonce and transaction nonce as
  separate counters packed in one slot.
- **Deployment** → `ContractDeployer` at `0x8006`. There is no initcode-return
  convention; bytecode is published as `factoryDeps` on the transaction.

### Inside the EVM emulator, where the opcode table does exist

- **`SELFDESTRUCT` (`0xFF`) is not implemented.** It is listed among the emulator's
  "Unused opcode" cases — invalid, not a no-op. So is **`CALLCODE` (`0xF2`)**.
- **`PREVRANDAO` (`0x44`) returns the fixed constant `2500000000000000`**, with the
  comment "This value is fixed in EraVM". Present, non-zero, identical in every block
  forever. A contract using it for randomness gets the same number every time, with no
  error — the same failure shape as Tron's `BASEFEE`.
- `BLOBHASH` returns 0; `BLOBBASEFEE` returns 1. Both stubbed with comments saying so.
- `PUSH0`, `MCOPY`, `TLOAD`/`TSTORE` are implemented — the Cancun set is there.
- `GAS` (`0x5A`) reports **simulated EVM gas** maintained by `EvmGasManager` (`0x8013`),
  not EraVM ergs. Two resources, one opcode, and a contract cannot see both.

## Transaction types outside the legal range

```rust
pub const EIP_712_TX_TYPE: u8 = 0x71;
pub const PROTOCOL_UPGRADE_TX_TYPE: u8 = 0xfe;
pub const PRIORITY_OPERATION_L2_TX_TYPE: u8 = 0xff;
```

EIP-2718 confines transaction types to `0x00`–`0x7f`. `0xfe` and `0xff` are values it
reserves precisely so they can never be transaction types — and both appear in RPC
output on this chain. The README's "two allocation frontiers closing on each other"
finding gets a third case: everyone else crowded *toward* the `0x7f` ceiling (Arbitrum
`0x78`, Base `0x79`, OP `0x7e`, Polygon `0x7f`); **zkSync went straight through it.** A
decoder that treats a leading byte ≥ `0xc0` as legacy RLP misparses every L1→L2
transaction on the chain.

`0x71` itself is signed as **EIP-712 typed data**, not as a keccak of an RLP payload, and
carries four fields with no mainnet analogue: `gasPerPubdata` (a second, independent
price the sender commits to), `factoryDeps` (bytecodes published with the transaction),
`customSignature`, and `paymasterParams` (a protocol-level third-party fee payer).

Accepted L2 types are `0x00`, `0x01`, `0x02`, `0x71`. Blob (`0x03`) and SetCode (`0x04`)
are absent; the dispatch in `TransactionRequest::rlp` ends in
`Some(_) => unreachable!("Unknown tx type")`, so that list is exhaustive.

## The whole of kernel space is tombstoned

Mainnet's missing precompiles here are not merely absent. Live at 71584105:

```
eth_call to 0x03 (RIPEMD160)  -> execution reverted
eth_call to 0x09 (BLAKE2F)    -> execution reverted
eth_call to 0x0a (KZG)        -> execution reverted
eth_call to 0xffff            -> execution reverted
eth_call to 0xdeadbeef        -> 0x            (success, empty — as on mainnet)
```

Every address below `2^16` (`ADDRESS_UNRESTRICTED_SPACE`) is EraVM **kernel space**, and a
kernel address with no deployed code aborts the call. That is SCHEMA.md's `tombstoned`
exactly — "calling a tombstoned address fails, while calling an absent one succeeds with
empty output" — and it is the first instance in the dataset reached **wholesale, by an
address-space rule** rather than by deliberately deploying reverting stubs, as Avalanche
and BSC did. 65,536 addresses, one rule.

It is also the one place zkSync fails *louder* than mainnet. Worth knowing before porting
error handling that relies on empty-address calls succeeding.

## Two ranges, and zero collisions

`SYSTEM_CONTRACTS_OFFSET = 0x8000`, with the comment: chosen "in order to avoid collision
with Ethereum precompiles". `USER_CONTRACTS_OFFSET = 0x10000` holds built-in but
unprivileged contracts (`Create2Factory`, `L2Bridgehub`, `L2AssetRouter`, interop).

That discipline paid off. zkSync Era occupies `0x01`–`0x08` with mainnet's own functions
and puts everything of its own at or above `0x8000` — no address it introduced collides
with a mainnet allocation, or with the `0x64`–`0x69` block BSC/Arbitrum/opBNB fight over,
or with Tron's `0x1000001`+ range. Compare Tron, which put `batchValidateSign` on
BLAKE2F's `0x09`. Placement discipline and semantic fidelity are independent axes, and
zkSync sits at the extreme corner: maximum semantic divergence, minimal placement
conflict.

## Fees, blocks, headers

- Metering is **ergs**, not gas. `MAX_TX_ERGS_LIMIT = 80,000,000` and
  `ERGS_PER_CIRCUIT = 80,000` — the per-transaction ceiling is literally a circuit count.
- **Pubdata is a second, orthogonal budget.** Every transaction declares `gas_per_pubdata`;
  `L1_GAS_PER_PUBDATA_BYTE = 17`, `COMPUTATIONAL_PRICE_FOR_PUBDATA = 80`,
  `MAX_PUBDATA_PER_BLOCK = 110000`. A storage-heavy transaction can exhaust a block while
  using almost no computation.
- Refunds are computed by the bootloader *after* execution, so gas actually charged is not
  derivable from the receipt the way it is on mainnet.
- Header `gasLimit` is the sentinel `BATCH_GAS_LIMIT = 1 << 50` (`0x4000000000000`).
  `miner` is the zero address, `extraData` is empty, `sealFields` is empty.
- **Two block concepts**: L2 blocks (what `eth_getBlockByNumber` returns) and L1 batches
  (the proving unit), surfaced as `l1BatchNumber` / `l1BatchTimestamp` — and
  `l1BatchNumber` is `null` until the batch seals.
- The envelope is shaped like a **pre-Shanghai** Ethereum block. `withdrawalsRoot`,
  `blobGasUsed`, `excessBlobGas`, `parentBeaconBlockRoot` and `requestsHash` are all
  simply **absent**, not present-and-zeroed. Three chains now handle absent features three
  ways: OP Stack repurposes the field, Avalanche keeps it pinned to zero, zkSync drops it.

## What is marked `unrecorded`, and why

- **EIP-7883 (MODEXP repricing).** The emulator computes modexp gas from iteration count
  and operand size in its own Yul. Whether that schedule matches Osaka's *for the operand
  sizes zkSync still permits* was not established, and inferring "probably not" would be
  exactly the failure mode this dataset exists to avoid.
- **The system-contract list is the node's view, not era-contracts'.** The entries in
  `chain.yaml` are the addresses `zksync-era` references by name. The full L1-side and
  interop deployment sets in era-contracts are larger and were not enumerated.
- **`EXTCODESIZE(0x01) == 0` rests on a source comment, not a measurement.** The mask is
  implemented and cited for `EXTCODEHASH` (`AccountCodeStorage.getCodeHash`); the
  `extcodesize` half is asserted by the `Constants.sol` comment. Confirming it would need
  a deployed helper contract.
- **`chain.yaml` cannot express the two coexisting address-derivation rules.** Both are
  written into the `1014` note and the gotchas; there is no structural field for "which VM
  is the deployer".

## A note on evidence quality

The single most important zkSync fact — the 32-byte MODEXP circuit cap — lives in
`EvmEmulator.yul`. `tools/verify.py` only resolves `:suffix` references in
`.go/.java/.rs/.proto/.sol/.md` files, so `.yul` citations are accepted without being
checked. The path and the symbol are real and the greps below show them, but the verifier
is not what establishes them.

## Re-verify

```
git clone --depth 1 --branch core-v31.5.0 https://github.com/matter-labs/zksync-era
git clone --depth 1 --branch v0.153.14 https://github.com/matter-labs/zksync-protocol
mkdir era-contracts && cd era-contracts && git init && \
  git remote add origin https://github.com/matter-labs/era-contracts && \
  git fetch --depth 1 origin 101ab952b2c7b03e7648e30842f081042afc2d9a && \
  git checkout FETCH_HEAD && cd ..
# the era-contracts commit is not chosen: it is the submodule pin of the core tag
git -C zksync-era ls-tree HEAD contracts

# tx types, including the two outside EIP-2718's legal range
sed -n '60,85p' zksync-era/core/lib/types/src/lib.rs

# address derivation: zkSync's rules...
sed -n '/function getNewAddressCreate2(/,/^    }/p;/function getNewAddressCreate(/,/^    }/p' \
  era-contracts/system-contracts/contracts/ContractDeployer.sol
grep -n "CREATE2_PREFIX\|CREATE_PREFIX\|CREATE2_EVM_PREFIX" \
  era-contracts/system-contracts/contracts/Constants.sol
# ...and mainnet's rules, for EVM-emulated deployers, on the same chain
sed -n '/function getNewAddressCreate2EVM/,/^    }/p;/function getNewAddressCreateEVM/,/^    }/p' \
  era-contracts/system-contracts/contracts/libraries/Utils.sol

# THE proof constraint, in the source's own words
grep -n -B 3 -A 4 "MAX_MODEXP_INPUT_FIELD_SIZE" era-contracts/system-contracts/contracts/EvmEmulator.yul
grep -n "violates EVM equivalence" era-contracts/system-contracts/contracts/EvmEmulator.yul

# emulator opcode gaps
grep -n "case 0xFF\|case 0xF2" era-contracts/system-contracts/contracts/EvmEmulator.yul
grep -n -A 2 "function PREVRANDAO_VALUE" era-contracts/system-contracts/contracts/EvmEmulator.yul

# the precompile mask, and where it stops
grep -n -B 4 "CURRENT_MAX_PRECOMPILE_ADDRESS" era-contracts/system-contracts/contracts/Constants.sol
sed -n '/function getCodeHash/,/^    }/p' era-contracts/system-contracts/contracts/AccountCodeStorage.sol

# EraVM: 17 opcode families, kernel space, ergs
sed -n '1,22p' zksync-protocol/crates/zkevm_opcode_defs/src/definitions/all.rs
grep -n "ADDRESS_UNRESTRICTED_SPACE\|MAX_TX_ERGS_LIMIT\|ERGS_PER_CIRCUIT\|MAX_PUBDATA_PER_BLOCK" \
  zksync-protocol/crates/zkevm_opcode_defs/src/system_params.rs

# system contract addresses, and the fee/batch constants
grep -n "0x80\|0x01, 0x00" zksync-era/core/lib/constants/src/contracts.rs
grep -n "BATCH_GAS_LIMIT" zksync-era/core/lib/multivm/src/versions/vm_latest/constants.rs

# native AA
grep -n "function" era-contracts/system-contracts/contracts/interfaces/IAccount.sol
```

Live probes, all at block `71584105` on `https://mainnet.era.zksync.io`:

```
R=https://mainnet.era.zksync.io; B=0x4444969
c(){ curl -s -X POST $R -H 'content-type: application/json' -d "$1"; echo; }

# precompiles have bytecode over RPC; 0x03/0x09/0x0a/0x0b-0x11 have none
for n in 01 02 03 04 05 06 07 08 09 0a 0b 0f 11; do
  c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x00000000000000000000000000000000000000$n\",\"$B\"]}"; done
# 0x0100 is above the 0xff mask and has real code
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x0000000000000000000000000000000000000100\",\"$B\"]}"

# kernel space reverts; ordinary empty addresses do not
for a in 0x0000000000000000000000000000000000000003 0x000000000000000000000000000000000000ffff \
         0x00000000000000000000000000000000deadbeef; do
  c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"$a\",\"data\":\"0x1234\"},\"$B\"]}"; done

# the EVM emulator is live on mainnet; and the pre-Shanghai block envelope
c '{"jsonrpc":"2.0","id":1,"method":"zks_getProtocolVersion","params":[]}'
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",false]}"
```
