# Sei

**Client:** `sei-protocol/sei-chain` `v6.6.1` (`43d1152e`), Go
**Companion:** `sei-protocol/go-ethereum` `v1.15.7-sei-17` (`929fc329`) — the EVM itself
**Chain ID:** 1329 (`pacific-1`) · **Baseline:** Prague · **Live probes:** block `226969278`

Sei is a Cosmos-SDK chain whose EVM interpreter is a maintained fork of go-ethereum.
The interpreter tracks upstream; nothing around it does. `role: fork` describes only
the part of Sei that descends from geth by code.

---

## The headline: `0x0100` is empty and Sei *has* P256VERIFY

The dataset's standing observation was that `0x0100` is the one address twelve of
thirteen rows agree on, and that Hyperliquid — where it is empty — is the exception
that makes it interesting. Sei is a stronger counterexample, because it is not a
chain that skipped the feature.

- Sei's secp256r1 verifier is at **`0x…1011`**.
- The geth fork's precompile switch tops out at `PrecompiledContractsPrague`. There is
  no Osaka branch, so `0x0100` is never populated by the built-in map.
- Custom precompiles are installed **only where the built-in map is empty**
  (`core/vm/evm.go:NewEVM` tests `if _, exists := evm.precompiles[addr]; !exists`), so
  Sei structurally cannot place anything at a mainnet address.
- `0x0100` is therefore an ordinary empty account. Calling it succeeds and returns
  empty output — which EIP-7951 defines as *invalid signature*.

Verified live against a *known-valid* signature (the wycheproof `CallP256Verify`
vector shipped in the Kaia repo's `p256Verify.json`), because the obvious probe cannot
distinguish "invalid" from "absent":

```
eth_call 0x0000000000000000000000000000000000000100  ->  0x
eth_call 0x0000000000000000000000000000000000001011  ->  0x…0020 0020 …0001
```

A passkey wallet ported to Sei fails closed, silently, forever — the second
independent arrival at the Hyperliquid failure mode, by a completely different route.

## Second-order: Sei's precompiles are ABI-dispatched

Not a placement difference — a **category** difference. Every one of the thirteen
custom precompiles dispatches on a 4-byte Solidity method selector and ABI-encodes its
result. `0x…1011` implements `verify(bytes)` (`0x8e760afe`), so the 160-byte RIP-7212
payload must be wrapped in an ABI `bytes` argument. Sending the bare 160 bytes
**reverts**. Gas is 300 per input byte, not a flat 3450 or 6900. `DELEGATECALL` is
refused.

They are still precompiles by SCHEMA.md's definition — native Go, no bytecode in
state, `EXTCODESIZE` 0 (verified live) — but no mainnet precompile behaves this way,
and no generic precompile prober will get a result out of one.

## The address block: `0x1001`–`0x100c`, plus `0x1011`

| addr | name | what it reaches |
|---|---|---|
| `0x…1001` | bank | Cosmos bank module: non-EVM denominations |
| `0x…1002` | wasmd | instantiate/execute/query CosmWasm — **re-enters the EVM** |
| `0x…1003` | json | JSON helpers for CosmWasm responses |
| `0x…1004` | addr | **address association**: `getSeiAddr` / `getEvmAddr` / `associate` |
| `0x…1005` | staking | delegate / undelegate / redelegate |
| `0x…1006` | gov | vote and deposit on governance proposals |
| `0x…1007` | distribution | |
| `0x…1008` | oracle | validator-voted price feed |
| `0x…1009` | ibc | initiates IBC transfers from EVM bytecode |
| `0x…100a` | pointerview | |
| `0x…100b` | pointer | deploys ERC-20/721/1155 pointer contracts |
| `0x…100c` | solo | `claim` / `claimSpecific` |
| `0x…1011` | P256VERIFY | **not contiguous** — `0x100d`–`0x1010` are unallocated |

Four orders of magnitude above every existing row's custom block (BSC/Arbitrum
`0x64`–`0x69`, Polygon/BSC `0x…1000`, Tron `0x1000001`+). The address table generalises,
but only because it was already keyed on full 20-byte addresses.

