# Module 06 — LLMs and Prompts

By the end of Module 05 you have an `enriched_tickets.csv` with
6,728 rows, every row tagged with a BERTopic cluster ID, a
`context_depth_score`, a `primary_desire` slug, evidence flags, and
manager/category/question_kind metadata. You can fit OLS with fixed
effects, run two-proportion z-tests, and defend the numbers with
robust standard errors. You can answer questions about the *shape* of
the inbox.

You cannot answer the question every operator asks first.

"What does this user actually want?"

The cluster label tells you the topic — `svip_svip points_buy svip_level`,
or `ban audit, ban verification, ban resolution`. The
`primary_desire` slug tells you the rule-based bucket —
`recover_access`, `protect_from_abuse_or_scam`. None of that is a
sentence you can read out loud in a coaching conversation. None of
that is "this user, in row 615, wants to know why she was blocked
and is anxious that her account is permanently gone."

A human can read row 615 and write that sentence. A human cannot read
6,728 rows. The pipeline picks 250 of the highest-context tickets, sends
each one to a small local language model, and gets back a JSON object
per ticket with thirteen interpreted fields — literal_request,
actual_user_want, job_to_be_done, user_emotion, four risk levels,
evidence lists, entity extraction, support_next_step, product_opportunity,
manager_note_quality, needs_human_review, confidence.

Out of the 250 sent in our reference run on 2026-05-02, **248 came
back valid and 2 came back as `bad_output`**. Both of the `bad_output`
rows had the same failure: the model invented an enum value for
`job_to_be_done` that wasn't in our schema. That number — 2 out of 250 —
is what the rest of this module's code is designed to drive down.

This module teaches you how to use a language model the way the
pipeline uses it: as a structured-extraction tool with a defensive
prompt, a JSON schema, post-hoc validation, alias normalization, and
graceful failure. No paid API keys. The model runs on your laptop.

## Prerequisites

- [Module 01 — Python Foundations](../01-python-foundations/README.md).
  You need `urllib.request`, `json.dumps` / `json.loads`, regex,
  `dict.get(key, default)`, exception chaining with `raise ... from exc`,
  and `pathlib.Path`. The HTTP-by-stdlib pattern in
  [`ollama_chat_json`](../../scripts/llm_extract_rich_tickets.py)
  uses every one.
- [Module 02 — Data with pandas](../02-data-with-pandas/README.md).
  You need to read CSVs, do `df.merge`, use `groupby(...).head(k)`
  for per-group sampling, and the
  `astype(str).str.lower().isin([...])` defensive coercion idiom.
  [`load_candidates`](../../scripts/llm_extract_rich_tickets.py)
  in this module's main script uses all of these.
- [Module 03 — Text and NLP](../03-text-and-nlp/README.md). You
  need to remember the evidence-flag regexes (`URL_RE`, `UID_RE`,
  `TIMESTAMP_RE`) and the `context_depth_score` formula. The rules
  backend in [`call_rules`](../../scripts/llm_extract_rich_tickets.py)
  reuses this exact logic; the LLM backend gets it as input metadata.
- [Module 04 — Dimensionality and Clustering](../04-dimensionality-and-clustering/README.md).
  You need `issue_label` (the BERTopic c-TF-IDF top-words label) on
  every ticket. The user prompt template in this module passes
  `issue_label` to the LLM as a hint, so the model doesn't have to
  re-derive the topic.
- [Module 05 — Statistics](../05-statistics/README.md). You need
  the discipline of "name your failure modes". This module names
  eight failure modes for LLM output and counts each one in
  `executive_findings.md`, the same way Module 05 named "Type I
  error" and counted it.
- The `outputs/option2_20260502_150055/` run on disk. Lessons load
  [`ollama_extractions.jsonl`](../../outputs/option2_20260502_150055/ollama_extractions.jsonl),
  [`ollama_gemma3-4b_extractions.csv`](../../outputs/option2_20260502_150055/ollama_gemma3-4b_extractions.csv),
  [`local_llm_model_comparison.md`](../../outputs/option2_20260502_150055/local_llm_model_comparison.md),
  [`llm_extraction_status.json`](../../outputs/option2_20260502_150055/llm_extraction_status.json),
  [`llm_extraction_prompt.md`](../../outputs/option2_20260502_150055/llm_extraction_prompt.md),
  and [`llm_extraction_schema.json`](../../outputs/option2_20260502_150055/llm_extraction_schema.json).
- Optional: a local Ollama install with `gemma3:4b` pulled (about
  3 GB on disk). The "Try it" exercises that hit a live model need
  this; the ones that read existing extractions don't.

## What you will be able to do after this module

- Read the two system prompts —
  [`SYSTEM_PROMPT`](../../scripts/llm_extract_rich_tickets.py) used
  by the OpenAI backend and
  [`OLLAMA_SYSTEM_PROMPT`](../../scripts/llm_extract_rich_tickets.py)
  used by the local backend — and explain in one paragraph why the
  Ollama version is more defensive: it forbids label copying, schema
  echoing, and template placeholders, because small models do all three.
