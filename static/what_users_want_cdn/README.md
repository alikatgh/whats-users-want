# Static What Users Want Readout

This folder is the CDN template. The `data/` subfolder is ignored by git and
may exist locally only for preview/debugging. Do not upload this template folder
directly unless you have intentionally synced it from a redacted export.

To build the shareable internal site from an existing run:

```bash
python3 scripts/export_static_readout.py outputs/option2_20260513_030517 --force
```

The exporter copies already-generated CSV/JSON outputs into:

```text
outputs/static_what_users_want/data/
```

It also copies the local chart library in `vendor/echarts.min.js`. Keep that
file with the package: charts do not load ECharts from a public CDN at runtime.

It does **not** run Ollama, embeddings, clustering, Streamlit, or any other AI
step. The browser reads the copied CSVs directly with `fetch()`. The exporter
removes person-attribution columns from the packaged CSV files.

Preview locally:

```bash
./scripts/run_static_readout.sh
```

Then open:

```text
http://127.0.0.1:38484/
```

Do not open `index.html` directly with `file://`. Modern browsers block
JavaScript `fetch()` calls to local CSV files from `file://`, which produces
CORS errors. The CDN will serve the same files over `https://`, and the local
preview command above serves them over `http://`.

Upload the full contents of `outputs/static_what_users_want/` to an internal,
access-controlled CDN location, including `assets/`, `data/`, and `vendor/`.
The copied CSVs can include ticket text, UIDs, URLs, and support notes. The
exporter removes person-attribution columns such as manager fields before
packaging.
