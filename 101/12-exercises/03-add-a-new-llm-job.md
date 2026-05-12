# Exercise 03 — Add a new LLM job category

## What you'll practice

- Extending the LLM-side `JOB_VALUES` enum.
- Updating the prompt and schema documentation in lockstep.
- Adding an alias to handle synonyms the model might emit.
- Wiring the rules-based fallback to use the new job.
- Re-running Stage 5 + 6 and verifying.

## The setup

You're adding a new job-to-be-done: `request_a_refund`. The LLM should
emit it when the user is asking the platform to return money already
paid (not just complain about a transaction). The existing
`buy_or_sell_diamonds` job covers commerce flows in general; the new
one is the specific subset where a refund is the explicit ask.

## Step 1 — add the value to JOB_VALUES

Open
[scripts/llm_extract_rich_tickets.py](../../scripts/llm_extract_rich_tickets.py).
Find `JOB_VALUES` (around line 73):

```python
JOB_VALUES = [
    "recover_access",
    "prove_innocence",
    "restore_income",
    "grow_channel",
    "avoid_scam",
    "buy_or_sell_diamonds",
    "gain_status",
    "understand_punishment",
    "restore_visibility",
    "protect_community",
    "fix_product_flow",
    "customize_identity",
    "other",
    "request_a_refund",   # NEW
]
```

The list-of-strings is duplicated in two other places: the SCHEMA dict
description, and the prompt text. Update both.

## Step 2 — update the SCHEMA description

Find `SCHEMA` (around line 23):

```python
SCHEMA: dict[str, Any] = {
    "source_row": "string",
    "literal_request": "short string: what the user explicitly asked for",
    "actual_user_want": "short string: deeper user want behind the request",
    "job_to_be_done": "one of: recover_access, prove_innocence, restore_income, grow_channel, avoid_scam, buy_or_sell_diamonds, gain_status, understand_punishment, restore_visibility, protect_community, fix_product_flow, customize_identity, request_a_refund, other",
    ...
}
```

Add `request_a_refund` before `other`. The order doesn't matter
mechanically (the validator uses set membership), but the description
should be readable.

## Step 3 — add a JOB_ALIASES entry

The model might emit synonyms instead of the canonical value. Add the
likely ones to `JOB_ALIASES` (around line 91):

```python
JOB_ALIASES = {
    "investigate_fraud": "avoid_scam",
    "report_fraud": "avoid_scam",
    "fraud_report": "avoid_scam",
    "verify_ban_and_reason": "understand_punishment",
    "ban_verification": "understand_punishment",
    "unblock_account": "recover_access",
    "restore_account": "recover_access",
    "account_recovery": "recover_access",
    "refund": "request_a_refund",                 # NEW
    "money_refund": "request_a_refund",           # NEW
    "chargeback": "request_a_refund",             # NEW
    "return_funds": "request_a_refund",           # NEW
}
```

These map the model's drift to the canonical value. The audit field
`_normalized_job_from` records the original.

## Step 4 — update the rules backend

The rules backend in `call_rules` (around line 550) classifies
tickets into jobs deterministically. It currently doesn't know about
refunds. Add a check.

Find the priority cascade (around line 580-605):

```python
if has_game_complaint:
    job = "fix_product_flow"
elif primary_desire == "protect_from_abuse_or_scam" or has_scam_report:
    job = "avoid_scam"
elif has_abuse_report:
    job = "protect_community"
elif has_claim or has_ban:
    job = "prove_innocence"
elif primary_job:
    job = primary_job
elif has_scam:
    job = "avoid_scam"
elif has_transaction:
    job = "buy_or_sell_diamonds"
elif has_room:
    job = "grow_channel"
elif has_account:
    job = "recover_access"
elif has_status:
    job = "gain_status"
else:
    job = "other"
```

Add a refund check above `has_transaction` because a refund mention
should override generic commerce:

```python
has_refund = bool(re.search(r"\b(?:refund|money back|chargeback|return my deposit|reverse the charge)\b", text, re.I))
...
elif has_claim or has_ban:
    job = "prove_innocence"
elif primary_job:
    job = primary_job
elif has_refund:                              # NEW
    job = "request_a_refund"                  # NEW
elif has_scam:
    job = "avoid_scam"
elif has_transaction:
    job = "buy_or_sell_diamonds"
...
```

You also need to add an `actual_user_want` and `support_next_step` /
`product_opportunity` for the new job. Find the `actual` dict
(around line 665):

```python
actual = {
    "avoid_scam": "User wants protection or redress from a scam/fraud dispute.",
    "buy_or_sell_diamonds": "User wants a safer money/diamonds transaction path.",
    ...
    "other": "User wants support to interpret and resolve a product/support problem.",
    "request_a_refund": "User wants money already paid returned to them.",   # NEW
}[job]
```

