# Exercise 05 — Cluster with different `k`

## What you'll practice

- Running `build_user_wants_taxonomy.py` with different parameters.
- Reading a silhouette score and judging cluster quality.
- Comparing two taxonomies side by side.
- Deciding when a finer / coarser taxonomy makes sense.

## The setup

The default Stage 6 produced 17 clusters from 250 LLM extractions
using the auto-fallback (HDBSCAN → KMeans with `k=17`). Was 17 the
right number?

This exercise re-runs the clustering at `k=10`, `k=15`, `k=20`, and
`k=25` and compares the results. There's no single right answer —
the goal is to develop intuition for when finer granularity buys
clarity vs noise.

## Step 1 — run with k=10

```bash
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)
.venv/bin/python scripts/build_user_wants_taxonomy.py "$RUN_DIR" \
  --method kmeans --n-clusters 10
```

This forces KMeans (skipping the HDBSCAN attempt) with exactly 10
clusters. Output files are overwritten in the run directory:

- `user_wants_taxonomy.csv` — 10 rows.
- `user_wants_assignments.csv` — 250 rows, each with want_id 0-9.
- `user_wants_findings.md` — refreshed.
- `user_wants_workbook.xlsx` — refreshed.

Save a copy before re-running with k=15, otherwise the next run will
overwrite:

```bash
cp "$RUN_DIR/user_wants_taxonomy.csv" "$RUN_DIR/user_wants_taxonomy_k10.csv"
cp "$RUN_DIR/user_wants_assignments.csv" "$RUN_DIR/user_wants_assignments_k10.csv"
```

## Step 2 — repeat for k=15, 20, 25

```bash
for k in 15 20 25; do
  .venv/bin/python scripts/build_user_wants_taxonomy.py "$RUN_DIR" \
    --method kmeans --n-clusters $k
  cp "$RUN_DIR/user_wants_taxonomy.csv" "$RUN_DIR/user_wants_taxonomy_k${k}.csv"
  cp "$RUN_DIR/user_wants_assignments.csv" "$RUN_DIR/user_wants_assignments_k${k}.csv"
done
```

Now the run directory has four `user_wants_taxonomy_k*.csv` files,
one per choice of k.

## Step 3 — inspect cluster sizes per k

```bash
.venv/bin/python -c "
import pandas as pd
for k in [10, 15, 20, 25]:
    df = pd.read_csv('$RUN_DIR/user_wants_taxonomy_k' + str(k) + '.csv')
    print(f'k={k}: {len(df)} clusters')
    sizes = df['size'].sort_values(ascending=False).tolist()
    print(f'  sizes: {sizes}')
    print(f'  smallest: {min(sizes)}, largest: {max(sizes)}, mean: {sum(sizes)/len(sizes):.1f}')
    print()
"
```

A typical pattern:

- **k=10**: largest clusters merge multiple intents; smallest cluster
  has ~10 tickets.
- **k=15**: closer to the natural split; smallest cluster ~5 tickets.
- **k=20**: starts breaking single intents into sub-clusters;
  smallest cluster ~3 tickets.
- **k=25**: sub-clusters of 2-3 tickets dominate; signal-to-noise drops.

The "right" k is where increasing k stops surfacing new structure and
starts producing tiny near-duplicate clusters.

## Step 4 — compute silhouette manually

Module 04 lesson 06 covered silhouette score. The Stage 4 outlier
script computes it automatically; the Stage 6 builder doesn't (yet).
Run it manually:

```bash
.venv/bin/python -c "
import pandas as pd
import numpy as np
from sklearn.metrics import silhouette_score
import sys
sys.path.insert(0, 'scripts')

# Reproduce embeddings
from build_user_wants_taxonomy import load_extractions, build_want_text, embed_texts
from pathlib import Path

run_dir = Path('$RUN_DIR')
extractions = load_extractions(run_dir)
extractions['_want_text'] = extractions.apply(build_want_text, axis=1)
extractions = extractions[extractions['_want_text'].str.len() > 0].reset_index(drop=True)
embeddings = embed_texts(extractions['_want_text'].tolist())

for k in [10, 15, 20, 25]:
    df = pd.read_csv(f'$RUN_DIR/user_wants_assignments_k{k}.csv')
    # Align on source_row in case order shifted
    merged = extractions[['source_row']].astype(str).merge(
        df[['source_row', 'want_id']].astype({'source_row': str}),
        on='source_row',
        how='inner',
    )
    if len(merged) != len(embeddings):
        print(f'k={k}: source_row mismatch ({len(merged)} vs {len(embeddings)}), skipping silhouette')
        continue
    labels = merged['want_id'].astype(int).to_numpy()
    score = silhouette_score(embeddings, labels, metric='cosine')
    print(f'k={k}: silhouette = {score:.4f}')
"
```

