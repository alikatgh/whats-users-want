# 02 — DuckDB basics

You have eight CSV files in your run directory. You want to answer a
question that touches three of them at once: "Which managers in the
top quartile of `avg_context_score` also handle a high share of
`clear_name_or_get_fairness` tickets?" That is a join between
`manager_context_quality` and `enriched_tickets`, with a `WHERE
primary_desire = 'clear_name_or_get_fairness'` filter. The pandas
answer is three reads, two merges, a groupby, a quantile filter, and
twenty lines of code.

The SQL answer is three lines:

```sql
SELECT m.manager, m.avg_context_score, COUNT(*) AS fairness_tickets
FROM manager_context_quality m
JOIN enriched_tickets t ON t.manager = m.manager
WHERE t.primary_desire = 'clear_name_or_get_fairness'
GROUP BY m.manager, m.avg_context_score
ORDER BY m.avg_context_score DESC;
```

If you write three lines of SQL and run them on a server, you have a
deployment. If you write three lines of SQL and run them on a CSV
file, you have nothing — pandas doesn't speak SQL natively. DuckDB
is the missing piece. It is a SQL engine that runs *inside your
process*, with no server, no daemon, no port, no cluster, no admin.
It opens a single file. It speaks standard SQL. It reads Parquet,
CSV, and its own native format directly. It hands results back as
pandas DataFrames.

The pipeline writes one DuckDB file per run. Look at
`export_analytical_store`:

```python
con = duckdb.connect(str(out_dir / "analysis.duckdb"))
try:
    for name, table in tables.items():
        safe = re.sub(r"[^A-Za-z0-9_]", "_", name).lower()
        con.register("_tmp_table", table)
        con.execute(f'CREATE OR REPLACE TABLE "{safe}" AS SELECT * FROM _tmp_table')
        con.unregister("_tmp_table")
    con.execute(
        """
        CREATE OR REPLACE VIEW manager_context_rank AS
        SELECT *
        FROM manager_context_quality
        ORDER BY avg_context_score DESC, tickets DESC
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW high_risk_user_needs AS
        SELECT desire, tickets, unresolved_share, avg_context_score
        FROM desire_summary
        WHERE unresolved_share >= 0.20 OR avg_context_score >= 24
        ORDER BY unresolved_share DESC, tickets DESC
        """
    )
finally:
    con.close()
```

That block in
[scripts/option2_pipeline.py:1802-1827](../../scripts/option2_pipeline.py)
is the full DuckDB setup for one run. By the time it returns, the run
directory has one file called `analysis.duckdb` containing eight
real tables and two views, ready for any SQL client. The same file
gets eleven more tables added by
[scripts/insight_layer.py:1196-1206](../../scripts/insight_layer.py)
later in the pipeline, using the same idiom. After both stages run,
`analysis.duckdb` weighs about 9.45 MB and contains 21 named objects.

This lesson teaches the four operations in that block:
`duckdb.connect`, `con.register`, `CREATE OR REPLACE TABLE` /
`VIEW`, and `con.unregister` / `con.close`. By the end you will be
able to read and write a DuckDB file from any Python REPL, and you
will know why DuckDB beats SQLite for this kind of work.

## `duckdb.connect`

```python
con = duckdb.connect(str(out_dir / "analysis.duckdb"))
```

That's the entire setup. No service to start. No password. No port.
No connection string. The argument is a filesystem path.

If the file exists, DuckDB opens it. If the file doesn't exist,
DuckDB creates it. If you pass `":memory:"` (or no argument at all),
DuckDB creates a transient in-memory database that disappears when
the process exits — useful for tests and ad-hoc analysis. The
fallback in
[pages/07_Find_a_Ticket.py:122-126](../../scripts/dashboard/pages/07_Find_a_Ticket.py)
uses exactly this trick:

```python
con = duckdb.connect()
con.execute(
    f"CREATE VIEW enriched_tickets AS SELECT * FROM read_csv_auto('{Path(run_dir_str) / 'enriched_tickets.csv'}', HEADER=True)"
)
```

If `analysis.duckdb` is missing for some reason, the page spins up
an in-memory database, creates a *view* over the CSV — DuckDB reads
the CSV directly, no import step — and proceeds. The dashboard never
notices. That is what "in-process SQL on local files" lets you do.

A `duckdb.DuckDBPyConnection` is a regular Python object. You hold
it in a variable. You pass it around. You close it with
`con.close()`. The pipeline wraps the work in `try / finally` to
guarantee the close runs even if a query raises:

```python
try:
    for name, table in tables.items():
        ...
finally:
    con.close()
```

