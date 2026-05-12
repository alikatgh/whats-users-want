# 05 — Enum aliases and normalization

You wrote a 13-value enum for `job_to_be_done`. The model returned
`"investigate_fraud"`. That isn't in your enum. Two ways to handle
it.

The first: tighten the prompt, scold the model, hope it picks
`"avoid_scam"` next time. Maybe also reject the row.

The second: notice that `"investigate_fraud"` is a perfect
synonym for `"avoid_scam"`. The model is right about the meaning
and wrong about the vocabulary. Accept the answer, rewrite it to
the canonical token, record the original in an audit field, and
move on.

The project picks the second. This lesson teaches you why, walks
the
[`JOB_ALIASES`](../../scripts/llm_extract_rich_tickets.py)
map and the
[`normalize_result_enums`](../../scripts/llm_extract_rich_tickets.py)
function, and explains how this pattern lets the schema evolve
without breaking past extractions.

## The alias problem

Different models settle on different vocabularies for the same
concept. `gemma3:4b` likes `"investigate_fraud"`. `gemma3:1b`
sometimes returns `"unblock_account"`. GPT-4-class models tend
to stay in your enum because they have the capacity to follow
your instructions, but small models drift.

The drift isn't random. It clusters around concepts that have
multiple natural English names. "Fraud investigation" and "scam
avoidance" name the same thing from different sides. "Unblock
account" and "recover access" describe the same operation.
"Verify ban and reason" and "understand punishment" point at
the same user goal. The model, asked to pick a word, picks one
of several reasonable choices, and the choice depends on
training data.

If you reject every reasonable-but-non-canonical answer, you
lose data. If you don't reject anything, your enum stops being
an enum — every analyst downstream has to handle every variant.
The project's compromise: accept a curated list of aliases at
the validation step, rewrite them to canonical tokens, and
preserve the original via an audit field. The rest of the
pipeline sees only canonical values.

## The JOB_ALIASES dict

[`JOB_ALIASES`](../../scripts/llm_extract_rich_tickets.py) is a
flat dict, alias -> canonical:

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
}
```

Eight aliases mapping to four canonical jobs. Read them as
"forward dictionary": when the model says X, treat it as Y.

The list is hand-curated. Each entry is here because we saw the
model emit it in a real run, and decided that the model's
intent matched the canonical token. The decisions are
documented implicitly by the existence of the entry — if you
wonder why `"unblock_account"` maps to `"recover_access"`, the
answer is "the rules layer's `recover_access` job covers
unblock-account requests, and the model picking
`"unblock_account"` clearly means the same thing."

The map is one-way. Many aliases point to one canonical token.
There's no reverse direction (you can't ask "what aliases does
`recover_access` have?") because the canonical token is the
one we use everywhere downstream and the aliases only exist as
input cleanup.

## normalize_result_enums

The rewrite happens in
[`normalize_result_enums`](../../scripts/llm_extract_rich_tickets.py):

```python
def normalize_result_enums(result: dict[str, Any]) -> dict[str, Any]:
    job = str(result.get("job_to_be_done", "")).strip()
    if job in JOB_ALIASES:
        result["job_to_be_done"] = JOB_ALIASES[job]
        result["_normalized_job_from"] = job
    emotion = str(result.get("user_emotion", "")).strip()
    if emotion == "stressed":
        result["user_emotion"] = "anxious"
        result["_normalized_emotion_from"] = emotion
    return result
