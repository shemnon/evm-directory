# Blast — findings

Chain ID 81457. Client `blast-io/blast` **v1.8.0** @ `b8210548`, a monorepo holding
`blast-geth/` (execution) and `blast-optimism/` (rollup node and predeploys).
Baseline fork **cancun**. Live probes at block **40090462** (`0x263bb1e`) on
`https://rpc.blast.io`.

`web3_clientVersion` returns `Geth/v0.1.0-unstable/linux-amd64/go1.24.11`, which is
the `OPVersion` string this repo builds and carries no commit — so the pin is
confirmed as "a blast-geth build", not as this exact commit. Every state-level claim
below was therefore checked against the running network as well as against source.

---

## 1. Blast changed the account, not the token

The prediction in CANDIDATES.md was "native rebasing yield changes balances with no
transaction; a genuine state-transition delta". That is right, and it understates it.
Rebasing is not implemented as a token, a predeploy, or a system transaction. It is
implemented by **deleting `Balance` from the consensus account**.

```go
type StateAccount struct {
	Nonce uint64
	Flags uint8      // 0 = YieldAutomatic, 1 = YieldDisabled, 2 = YieldClaimable
	Fixed *big.Int   // raw representation
	Shares    *big.Int
	Remainder *big.Int
	Root     common.Hash
	CodeHash []byte
}
```

Seven RLP items where mainnet has four, and no balance among them. Balance is
**derived**:

```go
func (s *stateObject) Balance() *big.Int {
	if s.data.Flags == types.YieldAutomatic {
		return s.computeShareValue(s.db.getSharePrice())   // sharePrice*Shares + Remainder
	}
	return s.data.Fixed
}
```

`getSharePrice()` reads **storage slot 1 of a single predeploy**,
`0x4300…0000` (`Shares.sol`). Verified live at block 40090462: share price
1,078,198,508 wei, share count 13,564,913,432,615, product 14,625.89 ETH.

For a sampled EOA the identity holds exactly:

```
shares 92,257,479 · remainder 165,240,044 · price 1,078,214,892
price*shares + remainder = 99,473,387,921,417,312 == eth_getBalance
```

## 2. Balances move with no transaction — measured, not inferred

The share price is raised by `addValue(uint256)` on the Shares predeploy, callable
only by the aliased L1 yield reporter. That call arrives as an **OP Stack deposit
transaction, type `0x7e`**. At block 40051137 the reporter posted 1.017 ETH of yield
(tx `0xb029b9c8…`, from `0xa9188db0…`) and the price rose from 1,078,139,877 to
1,078,214,892.

Two accounts that appear **nowhere** in that block's seven transactions gained ETH
across it:

| account | balance @ 40051136 | balance @ 40051137 | delta (wei) |
|---|---|---|---|
| `0xd2f2dc75…` | 1,400,555,525,696,954 | 1,400,652,973,782,674 | 97,448,085,720 |
| `0x4cf89f51…` | 26,957,720,791,111,404 | 26,959,596,459,945,159 | 1,875,668,833,755 |

No log, no receipt, no trace, and — this is the part that has no analogue elsewhere in
the dataset — **no write to their account leaves**. Their `Shares` and `Remainder` are
unchanged; only a number in someone else's storage moved. An indexer that
reconstructs balances from transfers is wrong on Blast from the first yield report
onward, and cannot be fixed by watching more events, because there are none to watch.

Compare Injective, whose batch auction "moves EVM-visible balances with no
transaction, receipt, log or trace": there the balances are *written*. Here they are
not written at all.

## 3. `eth_getProof` returns no balance

EIP-1186 specifies `{balance, codeHash, nonce, storageHash, accountProof,
storageProof}`. Blast returns:

```json
{"address":"0x4300…0002","accountProof":[…6 nodes…],
 "flags":"0x1","fixed":"0x0","shares":"0x0","remainder":"0x0",
 "codeHash":"0x7f5f4dba…","nonce":"0x0","storageHash":"0x2d40fa77…","storageProof":[]}
```

and the leaf is `f847 80 01 80 80 80 a0<storageRoot> a0<codeHash>` — a seven-item
list. A verifier written for Ethereum fails to decode it; a JSON client reading
`result.balance` gets `undefined`, silently. This is the sharpest form of the
`state-proof` problem in this dataset: not a different value, a different *shape*.

