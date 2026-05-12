# 01 — CSV vs Parquet

You have `enriched_tickets.csv` on disk. It is 4.79 MB. It contains
6,728 rows and 60 columns. You write a four-line pandas script:

```python
import pandas as pd
df = pd.read_csv("outputs/option2_20260502_150055/enriched_tickets.csv")
df["context_depth_score"].mean()
```

The script takes about three seconds to run. Almost all of that time
is the read. Pandas is parsing 4.79 MB of UTF-8 text, splitting on
commas, inferring per-column types, allocating numpy arrays, and
copying the parsed values in. You then computed one number from one
column and threw away the other 59 columns of work the parser did.

That is the CSV problem. It is not a bug. It is a property of the
format. The pipeline ships a second copy of the same eight tables
in a format that does not have the property. Look at the head of
`export_analytical_store`:

```python
parquet_dir = out_dir / "parquet"
ensure_dir(parquet_dir)
for name, table in tables.items():
    table.to_parquet(parquet_dir / f"{name}.parquet", index=False)
```

That four-line loop in
[scripts/option2_pipeline.py:1791-1794](../../scripts/option2_pipeline.py)
writes the columnar twin of every CSV the pipeline emits. The
`enriched_tickets.parquet` file it produces is 1.42 MB — about 30%
of the CSV size — and pandas reads it in under 100 ms. Same data,
3.4x smaller, 30x faster to read, and types preserved on disk.

This lesson teaches you the trade-off: what CSV is good at, what it
is bad at, what Parquet is good at, what it is bad at, and the rule
the pipeline applies — write both, let the consumer pick.

## What CSV does well

CSV is plain text. That single property is the source of every
strength.

You can `cat enriched_tickets.csv | head -3` and see the data. You
can `git diff` two runs side by side and the diff makes sense:
"manager Albert's row count went from 2,247 to 2,251". You can open
the file in Excel, in VS Code, in `less`, in `vim`, in a notebook,
in a colleague's twenty-year-old SAS install, in awk. You can email
it. Every modern data tool reads CSV; many tools' default export
format is CSV.

CSV is also the simplest format with the lowest engineering surface
area. There is no compression algorithm to negotiate. There is no
schema header. There is no library version mismatch — the format
hasn't changed since 1972 and the rough RFC since 2005. If you write
a CSV today and re-read it in 2046, it will still parse.

The pipeline writes CSV first because of these properties. Look at
the tail of `run`:

```python
for name, table in tables.items():
    table.to_csv(out_dir / f"{name}.csv", index=False)
export_excel(out_dir, tables)
export_analytical_store(out_dir, tables)
```

That ordering in
[scripts/option2_pipeline.py:1932-1935](../../scripts/option2_pipeline.py)
is deliberate. CSV first, Excel second, analytical store (Parquet
plus DuckDB) third. CSV is the source of truth because if any of the
other three writes fail — Excel can't be installed, Parquet engine
is missing, DuckDB has a permission error — you still have the data.
The
[insight_layer.write_outputs](../../scripts/insight_layer.py)
function repeats this priority: it writes all CSVs unconditionally,
then wraps the DuckDB call in `try/except Exception` because, as the
docstring says explicitly,
"CSV is the source of truth; SQL is a convenience"
([scripts/insight_layer.py:1186-1188](../../scripts/insight_layer.py)).

`index=False` in `to_csv` is also load-bearing. Without it pandas
writes the integer row index as the first column, and re-reading the
file produces a phantom `Unnamed: 0` column on every consumer's
side. Always pass `index=False` unless your index has semantic
meaning.

## What CSV does badly

The strengths cost you four things: speed, compactness, type safety,
and column projection.

**Speed.** A CSV reader has to do work proportional to the entire
file size before it can hand you a single column. Parse comma. Detect
quote. Handle escape. Decode UTF-8. Resolve `NA` strings. Infer types
on the fly. The work is per-byte, not per-row, and it scales with the
total uncompressed size.

**Compactness.** A 64-bit integer occupies 8 bytes in memory. The
same integer rendered as text — say `"6728"` followed by a comma —
is 5 bytes. Sometimes text wins on a single value. But a column of
7-digit integers averages about 8 bytes per value as text, and
floating-point columns explode: `0.18152258020533928` is 19 bytes
of text for an 8-byte double. Across 6,728 rows and 60 columns the
arithmetic adds up; `enriched_tickets.csv` weighs 4.79 MB.

