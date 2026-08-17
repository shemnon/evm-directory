# Tron — behavioural EVM, structural divergence everywhere else

**Chain ID 728126428 · role: `independent` · equivalence: `behavioural` · no upstream**

Reference: [tronprotocol/java-tron `GreatVoyage-v4.8.2.1`](https://github.com/tronprotocol/java-tron) @ `f8b05d40`.

Not a fork of any Ethereum client. java-tron reimplements EVM semantics in Java with
its own resource model, transaction format and address encoding. Every delta below is
a **behavioural** comparison, not a code diff — which is why the schema needs the
`independent` role at all.

## The one that will bite you: `0x03` is not RIPEMD160

Tron's precompile at `0x03` is named `Ripempd160` and does not compute RIPEMD160.
`PrecompiledContracts.java:552-580`:

```java
byte[] orig = Sha256Hash.hash(..., data);   // SHA256 of the input
System.arraycopy(orig, 0, target, 0, 20);   // first 20 bytes
return Pair.of(true, Sha256Hash.hash(..., target));   // SHA256 of those
```

That is `SHA256(SHA256(data)[0:20])`. **There is no RIPEMD anywhere in it.** The real
RIPEMD160 exists — at `0x020003`, as `EthRipemd160`, doing a plain `Hash.ripemd160(data)`.

A contract ported from Ethereum that calls `0x03` gets silently wrong hashes: no
revert, no error, just different bytes. This is the single most dangerous divergence
found across all seven rows.

## Two head-on precompile collisions

| Addr | Mainnet | Tron |
|---|---|---|
| `0x09` | BLAKE2F (EIP-152) | `batchValidateSign` |
| `0x0a` | KZG point evaluation (EIP-4844) | `validateMultiSign` |

Tron's genuine BLAKE2F was **relocated to `0x020009`** rather than the collision being
resolved.

That relocation reveals a deliberate structure: a **compatibility shadow range** at
`mainnet_address + 0x020000`, holding true Ethereum implementations displaced from
their canonical homes. `0x03 → 0x020003`, `0x09 → 0x020009`. Nothing else in this
dataset does this. Other chains that collided (BSC at `0x64`–`0x69`) or tombstoned
(Avalanche's native-asset trio) left the mainnet range alone; Tron built a parallel
map instead.

## Three address regions

- **`0x01`–`0x0a`** — overlaps mainnet, diverges *inside* it at `0x03`, `0x09`, `0x0a`.
- **`0x02xxxx`** — the shadow range: relocated Ethereum semantics.
- **`0x1000001`–`0x1000015`** — 21 Tron-native precompiles, safely out of the way:
  shielded TRC-20 zk-SNARK verification (`verifyMintProof`, `verifyTransferProof`,
  `verifyBurnProof`), consensus voting queries, staking/resource accounting, and
  `getChainParameter` for reading governance state.

P256VERIFY sits at `0x0100` — the **fourth** independent arrival at that address,
after mainnet (Osaka), OP Stack (Fjord) and Avalanche (Granite). Four chains, four
different forks, one address. It's the only genuinely universal non-original
precompile in the dataset.

## The only chain here with custom opcodes

Sixteen, at `0xd0`–`0xdf` (`Op.java:242-257`):

| Range | Opcodes |
|---|---|
| `0xd0`–`0xd3` | `CALLTOKEN`, `TOKENBALANCE`, `CALLTOKENVALUE`, `CALLTOKENID` (TRC-10) |
| `0xd4` | `ISCONTRACT` |
| `0xd5`–`0xd7` | `FREEZE`, `UNFREEZE`, `FREEZEEXPIRETIME` |
| `0xd8`–`0xd9` | `VOTEWITNESS`, `WITHDRAWREWARD` |
| `0xda`–`0xdf` | V2 staking: freeze, unfreeze, cancel, withdraw, delegate, undelegate |

Staking, consensus voting and reward withdrawal are **single instructions**.

Worth noting the irony: mainnet has never allocated `0xd0`–`0xdf`, so the most
divergent chain in the dataset has the *most* collision-safe opcode placement. Its
precompile placement is the worst. Placement discipline and semantic fidelity turn
out to be independent axes.

## Opcode set is more current than expected

Full Cancun coverage: `PUSH0` (`0x5f`), `MCOPY` (`0x5e`), `TLOAD`/`TSTORE`
(`0x5c`/`0x5d`), `BLOBHASH` (`0x49`), `BLOBBASEFEE` (`0x4a`), `CHAINID`, `SELFBALANCE`,
`EXTCODEHASH`, `CREATE2`. `PREVRANDAO` is absent — no randomness beacon.

But two are present-and-lying:

- **`BASEFEE` (`0x48`) returns the governance-set `ENERGY_FEE`** (default 100 sun per
  energy), not a computed base fee (`OperationActions.java:550-556`). Present,
  non-zero, and not a base fee — the most subtly misleading opcode found.
- **`BLOBBASEFEE` pushes zero** unconditionally.

So "Cancun-equivalent" describes Tron's jump table and nothing else.

## No transaction envelope in common with Ethereum

No RLP. No EIP-2718. Transactions are **protobuf messages** carrying one of 43
`ContractType` values (`Tron.proto:337-378`), sparsely numbered 0–59. Exactly two
reach the EVM:

- `CreateSmartContract` (30)
- `TriggerSmartContract` (31)

The other 41 are protocol operations with no EVM analogue — `TransferContract` (1)
moves native TRX *without touching the EVM at all*, plus voting, governance
proposals, asset issuance, decentralised exchange, shielded transfers, and the
staking/delegation family.

`chain.yaml` cannot express these in `tx_types` because none has a type byte. They
live in `non_evm_transactions`, the section Avalanche's atomic txs forced into the
schema — the second independent chain to need it.

Addresses differ too: base58 with a `0x41` prefix.

## Energy and bandwidth, not gas

Execution consumes **energy**; transaction size consumes **bandwidth**. Both are
obtained by staking (freezing) TRX, or paid by burning TRX at the governance-set
`ENERGY_FEE` — **100 sun per energy by default, set by SR proposal, not by a market**
(`DynamicPropertiesStore.java:73-75, 481`). Transactions carry a `fee_limit` rather
than a gas price.

An account with enough staked TRX **executes for free**. There is no mainnet
analogue, and fee estimation, gas golfing and 1559 tooling are all meaningless here.

## Governance activates features, not releases

Tron ships GreatVoyage releases, but features activate by **on-chain SR governance
proposal**. There is no fork-name mapping to Ethereum's schedule to record, which is
why `forks.timeline` is empty rather than guessed at.

## Re-verify

```
git clone --depth 1 --branch GreatVoyage-v4.8.2.1 https://github.com/tronprotocol/java-tron
F=actuator/src/main/java/org/tron/core/vm/PrecompiledContracts.java
sed -n '133,213p' $F        # all precompile addresses
sed -n '552,580p' $F        # 0x03 is not RIPEMD160
sed -n '1976,1995p' $F      # EthRipemd160 at 0x020003
sed -n '242,257p' actuator/src/main/java/org/tron/core/vm/Op.java          # 0xd0-0xdf
sed -n '548,556p;696,701p' actuator/src/main/java/org/tron/core/vm/OperationActions.java
sed -n '337,378p' protocol/src/main/protos/core/Tron.proto                 # 43 contract types
sed -n '73,75p' chainbase/src/main/java/org/tron/core/store/DynamicPropertiesStore.java
```
