# Exercise 02 — Add a new user desire

## What you'll practice

- Extending the rule-based `DESIRE_PATTERNS` taxonomy.
- Understanding the `idxmax`-based "primary desire" calculation.
- Updating downstream consumers that assume the desire list is fixed.

## The setup

The current pipeline has 10 hand-coded desires. You're adding an 11th:
`request_a_refund`. The rule-based detector should match tickets that
mention "refund", "money back", "chargeback", "return my deposit", or
similar.

This is a useful exercise because it shows how a hand-coded rule
interacts with the LLM-extracted job categories. Both are taxonomies;
they don't have to align.

## Step 1 — define the regex

Open [scripts/option2_pipeline.py](../../scripts/option2_pipeline.py).
Find `DESIRE_PATTERNS` (around line 52). Add a new entry:

```python
DESIRE_PATTERNS: dict[str, re.Pattern[str]] = {
    "recover_access": ACCOUNT_RE,
    "clear_name_or_get_fairness": re.compile(r"\b(?:unban|ban|banned|block|blocked|blacklist|without reason|unfair|wrongly|appeal|reason)\b", re.I),
    "earn_or_transact_money": MONEY_RE,
    "grow_audience_or_community": GROWTH_RE,
    "gain_status_or_privileges": STATUS_RE,
    "protect_from_abuse_or_scam": REPORT_RE,
    "fix_product_or_technical_flow": TECH_RE,
    "understand_rules_or_system_logic": RULES_RE,
    "customize_identity_or_assets": re.compile(r"\b(?:gift|prop|frame|avatar|profile|custom|name|photo|badge|skin)\b", re.I),
    "play_or_entertainment": re.compile(r"\b(?:game|games|win|durak|play|guess|casino|bet)\b", re.I),
    "request_a_refund": re.compile(r"\b(?:refund|money back|chargeback|return my deposit|i want my money|reverse the (?:charge|payment))\b", re.I),  # NEW
}
```

Word-boundary anchors (`\b`) ensure "refund" doesn't match
inside "refundable" weirdly; the `re.I` flag is case-insensitive.

## Step 2 — understand `primary_desire`

Look at `featurize_tickets` (around lines 179-185):

```python
for desire, pattern in DESIRE_PATTERNS.items():
    out[f"desire__{desire}"] = q.map(lambda s, p=pattern: bool(p.search(s)))

desire_cols = [f"desire__{name}" for name in DESIRE_PATTERNS]
out["desire_count"] = out[desire_cols].sum(axis=1)
out["primary_desire"] = out[desire_cols].idxmax(axis=1).str.replace("desire__", "", regex=False)
out.loc[out[desire_cols].sum(axis=1).eq(0), "primary_desire"] = "unclear_or_needs_llm"
```

Three things happen:

1. A boolean column per desire is added (`desire__refund` etc).
2. `idxmax(axis=1)` picks the column with the *first* True value per
   row. Pandas' `idxmax` returns the first column name with the max
   value; for booleans that's the first True.
3. If no desire matched (sum is 0), `primary_desire` is set to
   `unclear_or_needs_llm`.

The order of `DESIRE_PATTERNS` matters: it determines *priority* when
multiple desires match. Your new `request_a_refund` is at the end,
so it wins only when no earlier desire (recover_access, fairness,
earn_or_transact_money, etc.) also matches. If you want refund tickets
to always be classified as refund, move the entry higher.

## Step 3 — verify the new desire matches things

Re-run stage 1:

```bash
.venv/bin/python scripts/option2_pipeline.py --input data_2may.csv --embedding-backend tfidf
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)
```

Inspect the matches:

```bash
.venv/bin/python -c "
import pandas as pd
df = pd.read_csv('$RUN_DIR/enriched_tickets.csv')
hit = df['desire__request_a_refund'].sum()
print(f'Tickets matching request_a_refund: {hit}')

# What are they classified as?
sub = df[df['desire__request_a_refund']]
print('\\nPrimary desire distribution:')
print(sub['primary_desire'].value_counts())

print('\\nSample texts:')
for _, row in sub.head(5).iterrows():
    print(f'  [{row[\"primary_desire\"]}] {row[\"question_flat\"][:100]}')
"
```

