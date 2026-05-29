# 13 — DeepSeek V4 Full-Corpus Census (runbook)

**Status: prepared, not yet run.** The code path is wired (`--backend deepseek`);
this is the operating plan for when you run it. Prepared 2026-05-29.

## Goal

Read **every useful ticket (~6,702)** through **DeepSeek V4** — not the 1,348-ticket
high-signal subset the current run used. This removes the `risk_balanced` sampling
bias (limitation #1 in `docs/09-limitations.md`) and produces a full-coverage want
taxonomy + longitudinal layer on the strongest model used on this project so far.

## What was wired in the code (2026-05-29)

`scripts/llm_extract_rich_tickets.py` now supports OpenAI-compatible endpoints:

- a **`deepseek` backend** (`--backend deepseek`) — defaults the API base URL to
  `https://api.deepseek.com` and reads `DEEPSEEK_API_KEY` (falling back to `OPENAI_API_KEY`);
- a generic **`--base-url`** flag (or `$OPENAI_BASE_URL`) for any OpenAI-compatible host;
- a **JSON-mode fallback**: if the endpoint rejects `response_format=json_object` (some
  reasoning models do), it retries prompt-only and extracts the JSON via `parse_json_object`;
- deepseek output is aliased to **`llm_extractions.csv`** so `build_user_wants_taxonomy.py`
  picks it up with no extra flags.

DeepSeek speaks the OpenAI protocol, so no SDK beyond `openai` is needed.

## ⚠️ Decision before you run: cost + privacy

This is the **first path that sends ticket text off the machine**, so it changes the
project's posture:

- **Privacy.** Every ticket body goes to DeepSeek's API (a third party). This breaks the
  "no ticket text leaves the machine" claim and the `AGENTS.md` privacy guardrail. If
  privacy must hold, **self-host** DeepSeek V4 on a large multi-GPU instance (far bigger
  than the RTX 4090 used for Mistral) and point `--base-url` at it.
- **Cost.** Paid API. At DeepSeek V3-class pricing a ~6,702-ticket census is roughly
  single-digit dollars — **confirm V4 pricing first.** This breaks the "0 paid API calls" claim.
- Once this becomes the current run, update the framing in `docs/05-findings.md`,
  `docs/07-presenter-script.md`, and `docs/09-limitations.md` (and re-point
  `docs/engineering/DOC_RECONCILIATION.md`).

## Setup

```bash
export DEEPSEEK_API_KEY=...        # or export OPENAI_API_KEY=<deepseek key>
# --backend deepseek defaults --base-url to https://api.deepseek.com
# model id: check DeepSeek's docs for V4 (e.g. "deepseek-chat"); a chat model
# supports JSON mode; a reasoner model triggers the prompt-only fallback automatically.
```

Pick the run directory (reuse an existing one with cached embeddings, or make a fresh
base run first via `docs/11-runpod-mistral-runbook.md` Step 7):

```bash
RUN_DIR=$(ls -td outputs/option2_* | head -1); export RUN_DIR
```

## Step 1 — smoke test (3 tickets) — always first

```bash
.venv/bin/python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend deepseek --model <deepseek-v4-model-id> \
  --limit 3 --strategy risk_balanced --output-stem smoke_deepseek_3 --no-resume
```

Expect `candidates: 3, ok_rows: 3, bad_output_rows: 0, error_rows: 0`. Then move the
smoke aliases aside before the full run (as in the Mistral runbook Step 9):

```bash
mkdir -p "$RUN_DIR/smoke_test_outputs"
mv "$RUN_DIR"/smoke_deepseek_3.* "$RUN_DIR"/smoke_test_outputs/ 2>/dev/null
mv "$RUN_DIR"/llm_extractions.csv "$RUN_DIR"/smoke_test_outputs/ 2>/dev/null
```

## Step 2 — full census

```bash
.venv/bin/python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend deepseek --model <deepseek-v4-model-id> \
  --limit 6702 --min-context-score 0 --min-text-chars 1 \
  --strategy risk_balanced --timeout 240
```

- **Resumable.** Rerun the same command to continue — it skips already-processed
  `source_row` values in the JSONL. **Do not** pass `--no-resume`.
- Expect ~6,681 useful candidates (a few rows are effectively empty text).

## Step 3 — downstream stages (unchanged)

```bash
.venv/bin/python scripts/build_user_wants_taxonomy.py "$RUN_DIR"
.venv/bin/python scripts/label_user_wants.py "$RUN_DIR" --model mistral-small3.2:24b   # labels can stay on a local model — no privacy cost
.venv/bin/python scripts/project_user_wants_full_corpus.py "$RUN_DIR"
.venv/bin/python scripts/build_longitudinal_insights.py "$RUN_DIR"
```

With a full census, `project_user_wants_full_corpus.py`'s `llm_confirmed_rows`
approaches the whole corpus and the embedding-projection step becomes a thin top-up
rather than the bulk of the assignments.

## Step 4 — validate

Read the printed status JSON: `ok_rows` should be near the candidate count and
`error_rows: 0`. If you see mostly `error` with auth/connection messages, the API key
or base URL is wrong (see the Mistral runbook's "Validate the extraction" recovery).

## After it runs

This becomes the new **current** want layer. Reconcile the docs again — the canonical
numbers in `docs/engineering/DOC_RECONCILIATION.md` and the gold reference
`docs/05-findings.md` — pointing the want layer at the new run directory, and revisit
the privacy/cost framing flagged above.
