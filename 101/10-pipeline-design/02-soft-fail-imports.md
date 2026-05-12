# 02 — Soft-fail imports

## What problem does this solve

Some libraries in the stack are heavy or environment-specific:
`sentence-transformers` downloads ~480 MB of model weights, `umap-learn`
needs `numba`, `statsmodels` requires `scipy`, BERTopic depends on
several of those. A teammate cloning the repo for the first time, or a
CI runner with a minimal environment, may not have all of them.

Hard-failing the moment any optional library is missing turns a
useful pipeline into a brick. The right answer: **soft-fail**. If the
optional dependency isn't there, skip the feature it powers and emit a
warning. The pipeline still produces all the outputs that don't depend
on it.

## What's actually happening

The pattern has two moving parts.

First, an `optional_import` helper that wraps a try/except around
`__import__`. Returns `None` if the import fails.

Second, lazy imports **inside the function** that needs the library
rather than at the top of the module. That way the module file itself
loads even when the dependency is missing — only calling the specific
function fails.

Third, every cluster-related function wraps its imports in another
try/except so that a missing library produces a `print` warning and a
graceful fallback rather than an exception.

## The code in this codebase

[scripts/option2_pipeline.py](../../scripts/option2_pipeline.py) defines
the helper:

```python
def optional_import(module_name: str) -> Any | None:
    try:
        return __import__(module_name)
    except Exception:
        return None
```

It's not used much directly (the pattern that grew is "lazy import +
try/except"), but the helper is a one-liner that makes the intent
explicit when you do need it.

The real-world pattern is in `cluster_texts`:

```python
def cluster_texts(df, out_dir, backend, model_name):
    from sklearn.decomposition import TruncatedSVD
    from sklearn.preprocessing import normalize
    ...
    try:
        import umap
        n_neighbors = min(30, max(5, len(work) // 200))
        reducer_2d = umap.UMAP(...)
        coords = reducer_2d.fit_transform(dense)
        x, y = coords[:, 0], coords[:, 1]
        reducer_cluster = umap.UMAP(...)
        reduced = reducer_cluster.fit_transform(dense)
    except Exception as exc:
        print(f"[warn] UMAP unavailable/failed: {exc}. Clustering on SVD/embedding space.", file=sys.stderr)

    try:
        import hdbscan
        min_cluster_size = max(12, min(80, len(work) // 90))
        clusterer = hdbscan.HDBSCAN(...)
        labels = clusterer.fit_predict(reduced)
    except Exception as exc:
        print(f"[warn] HDBSCAN unavailable/failed: {exc}. Falling back to MiniBatchKMeans.", file=sys.stderr)
        from sklearn.cluster import MiniBatchKMeans
        k = max(8, min(35, int(math.sqrt(len(work) / 2))))
        clusterer = MiniBatchKMeans(n_clusters=k, ...)
        labels = clusterer.fit_predict(reduced)
```

Three try/except blocks, three different fallbacks:

- **UMAP missing or broken**: cluster directly in SVD or embedding
  space (still works, just lower-quality clustering).
- **HDBSCAN missing or broken**: fall back to MiniBatchKMeans (forces
  every ticket into a cluster instead of leaving noise as `-1`, but
  produces a usable assignment).
- **Plotly missing**: `create_charts` does the same dance and the
  HTML map is just not produced.

Each fallback is **strictly worse** than the primary path — but
"strictly worse than ideal" beats "completely missing."

The `adjusted_manager_context` function does the same with statsmodels:

```python
def adjusted_manager_context(df: pd.DataFrame) -> pd.DataFrame:
    try:
        import statsmodels.formula.api as smf
    except Exception:
        return pd.DataFrame({"note": ["statsmodels unavailable; adjusted model skipped"]})
    ...
```

Without statsmodels you get a one-row DataFrame with a note. The CSV
file still exists; everything that consumes it can handle the
note-only shape.

`build_network` does the same for networkx:

```python
def build_network(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    try:
        import networkx as nx
    except Exception:
        return pd.DataFrame({"note": ["networkx unavailable; desire/category network skipped"]})
    ...
```

## Lazy imports inside functions

Notice that `import sklearn`, `import umap`, `import hdbscan`,
`import statsmodels.formula.api`, `import networkx` are **inside**
their functions, not at the top of the file. This is deliberate.

If they were at the top, `import option2_pipeline` would fail when any
of those is missing — and pdoc, mypy, even the `--help` flag would
all fail.

By moving them inside the function:

- The module loads even with a partial environment.
- Only calling the function triggers the import.
- The try/except can catch `ImportError` cleanly.

The trade-off: lazy imports are slower the *first* time the function
is called (you pay the import cost then). For this pipeline that's
fine — clustering is run once per pipeline invocation, not in a tight
loop.

## When NOT to soft-fail

The pattern doesn't apply to everything. Hard dependencies (pandas,
numpy, the standard library) are required. If they're missing, the
pipeline is fundamentally broken and should fail at import time.

The convention: **mandatory libraries import at the top of the module;
optional libraries import inside their function with try/except**.

[scripts/option2_pipeline.py](../../scripts/option2_pipeline.py) top:

```python
import argparse
import json
import math
import os
import re
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
```

That's it. Nothing else at module load time. Every other library
appears inside a function with try/except.

## Why we chose this approach

Three benefits worth naming:

1. **Onboarding is easier.** A new contributor can `pip install pandas
   numpy` and run `python -c "import scripts.option2_pipeline"` to
   verify the module loads. They get TF-IDF clustering for free; they
   add UMAP/HDBSCAN/statsmodels later when they need them.
2. **CI is faster.** A linter or smoke-test job doesn't need the heavy
   ML libraries to import the module and run AST checks.
3. **Errors are useful.** When a feature is missing, the warning says
   *which* feature and *why* it's missing. A traceback from a
   top-of-module ImportError tells you nothing about the function
   that needed it.

The cost: the first call to `cluster_texts` pays the UMAP import time
(~2 seconds). Once. Acceptable.

## Try it

Open a Python shell and try the import-time experiment:

```bash
.venv/bin/python -c "import scripts.option2_pipeline; print('module loaded ok')"
```

You should see "module loaded ok" with no errors, even if UMAP and
HDBSCAN aren't installed. (They are in our `.venv`, but the
demonstration is that the module *would* still load without them.)

Now try simulating a missing library by uninstalling temporarily:

```bash
.venv/bin/pip uninstall -y umap-learn
.venv/bin/python scripts/option2_pipeline.py --input data_2may.csv --embedding-backend tfidf 2>&1 | head -20
```

You'll see `[warn] UMAP unavailable/failed:`, the pipeline falls back
to clustering directly in the SVD space, and the run directory still
gets created. The `semantic_ticket_map.html` file won't be there
(plotly UMAP fallback also failed to plot), but `enriched_tickets.csv`,
`manager_context_quality.csv`, and friends are all produced.

Reinstall to restore the full pipeline:

```bash
.venv/bin/pip install umap-learn
```

Try the same with `statsmodels`:

```bash
.venv/bin/pip uninstall -y statsmodels
.venv/bin/python scripts/option2_pipeline.py --input data_2may.csv --embedding-backend tfidf 2>&1 | grep statsmodels
```

You'll see "statsmodels unavailable; adjusted model skipped" and the
pipeline still finishes. `adjusted_manager_context_model.csv` will
have the one-row "note" shape instead of the per-manager rows.

Reinstall and you get the full output again. The pipeline degrades
gracefully — never throws away work.
