# Reading a messy CSV without losing data

## The problem

`data_2may.csv` is a Google Sheets export of 6,728 customer-support tickets.
Three things are wrong with it before you have even opened it:

1. The "UID" column contains 14-to-18-digit user identifiers like
   `1115686439938544`. They are strings, not numbers. They look like numbers
   to pandas, which means the default reader will quietly turn them into
   `float64` and drop precision past 2^53. Once a UID becomes
   `1.115686439938544e+15`, every join that follows is wrong.
2. Some users actually wrote the literal text `"NaN"` or `"null"` or
   `"N/A"` in their ticket. With pandas' default `keep_default_na=True`,
   those strings become real `NaN` floats. The user complaint vanishes.
3. Colleagues use the same sheet for ad-hoc tally rows during weekly
   meetings. A row at the bottom looks like
   `,咨询信息Consulting info,0,,,` — empty everywhere except a category
   label and a count. There is no UID and no Question, but pandas reads it
   as a real ticket. Every aggregation is now off by however many summary
   rows snuck in.

`read_raw_csv` in `scripts/option2_pipeline.py` exists to defuse all three
hazards in one place.

## `pd.read_csv` with the two settings that matter

Here is the entire reader, as it stands in the pipeline:

```python
def read_raw_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df.columns = [clean_text(c) for c in df.columns]
    empty_unnamed = [c for c in df.columns if c.lower().startswith("unnamed") and (df[c].astype(str).str.strip() == "").all()]
    if empty_unnamed:
        df = df.drop(columns=empty_unnamed)
    return df
```

[`scripts/option2_pipeline.py:341-381`](../../scripts/option2_pipeline.py)

Four lines, three deliberate choices, one cleanup. We walk each.

### `dtype=str`

`dtype=str` forces every column to be read as a Python string. No type
inference, no `int64`, no `float64`, no `datetime64`. Pandas hands you back
a frame of strings.

That sounds wasteful — you will have to coerce dates and numbers later
anyway. The reason to do it here is **non-reversibility**. Once pandas sees
`"1115686439938544"` and decides it is an int, then has to upcast to float
because some other row in the column is empty (and floats have NaN, ints
do not), the value becomes `1.115686439938544e15`. There is no way to get
the original 16-digit string back. You have already lost the data.

Reading as string preserves the bytes that were in the file. You can always
parse a string into a number later when you know what you want. You cannot
unparse a float back into the string it used to be.

The same problem hits leading zeros (`"007"` → `7`), Excel-flavoured
"scientific notation" UIDs that the export tool already mangled
(`"1.12e15"`), and any column where some rows have data and others do not.

### `keep_default_na=False`

By default `read_csv` interprets a long list of strings — `""`, `"NA"`,
`"N/A"`, `"NULL"`, `"null"`, `"NaN"`, `"#N/A"`, `"-"`, `"None"` — as the
NaN float. With `keep_default_na=False`, that magic stops. An empty cell
becomes the empty string `""`. The text `"NaN"` stays `"NaN"`.

You want this for two reasons:

- **You handle missingness yourself.** The pipeline downstream uses
  `df["uid"].fillna("").astype(str).str.strip().ne("")` to decide whether
  a UID is present. That code expects strings; it does not want pandas
  guessing on its behalf.
- **A user really did type the word "null".** Customer support tickets
  contain free text. Some of them mention nullness, NaN, or N/A as part
  of the complaint. With the default settings, those tickets disappear.

Combine the two flags and your DataFrame has exactly two cell types:
real strings and the empty string. Predictable. Boring. Correct.

### Rebuilding the column index

```python
df.columns = [clean_text(c) for c in df.columns]
```

[`scripts/option2_pipeline.py:377`](../../scripts/option2_pipeline.py)

This is a list comprehension over `df.columns`. pandas accepts an
assignment of any iterable whose length matches the existing column count
and silently rebuilds the index. `clean_text` (defined just above) strips
whitespace and normalises CR/LF runs. The original CSV has at least one
column whose header is `Role\n📆: 2026-04-06` because a colleague embedded
a newline and an emoji in the header cell during a sheet pivot. Without
this pass, every later `df["Role"]` lookup fails.

### Dropping empty `Unnamed: N` trailers

```python
empty_unnamed = [c for c in df.columns if c.lower().startswith("unnamed") and (df[c].astype(str).str.strip() == "").all()]
if empty_unnamed:
    df = df.drop(columns=empty_unnamed)
```

[`scripts/option2_pipeline.py:378-380`](../../scripts/option2_pipeline.py)

Google Sheets emits `Unnamed: 23, Unnamed: 24, ...` for any column the
selection rectangle touched but no human filled. We test each candidate
with `(df[col].astype(str).str.strip() == "").all()` — strip every cell,
compare to empty string, take the boolean Series, and call `.all()`. If
every cell is empty after stripping, the column is junk and we drop it.

The `.astype(str)` defends against the rare case the `dtype=str` directive
missed something. Belt-and-braces, because the cost is negligible and the
failure mode is loud.

## The colleague-pivot row example

Set `dtype=str` and `keep_default_na=False`, and a typical row of
`data_2may.csv` looks like this in memory:

```
{"#": "1234", "Date": "12.04.2026", "Manager": "Albert",
 "UID": "1115686439938544", "Question": "Hello, my channel...",
 "Status": "Done", "category": "Consulting info"}
```

Now consider a row a manager added during a weekly review:

```
{"#": "", "Date": "", "Manager": "", "UID": "", "Question": "",
 "Status": "", "category": "咨询信息Consulting info"}
```

There is no UID and no Question. The category cell carries the bilingual
label colleagues use as a pivot row label. Without intervention this row
becomes part of every count, every share, every average.