**Type safety.** CSV has no types. Every cell is a string. The reader
guesses. Pandas guesses well most of the time, but the guesses are
file-local: a column that is `BIGINT` in one run can come back as
`object` in the next if a single row contains the string `"NA"`. A
column that is `BOOLEAN` in DuckDB serialises to `True` / `False`
in CSV and re-reads as `bool` only because pandas has a rule for
those exact strings. Round-tripping types through CSV is unsafe.

**Column projection.** If you want one column out of 60, you still
read all 60. The bytes for the other 59 are interleaved with the bytes
for the one you want, so the reader cannot skip them. Tools like
`pyarrow.csv` can stream and discard, but they still pay the parse
cost.

These four costs do not matter at small scale. At a few hundred rows,
CSV is fine. At 6,728 rows and 60 columns they are visible. At a few
million rows they are unbearable.

## What Parquet is

Parquet is a binary, columnar, compressed, self-describing file
format. Each of those four words is doing real work.

**Binary.** No text parsing. The bytes on disk are already in a layout
the reader can copy into a numpy array.

**Columnar.** Values for one column are stored contiguously, separate
from the values for other columns. If you want `context_depth_score`
out of 60 columns, the reader seeks to the column's offset, reads its
bytes, and ignores everything else. You pay only for what you read.

**Compressed.** Parquet writes each column with a per-column codec —
Snappy by default, LZ4 or ZSTD on demand. Columnar data compresses
exceptionally well because adjacent values in one column are usually
similar (most rows have the same `nlp_backend`, most rows are within
a small range of `char_count`, etc.). The 4.79 MB CSV becomes a
1.42 MB Parquet file. That is a real, measured compression ratio on
your data.

**Self-describing.** Each Parquet file begins with a footer
describing every column's type, name, encoding, and statistics
(min, max, null count, sometimes histogram). The reader knows the
schema before it reads any rows. There is no type inference. There
are no surprises.

That last property is the deepest difference. CSV stores values.
Parquet stores values *and* their schema, on the same disk write.
A round-trip through Parquet preserves types — `BIGINT` stays
`BIGINT`, `BOOLEAN` stays `BOOLEAN`, `TIMESTAMP` stays `TIMESTAMP` —
without requiring a sidecar schema file or a `dtype=` argument on
read.

## The pipeline's choice

The pipeline writes both. Look at the docstring at the top of
`export_analytical_store`:

```python
def export_analytical_store(out_dir: Path, tables: dict[str, pd.DataFrame]) -> None:
    """Write Parquet copies of every table and a DuckDB database with all of them.

    Two analytical stores, complementary:

    * **Parquet** files (``parquet/<name>.parquet``) — columnar, compressed,
      ~10x faster than CSV for large reads, and supported by every modern
      data tool (pandas, polars, R/arrow, Spark, DuckDB).
    * **DuckDB** database (``analysis.duckdb``) — a single-file embedded SQL
      database. Lets analysts run SQL queries across tables with joins and
      window functions without spinning up Postgres. ...
    """
```

That comment in
[scripts/option2_pipeline.py:1754-1789](../../scripts/option2_pipeline.py)
is the design rationale. Parquet is a portable file format —
language-agnostic, framework-agnostic. DuckDB is a query engine that
also happens to read Parquet. CSV is the lingua franca. Some
analysts open the Parquet directly in pandas. Some join three tables
in DuckDB SQL. Some open the CSV in Excel. The pipeline writes all
three and lets the consumer choose.

The cost of writing all three is small. CSV writes are fast (text
formatting is cheap; only the read side is slow). Parquet writes are
fast because pandas hands the columns directly to `pyarrow` without
re-encoding. DuckDB writes are fast because each `CREATE OR REPLACE
TABLE ... AS SELECT * FROM _tmp_table` is a memory copy (lesson 02
covers the `register` / `unregister` view pattern that makes this
zero-copy). The whole `export_analytical_store` call against the
6,728-row dataset finishes in well under a second.

The cost of writing only one of the three is high. CSV-only locks
non-pandas consumers into a slow read every time. Parquet-only
breaks Excel users and `git diff`. DuckDB-only forces every
downstream tool to grow a DuckDB driver. Writing all three is the
cheap, ergonomic answer.

