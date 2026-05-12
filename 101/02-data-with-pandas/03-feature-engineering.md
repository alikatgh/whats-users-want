# Feature engineering with vectorised pandas

## The problem

You have a canonical frame with 6,728 rows and a clean `question` text
column. Every downstream stage needs the same derived signals: how long
each ticket is, whether it carries a URL or a screenshot, whether it
mentions a 14-digit UID, whether it complains about money, whether the
user claims innocence, what the user is *trying to accomplish*, how
urgent it sounds, and a single 0–100 number that summarises "did this
manager write enough to investigate without bothering the user."

`featurize_tickets` in `scripts/option2_pipeline.py` produces those
signals in one pass. Twenty-plus derived columns. Each one is a
vectorised pandas expression — no Python loops over rows. The function
is the heart of the pipeline; manager scoring, clustering, OLS,
opportunity ranking, and every dashboard chart read from columns it
produces.

This lesson walks the function end to end. Refer to the source at
[`scripts/option2_pipeline.py:619-789`](../../scripts/option2_pipeline.py).
We focus on the pandas idioms the function leans on, not the regexes
themselves (those are in [Module 01, Lesson 02](../01-python-foundations/02-regex.md)).

## The opening

```python
def featurize_tickets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    q = out["question"].fillna("").astype(str)
    flat = out["question_flat"].fillna("").astype(str)
```

[`scripts/option2_pipeline.py:730-732`](../../scripts/option2_pipeline.py)

Three habits worth copying:

- `out = df.copy()` returns a new frame. The original is left alone, so
  callers can run featurisation in a notebook and still inspect the
  pre-feature frame next to it.
- `q = out["question"].fillna("").astype(str)` replaces any rare `NaN`
  with `""` and casts to string. Belt-and-braces — `canonicalize` already
  produced strings — but the rest of the function uses `q.str.len()`,
  `q.str.findall(...)`, `q.map(...)` and they all assume strings.
- Two locals: `q` keeps newlines (used by `line_count`), `flat` is the
  whitespace-collapsed version (used by `word_count`). One frame, two
  views.

## Length features

```python
out["char_count"] = q.str.len()
out["word_count"] = flat.str.findall(r"\b\w+\b").str.len()
out["line_count"] = q.map(lambda s: len([line for line in s.split("\n") if line.strip()]))
```

[`scripts/option2_pipeline.py:734-736`](../../scripts/option2_pipeline.py)

Three patterns to internalise.

`q.str.len()` is the vectorised Python `len` per cell. The `.str`
accessor on a string Series exposes most string methods elementwise:
`.str.upper()`, `.str.contains(...)`, `.str.startswith(...)`. They run
in C, not Python, and operate on every row in one call.

`flat.str.findall(r"\b\w+\b").str.len()` chains two `.str` calls. The
first returns a Series of *lists* — for each cell, the list of word
tokens matched by the regex. The second `.str.len()` then takes the
length of each list. Same `.str` accessor, two different element types
(strings the first time, lists the second). The final result is a
Series of integers: the word count per ticket.

`q.map(lambda s: len([line for line in s.split("\n") if line.strip()]))`
falls back to `.map` when the per-row computation does not fit a `.str`
shortcut. `s.split("\n")` is a regular Python string method on a single
cell. The list comprehension counts lines that are not empty after
stripping. `.map` is the row-level escape hatch — a tiny bit slower than
`.str` because it hands each cell to Python, but unrestricted.

## Regex counts and boolean flags

```python
out["url_count"] = q.map(lambda s: len(URL_RE.findall(s)))
out["image_url_count"] = q.map(lambda s: len(IMAGE_RE.findall(s)))
out["timestamp_count"] = q.map(lambda s: len(TIMESTAMP_RE.findall(s)))
out["room_or_group_id_count"] = q.map(lambda s: len(ROOM_ID_RE.findall(s)))
out["long_uid_or_case_id_count"] = q.map(lambda s: len(LONG_ID_RE.findall(s)))

out["has_url"] = out["url_count"].gt(0)
out["has_image_url"] = out["image_url_count"].gt(0)
out["has_timestamp"] = out["timestamp_count"].gt(0)
out["has_room_or_group_id"] = out["room_or_group_id_count"].gt(0)
out["has_long_uid_or_case_id"] = out["long_uid_or_case_id_count"].gt(0)
```

[`scripts/option2_pipeline.py:737-748`](../../scripts/option2_pipeline.py)

Two layers per signal: a count, then a flag. The pattern is

```python
out["x_count"] = q.map(lambda s: len(SOMETHING_RE.findall(s)))
out["has_x"]   = out["x_count"].gt(0)
```

