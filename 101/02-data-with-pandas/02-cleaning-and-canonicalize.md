# Cleaning and canonicalising the schema

## The problem

After [Lesson 01](01-reading-messy-csv.md), you have a string-only DataFrame
with the original column headers preserved. Some of those headers are
English (`Manager`, `Question`, `UID`). Some are misspelled
(`Deligate to` instead of `Delegate to`). One is Chinese (`分类`). One is
Russian (`Статус`). One has a newline and a calendar emoji embedded in it
(`Role\n📆: 2026-04-06`). The Date column is a free-text string written
in mixed European and ISO formats (`12.04.2026` and `2026-04-12` in the
same column). The Status column has English values for some rows and
Chinese for others (`Closed` vs `已解决`).

Every downstream stage of the pipeline needs to read `df["manager"]`,
`df["date"]`, `df["is_resolved"]` without any of that variation visible.
`canonicalize` in `scripts/option2_pipeline.py` is the function that
collapses the variation into a stable snake_case schema with proper types.

## The `first_existing` pattern

Before reading `canonicalize`, read the helper it leans on:

```python
def first_existing(df: pd.DataFrame, names: Iterable[str]) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    lowered = {c.lower().strip(): c for c in df.columns}
    for name in names:
        hit = lowered.get(name.lower().strip())
        if hit:
            return hit
    return None
```

[`scripts/option2_pipeline.py:299-338`](../../scripts/option2_pipeline.py)

Take any number of candidate column names and return the first one that
actually exists in `df.columns`. The first loop is exact match, fast path.
The second loop builds a `{lower-stripped: original}` lookup table once
and tries each candidate again, case- and whitespace-insensitively.

Why two passes? On the happy path (column names match exactly) you do not
pay for the dict comprehension. Only when the exact lookup fails does the
function fall back to the slower, more forgiving comparison. For a
DataFrame with 30 columns and 17 lookups that adds up.

The `str | None` return type is load-bearing. Every caller has to check
the result before subscripting. The pipeline does this with a one-line
guard:

```python
out["manager"] = df[first_existing(df, ["Manager"])].map(normalize_space) if first_existing(df, ["Manager"]) else "Unknown"
```

[`scripts/option2_pipeline.py:598`](../../scripts/option2_pipeline.py)

The expression is read right-to-left: if `first_existing(...)` returned
`None`, fall back to the literal string `"Unknown"`; otherwise look the
column up by its real name and apply `normalize_space` row-wise. The
double call (once in the `if`, once in the index) is fine — `first_existing`
is cheap. It could be cached in a local variable for slightly better
readability; the pipeline accepts the duplication for grep-ability.

## Walking through `canonicalize`

```python
def canonicalize(df: pd.DataFrame) -> pd.DataFrame:
    category_col = first_existing(df, ["category", "分类"])
    status_cn_col = first_existing(df, ["status_cn", "Статус"])
    role_1_col = first_existing(df, ["Role.1", "role_1", "role_secondary"])
    svip_col = next((c for c in df.columns if "SVIP" in c.upper()), None)

    out = pd.DataFrame(index=df.index)
    out["source_row"] = df[first_existing(df, ["#"])].map(normalize_space) if first_existing(df, ["#"]) else np.arange(1, len(df) + 1).astype(str)
    out["date_raw"] = df[first_existing(df, ["Date"])].map(normalize_space) if first_existing(df, ["Date"]) else ""
    out["date"] = pd.to_datetime(out["date_raw"], errors="coerce", dayfirst=True)
    out["month"] = out["date"].dt.to_period("M").astype(str).replace("NaT", "")
    out["manager"] = df[first_existing(df, ["Manager"])].map(normalize_space) if first_existing(df, ["Manager"]) else "Unknown"
    out["role"] = df[first_existing(df, ["Role"])].map(normalize_space) if first_existing(df, ["Role"]) else ""
    out["uid"] = df[first_existing(df, ["UID"])].map(normalize_space) if first_existing(df, ["UID"]) else ""
    out["question"] = df[first_existing(df, ["Question"])].map(clean_text) if first_existing(df, ["Question"]) else ""
    out["question_flat"] = out["question"].map(normalize_space)
    out["status_en"] = df[first_existing(df, ["Status"])].map(normalize_space) if first_existing(df, ["Status"]) else ""
    out["status_cn"] = df[status_cn_col].map(normalize_space) if status_cn_col else ""
    out["is_resolved"] = out["status_en"].isin(["Closed", "Done"]) | out["status_cn"].eq("已解决")
    out["is_unresolved"] = ~out["is_resolved"]
    return out
```

