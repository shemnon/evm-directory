# `prompts/`

Specifications written to be handed to a model, one directory per deliverable. They are
the source of that deliverable's *structure*, the way `chains/*/chain.yaml` is the source
of its *content*.

| Directory | Governs |
|---|---|
| [`website/`](website/) | the static site in `website/`, and `tools/site.py` |

A prompt set is expected to be:

- **Sufficient** — a model given the repository and the set can rebuild the deliverable.
- **Addressable** — sections can be cited in a change request, e.g.
  `prompts/website/03-grids.md#row-identity`.
- **Current** — a behaviour change that does not update the spec is incomplete.
- **Checkable** — it ends with mechanical acceptance criteria, not opinions.
