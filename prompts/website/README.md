# `prompts/website/` — the site specification

These files are the **source of the website's structure**. `website/` is rendered
output and `tools/site.py` is an implementation; both are downstream of what is
written here. When the two disagree, this directory is wrong or the code is — decide
which, fix that one, and keep them in step.

## Using these

**To rebuild the site from nothing**, give a model [00-brief.md](00-brief.md) plus the
repository, then work through `01`–`07` in order. Each file is self-contained enough to
act on and states its own acceptance conditions.

**To refactor or extend**, cite the section you are changing —
`prompts/website/03-grids.md#row-identity` — state what should now be true, and update
that file in the same change. A change to behaviour that does not touch these files is
incomplete.

**To review**, run [08-acceptance.md](08-acceptance.md). It is mechanical and has no
judgement in it.

| File | Answers |
|---|---|
| [00-brief.md](00-brief.md) | what this site is, and the rules that override everything else |
| [01-architecture.md](01-architecture.md) | which pages exist, and the URL map |
| [02-pages.md](02-pages.md) | what each page contains, in order |
| [03-grids.md](03-grids.md) | the grid: cell vocabulary, row identity, links, filtering |
| [04-data.md](04-data.md) | how the dataset is read, and every inheritance rule |
| [05-build.md](05-build.md) | the generator, the incremental build, the CLI |
| [06-presentation.md](06-presentation.md) | layout, styling, interaction, persistence |
| [07-voice.md](07-voice.md) | how the site is allowed to talk |
| [08-acceptance.md](08-acceptance.md) | the checks a finished change must pass |

## What is *not* specified here

The **content of the dataset** — `chains/*/chain.yaml`, `chains/*/SUMMARY.md` — is
governed by [`SCHEMA.md`](../../SCHEMA.md), not by these files. The site renders
whatever the schema holds; it does not decide what is true.

The **narrative layer** — `findings.yaml` — is content, written by a human. These files
say where notes appear and how they are worded, not what they say.
