# Rootstock (RSK) — findings

Chain ID 30. Client `rsksmart/rskj` **VETIVER-9.0.4** @ `731b9d8a`, Java.
Baseline fork **petersburg**. Live probes at block **9225919** (`0x8cc6bf`) on
`https://public-node.rsk.co`.

`web3_clientVersion` returns `RskJ/9.0.3/Linux/Java17/VETIVER-c19cf12` — mainnet runs
9.0.3 while 9.0.4 is the newest GitHub release, so the pin is one patch *ahead* of the
network. Both are VETIVER and no consensus rule below differs between them.

A note on the tag ladder, because it costs an hour otherwise: RSKj versions are plant
names — ORCHID → WASABI → PAPYRUS → IRIS → HOP → FINGERROOT → ARROWHEAD → LOVELL →
REED → VETIVER — and `sort -V` over the tag list returns WASABI last.

---

## 1. The prediction was right, and about the wrong layer

CANDIDATES.md predicted "merge-mined, forked the EVM early enough that opcode-level
drift is likely". Opcode drift is real (§4), but it is the second-biggest finding.
The first is that **Rootstock runs Cancun-era opcodes on a Constantinople-era gas
schedule.**

PUSH0 (RSKIP398), MCOPY (RSKIP445), TLOAD/TSTORE (RSKIP446) are all live. And:

| | mainnet today | Rootstock |
|---|---|---|
| SLOAD | 2,100 cold / 100 warm | **200**, flat |
| BALANCE | 2,600 / 100 | **400**, flat |
| EXTCODEHASH | 2,600 / 100 | **400**, flat |
| CALL, EXTCODESIZE, EXTCODECOPY | 2,600 / 100 | **700**, flat |
| SSTORE | EIP-2200 net metering | **20,000 / 5,000 / 5,000**, no dirty tracking |
| storage-clear refund | 4,800 | **15,000** |
| SELFDESTRUCT refund | **0** (removed at London) | **24,000** |
| refund cap | gasUsed / 5 | **gasUsed / 2** |
| MODEXP | EIP-2565 (divisor 3) | **EIP-198 (divisor 20)** |

There is no access list anywhere in the tree: `grep -ri 'warm\|cold\|accessList'` over
`org/ethereum/vm/` returns nothing. EIP-2929, EIP-2200, EIP-3529 and EIP-6780 are all
absent, and EIP-1884 was taken **in half** — SELFBALANCE arrived via RSKIP151, its
repricings never did.

Two consequences worth stating plainly. Gas-token contracts (GST2, CHI) work on
Rootstock. And the Taraxa finding inverts here: on Taraxa a 2,300-gas stipend *can*
write storage because EIP-1283 shipped without its sentry; on Rootstock it cannot,
because the cheapest SSTORE is 5,000. Same conclusion, opposite reason — and neither
chain reaches it the way mainnet does.

## 2. There is no EIP-2718 envelope

`org.ethereum.core.Transaction` decodes nine RLP items and has no type branch. Not
"type 2 is rejected" — **absent from the transaction class**. Confirmed live: 126
transactions across 30 consecutive blocks at head, every one type `0x0`.

So Rootstock is the only row here whose envelope is *narrower* than mainnet's. It
consumes no type byte and collides with nobody, which is the opposite end of the
spectrum from Kaia's `uint16` types and Celo's `0x7b`.

## 3. The header is a different header, and the RPC hides it

`BlockHeader.getEncoded` produces:

```
parentHash, unclesHash, coinbase, stateRoot, txTrieRoot, receiptTrieRoot, logsBloom,
difficulty, number, gasLimit, gasUsed, timestamp, extraData,
paidFees, minimumGasPrice, uncleCount, [ummRoot], [rskPteEdges],
[btcMergedMiningHeader, btcMergedMiningMerkleProof, btcMergedMiningCoinbaseTx]
```

**`mixHash` and `nonce` are not in it.** `eth_getBlockByNumber` returns both anyway,
as all-zero. Anything that re-derives a block hash from the JSON, or reads `mixHash`
for randomness, is reading a value no header ever committed to.

And `block.prevrandao` is worse than zero: Rootstock never merged, so `0x44` is still
DIFFICULTY and `doDIFFICULTY` pushes the real merge-mining difficulty
(`0x157d44759dd5edf5da5` at the probed block) — a large, slowly-moving, Bitcoin-derived
number that any observer can predict. Solidity's `block.prevrandao` compiles to
`0x44`, with no revert and no signal.

## 4. Four tombstoned opcode bytes — three of them switched off by a fork