## 4. `0x0100` is occupied, and not by P256VERIFY

The README's standing finding is that `0x0100` "was the one universal address" —
eleven rows carry P256VERIFY there, two leave it empty. Blast is the third case and a
new one: the address holds a **live, ABI-dispatched, state-mutating precompile**.

```go
common.BytesToAddress([]byte{1, 0}): &blast{},   // in Berlin and Cancun maps alike
```

Four selectors — `claim`, `configure` (both gated on `caller == 0x4300…0002`),
`getClaimableAmount`, `getConfiguration` — with a 100,000-gas default that consumes
the budget before reverting on anything else. Verified live:
`getConfiguration(0x4300…0002)` returns `0x…01` (VOID), and `eth_getCode` on the
address returns `0x`.

So the three states of `0x0100` across the dataset are now: P256VERIFY, empty, and
**something else entirely**. Neither "call it and check for output" nor "check
`eth_getCode`" distinguishes the third case from the first two.

Blast also changed the precompile *interface* to make this possible:

```go
Run(caller common.Address, input []byte, db StateDB, readOnly bool) ([]byte, error)
```

Precompiles on this chain read and write state.

## 5. The precompile ladder is frozen at Cancun while the config file is not

`params/config.go` has `PragueTime`, `OsakaTime`, the whole BPO ladder and even a
Blast-specific `BPO2BlastTime`. `core/vm/contracts.go` is still the geth-1.13 file:
`ActivePrecompiles` has no Prague or Osaka case, and `PrecompiledContractsBLS` sits in
the file at the **abandoned draft addresses 0x0a–0x12**, referenced by nothing.

Against the network that is the correct reading. `config/rollup.json` names
regolith / canyon / delta / ecotone / **taiga** and stops; taiga has no
execution-layer effect. Confirmed live: EIP-4788's beacon-roots contract has code,
EIP-2935's history contract does not, MCOPY works, and `0x0b` returns empty. Blast is
**three OP forks behind** — no Fjord, Granite, Holocene, Isthmus or Jovian — which
means it has none of OP Stack's precompile input caps and no RIP-7212. Same shape as
opBNB, arrived at independently.

## 6. The coinbase is not paid, and the fallback that pays it is invisible

On the normal path, `AllocateDevGas` splits **base fee plus priority fee** across the
contracts a transaction touched, in proportion to the gas each consumed, crediting the
Gas predeploy and writing one packed storage slot per accruing contract.
`st.state.AddBalance(Coinbase, fee)` is skipped.

The other branch is labelled `CANARY` in the source:

```go
isGasAccountingCorrect := st.gasUsed() == gasTracker.GetGasUsed()
if !skipTip && !isGasAccountingCorrect {   // --> default to original behavior … CANARY
	st.state.AddBalance(st.evm.Context.Coinbase, fee)
}
```

If the client's per-contract gas counter disagrees with the standard total, fee
routing silently reverts to ordinary OP Stack behaviour for that transaction. The fee
destination is therefore not a property of the chain but of whether two counters
agreed, and nothing in the receipt says which branch ran.

## 7. Gas depends on call depth

Past frame 5 (`BlastMaxFrameCount`), the first `CALL`/`CALLCODE`/`DELEGATECALL`/
`STATICCALL` into an address that has not yet used gas costs an extra
`SstoreResetGasEIP2200 + ColdSloadCostEIP2929` = **7,100 gas**; `CREATE` and `CREATE2`
pay it unconditionally past that depth. This pays for the gas-tracker storage write.

No other row in this dataset prices an opcode by **depth**. The practical effect is
that `eth_estimateGas` on a top-level call under-predicts the same code invoked from
inside a router or a multicall, by 7,100 per newly-touched address.

## 8. The defaults differ by account kind

`NewEmptyStateAccount` leaves `Flags = 0` — **YieldAutomatic** — so every EOA earns
yield. `EVM.create` sets `YieldDisabled` immediately after the endowment transfer, so
every deployed contract starts **VOID** and forfeits its yield until someone calls
`configure` through the Blast predeploy. And both `opSelfdestruct` and
`opSelfdestruct6780` call `SetFlags(self, YieldAutomatic)` *before* reading the
balance, so a CLAIMABLE contract transfers a different amount on self-destruct than
`eth_getBalance` reported for it a moment earlier.