The count is for scoring (more URLs → more evidence). The flag is for
filtering (`df[df["has_url"]]` to look at the URL-bearing tickets).
Computing the count once and deriving the flag from it is cheaper than
computing both from scratch and keeps them consistent — `has_url` is
True iff `url_count > 0` by construction.

`.gt(0)` is the chainable form of `> 0`. `.gt`, `.lt`, `.eq`, `.ne`,
`.le`, `.ge` exist for the same reason: they make element-wise
comparisons readable when you are stacking them in a method chain.

## Boolean searches via `q.map(lambda s: bool(REGEX.search(s)))`

```python
out["has_ban_reason_language"] = q.map(lambda s: bool(BAN_REASON_RE.search(s)))
out["has_user_claim"] = q.map(lambda s: bool(USER_CLAIM_RE.search(s)))
out["has_money_terms"] = q.map(lambda s: bool(MONEY_RE.search(s)))
out["has_status_or_svip_terms"] = q.map(lambda s: bool(STATUS_RE.search(s)))
out["has_multiline_note"] = out["line_count"].ge(3)
out["has_screenshot_evidence"] = out["has_image_url"] | q.str.contains(r"\bscreens?\b|screenshot", flags=re.I, regex=True, na=False)
```

[`scripts/option2_pipeline.py:749-754`](../../scripts/option2_pipeline.py)

Two ways to test "does this row's text match a regex":

- `q.map(lambda s: bool(REGEX.search(s)))` calls a precompiled pattern's
  `.search` per row and casts the result (a `Match` or `None`) to bool.
  This is the workhorse: it lets you reuse the precompiled `BAN_REASON_RE`
  defined at module level once.
- `q.str.contains(pattern, flags=re.I, regex=True, na=False)` is the
  pandas vectorised version. It compiles the pattern internally and is
  slightly faster, but works against a literal string pattern, not a
  precompiled object. Use it when you want a one-off regex inline, the
  way `has_screenshot_evidence` does for `r"\bscreens?\b|screenshot"`.

`na=False` says "treat null cells as not-matching." Without it,
`str.contains` would propagate `NaN` into the result, and the boolean
column would have three states (True, False, NaN) instead of two —
breaking `(out["has_screenshot_evidence"]).mean()` arithmetic.

`has_multiline_note` is built differently: directly from `line_count.ge(3)`,
because three or more non-empty lines is the rule. No regex, no `.map`.

`has_screenshot_evidence` is a union of two signals via `|`: an image
URL was detected, OR the literal word "screen" / "screenshot" appeared.
Either path qualifies the ticket as having a screenshot.

## Building 10 desire flags from a dict of regexes

```python
for desire, pattern in DESIRE_PATTERNS.items():
    out[f"desire__{desire}"] = q.map(lambda s, p=pattern: bool(p.search(s)))

desire_cols = [f"desire__{name}" for name in DESIRE_PATTERNS]
out["desire_count"] = out[desire_cols].sum(axis=1)
out["primary_desire"] = out[desire_cols].idxmax(axis=1).str.replace("desire__", "", regex=False)
out.loc[out[desire_cols].sum(axis=1).eq(0), "primary_desire"] = "unclear_or_needs_llm"
```

[`scripts/option2_pipeline.py:756-762`](../../scripts/option2_pipeline.py)

`DESIRE_PATTERNS` (defined at
[`scripts/option2_pipeline.py:162-173`](../../scripts/option2_pipeline.py))
is a `dict[str, re.Pattern[str]]` mapping each of the 10 desire slugs
(`recover_access`, `clear_name_or_get_fairness`, `earn_or_transact_money`, ...)
to a compiled regex. The `for` loop unrolls the dict into 10 boolean
columns named `desire__<slug>`.

The trick worth remembering is `lambda s, p=pattern: bool(p.search(s))`.
That `p=pattern` is a default argument that captures `pattern` *at
function-definition time*, not at call time. Without it, every lambda in
the loop would close over the same variable `pattern` and they would all
end up using whichever value `pattern` held *after* the loop finished.
That is Python's late-binding closure trap. The `p=pattern` idiom binds
the value at the moment the lambda is created. Worth memorising — the
bug is silent when it strikes.

`out[desire_cols].sum(axis=1)` sums True/False values across columns
per row. `axis=1` means "sum within each row across columns" (the
opposite of `axis=0`, which sums each column down through rows). True
counts as 1, False as 0, so the result is the number of desires that
fired for that ticket. A ticket can fire multiple desires; the total
share across the corpus exceeds 100% on purpose.