And the per-job `next_step` / `product` dispatch (around line 681):

```python
elif job == "request_a_refund":                                # NEW
    next_step = (                                              # NEW
        "Verify the original transaction, the payment method, and "
        "the eligibility for refund per platform policy."
    )
    product = (
        "Build a self-service refund flow with status tracking, "
        "policy-based eligibility checks, and a transparent denial path."
    )
```

## Step 5 — re-run Stage 5 with the rules backend

The rules backend is the cheapest way to verify your change:

```bash
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)
.venv/bin/python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend rules --limit 250 --strategy risk_balanced
```

Check the new job:

```bash
.venv/bin/python -c "
import pandas as pd
df = pd.read_csv('$RUN_DIR/rules_extractions.csv')
print('Job distribution:')
print(df['job_to_be_done'].value_counts())
"
```

You should see `request_a_refund` in the list (likely 0 or a small
number, because the dataset doesn't have many refund-explicit tickets).

## Step 6 — re-run Stage 5 with Gemma

Now the LLM-side test (requires Ollama running with `gemma3:4b`):

```bash
.venv/bin/python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend ollama --model gemma3:4b --limit 50 --strategy risk_balanced
```

Inspect:

```bash
.venv/bin/python -c "
import pandas as pd
df = pd.read_csv('$RUN_DIR/ollama_gemma3-4b_extractions.csv')
print('Job distribution:')
print(df['job_to_be_done'].value_counts())
print()
print('Refund tickets:')
sub = df[df['job_to_be_done'] == 'request_a_refund']
print(sub[['source_row', 'literal_request', 'actual_user_want']].to_string(index=False))
"
```

If Gemma identified any refund tickets, you'll see them. If it
emitted aliases (e.g. `refund`), they'd be normalised to
`request_a_refund` automatically by the alias map.

## Step 7 — re-run Stage 6 to update the taxonomy

The user-want taxonomy is built from the LLM extractions. Re-run:

```bash
.venv/bin/python scripts/build_user_wants_taxonomy.py "$RUN_DIR"
```

If refund tickets are abundant enough, a new cluster might emerge. If
not, they'll fold into existing clusters (recover_access, money/diamonds).

```bash
.venv/bin/python scripts/label_user_wants.py "$RUN_DIR" --force
```

(`--force` regenerates Gemma labels for every cluster, including any
that have shifted.)

## Step 8 — verify in the dashboard

```bash
./scripts/run_dashboard.sh
# Compare Local Models page → pick rules vs ollama_gemma3-4b
```

You'll see job comparisons across backends, including your new job.

## Step 9 — handle invalid_job downgrade

If the model emits a value not in `JOB_VALUES` and not in
`JOB_ALIASES`, the validation step flags `_status = "bad_output"`
with `_quality_flag = "invalid_job"`. Run:

```bash
.venv/bin/python -c "
import pandas as pd
df = pd.read_csv('$RUN_DIR/ollama_gemma3-4b_extractions.csv')
flagged = df[df['_quality_flag'] == 'invalid_job']
print(f'Invalid-job count: {len(flagged)}')
if len(flagged):
    print(flagged[['source_row', 'job_to_be_done', '_normalized_job_from']].to_string(index=False))
"
```

If you see a recurring synonym in the output (e.g. `money_back`), add
it to `JOB_ALIASES`. This is how the alias map grows organically.

## What you learned

- The LLM-side taxonomy lives in three places: `JOB_VALUES` (the
  canonical list), `SCHEMA["job_to_be_done"]` (the description shown
  to the model), and the prompt text (which inlines the same list).
  All three must agree.
- `JOB_ALIASES` is the safety net for model drift. Add aliases as you
  observe them.
- The rules backend has its own classification logic (priority
  cascade, regex checks). Adding a new job means deciding the rule
  *and* adding the canonical narrative phrases.
- Re-running Stage 5 + 6 is fast enough to iterate quickly; the
  dashboard surfaces changes immediately.
- Schema evolution doesn't break old runs because each run has its
  own files. New runs use the new schema; old runs are frozen.

## When to add a new job vs an alias

Rule of thumb:

- If the new value represents a *meaningfully different intent* (refund
  vs general commerce dispute), add a new job.
- If the new value is a *synonym* of an existing intent (e.g. the
  model writes `regain_access` for `recover_access`), add to
  `JOB_ALIASES`.

The taxonomy should stay small (under ~15 jobs) so the model can
reliably learn it. Aliases are unlimited; canonical jobs should be
sparse.