## 9. What the schema could not hold

`chain.yaml` has no axis for the account representation. `header_fields` is empty
because the header is stock OP Stack; `tx_types` carries nothing Blast invented. The
single most consequential fact about this chain — that a Merkle proof of an account is
not an Ethereum account — is recorded in `gotchas`, in `eips.1186`, and in METHOD.md's
"Axes the schema does not model" table. That is the third entry in that table and the
first one that is about **state** rather than about execution.

---

## Re-verify

```bash
R=https://rpc.blast.io
B=0x263bb1e     # 40090462

# F1: the account has no Balance field
sed -n '28,50p' chains/blast/repos/blast/blast-geth/core/types/state_account.go
grep -n 'func (s \*stateObject) Balance' -A6 chains/blast/repos/blast/blast-geth/core/state/state_object.go
grep -n 'sharePriceSlot\|shareCountSlot\|getSharePrice\|adjustShareCount' \
  chains/blast/repos/blast/blast-geth/core/state/statedb.go

# F1/F3: eth_getProof returns flags/fixed/shares/remainder and NO balance
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getProof\",\"params\":[\"0x4300000000000000000000000000000000000002\",[],\"$B\"]}" \
  | python3 -c 'import sys,json;r=json.load(sys.stdin)["result"];print(sorted(r));print(r["accountProof"][-1])'

# F1: balance == sharePrice*shares + remainder
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getStorageAt\",\"params\":[\"0x4300000000000000000000000000000000000000\",\"0x1\",\"$B\"]}"   # share price
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getStorageAt\",\"params\":[\"0x4300000000000000000000000000000000000000\",\"0x33\",\"$B\"]}"  # share count (slot 51)

# F2: a balance change with no transaction touching the account
for b in 0x263bb00 0x263bb01; do   # 40051136, 40051137
  curl -s -X POST $R -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBalance\",\"params\":[\"0x4cf89f51e090d6dcddbbbe5a458a01e9061823c5\",\"$b\"]}"
done
curl -s -X POST $R -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["0x263bb01",true]}' \
  | python3 -c 'import sys,json;b=json.load(sys.stdin)["result"];print(len(b["transactions"]));print([(t["type"],t["to"]) for t in b["transactions"]])'
grep -n 'function _addValue' -A10 chains/blast/repos/blast/blast-optimism/packages/contracts-bedrock/src/L2/Shares.sol

# F4: 0x0100 is Blast's precompile, and it answers
grep -n 'BytesToAddress(\[\]byte{1, 0})' chains/blast/repos/blast/blast-geth/core/vm/contracts.go
sed -n '1182,1215p' chains/blast/repos/blast/blast-geth/core/vm/contracts.go
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"0xc44b11f70000000000000000000000004300000000000000000000000000000000000002\"},\"$B\"]}"   # 0x..01
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x0000000000000000000000000000000000000100\",\"$B\"]}"    # 0x

# F5: the ladder stops at Cancun; the network agrees
grep -n 'func ActivePrecompiles' -A14 chains/blast/repos/blast/blast-geth/core/vm/contracts.go
python3 -c 'import json;print(json.load(open("chains/blast/repos/blast/config/rollup.json")).keys())'
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x0000F90827F1C53a10cb7A02335B175320002935\",\"latest\"]}"   # 0x  (no Prague)
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x000000000000000000000000000000000000000b\",\"data\":\"0x00\"},\"latest\"]}"  # 0x  (no EIP-2537)

# F6: the coinbase branch, and the CANARY
sed -n '529,585p' chains/blast/repos/blast/blast-geth/core/state_transition.go
grep -n 'AllocateDevGas' -A40 chains/blast/repos/blast/blast-geth/core/vm/gas_tracker.go

# F7: +7,100 gas past frame 5
sed -n '178,190p' chains/blast/repos/blast/blast-geth/core/vm/operations_acl.go
grep -n 'BlastMaxFrameCount\|BlastGasParamStorageGas' chains/blast/repos/blast/blast-geth/params/protocol_params.go

# F8: yield defaults
grep -n 'SetFlags' chains/blast/repos/blast/blast-geth/core/vm/evm.go \
  chains/blast/repos/blast/blast-geth/core/vm/instructions.go

# row check
tools/.venv/bin/python tools/verify.py blast
```