[`scripts/option2_pipeline.py:548-616`](../../scripts/option2_pipeline.py)

Several patterns. We walk them in the order they appear.

### Building a fresh frame, not mutating

```python
out = pd.DataFrame(index=df.index)
```

Every column on `out` is *new*, derived from `df` but never alias-of. The
input frame is left untouched. That makes the function safe to call
from a notebook where you want to compare the canonical frame against
the raw one side by side.

The `index=df.index` argument keeps row indices aligned. When you assign
`out["manager"] = df[...].map(...)`, pandas joins on the index. If `out`
had a fresh `RangeIndex` and `df` did not, you would get rows mismatched
silently.

### `pd.to_datetime` with `errors="coerce"` and `dayfirst=True`

```python
out["date"] = pd.to_datetime(out["date_raw"], errors="coerce", dayfirst=True)
```

Three things going on.

- `pd.to_datetime` parses each string into a `Timestamp`. Values that
  cannot be parsed normally raise.
- `errors="coerce"` switches the failure mode: unparseable values become
  `NaT` (Not a Time, pandas's null for datetimes). One bad row no longer
  crashes the whole pipeline.
- `dayfirst=True` resolves the `12.04.2026` ambiguity in favour of
  European day-month-year. The rationale: the support team's handwritten
  dates use European order, and the ISO-format `2026-04-12` has a
  four-digit year as its first token, so pandas can disambiguate from the
  string alone.

After this line, `out["date"]` has dtype `datetime64[ns]`, and you can
call `.dt.year`, `.dt.month`, `.dt.dayofweek`, `.dt.to_period("M")` on it.

### Month buckets via `.dt.to_period("M").astype(str)`

```python
out["month"] = out["date"].dt.to_period("M").astype(str).replace("NaT", "")
```

The `.dt` accessor is to datetime columns what `.str` is to string
columns: it lets you call datetime methods element-wise.

`.to_period("M")` collapses each timestamp to the calendar month it
belongs to. `2026-04-12 14:30:00` becomes the period `2026-04`. The
result is a `PeriodIndex` whose dtype is `period[M]`.

`.astype(str)` turns the `PeriodIndex` into a plain string column —
useful for groupby keys, easy to write to CSV, easy to filter.

`.replace("NaT", "")` cleans up: when the original date was `NaT`, the
period is also `NaT`, and `astype(str)` produces the string `"NaT"`. We
prefer empty string for missing months because that is what the rest of
the pipeline expects.

You will see this exact triple — `.dt.to_period("M").astype(str)` — in
nearly every dashboard time series in the project. It is the canonical
"bucket by month" idiom in pandas.

### The `category_col` lookup with a Chinese alternative

```python
category_col = first_existing(df, ["category", "分类"])
...
if category_col:
    out["category"] = df[category_col].map(lambda v: strip_cjk_dup_prefix(normalize_space(v)))
else:
    out["category"] = ""
```

[`scripts/option2_pipeline.py:588, 608-611`](../../scripts/option2_pipeline.py)

The candidate list `["category", "分类"]` says "prefer the English column
if it exists, otherwise accept the Chinese one." Either way, the output
is a `category` column with snake_case naming.

The composed `lambda v: strip_cjk_dup_prefix(normalize_space(v))` is
applied row-wise via `.map`. `normalize_space` collapses every whitespace
run to a single space (defined back in
[`scripts/option2_pipeline.py:277-296`](../../scripts/option2_pipeline.py)).
`strip_cjk_dup_prefix` removes the leading Chinese label colleagues prepend
to many category strings — `'解封&封禁 Unblocking & Banning'` becomes
`'Unblocking & Banning'`. Module 01 has the regex; here we just need to
know it is one of the cleaning passes that happens during canonicalisation.

### Building booleans from two language variants

```python
out["is_resolved"] = out["status_en"].isin(["Closed", "Done"]) | out["status_cn"].eq("已解决")
out["is_unresolved"] = ~out["is_resolved"]
```

[`scripts/option2_pipeline.py:614-615`](../../scripts/option2_pipeline.py)

Two boolean Series joined with `|` (element-wise OR), then negated with
`~` (element-wise NOT). Every operator here is the *bitwise* one because
pandas Series do not respond to Python's `and`/`or`/`not` keywords —
those would coerce the whole Series to a single bool and raise
`ValueError: The truth value of a Series is ambiguous`.

Three idioms to memorise:

- `.isin([...])` — tests membership against a list. True where the cell
  matches any element of the list.
- `.eq(value)` — element-wise equality. Equivalent to `series == value`,
  but chains better when you are reading code top-to-bottom.
- `~series` — element-wise NOT. Flips True and False.

Combine them and you express "ticket is resolved if its English status is
Closed or Done, OR its Chinese status is `已解决`" in one line. Then
`is_unresolved` is just the inversion. Building both columns now means
every downstream `groupby` can read either polarity without recomputing.

### The "one ticket, two languages" trap

The reason `is_resolved` checks two columns is that some tickets have an
English status and some have a Chinese one — the same row never has both.
If you only checked `status_en.isin(["Closed", "Done"])`, every Chinese
ticket would be classified as unresolved. If you only checked
`status_cn.eq("已解决")`, every English ticket would be classified as
unresolved. The OR-of-two-language-tests pattern is how you handle a
bilingual status column without first translating it.

The same trick will appear later for the Question text itself — but
there we lean on multilingual sentence embeddings rather than column
unions. See [Module 03](../03-text-and-nlp/README.md).

### `next(...) or None` for fuzzy lookups

```python
svip_col = next((c for c in df.columns if "SVIP" in c.upper()), None)
```

[`scripts/option2_pipeline.py:591`](../../scripts/option2_pipeline.py)

When you do not know the exact name but you do know a substring, the
generator-expression-with-default form is the cleanest pattern: walk
the columns, yield each that contains the substring, take the first one,
fall back to `None` if there are zero matches. Same shape as
`first_existing`, but for a substring rule rather than an exact list.

## What canonical means

After `canonicalize`, every downstream function reads from a known schema:

| column | dtype | source |
|---|---|---|
| `source_row` | `object` (str) | original `#` column or fresh range |
| `date_raw` | `object` (str) | original `Date` column |
| `date` | `datetime64[ns]` | parsed from `date_raw` |
| `month` | `object` (str) | `dt.to_period("M").astype(str)` |
| `manager`, `role`, `uid`, `question_kind`, `delegate_to` | `object` (str) | normalised |
| `question` | `object` (str) | preserves newlines for line-counting |
| `question_flat` | `object` (str) | newlines collapsed for tokenizing |
| `category` | `object` (str) | CJK prefix stripped |
| `status_en`, `status_cn` | `object` (str) | bilingual variants kept side by side |
| `is_resolved`, `is_unresolved` | `bool` | union of bilingual status checks |

That table is the contract every later function relies on. The function
in [Lesson 03](03-feature-engineering.md) — `featurize_tickets` — opens by
doing `q = out["question"].fillna("").astype(str)` because it knows
canonical produced strings, and it just wants belt-and-braces.

## Try it

```bash
.venv/bin/python -c '
import sys
sys.path.insert(0, "scripts")
from option2_pipeline import read_raw_csv, drop_noise_columns, drop_summary_rows, canonicalize
from pathlib import Path

raw = read_raw_csv(Path("data_2may.csv"))
print("raw columns (first 20):")
for c in raw.columns[:20]:
    print(" ", repr(c))

cleaned, dropped_cols = drop_noise_columns(raw)
filtered, dropped_rows = drop_summary_rows(cleaned)
print(f"\ndropped {len(dropped_cols)} junk columns, {dropped_rows} summary rows")

canon = canonicalize(filtered)
print("\ncanonical schema:")
print(canon.dtypes)
print(f"\nrows: {len(canon)}")
print(f"is_resolved True share: {canon[\"is_resolved\"].mean():.4f}")
print(f"unique months: {sorted(m for m in canon[\"month\"].unique() if m)}")
print(f"non-empty UID share: {(canon[\"uid\"] != \"\").mean():.4f}")
'
```

What you should see:

1. The raw column list contains at least one entry with `\n` and a
   calendar emoji. After `drop_noise_columns`, those are gone.
2. The `dropped_rows` count is non-zero because at least a handful of
   colleague-pivot rows had neither Question nor UID.
3. The canonical schema has `date: datetime64[ns]`, `is_resolved: bool`,
   and string types everywhere else. Every column you expected, named
   in snake_case.
4. `is_resolved.mean()` is a fraction — the share of resolved tickets
   across the whole corpus. The number agrees with what the dashboard
   shows for the same run.

If `unique months` returns the values `['2025-06', '2025-07', ..., '2026-05']`,
your `pd.to_datetime(..., dayfirst=True)` parsed correctly. If you see
months in the wrong year or no months at all, that is the parser silently
turning every `12.04.2026` into the wrong date. Switch `dayfirst` off and
re-run to feel the difference.

[Lesson 03](03-feature-engineering.md) takes this canonical frame and
adds the 25 derived columns the rest of the pipeline reads from.