```

Three things to notice.

First: the function mutates `result` in place *and* returns it.
That's a Python convention — pandas methods do the same. It lets
callers either rely on the mutation (`normalize_result_enums(r)`
and continue using `r`) or chain (`r =
normalize_result_enums(r)`). The implementation is the same; the
caller picks the style.

Second: when an alias is rewritten, the original token is stored
in `_normalized_job_from`. This is the audit trail. Downstream
analysis can filter on `_normalized_job_from.notna()` to count
"how often did the model pick a non-canonical token". If a model
upgrade changes the rate, you can see it in the diff.

Third: emotion has only one alias, hardcoded:
`"stressed"` rewrites to `"anxious"`. The dict + loop pattern
isn't worth it for one entry, so the code uses an `if`. If a
second emotion alias appears, the right move is to extract an
`EMOTION_ALIASES` dict and parallel the job logic. For now,
one entry, one branch.

## Where normalization runs in the pipeline

The order of operations matters. Look at
[`run_extraction`](../../scripts/llm_extract_rich_tickets.py):

```python
result = call_rules(row)  # or call_ollama, etc.
result = normalize_result_enums(result)
quality_flag = output_quality_flag(result, source_row) if backend in {"ollama", "ollama_hybrid", "openai"} else None
result["_status"] = "bad_output" if quality_flag else "ok"
```

Normalization runs *before* validation. That ordering is the
whole point of the alias map.

If validation ran first, every row with `"investigate_fraud"`
would be flagged `invalid_job`. The validator would do its job
and the dataset would have eight rows (or however many the
model emitted) tagged bad_output despite being semantically
fine.

By normalizing first, the eight aliased rows get rewritten to
their canonical tokens *before* the validator looks at them. The
validator sees only un-aliasable failures — values the model
invented that we haven't decided are equivalent to anything in
the enum.

In our reference run, the two `invalid_job` rows had values
`"angry"` and `"gain_status_or_privileges"`. Neither is in
`JOB_ALIASES`. `"angry"` is wrong (it's an emotion, not a job;
field confusion). `"gain_status_or_privileges"` is a synonym we
hadn't seen before and could legitimately add to the alias map
on the next iteration.

The two-step (normalize, then validate) is what gives the
operator a clean failure rate. Without normalization, more rows
would fail validation — but the failures would be a mix of "real
errors the model got wrong" and "synonyms the model got right".
Mixing those makes the failure rate uninformative. With
normalization, the failures are *only* the things actually wrong.

## Why not just expand the enum?

A natural question: if `"investigate_fraud"` is fine, why not
just add it to `JOB_VALUES` and let the validator accept it?

Two reasons.

First, downstream consistency. Every dashboard, every analysis,
every join keys on the canonical job tokens. If the dataset has
both `"avoid_scam"` and `"investigate_fraud"`, the dashboard
would have to merge them at every read. Some readers would
forget. Bugs would creep in. Consolidating at the source — the
alias map — keeps every downstream consumer simple.

Second, schema clarity. `JOB_VALUES` is the "official enum",
the contract you'd document for an API consumer. Each value
should mean one thing. A list with eight near-synonyms is hard
to reason about and hard to use. A list with thirteen distinct
concepts plus an alias map is easier to explain: "the schema
has thirteen jobs; here are the variant spellings we accept."

The alias map is also easier to extend than the enum. Adding
`"unblock_account": "recover_access"` to the dict is a one-line
diff that doesn't change the schema. Adding `unblock_account`
to `JOB_VALUES` would be a schema change that all downstream
code has to handle.

## Schema evolution without breaking past extractions

The alias map gives you something subtle: it lets you change
how the model is *prompted* without changing how the dataset is
*shaped*.

Suppose six months from now you upgrade to a larger model that
produces `"escalate_to_finance"` for some tickets. You decide
that's the same as `"buy_or_sell_diamonds"` in your dataset
(they both relate to monetary disputes). You add one line to
`JOB_ALIASES`:

```python
"escalate_to_finance": "buy_or_sell_diamonds",
```

Past extractions don't need re-running. They already have
canonical tokens. New extractions will pick up the new alias.
Your dashboard code, which only ever sees the 13 canonical
values, doesn't need to change.

If you'd added `"escalate_to_finance"` to `JOB_VALUES` instead,
you'd have a 14-value enum. Every downstream consumer would
need to handle the new value. Re-running the past extractions
to migrate them would be expensive (hours of model time and
maybe some new failures the migration introduces).

The alias map is a one-way pressure valve: model vocabulary
changes get absorbed without forcing schema changes.

## When NOT to add an alias

The alias map can become a liability if you over-extend it.
Three rules of thumb.

**Don't alias semantically distinct concepts.** Suppose the
model returns `"prove_innocence"` for a ticket about lost
diamonds. Mapping `"prove_innocence" -> "buy_or_sell_diamonds"`
would hide the model's actual error, making the dataset look
clean while burying a real classification failure. Aliases
should only consolidate *true synonyms*.

**Don't alias confusion between fields.** `"angry"` is an
emotion that leaked into the job slot. Adding `"angry":
"protect_community"` (or any job) would paper over a different
kind of failure — the model doesn't understand which field is
which. Better to let the validator flag it as `invalid_job` and
investigate the prompt.

**Don't alias values that would distort downstream stats.** If
`"unblock_account"` is genuinely a different thing from
`"recover_access"` in your operational world (say, one is a
ban appeal and the other is a forgotten password), aliasing
them collapses two distinct categories into one. Be sure the
alias is faithful before you commit it.

The eight aliases in the current map all pass these tests.
`investigate_fraud / report_fraud / fraud_report` -> `avoid_scam`:
true synonyms, the user wants the same outcome.
`verify_ban_and_reason / ban_verification` -> `understand_punishment`:
both about ban transparency.
`unblock_account / restore_account / account_recovery` ->
`recover_access`: the rules layer treats all three identically,
so the alias is faithful.

## Tracking aliases in the executive report

Every run writes
[`executive_findings.md`](../../outputs/option2_20260502_150055/executive_findings.md)
with a section that includes job distribution. If a row was
aliased, its canonical job appears in the count, but the audit
field `_normalized_job_from` survives in the JSONL.

A simple analysis you can do over multiple runs: count alias
hits. If the rate of `_normalized_job_from = "investigate_fraud"`
goes up after a model upgrade, that's evidence the new model
prefers `"investigate_fraud"` more than the old one. You can
either tighten the prompt to push the model back toward
`"avoid_scam"`, or accept the drift and let the alias map
handle it.

The flexibility is what makes the design last. Six months from
now, you might be on a different model entirely, with a
different vocabulary preference. The alias map captures the
mapping; the rest of the pipeline doesn't notice.

## Try it

Read the JSONL, count alias hits, and identify which canonical
tokens absorb the most variation.

```python
import json
from collections import Counter
from pathlib import Path

