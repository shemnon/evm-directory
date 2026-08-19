# OP Stack — shared lineage node (not a chain)

**role: `stack` · no chain ID · upstream: go-ethereum**

Reference: [op-geth `v1.101702.2`](https://github.com/ethereum-optimism/op-geth) @ `e8800cff`.
Optimism, Base, World Chain and Zora inherit everything below; their own files carry
only what they add on top.

## Headline: zero custom precompile addresses, six divergent precompiles

The address list is identical to mainnet. Enumerate `0x01`–`0x11` plus `0x0100` and
you get a perfect match, which is exactly what "EVM equivalent" marketing rests on.
But **six of those addresses behave differently**:

| Addr | Name | Divergence |
|---|---|---|
| `0x05` | MODEXP | no EIP-7823 bounds, no EIP-7883 repricing — **cheaper and more permissive** than mainnet Osaka |
| `0x08` | BN256_PAIRING | input capped at 81,984 B / 427 pairs (mainnet: **uncapped**) |
| `0x0c` | BLS12_G1MSM | capped 288,960 B / 1,806 pairs (mainnet: uncapped) |
| `0x0e` | BLS12_G2MSM | capped 278,784 B / 968 pairs (mainnet: uncapped) |
| `0x0f` | BLS12_PAIRING | capped 156,672 B / 408 pairs (mainnet: uncapped) |
| `0x0100` | P256VERIFY | **3450 gas vs mainnet's 6900** |

The caps exist so accelerated precompiles stay under the fault-proof VM's 16M gas
ceiling (`params/protocol_params.go:190`). They are a proving-system constraint that
leaks into consensus: a contract pairing 500 BN254 points succeeds on mainnet and
reverts with `errBadPairingInputSize` on every OP chain.

**Methodological consequence for this whole project:** a survey that diffs address
lists reports OP Stack as fully equivalent and is wrong on six counts. Semantic
divergence at a shared address is the hardest class to detect and the most likely to
be missed. Every chain in this dataset needs its precompile *implementations*
compared, not just its addresses.

## Osaka does not restore mainnet semantics

`activePrecompiledContracts` (`core/vm/contracts.go:304`) tests `IsOptimismJovian`
**before** `IsOsaka`. The OP branch shadows the Ethereum branch permanently, so an OP
chain that activates Osaka still gets Jovian's MODEXP and 3450-gas P256VERIFY. The
phrase "Osaka-equivalent" is therefore false for OP chains regardless of their
configured `OsakaTime` — a claim that would have been recorded as true if fork names
were taken at face value.

## The fork mapping is enforced, not conventional

`CheckConfigForkOrder` (`params/config.go:1687-1694`) **rejects at startup** any
config where:

- `ShanghaiTime != CanyonTime`
- `CancunTime != EcotoneTime`
- `PragueTime != IsthmusTime`

So Canyon≡Shanghai, Ecotone≡Cancun, Isthmus≡Prague are verified facts. Fjord,
Granite, Holocene, Jovian, Karst and Interop have **no** Ethereum counterpart — they
are pure OP upgrades, and Fjord/Granite/Jovian are where all six precompile
divergences were introduced.

## `0x7e` DepositTx — the tx type that mints

```
DepositTx{ SourceHash, From, To, Mint, Value, Gas, IsSystemTransaction, Data }
```

No nonce. No signature. No `gasPrice`/`gasTipCap`. Inserted by the derivation
pipeline from L1 events rather than submitted by users, and `Mint` **creates native
ETH from nothing** — the only transaction type in this dataset that increases supply.
Two common assumptions break: "every transaction has a recoverable sender signature"
and "native token supply changes only via block rewards."

## `blobGasUsed` means something else

From Jovian on, OP Stack stores the **DA footprint** in the `blobGasUsed` header
field (`core/types/block.go:24-26`). Same field name, same RLP position, same
`blobGasUsed` JSON key over RPC — different quantity. An indexer computing blob
economics across chains gets silent garbage instead of an error. This is the nastiest
divergence found so far, because there is no signal that anything is wrong.

Meanwhile EIP-4844 itself is `removed`: there is no user-facing BlobTx on L2. Blobs
are an L1 batcher mechanism. So the field survives its own feature's absence.

## Three fee components, not one

User cost = L2 1559 execution fee **+** L1 data fee **+** operator fee (Isthmus,
`scalar * gasUsed + constant`). The L1 data fee has had three successive formulas
(Bedrock → Ecotone → Fjord). `eth_estimateGas` models only the first component.

## Opcodes

No divergence. OP Stack's equivalence claim holds cleanly at the opcode layer; it
breaks at the precompile, fee and header layers instead.

## Scope limit

Only the six `0x42..` predeploys that op-geth itself references are recorded. The
full predeploy set (WETH9, L2StandardBridge, GasPriceOracle, L2CrossDomainMessenger,
…) lives in `ethereum-optimism/optimism`, which is not cloned here, and is marked
`out_of_tree` rather than filled in from memory.

## Transaction authorization: the sender that was never signed for

`tx_authorization:` asks what makes the protocol accept a transaction as authorized by
its sender. For OP Stack **user** transactions the answer is mainnet's, exactly:
`recoverPlain` is the only recovery routine in the tree, the address is still the hash
of the recovered key, and the single OP addition to the signer chain —
`NewIsthmusSigner` — differs from geth's Prague signer only by *removing* blob
transactions from the accepted set. It changes which envelopes may carry a signature,
never how one is checked. P256VERIFY at `0x0100` is a tool for contracts; a P-256 key
cannot move a wei here any more than on mainnet.

The delta is `0x7e`. A deposit is **authorized without a signature at all**:

- `rawSignatureValues()` returns `0, 0, 0`, and `sigHash()` **panics** with
  `"deposit cannot be signed"` — the type cannot acquire a signature even in principle.
- The signer short-circuits on the type byte *before any cryptography* and returns the
  envelope's own `From` field verbatim. The sender is **read out of the transaction**,
  not recovered from it — the one place where this row's `key_binding: derived` does
  not hold.
- The txpool rejects every deposit, with the client stating why in as many words: *"No
  unauthenticated deposits allowed in the transaction pool … the external engine-API
  user authenticates deposits."* A deposit can only arrive through the authenticated
  engine API.

So what authorizes it? Construction by the derivation pipeline. For *user* deposits the
chain is real but one layer down: `op-node` scans L1 receipts for the portal's
`TransactionDeposited` logs, and `OptimismPortal2.depositTransaction` sets
`from = msg.sender`, aliased by `applyL1ToL2Alias` when the L1 caller is a contract — so
an L1 secp256k1 signature is ultimately behind it. But the pipeline also **synthesizes
deposits with no L1 event behind them at all**: the L1-attributes transaction from
`0xdead…0001`, and the network-upgrade transactions from `0x4210…0000` and from the
**zero address**. Nobody holds a key for those senders. They are authorized by protocol
construction and by nothing else.

Modelled as a scheme-like entry `unsigned` with `signers_per_tx: 0` on that path. It
carries `authorizes: protocol` + `precompile: none`, which is the pairing the schema
tells you to hunt for — and it is **deliberately not that finding**. That finding is
about a chain accepting *signatures* its own contracts cannot verify. Here there is no
signature, so there was never anything for a precompile to be paired with. The
integrator hazard is the mirror image and just as sharp: `ecrecover` over a `0x7e`
envelope returns garbage rather than failing, because every field it reads is zero.

A second unsigned path exists in the same tree — `PostExecTxType` `0x7D`, whose signer
branch returns the **zero address** and whose `sigHash` also panics. The client has the
type, its marshalling and its receipt handling, but no producer and no fork gate, so
whether it is reachable on any live chain is recorded as `unrecorded`.

## Re-verify

```
git clone --depth 1 --branch v1.101702.2 https://github.com/ethereum-optimism/op-geth
sed -n '/PrecompiledContractsJovian = /,/^}/p' core/vm/contracts.go
sed -n '300,320p' core/vm/contracts.go                  # OP-before-Osaka ordering
sed -n '185,200p' params/protocol_params.go             # the input caps
sed -n '1685,1696p' params/config.go                    # enforced fork mapping
cat core/types/deposit_tx.go                            # 0x7e
```
