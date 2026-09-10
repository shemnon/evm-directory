# ZK Stack (ZKsync Elastic Network) — findings

`role: template`, no chain ID. Evidence is the `zksync-era` row's clones —
`matter-labs/zksync-era` **core-v31.5.0** @ `fa3a9b94`, plus `era-contracts` and
`zksync-protocol` — declared with `client.shared_with`, which is the assertion this
row makes. Live probes on four mainnets at heads **71907999** (Era), **83125910**
(Abstract), **29664665** (Sophon), **6248281** (Lens).

---

## 1. The framework claim was tested, and it passed — harder than any other row's

CANDIDATES.md is explicit that a framework row must not be written on reputation:
three of eight proposed rows turned out not to be frameworks, because the code was
forked per chain (Frontier, BeaconKit) or the family had split across incompatible
stacks (Polygon CDK). The test applied here was to ask each network what it is
running.

`zks_getProtocolVersion` on all four:

```
bootloader     0x01000911c4db4fe62c98e180cfa7e9b3a22fb15f505905d4bf36192f481551e6
default_aa     0x010005f73e7c299ed73db937843643bdc276cbc2cc8596287e1e0cf3afc60252
evm_emulator   0x01000d8bae37b82f311186426184866498b357f41d7a02ced11f3e3fbfbacd63
minorVersion   30
```

Byte-identical on ZKsync Era, Abstract, Sophon and Lens. And
`zks_getBridgehubContract` returns `0x303a465b659cbb0ab36ee643ea362c509eeb5213` on
L1 chain 1 for all four.

That is a stronger shared-code claim than any other framework row here can make. OP
Stack descendants share a *client* and run different builds of it — Base reimplements
the EVM layer in Rust, opBNB is frozen three fork-generations back, Celo carries its
own transaction type. These four are executing **the same bytecode**, and the protocol
version is the thing that says so.

## 2. …and it did not always hold, so the claim carries a date

At L1 batch 1 the four chains had three different base-system-contract hash sets:

| chain | bootloader @ batch 1 |
|---|---|
| Era | `0x0100038581be3d0e…` |
| Abstract, Sophon | `0x010008e742608b21…` |
| Lens | `0x010008e15394cd83…` |

They converged onto version 30 afterwards. A ZK Chain can lag a protocol version, so
"shares the pinned code" is a claim with a date on it — the same discipline Scroll's
row forced for prover restrictions, arrived at from the opposite direction.

## 3. Why `template` and not `stack`

SCHEMA.md separates the two on whether a descendant can be fully described by pointing
at the ancestor. Here it cannot, and the reason is not precompiles — it is money.

| | Era | Abstract | Sophon | Lens |
|---|---|---|---|---|
| chain id | 324 | 2741 | 50104 | 232 |
| base token (L1) | ETH `0x…0001` | ETH `0x…0001` | **SOPH** `0x6b7774cb…` | **GHO** `0x1ff1dc3c…` |
| `minimal_l2_gas_price` | 45,250,000 | 45,250,000 | 45,250,000 | **36,948,438** |
| `max_pubdata_per_batch` | 500,000 | 700,000 | 1,000,000 | 1,000,000 |
| compute / pubdata overhead | 0 / 1 | 0 / 1 | 0.99 / 0.01 | 0.001 / 0.001 |
| base-token conversion ratio | 1/1 | 1/1 | 4,000,000/7 | 75/1 |

On two of the four, `msg.value` and `balance` are **not denominated in ETH**. Contract
code that assumes an 18-decimal ETH native asset is correct on Era and Abstract and
wrong on Sophon and Lens — from identical bytecode. And the same call costs different
gas on each, because the fee parameters are per deployment.

Abstract is the closest thing to a pure instantiation in this dataset: identical to
Era on every probed axis except `max_pubdata_per_batch`.

## 4. What this row deliberately does not say

Every EVM-visible fact — the tombstoned kernel address space below 2^16, the
`0x8000`–`0x8012` system contracts, transaction type `0x71`, native account
abstraction, the EVM emulator, the 32-byte modexp operand cap, `CREATE` address
derivation — is on `chains/zksync-era/` and is **not restated here**. Duplicating it
would violate the delta convention the dataset is built on, and would create two
places for the same fact to go stale.

The row therefore has an almost empty `precompiles` section, and that emptiness is the
finding: unlike `avalanche-subnet` and `cosmos-evm`, where the whole point of the
template row is that precompiles are opt-in per deployment, **a ZK Chain does not get
to choose**. The set is fixed by the protocol version's system-contract hashes. Only
`0x8010` (KECCAK256) and `0x8012` (CodeOracle) are restated, and only to record that
they are framework-wide rather than Era-specific.

The one address that genuinely is per chain lives on L1, not in this address space:
the diamond proxy — `0x32400084…` (Era), `0x2edc71e9…` (Abstract), `0x05ede6ad…`
(Sophon), `0xc29d04a9…` (Lens).

## 5. Consequence for the backlog

Tier 3 of CANDIDATES.md said "ZK Stack chains (Abstract, Sophon, Lens) likewise belong
under the zkSync row". That is now measured rather than assumed, and it is slightly
sharper than the original claim: they belong under **this** row, whose content is the
proof of sharing plus the per-deployment configuration, while the EVM facts stay on
`zksync-era`. Promote one of them to its own row only if it ships a protocol version
the others do not have — which `zks_getProtocolVersion` will show in one call.

---

## Re-verify

```bash
# All four networks, one command each. The framework claim IS these outputs.
for u in https://mainnet.era.zksync.io https://api.mainnet.abs.xyz \
         https://rpc.sophon.xyz https://rpc.lens.xyz; do
  echo "=== $u"
  for m in eth_chainId eth_blockNumber zks_L1ChainId zks_getBridgehubContract \
           zks_getMainContract zks_getBaseTokenL1Address; do
    printf '  %-26s ' $m
    curl -s -X POST $u -H 'content-type: application/json' \
      -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$m\",\"params\":[]}"
    echo
  done
  printf '  %-26s ' zks_getProtocolVersion
  curl -s -X POST $u -H 'content-type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"zks_getProtocolVersion","params":[]}' \
    | python3 -c 'import sys,json;r=json.load(sys.stdin)["result"];print(r["minorVersion"], r["base_system_contracts"])'
  printf '  %-26s ' zks_getFeeParams
  curl -s -X POST $u -H 'content-type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"zks_getFeeParams","params":[]}' \
    | python3 -c 'import sys,json;c=json.load(sys.stdin)["result"]["V2"];print(c["config"], c["conversion_ratio"])'
done

# F2: they did NOT always match — batch 1 on each
for u in https://mainnet.era.zksync.io https://api.mainnet.abs.xyz \
         https://rpc.sophon.xyz https://rpc.lens.xyz; do
  curl -s -X POST $u -H 'content-type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"zks_getL1BatchDetails","params":[1]}' \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["baseSystemContractsHashes"])'
done

# F4: the two restated precompiles are in the shared contracts clone
ls chains/zksync-era/repos/era-contracts/system-contracts/contracts/precompiles/

# the row shares zksync-era's clones by declaration — clone.sh skips it on purpose
grep -n 'shared_with' chains/zk-stack/chain.yaml
tools/clone.sh zk-stack        # prints nothing: nothing to clone

# row check (runs zksync-era's extractor against the shared clone)
tools/.venv/bin/python tools/verify.py zk-stack zksync-era
```