run_dir = Path("outputs/option2_20260502_150055")
alias_hits = Counter()
canonical_counts = Counter()

with (run_dir / "ollama_extractions.jsonl").open() as f:
    for line in f:
        r = json.loads(line)
        canonical_counts[r["job_to_be_done"]] += 1
        if "_normalized_job_from" in r:
            alias_hits[(r["_normalized_job_from"], r["job_to_be_done"])] += 1
        if "_normalized_emotion_from" in r:
            print(f"row {r['source_row']}: emotion '{r['_normalized_emotion_from']}' -> '{r['user_emotion']}'")

print("Job distribution (canonical):")
for job, n in canonical_counts.most_common():
    print(f"  {job}: {n}")

print("\nAlias hits (alias -> canonical):")
for (alias, canonical), n in alias_hits.most_common():
    print(f"  {alias} -> {canonical}: {n}")
```

In our reference run on `gemma3:4b`, you should see most rows
land on canonical values directly — the prompt is strong enough
that the model rarely emits aliases. The two `bad_output` rows
have `_quality_flag` set but not `_normalized_job_from`, because
their values aren't in the alias map.

Bonus: read
[`ollama_gemma3-1b_extractions.jsonl`](../../outputs/option2_20260502_150055/ollama_gemma3-1b_extractions.jsonl)
(if it exists) and run the same analysis. The smaller model
emitted more aliases — because the alias map exists, those rows
came back valid in the canonical schema. Without the alias map,
they'd have been `invalid_job` failures and the smaller model
would look much worse than it actually was. The map is what
makes a smaller model viable as a fallback.

Bonus 2: identify a candidate alias to add. Pick a row from
your most recent run with `_quality_flag == "invalid_job"`. Read
the `job_to_be_done` value. Decide whether it's a true synonym
for an existing canonical token. If yes, add a line to
`JOB_ALIASES` and re-run normalization on the JSONL. If no
(it's a confused or wrong classification), don't add it. The
exercise is the most important pattern in this lesson:
distinguishing "vocabulary drift" from "classification error"
is what keeps the alias map honest.
