# 11 - RunPod Mistral 1400 Runbook

This is the full operational runbook for running the management-quality local
LLM extraction on RunPod.

Use this when you want to run the project yourself without asking what to do
next. It includes what to do, why each step exists, when it matters, and how to
recover from the problems we already hit.

## What This Run Does

The goal is not just "run a model." The goal is:

1. Prepare and embed the full ticket export.
2. Ask Mistral Small 3.2 24B to deeply read the high-signal tickets.
3. Build the `What Users Want` taxonomy from those LLM-read tickets.
4. Label the wants in human language.
5. Project all analysis-ready support records onto the discovered wants.
6. Build the longitudinal layer: monthly trend, early warning, and repeat-user
   journeys.
7. Download the results.
8. Terminate the pod and delete leftover volumes.

Expected scale:

- Source rows: about `6,728`
- Analysis-ready support records: about `6,702`
- High-signal LLM candidates: about `1,348`
- The command says `--limit 1400`, but the script will only process the
  eligible high-signal tickets it can find. Seeing `candidates: 1348` is normal.
- Optional full AI census: about `6,681` useful non-empty support records.

## Cost Mental Model

You are paying RunPod for time while the pod is running and, separately, for
persistent storage if any network volumes remain.

Important:

- Running pod = GPU/compute billing.
- Stopped pod with network volume = storage billing can continue.
- Downloading packages/models is not a paid API call, but the pod is still on
  the clock while downloads happen.
- Ollama/Mistral here is local inference. Ticket text does not go to Mistral's
  API.

When you are finished and have downloaded the result archive, terminate the pod
and delete unused network volumes.

## Before You Deploy

You need:

- RunPod credits.
- A GPU with at least 24 GB VRAM. RTX 4090 is fine.
- The latest GitHub repo pushed.
- `data_2may.csv` available to upload.
- No need for SSH key if you use Web Terminal or JupyterLab terminal.

Recommended pod shape:

- GPU: `RTX 4090`
- Template: RunPod PyTorch is fine.
- Storage: avoid persistent network volumes unless you intentionally need them.
- Access: Web Terminal or JupyterLab.

Why no network volume by default: it can stay behind after you terminate the
pod and keep charging. We download the final archive instead.

## Step 1 - Open Terminal

In RunPod, open the pod's **Connect** tab.

Use either:

- **Web terminal**, or
- **Jupyter Lab -> Terminal**

You do not need SSH. The SSH warning panel is not a blocker.

Your prompt will look like this:

```bash
root@some-container:/#
```

That means you are typing inside the remote RunPod machine, not on your laptop.

## Step 2 - Clone The Latest Code

Run this inside the RunPod terminal:

```bash
cd /workspace
git clone https://github.com/alikatgh/whats-users-want.git
cd whats-users-want
git pull
```

Why:

- `git clone` downloads the project.
- `git pull` makes sure you have the newest scripts, including status counts
  and full-corpus projection.

If `git clone` asks for GitHub username/password, stop. You are probably using a
private URL or the repo permissions changed. Public HTTPS clone should not ask.

## Step 3 - Create Python Environment

Run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Why:

- The pipeline scripts need pandas, PyTorch, sentence-transformers, BERTopic,
  Streamlit, and other Python packages.
- RunPod's base image has Python, but not necessarily this project's packages.

Verify:

```bash
python - <<'PY'
import pandas, torch
print("pandas ok", pandas.__version__)
print("torch cuda available:", torch.cuda.is_available())
PY
```

Expected:

```text
pandas ok ...
torch cuda available: True
```

If you see `ModuleNotFoundError: No module named 'pandas'`, the requirements
were not installed in the active venv. Run the pip install commands again.

## Step 4 - Upload The CSV

Upload `data_2may.csv` into:

```text
/workspace/whats-users-want/data_2may.csv
```

Verify from the repo folder:

```bash
ls -lh data_2may.csv
```

Expected: a file around `1.5M`.

If it says "No such file", do not continue. The pipeline cannot run without the
CSV.

## Step 5 - Install And Start Ollama

Run:

```bash
curl -fsSL https://ollama.com/install.sh | sh
export PATH=/usr/local/bin:$PATH
which ollama
```

Expected:

