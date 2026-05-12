# 08 — Prompts and Extraction Layer

The exact text and rules used in Stage 5. Print this if someone wants to audit what the model was asked.

## Schema sent to the model

```json
{
  "source_row": "string",
  "literal_request": "short string: what the user explicitly asked for",
  "actual_user_want": "short string: deeper user want behind the request",
  "job_to_be_done": "one of: recover_access, prove_innocence, restore_income, grow_channel, avoid_scam, buy_or_sell_diamonds, gain_status, understand_punishment, restore_visibility, protect_community, fix_product_flow, customize_identity, other",
  "user_emotion": "one of: neutral, confused, anxious, angry, desperate, betrayed, urgent, hopeful, unknown",
  "urgency_level": "integer 1-5",
  "trust_risk_level": "integer 1-5",
  "money_risk_level": "integer 1-5",
  "safety_policy_risk_level": "integer 1-5",
  "evidence_present": ["screenshots", "urls", "timestamps", "uid", "room_or_group_id", "ban_reason", "money_amount", "counterparty", "user_claim", "none"],
  "evidence_missing": ["list of evidence needed to resolve or escalate safely"],
  "entities": {
    "uids": ["string"],
    "room_or_group_ids": ["string"],
    "timestamps": ["string"],
    "ban_reasons": ["string"],
    "money_or_diamond_amounts": ["string"],
    "counterparties": ["string"],
    "url_count": "integer"
  },
  "support_next_step": "specific next operational action",
  "product_opportunity": "what product/system should exist so user does not need to ask again",
  "manager_note_quality": "one of: thin, adequate, rich, forensic",
  "needs_human_review": "boolean",
  "confidence": "number 0-1"
}
```

## System prompts

### For OpenAI (full schema mode)

```
You are analyzing messy support tickets from IMO/BIGO-style support operations.
Extract what the user actually wants, not only the literal category.
Preserve uncertainty. Do not invent facts. If evidence is missing, say what is missing.
Treat screenshots/URLs/timestamps/ban reasons/IDs as evidence, not noise.
Return exactly one JSON object matching the requested schema. No markdown.
```

### For Ollama / Gemma (defensive)

```
You extract support-ticket meaning into JSON.
Infer the user's real goal from the ticket. Do not copy labels, enum lists, or template placeholders.
Write concrete short phrases, not enum tokens, for literal_request, actual_user_want, support_next_step, and product_opportunity.
If unsure, use "other", "unknown", empty lists, and lower confidence.
Return one valid JSON object only.
```

### For Hybrid (rules+model)

```
You write concise human interpretation fields for support-ticket analysis.
A deterministic rules layer already extracted IDs, evidence, risk levels, and job classification.
Do not reclassify the ticket. Do not invent facts. Use the supplied evidence and uncertainty.
Return one valid JSON object only.
```

## Per-ticket user prompt template

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

The Ollama backend then appends:

```

Fill the JSON template below with inferred values from the ticket.
Do not repeat the template placeholders. Do not output the enum lists.
literal_request: summarize what the user explicitly asks, in plain English.
actual_user_want: infer the outcome the user needs, in plain English.
support_next_step: write a concrete support action, starting with a verb.
product_opportunity: write a concrete product/system improvement; avoid just 'unknown'.
Do not use vague phrases like 'infer_goal', 'resolve issue', 'analyze', or just an enum token.
Use exactly one job_to_be_done token from: <JOB_VALUES>
Use exactly one user_emotion token from: <EMOTION_VALUES>
Use evidence_present values only from: <EVIDENCE_VALUES>
Use manager_note_quality from: <NOTE_QUALITY_VALUES>
Integer risk levels must be 1 to 5. confidence must be 0.0 to 1.0.
Return JSON only:
<TEMPLATE_JSON>
```

## Allowed enum values