You'll likely see most tickets classified under
`earn_or_transact_money` or `clear_name_or_get_fairness` rather than
`request_a_refund`, because those desires are higher in priority order.

## Step 4 — adjust priority (optional)

If you want refund tickets to be classified as refund first, move the
entry to the top of `DESIRE_PATTERNS`:

```python
DESIRE_PATTERNS: dict[str, re.Pattern[str]] = {
    "request_a_refund": re.compile(r"\b(?:refund|money back|chargeback|return my deposit|i want my money|reverse the (?:charge|payment))\b", re.I),  # MOVED to top
    "recover_access": ACCOUNT_RE,
    ...
}
```

Re-run stage 1 and inspect again. The matches should now mostly carry
`primary_desire = "request_a_refund"`.

(In Python 3.7+, dict literals preserve insertion order, so the order
in source is the order pandas sees.)

## Step 5 — update downstream consumers

A new desire affects several downstream files. Check each:

[scripts/insight_layer.py](../../scripts/insight_layer.py) `DESIRE_COLS`:

```python
DESIRE_COLS = [
    "desire__recover_access",
    "desire__clear_name_or_get_fairness",
    "desire__earn_or_transact_money",
    "desire__grow_audience_or_community",
    "desire__gain_status_or_privileges",
    "desire__protect_from_abuse_or_scam",
    "desire__fix_product_or_technical_flow",
    "desire__understand_rules_or_system_logic",
    "desire__customize_identity_or_assets",
    "desire__play_or_entertainment",
    "desire__request_a_refund",   # NEW
]
```

Decide whether your new desire should be a *risk desire* (it adds to
`trust_money_risk`):

```python
RISK_DESIRES = {
    "clear_name_or_get_fairness",
    "earn_or_transact_money",
    "protect_from_abuse_or_scam",
    "gain_status_or_privileges",
    "fix_product_or_technical_flow",
    "request_a_refund",   # NEW — money is at stake
}
```

Adding to `RISK_DESIRES` means refund tickets will increase the
opportunity score of any cluster they fall into.

[scripts/dashboard/lib.py](../../scripts/dashboard/lib.py)
`DESIRE_LABELS`:

```python
DESIRE_LABELS = {
    "recover_access": "Recover account access",
    "clear_name_or_get_fairness": "Get fairness / appeal a ban",
    ...
    "request_a_refund": "Request a refund",   # NEW
}
```

Without this, the dashboard will fall back to
`replace("_", " ").capitalize()` which produces "Request a refund" —
correct in this case but worth being explicit.

## Step 6 — re-run downstream stages

```bash
.venv/bin/python scripts/insight_layer.py "$RUN_DIR"
```

Check the desire summary:

```bash
.venv/bin/python -c "
import pandas as pd
df = pd.read_csv('$RUN_DIR/desire_summary.csv')
print(df.to_string(index=False))
"
```

Your new `request_a_refund` row should be there with its ticket count
and unresolved share.

## Step 7 — verify in the dashboard

Restart the dashboard and look at the Find a Ticket page filter:

```bash
pkill -f streamlit
./scripts/run_dashboard.sh
# open http://localhost:8501 → Find a ticket
```

The Primary desire dropdown should now include "Request a refund".
Pick it; you'll see only the matching tickets.

## What you learned

- A hand-coded taxonomy lives in one dict with regex values.
- `idxmax(axis=1)` is the standard "first True column wins" trick;
  ordering matters.
- A new desire affects many files: `option2_pipeline.py` (the regex
  + the column), `insight_layer.py` (DESIRE_COLS, optionally
  RISK_DESIRES), `dashboard/lib.py` (display label).
- Downstream consumers don't auto-adapt; you have to update each.
- The pipeline is idempotent: re-running stage 1 produces a fresh
  timestamped output dir; old runs are unaffected.

## A note on regex vs LLM classification

Your `request_a_refund` is now a *rule-based* signal. The LLM
extraction layer (Module 06) has its own job taxonomy (JOB_VALUES) —
"refund" isn't in it directly, but it would map to
`buy_or_sell_diamonds` or `recover_access` depending on context.

The two taxonomies don't have to match. Rules are the cheap pre-filter
that sees every ticket; the LLM is the expensive deep extraction that
sees the rich subset. Adding `request_a_refund` to LLM-side taxonomy
is exercise 03.