- Walk the
  [`USER_TEMPLATE`](../../scripts/llm_extract_rich_tickets.py)
  string format pattern: which fields go in (manager, date_raw,
  category, question_kind, status_en, primary_desire, issue_label,
  context_depth_score, text), and why grounding the prompt in upstream
  pipeline output makes the model's job easier — it doesn't have to
  re-derive what the rules layer already knows.
- Explain JSON mode at the API level:
  `response_format={"type": "json_object"}` for OpenAI versus
  `format: "json"` in the Ollama payload, and why the
  [`SCHEMA`](../../scripts/llm_extract_rich_tickets.py) dict is
  *still* embedded in the prompt even when JSON mode is on. JSON
  mode guarantees parseable JSON; it does not enforce field names
  or enum values.
- Walk the eight failure flags in
  [`output_quality_flag`](../../scripts/llm_extract_rich_tickets.py):
  `source_row_schema_echo`, `source_row_mismatch`,
  `empty_required_fields`, `schema_echo`, `invalid_job`,
  `invalid_emotion`, `too_vague`, plus the per-field validation in
  [`is_concrete_phrase`](../../scripts/llm_extract_rich_tickets.py)
  (length floor, snake_case rejection, `GENERIC_PHRASES` blacklist,
  per-field length, per-field semantic-term requirement).
  Reproduce the 250 / 248 / 2 split from
  [`ollama_extractions.jsonl`](../../outputs/option2_20260502_150055/ollama_extractions.jsonl)
  and identify the exact source rows that triggered each
  `invalid_job` flag — row 5990 (`job_to_be_done="angry"`, an
  emotion leaked into the job slot) and row 2739
  (`job_to_be_done="gain_status_or_privileges"`, the model invented
  a verbose synonym for `gain_status`).
- Read the
  [`JOB_ALIASES`](../../scripts/llm_extract_rich_tickets.py) dict
  and explain the design choice: instead of scolding the model when
  it says `investigate_fraud`, accept it and rewrite to `avoid_scam`,
  recording the original token in `_normalized_job_from`. This is
  schema evolution without breaking past extractions, and it's what
  separates a research script from a production pipeline.
- Pick the right backend for a job. The four backends in
  [`run_extraction`](../../scripts/llm_extract_rich_tickets.py) —
  `rules`, `ollama`, `ollama_hybrid`, `openai` — each serve a
  different question. Rules is free and reproducible. Ollama is
  free, private, and slow. Ollama_hybrid is the project's daily
  default: rules-layer skeleton plus LLM narrative. Openai is the
  premium option that we don't actually use because of cost.
- Compare the three Gemma sizes in
  [`local_llm_model_comparison.md`](../../outputs/option2_20260502_150055/local_llm_model_comparison.md):
  `gemma3:270m` returned 0/10 valid rows on smoke test;
  `gemma3:1b` direct returned 9/10 but collapsed all jobs into
  `recover_access`; `gemma3:4b` returned 50/50 and produced 8 distinct
  job values. 4 B is the smallest usable size for our task. Cite
  the table and explain *why* — small models can't hold the schema
  and the ticket and a coherent answer in working memory at once.

## Lessons

| # | Lesson | What it covers |
|---|---|---|
| 01 | [What is a prompt](01-what-is-a-prompt.md) | Prompts vs API params. The system/user role split. `SYSTEM_PROMPT` vs `OLLAMA_SYSTEM_PROMPT`. Why `temperature=0`. Grounding the model with metadata. |
| 02 | [JSON mode and schemas](02-json-mode-and-schemas.md) | The `SCHEMA` dict; why we serialise it into the prompt. OpenAI's `response_format={"type":"json_object"}` vs Ollama's `format:"json"`. What JSON mode does and doesn't enforce. |
| 03 | [Defensive prompting](03-defensive-prompting.md) | How small models fail: schema echo, snake_case in narrative, enum drift, over-collapse. Each "do not" line as a scar. |
| 04 | [Validation and quality flags](04-validation-and-quality-flags.md) | All eight failure flags walked. `is_concrete_phrase` rules. The 250 / 248 / 2 split reproduced. |
| 05 | [Enum aliases and normalization](05-enum-aliases-and-normalization.md) | `JOB_ALIASES`. `normalize_result_enums`. Why we map `investigate_fraud` → `avoid_scam` instead of rejecting. Schema evolution. |
| 06 | [Rules vs LLM vs hybrid](06-rules-vs-llm-vs-hybrid.md) | Four backends: rules / ollama / ollama_hybrid / openai. Why hybrid: rules classify, LLM writes only narrative. |
| 07 | [Local models with Ollama](07-local-models-with-ollama.md) | `urllib.request` to `localhost:11434/api/chat`. The `format:"json"` + `temperature:0` payload. `gemma3:270m` vs `1b` vs `4b` benchmarks. |

Each lesson lands at 1500-2500 words and ends with a runnable "Try it" against
`outputs/option2_20260502_150055/` or against a local Ollama instance.

## What's next

- [Module 07 — Databases and Storage](../07-databases-and-storage/README.md)
  loads the 250 extractions into `analysis.duckdb` for cross-cluster joins.
- [Module 09 — Streamlit Dashboards](../09-streamlit-dashboards/README.md)
  renders the extracted want / job / next-step strings into live pages.
- [Module 11 — The Findings](../11-the-findings/README.md) tells the
  business story the extractions tell.
