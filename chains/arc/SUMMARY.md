# Arc — the same brief as Tempo, the opposite answer

Client pinned: `circlefin/arc-node` **v0.7.3**, commit
`79b6fddf18345732007bb94b4af3add4c2efd12d`, Rust, built on `paradigmxyz/reth`
**tag v1.11.3** (a released tag, not a floating rev). Apache-2.0.

**Mainnet (5042) is not live.** `https://rpc.arc.network` does not resolve; chain
id 5042 exists in this tag as a constant and a hardfork table and nothing else.
Circle's announced public-mainnet date is 2026-09-16. Every live fact below comes
from the **public testnet, 5042002**, probed at block **58728247** (`0x3801f37`,
`finalized`). The row is `live: false` and every `src_live:` should be read as
"the testnet does this".

Tempo and Arc were briefed as the same problem — *what happens to the EVM when the
gas asset is a 6-decimal stablecoin*. They answer it in opposite directions, and
having both rows is worth more than either alone.

- **Tempo deleted the native asset.** `value` is rejected at admission, `BALANCE`
  is permanently zero, gas is settled in a token precompile, and the base fee is
  denominated in a unit that is not any asset.
- **Arc kept the native asset and made it USDC.** `msg.value` works. `BALANCE`
  works. `CALL` with value works. `baseFeePerGas` is 18-decimal units of the coin.
  The EVM is untouched.

Arc's cost is not a missing feature. It is a **duplicated unit**.

---

## 1. The ERC-20 balance is a floored copy of the real one

The native coin is 18-decimal. The ERC-20 view of it — `NativeFiatToken` at
`0x3600…0000`, symbol `"USDC"` — reports **6 decimals**. Measured at the pinned
block, on three unrelated accounts:

| account | `eth_getBalance` | `USDC.balanceOf` |
|---|---:|---:|
| `0xa693cc18…` (proposer) | 5028673577309960459376547 | 5028673577309 |
| `0x5d56c534…` (sender) | 808717034443278127 | 808717 |
| `0x1c831f75…` (recipient) | 3048802109906077411 | 3048802 |

The relationship is `balanceOf(a) == eth_getBalance(a) // 10^12` — **integer
division, exact in none of the three cases.** Minting happens in whole
microdollars (`totalSupply` does divide exactly: 314870942069315201 × 10¹²) but gas
refunds and priority fees are arbitrary wei, so live accounts accumulate
sub-microdollar dust that the token interface cannot see and cannot move.
`transfer`ring your entire ERC-20 balance does not empty your account, and any
reconciliation treating the ERC-20 view as authoritative will find unexplained
residue forever.

Nothing about this is in the pinned Rust. The 10¹² flooring lives in the
`NativeFiatToken` Solidity contract, whose **source is not in this repository** —
the client knows only its address, as a constant the precompiles compare `caller`
against. This finding is `src_live:` only, and that is recorded as such.

## 2. One transfer, two `Transfer` events, two different amounts

The first transaction in the probed block is an ordinary ERC-20
`transfer(0x1c831f75…, 78775)` to `0x3600…0000`. Its receipt carries **two logs**:

```
log[0]  address 0xfffffffffffffffffffffffffffffffffffffffe   (EIP-7708 system address)
        Transfer(from, to)  data 0x0117dd71f42e7000  = 78,775,000,000,000,000
log[1]  address 0x3600000000000000000000000000000000000000   (the USDC ERC-20)
        Transfer(from, to)  data 0x00000133b7        = 78,775
```

Same movement. Same topic hash. Two amounts, 10¹² apart. An indexer that
subscribes to the `Transfer` topic without filtering by address double-counts
every native movement on this chain *and* mis-scales one of the two copies.

Arc adopts **EIP-7708** (native transfers emit ERC-20-shaped logs), which is not on
mainnet Ethereum, because when the native coin *is* a stablecoin you want native
movement to be indexable like a token. But **adoption is partial**: the log is
emitted by `SELFDESTRUCT` (Zero5+) and by the NativeCoinAuthority mint/burn/transfer
paths, and **not** by an ordinary `CALL` carrying value. So "index native movement
from logs" works for some native movement.

## 3. The base fee lives in `extraData`

From the Zero5 hardfork, the header's `extraData` must be **exactly 8 bytes**, and
those bytes are the base fee the *child* block must use:

```rust
// crates/execution-validation/src/consensus.rs
fn arc_validate_extra_data_format(…)   // "invalid extra_data length {len}: must be 8 bytes"
let Some(expected_base_fee) = decode_base_fee_from_bytes(parent.extra_data()) else { … };
// … and the child's base_fee_per_gas must match exactly
```

Observed: `extraData = 0x00000004a817c800` = 20,000,000,000, and
`baseFeePerGas = 0x4a817c800` = the same number. A header field that mainnet leaves
free-form for client vanity strings is consensus-critical here, and the usual
"decode extraData as UTF-8 to identify the client" heuristic returns garbage.

## 4. The fee market: EMA-smoothed, fixed-point, and governed by a contract

Three changes to EIP-1559 at once:

1. The controller input is an **exponential moving average** of gas used,
   `(1-α)·G[t-1] + α·G[t]`, not the parent's raw figure — so the base fee tracks a
   trend rather than one block. `determine_ema_parent_gas_used`.
2. `max_change_denominator` and `elasticity_multiplier` are replaced by fixed-point
   `k_rate` and `inverse_elasticity_multiplier` against a scale of 10,000, letting
   the gas target be an arbitrary fraction of the gas limit instead of exactly half.
   `arc_calc_next_block_base_fee`.
3. The result is **bounded by `FeeParams` read out of a contract**.
   `retrieve_fee_params` calls ProtocolConfig at `0x3600…0001` from the system
   address, and the block gas limit comes from the same contract's storage. Probing
   the ERC-7201 gas-limit slot at the pinned block returns `0x1c9c380` = 30,000,000
   — exactly the header's `gasLimit`. ProtocolConfig is an **ERC-1967 proxy**, so
   the gas limit and the fee-market bounds are upgradeable by whoever holds the
   proxy admin, with no client release.

The base fee held flat at 20 gwei across the probed window while `gasUsedRatio`
moved from 0.017 to 0.19 and back — consistent with the smoothing.

## 5. A blocklist that reaches into block validity

`NativeCoinControl` at `0x1800…0001` holds a blocklist, and its effects are not
confined to the precompile:

- **Pre-execution, per transaction.** `check_blocklist` rejects if the caller is
  blocklisted, or — when `value != 0` — if the recipient is. Before nonce, before
  execution.
- **Inside SELFDESTRUCT.** The Arc instruction checks both the executing address
  and the beneficiary and fails with `"Blocked address"`.
- **Per block.** `validate_beneficiary_not_blocklisted` SLOADs the *block
  proposer's* blocklist slot and **rejects the entire block** if it is set (Zero5+).
  A validator that gets blocklisted stops being able to produce valid blocks.

