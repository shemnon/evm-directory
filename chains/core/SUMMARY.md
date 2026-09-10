# Core — findings

Chain ID 1116. Client `coredao-org/core-chain` **v1.0.26** @ `06a3e0a9`.
Baseline fork **prague**. Live probes at block **38560250** (`0x24c61ba`) on
`https://rpc.coredao.org`.

`web3_clientVersion` returns `Geth/v1.0.26-06a3e0a9-20260902/linux-amd64/go1.23.12`.
`06a3e0a9` is this commit: mainnet runs exactly the pinned tag, with no gap.

---

## 1. It is a BSC fork, and the fork names are the evidence

CANDIDATES.md filed Core under "Satoshi Plus, BTC staking" without naming a parent.
The parent is BSC. `CHANGELOG.md` for v1.0.16 records *"Merged versions up to v1.4.10
from Binance smart chain"*; `CoreChainConfig` schedules BSC's Kepler, Luban, Plato,
Bohr, Pascal and Hertz beside Core's own Zeus, Hera, Poseidon, Athena, Theseus and
Hermes; `go.mod` depends on `bnb-chain/fastssz` and replaces cometbft with
`bnb-chain/greenfield-cometbft`. Parlia is renamed Satoshi and extended with delegated
Bitcoin hash power and BTC staking.

The merge point matters. Core carries BSC's Prague and none of its Osaka: there is no
`OsakaTime` in `CoreChainConfig`, so no P256VERIFY at `0x0100`, and none of BSC's
`0x66`–`0x69` precompiles.

## 2. `0x64` and `0x65` are occupied — and not by what a BSC developer expects

| address | BSC | Core |
|---|---|---|
| `0x64` | `tmHeaderValidate` (tombstoned at Pasteur) | **`btcValidateV2`** |
| `0x65` | `iavlMerkleProofValidate` (tombstoned at Pasteur) | **`blsSignatureVerify`** |
| `0x66` | `blsSignatureVerify` | *nothing* |

Core took BSC's BLS verifier — byte-for-byte the same implementation, same input
layout `msg(32) ‖ sig(96) ‖ pubkey[](48…)`, 1,000 + 3,500/key — and installed it at
**one of BSC's other precompile addresses**.

Both directions fail silently:

- Code ported from BSC that calls `0x66` for BLS verification reaches an **empty
  account** on Core. The call *succeeds* and returns no data, which an unchecked
  caller reads as "verification produced nothing" rather than "there is no verifier
  here". Verified live: `eth_call` to `0x66` returns `0x`, while the same call to
  `0x65` reverts.
- Code written for BSC that calls `0x65` expecting an IAVL proof check gets a BLS
  signature verification.

With Cronos's (unregistered) Bank precompile also claiming `0x64`, that address is now
declared by **five** unrelated chains — BSC, Arbitrum (ArbSys), opBNB, Core and
Cronos — and live on three of them at once. The README's "two of the largest EVM
chains, six identical addresses" finding is now a five-way pile-up at a single byte.

`0x…1011` joins it: Core's `CoreAgentContract` shares an address with **Sei's
P256VERIFY**, which is ABI-dispatched as `verify(bytes)`.

## 3. Emitting a log can cost gas the EVM never charged — and can fail a transaction that succeeded

This is the finding. Since Theseus (2025-06-25), after every **successful** contract
call, `core/state_transition.go` does this:

1. reads the transaction's logs;
2. for each emitting address, reads a config out of the **raw storage** of the Fee
   Market contract at `0x…1016`;
3. for each log whose `topics[0]` matches a registered event signature, deducts
   `event.Gas × rewardPercentage / 10000` gas from the sender, **plus 2,300**
   (`FeeMarketDistributeGas`) per reward, and credits the equivalent wei to the reward
   address at the transaction's effective tip;
4. returns the deducted gas to the **block** gas pool (`st.gp.AddGas(distributedGas)`).

Four things follow.

**The gas is charged after execution.** `st.gasRemaining` is decremented once the EVM
has already returned, so the `GAS` opcode inside the transaction never sees it and no
in-contract gas budget can account for it.

