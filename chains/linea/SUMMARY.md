# Linea — a stock EVM behind a prover that vetoes what it cannot prove

**Chain ID 59144 · role: `fork` · baseline: Osaka · QBFT (Maru), 1s blocks**

Reference: [LFDT-Lineth/lineth-monorepo `releases/linea-besu-package/v2.1.1`](https://github.com/LFDT-Lineth/lineth-monorepo)
@ `0f74f554`, with [besu-eth/besu](https://github.com/besu-eth/besu) @ `6580da84` — the
exact commit that monorepo pins — cloned alongside as the EVM.

## The client is not what CANDIDATES.md said, and that is the first finding

`Consensys/linea-besu` is **archived**. Its last release is `25.3-delivery51`, March
2025. Linea no longer forks Besu at all: `linea-besu/besu/build.gradle` resolves
`besuCommit` from `gradle/libs.versions.toml` and consumes **upstream Hyperledger Besu
unmodified**, adding behaviour through plugins. Upstream Besu returns the favour by
shipping Linea as a **built-in network** — `NetworkDefinition.LINEA_MAINNET`, with
`config/src/main/resources/linea-mainnet.json` holding the genesis and the fork
schedule.

Two other coordinates moved: `Consensys/linea-monorepo` is now
`LFDT-Lineth/lineth-monorepo` under LF Decentralized Trust, and `hyperledger/besu` is
now `besu-eth/besu`. Java packages went from `net.consensys.linea` to `lineth`.

The consequence for this dataset is structural. Grep the entire Linea tree for
`PrecompileContractRegistry`, `PrecompiledContract` or `MainnetPrecompiledContracts`
and you get **nothing**. There is no Linea EVM to diff. Every divergence below is a
plugin or a config file.

## Proof constraints did leak into consensus — as a budget, not a cap

`linea-besu/package/linea-besu/config/trace-limits.mainnet.toml` is the whole story on
one page. It is the prover's per-block capacity, expressed as a line count per
arithmetization module, and the sequencer refuses to build a block that exceeds it.

Two of those numbers are **zero**:

```
PRECOMPILE_RIPEMD_BLOCKS          = 0
PRECOMPILE_BLAKE_EFFECTIVE_CALLS  = 0
PRECOMPILE_BLAKE_ROUNDS           = 0
```

So **RIPEMD160 (`0x03`) and BLAKE2F (`0x09`) can never appear in a Linea block.** The
tracer says so in its own words: `ZkCounter.uncheckedModules()` skips counting
`blakeRounds` "because blakeEffectiveCall is counted and **already rejects all BLAKE
calls**."

`TraceLineLimitTransactionSelector` turns an overflow into
`TX_MODULE_LINE_COUNT_OVERFLOW`, drops the transaction from the pool, and caches its
hash in `InvalidTransactionByLineCountCache` so it is never reconsidered.

### And yet it works in `eth_call`

```
eth_call to 0x03 with empty input, @ block 31744343
-> 0x0000000000000000000000009c1185a5c5e9fc54612808977ee8f548b2258d31
```

That is the correct RIPEMD160 of the empty string. The EVM is stock Besu; it computes
the right answer. Only *inclusion* is impossible.

This is the nastiest shape a divergence can take on this chain, and **the schema has no
word for it.** `removed` says the precompile is absent — it is not. `modified` says the
semantics differ — they are exact. Every simulation-based tool on earth (`eth_call`,
`eth_estimateGas`, forked-node testing, local Hardhat/Foundry suites) reports success
for code that cannot be mined. The row records `removed`, because that is the fact that
governs on-chain, and carries a note explaining the other half.

### The rest of the budget is a throughput cap, not an on/off switch

| Budget | Per block |
|---|---|
| `PRECOMPILE_MODEXP_EFFECTIVE_CALLS` | 64, of which at most **2** may have any operand > 32 bytes |
| `PRECOMPILE_ECPAIRING_MILLER_LOOPS` | 128, with 32 final exponentiations |
| `PRECOMPILE_ECMUL_EFFECTIVE_CALLS` | 80 |
| `PRECOMPILE_P256_VERIFY_EFFECTIVE_CALLS` | 256 |
| `PRECOMPILE_BLS_PAIRING_CHECK_MILLER_LOOPS` | 16 |
| `BLOCK_TRANSACTIONS` | **300**, regardless of gas |
| `BLOCK_L1_SIZE` | 120000 compressed bytes |

Compare OP Stack, which caps a *single call's input size* so the call reverts. Linea
caps *aggregate work per block* so the transaction is never selected. Same cause —
"the prover cannot do this much" — two different consensus mechanisms, and two
different failure signals: OP reverts inside the EVM, Linea returns nothing at all.

### The MODEXP cap that used to exist is gone, absorbed by an Ethereum EIP

`ModexpMetadata.getMaxInputSize()` now returns
`TraceOsaka.EIP_7823_MODEXP_UPPER_BYTE_SIZE_BOUND` — 1024 bytes, mainnet's own Osaka
bound. Linea's historic 512-byte modexp restriction is no longer a Linea restriction;
Ethereum adopted a bound of its own and Linea's prover fits inside it. A proving
constraint became a mainnet EIP, and the divergence closed itself.

## The one that will silently lose money: relocated Prague predeploys

The bundled `linea-mainnet.json` overrides three addresses:

```json
"depositContractAddress":             "0x94d4a7449B968b839dcbc64A61F195CA300986ae",
"withdrawalRequestContractAddress":   "0x66355689a9f067eeb9dc9d899E4192676988279C",
"consolidationRequestContractAddress":"0xF0e003F0dE2d583Ae28FA8cBF66aa096CdAce3ff"
```

These are not documentation. `MainnetProtocolSpecs.pragueDefinition` wires the
EIP-6110/7002/7251 request processors to whatever `RequestContractAddresses.fromGenesis`
returns, so Besu genuinely runs them here. Live at block 31744343, all three hold 2227
bytes of code beginning `0x608060405236610013` — Solidity proxies, *not* mainnet's
hand-written request-predeploy assembly.

And the canonical mainnet addresses:

```
0x00000961Ef480Eb55e80D19ad83579A64c007002 (EIP-7002) -> 0x   EMPTY
0x0000BBdDc7CE488642fb579F8B00f3a590007251 (EIP-7251) -> 0x   EMPTY
```

EIP-7002's contract answers a zero-calldata `staticcall` with the current request fee.
An **empty account answers the same call with success and no return data**, which every
caller parses as zero. So a withdrawal-request client written against mainnet — all of
them — reads a fee of zero, succeeds, and submits a request into the void. No revert, no
error. This is the same failure shape as Hyperliquid's empty `0x0100`, reached
independently by a completely different route.

EIP-2935 (`0x0000F90827…2935`) and EIP-4788 (`0x000F3df6…Beac02`) are at their canonical
addresses with the canonical `0x3373ffffffffffffff…` prologue — Besu does not take those
from genesis, so they could not drift.

`parentBeaconBlockRoot` is **zero in every header**. The 4788 contract is present,
callable, and permanently meaningless.

## `extraData` is a pricing channel

Observed at block 31744343:

```
extraData = 0x01 00007530 000f4240 0000a3b0 0000...
             ^v1 ^fixed   ^variable ^L1 gas price
```

`LineaExtraDataHandler.Version1Consumer` parses it as `VERSION(1) FIXED_COST(4)
VARIABLE_COST(4) ETH_GAS_PRICE(4)`, all in kWei, and — when
`plugin-linea-extra-data-set-min-gas-price-enabled` is on, as it is on mainnet — uses
the last field to **set the node's minimum gas price**. An unrecognised version byte
raises `LineaExtraDataException`.

So the L1 gas price travels into L2 consensus inside a header field that mainnet
treats as free-form vanity bytes. This is Linea's analogue of OP Stack repurposing
`blobGasUsed`, on a different field — the second independent instance of that pattern
in the dataset.

## The fee model where the base fee is decoration

```
baseFeePerGas @ 31744343 = 0x7          (7 wei)
eth_gasPrice  @ 31744343 = 0x4c335f9    (79,771,129 wei)
```

Four orders of magnitude apart. EIP-1559 is nominally active and carries almost none of
the price. The floor comes from `min-gas-price` (10,000,000 wei), the extraData-driven
update, and `ProfitabilityValidator`, which simulates the transaction and rejects it
unless the fee covers `fixedCost + variableCost × compressedSize` times a margin
(mainnet: `plugin-linea-min-margin=1.0`, `plugin-linea-tx-pool-min-margin=0.8`).

A transaction priced off `baseFeePerGas` is not mined late. It is **rejected from the
pool and disappears**.

## Smaller things that still break integrations

- **You cannot send a transaction to a precompile.** `PrecompileAddressValidator`
  rejects any transaction whose `to` is one of `0x01`–`0x11` or `0x0100`. On mainnet
  this is legal and harmless.
- **Blob transactions (`0x03`) are rejected** — `DEFAULT_BLOB_TX_ENABLED = false`, and
  the rule is registered through Besu's `TransactionValidatorService`, which the
  plugin's own javadoc says applies "during block import and transaction selection".
  `blobGasUsed`/`excessBlobGas` stay in the header at zero.
- **EIP-7702 is on** (`DEFAULT_DELEGATE_CODE_TX_ENABLED = true`), and the prover has an
  `RLP_AUTH` module budget for it. The same switch that killed blobs is set the other
  way here.
- **Per-transaction caps invisible in the header**: 60,000 bytes of calldata,
  24,000,000 gas.
- **Zero custom transaction types.** Linea took nothing from the `0x7f` ceiling. Its
  envelope is mainnet's *minus* a type (no blobs) rather than plus one — the opposite
  direction from Arbitrum `0x78`, Base `0x79`, OP `0x7e` and Polygon `0x7f`.
- **Forced inclusion exists**: `linea_sendForcedRawTransaction` and
  `linea_getForcedTransactionInclusionStatus`. Whether that path bypasses the
  module-limit rejection is **unrecorded**.

## Fork names, for once, do not lie

| Fork | Activation |
|---|---|
| london | genesis (block 0) |
| paris | TTD 49575263 |
| shanghai | 1761213600 |
| cancun | 1761645600 |
| prague | **1761646200** |
| osaka | 1764798551 |

Linea invented no fork names — the only chain here that reuses Ethereum's exactly, and
Maru's beacon genesis carries the same schedule as an `elFork` string per timestamp, so
the mapping is doubly attested.

Cancun and Prague are **600 seconds** apart. "Cancun-era Linea" describes a ten-minute
window nobody built against.

## What is marked `unrecorded`, and why

- **EIP-7928 / Amsterdam.** Besu at this commit threads `BalConfiguration` through
  `MainnetProtocolSpecs`, but no Amsterdam timestamp exists in `linea-mainnet.json` and
  nothing established which fields are live. Not guessed.
- **`gasLimit`.** The header says `0x77359400` (2,000,000,000). The mainnet node profile
  says `target-gas-limit=61000000` and `plugin-linea-max-block-gas=55000000`; upstream
  Besu's `NetworkDefinition` entry says 60,000,000. These disagree by ~36×, and nothing
  in this evidence establishes which the production sequencer applies. The profiles in
  the repo may not be what the sequencer runs.
- **Whether the relocated 7002/7251 proxies implement the canonical ABI.** They have
  code; they are proxies; the implementation was not decoded.
- **Whether forced-inclusion bypasses module limits.**

## Transaction authorization: mainnet's answer, reached by a different codebase

Linea has no delta on this axis, and establishing that is worth more here than
elsewhere: Besu shares no code with go-ethereum, so a second independent implementation
reaching the same answer is positive evidence rather than duplication.
`Transaction.getSender()` takes its algorithm from `SignatureAlgorithmFactory`, whose
`DEFAULT_INSTANCE` is `SECP256K1`, and that is the whole story for who may authorize a
transaction. Linea's divergence is entirely in what a plugin will let into a *block* —
profitability, trace limits, blob and delegate-code rejection — and those are refusals to
include an already-authorized transaction, not changes to who may authorize one. Nothing
in the plugin tree or the tracer touches `SignatureAlgorithmFactory`; Maru's
`SealVerifier` does, but consensus seals are not transaction authorization.

One fact is worth recording anyway, because the **client** differs even though the chain
does not: **Besu can replace the transaction signature curve wholesale.**
`SignatureAlgorithmFactory.switchInstance` accepts exactly `{secp256k1, secp256r1}`, and
`BesuCommand` calls it with whatever `ecCurve` the genesis names. geth has no such
switch. Linea's genesis names none — the built-in `linea-mainnet.json` config block has
no `ecCurve` key — so `SECP256K1` stands and a P-256 key cannot move a wei.

Two things separate this from Tron's superficially identical `crypto.engine` switch, and
both make it far less alarming:

- Besu reads `ecCurve` from the **genesis file**, i.e. network-wide consensus
  configuration, not per-node config. Two Linea nodes cannot silently disagree about who
  signed what, because they cannot disagree about genesis. Tron's switch is a node
  setting, and two differently-configured Tron nodes disagree on sender recovery.
- If it were ever flipped, **ECRECOVER would follow**: `ECRECPrecompiledContract` takes
  its algorithm from the same factory instance, so `0x01` and the sender-recovery path
  stay paired by construction and the scheme could never become an unpaired one.

For that reason the row records `secp256r1` as `authorizes: no` / `precompile: 0x0100`
with a note, and deliberately does **not** mark it `availability: optional` — there is no
per-deployment knob on Linea to opt into.

## Re-verify

```
git clone --depth 1 --branch releases/linea-besu-package/v2.1.1 \
  https://github.com/LFDT-Lineth/lineth-monorepo
mkdir besu && cd besu && git init && \
  git remote add origin https://github.com/besu-eth/besu && \
  git fetch --depth 1 origin 6580da84187533a3b0ced343dc516ebe2adba6ec && \
  git checkout FETCH_HEAD && cd ..

# the prover budget that is the whole story
cat lineth-monorepo/linea-besu/package/linea-besu/config/trace-limits.mainnet.toml

# the enforcement path
P=lineth-monorepo/linea-besu/plugins/linea-sequencer/sequencer/src/main/java/lineth
sed -n '125,200p' $P/sequencer/txselection/selectors/TraceLineLimitTransactionSelector.java
cat $P/sequencer/txpoolvalidation/validators/PrecompileAddressValidator.java
cat $P/sequencer/txvalidation/TransactionTypeValidation.java
grep -n "DEFAULT_BLOB_TX_ENABLED\|DEFAULT_DELEGATE_CODE_TX_ENABLED" \
  $P/config/LineaTransactionValidatorCliOptions.java
sed -n '84,140p' $P/extradata/LineaExtraDataHandler.java     # extraData v1 layout
grep -n "uncheckedModules" -A 22 \
  lineth-monorepo/tracer/arithmetization/src/main/java/net/consensys/linea/zktracer/ZkCounter.java

# the fork schedule and the relocated predeploys, from upstream Besu
grep -n -A 8 "LINEA_MAINNET(" besu/config/src/main/java/org/hyperledger/besu/config/NetworkDefinition.java
python3 -c "import json;print(json.load(open('besu/config/src/main/resources/linea-mainnet.json'))['config'])"
grep -n -B 4 -A 12 "hasSystemContractAddresses" \
  besu/ethereum/core/src/main/java/org/hyperledger/besu/ethereum/mainnet/MainnetProtocolSpecs.java

# the modexp bound is now EIP-7823's
grep -n "getMaxInputSize\|MODEXP_LARGE_INPUT_BYTE_WIDTH" \
  lineth-monorepo/tracer/arithmetization/src/main/java/net/consensys/linea/zktracer/module/hub/precompiles/ModexpMetadata.java

# no Linea EVM exists (expect: no output)
grep -rn "PrecompileContractRegistry\|MainnetPrecompiledContracts" lineth-monorepo/
```

Live probes, all at block `31744343` on `https://rpc.linea.build`:

```
R=https://rpc.linea.build; B=0x1e46157
c(){ curl -s -X POST $R -H 'content-type: application/json' -d "$1"; }

# RIPEMD160 works in eth_call although no transaction using it can be mined
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000003\",\"data\":\"0x\"},\"$B\"]}"
# -> 0x...9c1185a5c5e9fc54612808977ee8f548b2258d31

# relocated predeploys have code, canonical ones are empty
for a in 0x66355689a9f067eeb9dc9d899E4192676988279C \
         0x00000961Ef480Eb55e80D19ad83579A64c007002 \
         0xF0e003F0dE2d583Ae28FA8cBF66aa096CdAce3ff \
         0x0000BBdDc7CE488642fb579F8B00f3a590007251 \
         0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02; do
  c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$a\",\"$B\"]}"; echo; done

# 7-wei base fee, extraData pricing struct, zero beacon root
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",false]}"
c '{"jsonrpc":"2.0","id":1,"method":"eth_gasPrice","params":[]}'
```