The SLOADs are **unmetered** — a documented choice ("Blocklist SLOADs are unmetered
— no extra gas is added for blocklist checks"), which matters for worst-case
block-validation cost modelling.

Then there is a **second, independent blocklist that is not consensus at all**. The
`--arc.denylist.address` / `--arc.denylist.storage-slot` flags point the mempool and
a revm pre-flight at an arbitrary contract's ERC-7201 mapping. Two nodes configured
differently accept different transactions — SCHEMA.md's config-switchable warning,
applied to censorship instead of to signatures. It is not deployed at the default
address on testnet.

## 6. `msg.sender` is not proof of a signature (Zero7)

`CallFrom` at `0x1800…0003` is a **subcall precompile** — a category this dataset
has not carried. It is not in the precompile map at all; it lives in a separate
`SubcallRegistry` because it has to run a child EVM call and post-process the
result. Its interface is:

```solidity
function callFrom(address sender, address target, bytes calldata data)
    external returns (bool success, bytes memory returnData);
```

It executes `target` with `msg.sender == sender`. The guard is an allow-list of
**two hardcoded CREATE2 addresses compiled into the node**:

```rust
AllowedCallers::Only(HashSet::from([MEMO_ADDRESS, MULTICALL3_FROM_ADDRESS]))
```

Both are deployed on testnet. This does not change *who authorizes a transaction* —
that is still one secp256k1 signature — but it does mean `msg.sender` inside a
called contract is not evidence that that address signed anything, which is an
assumption a great deal of Solidity rests on. The allow-list is in consensus code,
not on chain, so it cannot be inspected or changed from the chain.

## 7. The first post-quantum precompile in the dataset

`0x1800…0004`, gated on Zero6: `verifySlhDsaSha2128s(bytes vk, bytes message,
bytes sig)` — FIPS 205 SLH-DSA-SHA2-128s, hash-based post-quantum signatures. Gas
is priced against the hash count the scheme implies rather than as a flat fee, and
the doc comment calls it experimental. It is `authorizes: never`, which is the
ordinary state of a verifier precompile — and worth stating precisely because the
Tempo row, written from the same brief, shows the *opposite* pairing on the same
axis (a scheme that authorizes with no verifier to match).

## 8. Mainnet and testnet do not run the same protocol

`ARC_MAINNET_HARDFORKS` gives chain 5042 Zero3, Zero4, Osaka, Zero5, Zero6 — all at
genesis — and **stops**. Zero7 and Zero8 are not in the mainnet table at this tag.
Testnet has been through Zero3..Zero7 on a real timeline and is running Zero7 now.

So CallFrom, Multicall3From, Memo and the Zero7 SELFDESTRUCT variant — everything in
§6 — are **live on testnet and not scheduled for mainnet genesis**. Anyone treating
testnet as a preview of mainnet is testing against a superset.

The activation *mechanism* is mixed too: Zero3/Zero4 by block; Zero5/Zero6 by block
on mainnet but by **timestamp** on testnet; Zero7+ by timestamp everywhere. The
client explains why — a block-based fork declared after a timestamp fork breaks
`ForkFilter`'s BTreeMap ordering and corrupts the EIP-2124 fork id — and
`is_arc_fork_active` has to OR both checks, "because a bare
`is_fork_active_at_block` silently returns false for timestamp-activated forks, so
the corresponding EVM/validation behaviour would never trigger."

## 9. `baseline_fork` is Osaka, and the client's own comments say Prague

The `ArcHardfork` enum annotates its variants "align to Ethereum Prague". The
schedule does not agree: `BASE_FORKS` stops at Prague and every network table then
inserts `EthereumHardfork::Osaka` — at `Timestamp(0)` for mainnet, at 1779890400 for
testnet — paired with Zero5. Confirmed live: P256VERIFY answers at `0x0100` with
EIP-7951 empty-on-invalid semantics, and the client asserts the negative case too
(`test_p256_precompile_not_available_with_prague`).

Source over comment, as usual.

## Smaller findings worth the line

- **`parentBeaconBlockRoot` is the parent block hash.** Not zero, not a beacon
  root. The EIP-4788 ring-buffer contract holds no code, so nothing consumes it,
  and no contract can read the value back. Anyone treating a non-zero value as
  evidence of a beacon chain is wrong here.
- **`eth_getCode` at an Arc precompile returns `0x01`.** Every address in
  `0x1800…000{0..4}` carries one byte of marker code and `EXTCODESIZE == 1`, while
  the inherited Ethereum precompiles return `0x`. Same inversion as Tempo's `0xef`,
  a different byte — and `0x01` as bytecode is a bare `ADD` that would underflow
  the stack, where `0xef` is the EOF-reserved prefix. The dataset now has six
  distinct fake-code shapes at precompile addresses.
- **KZG works on a chain that rejects blobs**, exactly as on Tempo — `0x0a` is
  present and errors on garbage while `.no_eip4844()` keeps blob transactions out
  of the pool. Note the removal here is *weaker* than Tempo's: it is a mempool
  policy, not an envelope that lacks the variant.
- **No Arc-specific transaction type exists.** For a chain whose pitch is
  stablecoin payments, that is a real finding: no fee-payer type, no sponsored
  type, no batch type. Batching and sender-spoofing are ordinary transactions to
  the Multicall3From contract. 586 transactions across 50 blocks were `{0x0: 355,
  0x2: 231}` — 60% legacy.
- **Receipts are stock.** No added fields, in contrast to Tempo's `feeToken` and
  `feePayer`.
- **The supply authority is one upgradeable contract.** The NativeCoinAuthority
  precompile refuses any caller other than `0x3600…0000`, and that address is an
  ERC-1967 proxy. Mint, burn, blocklist and the ERC-20 interface all sit behind one
  upgrade key.

## Not established here

- **Mainnet behaviour, at all.** Mainnet does not exist. The mainnet fork table is
  read from source; nothing about mainnet is live-verified, and the schedule may
  change before 2026-09-16.
- **The `NativeFiatToken` Solidity source.** Not in this repository. The 6-decimal
  ERC-20 view, the 10¹² flooring, and the mint/blocklist authorisation logic are
  established by live probe and by the precompile's `ALLOWED_CALLER_ADDRESS` check
  only — the contract itself is a black box with 3,598 bytes of runtime.
- **Whether a plain value-bearing CALL emits any log.** Argued from source (only
  SELFDESTRUCT and the precompile paths call the log constructors) but not probed —
  no value-bearing CALL was found in the scanned range. Recorded in `eips.7708` as
  partial adoption rather than asserted as absent.
- **EIP-4895 withdrawal handling.** The list is empty with the empty-trie root, but
  unlike Tempo no active rejection was traced. `unrecorded`.
- **EIP-2930 (`0x01`).** Not observed in the scanned range and nothing in the client
  excludes it. `unrecorded` rather than assumed inherited.
- **EIP-7623.** Not traced. `unrecorded`.
- **Whether the base fee is burned.** `fee_model.burn: unrecorded` — the destination
  of the base fee was not followed through the executor. On a chain where the base
  fee is a stablecoin this is a materially interesting question and it is left open.
- **The running testnet version.** `web3_clientVersion` returns only `arc/v1`, so
  the pinned tag cannot be matched to what testnet validators run — the gap Tempo's
  row was able to close.

## What this contradicts elsewhere in the dataset

- **"Stablecoin gas chain" is not one category.** Arc and Tempo share a pitch, a
  consensus family, a language and an execution client, and diverge completely on
  the question that matters. Any aggregate row that groups them will be wrong about
  one of them.
- **`eth_getCode` at a precompile now has a sixth shape** (`0x01`). Together with
  Tempo's `0xef` marker, two of the newest rows in the dataset both write fake code
  at precompile addresses *as a marker*, not as an ABI stub — a different pattern
  from Flare/Sonic/Cosmos EVM/Moonbeam and one that a size heuristic cannot
  separate from a genuine one-byte contract.
- **Header `extraData` can be consensus data.** Any tool that reads it as a client
  identity string is wrong on this chain.

---

## Re-verify

```sh
cd /Volumes/TendiesTown/EVM-intel/chains/arc/repos/arc-node
git rev-parse HEAD          # 79b6fddf18345732007bb94b4af3add4c2efd12d
git describe --tags         # v0.7.3
grep -n 'reth-chainspec' Cargo.toml    # tag = "v1.11.3"

# 1/2. the native coin is 18-decimal; the ERC-20 view is a separate contract
grep -n -A3 'NATIVE_FIAT_TOKEN_ADDRESS' crates/precompiles/src/helpers.rs
grep -n 'ALLOWED_CALLER_ADDRESS' crates/precompiles/src/native_coin_authority.rs
grep -n '18 decimals' contracts/src/mocks/PrecompileCallCode.sol
ls contracts/src        # note: no NativeFiatToken.sol — the ERC-20 is not in this repo

# 2. EIP-7708 logs, and where they are (and are not) emitted
sed -n '/create_eip7708_transfer_log/,/^}/p' crates/evm/src/log.rs
grep -rn 'create_eip7708_transfer_log\|create_native_transfer_log' crates/evm/src crates/precompiles/src

# 3. base fee in extraData
grep -n -A8 'fn encode_base_fee_to_bytes' crates/execution-config/src/gas_fee.rs
grep -n -B2 -A12 'fn arc_validate_extra_data_format' crates/execution-validation/src/consensus.rs

# 4. EMA smoothing, fixed-point 1559, contract-governed params
grep -n -A20 'fn determine_ema_parent_gas_used' crates/execution-config/src/gas_fee.rs
grep -n -A20 'fn arc_calc_next_block_base_fee' crates/execution-config/src/gas_fee.rs
grep -n 'BASE_FEE_CONFIG_MAINNET\|BASE_FEE_CONFIG_TESTNET\|block_gas_limit_config' \
     crates/execution-config/src/chainspec.rs
grep -n 'PROTOCOL_CONFIG_ADDRESS\|fn retrieve_fee_params\|fn determine_bounded_base_fee' \
     crates/execution-config/src/protocol_config.rs

# 5. the two blocklists
grep -n -A20 'fn check_blocklist' crates/evm/src/handler.rs
grep -n 'Blocklist SLOADs are unmetered' crates/evm/src/handler.rs
grep -n -A25 'fn validate_beneficiary_not_blocklisted' crates/evm/src/executor.rs
grep -n 'DEFAULT_DENYLIST_ADDRESS\|DEFAULT_DENYLIST_ERC7201_BASE_SLOT\|ERR_DENYLISTED_ADDRESS' \
     crates/execution-config/src/addresses_denylist.rs

# 6. CallFrom and its two hardcoded callers
grep -n -A12 'fn build_subcall_registry' crates/evm/src/evm.rs
cat crates/execution-config/src/call_from.rs | tail -10

# 7. the post-quantum precompile
grep -n -A10 'interface IPQ' crates/precompiles/src/pq.rs
grep -n -A6 'PQ_ADDRESS =>' crates/precompiles/src/precompile_provider.rs

# 8/9. two fork schedules; Osaka despite the "Prague" comments
sed -n '/pub static ARC_MAINNET_HARDFORKS/,/^});/p' crates/execution-config/src/hardforks.rs
sed -n '/pub static ARC_TESTNET_HARDFORKS/,/^});/p' crates/execution-config/src/hardforks.rs
grep -n 'align to Ethereum Prague' crates/execution-config/src/hardforks.rs
grep -n 'HARDFORK_.*_ACTIVATION_TESTNET' crates/execution-config/src/hardforks.rs
grep -n -A12 'fn is_arc_fork_active' crates/execution-config/src/hardforks.rs

# SELFDESTRUCT override; blobs off at the pool
grep -n -B6 -A10 'fn arc_network_selfdestruct_impl' crates/evm/src/opcode.rs
grep -n 'no_eip4844' crates/execution-txpool/src/pool.rs

# precompile addresses, as the contracts see them
cat contracts/src/Precompiles.sol | tail -10
```

```sh
# TESTNET (5042002) — mainnet does not exist yet
RPC=https://rpc.testnet.arc.network
B=0x3801f37          # 58728247
call() { curl -s -X POST $RPC -H 'Content-Type: application/json' \
         -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}"; echo; }

call eth_chainId '[]'                 # -> 0x4cef52 (5042002)
call web3_clientVersion '[]'          # -> "arc/v1" — no version detail, cannot match the tag
curl -s -m 10 https://rpc.arc.network -X POST -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}'   # -> nothing; mainnet is not up

# THE headline: the ERC-20 view is floor(native / 10^12), exact in none of these
for a in a693cc18aa09d33dd388013b7a02e5ff863b8760 \
         5d56c5348a4f17e21f00ef04222baff247163691 \
         1c831f75f24f5ca0ee088f201e691a6c55aff0b5; do
  call eth_getBalance "[\"0x$a\",\"$B\"]"
  call eth_call "[{\"to\":\"0x3600000000000000000000000000000000000000\",
                   \"data\":\"0x70a08231000000000000000000000000$a\"},\"$B\"]"
done
# 5028673577309960459376547 / 5028673577309
#      808717034443278127   /      808717
#     3048802109906077411   /     3048802

call eth_call '[{"to":"0x3600000000000000000000000000000000000000","data":"0x313ce567"},"0x3801f37"]' # 6
call eth_call '[{"to":"0x3600000000000000000000000000000000000000","data":"0x95d89b41"},"0x3801f37"]' # "USDC"
call eth_call '[{"to":"0x3600000000000000000000000000000000000000","data":"0x18160ddd"},"0x3801f37"]' # 6dp
call eth_call '[{"to":"0x1800000000000000000000000000000000000000","data":"0x18160ddd"},"0x3801f37"]' # 18dp
#   the second is exactly the first x 10^12

# one transfer, two Transfer logs, two amounts
call eth_getTransactionReceipt '["0x134f1abe4d0c4445c7b55702712550868dd039547510dec3b35cdb25b7bdcd24"]'
#   log[0] address 0xfffffffffffffffffffffffffffffffffffffffe data 0x0117dd71f42e7000 (78775e12)
#   log[1] address 0x3600000000000000000000000000000000000000 data 0x133b7            (78775)

# header: extraData IS the next base fee; parentBeaconBlockRoot IS the parent hash
call eth_getBlockByNumber '["0x3801f37",false]'
#   extraData 0x00000004a817c800 == baseFeePerGas 0x4a817c800 (20 gwei)
#   parentBeaconBlockRoot == parentHash;  gasLimit 0x1c9c380;  withdrawals []

# the gas limit really does come out of ProtocolConfig's storage
call eth_getStorageAt '["0x3600000000000000000000000000000000000001",
  "0x668f09ce856848ead6cb1ddee963f15ef833cea8958030868f867aec84385203","0x3801f37"]'  # -> 0x1c9c380
call eth_getStorageAt '["0x3600000000000000000000000000000000000001",
  "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc","0x3801f37"]'  # ERC-1967 impl

# base fee flat while gasUsedRatio swings — the EMA
call eth_feeHistory '["0x4","0x3801f37",[10,50]]'
call eth_gasPrice '[]'

# precompiles carry 0x01; Ethereum's carry nothing
for a in 1800000000000000000000000000000000000000 1800000000000000000000000000000000000001 \
         1800000000000000000000000000000000000002 1800000000000000000000000000000000000003 \
         1800000000000000000000000000000000000004; do
  call eth_getCode "[\"0x$a\",\"$B\"]"; done                 # all -> 0x01
call eth_getCode '["0x0000000000000000000000000000000000000001","0x3801f37"]'   # -> 0x
call eth_getCode '["0x0000000000000000000000000000000000000100","0x3801f37"]'   # -> 0x
call eth_call '[{"to":"0x00000000000000000000000000000000000face8",
                 "data":"0x0000000000000000000000001800000000000000000000000000000000000000"},
                "0x3801f37",{"0x00000000000000000000000000000000000face8":{"code":"0x5f353b5f5260205ff3"}}]'
#   EXTCODESIZE(NativeCoinAuthority) -> 1

# the precompiles answer
call eth_call '[{"to":"0x1800000000000000000000000000000000000001",
  "data":"0x8e204c430000000000000000000000000000000000000000000000000000000000000000"},"0x3801f37"]'  # isBlocklisted(0x0) -> false
call eth_call '[{"to":"0x1800000000000000000000000000000000000002",
  "data":"0x805108150000000000000000000000000000000000000000000000000000000003801f36"},"0x3801f37"]' # getGasValues(parent)
call eth_call '[{"to":"0x1800000000000000000000000000000000000004","data":"0x"},"0x3801f37"]'
#   -> revert "Input too short"  (PQ precompile is present)

# Osaka is live: P256VERIFY answers with EIP-7951 semantics; KZG present despite no blobs
call eth_call '[{"to":"0x0000000000000000000000000000000000000100","data":"0x'$(printf '00%.0s' {1..160})'"},"0x3801f37"]'  # -> 0x
call eth_call '[{"to":"0x000000000000000000000000000000000000000a","data":"0x'$(printf '00%.0s' {1..192})'"},"0x3801f37"]'  # -> PrecompileError

# Zero7 contracts exist on testnet; the node-configurable Denylist does not
call eth_getCode '["0x522fAf9A91c41c443c66765030741e4AaCe147D0","0x3801f37"]'   # Multicall3From — deployed
call eth_getCode '["0x5294E9927c3306DcBaDb03fe70b92e01cCede505","0x3801f37"]'   # Memo — deployed
call eth_getCode '["0x36059b615370eB999e8eC0c9401835B407834221","0x3801f37"]'   # Denylist — 0x

# 4788 dead, 2935 alive, 7002/7251 absent
call eth_getCode '["0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02","0x3801f37"]'   # -> 0x
call eth_getCode '["0x0000F90827F1C53a10cb7A02335B175320002935","0x3801f37"]'   # -> standard runtime
call eth_getCode '["0x00000961Ef480Eb55e80D19ad83579A64c007002","0x3801f37"]'   # -> 0x
call eth_getCode '["0x0000BBdDc7CE488642fb579F8B00f3a590007251","0x3801f37"]'   # -> 0x

# tx type census: 58728247..58728296 -> 586 txs, {0x0: 355, 0x2: 231}
for n in 3801f37 3801f38 3801f39 3801f3a; do call eth_getBlockByNumber "[\"0x$n\",true]"; done
```
