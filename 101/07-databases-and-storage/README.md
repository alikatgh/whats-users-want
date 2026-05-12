# Module 07 — Databases and Storage

By the end of Module 06 you have a directory full of CSV files and a
JSONL of LLM extractions. Open one of them in your editor:
`enriched_tickets.csv` is 4.79 MB across 6,728 rows and 60 columns. The
file opens, slowly. You scroll. You find the column you want by counting
commas in the header row. You write a pandas script. The pandas script
takes three seconds to read the CSV. That three seconds happens every
time you ask a question.

You are now in the regime where CSV is the wrong format.

The pipeline knows this. Look at the tail of `run` in
[scripts/option2_pipeline.py:1922-1935](../../scripts/option2_pipeline.py).
After it builds the eight analytical tables it calls
`export_excel(out_dir, tables)` and then
`export_analytical_store(out_dir, tables)`. The second call writes two
new artefacts the previous modules never touched: a `parquet/`
subdirectory with one `.parquet` file per table, and a single
`analysis.duckdb` file in the run root. Same data, three formats: CSV
for `git diff`, Parquet for fast columnar reads, DuckDB for SQL.

The dashboard pages in `scripts/dashboard/pages/` then build on the
DuckDB file. Page 07
([scripts/dashboard/pages/07_Find_a_Ticket.py](../../scripts/dashboard/pages/07_Find_a_Ticket.py))
is a search engine over `enriched_tickets`; page 10
([scripts/dashboard/pages/10_Run_SQL_Queries.py](../../scripts/dashboard/pages/10_Run_SQL_Queries.py))
is a tiny SQL IDE. Both open the same `analysis.duckdb` file in
read-only mode and push every filter through parameterised SQL with
`?` placeholders. There is no server to install. There is no schema
migration. There is one file on disk.

This module teaches the storage layer underneath those pages. By the
end you will know when a CSV stops paying its way and what to reach
for next, how DuckDB makes a single-file embedded SQL database
actually pleasant to use, how the standard `information_schema` views
let your dashboard browse its own structure without coupling to a
specific engine, and how `?` placeholders keep user input out of your
SQL string while making the IN-clause case work.

## Prerequisites

- [Module 01 — Python Foundations](../01-python-foundations/README.md).
  You need `pathlib.Path`, `try/except/finally`, `with` blocks for
  resource cleanup, and the `dict[str, DataFrame]` pattern. The
  `try/finally` guard around `con.close()` in
  [export_analytical_store](../../scripts/option2_pipeline.py) is the
  same pattern as `with open(path) as f:` — you just have to write it
  out by hand because DuckDB connections aren't context managers in
  the same way.
- [Module 02 — Data with pandas](../02-data-with-pandas/README.md).
  You need `df.to_csv`, `df.to_parquet`, and the idea that a DataFrame
  is a typed in-memory table. The `tables` dict in
  [scripts/option2_pipeline.py:1922-1933](../../scripts/option2_pipeline.py)
  is the single source of truth for "what's in this run"; every
  storage backend in this module consumes the same dict.
- [Module 03 — Text and NLP](../03-text-and-nlp/README.md). You need
  to remember that `question` is the cleaned ticket text and
  `question_flat` is its newline-stripped one-line version, because
  the case-insensitive search in
  [pages/07_Find_a_Ticket.py:210-212](../../scripts/dashboard/pages/07_Find_a_Ticket.py)
  pushes `LOWER("question") LIKE ?` to DuckDB.
- [Module 04 — Dimensionality and Clustering](../04-dimensionality-and-clustering/README.md).
  You need the clustering output schema — `cluster_id`,
  `cluster_probability`, `x`, `y`, `nlp_backend` — because that's the
  block of columns merged onto `enriched_tickets` in
  [scripts/option2_pipeline.py:1916-1920](../../scripts/option2_pipeline.py)
  before the table goes to the analytical store.
- [Module 05 — Statistics](../05-statistics/README.md). You need the
  outputs `manager_context_residuals` and `adjusted_manager_context_model`
  to exist as columns in DuckDB; the schema browser in lesson 03 will
  enumerate them.
- [Module 06 — LLMs and Prompts](../06-llms-and-prompts/README.md).
  Not strictly required for the storage layer, but the LLM
  extractions are loaded into the same `analysis.duckdb` workbook by
  [scripts/insight_layer.py:1196-1206](../../scripts/insight_layer.py),
  using the exact same `con.register / CREATE OR REPLACE TABLE /
  con.unregister` pattern.