`out[desire_cols].idxmax(axis=1)` returns, for each row, the *column
name* of the first True value. Because `DESIRE_PATTERNS` is a dict and
dict order is preserved in Python 3.7+, the iteration order is the
priority order: when a ticket fires both `recover_access` and
`fix_product_or_technical_flow`, `idxmax` picks `recover_access` because
it appears first in the dict.

`.str.replace("desire__", "", regex=False)` strips the column-name
prefix so the `primary_desire` cell holds `recover_access` rather than
`desire__recover_access`. `regex=False` says "treat the pattern as a
literal string, not a regex" — slightly faster and avoids the case where
your replacement string accidentally contains a metacharacter.

The last line uses `.loc[mask, column] = value` to overwrite the
`primary_desire` cell to `"unclear_or_needs_llm"` when no desire fired.
`out[desire_cols].sum(axis=1).eq(0)` is the boolean mask: True where the
row's desire-sum is exactly zero. The `.loc[]` assignment is the
canonical pandas idiom for conditional updates — using `df[mask][col] = ...`
would silently fail because of chained-indexing.

## Urgency and evidence count

```python
out["urgency_signal"] = q.map(lambda s: len(URGENCY_RE.findall(s)))
out["evidence_element_count"] = out[EVIDENCE_LABELS].sum(axis=1)
```

[`scripts/option2_pipeline.py:764-765`](../../scripts/option2_pipeline.py)

`urgency_signal` counts urgency cue words rather than booleanising. A
panicked user who writes "please please plz urgent now help" scores
higher than a single "please". Counts let the score scale; booleans
flatten everything to one bit.

`evidence_element_count` sums the 10 `has_*` flags listed in
`EVIDENCE_LABELS` (defined at
[`scripts/option2_pipeline.py:179-190`](../../scripts/option2_pipeline.py)).
The result is an integer 0–10 per ticket — "how many *kinds* of
forensic evidence did this ticket carry." Boolean True is 1 in pandas
arithmetic, so `.sum(axis=1)` over a frame of bools gives an integer.

## The 95th-percentile cap and the score formula

This is the centrepiece. Three continuous features are normalised by
their 95th-percentile value, then the whole thing is a weighted sum.

```python
char_cap = max(float(out["char_count"].quantile(0.95)), 1.0)
line_cap = max(float(out["line_count"].quantile(0.95)), 1.0)
url_cap = max(float(out["url_count"].quantile(0.95)), 1.0)
out["context_depth_score"] = (
    18 * np.minimum(out["char_count"] / char_cap, 1)
    + 10 * np.minimum(out["line_count"] / line_cap, 1)
    + 10 * np.minimum(out["url_count"] / url_cap, 1)
    + 10 * out["has_image_url"].astype(int)
    + 8 * out["has_timestamp"].astype(int)
    + 8 * out["has_room_or_group_id"].astype(int)
    + 8 * out["has_long_uid_or_case_id"].astype(int)
    + 10 * out["has_ban_reason_language"].astype(int)
    + 8 * out["has_user_claim"].astype(int)
    + 5 * out["has_money_terms"].astype(int)
    + 5 * out["has_status_or_svip_terms"].astype(int)
).round(2)
```

[`scripts/option2_pipeline.py:767-782`](../../scripts/option2_pipeline.py)

### Why 95th-percentile capping

`out["char_count"].quantile(0.95)` returns the 95th-percentile character
count across all 6,728 tickets — a number around 1,400 in the current
corpus. Dividing by that cap maps "median ticket length" to roughly 0.05,
"long ticket" to roughly 0.5, and "tickets longer than the 95th
percentile" to ≥ 1.

Without the cap, one outlier ticket — someone pasted 50,000 characters —
would dominate the score across the whole corpus. Every other ticket
would look "thin" by comparison. With the cap, that pasted-novel ticket
saturates at 1.0 and stops crowding everyone else out.

`np.minimum(x, 1)` clips the ratio to at most 1.0. If a ticket is longer
than the cap, its char-component contributes the maximum 18 points and
that is it. Linear up to the cap, flat afterwards. Saturation by design.

The `max(..., 1.0)` floor on the cap itself defends against the
degenerate case where the 95th percentile is 0 (every ticket has zero
URLs, for example, in a sample where nobody pasted any). Dividing by
zero is a hard error in numpy; dividing by 1 just produces 0.

### Why each weight

The team chose weights by hand to encode investigative priors:

- 18 chars — "user wrote a lot." Bulkiest single signal.
- 10 lines, 10 urls, 10 image, 10 ban-reason — strong forensic value.
- 8 timestamp, 8 room id, 8 long uid, 8 user claim — supporting forensic
  detail.
