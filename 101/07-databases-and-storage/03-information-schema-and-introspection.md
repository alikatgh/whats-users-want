# 03 — information_schema and introspection

You open a DuckDB file you didn't create. There are tables in it. You
don't remember the names. You don't remember the columns. You don't
have the pipeline source code in front of you. What do you do?

The wrong answer is `con.execute("SHOW TABLES")`. That works in
DuckDB. It also works in MySQL. It does *not* work in Postgres
(`\dt` instead, in the psql client only). It does not work in SQL
Server. It does not work in BigQuery. Every database engine has its
own catalogue dialect, and every catalogue dialect is slightly
different.

The right answer is `information_schema`. It is the SQL standard's
mandatory introspection layer: a fixed set of read-only views with
fixed names and fixed columns that every standards-compliant engine
must expose. The query

```sql
SELECT table_name, table_type FROM information_schema.tables ORDER BY 1
```

returns the same shape of result on DuckDB, Postgres, MySQL, MariaDB,
SQL Server, Snowflake, and BigQuery. Same column names, same data
types, same semantics. Write the query once, run it everywhere.

The dashboard's SQL console uses exactly this. Look at
[pages/10_Run_SQL_Queries.py:123-126](../../scripts/dashboard/pages/10_Run_SQL_Queries.py):

```python
tables = con.execute(
    "SELECT table_name, table_type FROM information_schema.tables ORDER BY 1"
).fetchdf()
st.caption(f"`{db_path.name}` has {len(tables)} tables and views.")
```

That is two lines of standards-compliant SQL and one line of
Streamlit. The page tells the user `analysis.duckdb has 21 tables
and views.` and feeds the table names into a `selectbox` for
inspection. The same code pointed at a Postgres database — change
`duckdb.connect(path)` to `psycopg2.connect(dsn)` and that's it —
would print `myschema has 412 tables and views.` and work
identically.

This lesson teaches the two `information_schema` views the dashboard
actually uses (`tables` and `columns`), the auxiliary
`SELECT * FROM "x" LIMIT 10` sample-row trick for showing data, and
why portability matters even when you have no plan to migrate.

## `information_schema.tables`

The `tables` view enumerates every table and view in the current
database. Its columns are standardised; the ones you care about are:

- `table_catalog` — the database name. In DuckDB, this matches the
  filename (without extension) of your `.duckdb` file.
- `table_schema` — the schema name. DuckDB defaults to `main`.
- `table_name` — the table or view name.
- `table_type` — one of `BASE TABLE`, `VIEW`, `LOCAL TEMPORARY`, plus
  a few engine-specific types. DuckDB uses `BASE TABLE` for
  `CREATE TABLE` outputs and `VIEW` for `CREATE VIEW`.

Run that two-line query against `outputs/option2_20260502_150055/analysis.duckdb`
and you get 21 rows, exactly as the dashboard caption says. The
order is `ORDER BY 1` — alphabetical by `table_name`. The first
table is `adjusted_manager_context_model`, the last is
`semantic_clusters`. Two of the 21 rows have `table_type = 'VIEW'`:
`high_risk_user_needs` and `manager_context_rank`. Both views came
from the `CREATE OR REPLACE VIEW` calls in
[scripts/option2_pipeline.py:1809-1825](../../scripts/option2_pipeline.py)
that you read in lesson 02.

The other nineteen are real tables. Eight of them came from the
main pipeline's `tables` dict (`enriched_tickets`,
`manager_context_quality`, `adjusted_manager_context_model`,
`desire_summary`, `semantic_clusters`,
`semantic_cluster_assignments`, `high_context_examples`,
`network_nodes`). Eleven came from the insight layer
(`opportunity_backlog`, `emerging_topics`, `repeat_user_personas`,
`refined_opportunity_backlog`, `outlier_subtopics`,
`outlier_subtopic_assignments`, `outlier_split_metrics`,
`issue_evidence_gaps`, `manager_evidence_coaching`,
`manager_context_residuals`, `context_value_model`). All written
into the same `analysis.duckdb` file by the
[scripts/insight_layer.py:1196-1204](../../scripts/insight_layer.py)
loop you saw in lesson 02.

You did not have to look at any of those scripts to get the list.
`information_schema.tables` told you, from a database you might
never have built. That is the point.

## `information_schema.columns`