- The `outputs/option2_20260502_150055/` run on disk. Lessons load
  `enriched_tickets.csv` (4.79 MB, 6,728 rows),
  `parquet/enriched_tickets.parquet` (1.42 MB, the same 6,728 rows
  compressed), and `analysis.duckdb` (9.45 MB, all 21 tables and views
  in one file).
- A working `duckdb` Python install. `pip install duckdb` is the only
  new dependency in this module. There is no service to start and no
  port to open.

## What you will be able to do after this module

- Pick the right format for the right job. CSV for human-readable
  diffs and "send this to a stakeholder" workflows; Parquet for
  pandas / polars / R-arrow consumers who want columnar reads;
  DuckDB for SQL across joined tables. Cite the
  [export_analytical_store](../../scripts/option2_pipeline.py)
  docstring in
  [scripts/option2_pipeline.py:1754-1789](../../scripts/option2_pipeline.py)
  in your defence.
- Open `analysis.duckdb` from a Python REPL and reproduce the 21
  tables and views the pipeline writes
  ([scripts/option2_pipeline.py:1802-1825](../../scripts/option2_pipeline.py)
  for the eight pipeline tables plus two views, and
  [scripts/insight_layer.py:1196-1206](../../scripts/insight_layer.py)
  for the eleven insight-layer tables on top).
- Read and write the `con.register / CREATE OR REPLACE TABLE /
  con.unregister` idiom. Explain why `register` is a zero-copy view,
  why we follow it with `CREATE OR REPLACE TABLE` to materialise a
  real table, and why the `try/finally` block around `con.close()` is
  not optional.
- Walk the schema browser in
  [pages/10_Run_SQL_Queries.py:128-137](../../scripts/dashboard/pages/10_Run_SQL_Queries.py).
  Explain why
  `SELECT table_name, table_type FROM information_schema.tables`
  works identically against DuckDB, Postgres, MySQL, SQL Server, and
  most other modern engines, and why that portability matters even
  when you have no plans to migrate.
- Trace the parameterised `?` flow in
  [pages/07_Find_a_Ticket.py:176-212](../../scripts/dashboard/pages/07_Find_a_Ticket.py).
  Explain how `in_clause(col, values)` builds
  `"col IN (?, ?, ?)"` and extends `params`, why this is the only
  injection-safe way to build a variable-length IN clause, and why
  the case-insensitive text search uses `LOWER("question") LIKE ?`
  with `f"%{text_query.lower()}%"`.
- Open a DuckDB connection in `read_only=True` and explain why the
  SQL console in
  [pages/10_Run_SQL_Queries.py:118](../../scripts/dashboard/pages/10_Run_SQL_Queries.py)
  insists on it. The flag is a safety belt, not a security boundary,
  but it converts a typo like `DELETE FROM enriched_tickets` from a
  data-loss event into an error message.

## Lessons

| # | Lesson | What it covers |
|---|---|---|
| 01 | [CSV vs Parquet](01-csv-vs-parquet.md) | CSV (human-readable) vs Parquet (columnar, typed, compressed). The 4.79 MB → 1.42 MB compression. The `to_parquet` loop in `option2_pipeline.py`. |
| 02 | [DuckDB basics](02-duckdb-basics.md) | In-process SQL on local files. `duckdb.connect`. The `register / CREATE OR REPLACE / unregister` pattern. Why DuckDB beats SQLite for analytics. |
| 03 | [Information schema](03-information-schema-and-introspection.md) | `information_schema.tables` and `.columns`. The schema browser in `pages/10_Run_SQL_Queries.py`. Why standard SQL info schema makes the dashboard portable. |
| 04 | [Parameterized queries](04-parameterized-queries-and-injection.md) | `?` placeholders. The `in_clause(col, values)` helper. Why never f-string user input. `read_only=True` as a safety belt. `LOWER(col) LIKE ?`. |

Each lesson is 1500-2500 words and ends with a runnable "Try it" block
against `outputs/option2_20260502_150055/`.

## What's next

- [Module 08 — Visualization](../08-visualization/README.md) renders chart
  series straight from SQL queries against `analysis.duckdb`.
- [Module 09 — Streamlit Dashboards](../09-streamlit-dashboards/README.md)
  shows the DuckDB connection caching pattern (`@st.cache_resource`) in use.
- [Module 10 — Pipeline Design](../10-pipeline-design/README.md) zooms back
  out to the timestamped output directory and the `tables` dict.