## When to use which

**Reach for CSV when:**

- The output is human-readable. A one-line audit log, a config file,
  a small status table, a thing you want to `git diff` between runs.
- The consumer is unknown or unsophisticated. "Send the data to a
  stakeholder" almost always means CSV.
- Reproducibility across decades matters. CSV is the only format on
  this list with a credible 50-year readability story.

**Reach for Parquet when:**

- The data is more than a few thousand rows.
- The consumer is pandas, polars, R-arrow, Spark, DuckDB, BigQuery,
  Athena, or any other modern columnar tool.
- Types matter. Round-tripping `BOOLEAN` and `TIMESTAMP` through CSV
  is a known pain point; Parquet just works.
- You read a small subset of columns from a wide table. The 60-column
  `enriched_tickets` is a textbook case: most consumers want 5-10
  columns; Parquet's columnar layout means you pay for those 5-10
  alone.

**Reach for both when:**

- You don't know who the consumer is yet. The pipeline does this. So
  do most data lakes. The CSV is the dumb-tool fallback; the Parquet
  is the smart-tool default.

The pipeline's `export_analytical_store` is "both". So is
[scripts/insight_layer.py:1190-1206](../../scripts/insight_layer.py)
— it writes CSVs unconditionally, then attempts an Excel write, then
attempts a DuckDB write. If you want to extend the pipeline with new
analytical tables, follow the same pattern: add the DataFrame to the
`tables` dict, and the existing CSV / Parquet / DuckDB code paths
pick it up automatically.

## Try it

Open a Python REPL in the project root.

```python
import time
import pandas as pd
from pathlib import Path

run = Path("outputs/option2_20260502_150055")

t0 = time.perf_counter()
df_csv = pd.read_csv(run / "enriched_tickets.csv")
t_csv = time.perf_counter() - t0

t0 = time.perf_counter()
df_pq = pd.read_parquet(run / "parquet" / "enriched_tickets.parquet")
t_pq = time.perf_counter() - t0

print(f"CSV:     {t_csv*1000:7.1f} ms, {len(df_csv):,} rows, "
      f"{(run/'enriched_tickets.csv').stat().st_size/1e6:5.2f} MB on disk")
print(f"Parquet: {t_pq*1000:7.1f} ms, {len(df_pq):,} rows, "
      f"{(run/'parquet'/'enriched_tickets.parquet').stat().st_size/1e6:5.2f} MB on disk")
print(f"Speedup: {t_csv/t_pq:.1f}x  /  Compression: {(run/'enriched_tickets.csv').stat().st_size / (run/'parquet'/'enriched_tickets.parquet').stat().st_size:.2f}x")
```

You should see something like 1.4 MB Parquet vs 4.79 MB CSV (a 3.4x
compression ratio) and the Parquet read at least 5x — often 20x or
more — faster than the CSV read. Now repeat with column projection:

```python
t0 = time.perf_counter()
just_score = pd.read_csv(run / "enriched_tickets.csv",
                         usecols=["context_depth_score"])
t_csv_one = time.perf_counter() - t0

t0 = time.perf_counter()
just_score_pq = pd.read_parquet(run / "parquet" / "enriched_tickets.parquet",
                                columns=["context_depth_score"])
t_pq_one = time.perf_counter() - t0

print(f"CSV  one column: {t_csv_one*1000:6.1f} ms")
print(f"Pq   one column: {t_pq_one*1000:6.1f} ms")
```

The Parquet version drops in proportion to the column you asked for.
The CSV version barely moves — you read the whole file regardless,
then threw away 59 columns. That is the columnar advantage in one
print statement.

Finally, prove the type-preservation claim:

```python
print(df_csv.dtypes["is_resolved"], df_pq.dtypes["is_resolved"])
print(df_csv.dtypes["date"], df_pq.dtypes["date"])
```

The CSV `is_resolved` column round-trips as `bool` only because
pandas has a rule for the literal strings `"True"` / `"False"`; the
CSV `date` column comes back as `object` (string) because there is
no rule to recognise it as a timestamp. The Parquet versions come
back as `bool` and `datetime64[ns]` because Parquet wrote the types
to disk alongside the values.