Silhouette interpretation (Module 04 lesson 06):

- **>0.5** — well-separated clusters.
- **0.25-0.5** — reasonable clustering.
- **<0.25** — clusters overlap heavily (typical for short text).

For 250 short LLM-extracted want strings, expect silhouette in the
0.05-0.15 range. Higher k tends to produce slightly higher silhouette
(small clusters are tighter), but with diminishing returns past
k=15-17.

## Step 5 — compare top clusters across k

Look at what the largest cluster looks like at different k:

```bash
.venv/bin/python -c "
import pandas as pd
for k in [10, 15, 20, 25]:
    df = pd.read_csv(f'$RUN_DIR/user_wants_taxonomy_k{k}.csv')
    biggest = df.sort_values('size', ascending=False).iloc[0]
    print(f'k={k} biggest cluster: {biggest[\"want_label\"]} (n={biggest[\"size\"]})')
    print(f'  jobs: {biggest[\"top_jobs\"]}')
    print(f'  example: {biggest[\"example_1\"][:140]}')
    print()
"
```

Watch how the biggest cluster's *example* changes:

- At k=10 it might combine "recover account" with "appeal a ban" — a
  single representative example might capture only one of those
  intents.
- At k=15-17 the biggest cluster narrows to "recover account access"
  pure.
- At k=25 the biggest cluster might be "recover account access"
  *narrowly* — but the second cluster is now another "recover account
  access" with subtly different wording.

## Step 6 — pick a k and label

Once you've decided on a k that feels right (say k=17), regenerate
the canonical files:

```bash
.venv/bin/python scripts/build_user_wants_taxonomy.py "$RUN_DIR" \
  --method kmeans --n-clusters 17
```

Run Gemma to label:

```bash
./scripts/label_user_wants.sh
```

The dashboard now shows the k=17 taxonomy. Look at it as a sanity
check.

## Step 7 — verify in the dashboard

```bash
pkill -f streamlit
./scripts/run_dashboard.sh
# Open: What users actually want
```

Compare the new bar chart of want counts to the previous one (mentally
or by screenshotting before re-running). At k=20 the bottom 5
clusters should look near-duplicate; at k=15 the top cluster might
absorb intents that should be separate.

## What you learned

- Cluster quality is a tradeoff between *granularity* (more clusters
  = finer detail) and *signal* (more clusters = noisier separation).
- Silhouette score gives a single number per k; rising silhouette
  with rising k can be misleading (small clusters are tight by
  definition).
- The "right" k is empirical: pick the smallest k that surfaces every
  intent the team cares about without producing 1-2 clusters that are
  obviously near-duplicates.
- Re-running clustering with different parameters is fast (~10
  seconds for 250 docs) so iteration is cheap.

## A general rule

For LLM-extracted text-cluster taxonomies on a few hundred rows:

- Start at `k = round(sqrt(n / 2))` — the same heuristic Stage 4 uses.
- Try `k-3`, `k`, `k+3`, `k+6`. Pick the smallest k that has every
  cluster carrying a distinct meaning.
- Re-label with Gemma and present.

For our 250 rows, `sqrt(125) ≈ 11`. The default fallback hit `k=17`
because we want extra granularity for the team's product roadmap. If
you were presenting to a board, `k=10` would be more digestible.

## Cleanup

Delete the comparison files when done:

```bash
rm "$RUN_DIR"/user_wants_taxonomy_k*.csv
rm "$RUN_DIR"/user_wants_assignments_k*.csv
```

Or leave them — they're small and document the decision.
