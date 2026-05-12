# 10 — API Documentation (browsable HTML)

The full documentation site has two parts that build together via [`scripts/build_docs.sh`](../../scripts/build_docs.sh):

1. **MkDocs Material** — renders all the markdown in [docs/](../) (this folder + the high-level docs) as a styled, searchable static site at `site/index.html`.
2. **pdoc** — renders the Python source docstrings as browsable HTML at `site/api/index.html`.

The two are linked from the MkDocs nav so it feels like one site.

## Build

```bash
./scripts/build_docs.sh
open site/index.html
```

The script:

- Regenerates `docs/api/` from current Python docstrings via pdoc.
- Builds MkDocs into `site/`.
- Copies `scripts/` and `outputs/` into `site/` so every relative link works.

## Live preview while editing

```bash
.venv/bin/mkdocs serve
```

Then open <http://localhost:8000>. Pages refresh on save.

## pdoc on its own

If you only want to look at Python source docs without MkDocs:

## Generate

```bash
.venv/bin/pdoc \
  scripts/option2_pipeline.py \
  scripts/bertopic_from_run.py \
  scripts/insight_layer.py \
  scripts/split_outlier_bucket.py \
  scripts/llm_extract_rich_tickets.py \
  scripts/build_user_wants_taxonomy.py \
  --output-directory docs/api \
  --docformat google
```

This creates `docs/api/` with one HTML page per script plus an index. Open `docs/api/index.html` in a browser.

## Live preview

While editing docstrings, run pdoc as a live server:

```bash
.venv/bin/pdoc \
  scripts/option2_pipeline.py \
  scripts/bertopic_from_run.py \
  scripts/insight_layer.py \
  scripts/split_outlier_bucket.py \
  scripts/llm_extract_rich_tickets.py \
  scripts/build_user_wants_taxonomy.py \
  --port 8080
```

Then open <http://localhost:8080> — pages refresh whenever you save a script.

## Convenience script

`scripts/build_docs.sh` runs the pdoc command above and writes the static site into `docs/api/`. Run it any time after editing a docstring:

```bash
./scripts/build_docs.sh
```

## Why MkDocs + pdoc and not Sphinx?

- **MkDocs Material** renders Markdown as-is. No `.rst` rewrite, no theme bootstrapping, no separate ToC files. Single `mkdocs.yml`.
- **pdoc** reads Python docstrings directly. No autodoc gymnastics.
- Together they cover the two orthogonal needs: prose docs (MkDocs) and source docs (pdoc).
- Sphinx is the standard for very large Python projects but is overkill here. The whole site builds in under 2 seconds.

## Why pdoc specifically

- pdoc reads docstrings directly from source. No `.rst` files to maintain.
- Single-command HTML generation. Sphinx requires `conf.py`, themes, build directories, ToC files.
- Python-only. We do not document any non-Python tooling.
- Search box, type-link rendering, and source-view are built in.

If we ever need cross-project docs or PDF output, Sphinx with the autodoc extension can re-use the same docstrings without rewrites.

## Docstring style

All docstrings use Google style:

```python
def function(arg: int) -> str:
    """One-line summary.

    Longer description if needed.

    Args:
        arg: what it represents.

    Returns:
        what comes back.

    Raises:
        ValueError: when invalid.
    """
```

To see what pdoc will render, look at any function in [scripts/build_user_wants_taxonomy.py](../../scripts/build_user_wants_taxonomy.py) — that file was written with documentation in mind.
