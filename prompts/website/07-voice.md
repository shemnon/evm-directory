# 07 — Voice

The site is a dry reference. It states what the data holds and stops.

## Not allowed on data pages

- **Methodology.** How facts were gathered, what makes them trustworthy, what a survey
  that did it differently would have missed.
- **Argument.** Anything defending the dataset's correctness or its approach.
- **Headlines.** Section and note titles are descriptive noun phrases, not claims.
  "Address collisions at `0x64`–`0x69`", not "Address collisions are real, shipped, and
  multiplying".
- **Rhetorical framing.** *the sharpest case*, *worse than divergence*, *and it is a law,
  not an anecdote*, *the interesting cell is where they fail to line up*. Delete the
  framing, keep the fact.
- **Shouting.** Callout labels are lower-case descriptors — "not enumerable",
  "unpaired", "byte-range occupancy" — never "COLLISION COURSE".

## The exception

**Chain pages** state where that chain's data came from: which client is pinned, at which
commit, whether the row rests on source, documentation or live probes, and how to
re-verify it. That is a fact about the chain, and it is the only methodology on the site.

**The Reference page** renders `SCHEMA.md` and `SITE.md`. Its subject *is* method, which
is why it exists and why nothing else discusses it.

## Notes

`findings.yaml` is the interpretive layer — the one place a human says what a set of rows
adds up to. Notes are **descriptive**: state what the data shows, cite the rows, stop.

A note is written once and appears in three places: the Overview index, its `axis:` page,
and the page of every chain in its `chains:` list.

Prefer computing a number to writing one. A note claiming "only `0x7a` and `0x7d` remain"
goes stale the moment a chain claims `0x7d`; a page that derives occupancy from the data
does not. Where both are useful, let the note point at the computed section.

## Author's prose

`chains/*/SUMMARY.md` and the `note:` fields in `chain.yaml` are the dataset author's
writing, reproduced verbatim. They are not subject to these rules and must not be
rewritten to match them. The rules govern what the *site* says in its own voice.
