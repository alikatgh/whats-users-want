# 05 — Stage 5: `llm_extract_rich_tickets.py`

[Source](../../scripts/llm_extract_rich_tickets.py).

The biggest, most defensive script. It picks rich tickets, builds a prompt, sends them to an LLM (or a deterministic rule layer), validates the output, normalizes enum aliases, flags bad model output without throwing it away, and supports resume.

## Why so much code

Small local models can hallucinate, return schema fragments, refuse to fill required fields, or invent enum values. We accepted this as a fact and built validation, normalization, structured-output schemas, and quality flagging around it instead of trusting the model blindly.

## Schema (lines 23-49)

The JSON we want back. Every field has a description; the model is shown this schema.

```python
SCHEMA = {
    "source_row": "string",
    "literal_request": "short string",
    "actual_user_want": "short string",
    "job_to_be_done": "one of: recover_access, prove_innocence, restore_income, ...",
    "user_emotion": "one of: neutral, confused, anxious, angry, ...",
    "urgency_level": "integer 1-5",
    "trust_risk_level": "integer 1-5",
    "money_risk_level": "integer 1-5",
    "safety_policy_risk_level": "integer 1-5",
    "evidence_present": [...],
    "evidence_missing": [...],
    "entities": {
        "uids": [...],
        "room_or_group_ids": [...],
        "timestamps": [...],
        "ban_reasons": [...],
        "money_or_diamond_amounts": [...],
        "counterparties": [...],
        "url_count": "integer",
    },
    "support_next_step": "specific next operational action",
    "product_opportunity": "what product/system should exist...",
    "manager_note_quality": "one of: thin, adequate, rich, forensic",
    "needs_human_review": "boolean",
    "confidence": "number 0-1",
}
```

## Prompts

### `SYSTEM_PROMPT` (lines 51-56) — for OpenAI

```
You are analyzing messy support tickets from IMO/BIGO-style support operations.
Extract what the user actually wants, not only the literal category.
Preserve uncertainty. Do not invent facts. If evidence is missing, say what is missing.
Treat screenshots/URLs/timestamps/ban reasons/IDs as evidence, not noise.
Return exactly one JSON object matching the requested schema. No markdown.
```

### `OLLAMA_SYSTEM_PROMPT` (lines 102-107) — tighter, for small local models

```
You extract support-ticket meaning into JSON.
Infer the user's real goal from the ticket. Do not copy labels, enum lists, or template placeholders.
Write concrete short phrases, not enum tokens, for literal_request, actual_user_want, support_next_step, and product_opportunity.
If unsure, use "other", "unknown", empty lists, and lower confidence.
Return one valid JSON object only.
```

This is **deliberately different** from the OpenAI prompt. Small models tend to:
- Echo the schema back as values ("one of: recover_access, ...").
- Use snake_case enum tokens for free-text fields.
- Repeat template placeholders.

The Ollama prompt explicitly forbids each of those.

### `HYBRID_OLLAMA_SYSTEM_PROMPT` (lines 109-113)

For the `ollama_hybrid` backend. The model is told that classification, IDs, evidence, and risk are already done by rules; it should only write the human-language interpretation fields.

### `USER_TEMPLATE` (lines 58-71)

Per-ticket prompt body:

```
Ticket metadata:
source_row: {source_row}
manager: {manager}
date: {date_raw}
category: {category}
question_kind: {question_kind}
status: {status_en}
primary_desire_rule_based: {primary_desire}
semantic_issue_label: {issue_label}
context_depth_score: {context_depth_score}

Ticket text:
{text}
```

`{issue_label}` comes from BERTopic / outlier subtopic if available. Giving the model the prior cluster label as a hint (without forcing it) materially improves enum stability.

## Candidate selection

`load_candidates(run_dir, limit, min_context_score, strategy, max_chars)` (lines 164-227).

Reads `enriched_tickets.csv`, optionally joins outlier subtopic + BERTopic labels, then filters:

```
rich = df[context_depth_score >= 24 AND len(question_flat) >= 40]
```

Three sampling strategies:

- **`highest_context`** — top N by `context_depth_score` (descending), tie-break by `char_count`.
- **`risk_balanced`** — adds a `risk_score = sum(money, status, ban_reason, user_claim) + is_unresolved`, sorts by `(risk_score, context_depth_score)` descending. **This is what the current 250-ticket run used.**
- **`issue_balanced`** — round-robin top context examples per `issue_label`, padded with leftover top-context if there aren't enough issues.