`DUPN (0xa8)`, `SWAPN (0xa9)` and `TXINDEX (0xaa)` are in the enum, implemented in
`VM.java`, and **unreachable**, because the dispatch inverts the usual gate:

```java
case OpCodes.OP_DUPN:
    if (activations.isActive(RSKIP191)) {
        throw Program.ExceptionHelper.invalidOpCode(program);
    }
    doDUPN();
```

RSKIP191 activates at `iris300`, block 3,614,800. So these were **live for four years
and then turned off**, and contracts deployed before that height that contain `0xa8`
now halt on it. Mainnet has never allocated `0xa8`–`0xaa`, so this is a delta against
Rootstock's own history rather than against mainnet's — a direction the schema's
vocabulary handles (`tombstoned`) but the dataset had not yet seen.

`HEADER (0xfc)` is the fourth, and it was born dead. The enum entry passes a script
version of 256 with the comment *"setting version==256 assures it's never considered
valid (because scriptVersion range is 0..255)"*, and the dispatch case falls through
to the raising default.

## 5. Precompile input is truncated, not rejected — and on `0x09` that changes the answer

Since RSKIP516 (`reed800`, block 8,052,200):

```java
int maxInputFromContract = contract.getMaxInput() != NO_LIMIT_ON_MAX_INPUT ? … ;
int finalInputLength = maxInputFromContract == 0 ? 0 : Math.min(initialInputLength, maxInputFromContract);
```

with caps of 128 (ECRECOVER, BN128_ADD, SECP256K1_ADD), 96 (BN128_MUL,
SECP256K1_MUL) and **213 (BLAKE2F)**. The excess is dropped and logged at debug level.

For ECRECOVER and the BN128 pair this changes nothing, because mainnet already ignores
bytes past the expected length. For BLAKE2F it inverts the outcome: **mainnet reverts
unless the input is exactly 213 bytes**, and Rootstock clips a 300-byte call to 213 and
returns a hash. Same address, same name, opposite result, no error on either side.

This is a fifth flavour of same-address divergence to set beside the six the README
lists — not a cap that makes the call *revert* (OP Stack) but a cap that makes it
*succeed*.

## 6. There is a maximum gas price, and exceeding it invalidates the block

`TxGasPriceCap` is an enum with two members: `FOR_BLOCK(100)` and
`FOR_TRANSACTION(80)`. Since RSKIP252 a block containing any transaction whose gas
price exceeds **100× that block's `minimumGasPrice`** fails `BlockTxsMaxGasPriceRule`
and is invalid; the mempool refuses anything over 80×.

No other chain in this dataset caps what a user may bid. Consequences: priority-fee
auctions have a ceiling, a stuck transaction cannot be rescued by overpaying, and a
wallet's "aggressive" preset calibrated for mainnet congestion can produce a
transaction no honest miner is able to include. The REMASC transaction is exempt by an
explicit `instanceof` test.

`minimumGasPrice` is also what `BASEFEE` returns (RSKIP412) — so `block.basefee` on
Rootstock is a miner-voted floor with no burn semantics and no relationship to
congestion.

## 7. Every block ends with an unsigned transaction whose sender is malformed on purpose

```java
/**
 * The Remasc transaction is not signed so it has no sender.
 * Due to a bug in the implementation before mainnet release, this address has a
 * special encoding. Instead of the empty array, it is encoded as the array with
 * just one zero.
 */
public static final RskAddress REMASC_ADDRESS = new RskAddress(new byte[20]) { … };
```

It appears in `eth_getBlockByNumber` as an ordinary `type: 0x0` transaction. An
indexer that assumes every legacy transaction has a recoverable signature fails on one
transaction per block, forever. In `tx_authorization` terms this is
`authorizes: protocol` paired with `precompile: none` — the chain accepts a
transaction its own contracts have no way to verify, because nothing signed it.

## 8. What is shipped and not on

`rskPteEdges` is a header field reserved for RSKIP144 parallel transaction execution,
fully implemented in the client. It is bound to `reed810`, whose height in
`config/main.conf` is **-1**. Confirmed live: `rskPteEdges` is `null`. RSKIP351
(header compression), RSKIP502 and RSKIP529 are parked at the same height.

Reading the activation state needs **both** config files and in that order:
`reference.conf` maps a rule to a fork name, `config/main.conf` maps a fork name to a
height, and `main.conf` may additionally pin one rule to a height of its own — which
it currently does, for `rskip536`. Either file alone gives the wrong answer, which is
why `tools/verify.py`'s extractor reads both.

## 9. Address placement, and a hex trap