The docstring in
[scripts/option2_pipeline.py:1786-1787](../../scripts/option2_pipeline.py)
calls this out explicitly: "The `try/finally` guarantees `con.close()`
runs even if a query raises — proper resource hygiene for database
handles." DuckDB will release the file lock when the process exits,
so a missed `close` is rarely catastrophic, but a leaked open handle
on a database file is the kind of bug that causes Windows users
problems with anti-virus scanners and concurrent runs to fail. Close
your handles.

## `con.register` and the zero-copy view

You have a pandas DataFrame in memory. You want it as a DuckDB
table. The naive way is to write the DataFrame to a Parquet file,
then `CREATE TABLE x AS SELECT * FROM 'x.parquet'`. That works but
it does two extra copies (DataFrame to disk; disk to DuckDB).

`con.register` does it in one step with no copy at all:

```python
con.register("_tmp_table", table)
con.execute(f'CREATE OR REPLACE TABLE "{safe}" AS SELECT * FROM _tmp_table')
con.unregister("_tmp_table")
```

`register` exposes the DataFrame to DuckDB as a *temporary view*.
DuckDB does not allocate. It does not copy. It holds a reference to
the underlying numpy arrays and reads them directly when a query
asks. The
[scripts/option2_pipeline.py:1778-1783](../../scripts/option2_pipeline.py)
docstring puts it cleanly: "`con.register('_tmp_table', table)`
creates a temporary view of the pandas DataFrame inside DuckDB
without copying the data — DuckDB reads the underlying numpy arrays
directly. Then `CREATE OR REPLACE TABLE ... AS SELECT * FROM
_tmp_table` copies the data into a real DuckDB table; we
`unregister` afterwards to keep the namespace clean."

