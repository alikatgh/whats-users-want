# 13 — The static frontend

How the management-facing readout is built: a single folder of plain HTML, CSS,
and JavaScript that runs with **no server** — open it as a file, or drop it on a
CDN — yet still searches, filters, and charts thousands of tickets entirely in
the browser. No React, no build tool, no framework. On purpose.

This module exists because of a hard constraint the project hit: *the only place
we can host the readout is a CDN.* A CDN serves files; it doesn't run code. So the
whole dashboard has to behave like a plain web page. That one constraint shapes
every decision in this chapter.

## Prerequisites

Module [02 — Data with pandas](../02-data-with-pandas/README.md) (the build
scripts read the same run-output CSVs) and a reading knowledge of HTML, CSS, and
JavaScript. You do **not** need any framework experience — there deliberately
isn't one here.

## What you can do after

- Build a dashboard that runs from `file://` and any CDN with **zero server code**.
- Embed data into a page so there is nothing to `fetch()` — and know when that's the right call.
- Apply a calm, legible design system: flat surfaces, hairline borders, weight-based hierarchy.
- Generate a complete, shippable HTML page from Python.
- Render thousands of rows client-side without a framework.
- Reason about privacy when **every byte you ship is downloadable**.

## Lessons

| # | File | What it covers |
|---|---|---|
| 01 | [01-self-contained-static.md](01-self-contained-static.md) | Why no server: data baked into the page, `fetch()` vs `<script>`, `file://` + CDN |
| 02 | [02-the-design-system.md](02-the-design-system.md) | The "feeling": flat surfaces, hairlines, no shadows, weight-not-color, tabular numbers |
| 03 | [03-generate-a-page-from-python.md](03-generate-a-page-from-python.md) | `build_compare_view.py`: a template + embedded JSON → one self-contained file |
| 04 | [04-the-dashboard-app.md](04-the-dashboard-app.md) | `app.js`: `window.WUW_DATA`, views, client-side rendering, ECharts |
| 05 | [05-baking-the-bundle.md](05-baking-the-bundle.md) | `export_static_readout.py`: bake the run's data into the folder, redaction, manifest |
| 06 | [06-privacy-on-a-static-site.md](06-privacy-on-a-static-site.md) | Everything shipped is downloadable: redaction + an access-controlled CDN |

## The two files to open alongside this chapter

- [static/what_users_want_cdn/](../../static/what_users_want_cdn/) — the deliverable: `index.html`, `assets/app.js`, `assets/styles.css`, `data/bundle.js`.
- [scripts/build_compare_view.py](../../scripts/build_compare_view.py) and [scripts/export_static_readout.py](../../scripts/export_static_readout.py) — the two builders.

What's next: back to the pipeline — [Module 10 — Pipeline design](../10-pipeline-design/README.md).
