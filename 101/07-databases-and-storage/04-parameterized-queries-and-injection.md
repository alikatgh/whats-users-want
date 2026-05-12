# 04 — Parameterised queries and injection

A user types into the search box on
[pages/07_Find_a_Ticket.py](../../scripts/dashboard/pages/07_Find_a_Ticket.py):

```
'); DROP TABLE enriched_tickets; --
```

If the page builds its SQL with f-strings, the database receives:

```sql
SELECT ... FROM enriched_tickets WHERE LOWER("question") LIKE '%'); DROP TABLE enriched_tickets; --%'
```

The first statement runs (matching nothing). The second statement
drops the table. The third statement (`--`) is a comment that
swallows the trailing quote. Your run directory's `enriched_tickets`
table is gone. The next time the dashboard reloads, every other
page that joins to `enriched_tickets` errors out.

That attack does not actually work against the dashboard. The
connection is opened in `read_only=True` mode, so the `DROP` would
error before it executed. But "the safety belt caught it" is not the
defence. The defence is that the page never builds SQL by
concatenating user input in the first place. It uses parameterised
queries — `?` placeholders that DuckDB substitutes server-side, with
proper escaping.

This lesson teaches the two parameterisation patterns the dashboard
uses, the helper that makes variable-length `IN` clauses safe, the
case-insensitive search idiom, and the one place where you genuinely
must f-string an identifier (table or column names) and how to make
that safe through input restriction.

## The `?` placeholder

DuckDB's parameter syntax is the SQL standard `?` positional
placeholder. You write the query with `?` where a value goes, and
pass the values as a separate list to `con.execute`:

```python
con.execute(
    'SELECT * FROM enriched_tickets WHERE manager = ?',
    ['Albert'],
).fetchdf()
```

Mechanically, DuckDB receives the SQL string and the parameter list
as two separate inputs. The SQL string is parsed first, *with the
`?` left as a parameter slot*. The values from the list are then
bound into those slots at execution time. There is no string
concatenation. The user input, no matter what it contains, can never
"escape" into the SQL grammar — DuckDB sees it as a value, not as
code.

The full flow in
[pages/07_Find_a_Ticket.py:235-239](../../scripts/dashboard/pages/07_Find_a_Ticket.py)
shows the pattern in action:

```python
where_sql = " AND ".join(clauses) if clauses else "1=1"

count_sql = f"SELECT COUNT(*) FROM enriched_tickets WHERE {where_sql}"
data_sql = f"SELECT {cols_sql} FROM enriched_tickets WHERE {where_sql} ORDER BY context_depth_score DESC LIMIT {limit}"

n_total = con.execute(count_sql, params).fetchone()[0]
df = con.execute(data_sql, params).df()
```

There is an f-string here, and that's important to understand. The
f-string interpolates `where_sql` (a SQL fragment built only from
trusted column names plus literal `?` placeholders) and `cols_sql`
(a pre-defined comma-separated list of trusted column names). It
does *not* interpolate any user-typed value. The user's
selections — the list of selected managers, the search text —
travel separately through `params` and get bound into the `?`
placeholders. The shape is correct: code-shape strings are
constructed from trusted material; data-shape values flow through
parameters.

## The `in_clause` helper for variable-length IN

The hard part of parameterising user input is the variable-length
case. `WHERE manager = ?` is one parameter. `WHERE manager IN (?,
?, ?)` is three parameters. But the user might select zero, one,
two, three, or twenty-eight managers. You don't know the right
number of `?` until runtime.

The page solves this with a tiny helper that takes a column name and
a list of selected values, and mutates the running `clauses` and
`params` lists in place:

```python
def in_clause(col: str, values: list[str]) -> None:
    if not values:
        return
    placeholders = ",".join(["?"] * len(values))
    clauses.append(f'"{col}" IN ({placeholders})')
    params.extend(values)
```

That code lives in
[pages/07_Find_a_Ticket.py:176-202](../../scripts/dashboard/pages/07_Find_a_Ticket.py).
Three things to notice.