Seven custom precompiles at `0x01000006`–`0x01000017`: Bridge (the BTC two-way peg),
REMASC (rewards), HDWalletUtils (BIP-32 derivation), BlockHeaderContract,
Environment (call-stack depth), and — since `reed800` — **secp256k1 point addition and
scalar multiplication**, which mainnet has never exposed despite signing with that
curve.

Placement is safe: far above anything mainnet has allocated, and far above the
`0x64`–`0x69` block that BSC, Core, Cronos, opBNB and Arbitrum are contending over.
The trap is that the constants are written to *look* decimal — `…01000016`,
`…01000017` — while being hex, so `0x01000012`–`0x01000015` are unallocated and a
reader skimming the list will mis-order them.

All seven return `0x` from `eth_getCode`, indistinguishable from an empty account.
The Bridge is the one that matters: it mints and burns RBTC, so a peg-in credits
native value with no EVM-level transfer to observe.

---

## Re-verify

```bash
R=https://public-node.rsk.co
B=0x8cc6bf     # 9225919
S=chains/rootstock/repos/rskj/rskj-core/src/main

# F1: the gas schedule
grep -n 'SLOAD\|BALANCE\|EXT_CODE_HASH\|SET_SSTORE\|RESET_SSTORE\|CLEAR_SSTORE\|REFUND_SSTORE\|SUICIDE_REFUND\|TX_NO_ZERO_DATA' \
  $S/java/org/ethereum/vm/GasCost.java
grep -n 'protected void doSSTORE' -A24 $S/java/org/ethereum/vm/VM.java
grep -n 'private long refundGas' -A12 $S/java/org/ethereum/core/TransactionExecutor.java
grep -n 'GQUAD_DIVISOR' $S/java/org/ethereum/vm/PrecompiledContracts.java
grep -rn 'warm\|cold\|accessList' $S/java/org/ethereum/vm/ | head    # nothing

# F2: no EIP-2718
sed -n '110,160p' $S/java/org/ethereum/core/Transaction.java
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",true]}" \
  | python3 -c 'import sys,json;b=json.load(sys.stdin)["result"];print(sorted({t["type"] for t in b["transactions"]}))'

# F3: the header, and the fields the RPC invents
sed -n '355,400p' $S/java/org/ethereum/core/BlockHeader.java
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",false]}" \
  | python3 -c 'import sys,json;b=json.load(sys.stdin)["result"];print(sorted(b));print({k:b[k] for k in ("mixHash","nonce","difficulty","minimumGasPrice","paidFees","rskPteEdges")})'
grep -n 'protected void doDIFFICULTY' -A10 $S/java/org/ethereum/vm/VM.java

# F4: the four tombstoned bytes
grep -n 'DUPN(0xa8\|SWAPN(0xa9\|TXINDEX(0xaa\|HEADER(0xfc' -A4 $S/java/org/ethereum/vm/OpCode.java
grep -n 'OP_DUPN\|OP_SWAPN\|OP_TXINDEX\|OP_HEADER' -A5 $S/java/org/ethereum/vm/VM.java
grep -n 'rskip191' $S/resources/reference.conf
grep -n 'iris300' $S/resources/config/main.conf

# F5: input truncation
grep -n 'getInputLength' -A16 $S/java/org/ethereum/vm/program/Program.java
grep -rn 'getMaxInput' -A5 $S/java/org/ethereum/vm/PrecompiledContracts.java \
  $S/java/co/rsk/pcc/altBN128/*.java $S/java/co/rsk/pcc/secp256k1/*.java

# F6: the gas price CAP
cat $S/../main/java/co/rsk/validators/TxGasPriceCap.java 2>/dev/null || \
  find chains/rootstock/repos/rskj -name TxGasPriceCap.java -exec sed -n '30,56p' {} \;
grep -n 'isValid' -A16 $S/java/co/rsk/validators/BlockTxsMaxGasPriceRule.java
grep -n 'protected void doBASEFEE' -A10 $S/java/org/ethereum/vm/VM.java

# F7: the REMASC transaction
sed -n '54,80p' $S/java/co/rsk/remasc/RemascTransaction.java

# F8: what is shipped and off
grep -n 'reed810\|vetiver900\|rskip544\|rskip516' $S/resources/config/main.conf $S/resources/reference.conf

# F9: the precompile addresses and their activation rules
sed -n '78,152p' $S/java/org/ethereum/vm/PrecompiledContracts.java
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x0000000000000000000000000000000001000006\",\"$B\"]}"   # 0x
for a in 0x0a 0x0100; do
  curl -s -X POST $R -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x00000000000000000000000000000000000000${a#0x}\",\"data\":\"0x00\"},\"$B\"]}"
done   # both 0x — absent precompiles that succeed

# row check
tools/.venv/bin/python tools/verify.py rootstock
```
