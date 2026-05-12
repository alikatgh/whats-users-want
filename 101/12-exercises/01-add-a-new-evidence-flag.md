# Exercise 01 — Add a new evidence flag

## What you'll practice

- Writing a regex that matches a new piece of evidence in ticket text.
- Adding a boolean column to the enriched DataFrame.
- Wiring the flag into `context_depth_score` with an appropriate weight.
- Re-running the pipeline end-to-end and checking the new flag.

## The setup

Suppose your team adds a new field to ticket forms: users can paste a
`/feedback#` link to a feedback form they previously filled in. You
want every ticket that contains such a link to score higher on
evidence depth, because it indicates the user has already engaged with
the platform's feedback system.

The flag will be called `has_feedback_link`. Its weight should be 5
(same as `has_money_terms` — it's a soft signal, not as strong as a
screenshot or a ban reason).

## Step 1 — write the regex

Open [scripts/option2_pipeline.py](../../scripts/option2_pipeline.py).
Find the regex constants block near the top of the file (around line
29-50). Add a new regex below the existing ones:

```python
FEEDBACK_LINK_RE = re.compile(r"/feedback#[A-Za-z0-9_-]+", re.I)
```

Walk the regex:

- `/feedback#` — literal prefix.
- `[A-Za-z0-9_-]+` — one or more letters, digits, underscores, or
  hyphens (the feedback ID).
- `re.I` — case-insensitive flag.

Test it interactively:

```bash
.venv/bin/python -c "
import re
p = re.compile(r'/feedback#[A-Za-z0-9_-]+', re.I)
print(p.findall('see /feedback#abc-123 and /Feedback#XY_42 and nothing here'))
"
```

You should see `['/feedback#abc-123', '/Feedback#XY_42']`.

## Step 2 — add the flag column

Find `featurize_tickets` (around line 152). Locate the block where
existing flags are computed:

```python
out["has_url"] = out["url_count"].gt(0)
out["has_image_url"] = out["image_url_count"].gt(0)
out["has_timestamp"] = out["timestamp_count"].gt(0)
...
```

Add your flag right after the URL flags:

```python
out["has_feedback_link"] = q.map(lambda s: bool(FEEDBACK_LINK_RE.search(s)))
```

The `q.map(lambda s: bool(...))` pattern is from
[Module 02 lesson 03](../02-data-with-pandas/03-feature-engineering.md).
`q` is the question-text Series. The lambda returns True if the regex
matches anywhere in the string.

## Step 3 — wire it into the score

The `context_depth_score` formula is below the flag declarations
(around line 193). Add your flag with a weight of 5:

```python
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
    + 5 * out["has_feedback_link"].astype(int)   # NEW
).round(2)
```

Why weight 5: the existing 5-point flags are "money terms" and "SVIP
terms" — soft signals. A feedback link is similar weight. Stronger
evidence (screenshots, ban reasons) gets 10. Weak signals get 5.

## Step 4 — add the flag to EVIDENCE_LABELS

The `EVIDENCE_LABELS` list (around line 65) controls which flags
contribute to `evidence_element_count`. Add yours:

```python
EVIDENCE_LABELS = [
    "has_url",
    "has_image_url",
    "has_timestamp",
    "has_room_or_group_id",
    "has_long_uid_or_case_id",
    "has_ban_reason_language",
    "has_user_claim",
    "has_money_terms",
    "has_status_or_svip_terms",
    "has_multiline_note",
    "has_feedback_link",   # NEW
]
```

## Step 5 — verify the change

Re-run stage 1:

```bash
.venv/bin/python scripts/option2_pipeline.py --input data_2may.csv --embedding-backend tfidf
```

It will create a new `outputs/option2_<NEW_TIMESTAMP>/` directory.
Inspect the new flag:

```bash
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)
.venv/bin/python -c "
import pandas as pd
df = pd.read_csv('$RUN_DIR/enriched_tickets.csv')
print('Total tickets:', len(df))
print('With feedback link:', df['has_feedback_link'].sum())
print('Sample tickets:')
print(df.loc[df['has_feedback_link'], ['source_row', 'manager', 'question_flat']].head(5).to_string())
"
```

If the dataset doesn't contain `/feedback#` URLs (it likely doesn't —
this is a synthetic exercise), the count will be 0 and that's fine.
The flag is wired correctly and ready for future tickets that do have
the link.

## Step 6 — verify the score change

Compare the score distribution before and after. With no `/feedback#`
links in the data the change should be zero. To confirm the wiring,
manually inject a fake feedback link into one ticket:

```bash
.venv/bin/python -c "
import re, sys
sys.path.insert(0, 'scripts')
import option2_pipeline as op

# Fake ticket text with a feedback link
text = 'I cannot login. See /feedback#bug-2025-04-15 for context.'
print('FEEDBACK_LINK_RE match:', op.FEEDBACK_LINK_RE.findall(text))
"
```

If you see the link in the output, the regex is wired into the module
correctly.

## Step 7 — update the EVIDENCE_COLS in insight_layer (optional)

[scripts/insight_layer.py](../../scripts/insight_layer.py) has a
similar list at the top:

```python
EVIDENCE_COLS = [
    "has_url",
    "has_image_url",
    ...
    "has_multiline_note",
]
```

Add `"has_feedback_link"` here too so the manager evidence-coaching
table includes it. Otherwise the insight layer runs but the new flag
is invisible in coaching outputs.

```python
EVIDENCE_COLS = [
    "has_url",
    "has_image_url",
    "has_timestamp",
    "has_room_or_group_id",
    "has_long_uid_or_case_id",
    "has_ban_reason_language",
    "has_user_claim",
    "has_money_terms",
    "has_status_or_svip_terms",
    "has_multiline_note",
    "has_feedback_link",   # NEW
]
```

Add a friendly label too. Find the `label_map` dict in
`build_manager_evidence_coaching` and add:

```python
label_map = {
    "has_url": "attach source links/screens",
    ...
    "has_multiline_note": "write structured multiline notes",
    "has_feedback_link": "include the user's feedback-form link",   # NEW
}
```

Re-run stage 3:

```bash
.venv/bin/python scripts/insight_layer.py "$RUN_DIR"
```

The `manager_evidence_coaching.csv` will now have a `has_feedback_link_share`
column. Open it in the dashboard's "Manager Note Quality" page (or
just `pd.read_csv` it) to confirm.

## What you learned

- Regex compilation lives at module top, named with `_RE` suffix
  convention.
- Boolean flags are derived once in `featurize_tickets` and used
  everywhere downstream.
- The `context_depth_score` formula is a weighted sum where weights
  encode editorial judgment (10 = strong evidence, 8 = medium, 5 =
  weak).
- Adding a flag means updating four touch-points: regex, flag
  computation, weight in score, EVIDENCE_LABELS list (+ optionally
  EVIDENCE_COLS in insight_layer).
- Re-running the pipeline produces a *new* timestamped directory; you
  never modify old runs in place.

## Cleanup

If you don't want to keep the new flag, revert by removing the regex,
the flag column, the score term, and the EVIDENCE_LABELS entry. The
test run directories under `outputs/` can be deleted with
`rm -rf outputs/option2_<TS>`.