- 5 money, 5 status — escalation signals but not directly investigable.

The weights sum to 100. The maximum theoretically achievable score is
exactly 100. `.round(2)` makes the column readable in CSV exports.

This is unapologetically hand-engineered. It works because every weight
came out of a meeting where a manager said "I want a ticket with a
timestamp to score about as much as a ticket with a room ID." If you
want a learned alternative, see the OLS context-value model in
[`scripts/insight_layer.py:931-1036`](../../scripts/insight_layer.py).

## `pd.cut` for bands

```python
out["context_depth_band"] = pd.cut(
    out["context_depth_score"],
    bins=[-1, 15, 35, 60, 101],
    labels=["thin", "basic", "rich", "forensic"],
).astype(str)
```

[`scripts/option2_pipeline.py:783-787`](../../scripts/option2_pipeline.py)

`pd.cut` slices a numeric Series into labelled bins. The `bins` list
defines the edges. `bins=[-1, 15, 35, 60, 101]` produces four buckets:
`(-1, 15]`, `(15, 35]`, `(35, 60]`, `(60, 101]`. The intervals are
right-closed by default — a score of exactly 15 falls into the *first*
bucket, not the second.

Note the choice of edges:

- `-1` lower edge so that a literal 0 score is included in `thin`.
- `101` upper edge so that the rare 100-score ticket lands in `forensic`,
  not in a NaN bucket.

`labels` provides human-readable names. The result is a pandas
`Categorical`. `.astype(str)` converts to plain strings, which serialise
cleanly to CSV and are simpler to filter in the dashboard.

In the current run (`outputs/option2_20260502_150055/`), the band
distribution lands roughly at 60% thin, 30% basic, 8% rich, 2% forensic.
Most tickets are short. Most tickets that are not short are also not
heavily evidenced. The cap-and-weight design is what keeps the rare
"100-score" ticket — usually a multi-screenshot, multi-paragraph
forensic dossier — visible at the top of the band distribution rather
than buried under raw character-count outliers.

## `model_text` for embedding

```python
out["model_text"] = q.map(lambda s: URL_RE.sub(" [URL] ", normalize_space(s)).strip())
```

[`scripts/option2_pipeline.py:788`](../../scripts/option2_pipeline.py)

Substitute every URL with the literal token `[URL]`, collapse
whitespace, strip ends. The result is the input to the embedding stage.

Why strip URLs? Because every URL in this corpus is a unique high-cardinality
token. TF-IDF would treat each one as its own "word" and waste vocabulary
slots. Sentence-transformers would tokenize them into byte-pair
fragments that contribute noise to the embedding. The fact that a URL
*existed* is captured separately in `has_url`. The URL itself is dead
weight at embedding time.

This single column is the bridge to [Module 03](../03-text-and-nlp/README.md):
the `model_text` you see written to `enriched_tickets.csv` is what the
TF-IDF vectoriser and the multilingual MiniLM model both consume.

## Try it

```bash
.venv/bin/python -c '
import sys
sys.path.insert(0, "scripts")
from option2_pipeline import (
    read_raw_csv, drop_noise_columns, drop_summary_rows,
    canonicalize, featurize_tickets,
)
from pathlib import Path

raw = read_raw_csv(Path("data_2may.csv"))
cleaned, _ = drop_noise_columns(raw)
filtered, _ = drop_summary_rows(cleaned)
canon = canonicalize(filtered)
feat = featurize_tickets(canon)

print(f"rows: {len(feat)}")
print(f"\ncontext_depth_band counts:")
print(feat["context_depth_band"].value_counts())

print(f"\nprimary_desire counts (top 10):")
print(feat["primary_desire"].value_counts().head(10))

print(f"\n95th-percentile caps used by the score:")
print(f"  char_cap : {feat[\"char_count\"].quantile(0.95):.1f}")
print(f"  line_cap : {feat[\"line_count\"].quantile(0.95):.1f}")
print(f"  url_cap  : {feat[\"url_count\"].quantile(0.95):.1f}")

print(f"\ncontext_depth_score summary:")
print(feat["context_depth_score"].describe()[["mean", "50%", "max"]])
'
```

Compare your `primary_desire` value-counts with
`outputs/option2_20260502_150055/desire_summary.csv`. The largest desire
should be `grow_audience_or_community` at about 2,143 tickets, and
`clear_name_or_get_fairness` should sit around 1,603. If those numbers
match, you have just rebuilt the foundation of every chart in the
dashboard from raw text in three function calls.

[Lesson 04](04-groupby-and-aggregations.md) takes this enriched frame
and rolls it up into the per-manager and per-user summary tables.