Final columns kept: `source_row, date_raw, manager, uid, category, question_kind, status_en, primary_desire, issue_label, context_depth_score, context_depth_band, char_count, url_count, image_url_count, timestamp_count, room_or_group_id_count, llm_input_text` (a compact-truncated version of the question, capped at `max_chars=6500` chars by default).

## Backends

Four backends, all share the same per-ticket dispatch in `run_extraction`.

### `call_openai(row, model)` (lines 256-274)

Standard `chat.completions.create` with `temperature=0`, `response_format={"type": "json_object"}`. Single-shot, JSON mode forced by API. Requires `OPENAI_API_KEY`.

### `call_ollama(row, model, ollama_url, timeout)` (lines 350-375)

Uses the local JSON template (full schema). The prompt includes the entire schema as a JSON template plus an explicit list of allowed enum values.

```python
ollama_chat_json(model, ollama_url, timeout, OLLAMA_SYSTEM_PROMPT, user_prompt)
```

Internally that POSTs to `<ollama_url>/api/chat` with `format=json` and `temperature=0`, `num_ctx=8192`. The format=json hint makes Ollama force JSON-shaped completion.

### `call_ollama_hybrid(row, model, ollama_url, timeout)` (lines 434-490)

1. Run `call_rules(row)` first to get a deterministic skeleton (job, risks, evidence, entities).
2. Show the model the rules output as ground truth. Ask only for `literal_request, actual_user_want, support_next_step, product_opportunity, user_emotion, manager_note_quality, needs_human_review, confidence`.
3. After receiving the model's narrative fields, validate with `narrative_quality_flag` (lines 414-424).
4. Only overwrite the rules result with model output for fields where:
   - the value is concrete (not snake_case, not in `GENERIC_PHRASES`, long enough);
   - enum values are in the allowed set;
   - confidence is bounded to [0,1].

This backend is more robust on small models because the deterministic skeleton catches the structure even if the model fields are garbage.

### `call_rules(row)` (lines 550-738)

Pure regex-based extraction. No model required. Determines:

- **Job to be done** by a priority cascade:
  1. Game complaint without ban → `fix_product_flow`
  2. `primary_desire == protect_from_abuse_or_scam` OR scam-report regex matches → `avoid_scam`
  3. Abuse-report regex matches → `protect_community`
  4. User-claim regex OR ban-state regex matches → `prove_innocence`
  5. Otherwise, the rule-based primary desire mapping (clear_name → prove_innocence, recover_access → recover_access, etc.)
  6. Falls through to `other`.

- **Emotion** by phrase matching: scam terms → `betrayed`; urgency words → `urgent`; user claim or "why" → `confused`; angry/insult words → `angry`; else `unknown`.

- **Evidence present** flags from the same regexes as Stage 1 plus user_claim.

- **Evidence missing** is conditional on detected state:
  - If ban detected: missing timestamp / ban reason text / user claim if any are absent.
  - If money or scam detected: missing amount, missing 2nd UID, missing screenshots/URLs.
  - If room reference but no room ID: missing room/group/channel ID.
  - If nothing missing: explicit `"none obvious from rules preview"`.

- **Risk levels** computed from feature counts:
  ```
  urgency_level = bounded_level(1 + len(URGENT)/2 + has_claim + has_scam)
  trust_risk = bounded_level(1 + 2*has_ban + 2*has_scam + has_status)
  money_risk = bounded_level(1 + 3*has_money + has_scam)
  safety_risk = bounded_level(1 + 3*has_pornographic_or_abuse_terms)
  ```
  `bounded_level` clamps to [1, 5].

- **Note quality** from context_depth_score: ≥60 forensic, ≥35 rich, else adequate.

- **`actual_user_want` and `support_next_step` and `product_opportunity`** come from a job-keyed dictionary of canonical phrases (lines 665-710). For example, `prove_innocence` always maps to:
  - actual: "User wants fairness, ban transparency, or an appeal path."
  - next_step: "Check ban history, reason, timestamp, room/user IDs, and compare against provided user claim/evidence."
  - product: "Expose ban reason, evidence summary, penalty timeline, and self-serve appeal requirements."

