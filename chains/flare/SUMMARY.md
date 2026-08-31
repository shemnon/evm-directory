# Flare

**Role:** `fork` · **Upstream:** `ethereum` (via avalanchego + coreth) · **Chain ID:** 14 ·
**Baseline:** Cancun
**Client:** [`flare-foundation/go-flare`](https://github.com/flare-foundation/go-flare) `v1.14.0`
(`1f9983a2f83a8469314817b456d8b279861dbad8`) — a monorepo fork of *both*
avalanchego `v1.14.0` and coreth `v0.16.0-rc.0`
**Live probes:** `https://flare-api.flare.network/ext/C/rpc` @ block `68124744`

Everything [`chains/avalanche-c/`](../avalanche-c/chain.yaml) establishes about coreth
v0.16.0 is true here. This file states only what is Flare's own — plus the handful of
places where measuring Flare turned up something the ancestor's row records wrongly.
(`avalanche-c` has `role: fork`, not `stack`, so `tools/model.py` does not resolve
inheritance across it; the shared entries are restated in `chain.yaml` out of necessity
and marked as coreth's.)

## 1. The prediction was wrong, and the way it was wrong is the finding

`CANDIDATES.md` promoted Flare on the expectation of *"FTSO and State Connector
**precompiles** at addresses like `0x1000…0002` — far outside the mainnet or `0x0100`
ranges."*

**Flare adds zero precompile addresses.** Its precompile map is coreth's, unmodified:
`coreth/params/hooks_libevm.go:PrecompiledContractsGranite` is three tombstoned
native-asset stubs plus `P256VerifyAddress`. There is no Flare entry in it.

The `0x1000…` addresses are real, and they are **system contracts** — Solidity written
into the C-Chain genesis allocation, with 2.1 KB–13.6 KB of runtime bytecode each.
`eth_getCode` at block 68124744:

| address | `eth_getCode` | identified by | what the client does with it |
|---|---|---|---|
| `0x1000…0001` | 2196 bytes | `submitAttestation`, `getAttestation` | State Connector — hook, now off |
| `0x1000…0002` | 13627 bytes | `trigger()`, `daemonize()` | **FlareDaemon** — called after every tx |
| `0x1000…0003` | 9742 bytes | `getFtsoManager()` | PriceSubmitter — prioritised fee path |
| `0x1000…0004` | 5048 bytes | `pullFunds`, `lastPullTs` | DistributionTreasury — swept by client |
| `0x1000…0005` | 4284 bytes | `incentivePool()` | IncentivePoolTreasury — 17.48 bn FLR |
| `0x1000…0006` | 6855 bytes | *(named in client)* | InitialAirdrop — swept by client |
| `0x1000…0007` | 2533 bytes | `setGovernanceAddress`, `setTimelock` | GovernanceSettings — re-executed by client |

Identity was **not** taken from documentation. Each name was confirmed by computing the
4-byte selector of a distinguishing signature and finding it in the deployed bytecode.

So Flare is not a second Hyperliquid-style break in precompile enumeration. It is the
opposite shape of surprise: **a chain that puts protocol machinery at fixed addresses
without making any of it a precompile**, and instead reaches consensus through
**state-transition hooks on ordinary contract calls**. `coreth/core/` gains four files
that do not exist upstream — `daemon.go`, `state_connector.go`, `governance_settings.go`,
`state_transition_params.go` — and all of Flare's divergence is in them.

An address-diff survey reports Flare as pure coreth and is right about the addresses and
wrong about the chain.

## 2. Receipts overstate the fee by 657× on 86% of transactions

This is the row's severity-`high` finding and it is live-measured, not inferred.

`IsPrioritisedContractCall` (`coreth/core/daemon.go`) marks a transaction *prioritised*
when it targets `0x1000…0003` or the hardcoded Submitter contract
`0x2cA6571Daa15ce734Bbd0Bf27D5C9D16787fc33f`, carries one of a fixed list of 4-byte
selectors, is ≤ 4500 bytes of calldata, has a gas limit ≤ 3,000,000, and returned a
non-zero word. For such a transaction `TransitionDb` **discards the metered fee**:

```
nominalFee = 21000 * 25 gwei
if actualFee > nominalFee:  refund (actualFee - nominalFee) to msg.From ; burn nominalFee
```

`gasUsed` and `effectiveGasPrice` in the receipt are never touched. They describe the
charge that did not happen.

Measured at block 68124744, transaction `0x5dbbbce3…9446d`:

| | |
|---|---|
| receipt `gasUsed` × `effectiveGasPrice` | 212362 × 1625 gwei = **0.34508825 FLR** |
| sender balance delta across the block | **0.000525 FLR** = exactly 21000 × 25 gwei |
| receipt `status` | `0x1` |

**657×**, silently. Block-wide the same gap holds: receipts imply 1.31034165 FLR of fees;
the burn address received 0.05638215 FLR.

And this is the *majority* path. A 40-block census (68124704–68124744) found **248 of 290
transactions (86%)** going to the Submitter contract, every one with selector `0x833bf6c0`
— which is in `submitterDataPrefixes`. Like Celo's `0x7b`, the exotic case *is* the
traffic.

Two consequences the dataset has not recorded before:

- Every fee/revenue/MEV figure computed from Flare receipts is wrong by two to three
  orders of magnitude, with no error to catch.
- **The block producer receives nothing at all.** `stateTransitionParamsFlare` returns
  `0x…dEaD` as the fee sink, so base fee *and* priority fee are burned. `miner` is the
  blackhole `0x0100…0000` in every header and its balance did not move across the probed
  block. Flare's validator economics are not fee-based, and OP-style "sequencer revenue"
  tooling reads zero.

## 3. A system call runs after every transaction, and it can mint

`atomicDaemonAndMint(st, log)` fires at the end of `TransitionDb` for every transaction
that did not throw a VM error — *after* the fee has been settled, *outside* the user's
call frame:

- calls `trigger()` (`0x7fec8d38`) on `0x1000…0002`,
- with a gas budget of **100 × the block gas limit**, charged to nobody,
- treats the returned 32-byte word as a **mint request** and credits it to that
  contract's balance with a raw `AddBalance`, capped at **60,000,000 FLR** per
  invocation,
- reverts only the daemon's own state on a rejected mint, and on a daemon *error* merely
  logs it — the user's transaction still succeeds.

This is the funding mechanism for FTSO rewards and inflation. It is the second mechanism
in this dataset that increases native supply outside block rewards (after subnet-evm's
`ContractNativeMinter`), and unlike that one it is unconditional and needs no allowlist.

Its side effects land inside somebody else's receipt. The receipt for
`0xf9a1072e…a39c` — a submission sent to `0x2cA6…c33f` — carries **six logs emitted by
`0x1000…0002`** that the transaction's own call tree never produced.

## 4. The client makes EVM calls as addresses with no private key

Four client paths execute EVM calls whose `msg.sender` is a synthesised address, chosen
because the target Solidity contract authorises on `msg.sender == SIGNAL` **and** on
`block.coinbase == SIGNAL`. The client temporarily rewrites `block.coinbase` to match:

| signal address | used for |
|---|---|
| `0x…000DEaD1` | State Connector round finalisation |
| `0x…000DEaD0` | `setGovernanceAddress` / `setTimelock` |
| `0x…000dead2` | InitialAirdrop address migration |
| `0x…000deAD3` | Distribution address migration |

`core/state_connector.go` states the security model in a comment: to subvert it one would
have to *"know the private key to the address `0x…DEaD1`"*. Authorisation by an address
that provably has no signer.

Two knock-on facts:

- **`block.coinbase` is not stable inside a transaction on Flare.** It is saved,
  overwritten and restored around these calls.
- The last two paths **move an entire treasury balance** with a `SubBalance`/`AddBalance`
  pair in Go — a value transfer with no transaction, no trace frame, and no log.

Recorded under `system_transactions`, and named in `tx_authorization.note`, because "what
can sign a transaction" and "what can cause a state change" come apart here in a way the
scheme table cannot express.

The State Connector hook itself is now **dead code on Flare**: the gate reads
`!isDurango && …`, and Durango activated 2025-08-05. It ran for three years. While live,
a node operator could set `SC_LOCAL_ATTESTATORS` and `SC_FORKING_ENABLED=1` to make the
node **halt when its local attestors disagreed with the hardcoded default set** — a
deliberate, configurable consensus split shipped in the client.

## 5. `0x0100` — Flare is the control case

Three chains now fail the `0x0100` test in three ways (Hyperliquid empty, Sei relocated to
`0x1011`, Sonic). Flare passes it cleanly, and the check was done properly — a **valid**
P-256 signature plus a **corrupted-`r`** control on otherwise identical calldata, because
EIP-7951 signals *invalid* with empty output, byte-identical to a missing precompile:

| probe @ 68124744 | result |
|---|---|
| valid signature | `0x…0001` |
| same input, `r ^ 1` | `0x` |
| gas floor (binary search) | **6900** — exactly EIP-7951 |
| `eth_getCode` | `0x` |

Better still, the fork gate is verifiable to the block. Binary search on header timestamps
puts the Granite boundary at **block 65060228, timestamp 1784030400** — the exact value in
`avalanchego/upgrade/upgrade.go:Flare`. `eth_call` to `0x0100` returns `0x` at 65060227 and
the correct answer at 65060228.

The usual Avalanche caveat still bites: Flare has `0x0100` and **no** BLS12-381 at
`0x0b`–`0x11`, because P256VERIFY arrived through Granite rather than Osaka. Fork-level
inference from precompile presence fails here in both directions.

## 6. Two corrections to how the dataset describes precompiles

**(a) `eth_getCode == 0x` is not a sound test for precompile-ness on Avalanche-lineage
chains.** `eth_getCode` at the Warp precompile `0x0200…0005` returns **`0x01`**.
`core/state_processor_ext.go:ApplyPrecompileActivations` deliberately writes `nonce = 1`
and `code = 0x01` when a stateful precompile activates, so that Solidity's `extcodesize`
guard lets contracts call it. It is still a precompile — native Go, no dispatcher, no ABI —
but it has bytecode in state and a non-zero `EXTCODESIZE`. SCHEMA.md's boundary
("precompile — native code at an address, **no bytecode in state, no `EXTCODESIZE`**")
does not have a slot for this. The one-byte marker is a third thing, and it applies to
every coreth/subnet-evm stateful precompile, not just Flare's.

**(b) A stateful precompile is live on Flare, and it is Warp — not an oracle.** The brief
asked whether Flare has a precompile a contract can `STATICCALL` for a changing answer.
The FTSO does not qualify: it is a contract. Warp does — its answers come from block
predicate results computed outside EVM execution — and it is **enabled on Flare mainnet**,
verified rather than assumed: `getBlockchainID()` returns
`0x77d3074dc510f43b09ac5be77edee276ef3b55f0097d504846aa8eec613fc625`.

## 7. Same client, a year behind

Flare runs the current coreth generation and reaches every Avalanche upgrade about a year
late. `avalanchego/upgrade/upgrade.go` puts a `Flare` config literal directly beside
`Mainnet`, so the two schedules are diffable in one file:

| fork | Avalanche | Flare | lag |
|---|---|---|---|
| Banff | 2022-10-18 | 2024-12-17 | 26 months |
| Cortina | 2023-04-25 | 2025-05-13 | 25 months |
| Durango (= Shanghai) | 2024-03-06 | 2025-08-05 | 17 months |
| Etna (= Cancun) | 2024-12-16 | 2025-12-02 | 11.5 months |
| Fortuna | 2025-04-08 | 2026-04-14 | 12 months |
| Granite | 2025-11-19 | 2026-07-14 | 8 months |

The gap is closing, but the point stands: **"runs current coreth" does not mean "allows
what current coreth allows."** `sync_point` in the schema was designed for a descendant
pinned to an *older client*; Flare is a descendant pinned to an older *clock*, with the
same code. Both baselines land on Cancun — no Prague, no Osaka, no EIP-7702, no `0x04`.

Flare also carries a fork field of its own in coreth's `NetworkUpgrades`,
`songbirdTransitionTimestamp`, which chain 14 never sets — it gates the Songbird/Coston
networks' migration onto this codebase. Recorded as `status: skipped`.

## Contradicts an existing row

`chains/avalanche-c/chain.yaml` records `header_fields.added: []`. Live probing block
68124744 on Flare — running the same coreth — returns `extDataHash`, `extDataGasUsed`,
`blockGasCost`, `blockExtraData`, `minDelayExcess` and `timestampMilliseconds` alongside
the Cancun fields, and `coreth/plugin/evm/customtypes/header_ext.go:HeaderExtra` shows
they are RLP-appended to the Ethereum header and therefore inside the block hash. Flare's
row records them as `added` with a note; the ancestor's `[]` looks like a gap rather than
a Flare difference, and belongs to whoever owns that row.

Two softer notes for the integrator:

- `avalanche-c` marks `0x0100` as `modified`. This row measures the same code path and
  finds the semantics and gas **identical to mainnet** (6900, valid → 1, invalid → empty).
  `modified` is still defensible because the fork gate differs, but the note should not be
  read as "the answer differs."
- Two places in the repo already cite "Flare `0x1000...0002`" as an example of custom
  **precompile** placement — `chains/celo/SUMMARY.md` (fourth finding) and the generated
  `PRECOMPILES.md` note that derives from it. That address is a system contract with
  13627 bytes of code. The sentence needs a different example or a different word; the
  point it is making (Celo parked a precompile three addresses below `0x0100`) survives
  either way, since Tron `0x1000001+` and Monad `0x1000` still carry it.

## Not established here

- **`debug_*` is not exposed on the public endpoint.** The claim that the daemon call is
  invisible to tracers is therefore *unverified*; only the receipt observation (logs from
  `0x1000…0002` attributed to a user transaction) is live evidence. Recorded as such.
- **The FTSO's own read path** (`FtsoV2.getFeedById` and friends) was not probed. Nothing
  in the client references it, so it has no bearing on the consensus claims — but "the
  oracle answer is a plain contract read" rests on `eth_getCode`, not on a value read.
- **Flare's FIP series** was not read; FTSO/FDC protocol versions are governed by on-chain
  contract upgrades, not client releases, so nothing in this clone records them.
  `non_eip_specs` says so rather than guessing an adoption state.
- **The `0x1000…0004` / `0x1000…0006` sweeps** are recorded from source; neither was
  observed firing on-chain (both are one-shot migrations from 2022–2023).
- **`songbird_transition`** is recorded as `skipped` for chain 14 from the absence of a
  timestamp in `upgrade.Flare`; Songbird itself (chain 19) is a separate row nobody has
  written.
- **No extractor** exists for this row, so `verify.py` takes the precompile list on trust.
  It is a nine-entry list copied from one `map` literal, which is the cheapest kind to
  extract if someone wants to.

## Re-verify

```sh
# from the repo root
tools/clone.sh                                 # re-fetches every pinned clone
tools/.venv/bin/python tools/verify.py         # expect: flare pin ok, citations ok, exit 0
                                               # "! NO EXTRACTOR" for flare is expected

C=chains/flare/repos/go-flare

# --- 1. the precompile map is coreth's, and has no Flare entry
git -C $C grep -n 'PrecompiledContractsGranite' -- coreth/params/hooks_libevm.go
git -C $C grep -rn '0x1000000000000000000000000000000000000' -- coreth/params/ ; echo "grep exit=$? (1 == no 0x1000.. address anywhere in the precompile config)"

# --- the 0x1000.. addresses have real bytecode (system contracts, not precompiles)
for a in 1 2 3 4 5 6 7; do
  printf '0x100000000000000000000000000000000000000%s ' $a
  curl -s -X POST https://flare-api.flare.network/ext/C/rpc -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"0x100000000000000000000000000000000000000$a\",\"0x40f8048\"]}" \
    | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print("bytes:",(len(r)-2)//2)'
done
# -> 2196 13627 9742 5048 4284 6855 2533   (none is "0")

# identity, by selector rather than by documentation
cast sig 'trigger()'                   # 0x7fec8d38 -> present in 0x1000..0002 (the selector the client calls)
cast sig 'incentivePool()'             # -> present in 0x1000..0005
cast sig 'setGovernanceAddress(address)'  # -> present in 0x1000..0007

# --- 2. the fee override: receipt vs reality
curl -s -X POST https://flare-api.flare.network/ext/C/rpc -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getTransactionReceipt","params":["0x5dbbbce34e3cdf774908dd2931f596cb3eabc6bceba7f6f3dd715a6a10e9446d"]}' \
  | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print("implied fee", int(r["gasUsed"],16)*int(r["effectiveGasPrice"],16)/1e18, "FLR")'
# -> implied fee 0.34508825 FLR
# sender 0x5dbbbce3..'s balance across 68124743 -> 68124744 falls by 0.000525 FLR
#   ( = 21000 * 25 gwei, the nominal fee ) — 657x less than the receipt says
git -C $C grep -n 'nominalFee' -- coreth/core/state_transition.go
git -C $C grep -n 'func IsPrioritisedContractCall' -- coreth/core/daemon.go

# 86% of traffic takes that path
python3 - <<'PY'
import json,urllib.request,collections
R="https://flare-api.flare.network/ext/C/rpc"
def rpc(m,p):
    q=urllib.request.Request(R,json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"content-type":"application/json"})
    return json.load(urllib.request.urlopen(q))["result"]
c=collections.Counter()
for n in range(0x40f8048-40, 0x40f8048):
    for t in rpc("eth_getBlockByNumber",[hex(n),True])["transactions"]:
        c[(t["to"] or "CREATE").lower()]+=1
print(c.most_common(3), "of", sum(c.values()))
PY
# -> 0x2ca6571daa15ce734bbd0bf27d5c9d16787fc33f: 248 of 290

# --- 3. the daemon runs after every transaction and can mint
git -C $C grep -n 'atomicDaemonAndMint' -- coreth/core/state_transition.go coreth/core/daemon.go
git -C $C grep -n 'GetMaximumMintRequest\|GetDaemonGasMultiplier\|AddBalance' -- coreth/core/daemon.go
# a user tx to 0x2cA6..c33f whose receipt carries 6 logs from 0x1000..0002:
curl -s -X POST https://flare-api.flare.network/ext/C/rpc -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getTransactionReceipt","params":["0xf9a1072e659b67ea1768a25f628b8c0776f70bb93f83b3eada23a2977c9aa39c"]}' \
  | python3 -c 'import json,sys,collections; r=json.load(sys.stdin)["result"]; print("to",r["to"]); print(collections.Counter(l["address"] for l in r["logs"]))'

# --- 4. calls from keyless addresses, and the coinbase rewrite
git -C $C grep -n 'DEaD1\|DEaD0\|dead2\|deAD3' -- coreth/core/state_connector.go coreth/core/governance_settings.go
git -C $C grep -n 'Context.Coinbase = coinbaseSignal' -- coreth/core/state_connector.go coreth/core/governance_settings.go
git -C $C grep -n 'return !isDurango' -- coreth/core/state_connector.go   # the hook is off since Durango

# --- 5. 0x0100 is the real P256VERIFY, and Granite is the gate
V=0x4cee90eb86eaa050036147a12d49004b6b9c72bd725d39d4785011fe190f0b4d61340c88c3aaebeb4f6d667f672ca9759a6ccaa9fa8811313039ee4a35471d325bea3d29d6f788eca19bf7488f8972be048acbcb4f2eae52575d1e02a08a16c760fed4ba255a9d31c961eb74c6356d68c049b8923b61fa6ce669622e60f29fb67903fe1008b8bc99a41ae9e95628bc64f2f1b20c2d7e9f5177a3c294d4462299
# valid -> 1 ; corrupted r (…1d33) -> empty ; pre-Granite block -> empty
for spec in "$V 0x40f8048" "${V/471d32/471d33} 0x40f8048" "$V 0x3e0bd83" "$V 0x3e0bd84"; do
  set -- $spec
  curl -s -X POST https://flare-api.flare.network/ext/C/rpc -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_call\",\"params\":[{\"to\":\"0x0000000000000000000000000000000000000100\",\"data\":\"$1\"},\"$2\"]}"; echo
done
# -> 0x..01 | 0x | 0x (block 65060227, pre-Granite) | 0x..01 (block 65060228)
git -C $C grep -n 'GraniteTime:' -- avalanchego/upgrade/upgrade.go   # Flare: 2026-07-14 12:00 UTC = 1784030400

# --- 6. the Warp precompile has one byte of code, on purpose
curl -s -X POST https://flare-api.flare.network/ext/C/rpc -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getCode","params":["0x0200000000000000000000000000000000000005","0x40f8048"]}'
# -> {"result":"0x01"}
git -C $C grep -n 'SetCode(module.Address' -- coreth/core/state_processor_ext.go

# --- 7. the fork clock, Flare beside Avalanche in one file
git -C $C grep -n -A16 '^\tFlare = Config{' -- avalanchego/upgrade/upgrade.go
git -C $C grep -n 'ShanghaiTime = utils.NewUint64\|CancunTime = utils.NewUint64\|PragueTime\|OsakaTime' -- coreth/params/config_extra.go
# -> Shanghai=durango, Cancun=etna, and no Prague/Osaka assignment anywhere
```
