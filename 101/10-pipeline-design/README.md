# 10 — Pipeline design

## Prerequisites

Modules [01-09](../README.md). This module looks at the pipeline as a
whole rather than at any one technique. It helps to have read modules
01-06 so each design pattern is concrete.

## What you can do after

- Recognise the patterns that make a multi-stage data pipeline maintainable.
- Decide when to soft-fail versus when to crash.
- Use timestamped run directories instead of mutating in place.
- Make a pipeline idempotent so partial reruns don't break.
- Track provenance so you can answer "where did this number come from?"
- Spot when an orchestrator function is doing too much.

## Lessons

| # | File | What it covers |
|---|---|---|
| 01 | [01-stages-and-runs.md](01-stages-and-runs.md) | Timestamped output dirs; six-stage shape; why each stage is its own script |
| 02 | [02-soft-fail-imports.md](02-soft-fail-imports.md) | `optional_import`; lazy imports; partial environments still produce outputs |
| 03 | [03-priority-fallback.md](03-priority-fallback.md) | `_first_existing`, `latest_run`, multi-CSV priority lookups |
| 04 | [04-marker-based-idempotency.md](04-marker-based-idempotency.md) | Replacing one section of a Markdown report on re-run instead of duplicating it |
| 05 | [05-metadata-and-provenance.md](05-metadata-and-provenance.md) | `run_metadata.json`, `df.attrs`, recording what was run and how |
| 06 | [06-orchestrator-pattern.md](06-orchestrator-pattern.md) | The `run(args)` entry point; argparse → orchestrator → exit |

What's next: [Module 11 — The findings](../11-the-findings/README.md).