Two wiring traps found while establishing this:

- `precompiles/setup.go` contains **two disagreeing lists**. `InitializePrecompiles`
  (which mutates geth's global maps) omits `solo` and is only ever called with
  `dryRun=true` to harvest ABIs. `GetCustomPrecompiles` is the live path
  (`app/app.go` → `Keeper.SetCustomPrecompiles` → `vm.NewEVM`) and has all thirteen.
  The row cites the live path.
- Each address carries a **per-upgrade version map** keyed by Sei's own named software
  upgrades, selected by the height at which that governance upgrade completed
  (`x/evm/keeper/keeper.go:GetCustomPrecompilesVersions`). "The precompile at `0x1001`"
  is a family, not a contract.

## The dual address space *does* change `CALLER` / `ORIGIN`

Yes — and worse than expected.

An unassociated Cosmos account's EVM address is `common.BytesToAddress(seiAddress)`:
a **raw byte-cast of its bech32 payload**, unrelated to its public key
(`x/evm/keeper/address.go:GetEVMAddressOrDefault`). After it associates, it resolves to
the real secp256k1-derived address. So `msg.sender` and `tx.origin` for the *same*
Cosmos account are **two different addresses before and after association**.

`utils/helpers/associate.go:MigrateBalance` moves native balances (and the sub-`usei`
"wei" remainder) from the cast address to the sei address at association time. It does
**not** move ERC-20 balances, allowances, or any contract storage keyed on the old cast
address. Those are stranded at an address nobody controls, with no event a contract can
react to.

The reverse edge also bites: `CanAddressReceive` returns false for a cast address whose
EVM counterpart has already associated — the same 20 bytes are a valid bank recipient
before association and an invalid one after.

## Other integrator-breaking findings

- **The base fee is not burned.** `baseFee + tip` is credited in full to the fee
  collector as the coinbase reward, with an in-source comment saying so
  (`core/state_transition.go`). Sei's fee market is also not EIP-1559: ±1.89% / −0.39%
  per block toward a 250k-gas target, clamped between governance floor and ceiling.
- **`PREVRANDAO` is `keccak256(block timestamp)`.** Fully predictable. Contracts using
  it for randomness are exploitable and show no outward sign.
- **Receipts with `type: 0xffffffff` exist.** Cosmos/CosmWasm transactions emitting
  EVM-shaped logs get a synthetic receipt whose type is `math.MaxUint32` — outside the
  legal EIP-2718 range by a factor of 2^25. `eth_getLogs` returns their logs.
- **Blob transactions are registered then refused.** `0x03` is in `AllowedTxTypes` from
  Cancun on and unconditionally rejected by the ante handler → recorded `tombstoned`.
- **`AssociateTx` is a free, nonce-less, type-less state-changing transaction.** Its
  `TxType()`, `GetNonce()`, `GetGas()`, `GetValue()` and `GetTo()` all *panic*.
- **The Ethereum block is a fiction, and `stateRoot` is the worst field in it.** It
  carries the Tendermint app hash — a commitment to the whole Cosmos multistore — under
  the name and shape of an Ethereum state root. No Ethereum state proof against it can
  verify. `mixHash` is the zero hash, not the value `PREVRANDAO` returned.
- **`SeiSstoreSetGasEIP2200`** is a `params.ChainConfig` field in the fork that
  overrides the clean-zero→nonzero `SSTORE` cost in both the EIP-2200 and EIP-2929 gas
  paths, refunds included. Default 20000 = mainnet. The mechanism has no mainnet
  analogue; whether `pacific-1` runs the default is a live value, not a source fact.

## Where the schema strained

- **`role`.** Sei is a code fork of geth *in the interpreter only*. Everything else —
  envelope, accounts, fees, blocks, addresses — is a rewrite. `fork` overstates
  equivalence; `independent` would understate the literal shared code. Recorded as
  `fork` with a `chain.note` saying which half it applies to. No new key proposed.
- **`header_fields`.** The section assumes a header exists to diff. Sei's consensus
  block is a Tendermint block; the Ethereum header is *assembled at RPC time* and is
  not hashed, signed or committed to. Recorded under `header_fields` anyway, with a
  section `note` saying so, because an integrator reading those fields cannot tell.
- **`system_contracts`.** Sei's pointer contracts are real EVM bytecode installed by
  the chain rather than by a user — but at addresses derived per asset at registration
  time. Neither a predeploy set nor a `dynamic_range` predicate. Recorded as a note.
- **Two upgrade axes.** `forks.timeline` models one sequence. Sei has two that do not
  line up: Ethereum fork level (all at genesis) and Sei's own governance-scheduled
  software upgrades (which are what actually gate precompile semantics). Recorded in
  `forks.note`; the timeline shows only the Ethereum axis.

## Deliberately not established

Nothing is marked `status: unrecorded` in this row, but these are *not* established and
are called out rather than guessed:

- **Whether `pacific-1` currently runs the default `SeiSstoreSetGasEIP2200` (20000).**
  It is a live chain-config value; source gives only the default. Recorded as
  `eips.2200: modified` with the uncertainty stated in the note, rather than as
  `inherited` (which would assert equivalence) or `unrecorded` (which would hide that
  the mechanism exists).
- **The exact `usei` ↔ EVM-gas conversion multiplier.** Established that one exists
  (`sdk.NewInfiniteGasMeterWithMultiplier`); the constant lives in `sei-cosmos`, a
  vendored subtree, and is not pinned as a separate repo.
- **The full Cosmos-SDK message set.** `non_evm_transactions` lists Sei's own
  `x/evm` messages exhaustively. Standard bank/staking/gov/IBC/wasm messages are noted
  as a population but not enumerated — they are stock Cosmos SDK, and their EVM-visible
  effects are reachable through `0x1001`–`0x100c`.
- **Whether `includeSyntheticTxs` defaults on or off per RPC method.** Established that
  the flag exists and gates the `0xffffffff` receipts differently on different paths.
- **Precompile extractor.** `verify.py` reports `! NO EXTRACTOR` for this row; the
  address list is taken on trust from `precompiles/setup.go:GetCustomPrecompiles`.

---

## Re-verify

```bash
# 1. Re-fetch the pinned evidence (both repos)
git clone --depth 1 --branch v6.6.1 \
  https://github.com/sei-protocol/sei-chain chains/sei/repos/sei-chain
git -C chains/sei/repos/sei-chain rev-parse HEAD   # 43d1152e06ed9020d39e10da706451718b66c804

git clone --depth 1 --branch v1.15.7-sei-17 \
  https://github.com/sei-protocol/go-ethereum chains/sei/repos/go-ethereum
git -C chains/sei/repos/go-ethereum rev-parse HEAD # 929fc329f2a82d97c51a97233f394f8d66d9cfc5

# 2. Re-check every citation in chain.yaml
tools/.venv/bin/python tools/verify.py

# 3. The thirteen custom precompile addresses (the live registration path)
sed -n '/^func GetCustomPrecompiles/,/^}/p' chains/sei/repos/sei-chain/precompiles/setup.go

# 4. Confirm the built-in map has no 0x0100 — the fork stops at Prague
sed -n '/^var PrecompiledContractsPrague/,/^}/p' \
  chains/sei/repos/go-ethereum/core/vm/contracts.go
grep -n "case rules.Is" chains/sei/repos/go-ethereum/core/vm/contracts.go

# 5. Confirm custom precompiles cannot shadow a built-in
sed -n '/^func NewEVM/,/^}/p' chains/sei/repos/go-ethereum/core/vm/evm.go

# 6. Base fee is credited, not burned
grep -n "burn the base fee" -A 2 \
  chains/sei/repos/go-ethereum/core/state_transition.go

# 7. PREVRANDAO = keccak256(timestamp); BLOBBASEFEE = 1; GASLIMIT = consensus MaxGas
sed -n '/^func (k \*Keeper) GetVMBlockContext/,/^}/p' \
  chains/sei/repos/sei-chain/x/evm/keeper/keeper.go

# 8. Dual address space: cast-vs-derived, and what migrates
sed -n '/^func (k \*Keeper) GetEVMAddressOrDefault/,/^}/p;/^func (k \*Keeper) CanAddressReceive/,/^}/p' \
  chains/sei/repos/sei-chain/x/evm/keeper/address.go
sed -n '/^func (p AssociationHelper) MigrateBalance/,/^}/p' \
  chains/sei/repos/sei-chain/utils/helpers/associate.go

# 9. Blob txs: permitted by the type table, refused by the ante handler
grep -n "AllowedTxTypes" -A 5 chains/sei/repos/sei-chain/x/evm/ante/preprocess.go
grep -n "ErrUnsupportedTxType" chains/sei/repos/sei-chain/x/evm/ante/basic.go

# 10. AssociateTx: every envelope accessor panics
cat chains/sei/repos/sei-chain/x/evm/types/ethtx/associate_tx.go

# 11. The 0xffffffff synthetic receipt type
grep -n "ShellEVMTxType" chains/sei/repos/sei-chain/x/evm/types/constants.go \
                          chains/sei/repos/sei-chain/app/receipt.go

# 12. The RPC-synthesised "Ethereum" block
sed -n '/^func EncodeTmBlock/,/^}/p' chains/sei/repos/sei-chain/evmrpc/block.go | tail -40
```

### Replay the live probes

Any archive node at block `226969278` (`0xd867abe`) or later. `V` is the wycheproof
`CallP256Verify` vector shipped in
`chains/kaia/repos/kaia/blockchain/vm/testdata/precompiles/p256Verify.json` (entry 0),
which the Kaia row independently confirms is **valid**.

```bash
SEI=https://evm-rpc.sei-apis.com
V=4cee90eb86eaa050036147a12d49004b6b9c72bd725d39d4785011fe190f0b4da73bd4903f0ce3b639bbbf6e8e80d16931ff4bcf5993d58468e8fb19086e8cac36dbcd03009df8c59286b162af3bd7fcc0450c9aa81be5d10d312af6c66b1d604aebd3099c618202fcfe16ae7770b0c49ab5eadf74b754204a3bb6060e44eff37618b065f9832de4ca6ca971a7a1adc826d0f7c00181a5fb2ddf79ae00b4e10e

# 0x0100 is an empty account, and a VALID signature there returns empty output
curl -s -X POST $SEI -H 'content-type: application/json' -d \
 '{"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":["0x0000000000000000000000000000000000000100","0xd867abe"]}'
curl -s -X POST $SEI -H 'content-type: application/json' -d \
 "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"0x$V\"},\"0xd867abe\"]}"
# -> "0x"  and  "0x"

# 0x1011, ABI-wrapped as verify(bytes) — selector 8e760afe, offset 0x20, length 0xa0
curl -s -X POST $SEI -H 'content-type: application/json' -d \
 "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000001011\",\"data\":\"0x8e760afe00000000000000000000000000000000000000000000000000000000000000200000000000000000000000000000000000000000000000000000000000000a0$V\"},\"0xd867abe\"]}"
# -> 0x...0020 ...0020 ...0001   (valid)

# the same vector sent raw to 0x1011 reverts — the precompile is ABI-dispatched
curl -s -X POST $SEI -H 'content-type: application/json' -d \
 "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000001011\",\"data\":\"0x$V\"},\"0xd867abe\"]}"
# -> error: execution reverted
```

The `verify(bytes)` selector is derivable from the pinned source rather than assumed:

```bash
cd chains/sei/repos/sei-chain
cat > precompiles/p256/zz_sel_test.go <<'GOEOF'
package p256

import "testing"
import pcommon "github.com/sei-protocol/sei-chain/precompiles/common"

func TestZZSel(t *testing.T) {
	a := pcommon.MustGetABI(f, "abi.json")
	for n, m := range a.Methods {
		t.Logf("SELECTOR %s = %x", n, m.ID)
	}
}
GOEOF
go test ./precompiles/p256/ -run TestZZSel -v 2>&1 | grep SELECTOR   # verify = 8e760afe
rm precompiles/p256/zz_sel_test.go
```
