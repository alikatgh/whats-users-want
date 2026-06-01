# 05 — Baking the bundle (export_static_readout.py)

## The build step

[scripts/export_static_readout.py](../../scripts/export_static_readout.py) is the
bridge from "a pipeline run finished" to "the readout folder is ready to open or
upload." It runs **no AI and no pipeline** — it reads existing run outputs and
writes `data/bundle.js`. One command:

```bash
python scripts/export_static_readout.py outputs/option2_<timestamp>
```

## Map run-filenames to app-keys

The app (`app.js`'s `FILES`) expects keys like `summary`, `journeys`, `trends`.
The run writes files like `user_wants_full_corpus_summary.csv`. `FILE_TO_KEY`
bridges the two:

```python
FILE_TO_KEY = {
    "user_wants_full_corpus_summary.csv": "summary",
    "longitudinal_user_journeys.csv": "journeys",
    # …
}
```

## Read + redact

`read_redacted_rows()` uses `csv.DictReader` and drops person-attribution columns
(manager names) on the way in:

```python
keep = [c for c in reader.fieldnames if not is_attribution_column(c)]
return [{k: (row.get(k) or "") for k in keep} for row in reader]
```

Redaction is a **build concern**, done once — not something the app has to
remember at render time. (Why it matters: Lesson 06.)

## Build + write

`build_data()` turns each CSV into a list of dicts and each JSON into an object.
`write_bundle()` serializes the whole thing into the global the app reads:

```python
bundle.write_text(
    "window.WUW_DATA = " + json.dumps({**data, "manifest": manifest}, ensure_ascii=False) + ";\n"
)
```

## Bake in place — the deliverable *is* the folder

By default the script writes straight into `static/what_users_want_cdn/data/` —
that folder is the thing you open and upload. There is no separate "output copy"
to keep in sync. (An earlier version *did* write a separate copy, and it caused
exactly the "bundle.js is missing" confusion of opening the wrong folder. Removing
the split removed the bug.) `--out-dir` optionally *also* emits a standalone copy
elsewhere, for upload convenience.

## Provenance: the manifest

Every bake writes `manifest.json` — which run, when, which files, and the redaction
note. So months later you can always answer *"where did these numbers come from?"*
This is the same provenance discipline as the pipeline itself (Module 10).

## The clean split

Notice the shape of this module: one script regenerates the **data layer**; the
**shell** (HTML/CSS/JS) is never touched. Data and presentation are cleanly
separated, so a new run is one command and a restyle (Lesson 02) is a token edit —
neither disturbs the other. That separation is what makes the whole thing
maintainable.

Read next: [06 — Privacy on a static site](06-privacy-on-a-static-site.md).