```text
/usr/local/bin/ollama
```

Warnings you can ignore:

- `systemd is not running`
- `Unable to detect NVIDIA/AMD GPU`

Those warnings happened in our pod too. The real test is `nvidia-smi` and
whether Ollama can answer.

Start the local Ollama server:

```bash
ollama serve > ollama.log 2>&1 &
sleep 5
curl http://127.0.0.1:11434/api/tags
```

Expected before any model is pulled:

```json
{"models":[]}
```

If you get `Connection refused`, Ollama server is not running. Start it again:

```bash
ollama serve > ollama.log 2>&1 &
sleep 5
```

## Step 6 - Pull And Test Mistral

Download the model:

```bash
ollama pull mistral-small3.2:24b
```

This is around 15 GB. It can take several minutes.

Verify GPU and model:

```bash
nvidia-smi
ollama run mistral-small3.2:24b "Reply with exactly: GPU ready"
```

Expected:

```text
GPU ready
```

Why this matters:

- `nvidia-smi` proves the pod sees the RTX 4090.
- The Ollama prompt proves the model is downloaded and the server is alive.

If `ollama: command not found`, Ollama is not installed or not on `PATH`.

Fix:

```bash
export PATH=/usr/local/bin:$PATH
which ollama
```

If still missing, reinstall Ollama.

## Step 7 - Run The Base Pipeline

Make sure you are in the repo folder and venv:

```bash
cd /workspace/whats-users-want
source .venv/bin/activate
```

Run:

```bash
python scripts/option2_pipeline.py \
  --input data_2may.csv \
  --embedding-backend local \
  --embedding-model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

What this does:

- cleans the CSV,
- drops summary rows,
- embeds the tickets,
- clusters semantic topics,
- writes the run folder under `outputs/`.

Normal output includes:

```text
[info] Dropped 2 colleague pivot/cohort columns...
[info] Dropped 26 summary/aggregation rows...
Warning: You are sending unauthenticated requests to the HF Hub...
Batches: 100% ...
```

The Hugging Face warning is not an error. It only means no HF token is set.

Capture the run directory:

```bash
RUN_DIR=$(ls -td outputs/option2_* | head -1)
export RUN_DIR
echo "$RUN_DIR"
```

Expected:

```text
outputs/option2_YYYYMMDD_HHMMSS
```

Why `export RUN_DIR`: monitoring commands in a second terminal can use it.

## Step 8 - Smoke Test 3 Tickets

Never start the big extraction until this passes.

Run:

```bash
python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend ollama \
  --model mistral-small3.2:24b \
  --limit 3 \
  --strategy risk_balanced \
  --output-stem smoke_mistral_3 \
  --no-resume