The reason to materialise into a real table — instead of just leaving
the registered view — is persistence. A registered view exists only
inside the current `DuckDBPyConnection`. As soon as you close `con`,
the view is gone. A real table written by `CREATE OR REPLACE TABLE`
is stored inside the `.duckdb` file on disk and survives the close.
The pipeline wants the file to be openable from a fresh process
(the dashboard, a teammate's notebook, a future analyst), so it
materialises every table.

`con.unregister("_tmp_table")` removes the temporary view *before*
the next iteration. Without it the namespace would accumulate views
from previous loop bodies, and although `register("_tmp_table",
new_table)` would overwrite the previous view, the explicit
`unregister` keeps the surface area clean and the docstring honest.

## `CREATE OR REPLACE TABLE` and `CREATE OR REPLACE VIEW`

Standard SQL says `CREATE TABLE` errors if a table by that name
already exists. That is correct, conservative behaviour for a
production database; you don't want to drop a customer-orders table
because you typo'd a migration. For an analytical export, it is the
wrong default. The pipeline runs every time you run the pipeline.
The `analysis.duckdb` file from the previous run already has tables
in it. You want the new run to overwrite, not error.

DuckDB extends standard SQL with `CREATE OR REPLACE`:

```python
con.execute(f'CREATE OR REPLACE TABLE "{safe}" AS SELECT * FROM _tmp_table')
```

That is "create the table; if it exists, drop it first". It is
idempotent: running the pipeline twice into the same file produces
the same result as running it once. The
[scripts/option2_pipeline.py:1788-1789](../../scripts/option2_pipeline.py)
docstring spells out why: "`CREATE OR REPLACE` makes the export
idempotent: running the pipeline a second time into the same
database is safe."

`CREATE OR REPLACE VIEW` works the same way for views. The
`manager_context_rank` and `high_risk_user_needs` views in the
pipeline are stored queries, not stored data — DuckDB re-runs the
underlying `SELECT` whenever the view is queried. They cost nothing
to write and let analysts say "give me the highest-ranked managers"
without retyping the `ORDER BY`. After the pipeline runs you can
verify them:

```python
con.execute("SELECT * FROM high_risk_user_needs LIMIT 3").fetchall()
# [('clear_name_or_get_fairness', 1603, 0.3157, 25.69),
#  ('protect_from_abuse_or_scam', 384, 0.2891, 29.04),
#  ('gain_status_or_privileges', 865, 0.2659, 23.61)]
```

Those three rows are the first three desire categories where the
unresolved share is above 20% or the average context score is above
24, sorted by unresolved share descending. They came from
`desire_summary` (a table) by way of the view definition in
[scripts/option2_pipeline.py:1817-1825](../../scripts/option2_pipeline.py).

## The same idiom, used twice

The pipeline uses `register` / `CREATE OR REPLACE TABLE` /
`unregister` once for the eight pipeline tables. Then
`scripts/insight_layer.py` uses the same idiom for the eleven
insight-layer tables on top:

```python
import duckdb
con = duckdb.connect(str(run_dir / "analysis.duckdb"))
for name, table in tables.items():
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name).lower()
    con.register("_tmp_insight", table)
    con.execute(f'CREATE OR REPLACE TABLE "{safe}" AS SELECT * FROM _tmp_insight')
    con.unregister("_tmp_insight")
con.close()
```

That block in
[scripts/insight_layer.py:1197-1204](../../scripts/insight_layer.py)
is the same five operations, with one difference: the temp-view name
is `_tmp_insight` instead of `_tmp_table`. There is no functional
reason for the rename — it is a defence against running both stages
in the same process and confusing the namespace. (Both stages
`unregister` before the next iteration, so a name collision is
avoided either way; the rename is belt-and-braces.)

The second stage opens the *same* `analysis.duckdb` file and adds
its tables. The pipeline tables and the insight tables coexist in
one file. By the time both stages finish, the schema browser in
[pages/10_Run_SQL_Queries.py](../../scripts/dashboard/pages/10_Run_SQL_Queries.py)
will show 21 named objects: 19 BASE TABLE entries (8 from the
pipeline + 11 from the insight layer) and 2 VIEW entries
(`manager_context_rank`, `high_risk_user_needs`).

## Why DuckDB and not SQLite

You may ask: SQLite already exists, ships with Python, has a single
file, no server. Why DuckDB?

Because SQLite is a row-oriented OLTP database designed for
transactional workloads — many small reads and writes, one row at a
time, with rollbacks and concurrency. DuckDB is a column-oriented
OLAP database designed for analytical workloads — large scans, joins,
aggregations, group-bys, window functions over millions of rows.

The differences show up immediately:

- **Storage layout.** SQLite stores rows. DuckDB stores columns. A
  query that reads three out of 60 columns reads 5% of the file in
  DuckDB; in SQLite it reads close to 100%.
- **SQL surface.** DuckDB supports window functions, CTEs, lateral
  joins, the SQL standard `INTERVAL` type, list types, struct types,
  `QUALIFY`, `PIVOT` / `UNPIVOT`, `SAMPLE`, regex functions. SQLite
  has subset of these.
- **Pandas integration.** DuckDB's `con.register(name, df)` is a
  zero-copy view over a numpy-backed DataFrame. SQLite has no such
  thing — you `df.to_sql(name, con)` which inserts row by row.
- **CSV / Parquet / JSON readers.** DuckDB can `SELECT * FROM
  read_csv_auto('file.csv')` and `SELECT * FROM 'file.parquet'`
  directly, without an import step. SQLite has no built-in for
  either.

For "the inbox is 6,728 rows, please join three tables and group by
manager", DuckDB is the right tool. For "store a thousand IoT
heartbeats per second from a hundred devices and survive a crash
mid-write", you'd want SQLite. The pipeline is decidedly the former
case.

## Try it

Open a Python REPL.

```python
import duckdb
from pathlib import Path

run = Path("outputs/option2_20260502_150055")
con = duckdb.connect(str(run / "analysis.duckdb"), read_only=True)

# 1. Confirm the file is real and contains the expected objects.
tables = con.execute(
    "SELECT table_name, table_type FROM information_schema.tables ORDER BY 1"
).fetchall()
for name, kind in tables:
    print(f"{kind:12} {name}")
```

You should see 21 entries: 19 `BASE TABLE` rows and 2 `VIEW` rows
(`high_risk_user_needs`, `manager_context_rank`). Now run the
three-line join from the start of this lesson:

```python
con.execute("""
    SELECT m.manager, m.avg_context_score, COUNT(*) AS fairness_tickets
    FROM manager_context_quality m
    JOIN enriched_tickets t ON t.manager = m.manager
    WHERE t.primary_desire = 'clear_name_or_get_fairness'
    GROUP BY m.manager, m.avg_context_score
    ORDER BY m.avg_context_score DESC
""").fetchdf()
```

`.fetchdf()` returns a pandas DataFrame. (The dashboard pages use
this method directly; see
[pages/10_Run_SQL_Queries.py:204](../../scripts/dashboard/pages/10_Run_SQL_Queries.py).)

Now build a fresh in-memory DuckDB and try the zero-copy register
trick yourself:

```python
import pandas as pd

mem = duckdb.connect()
df = pd.DataFrame({"a": range(5), "b": list("vwxyz")})
mem.register("my_view", df)
print(mem.execute("SELECT * FROM my_view WHERE a > 2").fetchdf())
mem.execute("CREATE TABLE my_table AS SELECT * FROM my_view")
mem.unregister("my_view")
print(mem.execute("SELECT * FROM my_table").fetchdf())
mem.close()
```

The first SELECT reads `df` directly — no import step, no copy. The
`CREATE TABLE` materialises a real DuckDB table. After
`unregister` the name `my_view` is gone but `my_table` remains until
`mem.close()` (and would persist on disk if you'd opened a file
instead of `:memory:`). That is the entire pipeline pattern in five
lines.