The next question, once you have the table names, is "what columns
does this table have?" The standard answer is
`information_schema.columns`. Its columns include:

- `table_name` — which table this column belongs to.
- `column_name` — the column's name.
- `ordinal_position` — the column's index in the table's CREATE
  TABLE definition, starting from 1. This is what the schema
  browser uses to show columns in their natural order rather than
  alphabetically.
- `data_type` — the column's SQL type as a string: `VARCHAR`,
  `BIGINT`, `BOOLEAN`, `TIMESTAMP`, etc. These are SQL standard
  type names; engines that have native non-standard types map them
  here.
- `is_nullable` — `'YES'` or `'NO'`.
- `column_default` — default value as a SQL expression, or null.

The schema browser in
[pages/10_Run_SQL_Queries.py:128-137](../../scripts/dashboard/pages/10_Run_SQL_Queries.py)
uses three of these columns and parameterises the table-name
filter:

```python
with st.expander("Schema browser", expanded=False):
    chosen_table = st.selectbox("Inspect table", tables["table_name"].tolist())
    schema = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY ordinal_position",
        [chosen_table],
    ).fetchdf()
    st.dataframe(schema, use_container_width=True, hide_index=True)
    sample = con.execute(f'SELECT * FROM "{chosen_table}" LIMIT 10').fetchdf()
    st.dataframe(sample, use_container_width=True, hide_index=True)
```

Three pieces of work here:

1. The `selectbox` is populated from the previous query's
   `table_name` column. So the dropdown shows all 21 names.
2. The schema query is parameterised with `?` and a single-element
   list. The user-chosen table name is treated as data, not as code,
   even though we trust it (it came from our own table list). That
   habit — never f-string user-driven values into SQL — is the
   subject of lesson 04. We start the habit here so it sticks.
3. The sample query *does* use an f-string: `f'SELECT * FROM
   "{chosen_table}" LIMIT 10'`. Why? Because table identifiers can't
   be parameterised in standard SQL — `?` is for *values* (in
   `WHERE`, `VALUES`, `INSERT`, etc.), never for *identifiers*
   (table names, column names). If you need to dynamically choose a
   table, you have to interpolate the name. The mitigation is to
   restrict the source: `chosen_table` only ever holds a value
   that came back from `information_schema.tables`, so it is by
   construction one of the 21 names already in the database. We
   wrap it in double quotes for safety against names with weird
   characters, but the real defence is the closed set of inputs.

The "ordinal_position" detail matters more than it seems. Without
it, a sort by `column_name` would scramble the natural order of the
table. `enriched_tickets` has `source_row` first, `date_raw` second,
`manager` fifth — that is the order in which the upstream code
defined them, and looking at the columns in that order is how a
human builds a mental model of the table. Sorting alphabetically
hides the structure.

Run the schema query against `enriched_tickets` and you see 60 rows.
The first three are:

```
column_name      data_type
source_row       VARCHAR
date_raw         VARCHAR
date             TIMESTAMP
```

The `date_raw` / `date` pair is from
[Module 02 — Data with pandas](../02-data-with-pandas/README.md):
the raw string `"2026/03/14"` is preserved alongside the parsed
timestamp so a downstream consumer can decide which to use.
`information_schema.columns` shows you both columns and their
distinct types without you having to remember any of that.

## The "sample 10 rows" follow-up

A schema is structure without content. Ten rows of content gives a
human a feel for what the structure means. The schema browser pairs
its `information_schema.columns` query with:

```python
sample = con.execute(f'SELECT * FROM "{chosen_table}" LIMIT 10').fetchdf()
st.dataframe(sample, use_container_width=True, hide_index=True)
```

Ten rows is enough to see "the `manager` column is full of human
names like Albert and Danila", "the `is_resolved` column is mostly
TRUE", "the `cluster_probability` column has a few NaN values".
Information schema tells you the column is a `VARCHAR`; ten sample
rows tell you whether it is a name, a UID, an enum slug, or free
text.

The order is "schema first, sample second". Read the structure, then
the data. Reverse the order and you waste cognitive effort guessing
what each column means before you've seen its type.

## Why portability matters

Nothing in this dashboard plans to migrate to Postgres. The
`analysis.duckdb` file is a local artefact, regenerated every run.
Why insist on standards-compliant catalogue queries when DuckDB has
shorter ones?