First, the empty case is a no-op. If `values` is empty (the user
selected nothing in the multiselect), the function returns without
modifying anything. The right semantics for an empty multiselect is
"no filter applied", and the right way to express "no filter
applied" is to omit the clause entirely. Adding a `WHERE manager IN
()` would be a SQL error in most engines and a no-match in others;
omitting the clause means "all values pass".

Second, the placeholders are built with
`",".join(["?"] * len(values))`. For three values you get `?,?,?`.
For one value you get `?`. For zero values you would get the empty
string, but the early `return` prevents that case from ever
reaching here. The placeholder count exactly matches the value
count.

Third, the column name is interpolated with an f-string into the
clause, but `col` is sourced from a hard-coded list in the page (you
can see all five callers in
[pages/07_Find_a_Ticket.py:205-209](../../scripts/dashboard/pages/07_Find_a_Ticket.py)):

```python
in_clause("manager", sel_manager)
in_clause("primary_desire", sel_desire)
in_clause("category", sel_category)
in_clause("status_en", sel_status)
in_clause("context_depth_band", sel_band)
```

Five trusted, hard-coded column names. The f-string is safe because
the inputs are not user-supplied. The `"col"` double-quoting
guards against engine-specific identifier rules (a column named
`status` could collide with a reserved word in some SQL dialects).

Watch the helper run for two managers selected:

```python
clauses, params = [], []
in_clause("manager", ["Albert", "Danila"])
print(clauses)   # ['"manager" IN (?,?)']
print(params)    # ['Albert', 'Danila']
```

Then the page assembles the WHERE clause from `clauses` joined with
` AND `, the `data_sql` string with `where_sql` interpolated, and
calls `con.execute(data_sql, params)`. DuckDB sees a query with two
unbound `?` slots and a list of two values, binds them, and returns
the result. The user's selections never touch the SQL parser as
code.

## Case-insensitive substring search

The text search box adds one more clause to the WHERE list, with
its own pattern:

```python
if text_query:
    clauses.append('LOWER("question") LIKE ?')
    params.append(f"%{text_query.lower()}%")
```

That code in
[pages/07_Find_a_Ticket.py:210-212](../../scripts/dashboard/pages/07_Find_a_Ticket.py)
is doing four things. Let's pull them apart.

**`LOWER("question") LIKE ?`.** SQL's default `LIKE` operator is
case-sensitive in most engines (DuckDB included). Wrapping the
column in `LOWER(...)` and lowercasing the pattern makes the
comparison case-insensitive. The user can type "BAN", "ban", or
"Ban" and match all three.

**`?` placeholder.** Same parameterisation as before — the actual
search text never touches the SQL string. If a user types
`'); DROP TABLE`, that string lands in the `params` list as a
single value, gets bound to the `?` slot, and is interpreted as a
literal LIKE pattern by DuckDB. No injection.

**`f"%{text_query.lower()}%"`.** The `%` characters are LIKE
wildcards. `%foo%` matches "foo anywhere"; `foo%` matches "starts
with foo"; `%foo` matches "ends with foo"; `foo` (with no `%`) is
an exact match. The page wraps the user's input with `%` on both
sides for the substring-search semantics a user expects from a
search box.

**`text_query.lower()`.** Performed on the Python side because the
SQL side already calls `LOWER` on the column. Both sides need to
lowercase or neither does; mixing one and not the other reintroduces
case sensitivity.

A subtle point: the f-string inside `params.append` is *not* the
same kind of f-string as a SQL-injection-prone f-string. This
f-string is building a Python *value* (the LIKE pattern) which then
flows through the parameterised `?`. It's safe by construction,
because DuckDB receives the resulting string as a value, not as
code. The unsafe f-string is the one that builds a query *string*
with user input concatenated in.

## `read_only=True` as a safety belt

The SQL console at
[pages/10_Run_SQL_Queries.py:118](../../scripts/dashboard/pages/10_Run_SQL_Queries.py)
opens DuckDB read-only:

```python
return duckdb.connect(path, read_only=True)
```

The docstring spells out why: "Read-only mode is a safety belt: the
SQL console is meant for exploration, so accidentally typing a
destructive query errors out rather than mutating the database."
([pages/10_Run_SQL_Queries.py:106-108](../../scripts/dashboard/pages/10_Run_SQL_Queries.py))

In read-only mode, any statement that would modify the database
errors at parse or execute time:

- `INSERT`, `UPDATE`, `DELETE`, `MERGE` — error.
- `CREATE TABLE`, `CREATE VIEW`, `CREATE INDEX` — error.
- `DROP TABLE`, `DROP VIEW`, `ALTER TABLE` — error.
- `TRUNCATE` — error.
- `SELECT`, `WITH`, `EXPLAIN`, `DESCRIBE`, `SHOW`, `PRAGMA SHOW`,
  `information_schema` queries — fine.

The flag costs nothing. The only times you don't want it are when
the page actually needs to write — and in this codebase, the only
writes happen in the pipeline scripts, never in the dashboard. Both
[pages/07_Find_a_Ticket.py:121](../../scripts/dashboard/pages/07_Find_a_Ticket.py)
and
[pages/10_Run_SQL_Queries.py:118](../../scripts/dashboard/pages/10_Run_SQL_Queries.py)
open read-only.

This is "defence in depth". The parameterisation is the primary
defence — user input cannot reach the SQL parser as code. Read-only
mode is the secondary defence — even if you somehow forgot to
parameterise *and* the user typed a malicious string *and* DuckDB
parsed it as code, the destructive statement would still fail to
execute. Two locks on the door cost twice nothing.

