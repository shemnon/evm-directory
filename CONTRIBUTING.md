# Contributing

EVM Directory records how EVM chains differ from Ethereum Mainnet, built from pinned
source code and pinned observations of live networks. Corrections are welcome. This file
says what the directory accepts and what it does not, how to report something, and what
happens after you do.

**Issues are open to everyone. Pull requests are accepted from the repository's
collaborators only.** The dataset is written by AI models under the operator's
supervision ([principle 2](#2-ai-generated)), so an outside contribution takes the form
of an issue carrying evidence, never a patch.

Every page on the site links to the issue form as **Report an inaccuracy**. On a chain
page the form opens with that chain already filled in. You can also start from the
[new-issue page](https://github.com/shemnon/evm-directory/issues/new/choose).

- [Principles](#principles)
- [Reporting an inaccuracy](#reporting-an-inaccuracy)
- [What happens to an issue](#what-happens-to-an-issue)
- [Adding a chain](#adding-a-chain)
- [Sensitive findings and security](#sensitive-findings-and-security)
- [Rows that do not yet meet these principles](#rows-that-do-not-yet-meet-these-principles)
- [The operator](#the-operator)
- [Conduct](#conduct)
- [License](#license)

## Principles

### 1. No marketing

This resource is not part of your marketing channel. Correcting an inaccuracy is
welcome. Adjusting an axis, a label, a note or a grid to showcase your chain's
differentiation is not, and requests to do so will be closed.

Every row is written in one fixed vocabulary against mainnet — `added`, `removed`,
`modified`, `inherited`, `pending` ([SCHEMA.md](SCHEMA.md)). A chain's own product
language ("fully EVM-equivalent", "EVM+", "next-generation") does not appear in its row,
and a chain's preferred framing of a difference is not a reason to change how the row
states it.

### 2. AI generated

This resource is the result of AI model analysis of public source code and public
networks. Present evidence and argument for an inaccuracy. To keep every row on the same
footing, AI models generate the resulting content — not the person who filed the issue,
and not the operator by hand. Your wording will not be pasted in, even when it is
correct; the claim is re-derived from the evidence and written in the dataset's own
vocabulary.

The models in use are listed under [The operator](#ai-models).

### 3. Evidence over assertion

A correction must point at something anyone can check. In order of strength:

| Kind | What to send |
|---|---|
| **Source** (`src:`) | the repository, a released tag or commit, the file and the symbol |
| **Live** (`src_live:`) | the RPC endpoint, the method and arguments, and the **block height** you observed it at |
| **Documentation** (`src_doc:`) | a URL. The weakest kind — documentation describes intent, and lags or contradicts what shipped. |

Documentation does not overrule the chain's own client. "Our docs say X" set against a
pinned source line that does Y is a report that the docs are wrong. A live observation
without a block height cannot be replayed and is not evidence. A claim with no evidence
is labelled `needs-evidence` and waits for some.

### 4. As shipped, not as planned

A row describes what the chain's mainnet runs now, as read from the pinned client.
Roadmaps, testnet-only features and "coming in v2" are out of scope. A scheduled fork can
be recorded with its date; what it changes is recorded when it activates on mainnet —
file a *Network upgrade* issue then.

### 5. Ethereum Mainnet is the reference

Every row is a delta against Ethereum Mainnet. A chain that matches mainnet produces a
nearly empty row, and that emptiness is itself the finding — not a gap to be filled with
features. The directory does not adopt another chain, or a framework, as the reference
for anyone else.

### 6. Divergence is not a demerit

The directory does not score, rank or grade chains. A difference from mainnet is recorded
because integrators, auditors and tool authors need to know about it, not because it is
good or bad. The directory will not add a difference because it flatters a chain, and
will not remove an accurate one because it looks bad.

`severity: high` marks a divergence that **fails silently** — no revert, no error, no
signal to the caller. It measures how hard a difference is to detect, not how bad the
chain is.

### 7. Public evidence only

Everything in a row must be reproducible by anyone with the public source and a public
endpoint. Private repositories, material under NDA, internal documents, private
conversations and "I work there" are not evidence, however accurate. If it cannot be
shown in public, it cannot be in the row.

### 8. Disclose your affiliation

When you file an issue, say whether you work for or with a chain it concerns: team,
foundation, contractor, grantee, investor — or a competitor. Affiliated reports are
welcome and are handled by exactly the same rules; the disclosure is for the reader.

A correction supplied by people affiliated with the chain it concerns is credited on that
chain's page ([below](#credit-on-the-chain-page)). The operator's own affiliations are
disclosed under [The operator](#the-operator).

### 9. Listing is not endorsement

A row means the chain met the [admission criteria](#adding-a-chain), and nothing more.
Chains are added on the criteria, not on request, and a row is never removed because the
chain's team would rather it were not there.

A chain that shuts down or goes dark keeps its row, marked as such on every page it
appears on. Its facts can no longer be contradicted by anything the network does, which
makes them a permanent record rather than stale data.

### 10. Sensitive findings do not go here

Not in an issue, not in a comment, not by any other route to the operator. See
[Sensitive findings and security](#sensitive-findings-and-security).

### 11. Live and publicly reachable

A row needs a mainnet that is producing blocks and a public RPC endpoint that answers.
Live observations are pinned to a block height precisely so that someone else can replay
them; a network nobody can reach cannot be checked. Rows that are prelaunch, halted or
unreachable exist and are marked as such, but they are exceptions recorded against this
rule, not a way around it.

### 12. Source available

A row should rest on a public execution client — the code that defines the state
transition — pinned to a released tag and a commit. A closed consensus client or
sequencer is tolerated when the execution client is public. A row built from
documentation and live probes alone (`evidence: documented`) is a labelled exception,
not an admission route.

## Reporting an inaccuracy

[Open an issue](https://github.com/shemnon/evm-directory/issues/new/choose) and pick a
form:

| Form | Use it when |
|---|---|
| **Correction** | a page states something wrong or incomplete about a chain |
| **Network upgrade** | a chain's mainnet has forked, or its client has a release newer than the pinned version |
| **Add a chain** | proposing a chain for a row of its own |
| **Site problem** | a broken link, a page that renders wrongly, a control that misbehaves |
| **Blank issue** | anything the forms do not fit — a question, a proposal about the schema or these principles |

A blank issue is held to the same principles as a form: evidence for a factual claim,
your affiliation if you have one, and nothing sensitive.

A good correction:

- links to the page and the entry — every entry on a chain page has its own anchor, e.g.
  `chains/base.html#precompiles-0x100`;
- quotes what the page says, and states what is true instead;
- gives evidence under [principle 3](#3-evidence-over-assertion);
- states your affiliation;
- makes **one claim**. Three unrelated problems are three issues.

## What happens to an issue

1. **Triage.** The issue is labelled. One without evidence is marked `needs-evidence`.
   One that asks for marketing, a roadmap item or non-public evidence is closed with the
   principle it conflicts with.
2. **Re-derivation.** An AI model re-reads the claim against the pinned source or a live
   probe — not against the issue's text. Often this means running the full update pass
   over the affected row, which can also move its pinned client to a newer release.
3. **Change.** If the evidence holds, the operator opens a pull request that references
   the issue. It passes the same gates as every other change.
4. **Close**, with one outcome: *corrected*, *not reproduced* (with what was checked),
   *needs evidence*, or *out of scope*.

The issue thread is the public record of the decision. No response time is promised:
this is a personal project, run as time allows.

### Credit on the chain page

When a merged correction came from a contributor who disclosed an affiliation with the
chain it concerns, that chain's page says so in its Evidence section, citing the issues:

> This row includes corrections and information provided by contributors affiliated with
> *Chain*, vetted by AI against publicly available data: #12, #31.

Only corrections from contributors affiliated with the chain itself are credited.
Unaffiliated contributors and contributors from competing chains are not listed. In
every case the re-derivation against public evidence is the safeguard; the credit exists
so a reader knows when a row's own team shaped what it says. The line appears on the
chain page only — never on an axis page, an index or a grid.

## Adding a chain

A chain is eligible for a row when it meets all four:

1. **It is an EVM chain.** It executes EVM bytecode, or presents an EVM interface to
   contracts and tooling.
2. **It is live and publicly reachable** ([principle 11](#11-live-and-publicly-reachable)).
3. **Its execution client is public** ([principle 12](#12-source-available)).
4. **It would teach something.** It differs from mainnet, or from the framework it is
   built on, in a way worth recording. A chain that reproduces its framework exactly —
   an OP Stack chain with no delta of its own, say — is listed under the framework's
   row instead of receiving one.

Eligible is not scheduled. The backlog, the selection order and what each past pass
predicted are in [CANDIDATES.md](CANDIDATES.md).

## Sensitive findings and security

> **Do not send sensitive findings to this directory.**
>
> If you believe you have found something exploitable — funds at risk, a consensus
> fault, an unpatched vulnerability in a chain or its client — report it to the affected
> chain's security contact or bug-bounty programme, or through another responsible
> disclosure venue. Do not file it as an issue, post it in a comment, or send it to the
> operator by any other means.
>
> **Do not consider this directory secure.** Issues are public the moment they are filed.
> There is no private reporting channel, and the operator does not triage, embargo or
> coordinate the disclosure of vulnerabilities. The directory and its operator are not
> responsible for anything disclosed through it.

The directory records behaviour that is already public — in released source code or on a
running network. Once a vulnerability has been fixed and publicly disclosed by the chain,
the behaviour it involved can be reported as an ordinary correction.

## Rows that do not yet meet these principles

The rows below predate the principles and conflict with at least one of them. Each will
be resolved by the operator — by fixing the row, by recording it as a standing
exception, or by removing it. Until then each is shown, marked, as it is today.

1. **[hyperliquid](chains/hyperliquid/SUMMARY.md)** — [12, source available](#12-source-available).
   No public execution client exists; the row is `evidence: documented`, built from
   documentation and live probes only.
2. **[rise](chains/rise/SUMMARY.md)** — [12, source available](#12-source-available).
   The pinned tag is a deployment repository; the execution client itself is closed.
3. **[taraxa](chains/taraxa/SUMMARY.md)** — [11, live and publicly reachable](#11-live-and-publicly-reachable).
   Every published RPC endpoint failed to resolve when checked on 2026-08-27, so the row
   has no live evidence, and it is still marked `live: true`.
4. **[arc](chains/arc/SUMMARY.md)** — [11, live and publicly reachable](#11-live-and-publicly-reachable).
   Prelaunch: mainnet has never produced a block. Launch is announced for 2026-09-16,
   which would resolve it.

Dead rows — [artela](chains/artela/SUMMARY.md), [moonbeam](chains/moonbeam/SUMMARY.md)
and [polygon-zkevm](chains/polygon-zkevm/SUMMARY.md) — are not on this list. They met the
principles while they ran, and [principle 9](#9-listing-is-not-endorsement) keeps them.

## The operator

The directory is run by one person, Danno Ferrin
([@shemnon](https://github.com/shemnon)), referred to here as the operator. The operator
supervises the AI models that write the dataset, triages issues and merges changes.

### Affiliations

As of 2026-09-11:

| | Organisation | Role | Rows it touches |
|---|---|---|---|
| Current | Sei Labs | engineer | [sei](chains/sei/SUMMARY.md) |
| Former | an unreleased reth-derived chain | engineer | none |
| Former | Hedera | execution and smart-contract engineer | [hedera](chains/hedera/SUMMARY.md) |
| Former | Hyperledger Besu | core developer | [linea](chains/linea/SUMMARY.md) (a Besu package), [hedera](chains/hedera/SUMMARY.md) (Besu's EVM as a library) |
| Former | Ethereum Foundation | Ethereum core developer | [ethereum](chains/ethereum/SUMMARY.md), the baseline every other row is measured against |

Rows touched by an affiliation are held to exactly the same rules as every other row:
built only from public source and public networks, generated by the same models, and
corrected through the same public issues. No non-public information from any employer,
past or present, enters the dataset.

A *current* affiliation is also stated on the page of each row it touches, in one line in
that page's Evidence section:

> The operator of this directory is a current Sei Labs engineer; see Contributing.

Former affiliations are disclosed here only. The machine-readable copy of this table is
[`operators.yaml`](operators.yaml); the two change together.

### Disclaimer

EVM Directory is a personal project of the operator. It is not a product of, and is not
reviewed or endorsed by, Sei Labs, the Sei Foundation, or any other current or former
employer of the operator. The views and opinions expressed in it are the operator's own
and do not necessarily reflect those of Sei Labs or any of those organisations.

### AI models

The dataset is generated by:

| Model | Vendor |
|---|---|
| Claude Opus 5 | Anthropic |

Each commit's `Co-Authored-By` trailer records the model that did that piece of work.

## Conduct

Stay on the facts. Bring evidence, argue from it, and accept an outcome stated against a
principle even when you disagree with the principle. Promotional material, personal
attacks, and pressure applied through channels other than the issue will be removed;
repeated, the account will be blocked.

## License

- **Code** — everything under `tools/`, the scripts under `.claude/`, and the workflows
  under `.github/` — is licensed under the [Apache License 2.0](LICENSE).
- **Data and prose** — `chains/`, `findings.yaml`, `operators.yaml`, the generated
  tables, the Markdown documents and the published site's content — are dedicated to the
  public domain under [CC0 1.0 Universal](LICENSE-DATA). Use them for anything, with no
  permission needed and no conditions attached.

**A request, not a condition:** if you use or republish this data, please link back to
<https://github.com/shemnon/evm-directory>. The dataset is corrected over time, and a
link is how your readers find the current version and a way to report an error. CC0
does not require it, and nothing here makes it binding.

By filing an issue you agree that the facts and evidence in it may be used in the
dataset under CC0. Material you cite stays under its own license: the dataset records
and cites it, it does not copy it.