**A successful transaction can still fail.** If what remains cannot cover the reads
and the rewards, the client sets `ErrFeeMarketOutOfGas` and reverts to a snapshot.
The transaction's own code completed; there is no `REVERT` in its trace and no failing
opcode to point at. This is the `third-party-code-in-your-transaction` class that
Artela opened, reached by a completely different mechanism — and unlike Artela's
Aspects, it is on a chain with real volume.

**The price is set by someone else.** Which event signatures are chargeable is
governance state in another contract. The same calldata against the same bytecode can
succeed today and run out of gas tomorrow with no change to either.

**A Solidity storage layout is a consensus interface.** The client does not *call* the
Fee Market contract; `eth/feemarket/feemarket.go` walks its packed slots directly, and
says so:

> This implementation reads the storage layout of the Fee Market Configuration.sol
> contract as deployed on-chain. The layout is tightly coupled to the Solidity
> contract. … Any change to slot packing/order is a breaking change.

Auditing that contract means auditing its slot assignment.

There is also a shipped bug in the history. Before `TheseusFix` (2025-07-31) the
revert used a snapshot taken **after** the nonce increment had been journalled, so a
fee-market failure rolled the nonce back too. `st.evm.InitialSnapshot()` now preserves
it. A consensus-visible nonce bug, live for five weeks.

## 4. `block.prevrandao` returns 1 or 2

```go
if header.Difficulty.Sign() == 0 { random = &header.MixDigest }
…
chainRules: chainConfig.Rules(blockCtx.BlockNumber, blockCtx.Random != nil, blockCtx.Time)
```

Satoshi, like Parlia, writes a difficulty of 1 or 2. `Random` therefore stays nil,
`IsMerge` is false, and the jump table binds `0x44` to `opDifficulty`. Verified live:
`difficulty: 0x2`.

Any contract using `block.prevrandao` as an entropy source on Core is reading a
one-bit value, with no revert and no signal. The identical construction exists at the
same line in `bnb-chain/bsc`, and BSC's row does not currently record it — see
"Follow-ups" below.

## 5. `mixHash` has been repurposed to carry milliseconds

```go
func (h *Header) SetMilliseconds(ms uint64) { h.MixDigest = common.Hash(uint256.NewInt(ms % 1000).Bytes32()) }
func (h *Header) MilliTimestamp() uint64    { return h.Time*1000 + <mixHash as uint> }
```

and the RPC exposes `milliTimestamp` on every block. On Core it is dormant today —
`mixHash` was zero in every block sampled, so `milliTimestamp` is exactly
`timestamp × 1000` — but the field is already consensus-visible, and the same
construction is **already active on BSC**, where `mixHash` carried `0x352` (850) at the
block sampled. Wherever it is switched on, `block.mixHash` becomes a number in
`[0, 999]`.

This is the third meaning the dataset has recorded for a repurposed header field,
after OP Stack's `blobGasUsed` (DA footprint) and Avalanche's (pinned to zero).

## 6. Two consensus rules are six days old

`CoreRewardFix` activated 2026-09-03, six days before this row was written, and does
two things:

```go
if p.chainConfig.IsCoreRewardFix(header.Number, header.Time) {
	if _, ok := types.ParseDelegation(state.GetCode(header.Coinbase)); ok {
		return errors.New("coinbase account carries an EIP-7702 delegation")
	}
}
```