This is intentionally rigid: the rules backend is for sanity comparison, not nuanced output. Use it to verify whether the LLM is adding value over a hard-coded baseline.

## Validation pipeline

After every backend call:

1. **`normalize_result_enums(result)`** (lines 534-543): map known aliases to canonical enums:
   ```
   investigate_fraud   → avoid_scam
   report_fraud        → avoid_scam
   fraud_report        → avoid_scam
   verify_ban_and_reason → understand_punishment
   ban_verification    → understand_punishment
   unblock_account     → recover_access
   restore_account     → recover_access
   account_recovery    → recover_access
   stressed (emotion)  → anxious
   ```
   Records the original value in `_normalized_job_from` / `_normalized_emotion_from` for auditing.

2. **`output_quality_flag(result, expected_source_row)`** (lines 493-531): detects bad output. Returns one of:
   - `source_row_schema_echo` — the model returned the literal string "string" for source_row.
   - `source_row_mismatch` — the model returned a different source_row than the input.
   - `empty_required_fields` — any of the four narrative fields is empty.
   - `schema_echo` — output contains schema descriptors like "one of:", "short string", "what the user explicitly asked for".
   - `invalid_job` — `job_to_be_done` is not in `JOB_VALUES`.
   - `invalid_emotion` — `user_emotion` is not in `EMOTION_VALUES`.
   - `too_vague` — ≥2 narrative fields contain only generic phrases ("unknown", "investigate", "n/a", etc.).
   - `None` — passed validation.

3. **Status field added** to the result:
   - `_status = "ok"` if no quality flag,
   - `_status = "bad_output"` if quality flag,
   - `_status = "error"` if the backend itself raised.
   - Plus `_backend`, `_model` for provenance.

## Resume support

In `run_extraction` (lines 762-832):

```
output_path = run_dir / f"{output_stem}.jsonl"
if not resume and output_path.exists():
    output_path.unlink()
if resume and output_path.exists():
    done = {source_row of every line already in the file}
```

Then the loop skips any candidate already in `done`. The `output_stem` is `<backend>_<model_slug>_extractions` by default, so different backends and models do not overwrite each other.

After the loop, `pd.json_normalize(all_rows)` flattens nested entities into dotted-column form (e.g., `entities.uids`, `entities.url_count`) and writes both `<output_stem>.csv` and the stable aliases `<backend>_extractions.csv` and `llm_extractions.csv`.

## Output writes

For every run, regardless of dry-run:

- `llm_extraction_candidates.csv` — the 250 chosen tickets
- `llm_extraction_schema.json` — pretty-printed `SCHEMA`
- `llm_extraction_prompt.md` — Markdown with system prompt + a sample user prompt
- `llm_extraction_status.json` — backend, model, dry_run, count, error count

For non-dry runs:

- `<output_stem>.jsonl` and `<output_stem>.csv` — primary outputs
- `<backend>_extractions.jsonl` and `.csv` — stable aliases
- `llm_extractions.csv` — alias for the latest free/local run
- Updated `executive_findings.md` with "LLM Extraction Layer" section

## Command-line

```bash
python scripts/llm_extract_rich_tickets.py [run_dir] \
  [--outputs-dir outputs] \
  [--limit 250] \
  [--min-context-score 24.0] \
  [--strategy {highest_context,risk_balanced,issue_balanced}] \
  [--backend {rules,ollama,ollama_hybrid,openai}] \
  [--model mistral-small3.2:24b] \
  [--ollama-url http://localhost:11434] \
  [--timeout 180] \
  [--max-chars 6500] \
  [--sleep-seconds 0.05] \
  [--output-stem custom_name] \
  [--no-resume] \
  [--dry-run]
```

## Why this design

- **JSON mode** (`format=json` in Ollama, `response_format={"type": "json_object"}` in OpenAI) shrinks the failure surface to "model fields wrong" rather than "model output unparseable."
- **Deterministic rules baseline** lets us measure whether the LLM adds value over hand-coded extraction.
- **Hybrid backend** lets a weak local model contribute only to fields where its weakness is least costly (narrative interpretation), while rules handle structured fields.
- **Quality flags, not exceptions** preserve every output for inspection while telling consumers which rows to trust.
- **Stable aliases** (`llm_extractions.csv`, `ollama_extractions.csv`) keep dashboards working when we swap models.
- **Resume on `source_row`** means a crash mid-run does not waste compute.