Three reasons.

**Skill transfer.** The next analyst who joins the team probably
knows Postgres and not DuckDB. Writing `information_schema.tables`
means they can sit down at the codebase and read it without learning
DuckDB-specific syntax. The investment pays for itself with the
first new hire.

**Optionality.** You don't plan to migrate. You also don't plan for
your manager to walk in tomorrow and say "the data is going to be
a hundred million rows; can you put it in our analytics warehouse?"
If the answer requires changing `SHOW TABLES` to
`SELECT * FROM information_schema.tables` in seventeen places in
your dashboard, that is a week of yak-shaving you could have spent
on the new feature. If the answer is "the queries already work,
just point the connection string at the warehouse", that is a
fifteen-minute change.

**Documentation.** `SHOW TABLES` reads as "magic incantation".
`SELECT table_name, table_type FROM information_schema.tables` reads
as "we are querying the catalogue, returning two columns, in
SQL". The second one is self-documenting; the first one is not. For
code other people will read, the explicit form wins.

The dashboard's design is opinionated about portability for the same
reason production code at large companies is opinionated about
portability: it is a small habit that costs nothing and pays back
when circumstances change. The `?` placeholder pattern in lesson 04
is another instance of the same principle — write the secure version
even when the trivially-insecure version would work, because the
habit is what matters.

## DuckDB-specific catalogues you should know exist (but rarely use)

DuckDB does have its own catalogue tables, exposed under the
`duckdb_*` schema:

- `duckdb_tables()` — function returning detailed table info, with
  more DuckDB-specific columns than `information_schema.tables`
  (estimated row count, on-disk size, etc.).
- `duckdb_columns()` — same idea for columns.
- `duckdb_views()`, `duckdb_indexes()`, `duckdb_constraints()`,
  `duckdb_databases()` — niche introspection.

Use these when you need DuckDB-specific information that the
standard schema doesn't carry, like estimated row counts or
on-disk-size statistics. For the "what tables exist and what columns
do they have" question — the dashboard's actual question —
`information_schema` is the cleaner answer.

## Try it

Open a Python REPL.

```python
import duckdb
from pathlib import Path

run = Path("outputs/option2_20260502_150055")
con = duckdb.connect(str(run / "analysis.duckdb"), read_only=True)

# Reproduce the dashboard's table count.
tables = con.execute(
    "SELECT table_name, table_type FROM information_schema.tables ORDER BY 1"
).fetchdf()
print(f"{len(tables)} tables and views")
print(tables["table_type"].value_counts())
```

You should see 21 total — 19 `BASE TABLE` and 2 `VIEW`. Now find
the wide tables, sorted by column count:

```python
column_counts = con.execute("""
    SELECT table_name, COUNT(*) AS n_cols
    FROM information_schema.columns
    GROUP BY table_name
    ORDER BY n_cols DESC
    LIMIT 5
""").fetchdf()
print(column_counts)
```

The widest is `enriched_tickets` at 60 columns. Three tables tie at
22 columns: `opportunity_backlog`, `outlier_subtopic_assignments`,
`refined_opportunity_backlog`. That is the kind of question that
takes seconds with `information_schema` and minutes if you go
script by script.

Now reproduce the schema browser by hand for the busiest table:

```python
schema = con.execute(
    """
    SELECT column_name, data_type, is_nullable, ordinal_position
    FROM information_schema.columns
    WHERE table_name = ?
    ORDER BY ordinal_position
    """,
    ["enriched_tickets"],
).fetchdf()
print(schema.head(15))
print(f"... and {len(schema) - 15} more")
```

You see the columns in their definition order — `source_row`,
`date_raw`, `date`, `month`, `manager`, … — exactly as the dashboard
shows them. The `?` placeholder takes the table name as a parameter,
the ORDER BY is by ordinal position, and the result is a tidy
DataFrame.

Last, prove the sample-row pattern:

```python
sample = con.execute('SELECT * FROM "manager_context_quality" LIMIT 5').fetchdf()
print(sample[["manager", "tickets", "avg_context_score"]])
```

The output is the five top managers by name (alphabetically, since
there is no ORDER BY) along with their ticket counts and context
scores. Pair the schema and the sample, and a database you've never
seen becomes legible inside thirty seconds — without reading a line
of pipeline source.
