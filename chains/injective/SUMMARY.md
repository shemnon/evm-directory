# Injective

**Role:** `fork` · **Upstream:** `cosmos-evm` · **Chain ID:** 1776 · **Baseline:** Prague
**Client:** [`InjectiveFoundation/injective-core`](https://github.com/InjectiveFoundation/injective-core)
`v1.20.3` (`5c3143ed621ed4e4a5d74d64ea952f5a8cda4c1f`)
**Live probes:** `https://sentry.evm-rpc.injective.network` @ block `180071265` (`0xabbab61`)

A Cosmos SDK L1 whose EVM runs beside a frequent-batch-auction derivatives exchange
that shares its account space and its balances. This file records only Injective's own
deltas; the Cosmos-EVM shape — the `MsgEthereumTx` wrapper, the fabricated Ethereum
block, the CometBFT-derived opcodes, the module-account fee sink — resolves through
[`chains/cosmos-evm/`](../cosmos-evm/chain.yaml).

**The repo moved.** `InjectiveLabs/injective-core` is a 404. The source is at
`InjectiveFoundation/injective-core`, while `go.mod` still replaces the Cosmos SDK,
CometBFT, ibc-go, wasmd, gogoproto and go-ethereum with `InjectiveLabs/*` forks — the
module paths point at one org and the code at another.

## 1. Yes: the exchange moves balances the EVM observes, every block

This is what the row was commissioned to answer, and the answer is unambiguous.

Injective's `EndBlocker` runs a frequent batch auction over the whole order book —
conditional triggers, then market orders, then limit orders, each matched at a uniform
clearing price and persisted
(`injective-chain/modules/exchange/abci.go:EndBlocker`). Settlement normally stays
inside the exchange module's subaccount ledger. **Except for default subaccounts**:

```go
// exchange/keeper/subaccount/keeper.go:SetDepositOrSendToBank
shouldSendFundsToBank := amountToSendToBank.IsPositive() && types.IsDefaultSubaccountID(subaccountID)
if shouldSendFundsToBank {
    accountAddress := types.SubaccountIDToSdkAddress(subaccountID)
    err := k.bank.SendCoinsFromModuleToAccount(ctx, types.ModuleName, accountAddress, ...)
```

A *default* subaccount is one whose last 12 bytes are zero
(`IsDefaultSubaccountID`), and its address is the plain 20-byte account —
`SubaccountIDToEthAddress` literally returns `common.BytesToAddress(subaccountID[:20])`.
The positive integer part of a settled balance is sent to that account's **bank
balance**, and `ChargeBank` pulls from the bank balance when it goes negative.

The EVM reads that balance directly:

```go
// evm/keeper/keeper.go:GetBalance
return k.bankKeeper.SpendableCoin(ctx, addr, denom).Amount.BigInt()
```

So `address.balance` and `SELFBALANCE` change between two EVM transactions with **no
EVM transaction, no receipt, no log and no trace frame in between** — and, because most
Injective blocks contain no EVM transactions at all, usually with no Ethereum-visible
artifact of the block whatsoever. Same class as Blast's rebasing yield, Flare's treasury
sweeps and Gnosis's withdrawal credits, and larger than any of them in volume: 54 of 60
consecutive probed blocks had zero EVM transactions and millions of gas used.

Recorded in `system_transactions.fba_settlement_to_bank`. One honest limit: it bites
accounts trading from their **default** subaccount; balances in nonce-derived
subaccounts stay inside the exchange module and are visible to the EVM only through the
`0x65` precompile's queries.

### A second, quieter instance in the same line of code

`GetBalance` returns `SpendableCoin`, not the total balance — it **excludes
vesting-locked coins**. A vesting account's EVM balance therefore *grows as the schedule
unlocks*: `address.balance` rises between blocks with no transaction of any kind, EVM or
Cosmos, and nothing emits an event. The framework's `GetBalance` has no such
subtraction.

## 2. Four precompiles, on the worst four addresses in the dataset

```go
bankContractAddress     = common.BytesToAddress([]byte{100})   // 0x64
exchangeContractAddress = common.BytesToAddress([]byte{101})   // 0x65
stakingContractAddress  = common.BytesToAddress([]byte{102})   // 0x66
oracleContractAddress   = common.HexToAddress("0x…0067")       // 0x67
```

README.md already flags `0x64`–`0x69` as the dataset's collision zone: Arbitrum's
ArbSys, ArbInfo, ArbAddressTable, ArbBLS, ArbFunctionTable and ArbosTest sit there, and
BSC uses the same six for its cross-chain and consensus precompiles, with opBNB making
`0x66` and `0x67` three-way. **Injective makes all four of `0x64`–`0x67` four-way**,
with no shared code between any of them. Any tool holding one global address-keyed
precompile map is now wrong on four addresses across four major chains.

It also shares *nothing* of the framework's layout: `cosmos/evm` went to `0x0100`,
`0x0400` and `0x0800`–`0x0807`, deliberately clear of mainnet. Injective went to the
lowest custom block anyone here uses, `0x53` above mainnet's `0x11` frontier.

**Probe discipline**, since Flare and Sonic made it necessary: all four return `0x` from
`eth_getCode` — no 1-byte stub, no impersonating bytecode — **and** the source map was
read. Both tests agree, and both are recorded.

### `0x64` mints; `0x65` trades

- **`0x64` bank** — `mint`, `burn`, `transfer`, `setMetadata` alongside the queries.
  `mint`/`burn` drive the tokenfactory msg server, so an EVM contract can create and
  destroy Cosmos bank supply. The framework's bank precompile at `0x0804` is
  **query-only** (`IsTransaction` returns `false` unconditionally), so this is
  Injective's own escalation, not something inherited.
- **`0x65` exchange** — the most powerful precompile in this dataset. Thirty-plus
  methods: deposit, withdraw, subaccount and external transfer, create and cancel spot,
  derivative and binary-option limit and market orders in single and batch form, margin
  adjustment, plus `approve`/`revoke`/`queryAllowance`. Every one dispatches through
  `authzKeeper.DispatchActions(ctx, caller, msg)` — so **an EVM contract holding a
  Cosmos authz grant can act for a user who signed nothing in that transaction**. Note
  the ERC-20-shaped surface is misleading: `approve` here grants the right to place
  orders, not to move tokens.
- **`0x66` staking** — delegate, undelegate, redelegate, withdraw rewards.
- **`0x67` oracle** — query-only, but the answers come from validator- and
  provider-submitted feeds updated outside EVM execution, so a `STATICCALL` to `0x67` is
  not a pure function of its input or of any EVM-writable state. Same class as Flare's
  oracle precompile.

**STATICCALL safety holds** — every writer begins `if readonly { return nil, errors.New("the method is not readonly") }` — but it is a hand-written check per method rather
than the framework's shared `IsTransaction` table, and one live observation is worth
recording: an empty-calldata `CALL` to `0x66` reverts with `execution reverted:
precompile panic`, because the contract slices `contract.Input[:4]` unconditionally and
a deferred recover converts the panic. It fails safe; it is still a panic path on the
thing a wallet does by accident.

## 3. There are no gas refunds

```go
// evm/keeper/gas.go:RefundGas
// DISABLED: due to DoS attack possibility by filling up whole block gas space almost for free due to refunds
return nil
```

The ante handler has already deducted `gasLimit × gasPrice`
(`DeductTxCostsFromUserBalance`). Nothing gives it back. **Every transaction pays for
its full gas limit**, and every EIP-3529 SSTORE-clear refund is discarded — while the
receipt reports the real `gasUsed`, so nothing in the Ethereum-visible record shows the
difference. Over-estimating gas costs real money here in a way it does not on any other
chain in this dataset. Recorded as `eips.3529: removed`.

## 4. A 7702 transaction is accepted and silently does nothing

Injective has **no accepted-type mask** — nothing in `ValidateEthBasic`, the ante chain
or `ValidateBasic` inspects the type byte, and Prague is active so the signer handles
`0x04`. A `SetCodeTx` is decoded and signature-verified. Then:

```go
// evm/types/msg.go:AsMessage
ethMsg := &core.Message{
    Nonce: tx.Nonce(), GasLimit: tx.Gas(), ..., AccessList: tx.AccessList(),
    From: common.BytesToAddress(msg.From),
}   // SetCodeAuthorizations is never set. Neither is BlobHashes.
```

The authorization list is dropped before execution. No delegation is installed, no error
is raised, no revert occurs — the transaction runs as an ordinary call. Worse, the two
intrinsic-gas call sites disagree: the ante path passes `tx.SetCodeAuthorizations()`
(the real list, charged for) while `GetEthIntrinsicGas` passes
`msg.SetCodeAuthorizations` (always empty). The user is billed for authorizations the
executor never sees.

This is a **source** finding — constructing a 7702 transaction against mainnet was out
of scope. `tx_types."0x03"` is left `unrecorded` for the same reason: the same absence
of a type gate applies, but whether a blob transaction is refused downstream or executes
with its blob fields dropped was not established, and guessing would be worse.

## 5. P256VERIFY is absent at `0x0100`, proven with a valid signature

Two independent causes: the framework's own P256 precompile is not in Injective's
vendored tree, and the built-in map is `vm.DefaultPrecompiles(cfg.Rules)` with `Rules` at
**Prague**, while geth only places P256VERIFY at `0x0100` under **Osaka** — which
Injective cannot reach (there is no `OsakaTime` field anywhere in the repo).

Proven live with geth's own `CallP256Verify` fixture — a **known-valid** vector, not an
absence test — against a control on the same batch:

| call @ 180071265 | result |
|---|---|
| `0x…0100` with the valid RIP-7212 vector | `0x` (empty) |
| `0x…02` (sha256) with empty input | `0xe3b0c442…b855` — correct |
| `0x…0b` (BLS12-381 G1ADD) with empty input | `invalid input length` — Prague map present |

Because EIP-7951 signals *invalid signature* by returning empty output, every P256
verification against `0x0100` on Injective reports invalid forever, silently. **Third
instance of this exact shape in the dataset — Hyperliquid, Sei, Injective — and a third
distinct cause**: Hyperliquid never implemented it, Sei implemented it somewhere else,
Injective's fork level cannot reach it.

## 6. `tx_authorization`: ed25519 authorizes, and nothing can verify it

The framework's key switch charges `SigVerifyCostED25519` and then returns
`ErrInvalidPubKey("ED25519 public keys are unsupported")`. Sei's does the same.
Injective's copy of the same function, in `injective-chain/app/ante/ante.go:DefaultSigVerificationGasConsumer`:

```go
case *ed25519.PubKey:
    meter.ConsumeGas(params.SigVerifyCostED25519, "ante verify: ed25519")
    return nil          // accepted
```

There is no Ed25519 verifier at any address on this chain — the built-in map is Prague's
`0x01`–`0x11`, and Injective's four custom precompiles are bank, exchange, staking and
oracle. So this is **`authorizes: protocol` with `precompile: none`**, the pairing
SCHEMA.md names as the one to look for. And the state change is EVM-visible, because
Injective has one account space: an ed25519 account's Cosmos address *is* its 20-byte
EVM address (`EthAccount.EthAddress` is a straight cast), and the EVM reads its balance
out of the bank module. A contract, a multisig or a recovery module on Injective cannot
check the very signature that just moved the balance it is looking at.

It is the same unpaired-scheme shape as Sei's sr25519, reached by the opposite route:
**Sei refuses ed25519 and admits sr25519; Injective admits ed25519 and has no sr25519.**
This overrides the `cosmos-evm` row's `ed25519: never` per SCHEMA.md's override-by-key
rule, with a note.

### Two more, both in the EIP-712 path the framework leaves dead

`ante/cosmos/eip712.go` is unreachable in `evmd`. On Injective the equivalent decorator
**is wired** (`ante.go:NewAnteHandler` installs `eip712SigVerificationDecorator`), and it
carries two findings:

- **`signers_per_tx` is 2.** A transaction may carry an `ExtensionOptionsWeb3Tx` naming
  a **fee payer** and that payer's own 65-byte secp256k1 signature over the same typed
  data. Two parties, two signatures, one transaction. Kaia is the only other row here
  with a genuine second signer.
- **A typed-data signature scoped to Ethereum mainnet is accepted.**

  ```go
  // app/ante/eip712.go:GetWeb3ExtensionOptions
  // chainID in EIP712 typed data is allowed to not match signerData.ChainID, …
  // thus Metamask will be able to submit signatures without switching networks.
  hasValidMainnetChainID := signerData.ChainID == "injective-1" &&
      (extOpts.TypedDataChainID == 1 || extOpts.TypedDataChainID == 1776)
  ```

  The domain separator is the one thing EIP-712 provides to stop a signature crossing
  chains, and this deliberately disarms it for **chain id 1**, the most-used domain in
  existence. Recorded as its own scheme entry, not a footnote.

### And an environment variable that turns signature verification off

In the same function that wires the EIP-712 decorator:

```go
// app/ante/ante.go
noSignatureVerification := os.Getenv("DEVNET_NO_SIGNATURE_VERIFICATION") == "true" ||
                           os.Getenv("DEVNET_NO_SIGNATURE_VERIFICATION") == "1"
var eip712SigVerificationDecorator sdk.AnteDecorator = NewEip712SigVerificationDecorator(ak)
if noSignatureVerification { eip712SigVerificationDecorator = noopAnteDecorator{} }
var sigVerificationDecorator sdk.AnteDecorator = authante.NewSigVerificationDecorator(ak, options.SignModeHandler)
if noSignatureVerification { sigVerificationDecorator = noopAnteDecorator{} }
```

Both the EIP-712 decorator **and the ordinary Cosmos signature decorator** become
no-ops: every signature on every Cosmos transaction accepted unchecked. It is plainly
meant for devnets, and it is compiled into the mainnet binary, read from `os.Getenv` at
ante-handler construction, with no chain-id guard and no consensus parameter behind it.
SCHEMA.md's warning about config-switchable schemes applies in its strongest form — two
validators with different environments do not disagree gracefully, they disagree about
who signed what.

A fifth item, authorization *delegation* rather than a signature scheme: the `0x65`
precompile's `authzKeeper.DispatchActions(ctx, caller, msgs)` makes an EVM **contract**
an authorized actor for any account that granted it — orders, deposits, withdrawals and
subaccount transfers with no signature anywhere in the envelope.

## 7. The header is worse than the framework's in two fields

The framework's "there is no Ethereum header" finding is inherited. Injective fabricates
a **narrower** one — 21 keys, with no `withdrawalsRoot`, `blobGasUsed`, `excessBlobGas`,
`parentBeaconBlockRoot` or `requestsHash` at all, where the framework emits all five as
constants — and fabricates two of the remaining fields worse:

- **`receiptsRoot` is a hard-coded constant.** `FormatBlock` sets
  `"receiptsRoot": ethtypes.EmptyRootHash` unconditionally — not computed, not
  conditional on emptiness. Verified live: block `0xabbaa3e` contains one successful
  transaction with a real receipt and still reports
  `0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421`, the empty trie
  root. **No receipt proof, no log-inclusion proof, and no bridge verifying against
  `receiptsRoot` can ever work on Injective.** The framework at least recomputes a real
  root over the receipts it exposes.
- **`transactionsRoot` is the CometBFT `DataHash`** when the block has any EVM
  transaction, and the empty trie root otherwise — a commitment to *all* transactions in
  the CometBFT block, overwhelmingly Cosmos ones. Never a trie over the transactions
  listed beside it.
- **`gasUsed` counts Cosmos gas.** Live: 54 of 60 consecutive blocks report **zero EVM
  transactions and non-zero gasUsed**; the probed block reports `0xac4551` (11,289,937)
  with an empty transactions array. A receipt's `cumulativeGasUsed` (`0xa75259`) was two
  hundred times its own `gasUsed` (`0xd715`). Utilisation metrics computed from these
  fields are measuring the exchange.

A smaller one: `EthHeaderFromTendermint`, used by the `newHeads` websocket stream, has
an inverted condition — it assigns `TxHash` from `DataHash` only
`if len(header.DataHash) == 0`, i.e. only when there is nothing to commit to.
`cosmos/evm`'s equivalent tests `!= 0`. The two transports disagree about the same field.

## 8. BASEFEE returns 0 while the block reports a base fee

`NewEVM` hard-codes `BlockContext.BaseFee` to `big.NewInt(0)` and `VMConfig` sets
`NoBaseFee: true`. There is **no EIP-1559 base fee inside the EVM at all** — Injective
has no `x/feemarket`; it uses its own `txfees` module, an Osmosis *Mempool1559* port,
which is a **node-local mempool admission floor** and is `Mempool1559Enabled: false` by
default. The RPC backend fills `baseFeePerGas` from that subsystem anyway.

Confirmed live by `eth_call` over state-overridden bytecode:

| probe @ 180071265 | opcode result | header field |
|---|---|---|
| `0x48 5f 52 60 20 5f f3` (BASEFEE) | `0x00…00` | `baseFeePerGas` `0x9896800` |
| `0x45 …` (GASLIMIT) | `0x00…00` | `gasLimit` `0x8f0d180` |
| `0x44 …` (PREVRANDAO) | `0x00…00` | `mixHash` `0x00…00` |
| `0x4a …` (BLOBBASEFEE) | `0x00…00` | *(field not emitted)* |

Two of these are new information beyond the framework:

- **`GASLIMIT` returns 0 under `eth_call`.** `BlockGasLimit` reads
  `ctx.ConsensusParams().Block`, which is absent in the query context, so the `return 0`
  branch is taken — while a real transaction sees the true `MaxGas`. A contract that
  branches on `block.gaslimit` **simulates differently from how it executes**, which is
  the failure mode static analysis is least likely to catch. Observed under `eth_call`
  only; the in-block value was not separately measured, and the entry says so.
- **`BLOBBASEFEE` returns 0** — this is the deployed answer to the `cosmos-evm` row's
  `unrecorded` for that opcode.

**`PREVRANDAO` overrides the framework's constant with a different constant.**
`cosmos/evm` pins it to `common.MaxHash` (`0xffff…ff`); Injective pins it to the **zero
hash**, commented "not supported, always zero". Still not randomness — but a contract
that sanity-checks PREVRANDAO against a known Cosmos-EVM value gets the wrong answer,
and one that treats zero as "unavailable" behaves differently here than on any other
Cosmos EVM chain.

## 9. `lineage.sync_point`: Injective does not depend on cosmos/evm

`grep cosmos/evm go.mod` returns nothing. The EVM lives at
`injective-chain/modules/evm/` as a **vendored fork** of the shared Ethermint /
cosmos-evm tree, so every upstream change has to be hand-carried. The dataset already
has this problem with opBNB and Celo; Injective's version has four measurable
consequences, all of them *older* than the framework row:

1. **The deprecated protobuf encoding is still in the wire format.** `cosmos/evm` v0.7
   writes `reserved 1, 2, 3, 4` in `MsgEthereumTx`. Injective still declares `data` (an
   `Any` of `LegacyTx`/`AccessListTx`/`DynamicFeeTx`), `size`, `deprecated_hash` and
   `deprecated_from` beside `raw`. `ValidateBasic` now rejects a message that sets any of
   them, and `AsTransaction` still falls back to unpacking `data` when `raw` is nil — so
   the old encoding is unusable going forward and stays decodable for history. **An
   indexer written against cosmos/evm v0.7's proto, where those field numbers are
   reserved, will not parse Injective's historical transactions.**
2. **No `x/feemarket`** — see §8.
3. **No active-precompile param and no `0x0800` block.** The framework's two-step
   registration (build the map, *then* list the address in `ActiveStaticPrecompiles`)
   does not exist; Injective hard-wires four `CustomContractFn` closures at app
   construction. Its precompile set is therefore **not** per-deployment optional. Probed
   live: `0x0100`, `0x0400`, `0x0800` and `0x0803` all return `0x` from `eth_getCode`
   and empty output from `eth_call`.

   That last address matters: the `cosmos-evm` row records `0x…0803` as `tombstoned`
   because `evmd`'s genesis lists a vesting precompile that has no implementation, which
   is the branch that **panics**. **Injective does not inherit that fault** — `0x0803`
   here is an ordinary empty account. The framework row predicted a deployment-dependent
   answer; this is that answer, measured.
4. **No `OsakaTime` field.** `grep -r OsakaTime` returns nothing. Osaka is not merely
   unscheduled but unrepresentable — Injective is on the *Sei* side of the line the
   `cosmos-evm` row draws, not the framework's.

Two more inherited-mechanism absences worth stating: Injective has **no preinstall
mechanism** and **no EIP-2935 history storage** (`eth_getCode` at `0x0000F908…2935` is
`0x`), so the framework's 8191/8192 ring-buffer mismatch does not apply here at all. The
ecosystem contracts are nonetheless present — Create2 deployer, Multicall3 and Permit2
all carry their canonical bytecode at block 180071265 — deployed by ordinary
transactions rather than by genesis. **An address-and-code probe cannot distinguish the
two; only the absence of the mechanism in source shows it.**

And the ERC-20 bridging runs the *opposite direction*: `cosmos/evm` turns a bank denom
into a precompile at a derived address (its non-enumerable `dynamic_range`), whereas
Injective's `x/erc20` mints a bank denom named `erc20:0x…` for an existing ERC-20
contract. **Injective therefore has no dynamic precompile range at all** — the
framework's hardest-to-enumerate feature is simply absent.

## Comparison with Sei, the nearest existing row

| | Sei | Injective |
|---|---|---|
| address space | **dual** — unassociated accounts byte-cast to a *different* identity; `AssociateTx`; stranded ERC-20 balances | **single** — `EthAccount.EthAddress` is a straight cast of the account bytes; `inj1…` is a re-encoding; no association step, none of the hazard |
| unpaired scheme | sr25519 accepted, ed25519 refused | **ed25519 accepted**, no sr25519 |
| P256VERIFY | exists, at `0x1011`, ABI-dispatched; `0x0100` empty | **does not exist**; `0x0100` empty |
| custom precompiles | `0x1001`–`0x100c`, `0x1011` | `0x64`–`0x67` — four-way collision with BSC and Arbitrum |
| inner encoding | Ethereum fields **re-encoded** as protobuf `TxData` | raw EIP-2718 envelope preserved in `raw`, deprecated `TxData` still declared |
| second signer | no | **yes** — EIP-712 fee payer |

The one-account-space difference is the most useful of these: the two chains look nearly
identical from outside, and every stranded-balance and identity-shift gotcha in the Sei
row is **absent** on Injective.

## Not established here

- **`tx_types."0x03"` (BlobTx)** — `unrecorded`. There is no accepted-type mask, so a
  blob transaction is decoded and passes `ValidateBasic`; whether it is refused
  downstream or executes with its blob fields dropped (as `0x04`'s authorizations
  demonstrably are) was not read, and none was submitted to mainnet.
- **EIP-7702 in practice.** The dropped-authorization finding is from source only. No
  `0x04` transaction was constructed against mainnet.
- **`GASLIMIT` inside a real transaction.** Measured as 0 under `eth_call`; the in-block
  value was not separately measured, only inferred from `BlockGasLimit`'s consensus-param
  read.
- **Live ed25519 accounts.** The code path is open; no census of ed25519 accounts on
  `injective-1` was taken, so the hazard is demonstrated as reachable, not as used.
- **`eips.2200` / `ExtraEIPs` on mainnet.** `DefaultExtraEIPs` is empty by design;
  whether live module params add any jump-table mutators is state that was not queried.
- **Auction and insurance-fund flows.** Recorded as `system_transactions` so the
  category is not understated, but not read in depth.
- **The `InjectiveLabs/go-ethereum v1.16.3-inj.2` fork is not cloned.** Every citation
  here is inside `injective-core`; what Injective changed inside its geth fork relative
  to upstream 1.16.3 is unmeasured.
- **State probes are not replayable at the pinned height.** The public sentry is not an
  archive node — it prunes within minutes, and a state query at `180071265` now returns
  "version does not exist". The block itself and the header fields remain readable. The
  Re-verify block below therefore re-derives a fresh height for state-dependent probes
  and pins only the block-level ones.

## Re-verify

```sh
# from the repo root
tools/clone.sh                                  # re-fetches every pinned clone
tools/.venv/bin/python tools/verify.py          # expect: pin ok, citations ok
                                                # "! NO EXTRACTOR" for injective is expected

I=chains/injective/repos/injective-core
R=https://sentry.evm-rpc.injective.network

# --- the repo moved orgs
curl -s -o /dev/null -w '%{http_code}\n' https://api.github.com/repos/InjectiveLabs/injective-core       # 404
curl -s -o /dev/null -w '%{http_code}\n' https://api.github.com/repos/InjectiveFoundation/injective-core # 200

# --- sync point: no dependency on cosmos/evm, own geth fork, no Osaka
git -C $I grep -c 'cosmos/evm' -- go.mod || echo 'not a dependency'
git -C $I grep -n 'go-ethereum =>' -- go.mod
git -C $I grep -rn 'OsakaTime' || echo 'NOT FOUND — Osaka is unrepresentable'

# --- chain id and fork level from source
git -C $I grep -n 'DefaultEIP155ChainID = 1776' -- injective-chain/modules/evm/types/chain_config.go

# --- THE headline: batch auction settles into bank balances the EVM reads
git -C $I grep -n 'shouldSendFundsToBank' -- injective-chain/modules/exchange/keeper/subaccount/keeper.go
git -C $I grep -n -A2 'func IsDefaultSubaccountID' -- injective-chain/modules/exchange/types/common_utils.go
git -C $I grep -n -A2 'func SubaccountIDToEthAddress' -- injective-chain/modules/exchange/types/common_utils.go
git -C $I grep -n -A3 'func (k \*Keeper) GetBalance' -- injective-chain/modules/evm/keeper/keeper.go
# -> SpendableCoin: also why a vesting unlock changes address.balance with no tx

# --- no gas refunds
git -C $I grep -n -B2 -A2 'DISABLED: due to DoS attack' -- injective-chain/modules/evm/keeper/gas.go

# --- 7702 authorizations are dropped
git -C $I grep -n -A16 'func (msg \*MsgEthereumTx) AsMessage' -- injective-chain/modules/evm/types/msg.go
git -C $I grep -n 'msg.SetCodeAuthorizations' -- injective-chain/modules/evm/keeper/gas.go
git -C $I grep -n 'tx.SetCodeAuthorizations()' -- injective-chain/modules/evm/keeper/utils.go

# --- precompile addresses 0x64-0x67
git -C $I grep -rn 'BytesToAddress(\[\]byte{10' -- injective-chain/modules/evm/precompiles/
git -C $I grep -n 'oracleContractAddress' -- injective-chain/modules/evm/precompiles/oracle/oracle.go
git -C $I grep -n -A4 'case MintMethodName, BurnMethodName' -- injective-chain/modules/evm/precompiles/bank/bank.go
git -C $I grep -n 'authzKeeper.DispatchActions' -- injective-chain/modules/evm/precompiles/exchange/exchange.go

# --- ed25519 is ACCEPTED (contrast cosmos-evm and sei, which refuse it)
git -C $I grep -n -A3 'case \*ed25519.PubKey' -- injective-chain/app/ante/ante.go
# --- an env var replaces BOTH signature decorators with a no-op
git -C $I grep -n -A6 'DEVNET_NO_SIGNATURE_VERIFICATION' -- injective-chain/app/ante/ante.go
# --- EIP-712 accepts Ethereum mainnet's chain id, and carries a fee payer
git -C $I grep -n 'TypedDataChainID == 1 ' -- injective-chain/app/ante/eip712.go
git -C $I grep -n 'eip712SigVerificationDecorator' -- injective-chain/app/ante/ante.go

# --- BASEFEE/PREVRANDAO/BLOBBASEFEE are hard-coded; receiptsRoot is a constant
git -C $I grep -n -A6 'blockCtx := vm.BlockContext' -- injective-chain/modules/evm/keeper/state_transition.go
git -C $I grep -n 'Random:      &zero' -- injective-chain/modules/evm/keeper/config.go
git -C $I grep -n 'NoBaseFee: true' -- injective-chain/modules/evm/keeper/config.go
git -C $I grep -n '"receiptsRoot":' -- injective-chain/modules/evm/rpc/types/utils.go
git -C $I grep -n 'if len(header.DataHash) == 0' -- injective-chain/modules/evm/rpc/types/utils.go

# --- LIVE. Block-level facts, pinned at 180071265 (0xabbab61) and at 0xabbaa3e.
curl -s -X POST $R -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["0xabbab61",true]}' \
  | python3 -c 'import json,sys; b=json.load(sys.stdin)["result"]; print("ntx",len(b["transactions"]),"gasUsed",b["gasUsed"],"baseFeePerGas",b["baseFeePerGas"],"gasLimit",b["gasLimit"]); print("keys",len(b))'
# -> ntx 0  gasUsed 0xac4551  baseFeePerGas 0x9896800  gasLimit 0x8f0d180  keys 21

curl -s -X POST $R -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["0xabbaa3e",true]}' \
  | python3 -c 'import json,sys; b=json.load(sys.stdin)["result"]; print("ntx",len(b["transactions"])); print("receiptsRoot",b["receiptsRoot"]); print("transactionsRoot",b["transactionsRoot"])'
# -> ntx 1; receiptsRoot 0x56e81f17...b421 (the EMPTY trie root, with a real receipt in the block)

# --- LIVE state probes. The sentry PRUNES: re-derive a fresh height rather than
#     replaying 180071265, which now returns "version does not exist".
H=$(curl -s -X POST $R -H 'content-type: application/json' \
      -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' \
    | python3 -c 'import json,sys; print(hex(int(json.load(sys.stdin)["result"],16)-3))')
echo "probing at $H"

# P256VERIFY is absent — geth's own VALID vector, with a sha256 control
V=0x4cee90eb86eaa050036147a12d49004b6b9c72bd725d39d4785011fe190f0b4da73bd4903f0ce3b639bbbf6e8e80d16931ff4bcf5993d58468e8fb19086e8cac36dbcd03009df8c59286b162af3bd7fcc0450c9aa81be5d10d312af6c66b1d604aebd3099c618202fcfe16ae7770b0c49ab5eadf74b754204a3bb6060e44eff37618b065f9832de4ca6ca971a7a1adc826d0f7c00181a5fb2ddf79ae00b4e10e
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"$V\"},\"$H\"]}"
# -> {"result":"0x"}   INVALID-looking output for a VALID signature
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000002\",\"data\":\"0x\"},\"$H\"]}"
# -> 0xe3b0c442...b855   control: precompiles work

# the four precompiles are native (no code stub) and ABI-dispatched
for A in 0064 0065 0066 0067 0068 0100 0800 0803; do
  printf '%s ' $A
  curl -s -X POST $R -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x00000000000000000000000000000000000$A\",\"$H\"]}"
  echo
done
# -> all 0x  (native, or empty — the source map distinguishes them)
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000064\",\"data\":\"0xdeadbeef\"},\"$H\"]}"
# -> revert "no method with id: 0xdeadbeef"  (0x64 is live and ABI-dispatched)
curl -s -X POST $R -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000803\",\"data\":\"0xdeadbeef\"},\"$H\"]}"
# -> {"result":"0x"}  empty account: Injective does NOT inherit cosmos-evm's 0x803 panic

# opcode values, via state-override bytecode  <OP> PUSH0 MSTORE PUSH1 20 PUSH0 RETURN
for OP in 48:BASEFEE 44:PREVRANDAO 4a:BLOBBASEFEE 45:GASLIMIT 46:CHAINID; do
  printf '%s ' ${OP#*:}
  curl -s -X POST $R -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x00000000000000000000000000000000000000ff\",\"data\":\"0x\"},\"$H\",{\"0x00000000000000000000000000000000000000ff\":{\"code\":\"0x${OP%%:*}5f5260205ff3\"}}]}"
  echo
done
# -> BASEFEE 0, PREVRANDAO 0, BLOBBASEFEE 0, GASLIMIT 0, CHAINID 0x6f0
#    while the same block's header reports baseFeePerGas 0x9896800 and gasLimit 0x8f0d180

# gasUsed counts Cosmos gas: most blocks have no EVM transactions at all
python3 - "$R" <<'PY'
import json,sys,urllib.request
from collections import Counter
R=sys.argv[1]
def call(p):
    return json.load(urllib.request.urlopen(urllib.request.Request(
        R,data=json.dumps(p).encode(),headers={'content-type':'application/json'}),timeout=40))
bn=int(call({"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]})["result"],16)-3
res=call([{"jsonrpc":"2.0","id":i,"method":"eth_getBlockByNumber","params":[hex(bn-i),True]} for i in range(60)])
c=Counter(); empty=0
for r in res:
    b=r["result"]; c.update(t["type"] for t in b["transactions"])
    if not b["transactions"] and int(b["gasUsed"],16)>0: empty+=1
print("tx types over 60 blocks:", dict(c), "| blocks with 0 tx and non-zero gasUsed:", empty, "/60")
PY
# -> e.g. {'0x2': 4, '0x0': 1} | 54/60
```
