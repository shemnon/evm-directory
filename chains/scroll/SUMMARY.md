# Scroll — a Shanghai EVM with Osaka features bolted on, and one opcode missing

**Chain ID 534352 · role: `fork` · baseline: Shanghai · Clique → SystemContract, 3s blocks**

Reference: [scroll-tech/go-ethereum `scroll-v5.10.2`](https://github.com/scroll-tech/go-ethereum)
@ `d67dd0ba`. The running network is at exactly that build —
`web3_clientVersion` returns `Geth/v5.10.2-mainnet/linux-amd64/go1.22.2` — which is
unusual in this dataset and means the pinned tag and the deployed client cannot drift
apart. No companion repo was needed: the predeploy addresses *and their deployed
bytecode* are Go constants inside the client (`rollup/rcfg/config.go`), so every
contract fact below is established from the execution client and confirmed live.

All live probes are at block **34765788** (`0x21279dc`, `finalized` at probe time) on
`https://rpc.scroll.io`.

---

## 1. `tombstoned` vs `removed`, demonstrated on one chain at one height

This was the question the row was commissioned to answer, and Scroll answers it
cleanly — it is the only chain here where both halves of the distinction are
observable at the same block:

```
eth_call 0x03 (RIPEMD160)      -> error -32000 "sha256, ripemd160, blake2f precompiles temporarily disabled"
eth_call 0x09 (BLAKE2F)        -> error -32000 (same)
eth_call 0x0a (BLS12-381 G1ADD)-> 0x           success, empty output
```

`0x03` and `0x09` are **`tombstoned`**: `PrecompiledContractsGalileo` maps them to
`ripemd160hashDisabled` and `blake2FDisabled`, whose `Run` returns
`errPrecompileDisabled`. Because that error is not `ErrExecutionReverted`, a `CALL`
consumes **all forwarded gas** and returns 0. Worse for `0x03`:
`ripemd160hashDisabled.RequiredGas` still returns the *real* RIPEMD160 price, so the
caller is charged in full and then fails. (`blake2FDisabled.RequiredGas` returns 0.)

`0x0a`–`0x12` are **`removed`**: `PrecompiledContractsBLS` is fully implemented in this
tree and wired into nothing — `ActivePrecompiles` has no BLS branch — so those
addresses are ordinary empty accounts and calling them *succeeds*.

Any survey that probes "does this address return data" classifies both as missing and
is wrong about one of them.

Two details worth keeping. The error string still names **sha256**, which was
re-enabled at Bernoulli two years ago — the message is stale. And "temporarily" has
now held for the chain's entire life: both tombstones date from **genesis**
(`PrecompiledContractsArchimedes`, block 0), not from a later restriction.

## 2. The prover-constraint leak is the same law as Linea's — but Scroll's has mostly healed

This is the third instance of the pattern (OP fault proofs, Linea, now Scroll), and
the comparison is the most useful thing this row adds.

| | Linea | Scroll |
|---|---|---|
| Mechanism | per-block **work budget** per arithmetization module (`trace-limits.mainnet.toml`) | per-call **capability gate** compiled into the precompile map, plus a per-block **row budget** (CCC) |
| Where it lives | a plugin's TOML config file | the client's `core/vm/contracts.go` and a Rust FFI checker |
| Failure signal | transaction is never *selected*; `eth_call` still succeeds | the call **errors inside the EVM**; `eth_call` fails identically |
| Detectable by probing? | **no** — simulation lies | **yes** — the probe above is sufficient |
| Status today | live; `RIPEMD_BLOCKS = 0`, `BLAKE_ROUNDS = 0` | **the per-block checker is retired**; the per-call gates remain |

Scroll's version is the *legible* one. Linea's is the dangerous one precisely because
`eth_call` cannot see it. Same cause, same two victims (RIPEMD160 and BLAKE2F), and
opposite observability.

And Scroll's has been decommissioned in place. `AsyncChecker.Check` opens with:

```go
if c.bc.Config().IsEuclid(block.Time()) {
    // Euclid blocks use MPT and CCC doesn't support them
    return nil
}
```

So the 950,000-row-per-sub-circuit budget in `types.RowConsumptionLimit` no longer
rejects anything on mainnet. **The limiter is gone; its scars are load-bearing.** What
survives are the two hash tombstones, `ScrollMaxTxPerBlock = 100`, and
`ScrollMaxTxPayloadBytesPerBlock = 120 KB` — the latter two enforced only in the
*producer* (`miner/scroll_worker.go`, `rollup/pipeline/pipeline.go`), not in block
validation, so they are sequencer policy rather than a consensus rule.

Three of the four original circuit-driven restrictions have since been lifted, each at
a different fork:

- **SHA256 (`0x02`)** re-enabled at **Bernoulli** (block 5,220,340). Any archive query
  or historical replay below that height must model `0x02` as failing.
- **BN256_PAIRING (`0x08`)** input cap lifted at **Feynman**. Until then
  `bn256PairingIstanbul{limitInputLength: true}` rejected anything over `4*192` bytes —
  a cap on a *single call's input size*, which is **exactly OP Stack's mechanism**, not
  Linea's.
- **MODEXP (`0x05`)** operand cap lifted at **Galileo**.

### The MODEXP arc is Linea's, repeated

From genesis to 1765868400, `bigModExp.Run` rejected any base/exponent/modulus over
32 bytes:

```
errModexpUnsupportedInput = "modexp temporarily only accepts inputs of 32 bytes (256 bits) or less"
```

RSA-2048 verification was impossible. Galileo sets `eip7823: true, eip7883: true`,
replacing the private 32-byte cap with **EIP-7823's 1024-byte bound**. Confirmed live:
`0x05` with 64-byte base and modulus returns `3^3 mod 10 = 7` as 64 bytes.

That is the identical arc Linea's 512-byte modexp cap took — *a private proving
constraint absorbed by a mainnet consensus rule*. Two chains, independently, closed the
same divergence by the same route. **zkSync Era still enforces the 32-byte width**, so
the dataset's claim that three chains cap modexp needs a date attached: as of Galileo,
Scroll's is history and the dead branch survives only behind `!(eip7823 || eip7883)`.

## 3. `SELFDESTRUCT` does not exist

Not EIP-6780's restriction. Total removal, since genesis:

```go
// SELFDESTRUCT is disabled in Scroll.
// SELFDESTRUCT has the same behavior as INVALID.
SELFDESTRUCT: nil,
```

`core/vm/eips.go` carries two commented-out gas assignments for it in `enable2929` and
`enable3529`, each labelled "SELFDESTRUCT is disabled in Scroll". Live, the opcode
aborts with `invalid opcode: SELFDESTRUCT`.

This is the only chain in the dataset that **removes a mainnet opcode outright** rather
than repricing or restricting it. Contracts whose emergency-withdraw or self-upgrade
path terminates in `SELFDESTRUCT` are unrecoverable here, and no EIP-6780 reasoning
applies — there is nothing to restrict.

## 4. `block.coinbase` is not the miner, and neither is `miner`

```
eth_call  COINBASE                    -> 0x5300000000000000000000000000000000000005
eth_getBlockByNumber -> miner          -> 0x0000000000000000000000000000000000000000
```

`NewEVMBlockContext` sets the block context's `Coinbase` to the **fee vault address**
whenever `FeeVaultEnabled()`, never consulting `Engine.Author(header)`. The header's
`miner` is pinned to zero (`errInvalidCoinbase` rejects anything else). The sequencer
that actually produced the block is a third answer, recoverable only from the block
signature.

**Three different answers to "who mined this block", none of which agree, and no error
anywhere.** A contract that pays the block producer via `block.coinbase` pays the fee
vault. EIP-3651 compounds it: the address warmed at transaction start is the fee vault,
so the *gas cost* of touching `block.coinbase` also differs from mainnet.

## 5. The L1-fee predeploy: OP's ABI at a different address

The brief asked whether Scroll's oracle is genuinely distinct from OP's `0x42…0F`. It
is — but the divergence runs the opposite way from what the dataset usually records.

`0x5300000000000000000000000000000000000002` answers **OP's GasPriceOracle selectors**:

```
l1BaseFee()        0x519b4bd3 -> 0x4086d28
overhead()         0x0c18c162 -> 0x38
scalar()           0xf45e65d8 -> 0x3e95ba80
getL1Fee(bytes)    0x49948e0e
getL1GasUsed(bytes)0xde26c4a1
```

Meanwhile `0x420000000000000000000000000000000000000F` and
`0x4200000000000000000000000000000000000015` are **empty accounts** on Scroll.

So this is **same interface, different address** — the mirror image of the
same-address/different-code collisions the dataset is built around, and it fails the
same silent way: OP-derived code calls `0x42…0F`, gets success and no return data,
decodes an L1 fee of **zero**.

### And the client writes that contract's bytecode itself

`applyCurieHardFork`, `applyFeynmanHardFork` and `applyGalileoV2HardFork` each call
`statedb.SetCode(rcfg.L1GasPriceOracleAddress, <hard-coded Go byte array>)` and seed new
storage slots. Verified live: the deployed code is 3782 bytes,
`sha256 = 0b32912d…5ac07b`, **byte-identical** to `rcfg.GalileoV2L1GasPriceOracleBytecode`
in the pinned clone, and slots 8/11/12 (`isCurie`/`isFeynman`/`isGalileo`) are all `1`.

A contract's code changes with **no transaction, no log and no receipt**. Three of
Scroll's ten forks exist mainly to upgrade this one contract. Any upgrade-monitoring
that watches events or diffs code at deployment sites sees nothing.

There is a further twist in the fee formula: four generations coexist
(`calculateEncodedL1DataFee`, `…Curie`, `…Feynman`, `…Galileo`) and the client selects
between them by reading the oracle's **own storage flags**, so the fee formula in force
is chosen by contract state, not by the chain config. From Feynman the L1 fee also
carries a **compression penalty** (`penaltyThreshold`/`penaltyFactor`, slots 9 and 10):
two transactions of identical length and identical gas can pay different L1 fees because
one compresses worse.

## 6. `0x7e` has a third, unrelated claimant

README currently reads `0x7d`/`0x7e` as "the OP family". Scroll's **L1MessageTx** is
`0x7E` and shares nothing with OP's deposit transaction but the byte:

```
QueueIndex, Gas, To, Value, Data, Sender
```

Six fields. No chain id, no nonce, no gas price, no signature; `To` may not be nil
(no contract creation from L1). Confirmed live on
`0x9b24c569…e74abbc6` at block 34760253: `type 0x7e`, `v`/`r`/`s` all `0x0`,
`nonce 0x0`, `gasPrice 0x0`, plus **non-standard `sender` and `queueIndex` JSON keys**.

A decoder that sees `0x7e` and reaches for OP's `DepositTx` layout mis-parses every L1
message on Scroll. And the type is **rare** — a 50-block census at the probe height
found 40 legacy + 11 dynamic-fee and zero `0x7e`; a 389-block sweep found none either.
An integration can pass every test and still be wrong in production.

## 7. Transaction authorization: `authorizes: protocol` with `precompile: none`

The finding SCHEMA.md says to look for. `londonSigner.Sender` for an L1 message is:

```go
if tx.IsL1MessageTx() { return tx.AsL1MessageTx().Sender, nil }
```

No cryptography runs on L2 at all. `SignatureValues` refuses ("l1 message tx do not
have a signature") and `Hash` **panics** ("l1 message tx cannot be signed and do not
have a signing hash"). Authority comes from the L1MessageQueue contract on Ethereum,
replayed into the block by the sequencer's sync service — the pool refuses the type
from the network outright ("No unauthenticated deposits allowed in the transaction
pool").

So an L2 contract handed an L1 message **cannot verify that the claimed sender
authorised it**: the authorising signature was consumed on Ethereum and never crosses
the bridge. What it is really trusting is sequencer honesty. `key_binding` for that path
is `declared`; `signers_per_tx` stays 1. Shape-identical to OP Stack's deposit
authorization, arrived at independently, on the same type byte.

`secp256r1` is the ordinary pairing: P256VERIFY present, cannot sign.

## 8. The fork name tells you nothing, in both directions

`params/config.go` has **no `CancunTime`, `PragueTime` or `OsakaTime` field**. Grep the
whole tree for "Cancun" and you get nothing. The ladder ends at `ShanghaiBlock: 0`.

Yet the chain has, all live and all probed:

| EIP | Mainnet fork | Scroll fork |
|---|---|---|
| 1153 TSTORE/TLOAD | Cancun | Curie (block 7,096,836) |
| 5656 MCOPY | Cancun | Curie |
| 7702 SetCode | Prague | EuclidV2 |
| 7623 calldata floor | Prague | Feynman |
| 2935 history storage | Prague | Feynman |
| 7823 + 7883 MODEXP | Osaka | Galileo |
| 7951 P256VERIFY | Osaka | Galileo |
| 7939 CLZ | Osaka | Galileo |

And it **lacks EIP-4895 (withdrawals), which mainnet shipped in Shanghai** — the fork
Scroll does claim. `types.Body` has only `Transactions` and `Uncles`; there is no
`Withdrawals` field to decode.

EIP-2935 is implemented *fully*, not cosmetically: canonical address, canonical
`0x3373…` bytecode, `HistoryServeWindow = 8191`, `BLOCKHASH` rewritten to read the
storage ring. Verified: `BLOCKHASH(n-1)` returns the block's `parentHash`.

EIP-7623 verified independently of source: 100 zero calldata bytes to an EOA estimate at
**22000** gas (`21000 + 10 × 100` tokens), not the 21400 pre-7623 pricing gives.

P256VERIFY's gas went **3450 → 6900** (RIP-7212's price → EIP-7951's), so Scroll is one
of the few rows whose `0x0100` now costs *exactly* what mainnet charges rather than
half. Its failure signalling is EIP-7951's empty return, which here is
indistinguishable from an unoccupied address — the Hyperliquid/Sei silent-failure shape,
except the precompile is genuinely present and answering.

`baseline_fork: shanghai` is therefore derived from the config, and every `added` entry
in `chain.yaml` means "not on mainnet **at Shanghai**", with the real mainnet fork named
in the note.

## 9. The block seal is outside the block hash

From EuclidV2 the sequencer's 65-byte seal is a header field of its own,
`BlockSignature`. Three encodings of one header coexist:

- **on the p2p wire**: the seal sits inside `extraData` (`PrepareForNetwork` moves it
  there; `PrepareFromNetwork` moves it back)
- **in the database**: `BlockSignature` populated, `Extra` nil
- **over JSON-RPC**: dropped entirely — hence `extraData: 0x` observed live

And `Header.Hash()` explicitly strips it:

```go
hCopy.BlockSignature = nil
if hCopy.IsEuclidV2 { hCopy.IsEuclidV2 = false; hCopy.Extra = nil }
```

**The block hash does not commit to the signature that authorises the block.** This is
the third instance in the dataset of a header field carrying something other than its
Ethereum meaning — after OP Stack's `blobGasUsed` and Linea's `extraData` — and it lands
on *the same field Linea repurposed*, for a different purpose, by a different mechanism.

Related: the consensus engine itself. From EuclidV2 the authorised signer is read from
**one storage slot on Ethereum mainnet** —
`eth_getStorageAt(0x8432728A257646449245558B8b7Dbe51A16c7a4D, 0x67)`. A Scroll node
cannot validate a header without an L1 RPC endpoint, and the L2's block-producer
authorisation is mutable from L1 with no L2 fork.

## 10. Whether the state root is checked depends on a node-local CLI flag

```go
shouldValidateStateRoot := v.config.Scroll.UseZktrie != v.config.IsEuclid(header.Time)
```

and `UseZktrie` is assigned at startup from `!ctx.GlobalBool(ScrollMPTFlag.Name)` —
i.e. from `--scroll-mpt`, a **node-local command-line flag**, not from genesis or from
consensus.

Post-Euclid, therefore: a node started **without** `--scroll-mpt` (the built-in default
for `--scroll`) evaluates `true != true` and **skips the state-root comparison
entirely**; one started **with** it evaluates `false != true` and performs it. This was
the mechanism that let zkTrie and MPT sequencers coexist across the Euclid migration
(the source says so: "clocks of mpt-sequencer and zktrie-sequencer can be slightly out
of sync… this might result in a reorg at the Euclid fork block"), and it is still the
code at this tag.

SCHEMA.md's warning about config-switchable consensus rules applies exactly: two nodes
with different flags disagree about whether they verify state at all. **Which flag
production nodes actually run is `unrecorded`** — nothing in the repo's docs, Dockerfiles
or configs mentions `--scroll-mpt`.

The same Euclid migration left `StateAccount` carrying two zkTrie-era extensions,
`PoseidonCodeHash` and `CodeSize`, both `rlp:"-"`.

## Not established here

- **Which flag production nodes run** (`--scroll-mpt` or not), and therefore whether
  the state root is verified on the network today. The code path is recorded; the
  deployment is not.
- **EIP-7928 / Amsterdam.** Nothing in the tree references block access lists and there
  is no timestamp field to gate one. Marked `unrecorded`, not guessed.
- **`scroll-tech/scroll` and `scroll-tech/scroll-contracts` were not pinned.** Both exist
  and neither is archived, but no fact in this row needed them — the client carries the
  predeploy addresses *and* their deployed bytecode as Go constants, and the live probe
  confirms the deployed code is byte-identical to the client's copy. The contracts moved
  out of the monorepo into `scroll-tech/scroll-contracts` at some point; that move is not
  characterised here.
- **Whether `0x03`/`0x09` ever return anything other than the disabled error at any
  height ≥ Bernoulli.** Only the probe height was tested.
- **The Darwin and DarwinV2 forks** have timestamps in the config and no identified EVM
  delta; they are DA/compression upgrades, not characterised from source here.
- **The exact live gas of P256VERIFY** could not be isolated by `eth_estimateGas`,
  because the EIP-7623 calldata floor dominates a 160-byte call. The 6900 figure comes
  from `params.P256VerifyGasGalileo`, not from a measurement.

## Re-verify

```sh
git clone --depth 1 --branch scroll-v5.10.2 --single-branch \
  https://github.com/scroll-tech/go-ethereum
cd go-ethereum
git rev-parse HEAD          # d67dd0baa0ff3607c23f8f23bc94be26aabaa290

# the fork ladder stops at Shanghai — and there is no Cancun/Prague/Osaka field at all
sed -n '/ScrollMainnetChainConfig = &ChainConfig{/,/^	}$/p' params/config.go
grep -rn "Cancun\|Prague\|Osaka" params/config.go        # expect: no output

# the two tombstones, and the BLS set that is wired into nothing
grep -n "errPrecompileDisabled\|errModexpUnsupportedInput" core/vm/contracts.go
sed -n '/PrecompiledContractsGalileo contains/,/^}/p'    core/vm/contracts.go
sed -n '/PrecompiledContractsArchimedes contains/,/^}/p' core/vm/contracts.go
grep -n "ripemd160hashDisabled\|blake2FDisabled\|sha256hashDisabled" -A 6 core/vm/contracts.go
grep -n "func ActivePrecompiles" -A 22 core/vm/contracts.go   # no BLS branch
grep -n "P256VerifyGas" params/protocol_params.go             # 3450 then 6900

# SELFDESTRUCT is nil; the Cancun/Osaka opcodes arrive at Curie and Galileo
grep -n "SELFDESTRUCT" core/vm/jump_table.go core/vm/eips.go
sed -n '75,130p' core/vm/jump_table.go

# COINBASE is the fee vault
grep -n "func NewEVMBlockContext" -A 20 core/evm.go
grep -n "func opCoinbase" -A 4 core/vm/instructions.go

# the client writes the oracle's bytecode at three forks
cat consensus/misc/forks.go consensus/misc/curie.go consensus/misc/galileoV2.go
grep -n "L1GasPriceOracleAddress\|ScrollFeeVaultAddress\|L2MessageQueueAddress" rollup/rcfg/config.go

# 0x7e, and the sender that is a field rather than a signature
sed -n '48,60p' core/types/transaction.go
sed -n '/^type L1MessageTx struct/,/^}/p' core/types/l1_message_tx.go
grep -n "IsL1MessageTx" core/types/transaction_signing.go core/tx_pool.go

# the seal outside the hash; the state root behind a CLI flag; the retired CCC
grep -n "func (h \*Header) Hash\|func (h \*Header) PrepareForNetwork" -A 10 core/types/block.go
sed -n '260,270p' core/block_validator.go
grep -n "ScrollMPTFlag" cmd/utils/flags.go
grep -n "CCC doesn't support" -B 3 rollup/ccc/async_checker.go
grep -n "RowConsumptionLimit" core/types/row_consumption.go
```

Live probes, all at block `34765788` (`0x21279dc`) on `https://rpc.scroll.io`:

```sh
R=https://rpc.scroll.io; B=0x21279dc
c(){ curl -s -X POST $R -H 'content-type: application/json' -d "$1"; echo; }
call(){ c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"data\":\"$1\",\"gas\":\"0x100000\"},\"$B\"]}"; }

# tombstoned (errors) vs removed (succeeds empty) — the whole distinction, two lines
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000003\",\"data\":\"0x\"},\"$B\"]}"
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x000000000000000000000000000000000000000a\",\"data\":\"0x\"},\"$B\"]}"
# and SHA256, which came back at Bernoulli
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000002\",\"data\":\"0x\"},\"$B\"]}"

# opcodes, run as eth_call init code (result = the 32 bytes RETURNed)
call 0x415f5260205ff3          # COINBASE   -> 0x53..05  (header miner is 0x00..00)
call 0x60011e5f5260205ff3      # CLZ(1)     -> 0xff      (EIP-7939, Osaka)
call 0x60aa60005d60005c5f5260205ff3   # TSTORE/TLOAD -> 0xaa   (EIP-1153, Cancun)
call 0x60ff5f5260205f60205e60206020f3 # MCOPY        -> 0xff   (EIP-5656, Cancun)
call 0x4360019003405f5260205ff3       # BLOCKHASH(n-1) == parentHash (EIP-2935)
call 0x5fff                    # -> "invalid opcode: SELFDESTRUCT"
call 0x5f495f5260205ff3        # -> "opcode 0x49 not defined"  (no BLOBHASH)
call 0x4a5f5260205ff3          # -> "opcode 0x4a not defined"  (no BLOBBASEFEE)

# MODEXP with 64-byte operands: 3^3 mod 10, impossible before Galileo
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000005\",\"data\":\"0x00000000000000000000000000000000000000000000000000000000000000400000000000000000000000000000000000000000000000000000000000000001000000000000000000000000000000000000000000000000000000000000004000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000003030000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000a\",\"gas\":\"0x1000000\"},\"$B\"]}"

# EIP-7623 floor: 22000 (0x55f0), not 21400 (0x5398)
Z=0x$(python3 -c "print('00'*100)")
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_estimateGas\",\"params\":[{\"to\":\"0x000000000000000000000000000000000000dead\",\"data\":\"$Z\"},\"$B\"]}"

# Scroll's oracle has OP's ABI; OP's address is empty
for s in 519b4bd3 0c18c162 f45e65d8; do
  c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x5300000000000000000000000000000000000002\",\"data\":\"0x$s\"},\"$B\"]}"; done
for a in 0x5300000000000000000000000000000000000000 0x5300000000000000000000000000000000000002 \
         0x5300000000000000000000000000000000000005 0x0000F90827F1C53a10cb7A02335B175320002935 \
         0x420000000000000000000000000000000000000F 0x4200000000000000000000000000000000000015; do
  c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$a\",\"$B\"]}" | head -c 100; echo " <- $a"; done

# deployed oracle code == the client's Go constant
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x5300000000000000000000000000000000000002\",\"$B\"]}" \
  | python3 -c "import sys,json,hashlib;r=json.load(sys.stdin)['result'];b=bytes.fromhex(r[2:]);print(len(b),hashlib.sha256(b).hexdigest())"
# -> 3782 0b32912d09bc322afbc270c1bdbf8979404e06d49de070804905fc5f105ac07b

# an unsigned 0x7e L1 message: v=r=s=0, plus `sender` and `queueIndex`
c '{"jsonrpc":"2.0","id":1,"method":"eth_getTransactionByHash","params":["0x9b24c569894dd98c75daba1b2fdc240712cc8e9d1ea4b978fa1ae440e74abbc6"]}'

# header: extraData empty, miner zero, difficulty 1, no 4844/4788/4895 fields
c "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",false]}"
```