## When you have to interpolate identifiers

SQL parameterisation works for *values* — the things on the right
side of `=`, in `VALUES (...)`, in `WHERE col IN (...)`. It does
not work for *identifiers* — table names, column names, schema
names. The `?` placeholder cannot stand in for a column name. This
is by design: parameter binding happens after parsing, and the
parser needs to know which columns are involved before it can plan
the query.

Consequently, the dashboard *does* f-string identifiers in two
places. Both have a closed set of inputs.

In `distinct(col)`:

```python
def distinct(col: str) -> list[str]:
    try:
        rows = con.execute(
            f'SELECT DISTINCT "{col}" FROM enriched_tickets WHERE "{col}" IS NOT NULL ORDER BY 1'
        ).fetchall()
        return [str(r[0]) for r in rows if r[0] is not None]
    except Exception:
        return []
```

That code in
[pages/07_Find_a_Ticket.py:132-154](../../scripts/dashboard/pages/07_Find_a_Ticket.py)
takes a column name and returns the distinct values in that column.
The page calls it five times with hard-coded names: `"manager"`,
`"primary_desire"`, `"category"`, `"status_en"`,
`"context_depth_band"`. The docstring is explicit:
"the column name is interpolated into SQL after being wrapped in
double quotes, so it must be trusted (i.e. hard-coded in this file,
not user-supplied)."

In the schema browser's sample-row query:

```python
sample = con.execute(f'SELECT * FROM "{chosen_table}" LIMIT 10').fetchdf()
```

Here `chosen_table` came from the `selectbox`, which was populated
from `information_schema.tables`. The set of possible values is
"the 21 names that exist in this database". A user cannot type a
name that isn't in the dropdown.

Both places accept input from a closed set known at code-write time.
That is the rule: when you must f-string an identifier, restrict
the source to a finite, code-controlled list.

## What about pandas's parameterisation?

pandas's `read_sql_query` accepts a `params` argument that does the
same parameter binding under the hood. If you have a pandas-native
codebase you might never see the `con.execute(sql, params)` pattern
explicitly. The principle is the same: never f-string user input
into the query string. The mechanics of how the parameters reach
the database driver vary; the discipline does not.

DuckDB's `con.execute(sql, params)` is the most direct expression
of the discipline, which is why the dashboard uses it directly.

## Try it

Open a Python REPL.

```python
import duckdb
from pathlib import Path

run = Path("outputs/option2_20260502_150055")
con = duckdb.connect(str(run / "analysis.duckdb"), read_only=True)

# 1. Reproduce the IN clause helper.
def build_in_clause(col, values):
    placeholders = ",".join(["?"] * len(values))
    return f'"{col}" IN ({placeholders})', list(values)

clause, params = build_in_clause("manager", ["Albert", "Danila"])
sql = f'SELECT manager, COUNT(*) AS n FROM enriched_tickets WHERE {clause} GROUP BY manager'
print(con.execute(sql, params).fetchdf())
```

You should see two rows: `Albert  2247` and `Danila  1441`. Now
prove the case-insensitive substring search:

```python
text = "BAN"  # uppercase, mixed languages later
n = con.execute(
    'SELECT COUNT(*) FROM enriched_tickets WHERE LOWER("question") LIKE ?',
    [f"%{text.lower()}%"],
).fetchone()[0]
print(f"{n} tickets mention 'ban' (any case)")
```

You should see `934 tickets mention 'ban' (any case)`. Try the
search with `text = "money"` for a smaller number — about 137 — and
notice that uppercase, lowercase, and Title Case all produce the
same count because the `LOWER(...) LIKE` symmetry treats them
identically.

Now demonstrate the read-only safety belt:

```python
ro = duckdb.connect(str(run / "analysis.duckdb"), read_only=True)
try:
    ro.execute("DROP TABLE enriched_tickets")
except Exception as exc:
    print(f"Blocked: {type(exc).__name__}: {exc}")
finally:
    ro.close()
```

You see a DuckDB error explaining that the database is read-only.
The table is intact. Reopen without the flag (don't actually drop
anything!) and you'd get a different error or, if you weren't
careful, a real drop. Always pass `read_only=True` when the page is
exploratory.

Last, show the injection-resistance directly:

```python
malicious = "'); DROP TABLE enriched_tickets; --"
n = con.execute(
    'SELECT COUNT(*) FROM enriched_tickets WHERE LOWER("question") LIKE ?',
    [f"%{malicious.lower()}%"],
).fetchone()[0]
print(f"Match count for the injection string treated as text: {n}")
```

You see `0` (no ticket text contains that exact phrase). The query
ran cleanly. The `enriched_tickets` table still has 6,728 rows. The
"injection" was treated as a literal LIKE pattern, never as code.
That is what `?` buys you, every time, for free.