```python
JOB_VALUES = [
    "recover_access", "prove_innocence", "restore_income", "grow_channel",
    "avoid_scam", "buy_or_sell_diamonds", "gain_status", "understand_punishment",
    "restore_visibility", "protect_community", "fix_product_flow",
    "customize_identity", "other",
]

EMOTION_VALUES = ["neutral", "confused", "anxious", "angry", "desperate",
                  "betrayed", "urgent", "hopeful", "unknown"]

EVIDENCE_VALUES = ["screenshots", "urls", "timestamps", "uid", "room_or_group_id",
                   "ban_reason", "money_amount", "counterparty", "user_claim", "none"]

NOTE_QUALITY_VALUES = ["thin", "adequate", "rich", "forensic"]
```

## Alias normalization

After every LLM call, `normalize_result_enums(result)` rewrites known aliases to canonical values.

| Model output | Canonical value | Source field |
|---|---|---|
| `investigate_fraud` | `avoid_scam` | job_to_be_done |
| `report_fraud` | `avoid_scam` | job_to_be_done |
| `fraud_report` | `avoid_scam` | job_to_be_done |
| `verify_ban_and_reason` | `understand_punishment` | job_to_be_done |
| `ban_verification` | `understand_punishment` | job_to_be_done |
| `unblock_account` | `recover_access` | job_to_be_done |
| `restore_account` | `recover_access` | job_to_be_done |
| `account_recovery` | `recover_access` | job_to_be_done |
| `stressed` | `anxious` | user_emotion |

The original value is preserved in `_normalized_job_from` / `_normalized_emotion_from`.

## Quality flags

`output_quality_flag(result, expected_source_row)` returns one of these or `None`:

| Flag | Trigger |
|---|---|
| `source_row_schema_echo` | `source_row` value is empty or literally `"string"` |
| `source_row_mismatch` | model returned a different source_row |
| `empty_required_fields` | any of `literal_request, actual_user_want, support_next_step, product_opportunity` is blank |
| `schema_echo` | output text contains schema descriptors like `"one of:"`, `"short string"`, `"what the user explicitly asked for"`, etc. |
| `invalid_job` | `job_to_be_done` not in `JOB_VALUES` |
| `invalid_emotion` | `user_emotion` not in `EMOTION_VALUES` |
| `too_vague` | ≥2 narrative fields contain only generic phrases (unknown, investigate, n/a, ...) |

## Status values

Each result has `_status`:

- `ok` — passed validation
- `bad_output` — failed validation (sets `_quality_flag`)
- `error` — backend itself raised (sets `_error`)

## Hybrid extraction details

`call_ollama_hybrid(row, model, ...)` (lines 434-490):

1. Run `call_rules(row)` first → deterministic skeleton.
2. Send the rules snapshot to the model (`job_to_be_done`, risk levels, evidence, entities).
3. Ask only for narrative fields + emotion + note_quality + needs_human_review + confidence.
4. After receiving the model output, call `narrative_quality_flag(update)` to check if the narrative fields are non-empty, concrete (not snake_case, not in `GENERIC_PHRASES`), and pass length thresholds.
5. Merge: only overwrite the rules result with model output where the model field passed validation.

`is_concrete_phrase(value, field)` rules:

- Empty / shorter than 8 characters → not concrete.
- Contains `_` or matches `SNAKE_TOKEN_RE` → not concrete (looks like a snake_case identifier).
- Lowercased value in `GENERIC_PHRASES` → not concrete.
- Field-specific minimums:
  - `support_next_step` < 24 chars → not concrete.
  - `product_opportunity` < 36 chars OR missing any product-language term ("system", "workflow", "form", "tool", "appeal", etc.) → not concrete.

## Generic phrases blacklist

```python
GENERIC_PHRASES = {
    "unknown", "infer goal", "resolve issue", "analyze", "investigate", "n/a",
    "none", "fix issue", "block user", "unblock user", "account restored",
    "ban audit", "ban verification", "ban resolution",
    "improve user experience", "improve dispute resolution process",
    "review rule layer and data integrity",
}
```

These are the phrases small models default to when they fail to extract anything specific. Catching them prevents downstream consumers from treating "investigate" as a real next-step recommendation.

## Sample real per-ticket prompt

See [llm_extraction_prompt.md](../../outputs/option2_20260502_150055/llm_extraction_prompt.md) for the version generated during the latest run with one actual ticket as the user-prompt example.