```

Expected:

```json
{
  "candidates": 3,
  "extractions_rows": 3,
  "ok_rows": 3,
  "bad_output_rows": 0,
  "error_rows": 0
}
```

Why:

- This catches missing Ollama, missing Python dependencies, and schema issues
  before wasting time.
- Use `--no-resume` only for smoke tests where you intentionally overwrite the
  small test output.

If the smoke test fails with `Connection refused`, Ollama is not running:

```bash
ollama serve > ollama.log 2>&1 &
sleep 5
curl http://127.0.0.1:11434/api/tags
```

If it fails with `ModuleNotFoundError`, install requirements in the active venv.

## Step 9 - Move Smoke Outputs Away

The smoke test creates aliases like `ollama_extractions.csv` and
`llm_extractions.csv`. Move them away before the full run so taxonomy does not
accidentally read the 3-row smoke output.

Run:

```bash
mkdir -p "$RUN_DIR/smoke_test_outputs"
mv "$RUN_DIR"/smoke_mistral_3.* "$RUN_DIR"/smoke_test_outputs/ 2>/dev/null
mv "$RUN_DIR"/ollama_extractions.* "$RUN_DIR"/smoke_test_outputs/ 2>/dev/null
mv "$RUN_DIR"/llm_extractions.csv "$RUN_DIR"/smoke_test_outputs/ 2>/dev/null
```

Check:

```bash
ls "$RUN_DIR"/*mistral-small3.2-24b_extractions* "$RUN_DIR"/ollama_extractions.* "$RUN_DIR"/llm_extractions.csv 2>/dev/null
```

It should print nothing before the full run starts.

## Step 10 - Run The Real High-Signal Extraction

Run:

```bash
python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend ollama \
  --model mistral-small3.2:24b \
  --limit 1400 \
  --strategy risk_balanced
```

Expected candidate count:

```json
"candidates": 1348
```

That is normal. The dataset has about 1,348 tickets that pass the current
high-signal filter (`context_depth_score >= 24` and enough text).

Important:

- Do not use `--no-resume` for the full run.
- If the run crashes halfway, rerun the same command. It will skip completed
  `source_row` values in the JSONL file and continue.
- If it finishes in 1-3 minutes, something is wrong. A real 1,348-ticket
  Mistral run should take real time.

## Step 11 - Monitor Progress

Open a second Web Terminal tab in RunPod. In that tab:

```bash
cd /workspace/whats-users-want
source .venv/bin/activate
RUN_DIR=$(ls -td outputs/option2_* | head -1)
export RUN_DIR
```

Then watch:

```bash
watch -n 10 'wc -l "$RUN_DIR"/ollama_mistral-small3.2-24b_extractions.jsonl 2>/dev/null; nvidia-smi'
```

What to look for:

- JSONL line count increasing.
- GPU memory in use.
- GPU utilization above idle while the model is thinking.

If JSONL count is frozen for a long time, check `ollama.log`:

```bash
tail -100 ollama.log
```

## Step 12 - Validate The Extraction

When the extraction command finishes, it prints status JSON.

Good output looks like:

```json
{
  "candidates": 1348,
  "extractions_rows": 1348,
  "ok_rows": 1348,
  "bad_output_rows": 0,
  "error_rows": 0
}
```

Some `bad_output_rows` can be acceptable if small. Large `error_rows` are not.

Run this check:

```bash
python - "$RUN_DIR" <<'PY'
import sys
import pandas as pd
from pathlib import Path

run = Path(sys.argv[1])
df = pd.read_csv(run / "ollama_mistral-small3.2-24b_extractions.csv")
print(df["_status"].value_counts(dropna=False))

cols = ["source_row", "_status"]
for c in ["_error", "_quality_flag", "actual_user_want"]:
    if c in df.columns:
        cols.append(c)
print(df[cols].head(20).to_string(index=False))
PY
```

If you see mostly `error` with:

```text
Connection refused
```

then Ollama was not running. Move the bad files away, start Ollama, smoke test,
then rerun.

Recovery:

```bash
mkdir -p "$RUN_DIR/bad_fast_extraction"
mv "$RUN_DIR"/ollama_mistral-small3.2-24b_extractions.* "$RUN_DIR"/bad_fast_extraction/ 2>/dev/null
mv "$RUN_DIR"/ollama_extractions.* "$RUN_DIR"/bad_fast_extraction/ 2>/dev/null
mv "$RUN_DIR"/llm_extractions.csv "$RUN_DIR"/bad_fast_extraction/ 2>/dev/null

ollama serve > ollama.log 2>&1 &
sleep 5
curl http://127.0.0.1:11434/api/tags
```

Then repeat smoke test and full extraction.

## Optional Step 12B - Spend Remaining Credits On A Full AI Census

Use this only after Step 12 shows the high-signal run is healthy, for example:

```json
"ok_rows": 1348,
"bad_output_rows": 0,
"error_rows": 0
```

Why:

- The `1,348` run is the strong evidence layer.
- The projection stage maps the rest with embeddings.
- If you still have RunPod credits and want the strongest possible readout,
  you can ask Mistral to read every useful non-empty support record too.

First, preview the queue:

```bash
python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend ollama \
  --model mistral-small3.2:24b \
  --limit 6702 \
  --min-context-score 0 \
  --min-text-chars 1 \
  --strategy risk_balanced \
  --dry-run
```

Expected useful candidate count is about `6,681`, not exactly `6,702`,
because a few records have effectively empty ticket text. Do not force empty
records through the model unless you have a specific reason; they cannot add
meaningful evidence.

Then run it for real:

```bash
python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend ollama \
  --model mistral-small3.2:24b \
  --limit 6702 \
  --min-context-score 0 \
  --min-text-chars 1 \
  --strategy risk_balanced \
  --timeout 240
```

Important:

- Do **not** add `--no-resume`.
- The script will reuse the existing
  `ollama_mistral-small3.2-24b_extractions.jsonl`.
- It will skip the `1,348` source rows already read and continue with the
  remaining useful records.
- This may take several more hours. At roughly `$0.70/hour`, that is still
  usually cheaper than buying a large hosted API run, but watch the clock.

Monitor it:

```bash
watch -n 30 'wc -l "$RUN_DIR"/ollama_mistral-small3.2-24b_extractions.jsonl 2>/dev/null; nvidia-smi'
```

When it finishes, good output should have `ok_rows` close to the useful
candidate count and `error_rows: 0`. After this optional step, continue to
Step 13 and rebuild the taxonomy from the larger AI-read file.

## Step 13 - Build The Taxonomy

After extraction is valid:

```bash
python scripts/build_user_wants_taxonomy.py "$RUN_DIR"
```

What this does:

- reads the Mistral extraction CSV,
- embeds the extracted want text,
- clusters the wants,
- writes the taxonomy/workbook/findings.

Expected outputs:

- `user_wants_taxonomy.csv`
- `user_wants_assignments.csv`
- `user_wants_workbook.xlsx`
- `user_wants_findings.md`
- `user_wants_metadata.json`

## Step 14 - Generate Human-Friendly Labels

Run:

```bash
python scripts/label_user_wants.py "$RUN_DIR" --model mistral-small3.2:24b
```

Why:

- The taxonomy labels from clustering can be mechanically correct but ugly.
- This script asks the local model to create management-friendly titles and
  one-sentence summaries for each cluster.

Expected output:

- `user_wants_human_labels.csv`

If this step fails, the dashboard still works, but titles may look more
machine-generated.

## Step 15 - Project All Tickets To The Wants

Run:

```bash
python scripts/project_user_wants_full_corpus.py "$RUN_DIR"
```

What this does:

- keeps the Mistral-read tickets as confirmed evidence,
- maps the full analysis-ready corpus to those wants using cached embeddings,
- marks weak or ambiguous rows for review.

Expected output:

```json
{
  "source_rows": 6702,
  "llm_confirmed_rows": 1348,
  "projected_rows": 5354,
  "wants": ...
}
```

Exact numbers may vary depending on the taxonomy.

Expected files:

- `user_wants_all_assignments.csv`
- `user_wants_full_corpus_summary.csv`
- `user_wants_review_queue.csv`
- `user_wants_full_corpus_workbook.xlsx`
- `user_wants_projection_metadata.json`

## Step 16 - Build Timeline And User-Journey Insights

Run:

```bash
python scripts/build_longitudinal_insights.py "$RUN_DIR"
```

Why:

- A want-count bar chart is not enough for management.
- This stage shows what changed month by month.
- It creates a simple next-month early warning score.
- It finds repeated-user journeys: the same UID returning across days or months
  with multiple problems, statuses, managers, and wants.
- It creates archetypes like account recovery loops, safety reporters, money /
  dealer disputes, creator/group operators, and multi-problem power users.

Expected files:

- `longitudinal_want_monthly_trends.csv`
- `longitudinal_emerging_wants.csv`
- `longitudinal_user_journeys.csv`
- `longitudinal_user_journey_events.csv`
- `longitudinal_journey_archetypes.csv`
- `longitudinal_findings.md`
- `longitudinal_metadata.json`

This is the layer to show when someone asks why this is more than a spreadsheet
pivot table.

## Step 17 - Package Results

Create one archive:

```bash
tar -czf runpod_1400_results.tar.gz "$RUN_DIR"
ls -lh runpod_1400_results.tar.gz
```

Download `runpod_1400_results.tar.gz` through JupyterLab or RunPod file tools.

Why:

- One archive is harder to miss than dozens of CSV/XLSX/JSON files.
- You can extract it locally into the repo's `outputs/` folder.

## Step 18 - Stop Billing

Only after the archive is downloaded:

1. Stop or terminate the pod.
2. Go to **Storage**.
3. Delete unused network volumes.
4. Check there are no old `straight_*_volume` or similar 50 GB volumes left.

This matters. We already saw RunPod leave many unused 50 GB network volumes
behind. Those can keep billing even after the pod is stopped.

## Fast Failure Reference

### `ollama: command not found`

Cause: Ollama is not installed or `/usr/local/bin` is not on `PATH`.

Fix:

```bash
curl -fsSL https://ollama.com/install.sh | sh
export PATH=/usr/local/bin:$PATH
which ollama
```

### `Connection refused` from Ollama

Cause: Ollama binary exists, but the server is not running.

Fix:

```bash
ollama serve > ollama.log 2>&1 &
sleep 5
curl http://127.0.0.1:11434/api/tags
```

### Full extraction finishes instantly

Cause: usually every row failed fast, often because Ollama was not running.

Check:

```bash
python - "$RUN_DIR" <<'PY'
import sys, pandas as pd
from pathlib import Path
run = Path(sys.argv[1])
df = pd.read_csv(run / "ollama_mistral-small3.2-24b_extractions.csv")
print(df["_status"].value_counts(dropna=False))
print(df[[c for c in ["source_row", "_status", "_error"] if c in df.columns]].head(20).to_string(index=False))
PY
```

If mostly `error`, move bad files away and rerun after a clean smoke test.

### `ModuleNotFoundError: No module named 'pandas'`

Cause: Python dependencies are not installed in the active venv.

Fix:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Smoke output pollutes main aliases

Cause: smoke test writes `ollama_extractions.csv` and `llm_extractions.csv`.

Fix before full run:

```bash
mkdir -p "$RUN_DIR/smoke_test_outputs"
mv "$RUN_DIR"/smoke_mistral_3.* "$RUN_DIR"/smoke_test_outputs/ 2>/dev/null
mv "$RUN_DIR"/ollama_extractions.* "$RUN_DIR"/smoke_test_outputs/ 2>/dev/null
mv "$RUN_DIR"/llm_extractions.csv "$RUN_DIR"/smoke_test_outputs/ 2>/dev/null
```

### Hugging Face warning

Message:

```text
Warning: You are sending unauthenticated requests to the HF Hub.
```

Meaning: normal. The embedding model is being downloaded without an HF token.
It worked for us. No action needed unless downloads are rate-limited.

## The Short Version

Only use this after you understand the full runbook above:

```bash
cd /workspace
git clone https://github.com/alikatgh/whats-users-want.git
cd whats-users-want
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt

# upload data_2may.csv here
ls -lh data_2may.csv

curl -fsSL https://ollama.com/install.sh | sh
export PATH=/usr/local/bin:$PATH
ollama serve > ollama.log 2>&1 &
sleep 5
ollama pull mistral-small3.2:24b
ollama run mistral-small3.2:24b "Reply with exactly: GPU ready"

python scripts/option2_pipeline.py \
  --input data_2may.csv \
  --embedding-backend local \
  --embedding-model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

RUN_DIR=$(ls -td outputs/option2_* | head -1)
export RUN_DIR

python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend ollama \
  --model mistral-small3.2:24b \
  --limit 3 \
  --strategy risk_balanced \
  --output-stem smoke_mistral_3 \
  --no-resume

mkdir -p "$RUN_DIR/smoke_test_outputs"
mv "$RUN_DIR"/smoke_mistral_3.* "$RUN_DIR"/smoke_test_outputs/ 2>/dev/null
mv "$RUN_DIR"/ollama_extractions.* "$RUN_DIR"/smoke_test_outputs/ 2>/dev/null
mv "$RUN_DIR"/llm_extractions.csv "$RUN_DIR"/smoke_test_outputs/ 2>/dev/null

python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend ollama \
  --model mistral-small3.2:24b \
  --limit 1400 \
  --strategy risk_balanced

python scripts/build_user_wants_taxonomy.py "$RUN_DIR"
python scripts/label_user_wants.py "$RUN_DIR" --model mistral-small3.2:24b
python scripts/project_user_wants_full_corpus.py "$RUN_DIR"
python scripts/build_longitudinal_insights.py "$RUN_DIR"

tar -czf runpod_1400_results.tar.gz "$RUN_DIR"
ls -lh runpod_1400_results.tar.gz
```