and `verifyNonSystemZeroGasTxs`, which invalidates a block containing any
zero-effective-gas-price transaction not addressed to a system contract. The comment
above the first says why: *"The block reward path treats `msg.sender ==
block.coinbase` as an implicit authorization for the system reward call, so a coinbase
that carries an EIP-7702 delegation designator can re-enter that path from ordinary
transactions."*

That is an EIP-7702 interaction with a Parlia-derived reward path, closed by a fork,
on a live chain, last week. Any analysis of Core's reward path from before that date
describes a different chain — and the pattern is worth checking on every PoSA chain
that treats the coinbase as an implicit authorizer.

## 7. System contract bytecode changes at forks, with no transaction

`TryUpdateBuildInSystemContract` calls `statedb.SetCode` for the contracts a fork
revises; `CoreRewardFix` ships a new `ValidatorContract` as an embedded file. Hermes
additionally moved the swap from the **start** of the block to the **end**, so the
same fork changed *when within a block* the change is observable. A code hash captured
before a fork will not match after it, and there is nothing on chain to explain why.
`chain.yaml` records this under `system_contracts.mutable_bytecode`, the same key BSC
uses.

## 8. The negative results

No custom transaction type. No custom opcode. The full Prague base precompile range at
mainnet addresses and mainnet prices, including EIP-2537 BLS and KZG. EIP-7702
accepted. Sampled live, 44 transactions across 30 blocks were types `0x00` and `0x02`
only.

So a survey that diffs type bytes and base precompiles reports Core as
mainnet-equivalent, and misses every one of §2 through §7.

Blob transactions are the one place the row hedges. The header carries
`blobGasUsed`/`excessBlobGas` (both zero live), `VerifyEIP4844Header` runs from
Cancun, and the pool admits type `0x03` — but there is no consensus layer to hold
sidecars, and whether a blob transaction has ever been included is recorded as not
established rather than guessed.

## Follow-ups this row raises for other rows

- **BSC (`chains/bnb/`) has the same `block.prevrandao` construction** and no
  `eips.4399` entry. Verified live here (difficulty `0x2`, mixHash `0x352`) but not
  changed on that row, because it is outside this pass's scope.
- BSC's `mixHash` is already carrying sub-second timestamps, which its
  `header_fields` section does not mention.

---

## Re-verify

```bash
R=https://rpc.coredao.org
B=0x24c61ba     # 38560250
C=chains/core/repos/core-chain

# F1: it is a BSC fork
grep -n 'Binance smart chain' $C/CHANGELOG.md
grep -n 'bnb-chain' $C/go.mod
sed -n '155,196p' $C/params/config.go

# F2: the precompile addresses, and the silent gap at 0x66
sed -n '163,173p' $C/core/vm/contracts.go
sed -n '263,296p' $C/core/vm/contracts.go
for a in 64 65 66 0100; do
  printf '0x%s -> ' $a
  curl -s -X POST $R -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x$(printf '%040s' $a | tr ' ' 0)\",\"data\":\"0x00\"},\"$B\"]}"
  echo
done      # 0x64 revert-free empty gas path, 0x65 reverts, 0x66 -> 0x, 0x0100 -> 0x
cat $C/core/systemcontracts/const.go

# F3: the fee market
sed -n '515,545p' $C/core/state_transition.go
sed -n '546,662p' $C/core/state_transition.go
sed -n '18,52p' $C/eth/feemarket/feemarket.go
grep -n 'FeeMarketDistributeGas' $C/params/protocol_params.go
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x0000000000000000000000000000000000001016\",\"$B\"]}" | head -c 80

# F4: prevrandao is the difficulty
sed -n '70,90p' $C/core/evm.go
grep -n 'chainRules:  chainConfig.Rules' $C/core/vm/evm.go
grep -n 'case rules.IsMerge' -A4 $C/core/vm/jump_table.go
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",false]}" \
  | python3 -c 'import sys,json;b=json.load(sys.stdin)["result"];print({k:b[k] for k in ("difficulty","mixHash","milliTimestamp","timestamp")})'
# the same construction on BSC, where mixHash is already in use:
curl -s -X POST https://bsc-dataseed.bnbchain.org -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["latest",false]}' \
  | python3 -c 'import sys,json;b=json.load(sys.stdin)["result"];print({k:b[k] for k in ("difficulty","mixHash")})'

# F5: milliTimestamp lives in mixHash
sed -n '160,175p' $C/core/types/block.go

# F6: the six-day-old rules
sed -n '1483,1500p' $C/consensus/satoshi/satoshi.go
sed -n '366,386p' $C/consensus/satoshi/satoshi.go
grep -n 'CoreRewardFixTime' $C/params/config.go

# F7: client-installed system contract bytecode
sed -n '763,782p' $C/core/systemcontracts/upgrade.go
ls $C/core/systemcontracts/corerewardfix/

# F8: the negatives
grep -rn 'TxType\s*=\s*0x' $C/core/types/transaction.go
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByNumber\",\"params\":[\"$B\",true]}" \
  | python3 -c 'import sys,json;b=json.load(sys.stdin)["result"];print(sorted({t["type"] for t in b["transactions"]}), b.get("blobGasUsed"))'

# row check
tools/.venv/bin/python tools/verify.py core
```