`read_raw_csv` does not catch it. That is `drop_summary_rows` in
[`scripts/option2_pipeline.py:501-545`](../../scripts/option2_pipeline.py)
two functions later, which uses the rule "if there is no Question and no
UID, the row is not a real ticket." But `drop_summary_rows` only works
because `read_raw_csv` produced empty strings, not `NaN`s, for the missing
cells — so a single `.fillna("").astype(str).str.strip().ne("")` test gives
a clean boolean. If you let pandas insert `NaN` floats here, the downstream
test has to handle two missingness representations, and the heuristic
becomes fragile.

The pattern: keep the file's bytes intact at read time, push every
interpretation decision downstream, and write each downstream test against
exactly one type. Strings in, strings out, NaN nowhere.

## Why not let pandas infer types?

Type inference is great when the file was written by code you trust. It is
catastrophic when the file came out of Google Sheets after a colleague
selected an empty cell to "tidy up the formatting." A single empty cell
in the middle of a UID column is enough to upcast 6,728 strings to floats
and lose precision on every one of them.

The rule of thumb: if the CSV was produced by humans clicking buttons,
read it as strings. Convert later, in code you wrote and can debug.

## When you do want pandas to coerce

`dtype=str` is for the *input boundary*. The whole point of pushing
type decisions downstream is so you can make them explicitly with
named functions:

- `pd.to_datetime(df["date_raw"], errors="coerce", dayfirst=True)` —
  parse a column of strings into datetimes; turn unparseable values
  into `NaT` instead of raising. This is the "parse late" half of the
  pattern.
- `pd.to_numeric(df["risk"], errors="coerce")` — same idea for
  integers and floats. The `cluster_id` column in `enriched_tickets.csv`
  goes through this conversion at the start of
  [Lesson 05](05-merge-and-join.md).
- `series.astype("Int64")` — pandas's nullable integer type. Use this
  when you want a real integer column that can also carry `NA` (for
  example, a topic id that BERTopic did not assign). Distinct from
  the regular `int64`, which cannot hold nulls.

Doing the parse downstream means each conversion lives at the place
where you know what the column is *supposed* to mean. Compare with
the alternative — letting `read_csv` guess at the boundary and then
discovering at use-site that the dtype is wrong. By the time you
notice, the original strings are gone.

## What about Excel files?

The same two flags work for `pd.read_excel`. The arguments are
identical: `dtype=str`, `keep_default_na=False`. Most of this corpus
arrived as a Sheets export, but the data team also receives weekly
Excel rollups, and `read_excel` has the same hazards as `read_csv`
plus the additional excitement of Excel's date serialisation
quirks. Read as string; parse with `pd.to_datetime` afterward.

## Reading large files in chunks

`read_csv` accepts a `chunksize=N` argument that returns an iterator of
DataFrames instead of one big frame. The pipeline does not use it
because 6,728 rows fit in memory comfortably. If your file is millions
of rows or your laptop is small, `chunksize=10000` lets you process the
file 10,000 rows at a time, append intermediate results to a list, and
concatenate at the end. The same `dtype=str, keep_default_na=False`
flags apply to each chunk.

## What you should remember

- `dtype=str` reads everything as strings. Use it on any human-produced CSV.
- `keep_default_na=False` stops pandas from interpreting strings as NaN.
  Combined with `dtype=str`, you get exactly two cell types: real strings
  and `""`.
- `df.columns = [clean_text(c) for c in df.columns]` rebuilds the column
  index. Use it to strip whitespace, normalise newlines, and survive the
  `Role\n📆` headers Sheets exports inflict on you.
- Empty `Unnamed: N` trailing columns are normal. Drop them with one
  `.all()` test on stripped values.
- Do not try to filter summary rows in the reader. That belongs to
  `drop_summary_rows`, which can rely on `""` instead of `NaN` precisely
  because the reader was strict.

## Try it

From the repo root, with the pipeline's virtualenv active:

```bash
.venv/bin/python -c '
import pandas as pd
from pathlib import Path

# Read the way pandas defaults — see what breaks.
default = pd.read_csv("data_2may.csv")
print("default dtypes for UID and #:")
print(default[["UID", "#"]].dtypes, "\n")
print("first UID at default settings:", repr(default["UID"].iloc[0]))

# Read the way the pipeline does it.
strict = pd.read_csv("data_2may.csv", dtype=str, keep_default_na=False)
print("\nstrict dtypes for UID and #:")
print(strict[["UID", "#"]].dtypes)
print("first UID at strict settings:", repr(strict["UID"].iloc[0]))

# Confirm no NaN floats anywhere.
n_nan = strict.isna().sum().sum()
print(f"\nNaN cells in strict frame: {n_nan} (should be 0)")
print(f"empty strings in strict UID column: {(strict[\"UID\"] == \"\").sum()}")

# Show the column headers exactly as they came out of Sheets.
print("\nraw columns:")
for c in default.columns:
    print(repr(c))
'
```

Two things you should observe:

1. The default UID dtype is `float64`, and the first UID is printed in
   scientific notation. The strict UID dtype is `object` and the first UID
   is the original 14–18 digit string.
2. The strict frame has zero `NaN` cells (because of `keep_default_na=False`).
   It has many empty strings instead — that is by design.

If you also see the `'Role\n📆: 2026-04-06'` header in the raw columns
list, you have just hit the reason `df.columns = [clean_text(c) for c in
df.columns]` exists. Run [Lesson 02](02-cleaning-and-canonicalize.md) next
to see how the pipeline turns this string-only frame into a stable, typed
analysis schema.
